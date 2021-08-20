# Copyright (C) 2005-2010 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Blackbox tests for version_info"""

import os

from breezy.tests import TestCaseWithTransport
from breezy.version_info_formats import VersionInfoBuilder


class TestVersionInfo(TestCaseWithTransport):

    def test_invalid_format(self):
        self.run_bzr('version-info --format quijibo', retcode=3)

    def create_tree(self):
        wt = self.make_branch_and_tree('branch')

        self.build_tree(['branch/a'])
        wt.add('a')
        wt.commit('adding a', rev_id=b'r1')

        self.build_tree(['branch/b'])
        wt.add('b')
        wt.commit('adding b', rev_id=b'r2')
        return wt

    def test_basic(self):
        wt = self.create_tree()

        txt = self.run_bzr('version-info branch')[0]
        self.assertContainsRe(txt, 'date:')
        self.assertContainsRe(txt, 'build-date:')
        self.assertContainsRe(txt, 'revno: 2')
        self.assertContainsRe(txt, 'revision-id: ' +
                              wt.branch.last_revision().decode('utf-8'))

    def test_all(self):
        """'--all' includes clean, revision history, and file revisions"""
        wt = self.create_tree()
        txt = self.run_bzr('version-info branch --all')[0]
        self.assertContainsRe(txt, 'date:')
        self.assertContainsRe(txt, 'revno: 2')
        self.assertContainsRe(txt, 'revision-id: ' +
                              wt.branch.last_revision().decode('utf-8'))
        self.assertContainsRe(txt, 'clean: True')
        self.assertContainsRe(txt, 'revisions:')
        for rev_id in wt.branch.repository.all_revision_ids():
            self.assertContainsRe(txt, 'id: ' + rev_id.decode('utf-8'))
        self.assertContainsRe(txt, 'message: adding a')
        self.assertContainsRe(txt, 'message: adding b')
        self.assertContainsRe(txt, 'file-revisions:')
        self.assertContainsRe(txt, 'path: a')
        self.assertContainsRe(txt, 'path: b')

    def test_clean(self):
        """Test that --check-clean includes the right info"""
        self.create_tree()

        txt = self.run_bzr('version-info branch --check-clean')[0]
        self.assertContainsRe(txt, 'clean: True')

        self.build_tree_contents([('branch/c', b'now unclean\n')])
        txt = self.run_bzr('version-info branch --check-clean')[0]
        self.assertContainsRe(txt, 'clean: False')

        txt = self.run_bzr('version-info branch --check-clean'
                           ' --include-file-revisions')[0]
        self.assertContainsRe(txt, 'revision: unversioned')

        os.remove('branch/c')

    def test_no_working_tree(self):
        tree = self.create_tree()
        branch = self.make_branch('just_branch')
        branch.pull(tree.branch)

        txt = self.run_bzr('version-info just_branch')[0]
        self.assertStartsWith(txt, 'revision-id: r2\n')

    def assertEqualNoBuildDate(self, text1, text2):
        """Compare 2 texts, but ignore the build-date field.

        build-date is the current timestamp, accurate to seconds. But the
        clock is always ticking, and it may have ticked between the time
        that text1 and text2 were generated.
        """
        lines1 = text1.splitlines(True)
        lines2 = text2.splitlines(True)
        for line1, line2 in zip(lines1, lines2):
            if line1.startswith('build-date: '):
                self.assertStartsWith(line2, 'build-date: ')
            else:
                self.assertEqual(line1, line2)
        self.assertEqual(len(lines1), len(lines2))

    def test_no_branch(self):
        """Test that brz defaults to the local working directory"""
        self.create_tree()

        txt1 = self.run_bzr('version-info branch')[0]

        os.chdir('branch')
        txt2 = self.run_bzr('version-info')[0]
        self.assertEqualNoBuildDate(txt1, txt2)

    def test_rio(self):
        """Test that we can pass --format=rio"""
        self.create_tree()

        txt = self.run_bzr('version-info branch')[0]
        txt1 = self.run_bzr('version-info --format rio branch')[0]
        txt2 = self.run_bzr('version-info --format=rio branch')[0]
        self.assertEqualNoBuildDate(txt, txt1)
        self.assertEqualNoBuildDate(txt, txt2)

    def test_python(self):
        """Test that we can do --format=python"""
        self.create_tree()

        txt = self.run_bzr('version-info --format python branch')[0]

        self.assertContainsRe(txt, 'version_info = {')

    def test_custom_without_template(self):
        wt = self.make_branch_and_tree('branch')
        out, err = self.run_bzr('version-info --custom', retcode=3)
        self.assertContainsRe(err, r'ERROR: No template specified\.')

    def test_custom_implies_all(self):
        self.create_tree()
        out, err = self.run_bzr('version-info --custom --template='
                                '"{revno} {branch_nick} {clean}\n" branch')
        self.assertEqual("2 branch 1\n", out)
        self.assertEqual("", err)
        self.build_tree_contents([('branch/c', b'now unclean\n')])
        out, err = self.run_bzr('version-info --custom --template='
                                '"{revno} {branch_nick} {clean}\n" branch')
        self.assertEqual("2 branch 0\n", out)
        self.assertEqual("", err)

    def test_custom_no_clean_in_template(self):
        def should_not_be_called(self):
            raise AssertionError(
                "Method on %r should not have been used" % (self,))
        self.overrideAttr(VersionInfoBuilder, "_extract_file_revisions",
                          should_not_be_called)
        self.create_tree()
        out, err = self.run_bzr(
            'version-info --custom --template=r{revno} branch')
        self.assertEqual("r2", out)
        self.assertEqual("", err)

    def test_non_ascii(self):
        """Test that we can output non-ascii data"""
        commit_message = u'Non-ascii message with character not in latin-1: \u1234'

        tree = self.make_branch_and_tree('.')
        self.build_tree(['a_file'])
        tree.add('a_file')
        tree.commit(commit_message)
        out, err = self.run_bzr_raw(
            ['version-info', '--include-history'], encoding='latin-1')

    def test_revision(self):
        tree = self.create_tree()
        branch = self.make_branch('just_branch')
        branch.pull(tree.branch)

        txt = self.run_bzr('version-info -r1 just_branch')[0]
        self.assertStartsWith(txt, 'revision-id: r1\n')

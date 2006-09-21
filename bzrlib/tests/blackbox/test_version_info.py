# Copyright (C) 2005, 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Blackbox tests for version_info"""

import imp
import os
import sys

from bzrlib.tests import TestCaseWithTransport


class TestVersionInfo(TestCaseWithTransport):

    def test_invalid_format(self):
        self.run_bzr('version-info', '--format', 'quijibo', retcode=3)

    def create_branch(self):
        wt = self.make_branch_and_tree('branch')

        self.build_tree(['branch/a'])
        wt.add('a')
        wt.commit('adding a', rev_id='r1')

        self.build_tree(['branch/b'])
        wt.add('b')
        wt.commit('adding b', rev_id='r2')

        self.revisions = wt.branch.revision_history()

    def test_basic(self):
        self.create_branch()

        txt = self.run_bzr('version-info', 'branch')[0]
        self.assertContainsRe(txt, 'date:')
        self.assertContainsRe(txt, 'build-date:')
        self.assertContainsRe(txt, 'revno: 2')
        self.assertContainsRe(txt, 'revision-id: ' + self.revisions[-1])

    def test_all(self):
        """'--all' includes clean, revision history, and file revisions"""
        self.create_branch()
        txt = self.run_bzr('version-info', 'branch',
                           '--all')[0]
        self.assertContainsRe(txt, 'date:')
        self.assertContainsRe(txt, 'revno: 2')
        self.assertContainsRe(txt, 'revision-id: ' + self.revisions[-1])
        self.assertContainsRe(txt, 'clean: True')
        self.assertContainsRe(txt, 'revisions:')
        for rev_id in self.revisions:
            self.assertContainsRe(txt, 'id: ' + rev_id)
        self.assertContainsRe(txt, 'message: adding a')
        self.assertContainsRe(txt, 'message: adding b')
        self.assertContainsRe(txt, 'file-revisions:')
        self.assertContainsRe(txt, 'path: a')
        self.assertContainsRe(txt, 'path: b')

    def test_clean(self):
        """Test that --check-clean includes the right info"""
        self.create_branch()

        txt = self.run_bzr('version-info', 'branch',
                           '--check-clean')[0]
        self.assertContainsRe(txt, 'clean: True')

        self.build_tree_contents([('branch/c', 'now unclean\n')])
        txt = self.run_bzr('version-info', 'branch',
                           '--check-clean')[0]
        self.assertContainsRe(txt, 'clean: False')

        txt = self.run_bzr('version-info', 'branch',
                           '--check-clean', '--include-file-revisions')[0]
        self.assertContainsRe(txt, 'revision: unversioned')

        os.remove('branch/c')

    def test_no_branch(self):
        """Test that bzr defaults to the local working directory"""
        self.create_branch()

        os.chdir('branch')
        txt = self.run_bzr('version-info')[0]

    def test_rio(self):
        """Test that we can pass --format=rio"""
        self.create_branch()

        txt = self.run_bzr('version-info', 'branch')[0]
        txt1 = self.run_bzr('version-info', '--format', 'rio', 'branch')[0]
        txt2 = self.run_bzr('version-info', '--format=rio', 'branch')[0]
        self.assertEqual(txt, txt1)
        self.assertEqual(txt, txt2)

    def test_python(self):
        """Test that we can do --format=python"""
        self.create_branch()

        txt = self.run_bzr('version-info', '--format', 'python', 'branch')[0]

        self.assertContainsRe(txt, 'revisions = {')

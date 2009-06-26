# Copyright (C) 2006, 2007, 2008, 2009 Canonical Ltd
# Authors: Aaron Bentley
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


import sys
from cStringIO import StringIO

from bzrlib import (
    branch,
    bzrdir,
    merge_directive,
    tests,
    )
from bzrlib.bundle import serializer


class TestSend(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestSend, self).setUp()
        grandparent_tree = bzrdir.BzrDir.create_standalone_workingtree(
            'grandparent')
        self.build_tree_contents([('grandparent/file1', 'grandparent')])
        grandparent_tree.add('file1')
        grandparent_tree.commit('initial commit', rev_id='rev1')

        parent_bzrdir = grandparent_tree.bzrdir.sprout('parent')
        parent_tree = parent_bzrdir.open_workingtree()
        parent_tree.commit('next commit', rev_id='rev2')

        branch_tree = parent_tree.bzrdir.sprout('branch').open_workingtree()
        self.build_tree_contents([('branch/file1', 'branch')])
        branch_tree.commit('last commit', rev_id='rev3')

    def run_send(self, args, cmd=None, rc=0, wd='branch'):
        if cmd is None:
            cmd = ['send', '-o-']
        return self.run_bzr(cmd + args, retcode=rc, working_dir=wd)

    def get_MD(self, args, cmd=None, wd='branch'):
        out = StringIO(self.run_send(args, cmd=cmd, wd=wd)[0])
        return merge_directive.MergeDirective.from_lines(out.readlines())

    def assertBundleContains(self, revs, args, cmd=None, wd='branch'):
        md = self.get_MD(args, cmd=cmd, wd=wd)
        br = serializer.read_bundle(StringIO(md.get_raw_bundle()))
        self.assertEqual(set(revs), set(r.revision_id for r in br.revisions))

    def assertFormatIs(self, fmt_string, md):
        self.assertEqual(fmt_string, md.get_raw_bundle().splitlines()[0])

    def test_uses_parent(self):
        """Parent location is used as a basis by default"""
        errmsg = self.run_send([], rc=3, wd='grandparent')[1]
        self.assertContainsRe(errmsg, 'No submit branch known or specified')
        stdout, stderr = self.run_send([])
        self.assertEqual(stderr.count('Using saved parent location'), 1)
        self.assertBundleContains(['rev3'], [])

    def test_bundle(self):
        """Bundle works like send, except -o is not required"""
        errmsg = self.run_send([], cmd=['bundle'], rc=3, wd='grandparent')[1]
        self.assertContainsRe(errmsg, 'No submit branch known or specified')
        stdout, stderr = self.run_send([], cmd=['bundle'])
        self.assertEqual(stderr.count('Using saved parent location'), 1)
        self.assertBundleContains(['rev3'], [], cmd=['bundle'])

    def test_uses_submit(self):
        """Submit location can be used and set"""
        self.assertBundleContains(['rev3'], [])
        self.assertBundleContains(['rev3', 'rev2'], ['../grandparent'])
        # submit location should be auto-remembered
        self.assertBundleContains(['rev3', 'rev2'], [])

        self.run_send(['../parent'])
        # We still point to ../grandparent
        self.assertBundleContains(['rev3', 'rev2'], [])
        # Remember parent now
        self.run_send(['../parent', '--remember'])
        # Now we point to parent
        self.assertBundleContains(['rev3'], [])

        err = self.run_send(['--remember'], rc=3)[1]
        self.assertContainsRe(err,
                              '--remember requires a branch to be specified.')

    def test_revision_branch_interaction(self):
        self.assertBundleContains(['rev3', 'rev2'], ['../grandparent'])
        self.assertBundleContains(['rev2'], ['../grandparent', '-r-2'])
        self.assertBundleContains(['rev3', 'rev2'],
                                  ['../grandparent', '-r-2..-1'])
        md = self.get_MD(['-r-2..-1'])
        self.assertEqual('rev2', md.base_revision_id)
        self.assertEqual('rev3', md.revision_id)

    def test_output(self):
        # check output for consistency
        # win32 stdout converts LF to CRLF,
        # which would break patch-based bundles
        self.assertBundleContains(['rev3'], [])

    def test_no_common_ancestor(self):
        foo = self.make_branch_and_tree('foo')
        foo.commit('rev a')
        bar = self.make_branch_and_tree('bar')
        bar.commit('rev b')
        self.run_send(['--from', 'foo', '../bar'], wd='foo')

    def test_content_options(self):
        """--no-patch and --no-bundle should work and be independant"""
        md = self.get_MD([])
        self.assertIsNot(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(['--format=0.9'])
        self.assertIsNot(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(['--no-patch'])
        self.assertIsNot(None, md.bundle)
        self.assertIs(None, md.patch)
        self.run_bzr_error(['Format 0.9 does not permit bundle with no patch'],
                           ['send', '--no-patch', '--format=0.9', '-o-'],
                           working_dir='branch')
        md = self.get_MD(['--no-bundle', '.', '.'])
        self.assertIs(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(['--no-bundle', '--format=0.9', '../parent',
                                  '.'])
        self.assertIs(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(['--no-bundle', '--no-patch', '.', '.'])
        self.assertIs(None, md.bundle)
        self.assertIs(None, md.patch)

        md = self.get_MD(['--no-bundle', '--no-patch', '--format=0.9',
                          '../parent', '.'])
        self.assertIs(None, md.bundle)
        self.assertIs(None, md.patch)

    def test_from_option(self):
        self.run_bzr('send', retcode=3)
        md = self.get_MD(['--from', 'branch'])
        self.assertEqual('rev3', md.revision_id)
        md = self.get_MD(['-f', 'branch'])
        self.assertEqual('rev3', md.revision_id)

    def test_output_option(self):
        stdout = self.run_bzr('send -f branch --output file1')[0]
        self.assertEqual('', stdout)
        md_file = open('file1', 'rb')
        self.addCleanup(md_file.close)
        self.assertContainsRe(md_file.read(), 'rev3')
        stdout = self.run_bzr('send -f branch --output -')[0]
        self.assertContainsRe(stdout, 'rev3')

    def test_note_revisions(self):
        stderr = self.run_send([])[1]
        self.assertEndsWith(stderr, '\nBundling 1 revision(s).\n')

    def test_mailto_option(self):
        b = branch.Branch.open('branch')
        b.get_config().set_user_option('mail_client', 'editor')
        self.run_bzr_error(
            ('No mail-to address \\(--mail-to\\) or output \\(-o\\) specified',
            ), 'send -f branch')
        b.get_config().set_user_option('mail_client', 'bogus')
        self.run_send([])
        self.run_bzr_error(('Unknown mail client: bogus',),
                           'send -f branch --mail-to jrandom@example.org')
        b.get_config().set_user_option('submit_to', 'jrandom@example.org')
        self.run_bzr_error(('Unknown mail client: bogus',),
                           'send -f branch')

    def test_mailto_child_option(self):
        """Make sure that child_submit_to is used."""
        b = branch.Branch.open('branch')
        b.get_config().set_user_option('mail_client', 'bogus')
        parent = branch.Branch.open('parent')
        parent.get_config().set_user_option('child_submit_to',
                           'somebody@example.org')
        self.run_bzr_error(('Unknown mail client: bogus',),
                           'send -f branch')

    def test_format(self):
        md = self.get_MD(['--format=4'])
        self.assertIs(merge_directive.MergeDirective2, md.__class__)
        self.assertFormatIs('# Bazaar revision bundle v4', md)

        md = self.get_MD(['--format=0.9'])
        self.assertFormatIs('# Bazaar revision bundle v0.9', md)

        md = self.get_MD(['--format=0.9'], cmd=['bundle'])
        self.assertFormatIs('# Bazaar revision bundle v0.9', md)
        self.assertIs(merge_directive.MergeDirective, md.__class__)

        self.run_bzr_error(['Bad value .* for option .format.'],
                            'send -f branch -o- --format=0.999')[0]

    def test_format_child_option(self):
        parent_config = branch.Branch.open('parent').get_config()
        parent_config.set_user_option('child_submit_format', '4')
        md = self.get_MD([])
        self.assertIs(merge_directive.MergeDirective2, md.__class__)

        parent_config.set_user_option('child_submit_format', '0.9')
        md = self.get_MD([])
        self.assertFormatIs('# Bazaar revision bundle v0.9', md)

        md = self.get_MD([], cmd=['bundle'])
        self.assertFormatIs('# Bazaar revision bundle v0.9', md)
        self.assertIs(merge_directive.MergeDirective, md.__class__)

        parent_config.set_user_option('child_submit_format', '0.999')
        self.run_bzr_error(["No such send format '0.999'"],
                            'send -f branch -o-')[0]

    def test_message_option(self):
        self.run_bzr('send', retcode=3)
        md = self.get_MD([])
        self.assertIs(None, md.message)
        md = self.get_MD(['-m', 'my message'])
        self.assertEqual('my message', md.message)

    def test_omitted_revision(self):
        md = self.get_MD(['-r-2..'])
        self.assertEqual('rev2', md.base_revision_id)
        self.assertEqual('rev3', md.revision_id)
        md = self.get_MD(['-r..3', '--from', 'branch', 'grandparent'], wd='.')
        self.assertEqual('rev1', md.base_revision_id)
        self.assertEqual('rev3', md.revision_id)

    def test_nonexistant_branch(self):
        if sys.platform == "win32":
            location = "C:/i/do/not/exist/"
        else:
            location = "/i/do/not/exist/"
        out, err = self.run_bzr(["send", "--from", location], retcode=3)
        self.assertEqual(out, '')
        self.assertEqual(err, 'bzr: ERROR: Not a branch: "%s".\n' % location)

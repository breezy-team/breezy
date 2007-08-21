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


"""Black-box tests for bzr diff.
"""

import os
import re

import bzrlib
from bzrlib import workingtree
from bzrlib.branch import Branch
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


def subst_dates(string):
    """Replace date strings with constant values."""
    return re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [-\+]\d{4}',
                  'YYYY-MM-DD HH:MM:SS +ZZZZ', string)


class DiffBase(ExternalBase):
    """Base class with common setup method"""

    def make_example_branch(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([
            ('hello',   'foo\n'),
            ('goodbye', 'baz\n')])
        tree.add(['hello'])
        tree.commit('setup')
        tree.add(['goodbye'])
        tree.commit('setup')
        return tree


class TestDiff(DiffBase):

    def test_diff(self):
        tree = self.make_example_branch()
        self.build_tree_contents([('hello', 'hello world!')])
        tree.commit(message='fixing hello')
        output = self.run_bzr('diff -r 2..3', retcode=1)[0]
        self.assert_('\n+hello world!' in output)
        output = self.run_bzr('diff -r last:3..last:1',
                retcode=1)[0]
        self.assert_('\n+baz' in output)
        self.build_tree(['moo'])
        tree.add('moo')
        os.unlink('moo')
        self.run_bzr('diff')

    def test_diff_prefix(self):
        """diff --prefix appends to filenames in output"""
        self.make_example_branch()
        self.build_tree_contents([('hello', 'hello world!\n')])
        out, err = self.run_bzr('diff --prefix old/:new/', retcode=1)
        self.assertEquals(err, '')
        self.assertEqualDiff(subst_dates(out), '''\
=== modified file 'hello'
--- old/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ new/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

''')

    def test_diff_illegal_prefix_value(self):
        # There was an error in error reporting for this option
        out, err = self.run_bzr('diff --prefix old/', retcode=3)
        self.assertContainsRe(err,
            '--prefix expects two values separated by a colon')

    def test_diff_p1(self):
        """diff -p1 produces lkml-style diffs"""
        self.make_example_branch()
        self.build_tree_contents([('hello', 'hello world!\n')])
        out, err = self.run_bzr('diff -p1', retcode=1)
        self.assertEquals(err, '')
        self.assertEqualDiff(subst_dates(out), '''\
=== modified file 'hello'
--- old/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ new/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

''')

    def test_diff_p0(self):
        """diff -p0 produces diffs with no prefix"""
        self.make_example_branch()
        self.build_tree_contents([('hello', 'hello world!\n')])
        out, err = self.run_bzr('diff -p0', retcode=1)
        self.assertEquals(err, '')
        self.assertEqualDiff(subst_dates(out), '''\
=== modified file 'hello'
--- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

''')

    def test_diff_nonexistent(self):
        # Get an error from a file that does not exist at all
        # (Malone #3619)
        self.make_example_branch()
        out, err = self.run_bzr('diff does-not-exist', retcode=3)
        self.assertContainsRe(err, 'not versioned.*does-not-exist')

    def test_diff_illegal_revision_specifiers(self):
        out, err = self.run_bzr('diff -r 1..23..123', retcode=3)
        self.assertContainsRe(err, 'one or two revision specifiers')

    def test_diff_unversioned(self):
        # Get an error when diffing a non-versioned file.
        # (Malone #3619)
        self.make_example_branch()
        self.build_tree(['unversioned-file'])
        out, err = self.run_bzr('diff unversioned-file', retcode=3)
        self.assertContainsRe(err, 'not versioned.*unversioned-file')

    # TODO: What should diff say for a file deleted in working tree?

    def example_branches(self):
        branch1_tree = self.make_branch_and_tree('branch1')
        self.build_tree(['branch1/file'], line_endings='binary')
        branch1_tree.add('file')
        branch1_tree.commit(message='add file')
        branch2_tree = branch1_tree.bzrdir.sprout('branch2').open_workingtree()
        self.build_tree_contents([('branch2/file', 'new content\n')])
        branch2_tree.commit(message='update file')
        return branch1_tree, branch2_tree

    def test_diff_branches(self):
        self.example_branches()
        # should open branch1 and diff against branch2, 
        out, err = self.run_bzr('diff -r branch:branch2 branch1',
                                retcode=1)
        self.assertEquals('', err)
        self.assertEquals("=== modified file 'file'\n"
                          "--- file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                          "+++ file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                          "@@ -1,1 +1,1 @@\n"
                          "-new content\n"
                          "+contents of branch1/file\n"
                          "\n", subst_dates(out))
        out, err = self.run_bzr('diff branch2 branch1',
                                         retcode=1)
        self.assertEquals('', err)
        self.assertEqualDiff("=== modified file 'file'\n"
                              "--- file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "+++ file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "@@ -1,1 +1,1 @@\n"
                              "-new content\n"
                              "+contents of branch1/file\n"
                              "\n", subst_dates(out))

    def test_diff_revno_branches(self):
        self.example_branches()
        branch2_tree = workingtree.WorkingTree.open_containing('branch2')[0]
        self.build_tree_contents([('branch2/file', 'even newer content')])
        branch2_tree.commit(message='update file once more')

        out, err = self.run_bzr('diff -r revno:1:branch2..revno:1:branch1',
                                )
        self.assertEquals('', err)
        self.assertEquals('', out)
        out, err = self.run_bzr('diff -r revno:2:branch2..revno:1:branch1',
                                retcode=1)
        self.assertEquals('', err)
        self.assertEqualDiff("=== modified file 'file'\n"
                              "--- file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "+++ file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "@@ -1,1 +1,1 @@\n"
                              "-new content\n"
                              "+contents of branch1/file\n"
                              "\n", subst_dates(out))

    def example_branch2(self):
        branch1_tree = self.make_branch_and_tree('branch1')
        self.build_tree_contents([('branch1/file1', 'original line\n')])
        branch1_tree.add('file1')
        branch1_tree.commit(message='first commit')
        self.build_tree_contents([('branch1/file1', 'repo line\n')])
        branch1_tree.commit(message='second commit')
        return branch1_tree

    def test_diff_to_working_tree(self):
        self.example_branch2()
        self.build_tree_contents([('branch1/file1', 'new line')])
        output = self.run_bzr('diff -r 1.. branch1', retcode=1)
        self.assertContainsRe(output[0], '\n\\-original line\n\\+new line\n')

    def test_diff_across_rename(self):
        """The working tree path should always be considered for diffing"""
        tree = self.make_example_branch()
        self.run_bzr('diff -r 0..1 hello', retcode=1)
        tree.rename_one('hello', 'hello1')
        self.run_bzr('diff hello1', retcode=1)
        self.run_bzr('diff -r 0..1 hello1', retcode=1)


class TestCheckoutDiff(TestDiff):

    def make_example_branch(self):
        tree = super(TestCheckoutDiff, self).make_example_branch()
        tree = tree.branch.create_checkout('checkout')
        os.chdir('checkout')
        return tree

    def example_branch2(self):
        tree = super(TestCheckoutDiff, self).example_branch2()
        os.mkdir('checkouts')
        tree = tree.branch.create_checkout('checkouts/branch1')
        os.chdir('checkouts')
        return tree

    def example_branches(self):
        branch1_tree, branch2_tree = super(TestCheckoutDiff, self).example_branches()
        os.mkdir('checkouts')
        branch1_tree = branch1_tree.branch.create_checkout('checkouts/branch1')
        branch2_tree = branch2_tree.branch.create_checkout('checkouts/branch2')
        os.chdir('checkouts')
        return branch1_tree, branch2_tree


class TestDiffLabels(DiffBase):

    def test_diff_label_removed(self):
        tree = super(TestDiffLabels, self).make_example_branch()
        tree.remove('hello', keep_files=False)
        diff = self.run_bzr('diff', retcode=1)
        self.assertTrue("=== removed file 'hello'" in diff[0])

    def test_diff_label_added(self):
        tree = super(TestDiffLabels, self).make_example_branch()
        self.build_tree_contents([('barbar', 'barbar')])
        tree.add('barbar')
        diff = self.run_bzr('diff', retcode=1)
        self.assertTrue("=== added file 'barbar'" in diff[0])

    def test_diff_label_modified(self):
        super(TestDiffLabels, self).make_example_branch()
        self.build_tree_contents([('hello', 'barbar')])
        diff = self.run_bzr('diff', retcode=1)
        self.assertTrue("=== modified file 'hello'" in diff[0])

    def test_diff_label_renamed(self):
        tree = super(TestDiffLabels, self).make_example_branch()
        tree.rename_one('hello', 'gruezi')
        diff = self.run_bzr('diff', retcode=1)
        self.assertTrue("=== renamed file 'hello' => 'gruezi'" in diff[0])


class TestExternalDiff(DiffBase):

    def test_external_diff(self):
        """Test that we can spawn an external diff process"""
        # We have to use run_bzr_subprocess, because we need to
        # test writing directly to stdout, (there was a bug in
        # subprocess.py that we had to workaround).
        # However, if 'diff' may not be available
        self.make_example_branch()
        orig_progress = os.environ.get('BZR_PROGRESS_BAR')
        try:
            os.environ['BZR_PROGRESS_BAR'] = 'none'
            out, err = self.run_bzr_subprocess('diff -r 1 --diff-options -ub',
                                               universal_newlines=True,
                                               retcode=None)
        finally:
            if orig_progress is None:
                del os.environ['BZR_PROGRESS_BAR']
            else:
                os.environ['BZR_PROGRESS_BAR'] = orig_progress
            
        if 'Diff is not installed on this machine' in err:
            raise TestSkipped("No external 'diff' is available")
        self.assertEqual('', err)
        # We have to skip the stuff in the middle, because it depends
        # on time.time()
        self.assertStartsWith(out, "=== added file 'goodbye'\n"
                                   "--- goodbye\t1970-01-01 00:00:00 +0000\n"
                                   "+++ goodbye\t")
        self.assertEndsWith(out, "\n@@ -0,0 +1 @@\n"
                                 "+baz\n\n")


class TestDiffOutput(DiffBase):

    def test_diff_output(self):
        # check that output doesn't mangle line-endings
        self.make_example_branch()
        self.build_tree_contents([('hello', 'hello world!\n')])
        output = self.run_bzr_subprocess('diff', retcode=1)[0]
        self.assert_('\n+hello world!\n' in output)

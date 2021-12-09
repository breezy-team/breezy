# Copyright (C) 2006, 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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

"""Black-box tests for brz revert."""

import os

import breezy.osutils
from breezy.tests import TestCaseWithTransport
from breezy.trace import mutter
from breezy.workingtree import WorkingTree


class TestRevert(TestCaseWithTransport):

    def _prepare_tree(self):
        self.run_bzr('init')
        self.run_bzr('mkdir dir')

        with open('dir/file', 'wb') as f:
            f.write(b'spam')
        self.run_bzr('add dir/file')

        self.run_bzr('commit -m1')

        # modify file
        with open('dir/file', 'wb') as f:
            f.write(b'eggs')

        # check status
        self.assertEqual('modified:\n  dir/file\n', self.run_bzr('status')[0])

    def _prepare_rename_mod_tree(self):
        self.build_tree(['a/', 'a/b', 'a/c', 'a/d/', 'a/d/e', 'f/', 'f/g',
                         'f/h', 'f/i'])
        self.run_bzr('init')
        self.run_bzr('add')
        self.run_bzr('commit -m 1')
        wt = WorkingTree.open('.')
        wt.rename_one('a/b', 'f/b')
        wt.rename_one('a/d/e', 'f/e')
        wt.rename_one('a/d', 'f/d')
        wt.rename_one('f/g', 'a/g')
        wt.rename_one('f/h', 'h')
        wt.rename_one('f', 'j')

    def helper(self, param=''):
        self._prepare_tree()
        # change dir
        # revert to default revision for file in subdir does work
        os.chdir('dir')
        mutter('cd dir\n')

        self.assertEqual('1\n', self.run_bzr('revno')[0])
        self.run_bzr('revert %s file' % param)
        with open('file', 'rb') as f:
            self.assertEqual(b'spam', f.read())

    def test_revert_in_subdir(self):
        self.helper()

    def test_revert_to_revision_in_subdir(self):
        # test case for bug #29424:
        # revert to specific revision for file in subdir does not work
        self.helper('-r 1')

    def test_revert_in_checkout(self):
        os.mkdir('brach')
        os.chdir('brach')
        self._prepare_tree()
        self.run_bzr('checkout --lightweight . ../sprach')
        self.run_bzr('commit -m more')
        os.chdir('../sprach')
        self.assertEqual('', self.run_bzr('status')[0])
        self.run_bzr('revert')
        self.assertEqual('', self.run_bzr('status')[0])

    def test_revert_dirname(self):
        """Test that revert DIRECTORY does what's expected"""
        self._prepare_rename_mod_tree()
        self.run_bzr('revert a')
        self.assertPathExists('a/b')
        self.assertPathExists('a/d')
        self.assertPathDoesNotExist('a/g')
        self.expectFailure(
            "j is in the delta revert applies because j was renamed too",
            self.assertPathExists, 'j')
        self.assertPathExists('h')
        self.run_bzr('revert f')
        self.assertPathDoesNotExist('j')
        self.assertPathDoesNotExist('h')
        self.assertPathExists('a/d/e')

    def test_revert_chatter(self):
        self._prepare_rename_mod_tree()
        chatter = self.run_bzr('revert')[1]
        self.assertEqualDiff(
            'R   a/g => f/g\n'
            'R   h => f/h\n'
            'R   j/ => f/\n'
            'R   j/b => a/b\n'
            'R   j/d/ => a/d/\n'
            'R   j/e => a/d/e\n',
            chatter)

    def test_revert(self):
        self.run_bzr('init')

        with open('hello', 'wt') as f:
            f.write('foo')
        self.run_bzr('add hello')
        self.run_bzr('commit -m setup hello')

        with open('goodbye', 'wt') as f:
            f.write('baz')
        self.run_bzr('add goodbye')
        self.run_bzr('commit -m setup goodbye')

        with open('hello', 'wt') as f:
            f.write('bar')
        with open('goodbye', 'wt') as f:
            f.write('qux')
        self.run_bzr('revert hello')
        self.check_file_contents('hello', b'foo')
        self.check_file_contents('goodbye', b'qux')
        self.run_bzr('revert')
        self.check_file_contents('goodbye', b'baz')

        os.mkdir('revertdir')
        self.run_bzr('add revertdir')
        self.run_bzr('commit -m f')
        os.rmdir('revertdir')
        self.run_bzr('revert')

        if breezy.osutils.supports_symlinks(self.test_dir):
            os.symlink('/unlikely/to/exist', 'symlink')
            self.run_bzr('add symlink')
            self.run_bzr('commit -m f')
            os.unlink('symlink')
            self.run_bzr('revert')
            self.assertPathExists('symlink')
            os.unlink('symlink')
            os.symlink('a-different-path', 'symlink')
            self.run_bzr('revert')
            self.assertEqual('/unlikely/to/exist',
                             os.readlink('symlink'))
        else:
            self.log("skipping revert symlink tests")

        with open('hello', 'wt') as f:
            f.write('xyz')
        self.run_bzr('commit -m xyz hello')
        self.run_bzr('revert -r 1 hello')
        self.check_file_contents('hello', b'foo')
        self.run_bzr('revert hello')
        self.check_file_contents('hello', b'xyz')
        os.chdir('revertdir')
        self.run_bzr('revert')
        os.chdir('..')

    def test_revert_newly_added(self):
        # this tests the UI reports reverting a newly added file
        # correct (such files are not deleted)
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        tree.add(['file'])
        out, err = self.run_bzr('revert')
        self.assertEqual('', out)
        self.assertEqual('-   file\n', err)

    def test_revert_removing_file(self):
        # this tests the UI reports reverting a file which has been committed
        # to a revision that did not have it, reports it as being deleted.
        tree = self.make_branch_and_tree('.')
        tree.commit('empty commit')
        self.build_tree(['file'])
        tree.add(['file'])
        tree.commit('add file')
        out, err = self.run_bzr('revert -r -2')
        self.assertEqual('', out)
        self.assertEqual('-D  file\n', err)

    def test_revert_forget_merges(self):
        # revert --forget-merges removes any pending merges into the tree, but
        # leaves the files unchanged
        tree = self.make_branch_and_tree('.')
        # forget-merges before first commit, though pointless, does not fail
        self.run_bzr(['revert', '--forget-merges'])
        self.build_tree(['file'])
        first_rev_id = tree.commit('initial commit')
        self.build_tree_contents([('file', b'new content')])
        existing_parents = tree.get_parent_ids()
        self.assertEqual([first_rev_id], existing_parents)
        merged_parents = existing_parents + [b'merged-in-rev']
        tree.set_parent_ids(merged_parents)
        self.assertEqual(merged_parents, tree.get_parent_ids())
        self.run_bzr(['revert', '--forget-merges'])
        self.assertEqual([first_rev_id], tree.get_parent_ids())
        # changed files are not reverted
        self.assertFileEqual(b'new content', 'file')
        # you can give it the path of a tree
        self.run_bzr(['revert', '--forget-merges', tree.abspath('.')])

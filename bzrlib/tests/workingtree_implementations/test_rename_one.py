# Copyright (C) 2007 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.rename_one'"""

import os

from bzrlib import (
    errors,
    osutils,
    )

from bzrlib.workingtree_4 import WorkingTreeFormat4
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestRenameOne(TestCaseWithWorkingTree):

    def get_tree_layout(self, tree):
        """Get the (path, file_id) pairs for the current tree."""
        tree.lock_read()
        try:
            return [(path, ie.file_id) for path, ie
                    in tree.iter_entries_by_dir()]
        finally:
            tree.unlock()

    def assertTreeLayout(self, expected, tree):
        """Check that the tree has the correct layout."""
        actual = self.get_tree_layout(tree)
        self.assertEqual(expected, actual)

    def test_rename_one_target_not_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'not-a-dir/b')

    def test_rename_one_non_existent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'not-a-file', 'a/failure')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'not-a-file', 'also_not')

    def test_rename_one_target_not_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['b'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'b', 'a/b')

    def test_rename_one_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'b', 'a/b')

    def test_rename_one_samedir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        a_contents = tree.get_file_text('a-id')
        tree.rename_one('a', 'foo')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('foo', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())
        self.failIfExists('a')
        self.assertFileEqual(a_contents, 'foo')

    def test_rename_one_not_localdir(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        a_contents = tree.get_file_text('a-id')
        tree.rename_one('a', 'b/foo')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/foo', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())
        self.failIfExists('tree/a')
        self.assertFileEqual(a_contents, 'tree/b/foo')

    def test_rename_one_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        a_contents = tree.get_file_text('a-id')
        tree.rename_one('a', 'b/d')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/c', 'c-id'),
                               ('b/d', 'a-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        self.failIfExists('a')
        self.assertFileEqual(a_contents, 'b/d')

    def test_rename_one_parent_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        c_contents = tree.get_file_text('c-id')
        tree.rename_one('b/c', 'd')
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('d', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        self.failIfExists('b/c')
        self.assertFileEqual(c_contents, 'd')

    def test_rename_one_fail_consistent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/a', 'c'])
        tree.add(['a', 'b', 'c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        # Target already exists
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.rename_one, 'a', 'b/a')
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('c', 'c-id')], tree.basis_tree())

    def test_rename_one_onto_existing(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'b')

    def test_rename_one_onto_self(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['b/', 'b/a'])
        tree.add(['b', 'b/a'], ['b-id', 'a-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'b/a', 'b/a')

    def test_rename_one_onto_self_root(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'], ['a-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'a')

    def test_rename_one_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        os.rename('a', 'b/foo')

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        # We don't need after=True as long as source is missing and target
        # exists.
        tree.rename_one('a', 'b/foo')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'),
                               ('b/foo', 'a-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())

    def test_rename_one_after_with_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        os.rename('a', 'b/foo')

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        # Passing after=True should work as well
        tree.rename_one('a', 'b/foo', after=True)
        self.assertTreeLayout([('', root_id), ('b', 'b-id'),
                               ('b/foo', 'a-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())

    def test_rename_one_after_no_target(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        # Passing after when the file hasn't been rename_one raises an exception
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'b/foo', after=True)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())

    def test_rename_one_after_source_and_dest(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/foo'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        # TODO: jam 20070225 I would usually use 'rb', but assertFileEqual
        #       uses 'r'.
        a_file = open('a', 'r')
        try:
            a_text = a_file.read()
        finally:
            a_file.close()
        foo_file = open('b/foo', 'r')
        try:
            foo_text = foo_file.read()
        finally:
            foo_file.close()

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.rename_one, 'a', 'b/foo', after=False)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(foo_text, 'b/foo')
        # But you can pass after=True
        tree.rename_one('a', 'b/foo', after=True)
        self.assertTreeLayout([('', root_id), ('b', 'b-id'),
                               ('b/foo', 'a-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())
        # But it shouldn't actually move anything
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(foo_text, 'b/foo')

    def test_rename_one_directory(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c/', 'a/c/d', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'a/c/d', 'e'],
                 ['a-id', 'b-id', 'c-id', 'd-id', 'e-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        tree.rename_one('a', 'e/f')
        self.assertTreeLayout([('', root_id), ('e', 'e-id'), ('e/f', 'a-id'),
                               ('e/f/b', 'b-id'), ('e/f/c', 'c-id'),
                               ('e/f/c/d', 'd-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('e', 'e-id'),
                               ('a/b', 'b-id'), ('a/c', 'c-id'),
                               ('a/c/d', 'd-id')], tree.basis_tree())

    def test_rename_one_moved(self):
        """Moving a moved entry works as expected."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c/'])
        tree.add(['a', 'a/b', 'c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        tree.rename_one('a/b', 'c/foo')
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('c', 'c-id'),
                               ('c/foo', 'b-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('c', 'c-id'),
                               ('a/b', 'b-id')], tree.basis_tree())

        tree.rename_one('c/foo', 'bar')
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('bar', 'b-id'),
                               ('c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('c', 'c-id'),
                               ('a/b', 'b-id')], tree.basis_tree())

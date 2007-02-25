# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for interface conformance of 'workingtree.put_mkdir'"""

import os

from bzrlib import (
    errors,
    osutils,
    )

from bzrlib.workingtree_4 import WorkingTreeFormat4
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestMove(TestCaseWithWorkingTree):

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

    def test_move_correct_call_named(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using named parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        tree.move(['a1'], to_dir='sub1', after=False)

    def test_move_correct_call_unnamed(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using unnamed parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        tree.move(['a1'], 'sub1', after=False)

    def test_move_deprecated_wrong_call(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using wrong parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        self.assertRaises(TypeError, tree.move, ['a1'],
                          to_this_parameter_does_not_exist='sub1',
                          after=False)

    def test_move_deprecated_call(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using deprecated parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')

        try:
            self.callDeprecated(['The parameter to_name was deprecated'
                                 ' in version 0.13. Use to_dir instead'],
                                tree.move, ['a1'], to_name='sub1',
                                after=False)
        except TypeError:
            # WorkingTreeFormat4 doesn't have to maintain api compatibility
            # since it was deprecated before the class was introduced.
            if not isinstance(self.workingtree_format, WorkingTreeFormat4):
                raise

    def test_move_target_not_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'not-a-dir')

    def test_move_non_existent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], '')

    def test_move_target_not_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['b'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')

    # TODO: jam 20070225 What about a test when the target is now a directory,
    #       but in the past it was a file. Theoretically WorkingTree should
    #       notice the kind change.

    def test_move_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')

    def test_move_multi_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b', 'c', 'd'])
        tree.add(['a', 'c', 'd'], ['a-id', 'c-id', 'd-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['c', 'b', 'd'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b', 'c', 'd'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['d', 'c', 'b'], 'a')
        if osutils.lexists('a/c'):
            # If 'c' was actually moved, then 'd' should have also been moved
            self.assertTreeLayout([('', root_id), ('a', 'a-id'),
                                   ('a/c', 'c-id'),  ('a/d', 'd-id')], tree)
        else:
            self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('c', 'c-id'),
                                   ('d', 'd-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('c', 'c-id'),
                               ('d', 'd-id')], tree.basis_tree())

    def test_move_subdir(self):
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
        tree.move(['a'], 'b')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/a', 'a-id'),
                               ('b/c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        self.failIfExists('a')
        self.assertFileEqual(a_contents, 'b/a')

    def test_move_parent_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        c_contents = tree.get_file_text('c-id')
        tree.move(['b/c'], '')
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        self.failIfExists('b/c')
        self.assertFileEqual(c_contents, 'c')

    def test_move_fail_consistent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/a', 'c'])
        tree.add(['a', 'b', 'c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        # Target already exists
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.move, ['c', 'a'], 'b')
        # 'c' may or may not have been moved, but either way the tree should
        # maintain a consistent state.
        if osutils.lexists('c'):
            self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                                   ('c', 'c-id')], tree)
        else:
            self.failUnlessExists('b/c')
            self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                                   ('b/c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('c', 'c-id')], tree.basis_tree())

    def test_move_onto_self(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['b/', 'b/a'])
        tree.add(['b', 'b/a'], ['b-id', 'a-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b/a'], 'b')

    def test_move_onto_self_root(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'], ['a-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'a')

    def test_move_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        os.rename('a', 'b/a')

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        # We don't need after=True as long as source is missing and target
        # exists.
        tree.move(['a'], 'b')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/a', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())

    def test_move_after_with_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        os.rename('a', 'b/a')

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        # Passing after=True should work as well
        tree.move(['a'], 'b', after=True)
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/a', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())

    def test_move_after_no_target(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        # Passing after when the file hasn't been move raises an exception
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'b', after=True)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())

    def test_move_after_source_and_dest(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/a'])
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
        ba_file = open('b/a', 'r')
        try:
            ba_text = ba_file.read()
        finally:
            ba_file.close()

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.move, ['a'], 'b', after=False)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree)
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(ba_text, 'b/a')
        # But you can pass after=True
        tree.move(['a'], 'b', after=True)
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/a', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id')],
                              tree.basis_tree())
        # But it shouldn't actually move anything
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(ba_text, 'b/a')

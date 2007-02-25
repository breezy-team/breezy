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

from bzrlib import (
    errors,
    )

from bzrlib.workingtree_4 import WorkingTreeFormat4
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestMove(TestCaseWithWorkingTree):

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

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'not-a-dir')

    def test_move_non_existent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        tree.add(['a'])
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], 'a')

    def test_move_target_not_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['b'])
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')

    # TODO: jam 20070225 What about a test when the target is now a directory,
    #       but in the past it was a file. Theoretically WorkingTree should
    #       notice the kind change.

    def test_move_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['a'])
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')

    def test_move_multi_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b', 'c', 'd'])
        tree.add(['a', 'c', 'd'])
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['c', 'b', 'd'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b', 'c', 'd'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['c', 'd', 'b'], 'a')

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

    def test_move_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        root_id = tree.get_root_id()
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('b/c', 'c-id')], tree)
        a_contents = tree.get_file_text('a-id')
        tree.move(['a'], 'b')
        self.assertTreeLayout([('', root_id), ('b', 'b-id'), ('b/a', 'a-id'),
                               ('b/c', 'c-id')], tree)
        self.failIfExists('a')
        self.failUnlessExists('b/a')
        self.check_file_contents('b/a', a_contents)

    def test_move_parent_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        root_id = tree.get_root_id()
        c_contents = tree.get_file_text('c-id')
        tree.move(['b/c'], '')
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('c', 'c-id')], tree)
        self.failIfExists('b/c')
        self.failUnlessExists('c')
        self.check_file_contents('c', c_contents)

    def dont_test(self):
        self.run_bzr('mv', 'a', 'b')
        self.assertMoved('a','b')

        self.run_bzr('mv', 'b', 'subdir')
        self.assertMoved('b','subdir/b')

        self.run_bzr('mv', 'subdir/b', 'a')
        self.assertMoved('subdir/b','a')

        self.run_bzr('mv', 'a', 'c', 'subdir')
        self.assertMoved('a','subdir/a')
        self.assertMoved('c','subdir/c')

        self.run_bzr('mv', 'subdir/a', 'subdir/newa')
        self.assertMoved('subdir/a','subdir/newa')

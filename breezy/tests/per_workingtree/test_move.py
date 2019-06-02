# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.move'"""

import os

from breezy import (
    errors,
    osutils,
    tests,
    )

from breezy.tests.matchers import HasLayout, HasPathRelations
from breezy.tests.per_workingtree import TestCaseWithWorkingTree
from breezy.tests import (
    features,
    )


class TestMove(TestCaseWithWorkingTree):

    def assertPathRelations(self, previous_tree, tree, relations):
        self.assertThat(tree, HasPathRelations(previous_tree, relations))

    def assertTreeLayout(self, expected, tree):
        """Check that the tree has the correct layout."""
        self.assertThat(tree, HasLayout(expected))

    def test_move_via_rm_and_add(self):
        """Move by remove and add-with-id"""
        self.build_tree(['a1', 'b1'])
        tree = self.make_branch_and_tree('.')
        if tree.supports_setting_file_ids():
            tree.add(['a1'], ids=[b'a1-id'])
        else:
            tree.add(['a1'])
        tree.commit('initial commit')
        tree.remove('a1', force=True, keep_files=False)
        if tree.supports_setting_file_ids():
            tree.add(['b1'], ids=[b'a1-id'])
        else:
            tree.add(['b1'])
        tree._validate()

    def test_move_correct_call_named(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using named parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        self.assertEqual([('a1', 'sub1/a1')],
                         tree.move(['a1'], to_dir='sub1', after=False))
        tree._validate()

    def test_move_correct_call_unnamed(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using unnamed parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        self.assertEqual([('a1', 'sub1/a1')],
                         tree.move(['a1'], 'sub1', after=False))
        tree._validate()

    def test_move_target_not_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'not-a-dir')
        tree._validate()

    def test_move_non_existent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        tree.add(['a'])
        tree.commit('initial')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], '')
        tree._validate()

    def test_move_target_not_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['b'])
        tree.commit('initial')
        if tree.has_versioned_directories():
            self.assertRaises(errors.BzrMoveFailedError,
                              tree.move, ['b'], 'a')
        else:
            tree.move(['b'], 'a')
        tree._validate()

    def test_move_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['a'])
        tree.commit('initial')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')
        tree._validate()

    def test_move_multi_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b', 'c', 'd'])
        tree.add(['a', 'c', 'd'])
        tree.commit('initial')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['c', 'b', 'd'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b', 'c', 'd'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['d', 'c', 'b'], 'a')
        if osutils.lexists('a/c'):
            # If 'c' was actually moved, then 'd' should have also been moved
            self.assertPathRelations(
                tree.basis_tree(), tree,
                [('', ''), ('a/', 'a/'), ('a/c', 'c'), ('a/d', 'd')])
        else:
            self.assertPathRelations(
                tree.basis_tree(), tree,
                [('', ''), ('a/', 'a/'), ('c', 'c'), ('d', 'd')])
        tree._validate()

    def test_move_over_deleted(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'b'])
        tree.add(['a', 'a/b', 'b'])
        tree.commit('initial')

        tree.remove(['a/b'], keep_files=False)
        self.assertEqual([('b', 'a/b')], tree.move(['b'], 'a'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a/', 'a/'), ('a/b', 'b')])
        tree._validate()

    def test_move_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'])
        tree.commit('initial')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/'), ('b/c', 'b/c')])
        a_contents = tree.get_file_text('a')
        self.assertEqual([('a', 'b/a')], tree.move(['a'], 'b'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/a', 'a'), ('b/c', 'b/c')])
        self.assertPathDoesNotExist('a')
        self.assertFileEqual(a_contents, 'b/a')
        tree._validate()

    def test_move_parent_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'])
        tree.commit('initial')
        c_contents = tree.get_file_text('b/c')
        self.assertEqual([('b/c', 'c')],
                         tree.move(['b/c'], ''))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/'), ('c', 'b/c')])
        self.assertPathDoesNotExist('b/c')
        self.assertFileEqual(c_contents, 'c')
        tree._validate()

    def test_move_fail_consistent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/a', 'c'])
        tree.add(['a', 'b', 'c'])
        tree.commit('initial')
        # Target already exists
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.move, ['c', 'a'], 'b')
        # 'c' may or may not have been moved, but either way the tree should
        # maintain a consistent state.
        if osutils.lexists('c'):
            self.assertPathRelations(
                tree.basis_tree(), tree,
                [('', ''), ('a', 'a'), ('b/', 'b/'), ('c', 'c')])
        else:
            self.assertPathExists('b/c')
            self.assertPathRelations(
                tree.basis_tree(), tree,
                [('', ''), ('a', 'a'), ('b/', 'b/'), ('b/c', 'c')])
        tree._validate()

    def test_move_onto_self(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['b/', 'b/a'])
        tree.add(['b', 'b/a'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b/a'], 'b')
        tree._validate()

    def test_move_onto_self_root(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'a')
        tree._validate()

    def test_move_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')
        os.rename('a', 'b/a')

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/')])
        # We don't need after=True as long as source is missing and target
        # exists.
        self.assertEqual([('a', 'b/a')],
                         tree.move(['a'], 'b'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/a', 'a')])
        tree._validate()

    def test_move_after_with_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')
        os.rename('a', 'b/a')

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/')])
        # Passing after=True should work as well
        self.assertEqual([('a', 'b/a')], tree.move(['a'], 'b', after=True))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/a', 'a')])
        tree._validate()

    def test_move_after_no_target(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        # Passing after when the file hasn't been move raises an exception
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'b', after=True)

        self.assertTreeLayout(['', 'a', 'b/'], tree.basis_tree())
        tree._validate()

    def test_move_after_source_and_dest(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/a'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        # TODO: jam 20070225 I would usually use 'rb', but assertFileEqual
        #       uses 'r'.
        with open('a', 'r') as a_file:
            a_text = a_file.read()
        with open('b/a', 'r') as ba_file:
            ba_text = ba_file.read()

        self.assertTreeLayout(['', 'a', 'b/'], tree)
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.move, ['a'], 'b', after=False)
        self.assertTreeLayout(['', 'a', 'b/'], tree)
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(ba_text, 'b/a')
        # But you can pass after=True
        self.assertEqual([('a', 'b/a')],
                         tree.move(['a'], 'b', after=True))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/a', 'a')])
        # But it shouldn't actually move anything
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(ba_text, 'b/a')
        tree._validate()

    def test_move_directory(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c/', 'a/c/d', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'a/c/d', 'e'])
        tree.commit('initial')

        self.assertEqual([('a', 'e/a')], tree.move(['a'], 'e'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('e/', 'e/'), ('e/a/', 'a/'), ('e/a/b', 'a/b'),
             ('e/a/c/', 'a/c/'), ('e/a/c/d', 'a/c/d')])
        tree._validate()

    def test_move_directory_into_parent(self):
        if not self.workingtree_format.supports_versioned_directories:
            raise tests.TestNotApplicable(
                "test requires versioned directories")
        tree = self.make_branch_and_tree('.')
        self.build_tree(['c/', 'c/b/', 'c/b/d/'])
        tree.add(['c', 'c/b', 'c/b/d'])
        tree.commit('initial')

        self.assertEqual([('c/b', 'b')],
                         tree.move(['c/b'], ''))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('b/', 'c/b/'),
             ('c/', 'c/'),
             ('b/d/', 'c/b/d/')])
        tree._validate()

    def test_move_directory_with_children_in_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c/', 'd/'])
        tree.add(['a', 'a/b', 'a/c', 'd'])
        tree.commit('initial')

        tree.rename_one('a/b', 'a/c/b')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('a/', 'a/'),
             ('d/', 'd/'),
             ('a/c/', 'a/c/'),
             ('a/c/b', 'a/b'),
             ])
        self.assertEqual([('a', 'd/a')],
                         tree.move(['a'], 'd'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('d/', 'd/'),
             ('d/a/', 'a/'),
             ('d/a/c/', 'a/c/'),
             ('d/a/c/b', 'a/b'),
             ])
        tree._validate()

    def test_move_directory_with_deleted_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'a/d', 'b/'])
        tree.add(['a', 'b', 'a/b', 'a/c', 'a/d'])
        tree.commit('initial')

        tree.remove(['a/b', 'a/d'])

        self.assertEqual([('a', 'b/a')],
                         tree.move(['a'], 'b'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('b/', 'b/'),
             ('b/a/', 'a/'),
             ('b/a/c', 'a/c')])
        tree._validate()

    def test_move_directory_with_new_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/c', 'b/'])
        tree.add(['a', 'b', 'a/c'])
        tree.commit('initial')

        self.build_tree(['a/b', 'a/d'])
        tree.add(['a/b', 'a/d'])

        self.assertEqual([('a', 'b/a')], tree.move(['a'], 'b'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('b/', 'b/'),
             ('b/a/', 'a/'),
             ('b/a/b', None),
             ('b/a/c', 'a/c'),
             ('b/a/d', None),
             ])
        tree._validate()

    def test_move_directory_with_moved_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'd', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'd', 'e'])
        tree.commit('initial')

        self.assertEqual([('a/b', 'b')],
                         tree.move(['a/b'], ''))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('a/', 'a/'),
             ('b', 'a/b'),
             ('d', 'd'),
             ('e/', 'e/'),
             ('a/c', 'a/c'),
             ])
        self.assertEqual([('d', 'a/d')],
                         tree.move(['d'], 'a'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('a/', 'a/'),
             ('b', 'a/b'),
             ('e/', 'e/'),
             ('a/c', 'a/c'),
             ('a/d', 'd'),
             ])
        self.assertEqual([('a', 'e/a')],
                         tree.move(['a'], 'e'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('b', 'a/b'),
             ('e/', 'e/'),
             ('e/a/', 'a/'),
             ('e/a/c', 'a/c'),
             ('e/a/d', 'd'),
             ])
        tree._validate()

    def test_move_directory_with_renamed_child(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'd/'])
        tree.add(['a', 'a/b', 'a/c', 'd'])
        tree.commit('initial')

        tree.rename_one('a/b', 'a/d')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('a/', 'a/'),
             ('d/', 'd/'),
             ('a/c', 'a/c'),
             ('a/d', 'a/b')])

        self.assertEqual([('a', 'd/a')],
                         tree.move(['a'], 'd'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('d/', 'd/'),
             ('d/a/', 'a/'),
             ('d/a/c', 'a/c'),
             ('d/a/d', 'a/b')])
        tree._validate()

    def test_move_directory_with_swapped_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'a/d', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'a/d', 'e'])
        tree.commit('initial')

        tree.rename_one('a/b', 'a/bb')
        tree.rename_one('a/d', 'a/b')
        tree.rename_one('a/bb', 'a/d')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('a/', 'a/'),
             ('e/', 'e/'),
             ('a/b', 'a/d'),
             ('a/c', 'a/c'),
             ('a/d', 'a/b')])
        self.assertEqual([('a', 'e/a')],
                         tree.move(['a'], 'e'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''),
             ('e/', 'e/'),
             ('e/a/', 'a/'),
             ('e/a/b', 'a/d'),
             ('e/a/c', 'a/c'),
             ('e/a/d', 'a/b')])
        tree._validate()

    def test_move_moved(self):
        """Moving a moved entry works as expected."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c/'])
        tree.add(['a', 'a/b', 'c'])
        tree.commit('initial')

        self.assertEqual([('a/b', 'c/b')],
                         tree.move(['a/b'], 'c'))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a/', 'a/'), ('c/', 'c/'), ('c/b', 'a/b')])

        self.assertEqual([('c/b', 'b')], tree.move(['c/b'], ''))
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a/', 'a/'), ('b', 'a/b'), ('c/', 'c/')])
        tree._validate()

    def test_move_to_unversioned_non_ascii_dir(self):
        """Check error when moving to unversioned non-ascii directory"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", u"\xA7/"])
        tree.add(["a"])
        if tree.has_versioned_directories():
            e = self.assertRaises(errors.BzrMoveFailedError,
                                  tree.move, ["a"], u"\xA7")
            self.assertIsInstance(e.extra, errors.NotVersionedError)
            self.assertEqual(e.extra.path, u"\xA7")
        else:
            tree.move(["a"], u"\xA7")

    def test_move_unversioned_non_ascii(self):
        """Check error when moving an unversioned non-ascii file"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree([u"\xA7", "dir/"])
        tree.add("dir")
        e = self.assertRaises(errors.BzrMoveFailedError,
                              tree.move, [u"\xA7"], "dir")
        self.assertIsInstance(e.extra, errors.NotVersionedError)
        self.assertEqual(e.extra.path, u"\xA7")

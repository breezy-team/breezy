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

from bzrlib import (
    errors,
    osutils,
    tests,
    )

from bzrlib.tests.matchers import HasLayout
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree
from bzrlib.tests import (
    features,
    )


class TestMove(TestCaseWithWorkingTree):

    def assertTreeLayout(self, expected, tree):
        """Check that the tree has the correct layout."""
        self.assertThat(tree, HasLayout(expected))

    def test_move_via_rm_and_add(self):
        """Move by remove and add-with-id"""
        self.build_tree(['a1', 'b1'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1'], ids=['a1-id'])
        tree.commit('initial commit')
        tree.remove('a1', force=True, keep_files=False)
        tree.add(['b1'], ids=['a1-id'])
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
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'not-a-dir')
        tree._validate()

    def test_move_non_existent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], 'a')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['not-a-file'], '')
        tree._validate()

    def test_move_target_not_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['b'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')
        tree._validate()

    def test_move_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['a'])
        tree.commit('initial', rev_id='rev-1')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b'], 'a')
        tree._validate()

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
            self.assertTreeLayout([('', root_id), ('a/', 'a-id'),
                                   ('a/c', 'c-id'),  ('a/d', 'd-id')], tree)
        else:
            self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('c', 'c-id'),
                                   ('d', 'd-id')], tree)
        self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('c', 'c-id'),
                               ('d', 'd-id')], tree.basis_tree())
        tree._validate()

    def test_move_over_deleted(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'b'])
        tree.add(['a', 'a/b', 'b'], ['a-id', 'ab-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')

        root_id = tree.get_root_id()
        tree.remove(['a/b'], keep_files=False)
        self.assertEqual([('b', 'a/b')], tree.move(['b'], 'a'))
        self.assertTreeLayout([('', root_id),
                               ('a/', 'a-id'),
                               ('a/b', 'b-id'),
                              ], tree)
        tree._validate()

    def test_move_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                               ('b/c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        a_contents = tree.get_file_text('a-id')
        self.assertEqual([('a', 'b/a')],
            tree.move(['a'], 'b'))
        self.assertTreeLayout([('', root_id), ('b/', 'b-id'), ('b/a', 'a-id'),
                               ('b/c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        self.assertPathDoesNotExist('a')
        self.assertFileEqual(a_contents, 'b/a')
        tree._validate()

    def test_move_parent_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        c_contents = tree.get_file_text('c-id')
        self.assertEqual([('b/c', 'c')],
            tree.move(['b/c'], ''))
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                               ('c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                               ('b/c', 'c-id')], tree.basis_tree())
        self.assertPathDoesNotExist('b/c')
        self.assertFileEqual(c_contents, 'c')
        tree._validate()

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
            self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                                   ('c', 'c-id')], tree)
        else:
            self.assertPathExists('b/c')
            self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                                   ('b/c', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id'),
                               ('c', 'c-id')], tree.basis_tree())
        tree._validate()

    def test_move_onto_self(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['b/', 'b/a'])
        tree.add(['b', 'b/a'], ['b-id', 'a-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['b/a'], 'b')
        tree._validate()

    def test_move_onto_self_root(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'], ['a-id'])
        tree.commit('initial', rev_id='rev-1')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'a')
        tree._validate()

    def test_move_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        os.rename('a', 'b/a')

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree)
        # We don't need after=True as long as source is missing and target
        # exists.
        self.assertEqual([('a', 'b/a')],
            tree.move(['a'], 'b'))
        self.assertTreeLayout([('', root_id), ('b/', 'b-id'), ('b/a', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree.basis_tree())
        tree._validate()

    def test_move_after_with_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()
        os.rename('a', 'b/a')

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree)
        # Passing after=True should work as well
        self.assertEqual([('a', 'b/a')],
            tree.move(['a'], 'b', after=True))
        self.assertTreeLayout([('', root_id), ('b/', 'b-id'), ('b/a', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree.basis_tree())
        tree._validate()

    def test_move_after_no_target(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        # Passing after when the file hasn't been move raises an exception
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.move, ['a'], 'b', after=True)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree.basis_tree())
        tree._validate()

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

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree)
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.move, ['a'], 'b', after=False)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree)
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(ba_text, 'b/a')
        # But you can pass after=True
        self.assertEqual([('a', 'b/a')],
            tree.move(['a'], 'b', after=True))
        self.assertTreeLayout([('', root_id), ('b/', 'b-id'), ('b/a', 'a-id')],
                              tree)
        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b/', 'b-id')],
                              tree.basis_tree())
        # But it shouldn't actually move anything
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(ba_text, 'b/a')
        tree._validate()

    def test_move_directory(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c/', 'a/c/d', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'a/c/d', 'e'],
                 ['a-id', 'b-id', 'c-id', 'd-id', 'e-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        self.assertEqual([('a', 'e/a')],
            tree.move(['a'], 'e'))
        self.assertTreeLayout([('', root_id), ('e/', 'e-id'), ('e/a/', 'a-id'),
                               ('e/a/b', 'b-id'), ('e/a/c/', 'c-id'),
                               ('e/a/c/d', 'd-id')], tree)
        self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('e/', 'e-id'),
                               ('a/b', 'b-id'), ('a/c/', 'c-id'),
                               ('a/c/d', 'd-id')], tree.basis_tree())
        tree._validate()

    def test_move_directory_into_parent(self):
        if not self.workingtree_format.supports_versioned_directories:
            raise tests.TestNotApplicable(
                "test requires versioned directories")
        tree = self.make_branch_and_tree('.')
        self.build_tree(['c/', 'c/b/', 'c/b/d/'])
        tree.add(['c', 'c/b', 'c/b/d'],
                 ['c-id', 'b-id', 'd-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        self.assertEqual([('c/b', 'b')],
                         tree.move(['c/b'], ''))
        self.assertTreeLayout([('', root_id),
                               ('b/', 'b-id'),
                               ('c/', 'c-id'),
                               ('b/d/', 'd-id'),
                              ], tree)
        tree._validate()

    def test_move_directory_with_children_in_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c/', 'd/'])
        tree.add(['a', 'a/b', 'a/c', 'd'],
                 ['a-id', 'b-id', 'c-id', 'd-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        tree.rename_one('a/b', 'a/c/b')
        self.assertTreeLayout([('', root_id),
                               ('a/', 'a-id'),
                               ('d/', 'd-id'),
                               ('a/c/', 'c-id'),
                               ('a/c/b', 'b-id'),
                              ], tree)
        self.assertEqual([('a', 'd/a')],
                         tree.move(['a'], 'd'))
        self.assertTreeLayout([('', root_id),
                               ('d/', 'd-id'),
                               ('d/a/', 'a-id'),
                               ('d/a/c/', 'c-id'),
                               ('d/a/c/b', 'b-id'),
                              ], tree)
        tree._validate()

    def test_move_directory_with_deleted_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'a/d', 'b/'])
        tree.add(['a', 'b', 'a/b', 'a/c', 'a/d'],
                 ['a-id', 'b-id', 'ab-id', 'ac-id', 'ad-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        tree.remove(['a/b', 'a/d'])

        self.assertEqual([('a', 'b/a')],
                         tree.move(['a'], 'b'))
        self.assertTreeLayout([('', root_id),
                               ('b/', 'b-id'),
                               ('b/a/', 'a-id'),
                               ('b/a/c', 'ac-id'),
                              ], tree)
        tree._validate()

    def test_move_directory_with_new_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/c', 'b/'])
        tree.add(['a', 'b', 'a/c'], ['a-id', 'b-id', 'ac-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        self.build_tree(['a/b', 'a/d'])
        tree.add(['a/b', 'a/d'], ['ab-id', 'ad-id'])

        self.assertEqual([('a', 'b/a')],
                         tree.move(['a'], 'b'))
        self.assertTreeLayout([('', root_id),
                               ('b/', 'b-id'),
                               ('b/a/', 'a-id'),
                               ('b/a/b', 'ab-id'),
                               ('b/a/c', 'ac-id'),
                               ('b/a/d', 'ad-id'),
                              ], tree)
        tree._validate()

    def test_move_directory_with_moved_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'd', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'd', 'e'],
                 ['a-id', 'b-id', 'c-id', 'd-id', 'e-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        self.assertEqual([('a/b', 'b')],
                         tree.move(['a/b'], ''))
        self.assertTreeLayout([('', root_id),
                               ('a/', 'a-id'),
                               ('b', 'b-id'),
                               ('d', 'd-id'),
                               ('e/', 'e-id'),
                               ('a/c', 'c-id'),
                              ], tree)
        self.assertEqual([('d', 'a/d')],
                         tree.move(['d'], 'a'))
        self.assertTreeLayout([('', root_id),
                               ('a/', 'a-id'),
                               ('b', 'b-id'),
                               ('e/', 'e-id'),
                               ('a/c', 'c-id'),
                               ('a/d', 'd-id'),
                              ], tree)
        self.assertEqual([('a', 'e/a')],
                         tree.move(['a'], 'e'))
        self.assertTreeLayout([('', root_id),
                               ('b', 'b-id'),
                               ('e/', 'e-id'),
                               ('e/a/', 'a-id'),
                               ('e/a/c', 'c-id'),
                               ('e/a/d', 'd-id'),
                              ], tree)
        tree._validate()

    def test_move_directory_with_renamed_child(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'd/'])
        tree.add(['a', 'a/b', 'a/c', 'd'],
                 ['a-id', 'b-id', 'c-id', 'd-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        tree.rename_one('a/b', 'a/d')
        self.assertTreeLayout([('', root_id),
                               ('a/', 'a-id'),
                               ('d/', 'd-id'),
                               ('a/c', 'c-id'),
                               ('a/d', 'b-id'),
                              ], tree)
        self.assertEqual([('a', 'd/a')],
                         tree.move(['a'], 'd'))
        self.assertTreeLayout([('', root_id),
                               ('d/', 'd-id'),
                               ('d/a/', 'a-id'),
                               ('d/a/c', 'c-id'),
                               ('d/a/d', 'b-id'),
                              ], tree)
        tree._validate()

    def test_move_directory_with_swapped_children(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'a/d', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'a/d', 'e'],
                 ['a-id', 'b-id', 'c-id', 'd-id', 'e-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        tree.rename_one('a/b', 'a/bb')
        tree.rename_one('a/d', 'a/b')
        tree.rename_one('a/bb', 'a/d')
        self.assertTreeLayout([('', root_id),
                               ('a/', 'a-id'),
                               ('e/', 'e-id'),
                               ('a/b', 'd-id'),
                               ('a/c', 'c-id'),
                               ('a/d', 'b-id'),
                              ], tree)
        self.assertEqual([('a', 'e/a')],
                         tree.move(['a'], 'e'))
        self.assertTreeLayout([('', root_id),
                               ('e/', 'e-id'),
                               ('e/a/', 'a-id'),
                               ('e/a/b', 'd-id'),
                               ('e/a/c', 'c-id'),
                               ('e/a/d', 'b-id'),
                              ], tree)
        tree._validate()

    def test_move_moved(self):
        """Moving a moved entry works as expected."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c/'])
        tree.add(['a', 'a/b', 'c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial', rev_id='rev-1')
        root_id = tree.get_root_id()

        self.assertEqual([('a/b', 'c/b')],
            tree.move(['a/b'], 'c'))
        self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('c/', 'c-id'),
                               ('c/b', 'b-id')], tree)
        self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('c/', 'c-id'),
                               ('a/b', 'b-id')], tree.basis_tree())

        self.assertEqual([('c/b', 'b')],
            tree.move(['c/b'], ''))
        self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('b', 'b-id'),
                               ('c/', 'c-id')], tree)
        self.assertTreeLayout([('', root_id), ('a/', 'a-id'), ('c/', 'c-id'),
                               ('a/b', 'b-id')], tree.basis_tree())
        tree._validate()

    def test_move_to_unversioned_non_ascii_dir(self):
        """Check error when moving to unversioned non-ascii directory"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", u"\xA7/"])
        tree.add(["a"])
        e = self.assertRaises(errors.BzrMoveFailedError,
            tree.move, ["a"], u"\xA7")
        self.assertIsInstance(e.extra, errors.NotVersionedError)
        self.assertEqual(e.extra.path, u"\xA7")

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

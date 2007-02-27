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

"""Tests for interface conformance of 'WorkingTree.add'"""

import os

from bzrlib import (
    errors,
    osutils,
    )

from bzrlib.workingtree_4 import WorkingTreeFormat4
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestAdd(TestCaseWithWorkingTree):

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

    def test_add_one(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add('one', 'one-id')
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('one', 'one-id')], tree)

    def test_add_existing_id(self):
        """Adding an entry with a pre-existing id raises DuplicateFileId"""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a'], ['an-id'])
        self.assertRaises(errors.DuplicateFileId,
                          tree.add, ['b'], ['an-id'])
        root_id = tree.get_root_id()
        # And the entry should not have been added.
        self.assertTreeLayout([('', root_id), ('a', 'an-id')], tree)

    def test_add_old_id(self):
        """We can add an old id, as long as it doesn't exist now."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a'], ['an-id'])
        tree.commit('first', rev_id='rev-1')
        root_id = tree.get_root_id()
        # And the entry should not have been added.
        tree.unversion(['an-id'])
        tree.add(['b'], ['an-id'])
        self.assertTreeLayout([('', root_id), ('b', 'an-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'an-id')],
                              tree.basis_tree())

    def test_add_one_list(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add(['one'], ['one-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('one', 'one-id')], tree)

    def test_add_one_new_id(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add(['one'])
        root_id = tree.get_root_id()
        one_id = tree.path2id('one')

        self.assertTreeLayout([('', root_id), ('one', one_id)], tree)

    def test_add_unicode(self):
        tree = self.make_branch_and_tree('.')
        try:
            self.build_tree([u'f\xf6'])
        except UnicodeError:
            raise tests.TestSkipped('Filesystem does not support filename.')
        tree.add([u'f\xf6'])
        root_id = tree.get_root_id()
        foo_id = tree.path2id(u'f\xf6')

        self.assertTreeLayout([('', root_id), (u'f\xf6', foo_id)], tree)

    def test_add_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['dir'], ['dir-id'])
        tree.add(['dir/subdir'], ['subdir-id'])
        tree.add(['dir/subdir/foo'], ['foo-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('dir', 'dir-id'),
                               ('dir/subdir', 'subdir-id'),
                               ('dir/subdir/foo', 'foo-id')], tree)

    def test_add_multiple(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['a', 'b', 'dir', 'dir/subdir', 'dir/subdir/foo'],
                 ['a-id', 'b-id', 'dir-id', 'subdir-id', 'foo-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('dir', 'dir-id'), ('dir/subdir', 'subdir-id'),
                               ('dir/subdir/foo', 'foo-id')], tree)

    def test_add_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        root_id = tree.get_root_id()

        self.assertRaises(errors.NotVersionedError,
                          tree.add, ['dir/subdir'])
        self.assertTreeLayout([('', root_id)], tree)

    def test_add_after_remove(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        root_id = tree.get_root_id()
        tree.add(['dir'], ['dir-id'])
        tree.commit('dir', rev_id='rev-1')
        tree.unversion(['dir-id'])
        self.assertRaises(errors.NotVersionedError,
                          tree.add, ['dir/subdir'])

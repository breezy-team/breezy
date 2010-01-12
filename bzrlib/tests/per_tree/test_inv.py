# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Tests for interface conformance of inventories of trees."""


from cStringIO import StringIO
import os

from bzrlib import (
    tests,
    )
from bzrlib.tests import per_tree
from bzrlib.mutabletree import MutableTree
from bzrlib.tests import SymlinkFeature, TestSkipped
from bzrlib.transform import _PreviewTree
from bzrlib.uncommit import uncommit


def get_entry(tree, file_id):
    return tree.iter_entries_by_dir([file_id]).next()[1]


class TestPreviousHeads(per_tree.TestCaseWithTree):

    def setUp(self):
        # we want several inventories, that respectively
        # give use the following scenarios:
        # A) fileid not in any inventory (A),
        # B) fileid present in one inventory (B) and (A,B)
        # C) fileid present in two inventories, and they
        #   are not mutual descendents (B, C)
        # D) fileid present in two inventories and one is
        #   a descendent of the other. (B, D)
        super(TestPreviousHeads, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        self.build_tree(['file'])
        self.wt.commit('new branch', allow_pointless=True, rev_id='A')
        self.inv_A = self.branch.repository.get_inventory('A')
        self.wt.add(['file'], ['fileid'])
        self.wt.commit('add file', rev_id='B')
        self.inv_B = self.branch.repository.get_inventory('B')
        uncommit(self.branch, tree=self.wt)
        self.assertEqual(self.branch.revision_history(), ['A'])
        self.wt.commit('another add of file', rev_id='C')
        self.inv_C = self.branch.repository.get_inventory('C')
        self.wt.add_parent_tree_id('B')
        self.wt.commit('merge in B', rev_id='D')
        self.inv_D = self.branch.repository.get_inventory('D')
        self.tree = self.workingtree_to_test_tree(self.wt)
        self.tree.lock_read()
        self.addCleanup(self.tree.unlock)
        self.file_active = get_entry(self.tree, 'fileid')

    # TODO: test two inventories with the same file revision


class TestInventoryWithSymlinks(per_tree.TestCaseWithTree):

    _test_needs_features = [tests.SymlinkFeature]

    def setUp(self):
        per_tree.TestCaseWithTree.setUp(self)
        self.tree = self.get_tree_with_subdirs_and_all_content_types()
        self.tree.lock_read()
        self.addCleanup(self.tree.unlock)

    def test_symlink_target(self):
        if isinstance(self.tree, (MutableTree, _PreviewTree)):
            raise TestSkipped(
                'symlinks not accurately represented in working trees and'
                ' preview trees')
        entry = get_entry(self.tree, self.tree.path2id('symlink'))
        self.assertEqual(entry.symlink_target, 'link-target')

    def test_symlink_target_tree(self):
        self.assertEqual('link-target',
                         self.tree.get_symlink_target('symlink'))

    def test_kind_symlink(self):
        self.assertEqual('symlink', self.tree.kind('symlink'))
        self.assertIs(None, self.tree.get_file_size('symlink'))

    def test_symlink(self):
        entry = get_entry(self.tree, self.tree.path2id('symlink'))
        self.assertEqual(entry.kind, 'symlink')
        self.assertEqual(None, entry.text_size)


class TestInventory(per_tree.TestCaseWithTree):

    def test_paths2ids_recursive(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        work_tree.add(['dir', 'dir/file'], ['dir-id', 'file-id'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(set(['dir-id', 'file-id']), tree.paths2ids(['dir']))

    def test_paths2ids_forget_old(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        work_tree.add('file', 'first-id')
        work_tree.commit('commit old state')
        work_tree.remove('file')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(set([]), tree.paths2ids(['file'],
                         require_versioned=False))

    def _make_canonical_test_tree(self, commit=True):
        # make a tree used by all the 'canonical' tests below.
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        work_tree.add(['dir', 'dir/file'])
        if commit:
            work_tree.commit('commit 1')
        return work_tree

    def test_canonical_path(self):
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('dir/file',
                         work_tree.get_canonical_inventory_path('Dir/File'))

    def test_canonical_path_before_commit(self):
        work_tree = self._make_canonical_test_tree(False)
        # note: not committed.
        self.assertEqual('dir/file',
                         work_tree.get_canonical_inventory_path('Dir/File'))

    def test_canonical_path_dir(self):
        # check it works when asked for just the directory portion.
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('dir', work_tree.get_canonical_inventory_path('Dir'))

    def test_canonical_path_root(self):
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('', work_tree.get_canonical_inventory_path(''))
        self.assertEqual('/', work_tree.get_canonical_inventory_path('/'))

    def test_canonical_path_invalid_all(self):
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('foo/bar',
                         work_tree.get_canonical_inventory_path('foo/bar'))

    def test_canonical_invalid_child(self):
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('dir/None',
                         work_tree.get_canonical_inventory_path('Dir/None'))

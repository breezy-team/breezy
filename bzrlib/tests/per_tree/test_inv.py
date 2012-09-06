# Copyright (C) 2007-2010 Canonical Ltd
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


from bzrlib import (
    tests,
    )
from bzrlib.tests import (
    per_tree,
    )
from bzrlib.mutabletree import MutableTree
from bzrlib.tests import TestSkipped
from bzrlib.tree import InventoryTree
from bzrlib.transform import _PreviewTree
from bzrlib.uncommit import uncommit
from bzrlib.tests import (
    features,
    )


def get_entry(tree, file_id):
    return tree.iter_entries_by_dir([file_id]).next()[1]


class TestInventoryWithSymlinks(per_tree.TestCaseWithTree):

    _test_needs_features = [features.SymlinkFeature]

    def setUp(self):
        super(TestInventoryWithSymlinks, self).setUp()
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
        # XXX: this isn't actually guaranteed to return the class we want to
        # test -- mbp 2010-02-12
        return work_tree

    def test_canonical_path(self):
        work_tree = self._make_canonical_test_tree()
        if not isinstance(work_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")
        self.assertEqual('dir/file',
                         work_tree.get_canonical_inventory_path('Dir/File'))

    def test_canonical_path_before_commit(self):
        work_tree = self._make_canonical_test_tree(False)
        if not isinstance(work_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")        # note: not committed.
        self.assertEqual('dir/file',
                         work_tree.get_canonical_inventory_path('Dir/File'))

    def test_canonical_path_dir(self):
        # check it works when asked for just the directory portion.
        work_tree = self._make_canonical_test_tree()
        if not isinstance(work_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")
        self.assertEqual('dir', work_tree.get_canonical_inventory_path('Dir'))

    def test_canonical_path_root(self):
        work_tree = self._make_canonical_test_tree()
        if not isinstance(work_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")
        self.assertEqual('', work_tree.get_canonical_inventory_path(''))
        self.assertEqual('/', work_tree.get_canonical_inventory_path('/'))

    def test_canonical_path_invalid_all(self):
        work_tree = self._make_canonical_test_tree()
        if not isinstance(work_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")
        self.assertEqual('foo/bar',
                         work_tree.get_canonical_inventory_path('foo/bar'))

    def test_canonical_invalid_child(self):
        work_tree = self._make_canonical_test_tree()
        if not isinstance(work_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")
        self.assertEqual('dir/None',
                         work_tree.get_canonical_inventory_path('Dir/None'))

    def test_canonical_tree_name_mismatch(self):
        # see <https://bugs.launchpad.net/bzr/+bug/368931>
        # some of the trees we want to use can only exist on a disk, not in
        # memory - therefore we can only test this if the filesystem is
        # case-sensitive.
        self.requireFeature(features.case_sensitive_filesystem_feature)
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['test/', 'test/file', 'Test'])
        work_tree.add(['test/', 'test/file', 'Test'])

        test_tree = self._convert_tree(work_tree)
        if not isinstance(test_tree, InventoryTree):
            raise tests.TestNotApplicable(
                "test not applicable on non-inventory tests")
        test_tree.lock_read()
        self.addCleanup(test_tree.unlock)

        self.assertEqual(['test', 'test/file', 'Test', 'test/foo', 'Test/foo'],
            test_tree.get_canonical_inventory_paths(
                ['test', 'test/file', 'Test', 'test/foo', 'Test/foo']))

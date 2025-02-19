# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


from breezy.bzr import inventorytree
from breezy.tests import TestNotApplicable
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestNestedSupport(TestCaseWithWorkingTree):
    def make_branch_and_tree(self, path):
        tree = TestCaseWithWorkingTree.make_branch_and_tree(self, path)
        if not tree.supports_tree_reference():
            raise TestNotApplicable("Tree references not supported")
        return tree

    def test_set_get_inventory_tree_reference(self):
        """This tests that setting a tree reference is persistent."""
        tree = self.make_branch_and_tree(".")
        if not isinstance(tree, inventorytree.InventoryTree):
            raise TestNotApplicable("not an inventory tree")
        transform = tree.transform()
        trans_id = transform.new_directory("reference", transform.root, b"subtree-id")
        transform.set_tree_reference(b"subtree-revision", trans_id)
        transform.apply()
        tree = tree.controldir.open_workingtree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            b"subtree-revision",
            tree.root_inventory.get_entry(b"subtree-id").reference_revision,
        )

    def test_extract_while_locked(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(["subtree/"])
        tree.add(["subtree"])
        subtree = tree.extract("subtree")

    def prepare_with_subtree(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        subtree = self.make_branch_and_tree("subtree")
        subtree.commit("dummy")
        tree.add(["subtree"])
        return tree

    def test_comparison_data_does_not_autodetect_subtree(self):
        tree = self.prepare_with_subtree()
        (path, versioned, kind, ie) = list(tree.list_files("subtree"))[0]
        self.assertEqual("directory", tree._comparison_data(ie, "subtree")[0])

    def test_may_not_autodetect_subtree(self):
        tree = self.prepare_with_subtree()
        self.assertIn(tree.kind("subtree"), ("directory", "tree-reference"))

    def test_iter_entries_by_dir_autodetects_subtree(self):
        tree = self.prepare_with_subtree()
        path, ie = next(tree.iter_entries_by_dir(specific_files=["subtree"]))
        self.assertEqual("tree-reference", ie.kind)

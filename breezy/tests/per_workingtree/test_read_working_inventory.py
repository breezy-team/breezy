# Copyright (C) 2006 Canonical Ltd
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

"""Tests for WorkingTree.read_working_inventory."""

from breezy.bzr import inventory
from breezy.bzr.workingtree import InventoryModified, InventoryWorkingTree
from breezy.tests import TestNotApplicable
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestReadWorkingInventory(TestCaseWithWorkingTree):
    def test_trivial_read(self):
        tree = self.make_branch_and_tree("t1")
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable(
                "read_working_inventory not usable on non-inventory working trees"
            )
        tree.lock_read()
        self.assertIsInstance(tree.read_working_inventory(), inventory.Inventory)
        tree.unlock()

    def test_read_after_inventory_modification(self):
        tree = self.make_branch_and_tree("tree")
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable(
                "read_working_inventory not usable on non-inventory working trees"
            )
        # prepare for a series of changes that will modify the
        # inventory
        with tree.lock_write():
            tree.set_root_id(b"new-root")
            # having dirtied the inventory, we can now expect an
            # InventoryModified exception when doing a read_working_inventory()
            # OR, the call can be ignored and the changes preserved
            try:
                tree.read_working_inventory()
            except InventoryModified:
                pass
            else:
                self.assertEqual(b"new-root", tree.path2id(""))

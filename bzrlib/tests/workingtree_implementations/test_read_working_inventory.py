# (C) 2006 Canonical Ltd
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

"""Tests for WorkingTree.read_working_inventory."""

from bzrlib import errors, inventory
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestReadWorkingInventory(TestCaseWithWorkingTree):

    def test_trivial_read(self):
        tree = self.make_branch_and_tree('t1')
        self.assertIsInstance(tree.read_working_inventory(), inventory.Inventory)

    def test_read_after_inventory_modification(self):
        tree = self.make_branch_and_tree('tree')
        # prepare for a series of changes that will modify the 
        # inventory
        tree.lock_write()
        try:
            tree.set_root_id('new-root')
            # having dirtied the inventory, we can now expect an 
            # InventoryModified exception when doing a read_working_inventory()
            self.assertRaises(errors.InventoryModified, tree.read_working_inventory)
        finally:
            tree.unlock()

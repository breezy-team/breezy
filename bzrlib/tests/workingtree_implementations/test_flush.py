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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for WorkingTree.flush."""

from bzrlib import errors, inventory
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestFlush(TestCaseWithWorkingTree):

    def test_flush_fresh_tree(self):
        tree = self.make_branch_and_tree('t1')
        tree.lock_write()
        try:
            tree.flush()
        finally:
            tree.unlock()

    def test_flush_when_inventory_is_modified(self):
        # when doing a flush the inventory should be written if needed.
        # we test that by changing the inventory (using
        # _set_inventory for now until add etc have lazy writes of
        # the inventory on unlock).
        tree = self.make_branch_and_tree('tree')
        # prepare for a series of changes that will modify the 
        # inventory
        tree.lock_write()
        try:
            old_root = tree.get_root_id()
            tree.set_root_id('new-root')
            # to detect that the inventory is written by flush, we
            # first check that it was not written yet.
            reference_tree = tree.bzrdir.open_workingtree()
            self.assertEqual(old_root, reference_tree.get_root_id())
            # now flush the tree which should write the inventory.
            tree.flush()
            # and check it was written using another reference tree
            reference_tree = tree.bzrdir.open_workingtree()
            self.assertEqual('new-root', reference_tree.get_root_id())
        finally:
            tree.unlock()
            
    def test_flush_with_read_lock_fails(self):
        """Flush cannot be used during a read lock."""
        tree = self.make_branch_and_tree('t1')
        tree.lock_read()
        try:
            self.assertRaises(errors.NotWriteLocked, tree.flush)
        finally:
            tree.unlock()
            
    def test_flush_with_no_lock_fails(self):
        tree = self.make_branch_and_tree('t1')
        self.assertRaises(errors.NotWriteLocked, tree.flush)

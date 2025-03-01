# Copyright (C) 2017 Breezy Developers
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

"""Tests for interface conformance of 'WorkingTree.get_shelf_manager'."""

from breezy.tests.per_workingtree import TestCaseWithWorkingTree
from breezy.workingtree import ShelvingUnsupported


class TestShelfManager(TestCaseWithWorkingTree):
    def test_shelf_manager(self):
        tree = self.make_branch_and_tree(".")
        if self.workingtree_format.supports_store_uncommitted:
            self.assertIsNot(None, tree.get_shelf_manager())
        else:
            self.assertRaises(ShelvingUnsupported, tree.get_shelf_manager)

    # TODO(jelmer): Add more tests for shelf manager.

# Copyright (C) 2010 Canonical Ltd
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

"""Test that all trees support Tree.lock_read()."""

from breezy.tests.matchers import *
from breezy.tests.per_tree import TestCaseWithTree


class TestLocking(TestCaseWithTree):
    def test_lock_read(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.workingtree_to_test_tree(work_tree)
        self.assertThat(tree.lock_read, ReturnsUnlockable(tree))

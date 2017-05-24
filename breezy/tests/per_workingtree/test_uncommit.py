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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests of the parent related functions of WorkingTrees."""

from breezy import (
    uncommit,
    )
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestUncommit(TestCaseWithWorkingTree):

    def test_uncommit_to_null(self):
        tree = self.make_branch_and_tree('branch')
        tree.lock_write()
        revid = tree.commit('a revision')
        tree.unlock()
        uncommit.uncommit(tree.branch, tree=tree)
        self.assertEqual([], tree.get_parent_ids())

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

"""Tests for breezy.branch.InterBranch.get."""

from breezy import (
    branch,
    )
from breezy.tests.per_interbranch import (
    TestCaseWithInterBranch,
    )


class TestInterBranchGet(TestCaseWithInterBranch):

    def test_gets_right_inter(self):
        self.tree1 = self.make_from_branch_and_tree('tree1')
        branch2 = self.make_to_branch('tree2')
        self.assertIs(branch.InterBranch.get(
            self.tree1.branch, branch2).__class__,
            self.interbranch_class)

# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the WorkingTree.merge_from_branch api."""

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestMergeFromBranch(TestCaseWithWorkingTree):

    def create_two_trees_for_merging(self):
        """Create two trees that can be merged from.

        This sets self.tree_from, self.first_rev, self.tree_to, self.second_rev
        and self.to_second_rev.
        """
        self.tree_from = self.make_branch_and_tree('from')
        self.first_rev = self.tree_from.commit('first post')
        self.tree_to = self.tree_from.bzrdir.sprout('to').open_workingtree()
        self.second_rev = self.tree_from.commit('second rev', allow_pointless=True)
        self.to_second_rev = self.tree_to.commit('second rev', allow_pointless=True)

    def test_smoking_merge(self):
        """Smoke test of merge_from_branch."""
        self.create_two_trees_for_merging()
        self.tree_to.merge_from_branch(self.tree_from.branch)
        self.assertEqual([self.to_second_rev, self.second_rev],
            self.tree_to.get_parent_ids())

    def test_merge_to_revision(self):
        """Merge from a branch to a revision that is not the tip."""
        self.create_two_trees_for_merging()
        self.third_rev = self.tree_from.commit('real_tip')
        self.tree_to.merge_from_branch(self.tree_from.branch,
            to_revision=self.second_rev)
        self.assertEqual([self.to_second_rev, self.second_rev],
            self.tree_to.get_parent_ids())

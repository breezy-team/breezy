# Copyright (C) 2007, 2009-2012, 2016 Canonical Ltd
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

"""Tests for Branch.get_rev_id."""

from breezy.errors import RevnoOutOfBounds
from breezy.revision import NULL_REVISION
from breezy.tests import TestCaseWithTransport, TestNotApplicable
from breezy.tests.per_branch import TestCaseWithBranch


class TestGetRevid(TestCaseWithTransport):
    def test_empty_branch(self):
        # on an empty branch we want (0, NULL_REVISION)
        branch = self.make_branch("branch")
        self.assertEqual(NULL_REVISION, branch.get_rev_id(0))
        self.assertRaises(RevnoOutOfBounds, branch.get_rev_id, 1)
        self.assertRaises(RevnoOutOfBounds, branch.get_rev_id, -1)

    def test_non_empty_branch(self):
        # after the second commit we want (2, 'second-revid')
        tree = self.make_branch_and_tree("branch")
        revid1 = tree.commit("1st post")
        revid2 = tree.commit("2st post", allow_pointless=True)
        self.assertEqual(revid2, tree.branch.get_rev_id(2))
        self.assertEqual(revid1, tree.branch.get_rev_id(1))
        self.assertRaises(RevnoOutOfBounds, tree.branch.get_rev_id, 3)


class TestGetRevIdFromTip(TestCaseWithBranch):
    def test_history(self):
        tree = self.make_branch_and_tree("branch")
        revid1 = tree.commit("one")
        revid2 = tree.commit("two")
        revid3 = tree.commit("three")
        self.assertEqual(
            [revid3, revid2, revid1],
            [tree.branch.get_rev_id_from_tip(distance) for distance in range(3)],
        )

    def test_past_the_start(self):
        tree = self.make_branch_and_tree("branch")
        revid1 = tree.commit("one")
        self.assertEqual(
            [revid1, None, None],
            [tree.branch.get_rev_id_from_tip(distance) for distance in (0, 1, 5)],
        )

    def test_empty_branch(self):
        self.assertIsNone(self.make_branch("branch").get_rev_id_from_tip(0))

    def test_ghost(self):
        tree = self.make_branch_and_tree("branch")
        if not tree.branch.repository._format.supports_ghosts:
            raise TestNotApplicable("repository format does not support ghosts")
        tree.set_parent_ids([b"ghost"], allow_leftmost_as_ghost=True)
        tree.add("")
        revid1 = tree.commit("one")
        revid2 = tree.commit("two")
        self.assertEqual(
            [revid2, revid1, None],
            [tree.branch.get_rev_id_from_tip(distance) for distance in range(3)],
        )

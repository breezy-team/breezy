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

from breezy.tests import TestCaseWithTransport

from ...errors import RevnoOutOfBounds
from ...revision import NULL_REVISION


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

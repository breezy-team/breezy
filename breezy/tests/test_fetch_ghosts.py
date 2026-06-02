# Copyright (C) 2005 by Aaron Bentley

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

"""Tests for ghost revision fetching functionality."""

from ..fetch_ghosts import GhostFetcher
from . import TestCaseWithTransport


class TestFetchGhosts(TestCaseWithTransport):
    """Tests for the GhostFetcher functionality."""

    def prepare_with_ghosts(self):
        """Create a test repository with ghost revisions.

        Returns:
            The working tree with ghost revision references.
        """
        tree = self.make_branch_and_tree(".")
        tree.commit("rev1", rev_id=b"rev1-id")
        tree.set_parent_ids([b"rev1-id", b"ghost-id"])
        tree.commit("rev2")
        return tree

    def test_fetch_ghosts_failure(self):
        """Test that ghost fetching fails when ghosts are unavailable."""
        tree = self.prepare_with_ghosts()
        branch = self.make_branch("branch")
        GhostFetcher(tree.branch, branch).run()
        self.assertFalse(tree.branch.repository.has_revision(b"ghost-id"))

    def test_fetch_ghosts_success(self):
        """Test that ghost fetching succeeds when ghosts are available."""
        tree = self.prepare_with_ghosts()
        ghost_tree = self.make_branch_and_tree("ghost_tree")
        ghost_tree.commit("ghost", rev_id=b"ghost-id")
        GhostFetcher(tree.branch, ghost_tree.branch).run()
        self.assertTrue(tree.branch.repository.has_revision(b"ghost-id"))

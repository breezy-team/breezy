# Copyright (C) 2008 Canonical Ltd
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

"""Tests for MutableTree.

Most functionality of MutableTree is tested as part of WorkingTree.
"""

from .. import mutabletree, tests


class TestHooks(tests.TestCase):
    """Tests for MutableTreeHooks functionality."""

    def test_constructor(self):
        """Check that creating a MutableTreeHooks instance has the right
        defaults.
        """
        hooks = mutabletree.MutableTreeHooks()
        self.assertIn("start_commit", hooks, f"start_commit not in {hooks}")
        self.assertIn("post_commit", hooks, f"post_commit not in {hooks}")

    def test_installed_hooks_are_MutableTreeHooks(self):
        """The installed hooks object should be a MutableTreeHooks."""
        # the installed hooks are saved in self._preserved_hooks.
        self.assertIsInstance(
            self._preserved_hooks[mutabletree.MutableTree][1],
            mutabletree.MutableTreeHooks,
        )


class TestHasChanges(tests.TestCaseWithTransport):
    """Tests for the has_changes method of MutableTree."""

    def setUp(self):
        """Set up test environment with a branch and tree."""
        super().setUp()
        self.tree = self.make_branch_and_tree("tree")

    def test_with_uncommitted_changes(self):
        """Test that has_changes returns True when there are uncommitted changes."""
        self.build_tree(["tree/file"])
        self.tree.add("file")
        self.assertTrue(self.tree.has_changes())

    def test_with_pending_merges(self):
        """Test that has_changes returns True when there are pending merges."""
        self.tree.commit("first commit")
        other_tree = self.tree.controldir.sprout("other").open_workingtree()
        other_tree.commit("mergeable commit")
        self.tree.merge_from_branch(other_tree.branch)
        self.assertTrue(self.tree.has_changes())

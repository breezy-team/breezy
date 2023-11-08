# Copyright (C) 2006, 2008-2012, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the RevisionTree class."""

from breezy import revision
from breezy.tests import TestCaseWithTransport

from ..tree import FileTimestampUnavailable


class TestTreeWithCommits(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.t = self.make_branch_and_tree(".")
        self.rev_id = self.t.commit("foo", allow_pointless=True)
        self.rev_tree = self.t.branch.repository.revision_tree(self.rev_id)

    def test_empty_no_unknowns(self):
        self.assertEqual([], list(self.rev_tree.unknowns()))

    def test_no_conflicts(self):
        self.assertEqual([], list(self.rev_tree.conflicts()))

    def test_parents(self):
        """RevisionTree.parent_ids should match the revision graph."""
        # XXX: TODO: Should this be a repository_implementation test ?
        # at the end of the graph, we get []
        self.assertEqual([], self.rev_tree.get_parent_ids())
        # do a commit to look further up
        revid_2 = self.t.commit("bar", allow_pointless=True)
        self.assertEqual(
            [self.rev_id],
            self.t.branch.repository.revision_tree(revid_2).get_parent_ids(),
        )
        # TODO commit a merge and check it is reported correctly.

        # the parents for a revision_tree(NULL_REVISION) are []:
        self.assertEqual(
            [],
            self.t.branch.repository.revision_tree(
                revision.NULL_REVISION
            ).get_parent_ids(),
        )

    def test_empty_no_root(self):
        null_tree = self.t.branch.repository.revision_tree(revision.NULL_REVISION)
        self.assertIs(None, null_tree.path2id(""))

    def test_get_file_revision_root(self):
        self.assertEqual(self.rev_id, self.rev_tree.get_file_revision(""))

    def test_get_file_revision(self):
        self.build_tree_contents([("a", b"initial")])
        self.t.add(["a"])
        revid1 = self.t.commit("add a")
        revid2 = self.t.commit("another change", allow_pointless=True)
        tree = self.t.branch.repository.revision_tree(revid2)
        self.assertEqual(revid1, tree.get_file_revision("a"))

    def test_get_file_mtime_ghost(self):
        if not hasattr(self.rev_tree.root_inventory, "delete"):
            self.skipTest("Inventory does not support delete")
        path = next(iter(self.rev_tree.all_versioned_paths()))
        new_ie = self.rev_tree.root_inventory.get_entry(
            self.rev_tree.path2id(path)
        ).derive(revision=b"ghostrev")
        self.rev_tree.root_inventory.delete(new_ie.file_id)
        self.rev_tree.root_inventory.add(new_ie)
        self.assertRaises(FileTimestampUnavailable, self.rev_tree.get_file_mtime, path)

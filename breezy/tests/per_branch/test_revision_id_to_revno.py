# Copyright (C) 2007, 2009, 2011, 2016 Canonical Ltd
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

"""Tests for Branch.revision_id_to_revno()."""

from breezy import errors
from breezy.tests import TestNotApplicable
from breezy.tests.per_branch import TestCaseWithBranch


class TestRevisionIdToRevno(TestCaseWithBranch):
    def test_simple_revno(self):
        tree, revmap = self.create_tree_with_merge()
        the_branch = tree.branch

        self.assertEqual(0, the_branch.revision_id_to_revno(b"null:"))
        self.assertEqual(1, the_branch.revision_id_to_revno(revmap["1"]))
        self.assertEqual(2, the_branch.revision_id_to_revno(revmap["2"]))
        self.assertEqual(3, the_branch.revision_id_to_revno(revmap["3"]))

        self.assertRaises(
            errors.NoSuchRevision, the_branch.revision_id_to_revno, b"rev-none"
        )
        # revision_id_to_revno is defined as returning only integer revision
        # numbers, so non-mainline revisions get NoSuchRevision raised
        self.assertRaises(
            errors.NoSuchRevision, the_branch.revision_id_to_revno, revmap["1.1.1"]
        )

    def test_mainline_ghost(self):
        tree = self.make_branch_and_tree("tree1")
        if not tree.branch.repository._format.supports_ghosts:
            raise TestNotApplicable("repository format does not support ghosts")
        tree.set_parent_ids([b"spooky"], allow_leftmost_as_ghost=True)
        tree.add("")
        tree.commit("msg1", rev_id=b"rev1")
        tree.commit("msg2", rev_id=b"rev2")
        # Some older branch formats store the full known revision history
        # and thus can't distinguish between not being able to find a revno because of
        # a ghost and the revision not being on the mainline. As such,
        # allow both NoSuchRevision and GhostRevisionsHaveNoRevno here.
        self.assertRaises(
            (errors.NoSuchRevision, errors.GhostRevisionsHaveNoRevno),
            tree.branch.revision_id_to_revno,
            b"unknown",
        )
        self.assertEqual(1, tree.branch.revision_id_to_revno(b"rev1"))
        self.assertEqual(2, tree.branch.revision_id_to_revno(b"rev2"))

    def test_empty(self):
        branch = self.make_branch(".")
        self.assertRaises(
            errors.NoSuchRevision, branch.revision_id_to_revno, b"unknown"
        )
        self.assertEqual(0, branch.revision_id_to_revno(b"null:"))

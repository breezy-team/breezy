# Copyright (C) 2008, 2009, 2011, 2016 Canonical Ltd
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

"""Tests for branch implementations - test reconcile() functionality."""

from breezy import errors, reconcile
from breezy.tests import TestNotApplicable
from breezy.tests.per_branch import TestCaseWithBranch

from ...bzr.branch import BzrBranch
from ...symbol_versioning import deprecated_in


class TestBranchReconcile(TestCaseWithBranch):
    def test_reconcile_fixes_invalid_revhistory(self):
        if not isinstance(self.branch_format, BzrBranch):
            raise TestNotApplicable("test only applies to bzr formats")
        # Different formats have different ways of handling invalid revision
        # histories, so the setup portion is customized
        tree = self.make_branch_and_tree("test")
        r1 = tree.commit("one")
        tree.commit("two")
        tree.commit("three")
        r4 = tree.commit("four")
        # create an alternate branch
        tree.set_parent_ids([r1])
        tree.branch.set_last_revision_info(1, r1)
        r2b = tree.commit("two-b")

        # now go back and merge the commit
        tree.set_parent_ids([r4, r2b])
        tree.branch.set_last_revision_info(4, r4)

        r5 = tree.commit("five")
        # Now, try to set an invalid history
        try:
            self.applyDeprecated(
                deprecated_in((2, 4, 0)),
                tree.branch.set_revision_history,
                [r1, r2b, r5],
            )
            if tree.branch.last_revision_info() != (3, r5):
                # RemoteBranch silently corrects an impossible revision
                # history given to set_revision_history.  It can be tricked
                # with set_last_revision_info though.
                tree.branch.set_last_revision_info(3, r5)
        except errors.NotLefthandHistory:
            # Branch5 allows set_revision_history to be wrong
            # Branch6 raises NotLefthandHistory, but we can force bogus stuff
            # with set_last_revision_info
            tree.branch.set_last_revision_info(3, r5)

        self.assertEqual((3, r5), tree.branch.last_revision_info())
        reconciler = tree.branch.reconcile()
        self.assertEqual((5, r5), tree.branch.last_revision_info())
        self.assertIs(True, reconciler.fixed_history)

    def test_reconcile_returns_reconciler(self):
        a_branch = self.make_branch("a_branch")
        result = a_branch.reconcile()
        self.assertIsInstance(result, reconcile.ReconcileResult)
        # No history to fix
        self.assertIs(False, getattr(result, "fixed_history", False))

    def test_reconcile_supports_thorough(self):
        a_branch = self.make_branch("a_branch")
        a_branch.reconcile(thorough=False)
        a_branch.reconcile(thorough=True)

    def test_reconcile_handles_ghosts_in_revhistory(self):
        tree = self.make_branch_and_tree("test")
        if not tree.branch.repository._format.supports_ghosts:
            raise TestNotApplicable("repository format does not support ghosts")
        tree.set_parent_ids([b"spooky"], allow_leftmost_as_ghost=True)
        tree.commit("one")
        r2 = tree.commit("two")
        tree.branch.set_last_revision_info(2, r2)

        tree.branch.reconcile()
        self.assertEqual(r2, tree.branch.last_revision())

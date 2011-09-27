# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for Branch.iter_reverse_revision_history."""

from bzrlib.branch import BranchReferenceFormat
from bzrlib.errors import RevisionNotPresent
from bzrlib.tests import (
    per_branch,
    TestNotApplicable,
    TestSkipped,
    )


class IterReverseRevisionHistoryTests(per_branch.TestCaseWithBranch):
    """Tests for Branch.iter_reverse_revision_history()."""

    def test_null(self):
        b = self.get_branch()
        self.assertRaises(StopIteration,
            b.iter_reverse_revision_history().next)

    def test_single_rev(self):
        if isinstance(self.branch_format, BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise TestSkipped(
                "BranchBuilder can't make reference branches.")
        bb = self.make_branch_builder('.')
        bb.build_commit(rev_id='rev1')
        b = bb.get_branch()
        self.assertEquals(['rev1'],
            list(b.iter_reverse_revision_history()))

    def test_multiple_revs(self):
        if isinstance(self.branch_format, BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise TestSkipped(
                "BranchBuilder can't make reference branches.")
        bb = self.make_branch_builder('.')
        bb.start_series()
        bb.build_commit(rev_id='rev1')
        bb.build_commit(rev_id='rev2')
        bb.build_commit(rev_id='rev3')
        bb.finish_series()
        b = bb.get_branch()
        self.assertEquals(
            ['rev3', 'rev2', 'rev1'],
            list(b.iter_reverse_revision_history()))

    def test_parent_ghost(self):
        tree = self.make_branch_and_tree('.')
        if not tree.branch.repository._format.supports_ghosts:
            raise TestNotApplicable("repository format does not "
                "support ghosts")
        tree.add_parent_tree_id('ghost-revision',
                                allow_leftmost_as_ghost=True)
        tree.commit('first non-ghost commit', rev_id='non-ghost-revision')
        it = tree.branch.iter_reverse_revision_history()
        self.assertEquals('non-ghost-revision', it.next())
        self.assertRaises((RevisionNotPresent, StopIteration), it.next)

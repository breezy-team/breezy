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

"""Tests for breezy.branch.InterBranch.copy_content_into."""

from breezy import branch
from breezy.tests import TestNotApplicable
from breezy.tests.per_interbranch import (
    StubMatchingInter,
    StubWithFormat,
    TestCaseWithInterBranch,
)

from ...errors import NoRoundtrippingSupport


class TestCopyContentInto(TestCaseWithInterBranch):
    def test_contract_convenience_method(self):
        self.tree1 = self.make_from_branch_and_tree("tree1")
        rev1 = self.tree1.commit("one")
        branch2 = self.make_to_branch("tree2")
        try:
            branch2.repository.fetch(self.tree1.branch.repository)
        except NoRoundtrippingSupport as e:
            raise TestNotApplicable(
                f"lossless cross-vcs fetch from {self.tree1.branch!r} to {branch2!r} unsupported"
            ) from e
        self.tree1.branch.copy_content_into(branch2, revision_id=rev1)

    def test_inter_is_used(self):
        self.tree1 = self.make_from_branch_and_tree("tree1")
        self.addCleanup(branch.InterBranch.unregister_optimiser, StubMatchingInter)
        branch.InterBranch.register_optimiser(StubMatchingInter)
        del StubMatchingInter._uses[:]
        self.tree1.branch.copy_content_into(StubWithFormat(), revision_id=b"54")
        self.assertLength(1, StubMatchingInter._uses)
        use = StubMatchingInter._uses[0]
        self.assertEqual("copy_content_into", use[1])
        self.assertEqual(b"54", use[3]["revision_id"])
        del StubMatchingInter._uses[:]

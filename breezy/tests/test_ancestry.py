# Copyright (C) 2005-2009, 2011 Canonical Ltd
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

"""Tests for revision ancestry tracking.

This module tests that the ancestry of revisions is correctly tracked
and reported by repositories.
"""

from ..branchbuilder import BranchBuilder
from . import TestCaseWithMemoryTransport
from .matchers import MatchesAncestry


class TestAncestry(TestCaseWithMemoryTransport):
    """Tests for checking revision ancestry in repositories."""

    def test_straightline_ancestry(self):
        """Test ancestry file when just committing."""
        builder = BranchBuilder(self.get_transport())
        rev_id_one = builder.build_commit()
        rev_id_two = builder.build_commit()
        branch = builder.get_branch()
        self.assertThat(
            [rev_id_one, rev_id_two], MatchesAncestry(branch.repository, rev_id_two)
        )
        self.assertThat([rev_id_one], MatchesAncestry(branch.repository, rev_id_one))


# TODO: check that ancestry is updated to include indirectly merged revisions

# Copyright (C) 2005, 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from cStringIO import StringIO
import os
import sys

from bzrlib.tests import TestCaseWithMemoryTransport
from bzrlib.branch import Branch
from bzrlib.branchbuilder import BranchBuilder
from bzrlib.revision import is_ancestor


class TestAncestry(TestCaseWithMemoryTransport):

    def assertAncestryEqual(self, expected, revision_id, branch):
        """Assert that the ancestry of revision_id in branch is as expected."""
        ancestry = branch.repository.get_ancestry(revision_id)
        self.assertEqual(expected, ancestry)

    def test_straightline_ancestry(self):
        """Test ancestry file when just committing."""
        builder = BranchBuilder(self.get_transport())
        rev_id_one = builder.build_commit()
        rev_id_two = builder.build_commit()
        branch = builder.get_branch()
        self.assertAncestryEqual([None, rev_id_one, rev_id_two],
            rev_id_two, branch)
        self.assertAncestryEqual([None, rev_id_one], rev_id_one, branch)

    def test_none_is_ancestor_empty_branch(self):
        branch = self.make_branch('.')
        self.assertTrue(is_ancestor(None, None, branch))

    def test_none_is_ancestor_non_empty_branch(self):
        builder = BranchBuilder(self.get_transport())
        rev_id = builder.build_commit()
        branch = builder.get_branch()
        self.assertTrue(is_ancestor(None, None, branch))
        self.assertTrue(is_ancestor(rev_id, None, branch))
        self.assertFalse(is_ancestor(None, rev_id, branch))


# TODO: check that ancestry is updated to include indirectly merged revisions

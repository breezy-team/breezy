# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the BranchBuilder class."""

from bzrlib import (
    branch as _mod_branch,
    revision as _mod_revision,
    tests,
    )
from bzrlib.branchbuilder import BranchBuilder


class TestBranchBuilder(tests.TestCaseWithMemoryTransport):
    
    def test_create(self):
        """Test the constructor api."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        # we dont care if the branch has been built or not at this point.

    def test_get_branch(self):
        """get_branch returns the created branch."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        branch = builder.get_branch()
        self.assertIsInstance(branch, _mod_branch.Branch)
        self.assertEqual(self.get_transport().clone('foo').base,
            branch.base)
        self.assertEqual(
            (0, _mod_revision.NULL_REVISION),
            branch.last_revision_info())

    def test_format(self):
        """Making a BranchBuilder with a format option sets the branch type."""
        builder = BranchBuilder(self.get_transport(), format='dirstate-tags')
        branch = builder.get_branch()
        self.assertIsInstance(branch, _mod_branch.BzrBranch6)

    def test_build_one_commit(self):
        """doing build_commit causes a commit to happen."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id = builder.build_commit()
        branch = builder.get_branch()
        self.assertEqual((1, rev_id), branch.last_revision_info())
        self.assertEqual(
            'commit 1',
            branch.repository.get_revision(branch.last_revision()).message)

    def test_build_two_commits(self):
        """The second commit has the right parents and message."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id1 = builder.build_commit()
        rev_id2 = builder.build_commit()
        branch = builder.get_branch()
        self.assertEqual((2, rev_id2), branch.last_revision_info())
        self.assertEqual(
            'commit 2',
            branch.repository.get_revision(branch.last_revision()).message)
        self.assertEqual(
            [rev_id1],
            branch.repository.get_revision(branch.last_revision()).parent_ids)

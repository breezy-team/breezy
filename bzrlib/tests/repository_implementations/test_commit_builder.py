# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for repository commit builder."""

from bzrlib.repository import CommitBuilder
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository


class TestCommitBuilder(TestCaseWithRepository):

    def testGetCommitBuilder(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.assertIsInstance(builder, CommitBuilder)

    def testFinishInventory(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.assertIsInstance(builder.finish_inventory(), basestring)

    def testSetMessage(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([], revision_id="foo")
        builder.set_message("foobar")

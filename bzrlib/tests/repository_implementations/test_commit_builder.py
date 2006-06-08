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

from bzrlib.errors import UnsupportedOperation
from bzrlib.repository import CommitBuilder
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository


class TestCommitBuilder(TestCaseWithRepository):

    def test_get_commit_builder(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.assertIsInstance(builder, CommitBuilder)

    def test_finish_inventory(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        builder.finish_inventory()

    def test_commit_message(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        builder.finish_inventory()
        rev_id = builder.commit('foo bar blah')
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual('foo bar blah', rev.message)

    def test_commit_with_revision_id(self):
        tree = self.make_branch_and_tree(".")
        try:
            builder = tree.branch.get_commit_builder([], revision_id="foo")
        except UnsupportedOperation:
            # This format doesn't support supplied revision ids
            return
        builder.finish_inventory()
        self.assertEqual("foo", builder.commit('foo bar'))
        self.assertTrue(tree.branch.repository.has_revision("foo"))

    def test_commit(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        builder.finish_inventory()
        rev_id = builder.commit('foo bar')
        self.assertNotEqual(None, rev_id)
        self.assertTrue(tree.branch.repository.has_revision(rev_id))

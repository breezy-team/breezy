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

from bzrlib import inventory
from bzrlib.errors import UnsupportedOperation
from bzrlib.repository import CommitBuilder
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository


class TestCommitBuilder(TestCaseWithRepository):

    def test_get_commit_builder(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.assertIsInstance(builder, CommitBuilder)

    def record_root(self, builder, tree):
        if builder.record_root_entry is True:
            ie = tree.inventory.root
            parent_tree = tree.branch.repository.revision_tree(None)
            parent_invs = [parent_tree.inventory]
            builder.record_entry_contents(ie, parent_invs, '', tree)

    def test_finish_inventory(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.record_root(builder, tree)
        builder.finish_inventory()

    def test_commit_message(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.record_root(builder, tree)
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
        self.record_root(builder, tree)
        builder.finish_inventory()
        self.assertEqual("foo", builder.commit('foo bar'))
        self.assertTrue(tree.branch.repository.has_revision("foo"))
        # the revision id must be set on the inventory when saving it. This does not
        # precisely test that - a repository that wants to can add it on deserialisation,
        # but thats all the current contract guarantees anyway.
        self.assertEqual('foo', tree.branch.repository.get_inventory('foo').revision_id)

    def test_commit_without_root(self):
        """This should cause a deprecation warning, not an assertion failure"""
        tree = self.make_branch_and_tree(".")
        self.build_tree(['foo'])
        tree.add('foo', 'foo-id')
        entry = tree.inventory['foo-id']
        builder = tree.branch.get_commit_builder([])
        self.callDeprecated(['Root entry should be supplied to'
            ' record_entry_contents, as of bzr 0.10.'],
            builder.record_entry_contents, entry, [], 'foo', tree)
        builder.finish_inventory()
        rev_id = builder.commit('foo bar')

    def test_commit(self):
        tree = self.make_branch_and_tree(".")
        builder = tree.branch.get_commit_builder([])
        self.record_root(builder, tree)
        builder.finish_inventory()
        rev_id = builder.commit('foo bar')
        self.assertNotEqual(None, rev_id)
        self.assertTrue(tree.branch.repository.has_revision(rev_id))
        # the revision id must be set on the inventory when saving it. This does not
        # precisely test that - a repository that wants to can add it on deserialisation,
        # but thats all the current contract guarantees anyway.
        self.assertEqual(rev_id, tree.branch.repository.get_inventory(rev_id).revision_id)

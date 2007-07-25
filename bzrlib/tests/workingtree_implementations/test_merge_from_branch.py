# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for the WorkingTree.merge_from_branch api."""

import os

from bzrlib import (
    errors,
    merge
    )
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestMergeFromBranch(TestCaseWithWorkingTree):

    def create_two_trees_for_merging(self):
        """Create two trees that can be merged from.

        This sets self.tree_from, self.first_rev, self.tree_to, self.second_rev
        and self.to_second_rev.
        """
        self.tree_from = self.make_branch_and_tree('from')
        self.first_rev = self.tree_from.commit('first post')
        self.tree_to = self.tree_from.bzrdir.sprout('to').open_workingtree()
        self.second_rev = self.tree_from.commit('second rev', allow_pointless=True)
        self.to_second_rev = self.tree_to.commit('second rev', allow_pointless=True)

    def test_smoking_merge(self):
        """Smoke test of merge_from_branch."""
        self.create_two_trees_for_merging()
        self.tree_to.merge_from_branch(self.tree_from.branch)
        self.assertEqual([self.to_second_rev, self.second_rev],
            self.tree_to.get_parent_ids())

    def test_merge_to_revision(self):
        """Merge from a branch to a revision that is not the tip."""
        self.create_two_trees_for_merging()
        self.third_rev = self.tree_from.commit('real_tip')
        self.tree_to.merge_from_branch(self.tree_from.branch,
            to_revision=self.second_rev)
        self.assertEqual([self.to_second_rev, self.second_rev],
            self.tree_to.get_parent_ids())

    def test_compare_after_merge(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'text-a')])
        tree_a.add('file')
        tree_a.commit('added file')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        os.unlink('tree_a/file')
        tree_a.commit('deleted file')
        self.build_tree_contents([('tree_b/file', 'text-b')])
        tree_b.commit('changed file')
        tree_a.merge_from_branch(tree_b.branch)
        tree_a.lock_read()
        self.addCleanup(tree_a.unlock)
        list(tree_a._iter_changes(tree_a.basis_tree()))

    def test_merge_empty(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'text-a')])
        tree_a.add('file')
        tree_a.commit('added file')
        tree_b = self.make_branch_and_tree('treeb')
        self.assertRaises(errors.NoCommits, tree_a.merge_from_branch,
                          tree_b.branch)
        tree_b.merge_from_branch(tree_a.branch)

    def test_merge_base(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'text-a')])
        tree_a.add('file')
        tree_a.commit('added file', rev_id='rev_1')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        os.unlink('tree_a/file')
        tree_a.commit('deleted file')
        self.build_tree_contents([('tree_b/file', 'text-b')])
        tree_b.commit('changed file')
        self.assertRaises(errors.PointlessMerge, tree_a.merge_from_branch,
            tree_b.branch, from_revision=tree_b.branch.last_revision())
        tree_a.merge_from_branch(tree_b.branch, from_revision='rev_1')
        tree_a.lock_read()
        self.addCleanup(tree_a.unlock)
        changes = list(tree_a._iter_changes(tree_a.basis_tree()))
        self.assertEqual(1, len(changes))

    def test_merge_type(self):
        this = self.make_branch_and_tree('this')
        self.build_tree_contents([('this/foo', 'foo')])
        this.add('foo', 'foo-id')
        this.commit('added foo')
        other = this.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/foo', 'bar')])
        other.commit('content -> bar')
        self.build_tree_contents([('this/foo', 'baz')])
        this.commit('content -> baz')
        class QuxMerge(merge.Merge3Merger):
            def text_merge(self, file_id, trans_id):
                self.tt.create_file('qux', trans_id)
        this.merge_from_branch(other.branch, merge_type=QuxMerge)
        self.assertEqual('qux', this.get_file_text('foo-id'))

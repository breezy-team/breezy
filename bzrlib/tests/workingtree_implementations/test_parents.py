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

"""Tests of the parent related functions of WorkingTrees."""

import os

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.branch import Branch
from bzrlib.revision import Revision
from bzrlib.uncommit import uncommit
import bzrlib.xml5


class TestParents(TestCaseWithWorkingTree):

    def assertConsistentParents(self, expected, tree):
        self.assertEqual(expected, tree.get_parent_ids())
        if expected == []:
            self.assertEqual(None, tree.last_revision())
        else:
            self.assertEqual(expected[0], tree.last_revision())
        self.assertEqual(expected[1:], tree.pending_merges())


class TestSetParents(TestParents):

    def test_set_no_parents(self):
        t = self.make_branch_and_tree('.')
        t.set_parent_trees([])
        self.assertEqual([], t.get_parent_ids())
        # now give it a real parent, and then set it to no parents again.
        t.commit('first post')
        t.set_parent_trees([])
        self.assertConsistentParents([], t)

    def test_set_one_ghost_parent(self):
        t = self.make_branch_and_tree('.')
        t.set_parent_trees([('missing-revision-id', None)])
        self.assertConsistentParents(['missing-revision-id'], t)

    def test_set_two_parents_one_ghost(self):
        t = self.make_branch_and_tree('.')
        revision_in_repo = t.commit('first post')
        # remove the tree's history
        uncommit(t.branch, tree=t)
        rev_tree = t.branch.repository.revision_tree(revision_in_repo)
        t.set_parent_trees([(revision_in_repo, rev_tree),
            ('another-missing', None)])
        self.assertConsistentParents([revision_in_repo, 'another-missing'], t)

    def test_set_three_parents(self):
        t = self.make_branch_and_tree('.')
        first_revision = t.commit('first post')
        uncommit(t.branch, tree=t)
        second_revision = t.commit('second post')
        uncommit(t.branch, tree=t)
        third_revision = t.commit('third post')
        uncommit(t.branch, tree=t)
        rev_tree1 = t.branch.repository.revision_tree(first_revision)
        rev_tree2 = t.branch.repository.revision_tree(second_revision)
        rev_tree3 = t.branch.repository.revision_tree(third_revision)
        t.set_parent_trees([(first_revision, rev_tree1),
            (second_revision, rev_tree2),
            (third_revision, rev_tree3)])
        self.assertConsistentParents(
            [first_revision, second_revision, third_revision], t)

    def test_set_no_parents_ids(self):
        t = self.make_branch_and_tree('.')
        t.set_parent_ids([])
        self.assertEqual([], t.get_parent_ids())
        # now give it a real parent, and then set it to no parents again.
        t.commit('first post')
        t.set_parent_ids([])
        self.assertConsistentParents([], t)

    def test_set_one_ghost_parent_ids(self):
        t = self.make_branch_and_tree('.')
        t.set_parent_ids(['missing-revision-id'])
        self.assertConsistentParents(['missing-revision-id'], t)

    def test_set_two_parents_one_ghost_ids(self):
        t = self.make_branch_and_tree('.')
        revision_in_repo = t.commit('first post')
        # remove the tree's history
        uncommit(t.branch, tree=t)
        rev_tree = t.branch.repository.revision_tree(revision_in_repo)
        t.set_parent_ids([revision_in_repo, 'another-missing'])
        self.assertConsistentParents([revision_in_repo, 'another-missing'], t)

    def test_set_three_parents_ids(self):
        t = self.make_branch_and_tree('.')
        first_revision = t.commit('first post')
        uncommit(t.branch, tree=t)
        second_revision = t.commit('second post')
        uncommit(t.branch, tree=t)
        third_revision = t.commit('third post')
        uncommit(t.branch, tree=t)
        rev_tree1 = t.branch.repository.revision_tree(first_revision)
        rev_tree2 = t.branch.repository.revision_tree(second_revision)
        rev_tree3 = t.branch.repository.revision_tree(third_revision)
        t.set_parent_ids([first_revision, second_revision, third_revision])
        self.assertConsistentParents(
            [first_revision, second_revision, third_revision], t)


class TestAddParent(TestParents):

    def test_add_first_parent_id(self):
        """Test adding the first parent id"""
        tree = self.make_branch_and_tree('.')
        first_revision = tree.commit('first post')
        uncommit(tree.branch, tree=tree)
        tree.add_parent_tree_id(first_revision)
        self.assertConsistentParents([first_revision], tree)
        
    def test_add_first_parent_id_ghost(self):
        """Test adding the first parent id - as a ghost"""
        tree = self.make_branch_and_tree('.')
        tree.add_parent_tree_id('first-revision')
        self.assertConsistentParents(['first-revision'], tree)
        
    def test_add_second_parent_id(self):
        """Test adding the second parent id"""
        tree = self.make_branch_and_tree('.')
        first_revision = tree.commit('first post')
        uncommit(tree.branch, tree=tree)
        second_revision = tree.commit('second post')
        tree.add_parent_tree_id(first_revision)
        self.assertConsistentParents([second_revision, first_revision], tree)
        
    def test_add_second_parent_id_ghost(self):
        """Test adding the second parent id - as a ghost"""
        tree = self.make_branch_and_tree('.')
        first_revision = tree.commit('first post')
        tree.add_parent_tree_id('second')
        self.assertConsistentParents([first_revision, 'second'], tree)
        
    def test_add_first_parent_tree(self):
        """Test adding the first parent id"""
        tree = self.make_branch_and_tree('.')
        first_revision = tree.commit('first post')
        uncommit(tree.branch, tree=tree)
        tree.add_parent_tree((first_revision,
            tree.branch.repository.revision_tree(first_revision)))
        self.assertConsistentParents([first_revision], tree)
        
    def test_add_first_parent_tree_ghost(self):
        """Test adding the first parent id - as a ghost"""
        tree = self.make_branch_and_tree('.')
        tree.add_parent_tree(('first-revision', None))
        self.assertConsistentParents(['first-revision'], tree)
        
    def test_add_second_parent_tree(self):
        """Test adding the second parent id"""
        tree = self.make_branch_and_tree('.')
        first_revision = tree.commit('first post')
        uncommit(tree.branch, tree=tree)
        second_revision = tree.commit('second post')
        tree.add_parent_tree((first_revision,
            tree.branch.repository.revision_tree(first_revision)))
        self.assertConsistentParents([second_revision, first_revision], tree)
        
    def test_add_second_parent_tree_ghost(self):
        """Test adding the second parent id - as a ghost"""
        tree = self.make_branch_and_tree('.')
        first_revision = tree.commit('first post')
        tree.add_parent_tree(('second', None))
        self.assertConsistentParents([first_revision, 'second'], tree)

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

import os

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.branch import Branch
from bzrlib.revision import Revision
from bzrlib.uncommit import uncommit
import bzrlib.xml5


class TestSetParents(TestCaseWithWorkingTree):

    def test_set_no_parents(self):
        t = self.make_branch_and_tree('.')
        t.set_parent_trees([])
        self.assertEqual([], t.get_parent_ids())
        # now give it a real parent, and then set it to no parents again.
        t.commit('first post')
        t.set_parent_trees([])
        self.assertEqual([], t.get_parent_ids())
        self.assertEqual(None, t.last_revision())
        self.assertEqual([], t.pending_merges())

    def test_set_one_ghost_parent(self):
        t = self.make_branch_and_tree('.')
        t.set_parent_trees([('missing-revision-id', None)])
        self.assertEqual(['missing-revision-id'], t.get_parent_ids())
        self.assertEqual('missing-revision-id', t.last_revision())
        self.assertEqual([], t.pending_merges())

    def test_set_two_parents_one_ghost(self):
        t = self.make_branch_and_tree('.')
        revision_in_repo = t.commit('first post')
        # remove the tree's history
        uncommit(t.branch, tree=t)
        rev_tree = t.branch.repository.revision_tree(revision_in_repo)
        t.set_parent_trees([(revision_in_repo, rev_tree),
            ('another-missing', None)])
        self.assertEqual([revision_in_repo, 'another-missing'],
            t.get_parent_ids())
        self.assertEqual(revision_in_repo, t.last_revision())
        self.assertEqual(['another-missing'], t.pending_merges())

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
        self.assertEqual([first_revision, second_revision, third_revision],
            t.get_parent_ids())
        self.assertEqual(first_revision, t.last_revision())
        self.assertEqual([second_revision, third_revision], t.pending_merges())

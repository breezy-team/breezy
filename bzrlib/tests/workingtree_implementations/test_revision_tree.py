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

"""Tests for WorkingTree.revision_tree.

These tests are in addition to the tests from 
tree_implementations.test_revision_tree which cover the behaviour expected from
all Trees. WorkingTrees implement the revision_tree api to allow access to
cached data, but we don't require that all WorkingTrees have such a cache,
so these tests are testing that when there is a cache, it performs correctly.
"""

from bzrlib import errors
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestRevisionTree(TestCaseWithWorkingTree):

    def test_get_zeroth_basis_tree_via_revision_tree(self):
        tree = self.make_branch_and_tree('.')
        try:
            revision_tree = tree.revision_tree(tree.last_revision())
        except errors.NoSuchRevision:
            # its ok for a working tree to not cache trees, so just return.
            return
        basis_tree = tree.basis_tree()
        self.assertTreesEqual(revision_tree, basis_tree)

    def test_get_nonzeroth_basis_tree_via_revision_tree(self):
        tree = self.make_branch_and_tree('.')
        revision1 = tree.commit('first post')
        revision_tree = tree.revision_tree(revision1)
        basis_tree = tree.basis_tree()
        self.assertTreesEqual(revision_tree, basis_tree)

    def test_get_pending_merge_revision_tree(self):
        tree = self.make_branch_and_tree('tree1')
        tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        revision1 = tree2.commit('commit in branch', allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        try:
            cached_revision_tree = tree.revision_tree(revision1)
        except errors.NoSuchRevision:
            # its ok for a working tree to not cache trees, so just return.
            return
        real_revision_tree = tree2.basis_tree()
        self.assertTreesEqual(real_revision_tree, cached_revision_tree)

    def test_get_uncached_basis_via_revision_tree(self):
        # The basis_tree method returns an empty tree when you ask for the
        # basis if the basis is not cached, and it is a ghost. However the
        # revision_tree method should always raise when a request tree is not
        # cached, so we force this by setting a basis that is a ghost and
        # thus cannot be cached.
        tree = self.make_branch_and_tree('.')
        tree.set_parent_ids(['a-ghost'], allow_leftmost_as_ghost=True)
        self.assertRaises(errors.NoSuchRevision, tree.revision_tree, 'a-ghost')

# Copyright (C) 2006, 2007, 2009, 2010 Canonical Ltd
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

"""Tests for WorkingTree.revision_tree.

These tests are in addition to the tests from
per_tree.test_revision_tree which cover the behaviour expected from
all Trees. WorkingTrees implement the revision_tree api to allow access to
cached data, but we don't require that all WorkingTrees have such a cache,
so these tests are testing that when there is a cache, it performs correctly.
"""

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.tests import per_workingtree


class TestRevisionTree(per_workingtree.TestCaseWithWorkingTree):

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

    def test_revision_tree_different_root_id(self):
        """A revision tree might have a very different root."""
        tree = self.make_branch_and_tree('tree1')
        tree.set_root_id('one')
        rev1 = tree.commit('first post')
        tree.set_root_id('two')
        try:
            cached_revision_tree = tree.revision_tree(rev1)
        except errors.NoSuchRevision:
            # its ok for a working tree to not cache trees, so just return.
            return
        repository_revision_tree = tree.branch.repository.revision_tree(rev1)
        self.assertTreesEqual(repository_revision_tree, cached_revision_tree)


class TestRevisionTreeKind(per_workingtree.TestCaseWithWorkingTree):

    def make_branch_with_merged_deletions(self, relpath='tree'):
        tree = self.make_branch_and_tree(relpath)
        files = ['a', 'b/', 'b/c']
        self.build_tree(files, line_endings='binary',
                        transport=tree.bzrdir.root_transport)
        tree.set_root_id('root-id')
        tree.add(files, ['a-id', 'b-id', 'c-id'])
        tree.commit('a, b and b/c', rev_id='base')
        tree2 = tree.bzrdir.sprout(relpath + '2').open_workingtree()
        # Delete 'a' in tree
        tree.remove('a', keep_files=False)
        tree.commit('remove a', rev_id='this')
        # Delete 'c' in tree2
        tree2.remove('b/c', keep_files=False)
        tree2.remove('b', keep_files=False)
        tree2.commit('remove b/c', rev_id='other')
        # Merge tree2 into tree
        tree.merge_from_branch(tree2.branch)
        return tree

    def test_kind_parent_tree(self):
        tree = self.make_branch_with_merged_deletions()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        parents = tree.get_parent_ids()
        self.assertEqual(['this', 'other'], parents)
        basis = tree.revision_tree(parents[0])
        basis.lock_read()
        self.addCleanup(basis.unlock)
        self.assertRaises(errors.NoSuchId, basis.kind, 'a-id')
        self.assertEqual(['directory', 'file'],
                         [basis.kind('b-id'), basis.kind('c-id')])
        try:
            other = tree.revision_tree(parents[1])
        except errors.NoSuchRevisionInTree:
            raise tests.TestNotApplicable(
                'Tree type %s caches only the basis revision tree.'
                % type(tree))
        other.lock_read()
        self.addCleanup(other.unlock)
        self.assertRaises(errors.NoSuchId, other.kind, 'b-id')
        self.assertRaises(errors.NoSuchId, other.kind, 'c-id')
        self.assertEqual('file', other.kind('a-id'))

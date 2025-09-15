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

from breezy import errors, tests
from breezy import transport as _mod_transport
from breezy.tests import per_workingtree


class TestRevisionTree(per_workingtree.TestCaseWithWorkingTree):
    def test_get_zeroth_basis_tree_via_revision_tree(self):
        tree = self.make_branch_and_tree(".")
        try:
            revision_tree = tree.revision_tree(tree.last_revision())
        except errors.NoSuchRevision:
            # its ok for a working tree to not cache trees, so just return.
            return
        basis_tree = tree.basis_tree()
        self.assertTreesEqual(revision_tree, basis_tree)

    def test_get_nonzeroth_basis_tree_via_revision_tree(self):
        tree = self.make_branch_and_tree(".")
        revision1 = tree.commit("first post")
        revision_tree = tree.revision_tree(revision1)
        basis_tree = tree.basis_tree()
        self.assertTreesEqual(revision_tree, basis_tree)

    def test_get_pending_merge_revision_tree(self):
        tree = self.make_branch_and_tree("tree1")
        tree.commit("first post")
        tree2 = tree.controldir.sprout("tree2").open_workingtree()
        revision1 = tree2.commit("commit in branch", allow_pointless=True)
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
        tree = self.make_branch_and_tree(".")
        if not tree.branch.repository._format.supports_ghosts:
            self.skipTest("format does not support ghosts")
        tree.set_parent_ids([b"a-ghost"], allow_leftmost_as_ghost=True)
        self.assertRaises(errors.NoSuchRevision, tree.revision_tree, b"a-ghost")

    def test_revision_tree_different_root_id(self):
        """A revision tree might have a very different root."""
        tree = self.make_branch_and_tree("tree1")
        if not tree.supports_setting_file_ids():
            raise tests.TestNotApplicable("tree does not support setting file ids")
        tree.set_root_id(b"one")
        rev1 = tree.commit("first post")
        tree.set_root_id(b"two")
        try:
            cached_revision_tree = tree.revision_tree(rev1)
        except errors.NoSuchRevision:
            # its ok for a working tree to not cache trees, so just return.
            return
        repository_revision_tree = tree.branch.repository.revision_tree(rev1)
        self.assertTreesEqual(repository_revision_tree, cached_revision_tree)


class TestRevisionTreeKind(per_workingtree.TestCaseWithWorkingTree):
    def make_branch_with_merged_deletions(self, relpath="tree"):
        tree = self.make_branch_and_tree(relpath)
        files = ["a", "b/", "b/c"]
        self.build_tree(
            files, line_endings="binary", transport=tree.controldir.root_transport
        )
        tree.add(files)
        base_revid = tree.commit("a, b and b/c")
        tree2 = tree.controldir.sprout(relpath + "2").open_workingtree()
        # Delete 'a' in tree
        tree.remove("a", keep_files=False)
        this_revid = tree.commit("remove a")
        # Delete 'c' in tree2
        tree2.remove("b/c", keep_files=False)
        tree2.remove("b", keep_files=False)
        other_revid = tree2.commit("remove b/c")
        # Merge tree2 into tree
        tree.merge_from_branch(tree2.branch)
        return tree, [base_revid, this_revid, other_revid]

    def test_kind_parent_tree(self):
        (
            tree,
            [_base_revid, this_revid, other_revid],
        ) = self.make_branch_with_merged_deletions()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        parents = tree.get_parent_ids()
        self.assertEqual([this_revid, other_revid], parents)
        basis = tree.revision_tree(parents[0])
        basis.lock_read()
        self.addCleanup(basis.unlock)
        self.assertRaises(_mod_transport.NoSuchFile, basis.kind, "a")
        self.assertEqual(["directory", "file"], [basis.kind("b"), basis.kind("b/c")])
        try:
            other = tree.revision_tree(parents[1])
        except errors.NoSuchRevisionInTree as err:
            raise tests.TestNotApplicable(
                f"Tree type {type(tree)} caches only the basis revision tree."
            ) from err
        other.lock_read()
        self.addCleanup(other.unlock)
        self.assertRaises(_mod_transport.NoSuchFile, other.kind, "b")
        self.assertRaises(_mod_transport.NoSuchFile, other.kind, "c")
        self.assertEqual("file", other.kind("a"))

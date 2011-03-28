# Copyright (C) 2011 Canonical Ltd
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

"""Tests for repository implementations - tests a repository format."""

from bzrlib import (
    errors,
    tests,
    versionedfile,
    )

from bzrlib.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
    )
from bzrlib.tests.scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


class TestRepository(TestCaseWithRepository):

    scenarios = all_repository_vf_format_scenarios()

    def test_attribute_inventories_store(self):
        """Test the existence of the inventories attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.inventories, versionedfile.VersionedFiles)

    def test_attribute_inventories_basics(self):
        """Test basic aspects of the inventories attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        rev_id = (tree.commit('a'),)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(set([rev_id]), set(repo.inventories.keys()))

    def test_attribute_revision_store(self):
        """Test the existence of the revisions attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.revisions,
            versionedfile.VersionedFiles)

    def test_attribute_revision_store_basics(self):
        """Test the basic behaviour of the revisions attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        repo.lock_write()
        try:
            self.assertEqual(set(), set(repo.revisions.keys()))
            revid = (tree.commit("foo"),)
            self.assertEqual(set([revid]), set(repo.revisions.keys()))
            self.assertEqual({revid:()},
                repo.revisions.get_parent_map([revid]))
        finally:
            repo.unlock()
        tree2 = self.make_branch_and_tree('tree2')
        tree2.pull(tree.branch)
        left_id = (tree2.commit('left'),)
        right_id = (tree.commit('right'),)
        tree.merge_from_branch(tree2.branch)
        merge_id = (tree.commit('merged'),)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(set([revid, left_id, right_id, merge_id]),
            set(repo.revisions.keys()))
        self.assertEqual({revid:(), left_id:(revid,), right_id:(revid,),
             merge_id:(right_id, left_id)},
            repo.revisions.get_parent_map(repo.revisions.keys()))

    def test_attribute_signature_store(self):
        """Test the existence of the signatures attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.signatures,
            versionedfile.VersionedFiles)

    def test_exposed_versioned_files_are_marked_dirty(self):
        repo = self.make_repository('.')
        repo.lock_write()
        signatures = repo.signatures
        revisions = repo.revisions
        inventories = repo.inventories
        repo.unlock()
        self.assertRaises(errors.ObjectNotLocked,
            signatures.keys)
        self.assertRaises(errors.ObjectNotLocked,
            revisions.keys)
        self.assertRaises(errors.ObjectNotLocked,
            inventories.keys)
        self.assertRaises(errors.ObjectNotLocked,
            signatures.add_lines, ('foo',), [], [])
        self.assertRaises(errors.ObjectNotLocked,
            revisions.add_lines, ('foo',), [], [])
        self.assertRaises(errors.ObjectNotLocked,
            inventories.add_lines, ('foo',), [], [])


class TestCaseWithComplexRepository(TestCaseWithRepository):

    scenarios = all_repository_vf_format_scenarios()

    def setUp(self):
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        # this may need some generalising for knits.
        tree_a.lock_write()
        try:
            tree_a.branch.repository.start_write_group()
            try:
                inv_file = tree_a.branch.repository.inventories
                inv_file.add_lines(('orphan',), [], [])
            except:
                tree_a.branch.repository.commit_write_group()
                raise
            else:
                tree_a.branch.repository.abort_write_group()
        finally:
            tree_a.unlock()
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)
        # add a reference to a ghost
        tree_a.add_parent_tree_id('ghost1')
        try:
            tree_a.commit('rev3', rev_id='rev3', allow_pointless=True)
        except errors.RevisionNotPresent:
            raise tests.TestNotApplicable(
                "Cannot test with ghosts for this format.")
        # add another reference to a ghost, and a second ghost.
        tree_a.add_parent_tree_id('ghost1')
        tree_a.add_parent_tree_id('ghost2')
        tree_a.commit('rev4', rev_id='rev4', allow_pointless=True)

    def test_revision_trees(self):
        revision_ids = ['rev1', 'rev2', 'rev3', 'rev4']
        repository = self.bzrdir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        trees1 = list(repository.revision_trees(revision_ids))
        trees2 = [repository.revision_tree(t) for t in revision_ids]
        self.assertEqual(len(trees1), len(trees2))
        for tree1, tree2 in zip(trees1, trees2):
            self.assertFalse(tree2.changes_from(tree1).has_changed())

    def test_get_deltas_for_revisions(self):
        repository = self.bzrdir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        revisions = [repository.get_revision(r) for r in
                     ['rev1', 'rev2', 'rev3', 'rev4']]
        deltas1 = list(repository.get_deltas_for_revisions(revisions))
        deltas2 = [repository.get_revision_delta(r.revision_id) for r in
                   revisions]
        self.assertEqual(deltas1, deltas2)

    def test_all_revision_ids(self):
        # all_revision_ids -> all revisions
        self.assertEqual(set(['rev1', 'rev2', 'rev3', 'rev4']),
            set(self.bzrdir.open_repository().all_revision_ids()))

    def test_get_ancestry_missing_revision(self):
        # get_ancestry(revision that is in some data but not fully installed
        # -> NoSuchRevision
        self.assertRaises(errors.NoSuchRevision,
                          self.bzrdir.open_repository().get_ancestry, 'orphan')

    def test_get_unordered_ancestry(self):
        repo = self.bzrdir.open_repository()
        self.assertEqual(set(repo.get_ancestry('rev3')),
                         set(repo.get_ancestry('rev3', topo_sorted=False)))

    def test_reserved_id(self):
        repo = self.make_repository('repository')
        repo.lock_write()
        repo.start_write_group()
        try:
            self.assertRaises(errors.ReservedId, repo.add_inventory,
                'reserved:', None, None)
            self.assertRaises(errors.ReservedId, repo.add_inventory_by_delta,
                "foo", [], 'reserved:', None)
            self.assertRaises(errors.ReservedId, repo.add_revision,
                'reserved:', None)
        finally:
            repo.abort_write_group()
            repo.unlock()

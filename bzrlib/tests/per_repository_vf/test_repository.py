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

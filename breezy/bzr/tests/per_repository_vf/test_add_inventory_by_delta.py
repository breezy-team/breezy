# Copyright (C) 2008 Canonical Ltd
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

"""Tests for Repository.add_inventory_by_delta."""

from breezy import errors, revision
from breezy.bzr.inventory_delta import InventoryDelta
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)

from ....tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestAddInventoryByDelta(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def _get_repo_in_write_group(self, path="repository"):
        repo = self.make_repository(path)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        return repo

    def test_basis_missing_errors(self):
        repo = self._get_repo_in_write_group()
        try:
            self.assertRaises(
                errors.NoSuchRevision,
                repo.add_inventory_by_delta,
                b"missing-revision",
                [],
                b"new-revision",
                [b"missing-revision"],
            )
        finally:
            repo.abort_write_group()

    def test_not_in_write_group_errors(self):
        repo = self.make_repository("repository")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        self.assertRaises(
            AssertionError,
            repo.add_inventory_by_delta,
            b"missing-revision",
            [],
            b"new-revision",
            [b"missing-revision"],
        )

    def make_inv_delta(self, old, new):
        """Make an inventory delta from two inventories."""
        by_id = getattr(old, "_byid", None)
        if by_id is None:
            old_ids = {entry.file_id for (_n, entry) in old.iter_entries()}
        else:
            old_ids = set(by_id)
        by_id = getattr(new, "_byid", None)
        if by_id is None:
            new_ids = {entry.file_id for (_n, entry) in new.iter_entries()}
        else:
            new_ids = set(by_id)

        adds = new_ids - old_ids
        deletes = old_ids - new_ids
        common = old_ids.intersection(new_ids)
        delta = []
        for file_id in deletes:
            delta.append((old.id2path(file_id), None, file_id, None))
        for file_id in adds:
            delta.append((None, new.id2path(file_id), file_id, new.get_entry(file_id)))
        for file_id in common:
            if old.get_entry(file_id) != new.get_entry(file_id):
                delta.append(
                    (old.id2path(file_id), new.id2path(file_id), file_id, new[file_id])
                )
        return InventoryDelta(delta)

    def test_same_validator(self):
        # Adding an inventory via delta or direct results in the same
        # validator.
        tree = self.make_branch_and_tree("tree")
        revid = tree.commit("empty post")
        # tree.basis_tree() always uses a plain Inventory from the dirstate, we
        # want the same format inventory as we have in the repository
        revtree = tree.branch.repository.revision_tree(tree.branch.last_revision())
        tree.basis_tree()
        revtree.lock_read()
        self.addCleanup(revtree.unlock)
        old_inv = tree.branch.repository.revision_tree(
            revision.NULL_REVISION
        ).root_inventory
        new_inv = revtree.root_inventory
        delta = self.make_inv_delta(old_inv, new_inv)
        repo_direct = self._get_repo_in_write_group("direct")
        add_validator = repo_direct.add_inventory(revid, new_inv, [])
        repo_direct.commit_write_group()
        repo_delta = self._get_repo_in_write_group("delta")
        try:
            delta_validator, inv = repo_delta.add_inventory_by_delta(
                revision.NULL_REVISION, delta, revid, []
            )
        except:
            repo_delta.abort_write_group()
            raise
        else:
            repo_delta.commit_write_group()
        self.assertEqual(add_validator, delta_validator)
        self.assertEqual(list(new_inv.iter_entries()), list(inv.iter_entries()))

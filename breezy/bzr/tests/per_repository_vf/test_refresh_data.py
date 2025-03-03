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

"""Tests for VersionedFileRepository.refresh_data."""

from breezy import errors, repository
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)
from breezy.tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestRefreshData(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def fetch_new_revision_into_concurrent_instance(self, repo, token):
        """Create a new revision (revid 'new-rev') and fetch it into a
        concurrent instance of repo.
        """
        source = self.make_branch_and_memory_tree("source")
        source.lock_write()
        self.addCleanup(source.unlock)
        source.add([""], [b"root-id"])
        revid = source.commit("foo", rev_id=b"new-rev")
        # Force data reading on weaves/knits
        repo.all_revision_ids()
        repo.revisions.keys()
        repo.inventories.keys()
        # server repo is the instance a smart server might hold for this
        # repository.
        server_repo = repo.controldir.open_repository()
        try:
            server_repo.lock_write(token)
        except errors.TokenLockingNotSupported:
            self.skipTest(
                "Cannot concurrently insert into repo format {!r}".format(
                    self.repository_format
                )
            )
        try:
            server_repo.fetch(source.branch.repository, revid)
        finally:
            server_repo.unlock()

    def test_refresh_data_after_fetch_new_data_visible_in_write_group(self):
        tree = self.make_branch_and_memory_tree("target")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""], ids=[b"root-id"])
        tree.commit("foo", rev_id=b"commit-in-target")
        repo = tree.branch.repository
        token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        self.fetch_new_revision_into_concurrent_instance(repo, token)
        # Call refresh_data.  It either fails with IsInWriteGroupError, or it
        # succeeds and the new revisions are visible.
        try:
            repo.refresh_data()
        except repository.IsInWriteGroupError:
            pass
        else:
            self.assertEqual(
                [b"commit-in-target", b"new-rev"], sorted(repo.all_revision_ids())
            )

    def test_refresh_data_after_fetch_new_data_visible(self):
        repo = self.make_repository("target")
        token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        self.fetch_new_revision_into_concurrent_instance(repo, token)
        repo.refresh_data()
        self.assertNotEqual({}, repo.get_graph().get_parent_map([b"new-rev"]))

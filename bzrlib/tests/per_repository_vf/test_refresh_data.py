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


from bzrlib.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
    )
from bzrlib.tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestRefreshData(TestCaseWithRepository):

    scenarios = all_repository_vf_format_scenarios()

    def fetch_new_revision_into_concurrent_instance(self, repo, token):
        """Create a new revision (revid 'new-rev') and fetch it into a
        concurrent instance of repo.
        """
        source = self.make_branch_and_memory_tree('source')
        source.lock_write()
        self.addCleanup(source.unlock)
        source.add([''], ['root-id'])
        revid = source.commit('foo', rev_id='new-rev')
        # Force data reading on weaves/knits
        repo.all_revision_ids()
        repo.revisions.keys()
        repo.inventories.keys()
        # server repo is the instance a smart server might hold for this
        # repository.
        server_repo = repo.bzrdir.open_repository()
        try:
            server_repo.lock_write(token)
        except errors.TokenLockingNotSupported:
            raise TestSkipped('Cannot concurrently insert into repo format %r'
                % self.repository_format)
        try:
            server_repo.fetch(source.branch.repository, revid)
        finally:
            server_repo.unlock()



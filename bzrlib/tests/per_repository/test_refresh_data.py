# Copyright (C) 2009 Canonical Ltd
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

"""Tests for Repository.refresh_data."""

from bzrlib import (
    errors,
    remote,
    )
from bzrlib.tests import TestSkipped
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestRefreshData(TestCaseWithRepository):

    def test_refresh_data_unlocked(self):
        # While not interesting, it should not error.
        repo = self.make_repository('.')
        repo.refresh_data()

    def test_refresh_data_read_locked(self):
        # While not interesting, it should not error.
        repo = self.make_repository('.')
        repo.lock_read()
        self.addCleanup(repo.unlock)
        repo.refresh_data()

    def test_refresh_data_write_locked(self):
        # While not interesting, it should not error.
        repo = self.make_repository('.')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.refresh_data()

    def test_refresh_data_in_write_group_errors(self):
        repo = self.make_repository('.')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        # No flow control anticipated, BzrError is enough
        self.assertRaises(errors.BzrError, repo.refresh_data)

    def test_refresh_data_after_fetch_new_data_visible(self):
        source = self.make_branch_and_tree('source')
        revid = source.commit('foo')
        repo = self.make_repository('target')
        token = repo.lock_write()
        self.addCleanup(repo.unlock)
        # Force data reading on weaves/knits
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
        repo.refresh_data()
        self.assertNotEqual({}, repo.get_graph().get_parent_map([revid]))

# Copyright (C) 2009, 2010 Canonical Ltd
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

from breezy import (
    repository,
    )
from breezy.tests.per_repository import TestCaseWithRepository


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

    def test_refresh_data_in_write_group(self):
        # refresh_data may either succeed or raise IsInWriteGroupError during a
        # write group.
        repo = self.make_repository('.')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        try:
            repo.refresh_data()
        except repository.IsInWriteGroupError:
            # This is ok.
            pass
        else:
            # This is ok too.
            pass

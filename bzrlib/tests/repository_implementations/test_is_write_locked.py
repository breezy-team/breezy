# Copyright (C) 2007 Canonical Ltd
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

"""Tests for Repository.is_write_locked()."""

from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository


class TestIsWriteLocked(TestCaseWithRepository):

    def test_not_locked(self):
        repo = self.make_repository('.')
        self.assertFalse(repo.is_write_locked())

    def test_read_locked(self):
        repo = self.make_repository('.')
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertFalse(repo.is_write_locked())

    def test_write_locked(self):
        repo = self.make_repository('.')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        self.assertTrue(repo.is_write_locked())

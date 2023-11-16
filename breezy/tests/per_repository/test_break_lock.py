# Copyright (C) 2006-2010 Canonical Ltd
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

"""Tests for repository break-lock."""

import contextlib

from breezy import errors, ui
from breezy.tests import per_repository


class TestBreakLock(per_repository.TestCaseWithRepository):
    def setUp(self):
        super().setUp()
        self.unused_repo = self.make_repository(".")
        self.repo = self.unused_repo.controldir.open_repository()
        ui.ui_factory = ui.CannedInputUIFactory([True])

    def test_unlocked(self):
        # break lock when nothing is locked should just return
        with contextlib.suppress(NotImplementedError):
            self.repo.break_lock()

    def test_locked(self):
        # break_lock when locked should
        self.repo.lock_write()
        self.assertEqual(
            self.repo.get_physical_lock_status(),
            self.unused_repo.get_physical_lock_status(),
        )
        if not self.unused_repo.get_physical_lock_status():
            # 'lock_write' has not taken a physical mutex out.
            self.repo.unlock()
            return
        self.unused_repo.break_lock()
        self.assertRaises(errors.LockBroken, self.repo.unlock)

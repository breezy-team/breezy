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

"""Tests for break_lock on a repository with external references."""

from breezy import (
    errors,
    ui,
    )
from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestBreakLock(TestCaseWithExternalReferenceRepository):

    def test_break_lock(self):
        base = self.make_repository('base')
        repo = self.make_referring('referring', base)
        unused_repo = repo.controldir.open_repository()
        base.lock_write()
        self.addCleanup(base.unlock)
        # break_lock when locked should
        repo.lock_write()
        self.assertEqual(repo.get_physical_lock_status(),
                         unused_repo.get_physical_lock_status())
        if not unused_repo.get_physical_lock_status():
            # 'lock_write' has not taken a physical mutex out.
            repo.unlock()
            return
        ui.ui_factory = ui.CannedInputUIFactory([True])
        unused_repo.break_lock()
        self.assertRaises(errors.LockBroken, repo.unlock)

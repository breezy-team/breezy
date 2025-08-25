# Copyright (C) 2006-2012 Canonical Ltd
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

"""Tests for branch break-lock behaviour."""

import contextlib

from breezy import branch as _mod_branch
from breezy import errors, tests, ui
from breezy.tests import per_branch


class TestBreakLock(per_branch.TestCaseWithBranch):
    def setUp(self):
        super().setUp()
        self.unused_branch = self.make_branch("branch")
        self.branch = _mod_branch.Branch.open(self.unused_branch.base)

    def test_unlocked(self):
        # break lock when nothing is locked should just return
        with contextlib.suppress(NotImplementedError):
            self.branch.break_lock()

    def test_unlocked_repo_locked(self):
        # break lock on the branch should try on the repository even
        # if the branch isn't locked
        token = self.branch.repository.lock_write().repository_token
        if token is None:
            self.branch.repository.unlock()
            raise tests.TestNotApplicable("Repository does not use physical locks.")
        self.branch.repository.leave_lock_in_place()
        self.branch.repository.unlock()
        other_instance = self.branch.repository.controldir.open_repository()
        if not other_instance.get_physical_lock_status():
            raise tests.TestNotApplicable("Repository does not lock persistently.")
        ui.ui_factory = ui.CannedInputUIFactory([True])
        try:
            self.unused_branch.break_lock()
        except NotImplementedError:
            # branch does not support break_lock
            self.branch.repository.unlock()
            return
        self.assertRaises(errors.LockBroken, self.branch.repository.unlock)

    def test_locked(self):
        # break_lock when locked should unlock the branch and repo
        self.branch.lock_write()
        ui.ui_factory = ui.CannedInputUIFactory([True, True])
        try:
            self.unused_branch.break_lock()
        except NotImplementedError:
            # branch does not support break_lock
            self.branch.unlock()
            return
        self.assertRaises(errors.LockBroken, self.branch.unlock)

    def test_unlocks_master_branch(self):
        # break_lock when the master branch is locked should offer to
        # unlock it.
        master = self.make_branch("master")
        try:
            self.branch.bind(master)
        except _mod_branch.BindingUnsupported:
            # this branch does not support binding.
            return
        master.lock_write()
        ui.ui_factory = ui.CannedInputUIFactory([True, True])
        try:
            fresh = _mod_branch.Branch.open(self.unused_branch.base)
            fresh.break_lock()
        except NotImplementedError:
            # branch does not support break_lock
            master.unlock()
            return
        self.assertRaises(errors.LockBroken, master.unlock)
        # can we lock it now ?
        master.lock_write()
        master.unlock()

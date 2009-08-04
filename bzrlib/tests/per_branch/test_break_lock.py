# Copyright (C) 2006, 2009 Canonical Ltd
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

from cStringIO import StringIO

import bzrlib
import bzrlib.errors as errors
from bzrlib.tests import TestCase, TestCaseWithTransport, TestNotApplicable
from bzrlib.tests.per_branch.test_branch import TestCaseWithBranch
from bzrlib.ui import (
    CannedInputUIFactory,
    )


class TestBreakLock(TestCaseWithBranch):

    def setUp(self):
        super(TestBreakLock, self).setUp()
        self.unused_branch = self.make_branch('branch')
        self.branch = self.unused_branch.bzrdir.open_branch()
        # we want a UI factory that accepts canned input for the tests:
        # while SilentUIFactory still accepts stdin, we need to customise
        # ours
        self.old_factory = bzrlib.ui.ui_factory
        self.addCleanup(self.restoreFactory)

    def restoreFactory(self):
        bzrlib.ui.ui_factory = self.old_factory

    def test_unlocked(self):
        # break lock when nothing is locked should just return
        try:
            self.branch.break_lock()
        except NotImplementedError:
            pass

    def test_unlocked_repo_locked(self):
        # break lock on the branch should try on the repository even
        # if the branch isn't locked
        token = self.branch.repository.lock_write()
        if token is None:
            self.branch.repository.unlock()
            raise TestNotApplicable('Repository does not use physical locks.')
        self.branch.repository.leave_lock_in_place()
        self.branch.repository.unlock()
        other_instance = self.branch.repository.bzrdir.open_repository()
        if not other_instance.get_physical_lock_status():
            raise TestNotApplicable("Repository does not lock persistently.")
        bzrlib.ui.ui_factory = CannedInputUIFactory([True])
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
        bzrlib.ui.ui_factory = CannedInputUIFactory([True, True])
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
        master = self.make_branch('master')
        try:
            self.branch.bind(master)
        except errors.UpgradeRequired:
            # this branch does not support binding.
            return
        master.lock_write()
        bzrlib.ui.ui_factory = CannedInputUIFactory([True, True])
        try:
            self.unused_branch.break_lock()
        except NotImplementedError:
            # branch does not support break_lock
            master.unlock()
            return
        self.assertRaises(errors.LockBroken, master.unlock)
        # can we lock it now ?
        master.lock_write()
        master.unlock()


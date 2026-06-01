# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

import contextlib

from breezy import errors, ui
from breezy.tests import TestNotApplicable
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestBreakLock(TestCaseWithWorkingTree):
    def setUp(self):
        super().setUp()
        self.unused_workingtree = self.make_branch_and_tree(".")
        self.workingtree = self.unused_workingtree.controldir.open_workingtree()

    def test_unlocked(self):
        # break lock when nothing is locked should just return
        with contextlib.suppress(NotImplementedError):
            self.workingtree.break_lock()

    def test_unlocked_repo_locked(self):
        # break lock on the workingtree should try on the branch even
        # if the workingtree isn't locked - and the easiest way
        # to see if that happened is to lock the repo.
        self.workingtree.branch.repository.lock_write()
        ui.ui_factory = ui.CannedInputUIFactory([True])
        try:
            self.unused_workingtree.break_lock()
        except NotImplementedError:
            # workingtree does not support break_lock
            self.workingtree.branch.repository.unlock()
            return
        if ui.ui_factory.responses == [True]:
            raise TestNotApplicable("repository does not physically lock.")
        self.assertRaises(errors.LockBroken, self.workingtree.branch.repository.unlock)

    def test_locked(self):
        # break_lock when locked should
        self.workingtree.lock_write()
        ui.ui_factory = ui.CannedInputUIFactory([True, True, True])
        try:
            self.unused_workingtree.break_lock()
        except (NotImplementedError, errors.LockActive):
            # workingtree does not support break_lock,
            # or does not support breaking a lock held by an alive
            # object/process.
            self.workingtree.unlock()
            return
        self.assertRaises(errors.LockBroken, self.workingtree.unlock)

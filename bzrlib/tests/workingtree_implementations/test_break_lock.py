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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from cStringIO import StringIO
import os

import bzrlib
import bzrlib.errors as errors
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestBreakLock(TestCaseWithWorkingTree):

    def setUp(self):
        super(TestBreakLock, self).setUp()
        self.unused_workingtree = self.make_branch_and_tree('.')
        self.workingtree = self.unused_workingtree.bzrdir.open_workingtree()
        # we want a UI factory that accepts canned input for the tests:
        # while SilentUIFactory still accepts stdin, we need to customise
        # ours
        self.old_factory = bzrlib.ui.ui_factory
        self.addCleanup(self.restoreFactory)
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()

    def restoreFactory(self):
        bzrlib.ui.ui_factory = self.old_factory

    def test_unlocked(self):
        # break lock when nothing is locked should just return
        try:
            self.workingtree.break_lock()
        except NotImplementedError:
            pass

    def test_unlocked_repo_locked(self):
        # break lock on the workingtree should try on the branch even
        # if the workingtree isn't locked - and the easiest way
        # to see if that happened is to lock the repo.
        self.workingtree.branch.repository.lock_write()
        bzrlib.ui.ui_factory.stdin = StringIO("y\n")
        try:
            self.unused_workingtree.break_lock()
        except NotImplementedError:
            # workingtree does not support break_lock
            self.workingtree.branch.repository.unlock()
            return
        self.assertRaises(errors.LockBroken, self.workingtree.branch.repository.unlock)

    def test_locked(self):
        # break_lock when locked should
        self.workingtree.lock_write()
        bzrlib.ui.ui_factory.stdin = StringIO("y\ny\ny\n")
        try:
            self.unused_workingtree.break_lock()
        except NotImplementedError:
            # workingtree does not support break_lock
            self.workingtree.unlock()
            return
        self.assertRaises(errors.LockBroken, self.workingtree.unlock)

# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for repository break-lock."""

from cStringIO import StringIO

import bzrlib
import bzrlib.errors as errors
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.transport import get_transport
from bzrlib.workingtree import WorkingTree


class TestBreakLock(TestCaseWithRepository):

    def setUp(self):
        super(TestBreakLock, self).setUp()
        self.unused_repo = self.make_repository('.')
        self.repo = self.unused_repo.bzrdir.open_repository()
        # we want a UI factory that accepts canned input for the tests:
        # while SilentUIFactory still accepts stdin, we need to customise
        # ours
        self.old_factory = bzrlib.ui.ui_factory
        self.addCleanup(self.restoreFactory)
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()
        bzrlib.ui.ui_factory.stdin = StringIO("y\n")

    def restoreFactory(self):
        bzrlib.ui.ui_factory = self.old_factory

    def test_unlocked(self):
        # break lock when nothing is locked should just return
        try:
            self.repo.break_lock()
        except NotImplementedError:
            pass

    def test_locked(self):
        # break_lock when locked should
        self.repo.lock_write()
        try:
            self.unused_repo.break_lock()
        except NotImplementedError:
            # repository does not support break_lock
            self.repo.unlock()
            return
        self.assertRaises(errors.LockBroken, self.repo.unlock)

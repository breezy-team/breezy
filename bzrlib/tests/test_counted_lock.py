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

"""Tests for bzrlib.counted_lock"""

from bzrlib.counted_lock import CountedLock
from bzrlib.errors import (
    LockError,
    ReadOnlyError,
    )
from bzrlib.tests import TestCase


class DummyLock(object):
    """Lock that just records what's been done to it."""

    def __init__(self):
        self._calls = []
        self._lock_mode = None

    def is_locked(self):
        return self._lock_mode is not None

    def lock_read(self):
        self._assert_not_locked()
        self._lock_mode = 'r'
        self._calls.append('lock_read')

    def lock_write(self):
        self._assert_not_locked()
        self._lock_mode = 'w'
        self._calls.append('lock_write')

    def unlock(self):
        self._assert_locked()
        self._lock_mode = None
        self._calls.append('unlock')

    def break_lock(self):
        self._lock_mode = None
        self._calls.append('break')

    def _assert_locked(self):
        if not self._lock_mode:
            raise LockError("%s is not locked" % (self,))

    def _assert_not_locked(self):
        if self._lock_mode:
            raise LockError("%s is already locked in mode %r" %
                (self, self._lock_mode))


class TestDummyLock(TestCase):

    def test_lock_initially_not_held(self):
        l = DummyLock()
        self.assertFalse(l.is_locked())

    def test_lock_not_reentrant(self):
        # can't take the underlying lock twice
        l = DummyLock()
        l.lock_read()
        self.assertRaises(LockError, l.lock_read)

    def test_detect_underlock(self):
        l = DummyLock()
        self.assertRaises(LockError, l.unlock)

    def test_basic_locking(self):
        # dummy lock works like a basic non reentrant lock
        real_lock = DummyLock()
        self.assertFalse(real_lock.is_locked())
        # lock read and unlock
        real_lock.lock_read()
        self.assertTrue(real_lock.is_locked())
        real_lock.unlock()
        self.assertFalse(real_lock.is_locked())
        # lock write and unlock
        real_lock.lock_write()
        self.assertTrue(real_lock.is_locked())
        real_lock.unlock()
        self.assertFalse(real_lock.is_locked())
        # check calls
        self.assertEqual(
            ['lock_read', 'unlock', 'lock_write', 'unlock'],
            real_lock._calls)

    def test_break_lock(self):
        l = DummyLock()
        l.lock_write()
        l.break_lock()
        self.assertFalse(l.is_locked())
        self.assertEqual(
            ['lock_write', 'break'],
            l._calls)


class TestCountedLock(TestCase):

    def test_lock_unlock(self):
        # Lock and unlock a counted lock
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        self.assertFalse(l.is_locked())
        # can lock twice, although this isn't allowed on the underlying lock
        l.lock_read()
        l.lock_read()
        self.assertTrue(l.is_locked())
        # and release
        l.unlock()
        self.assertTrue(l.is_locked())
        l.unlock()
        self.assertFalse(l.is_locked())
        self.assertEquals(
            ['lock_read', 'unlock'],
            real_lock._calls)

    def test_unlock_not_locked(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        self.assertRaises(LockError, l.unlock)

    def test_read_lock_while_write_locked(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        l.lock_write()
        l.lock_read()
        l.lock_write()
        l.unlock()
        l.unlock()
        l.unlock()
        self.assertFalse(l.is_locked())
        self.assertEquals(
            ['lock_write', 'unlock'],
            real_lock._calls)

    def test_write_lock_while_read_locked(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        l.lock_read()
        self.assertRaises(ReadOnlyError, l.lock_write)
        self.assertRaises(ReadOnlyError, l.lock_write)
        l.unlock()
        self.assertFalse(l.is_locked())
        self.assertEquals(
            ['lock_read', 'unlock'],
            real_lock._calls)

    def test_break_lock(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        l.lock_write()
        l.lock_write()
        self.assertTrue(real_lock.is_locked())
        l.break_lock()
        self.assertFalse(l.is_locked())
        self.assertFalse(real_lock.is_locked())

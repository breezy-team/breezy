# Copyright (C) 2007, 2008, 2009, 2016 Canonical Ltd
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

"""Tests for breezy.counted_lock"""

from ..counted_lock import CountedLock
from ..errors import (
    LockError,
    LockNotHeld,
    ReadOnlyError,
    TokenMismatch,
    )
from . import TestCase


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

    def lock_write(self, token=None):
        if token is not None:
            if token == 'token':
                # already held by this caller
                return 'token'
            else:
                raise TokenMismatch()
        self._assert_not_locked()
        self._lock_mode = 'w'
        self._calls.append('lock_write')
        return 'token'

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

    def validate_token(self, token):
        if token == 'token':
            # already held by this caller
            return 'token'
        elif token is None:
            return
        else:
            raise TokenMismatch(token, 'token')


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
        result = real_lock.lock_write()
        self.assertEqual('token', result)
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

    def test_read_lock(self):
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
        self.assertEqual(
            ['lock_read', 'unlock'],
            real_lock._calls)

    def test_unlock_not_locked(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        self.assertRaises(LockNotHeld, l.unlock)

    def test_read_lock_while_write_locked(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        l.lock_write()
        l.lock_read()
        self.assertEqual('token', l.lock_write())
        l.unlock()
        l.unlock()
        l.unlock()
        self.assertFalse(l.is_locked())
        self.assertEqual(
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
        self.assertEqual(
            ['lock_read', 'unlock'],
            real_lock._calls)

    def test_write_lock_reentrant(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        self.assertEqual('token', l.lock_write())
        self.assertEqual('token', l.lock_write())
        l.unlock()
        l.unlock()

    def test_reenter_with_token(self):
        real_lock = DummyLock()
        l1 = CountedLock(real_lock)
        l2 = CountedLock(real_lock)
        token = l1.lock_write()
        self.assertEqual('token', token)
        # now imagine that we lost that connection, but we still have the
        # token...
        del l1
        # because we can supply the token, we can acquire the lock through
        # another instance
        self.assertTrue(real_lock.is_locked())
        self.assertFalse(l2.is_locked())
        self.assertEqual(token, l2.lock_write(token=token))
        self.assertTrue(l2.is_locked())
        self.assertTrue(real_lock.is_locked())
        l2.unlock()
        self.assertFalse(l2.is_locked())
        self.assertFalse(real_lock.is_locked())

    def test_break_lock(self):
        real_lock = DummyLock()
        l = CountedLock(real_lock)
        l.lock_write()
        l.lock_write()
        self.assertTrue(real_lock.is_locked())
        l.break_lock()
        self.assertFalse(l.is_locked())
        self.assertFalse(real_lock.is_locked())

    # TODO: test get_physical_lock_status

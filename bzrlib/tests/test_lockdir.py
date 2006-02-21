# Copyright (C) 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for LockDir"""

from threading import Thread
import time

from bzrlib.errors import LockContention, LockError, UnlockableTransport, \
        LockNotHeld
from bzrlib.lockdir import LockDir
from bzrlib.tests import TestCaseInTempDir, TestCaseWithTransport

# These tests sometimes use threads to test the behaviour of lock files with
# concurrent actors.  This is not a typical (or necessarily supported) use;
# they're really meant for guarding between processes.

class TestLockDir(TestCaseWithTransport):
    """Test LockDir operations"""

    def test_00_lock_creation(self):
        """Creation of lock file on a transport"""
        t = self.get_transport()
        lf = LockDir(t, 'test_lock')
        self.assertFalse(lf.is_held)

    def test_01_lock_repr(self):
        """Lock string representation"""
        lf = LockDir(self.get_transport(), 'test_lock')
        r = repr(lf)
        self.assertContainsRe(r, r'^LockDir\(.*/test_lock\)$')

    def test_02_unlocked_peek(self):
        lf = LockDir(self.get_transport(), 'test_lock')
        self.assertEqual(lf.peek(), None)

    def test_03_readonly_peek(self):
        lf = LockDir(self.get_readonly_transport(), 'test_lock')
        self.assertEqual(lf.peek(), None)

    def test_10_lock_uncontested(self):
        """Acquire and release a lock"""
        t = self.get_transport()
        lf = LockDir(t, 'test_lock')
        lf.attempt_lock()
        try:
            self.assertTrue(lf.is_held)
        finally:
            lf.unlock()
            self.assertFalse(lf.is_held)

    def test_11_lock_readonly_transport(self):
        """Fail to lock on readonly transport"""
        t = self.get_readonly_transport()
        lf = LockDir(t, 'test_lock')
        self.assertRaises(UnlockableTransport, lf.attempt_lock)

    def test_20_lock_contested(self):
        """Contention to get a lock"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.attempt_lock()
        lf2 = LockDir(t, 'test_lock')
        try:
            # locking is between LockDir instances; aliases within 
            # a single process are not detected
            lf2.attempt_lock()
            self.fail('Failed to detect lock collision')
        except LockContention, e:
            self.assertEqual(e.lock, lf2)
            self.assertContainsRe(str(e),
                    r'^Could not acquire.*test_lock.*$')
        lf1.unlock()

    def test_20_lock_peek(self):
        """Peek at the state of a lock"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.attempt_lock()
        # lock is held, should get some info on it
        info1 = lf1.peek()
        self.assertEqual(set(info1.keys()),
                         set(['user', 'nonce', 'hostname', 'pid', 'start_time']))
        # should get the same info if we look at it through a different
        # instance
        info2 = LockDir(t, 'test_lock').peek()
        self.assertEqual(info1, info2)
        # locks which are never used should be not-held
        self.assertEqual(LockDir(t, 'other_lock').peek(), None)

    def test_21_peek_readonly(self):
        """Peek over a readonly transport"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf2 = LockDir(self.get_readonly_transport(), 'test_lock')
        self.assertEqual(lf2.peek(), None)
        lf1.attempt_lock()
        info2 = lf2.peek()
        self.assertTrue(info2)
        self.assertEqual(info2['nonce'], lf1.nonce)

    def test_30_lock_wait_fail(self):
        """Wait on a lock, then fail
        
        We ask to wait up to 400ms; this should fail within at most one
        second.  (Longer times are more realistic but we don't want the test
        suite to take too long, and this should do for now.)
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf2 = LockDir(t, 'test_lock')
        lf1.attempt_lock()
        try:
            before = time.time()
            self.assertRaises(LockContention, lf2.wait_lock,
                              timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            lf1.unlock()

    def test_31_lock_wait_easy(self):
        """Succeed when waiting on a lock with no contention.
        """
        t = self.get_transport()
        lf2 = LockDir(t, 'test_lock')
        try:
            before = time.time()
            lf2.wait_lock(timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            lf2.unlock()

    def test_32_lock_wait_succeed(self):
        """Succeed when trying to acquire a lock that gets released

        One thread holds on a lock and then releases it; another tries to lock it.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.attempt_lock()

        def wait_and_unlock():
            time.sleep(0.1)
            lf1.unlock()
        unlocker = Thread(target=wait_and_unlock)
        unlocker.start()
        try:
            lf2 = LockDir(t, 'test_lock')
            before = time.time()
            # wait and then lock
            lf2.wait_lock(timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            unlocker.join()

    def test_33_wait(self):
        """Succeed when waiting on a lock that gets released

        The difference from test_32_lock_wait_succeed is that the second 
        caller does not actually acquire the lock, but just waits for it
        to be released.  This is done over a readonly transport.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.attempt_lock()

        def wait_and_unlock():
            time.sleep(0.1)
            lf1.unlock()
        unlocker = Thread(target=wait_and_unlock)
        unlocker.start()
        try:
            lf2 = LockDir(self.get_readonly_transport(), 'test_lock')
            before = time.time()
            # wait but don't lock
            lf2.wait(timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            unlocker.join()

    def test_40_confirm_easy(self):
        """Confirm a lock that's already held"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.attempt_lock()
        lf1.confirm()

    def test_41_confirm_not_held(self):
        """Confirm a lock that's already held"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        self.assertRaises(LockNotHeld, lf1.confirm)

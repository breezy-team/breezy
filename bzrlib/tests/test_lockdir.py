# Copyright (C) 2006 Canonical Ltd
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

"""Tests for LockDir"""

from cStringIO import StringIO
from threading import Thread, Lock
import time

import bzrlib
from bzrlib import (
    osutils,
    )
from bzrlib.errors import (
        LockBreakMismatch,
        LockContention, LockError, UnlockableTransport,
        LockNotHeld, LockBroken
        )
from bzrlib.lockdir import LockDir, _DEFAULT_TIMEOUT_SECONDS
from bzrlib.tests import TestCaseWithTransport
from bzrlib.trace import note

# These tests sometimes use threads to test the behaviour of lock files with
# concurrent actors.  This is not a typical (or necessarily supported) use;
# they're really meant for guarding between processes.

# These tests are run on the default transport provided by the test framework
# (typically a local disk transport).  That can be changed by the --transport
# option to bzr selftest.  The required properties of the transport
# implementation are tested separately.  (The main requirement is just that
# they don't allow overwriting nonempty directories.)

class TestLockDir(TestCaseWithTransport):
    """Test LockDir operations"""

    def logging_report_function(self, fmt, *args):
        self._logged_reports.append((fmt, args))

    def setup_log_reporter(self, lock_dir):
        self._logged_reports = []
        lock_dir._report_function = self.logging_report_function

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

    def get_lock(self):
        return LockDir(self.get_transport(), 'test_lock')

    def test_unlock_after_break_raises(self):
        ld = self.get_lock()
        ld2 = self.get_lock()
        ld.create()
        ld.attempt_lock()
        ld2.force_break(ld2.peek())
        self.assertRaises(LockBroken, ld.unlock)

    def test_03_readonly_peek(self):
        lf = LockDir(self.get_readonly_transport(), 'test_lock')
        self.assertEqual(lf.peek(), None)

    def test_10_lock_uncontested(self):
        """Acquire and release a lock"""
        t = self.get_transport()
        lf = LockDir(t, 'test_lock')
        lf.create()
        lf.attempt_lock()
        try:
            self.assertTrue(lf.is_held)
        finally:
            lf.unlock()
            self.assertFalse(lf.is_held)

    def test_11_create_readonly_transport(self):
        """Fail to create lock on readonly transport"""
        t = self.get_readonly_transport()
        lf = LockDir(t, 'test_lock')
        self.assertRaises(UnlockableTransport, lf.create)

    def test_12_lock_readonly_transport(self):
        """Fail to lock on readonly transport"""
        lf = LockDir(self.get_transport(), 'test_lock')
        lf.create()
        lf = LockDir(self.get_readonly_transport(), 'test_lock')
        self.assertRaises(UnlockableTransport, lf.attempt_lock)

    def test_20_lock_contested(self):
        """Contention to get a lock"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
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
        lf1.create()
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
        lf1.create()
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
        lf1.create()
        lf2 = LockDir(t, 'test_lock')
        self.setup_log_reporter(lf2)
        lf1.attempt_lock()
        try:
            before = time.time()
            self.assertRaises(LockContention, lf2.wait_lock,
                              timeout=0.4, poll=0.1)
            after = time.time()
            # it should only take about 0.4 seconds, but we allow more time in
            # case the machine is heavily loaded
            self.assertTrue(after - before <= 8.0, 
                    "took %f seconds to detect lock contention" % (after - before))
        finally:
            lf1.unlock()
        lock_base = lf2.transport.abspath(lf2.path)
        self.assertEqual(1, len(self._logged_reports))
        self.assertEqual('Unable to obtain %s\n'
                         '%s\n%s\n'
                         'Will continue to try for %s seconds\n',
                         self._logged_reports[0][0])
        args = self._logged_reports[0][1]
        self.assertEqual('lock %s' % (lock_base,), args[0])
        self.assertStartsWith(args[1], 'held by ')
        self.assertStartsWith(args[2], 'locked ')
        self.assertEndsWith(args[2], ' ago')

    def test_31_lock_wait_easy(self):
        """Succeed when waiting on a lock with no contention.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        self.setup_log_reporter(lf1)
        try:
            before = time.time()
            lf1.wait_lock(timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            lf1.unlock()
        self.assertEqual([], self._logged_reports)

    def test_32_lock_wait_succeed(self):
        """Succeed when trying to acquire a lock that gets released

        One thread holds on a lock and then releases it; another 
        tries to lock it.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()

        def wait_and_unlock():
            time.sleep(0.1)
            lf1.unlock()
        unlocker = Thread(target=wait_and_unlock)
        unlocker.start()
        try:
            lf2 = LockDir(t, 'test_lock')
            self.setup_log_reporter(lf2)
            before = time.time()
            # wait and then lock
            lf2.wait_lock(timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            unlocker.join()

        # There should be only 1 report, even though it should have to
        # wait for a while
        lock_base = lf2.transport.abspath(lf2.path)
        self.assertEqual(1, len(self._logged_reports))
        self.assertEqual('Unable to obtain %s\n'
                         '%s\n%s\n'
                         'Will continue to try for %s seconds\n',
                         self._logged_reports[0][0])
        args = self._logged_reports[0][1]
        self.assertEqual('lock %s' % (lock_base,), args[0])
        self.assertStartsWith(args[1], 'held by ')
        self.assertStartsWith(args[2], 'locked ')
        self.assertEndsWith(args[2], ' ago')

    def test_33_wait(self):
        """Succeed when waiting on a lock that gets released

        The difference from test_32_lock_wait_succeed is that the second 
        caller does not actually acquire the lock, but just waits for it
        to be released.  This is done over a readonly transport.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
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

    def test_34_lock_write_waits(self):
        """LockDir.lock_write() will wait for the lock.""" 
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()

        def wait_and_unlock():
            time.sleep(0.1)
            lf1.unlock()
        unlocker = Thread(target=wait_and_unlock)
        unlocker.start()
        try:
            lf2 = LockDir(t, 'test_lock')
            self.setup_log_reporter(lf2)
            before = time.time()
            # wait and then lock
            lf2.lock_write()
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            unlocker.join()

        # There should be only 1 report, even though it should have to
        # wait for a while
        lock_base = lf2.transport.abspath(lf2.path)
        self.assertEqual(1, len(self._logged_reports))
        self.assertEqual('Unable to obtain %s\n'
                         '%s\n%s\n'
                         'Will continue to try for %s seconds\n',
                         self._logged_reports[0][0])
        args = self._logged_reports[0][1]
        self.assertEqual('lock %s' % (lock_base,), args[0])
        self.assertStartsWith(args[1], 'held by ')
        self.assertStartsWith(args[2], 'locked ')
        self.assertEndsWith(args[2], ' ago')

    def test_35_wait_lock_changing(self):
        """LockDir.wait_lock() will report if the lock changes underneath.
        
        This is the stages we want to happen:

        0) Synchronization locks are created and locked.
        1) Lock1 obtains the lockdir, and releases the 'check' lock.
        2) Lock2 grabs the 'check' lock, and checks the lockdir.
           It sees the lockdir is already acquired, reports the fact, 
           and unsets the 'peek' lock.
        3) Thread1 blocks on acquiring the 'peek' lock, and then tells
           Lock1 to release and acquire the lockdir. This resets the 'check'
           lock.
        4) Lock2 acquires the 'check' lock, and checks again. It notices
           that the holder of the lock has changed, and so reports a new 
           lock holder.
        5) Thread1 blocks on the 'peek' lock, this time, it completely
           unlocks the lockdir, allowing Lock2 to acquire the lock.
        """

        wait_to_check_lock = Lock()
        wait_until_peek_lock = Lock()

        wait_to_check_lock.acquire()
        wait_until_peek_lock.acquire()
        note('locked check and peek locks')

        class LockDir1(LockDir):
            """Use the synchronization points for the first lock."""

            def attempt_lock(self):
                # Once we have acquired the lock, it is okay for
                # the other lock to check it
                try:
                    return super(LockDir1, self).attempt_lock()
                finally:
                    note('lock1: releasing check lock')
                    wait_to_check_lock.release()

        class LockDir2(LockDir):
            """Use the synchronization points for the second lock."""

            def peek(self):
                note('lock2: waiting for check lock')
                wait_to_check_lock.acquire()
                note('lock2: acquired check lock')
                try:
                    return super(LockDir2, self).peek()
                finally:
                    note('lock2: releasing peek lock')
                    wait_until_peek_lock.release()

        t = self.get_transport()
        lf1 = LockDir1(t, 'test_lock')
        lf1.create()

        lf2 = LockDir2(t, 'test_lock')
        self.setup_log_reporter(lf2)

        def wait_and_switch():
            lf1.attempt_lock()
            # Block until lock2 has had a chance to peek
            note('lock1: waiting 1 for peek lock')
            wait_until_peek_lock.acquire()
            note('lock1: acquired for peek lock')
            note('lock1: released lockdir')
            lf1.unlock()
            note('lock1: acquiring lockdir')
            # Create a new nonce, so the lock looks different.
            lf1.nonce = osutils.rand_chars(20)
            lf1.lock_write()
            note('lock1: acquired lockdir')

            # Block until lock2 has peeked again
            note('lock1: waiting 2 for peek lock')
            wait_until_peek_lock.acquire()
            note('lock1: acquired for peek lock')
            lf1.unlock()
            # We need to allow check 2 times
            wait_to_check_lock.release()
            wait_until_peek_lock.acquire()
            wait_to_check_lock.release()

        unlocker = Thread(target=wait_and_switch)
        unlocker.start()
        try:
            # Start the other thread
            time.sleep(0.1)
            # wait and then lock
            lf2.wait_lock(timeout=1.0, poll=0.1)
        finally:
            unlocker.join()
        lf2.unlock()

        # There should be 2 reports, because the lock changed
        lock_base = lf2.transport.abspath(lf2.path)
        self.assertEqual(2, len(self._logged_reports))
        def check_one(index):
            self.assertEqual('Unable to obtain %s\n'
                             '%s\n%s\n'
                             'Will continue to try for %s seconds\n',
                             self._logged_reports[index][0])
            args = self._logged_reports[index][1]
            self.assertEqual('lock %s' % (lock_base,), args[0])
            self.assertStartsWith(args[1], 'held by ')
            self.assertStartsWith(args[2], 'locked ')
            self.assertEndsWith(args[2], ' ago')
        check_one(0)
        check_one(1)

    def test_40_confirm_easy(self):
        """Confirm a lock that's already held"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()
        lf1.confirm()

    def test_41_confirm_not_held(self):
        """Confirm a lock that's already held"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        self.assertRaises(LockNotHeld, lf1.confirm)

    def test_42_confirm_broken_manually(self):
        """Confirm a lock broken by hand"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()
        t.move('test_lock', 'lock_gone_now')
        self.assertRaises(LockBroken, lf1.confirm)

    def test_43_break(self):
        """Break a lock whose caller has forgotten it"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()
        # we incorrectly discard the lock object without unlocking it
        del lf1
        # someone else sees it's still locked
        lf2 = LockDir(t, 'test_lock')
        holder_info = lf2.peek()
        self.assertTrue(holder_info)
        lf2.force_break(holder_info)
        # now we should be able to take it
        lf2.attempt_lock()
        lf2.confirm()

    def test_44_break_already_released(self):
        """Lock break races with regular release"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()
        # someone else sees it's still locked
        lf2 = LockDir(t, 'test_lock')
        holder_info = lf2.peek()
        # in the interim the lock is released
        lf1.unlock()
        # break should succeed
        lf2.force_break(holder_info)
        # now we should be able to take it
        lf2.attempt_lock()
        lf2.confirm()

    def test_45_break_mismatch(self):
        """Lock break races with someone else acquiring it"""
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.attempt_lock()
        # someone else sees it's still locked
        lf2 = LockDir(t, 'test_lock')
        holder_info = lf2.peek()
        # in the interim the lock is released
        lf1.unlock()
        lf3 = LockDir(t, 'test_lock')
        lf3.attempt_lock()
        # break should now *fail*
        self.assertRaises(LockBreakMismatch, lf2.force_break,
                          holder_info)
        lf3.unlock()

    def test_46_fake_read_lock(self):
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        lf1.lock_read()
        lf1.unlock()

    def test_50_lockdir_representation(self):
        """Check the on-disk representation of LockDirs is as expected.

        There should always be a top-level directory named by the lock.
        When the lock is held, there should be a lockname/held directory 
        containing an info file.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')
        lf1.create()
        self.assertTrue(t.has('test_lock'))
        lf1.lock_write()
        self.assertTrue(t.has('test_lock/held/info'))
        lf1.unlock()
        self.assertFalse(t.has('test_lock/held/info'))

    def test_break_lock(self):
        # the ui based break_lock routine should Just Work (tm)
        ld1 = self.get_lock()
        ld2 = self.get_lock()
        ld1.create()
        ld1.lock_write()
        # do this without IO redirection to ensure it doesn't prompt.
        self.assertRaises(AssertionError, ld1.break_lock)
        orig_factory = bzrlib.ui.ui_factory
        # silent ui - no need for stdout
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()
        bzrlib.ui.ui_factory.stdin = StringIO("y\n")
        try:
            ld2.break_lock()
            self.assertRaises(LockBroken, ld1.unlock)
        finally:
            bzrlib.ui.ui_factory = orig_factory

    def test_create_missing_base_directory(self):
        """If LockDir.path doesn't exist, it can be created

        Some people manually remove the entire lock/ directory trying
        to unlock a stuck repository/branch/etc. Rather than failing
        after that, just create the lock directory when needed.
        """
        t = self.get_transport()
        lf1 = LockDir(t, 'test_lock')

        lf1.create()
        self.failUnless(t.has('test_lock'))

        t.rmdir('test_lock')
        self.failIf(t.has('test_lock'))

        # This will create 'test_lock' if it needs to
        lf1.lock_write()
        self.failUnless(t.has('test_lock'))
        self.failUnless(t.has('test_lock/held/info'))

        lf1.unlock()
        self.failIf(t.has('test_lock/held/info'))

    def test__format_lock_info(self):
        ld1 = self.get_lock()
        ld1.create()
        ld1.lock_write()
        try:
            info_list = ld1._format_lock_info(ld1.peek())
        finally:
            ld1.unlock()
        self.assertEqual('lock %s' % (ld1.transport.abspath(ld1.path),),
                         info_list[0])
        self.assertContainsRe(info_list[1],
                              r'^held by .* on host .* \[process #\d*\]$')
        self.assertContainsRe(info_list[2], r'locked \d+ seconds? ago$')

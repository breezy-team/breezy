# Copyright (C) 2005-2011 Canonical Ltd
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

import breezy
from .. import (
    errors,
    lockdir,
    osutils,
    transport,
    )
from ..lockable_files import LockableFiles, TransportLock
from . import (
    TestCaseInTempDir,
    TestNotApplicable,
    )
from ..bzr.tests.test_smart import TestCaseWithSmartMedium
from .test_transactions import DummyWeave
from ..transactions import (PassThroughTransaction,
                            ReadOnlyTransaction,
                            WriteTransaction,
                            )


# these tests are applied in each parameterized suite for LockableFiles
#
# they use an old style of parameterization, but we want to remove this class
# so won't modernize them now. - mbp 20080430
class _TestLockableFiles_mixin(object):

    def test_transactions(self):
        self.assertIs(self.lockable.get_transaction().__class__,
                      PassThroughTransaction)
        self.lockable.lock_read()
        try:
            self.assertIs(self.lockable.get_transaction().__class__,
                          ReadOnlyTransaction)
        finally:
            self.lockable.unlock()
        self.assertIs(self.lockable.get_transaction().__class__,
                      PassThroughTransaction)
        self.lockable.lock_write()
        self.assertIs(self.lockable.get_transaction().__class__,
                      WriteTransaction)
        # check that finish is called:
        vf = DummyWeave('a')
        self.lockable.get_transaction().register_dirty(vf)
        self.lockable.unlock()
        self.assertTrue(vf.finished)

    def test__escape(self):
        self.assertEqual('%25', self.lockable._escape('%'))

    def test__escape_empty(self):
        self.assertEqual('', self.lockable._escape(''))

    def test_break_lock(self):
        # some locks are not breakable
        self.lockable.lock_write()
        try:
            self.assertRaises(AssertionError, self.lockable.break_lock)
        except NotImplementedError:
            # this lock cannot be broken
            self.lockable.unlock()
            raise TestNotApplicable("%r is not breakable" % (self.lockable,))
        l2 = self.get_lockable()
        orig_factory = breezy.ui.ui_factory
        # silent ui - no need for stdout
        breezy.ui.ui_factory = breezy.ui.CannedInputUIFactory([True])
        try:
            l2.break_lock()
        finally:
            breezy.ui.ui_factory = orig_factory
        try:
            l2.lock_write()
            l2.unlock()
        finally:
            self.assertRaises(errors.LockBroken, self.lockable.unlock)
            self.assertFalse(self.lockable.is_locked())

    def test_lock_write_returns_None_refuses_token(self):
        token = self.lockable.lock_write()
        self.addCleanup(self.lockable.unlock)
        if token is not None:
            # This test does not apply, because this lockable supports
            # tokens.
            raise TestNotApplicable("%r uses tokens" % (self.lockable,))
        self.assertRaises(errors.TokenLockingNotSupported,
                          self.lockable.lock_write, token='token')

    def test_lock_write_returns_token_when_given_token(self):
        token = self.lockable.lock_write()
        self.addCleanup(self.lockable.unlock)
        if token is None:
            # This test does not apply, because this lockable refuses
            # tokens.
            return
        new_lockable = self.get_lockable()
        token_from_new_lockable = new_lockable.lock_write(token=token)
        self.addCleanup(new_lockable.unlock)
        self.assertEqual(token, token_from_new_lockable)

    def test_lock_write_raises_on_token_mismatch(self):
        token = self.lockable.lock_write()
        self.addCleanup(self.lockable.unlock)
        if token is None:
            # This test does not apply, because this lockable refuses
            # tokens.
            return
        different_token = token + b'xxx'
        # Re-using the same lockable instance with a different token will
        # raise TokenMismatch.
        self.assertRaises(errors.TokenMismatch,
                          self.lockable.lock_write, token=different_token)
        # A separate instance for the same lockable will also raise
        # TokenMismatch.
        # This detects the case where a caller claims to have a lock (via
        # the token) for an external resource, but doesn't (the token is
        # different).  Clients need a separate lock object to make sure the
        # external resource is probed, whereas the existing lock object
        # might cache.
        new_lockable = self.get_lockable()
        self.assertRaises(errors.TokenMismatch,
                          new_lockable.lock_write, token=different_token)

    def test_lock_write_with_matching_token(self):
        # If the token matches, so no exception is raised by lock_write.
        token = self.lockable.lock_write()
        self.addCleanup(self.lockable.unlock)
        if token is None:
            # This test does not apply, because this lockable refuses
            # tokens.
            return
        # The same instance will accept a second lock_write if the specified
        # token matches.
        self.lockable.lock_write(token=token)
        self.lockable.unlock()
        # Calling lock_write on a new instance for the same lockable will
        # also succeed.
        new_lockable = self.get_lockable()
        new_lockable.lock_write(token=token)
        new_lockable.unlock()

    def test_unlock_after_lock_write_with_token(self):
        # If lock_write did not physically acquire the lock (because it was
        # passed a token), then unlock should not physically release it.
        token = self.lockable.lock_write()
        self.addCleanup(self.lockable.unlock)
        if token is None:
            # This test does not apply, because this lockable refuses
            # tokens.
            return
        new_lockable = self.get_lockable()
        new_lockable.lock_write(token=token)
        new_lockable.unlock()
        self.assertTrue(self.lockable.get_physical_lock_status())

    def test_lock_write_with_token_fails_when_unlocked(self):
        # Lock and unlock to get a superficially valid token.  This mimics a
        # likely programming error, where a caller accidentally tries to lock
        # with a token that is no longer valid (because the original lock was
        # released).
        token = self.lockable.lock_write()
        self.lockable.unlock()
        if token is None:
            # This test does not apply, because this lockable refuses
            # tokens.
            return

        self.assertRaises(errors.TokenMismatch,
                          self.lockable.lock_write, token=token)

    def test_lock_write_reenter_with_token(self):
        token = self.lockable.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            # Relock with a token.
            token_from_reentry = self.lockable.lock_write(token=token)
            try:
                self.assertEqual(token, token_from_reentry)
            finally:
                self.lockable.unlock()
        finally:
            self.lockable.unlock()
        # The lock should be unlocked on disk.  Verify that with a new lock
        # instance.
        new_lockable = self.get_lockable()
        # Calling lock_write now should work, rather than raise LockContention.
        new_lockable.lock_write()
        new_lockable.unlock()

    def test_second_lock_write_returns_same_token(self):
        first_token = self.lockable.lock_write()
        try:
            if first_token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            # Relock the already locked lockable.  It should return the same
            # token.
            second_token = self.lockable.lock_write()
            try:
                self.assertEqual(first_token, second_token)
            finally:
                self.lockable.unlock()
        finally:
            self.lockable.unlock()

    def test_leave_in_place(self):
        token = self.lockable.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            self.lockable.leave_in_place()
        finally:
            self.lockable.unlock()
        # At this point, the lock is still in place on disk
        self.assertRaises(errors.LockContention, self.lockable.lock_write)
        # But should be relockable with a token.
        self.lockable.lock_write(token=token)
        self.lockable.unlock()
        # Cleanup: we should still be able to get the lock, but we restore the
        # behavior to clearing the lock when unlocking.
        self.lockable.lock_write(token=token)
        self.lockable.dont_leave_in_place()
        self.lockable.unlock()

    def test_dont_leave_in_place(self):
        token = self.lockable.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            self.lockable.leave_in_place()
        finally:
            self.lockable.unlock()
        # At this point, the lock is still in place on disk.
        # Acquire the existing lock with the token, and ask that it is removed
        # when this object unlocks, and unlock to trigger that removal.
        new_lockable = self.get_lockable()
        new_lockable.lock_write(token=token)
        new_lockable.dont_leave_in_place()
        new_lockable.unlock()
        # At this point, the lock is no longer on disk, so we can lock it.
        third_lockable = self.get_lockable()
        third_lockable.lock_write()
        third_lockable.unlock()


# This method of adapting tests to parameters is different to
# the TestProviderAdapters used elsewhere, but seems simpler for this
# case.
class TestLockableFiles_TransportLock(TestCaseInTempDir,
                                      _TestLockableFiles_mixin):

    def setUp(self):
        super(TestLockableFiles_TransportLock, self).setUp()
        t = transport.get_transport_from_path('.')
        t.mkdir('.bzr')
        self.sub_transport = t.clone('.bzr')
        self.lockable = self.get_lockable()
        self.lockable.create_lock()

    def stop_server(self):
        super(TestLockableFiles_TransportLock, self).stop_server()
        # free the subtransport so that we do not get a 5 second
        # timeout due to the SFTP connection cache.
        try:
            del self.sub_transport
        except AttributeError:
            pass

    def get_lockable(self):
        return LockableFiles(self.sub_transport, 'my-lock', TransportLock)


class TestLockableFiles_LockDir(TestCaseInTempDir,
                                _TestLockableFiles_mixin):
    """LockableFile tests run with LockDir underneath"""

    def setUp(self):
        super(TestLockableFiles_LockDir, self).setUp()
        self.transport = transport.get_transport_from_path('.')
        self.lockable = self.get_lockable()
        # the lock creation here sets mode - test_permissions on branch
        # tests that implicitly, but it might be a good idea to factor
        # out the mode checking logic and have it applied to loackable files
        # directly. RBC 20060418
        self.lockable.create_lock()

    def get_lockable(self):
        return LockableFiles(self.transport, 'my-lock', lockdir.LockDir)

    def test_lock_created(self):
        self.assertTrue(self.transport.has('my-lock'))
        self.lockable.lock_write()
        self.assertTrue(self.transport.has('my-lock/held/info'))
        self.lockable.unlock()
        self.assertFalse(self.transport.has('my-lock/held/info'))
        self.assertTrue(self.transport.has('my-lock'))

    def test__file_modes(self):
        self.transport.mkdir('readonly')
        osutils.make_readonly('readonly')
        lockable = LockableFiles(self.transport.clone('readonly'), 'test-lock',
                                 lockdir.LockDir)
        # The directory mode should be read-write-execute for the current user
        self.assertEqual(0o0700, lockable._dir_mode & 0o0700)
        # Files should be read-write for the current user
        self.assertEqual(0o0600, lockable._file_mode & 0o0700)


class TestLockableFiles_RemoteLockDir(TestCaseWithSmartMedium,
                                      _TestLockableFiles_mixin):
    """LockableFile tests run with RemoteLockDir on a branch."""

    def setUp(self):
        super(TestLockableFiles_RemoteLockDir, self).setUp()
        # can only get a RemoteLockDir with some RemoteObject...
        # use a branch as thats what we want. These mixin tests test the end
        # to end behaviour, so stubbing out the backend and simulating would
        # defeat the purpose. We test the protocol implementation separately
        # in test_remote and test_smart as usual.
        b = self.make_branch('foo')
        self.addCleanup(b.controldir.transport.disconnect)
        self.transport = transport.get_transport_from_path('.')
        self.lockable = self.get_lockable()

    def get_lockable(self):
        # getting a new lockable involves opening a new instance of the branch
        branch = breezy.branch.Branch.open(self.get_url('foo'))
        self.addCleanup(branch.controldir.transport.disconnect)
        return branch.control_files

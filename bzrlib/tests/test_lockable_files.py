# Copyright (C) 2005, 2006 Canonical Ltd
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

from StringIO import StringIO

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import BzrBadParameterNotString, NoSuchFile, ReadOnlyError
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib import lockdir
from bzrlib.lockdir import LockDir
from bzrlib.tests import TestCaseInTempDir
from bzrlib.tests.test_smart import TestCaseWithSmartMedium
from bzrlib.tests.test_transactions import DummyWeave
from bzrlib.transactions import (PassThroughTransaction,
                                 ReadOnlyTransaction,
                                 WriteTransaction,
                                 )
from bzrlib.transport import get_transport


# these tests are applied in each parameterized suite for LockableFiles
class _TestLockableFiles_mixin(object):

    def test_read_write(self):
        self.assertRaises(NoSuchFile, self.lockable.get, 'foo')
        self.assertRaises(NoSuchFile, self.lockable.get_utf8, 'foo')
        self.lockable.lock_write()
        try:
            unicode_string = u'bar\u1234'
            self.assertEqual(4, len(unicode_string))
            byte_string = unicode_string.encode('utf-8')
            self.assertEqual(6, len(byte_string))
            self.assertRaises(UnicodeEncodeError, self.lockable.put, 'foo',
                              StringIO(unicode_string))
            self.lockable.put('foo', StringIO(byte_string))
            self.assertEqual(byte_string,
                             self.lockable.get('foo').read())
            self.assertEqual(unicode_string,
                             self.lockable.get_utf8('foo').read())
            self.assertRaises(BzrBadParameterNotString,
                              self.lockable.put_utf8,
                              'bar',
                              StringIO(unicode_string)
                              )
            self.lockable.put_utf8('bar', unicode_string)
            self.assertEqual(unicode_string,
                             self.lockable.get_utf8('bar').read())
            self.assertEqual(byte_string,
                             self.lockable.get('bar').read())
            self.lockable.put_bytes('raw', 'raw\xffbytes')
            self.assertEqual('raw\xffbytes',
                             self.lockable.get('raw').read())
        finally:
            self.lockable.unlock()

    def test_locks(self):
        self.lockable.lock_read()
        try:
            self.assertRaises(ReadOnlyError, self.lockable.put, 'foo', 
                              StringIO('bar\u1234'))
        finally:
            self.lockable.unlock()

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
            return
        l2 = self.get_lockable()
        orig_factory = bzrlib.ui.ui_factory
        # silent ui - no need for stdout
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()
        bzrlib.ui.ui_factory.stdin = StringIO("y\n")
        try:
            l2.break_lock()
        finally:
            bzrlib.ui.ui_factory = orig_factory
        try:
            l2.lock_write()
            l2.unlock()
        finally:
            self.assertRaises(errors.LockBroken, self.lockable.unlock)
            self.assertFalse(self.lockable.is_locked())

    def test_lock_write_returns_None_refuses_token(self):
        token = self.lockable.lock_write()
        try:
            if token is not None:
                # This test does not apply, because this lockable supports
                # tokens.
                return
            self.assertRaises(errors.TokenLockingNotSupported,
                              self.lockable.lock_write, token='token')
        finally:
            self.lockable.unlock()

    def test_lock_write_returns_token_when_given_token(self):
        token = self.lockable.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            new_lockable = self.get_lockable()
            token_from_new_lockable = new_lockable.lock_write(token=token)
            try:
                self.assertEqual(token, token_from_new_lockable)
            finally:
                new_lockable.unlock()
        finally:
            self.lockable.unlock()

    def test_lock_write_raises_on_token_mismatch(self):
        token = self.lockable.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            different_token = token + 'xxx'
            # Re-using the same lockable instance with a different token will
            # raise TokenMismatch.
            self.assertRaises(errors.TokenMismatch,
                              self.lockable.lock_write, token=different_token)
            # A seperate instance for the same lockable will also raise
            # TokenMismatch.
            # This detects the case where a caller claims to have a lock (via
            # the token) for an external resource, but doesn't (the token is
            # different).  Clients need a seperate lock object to make sure the
            # external resource is probed, whereas the existing lock object
            # might cache.
            new_lockable = self.get_lockable()
            self.assertRaises(errors.TokenMismatch,
                              new_lockable.lock_write, token=different_token)
        finally:
            self.lockable.unlock()

    def test_lock_write_with_matching_token(self):
        # If the token matches, so no exception is raised by lock_write.
        token = self.lockable.lock_write()
        try:
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
        finally:
            self.lockable.unlock()

    def test_unlock_after_lock_write_with_token(self):
        # If lock_write did not physically acquire the lock (because it was
        # passed a token), then unlock should not physically release it.
        token = self.lockable.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            new_lockable = self.get_lockable()
            new_lockable.lock_write(token=token)
            new_lockable.unlock()
            self.assertTrue(self.lockable.get_physical_lock_status())
        finally:
            self.lockable.unlock()

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
        TestCaseInTempDir.setUp(self)
        transport = get_transport('.')
        transport.mkdir('.bzr')
        self.sub_transport = transport.clone('.bzr')
        self.lockable = self.get_lockable()
        self.lockable.create_lock()

    def tearDown(self):
        super(TestLockableFiles_TransportLock, self).tearDown()
        # free the subtransport so that we do not get a 5 second
        # timeout due to the SFTP connection cache.
        del self.sub_transport

    def get_lockable(self):
        return LockableFiles(self.sub_transport, 'my-lock', TransportLock)
        

class TestLockableFiles_LockDir(TestCaseInTempDir,
                              _TestLockableFiles_mixin):
    """LockableFile tests run with LockDir underneath"""

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.transport = get_transport('.')
        self.lockable = self.get_lockable()
        # the lock creation here sets mode - test_permissions on branch 
        # tests that implicitly, but it might be a good idea to factor 
        # out the mode checking logic and have it applied to loackable files
        # directly. RBC 20060418
        self.lockable.create_lock()

    def get_lockable(self):
        return LockableFiles(self.transport, 'my-lock', LockDir)

    def test_lock_created(self):
        self.assertTrue(self.transport.has('my-lock'))
        self.lockable.lock_write()
        self.assertTrue(self.transport.has('my-lock/held/info'))
        self.lockable.unlock()
        self.assertFalse(self.transport.has('my-lock/held/info'))
        self.assertTrue(self.transport.has('my-lock'))


    # TODO: Test the lockdir inherits the right file and directory permissions
    # from the LockableFiles.
        

class TestLockableFiles_RemoteLockDir(TestCaseWithSmartMedium,
                              _TestLockableFiles_mixin):
    """LockableFile tests run with RemoteLockDir on a branch."""

    def setUp(self):
        TestCaseWithSmartMedium.setUp(self)
        # can only get a RemoteLockDir with some RemoteObject...
        # use a branch as thats what we want. These mixin tests test the end
        # to end behaviour, so stubbing out the backend and simulating would
        # defeat the purpose. We test the protocol implementation separately
        # in test_remote and test_smart as usual.
        self.make_branch('foo')
        self.transport = get_transport('.')
        self.lockable = self.get_lockable()

    def get_lockable(self):
        # getting a new lockable involves opening a new instance of the branch
        branch = bzrlib.branch.Branch.open(self.get_url('foo'))
        return branch.control_files

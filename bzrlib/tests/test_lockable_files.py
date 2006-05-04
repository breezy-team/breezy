# Copyright (C) 2005, 2006 by Canonical Ltd

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

from StringIO import StringIO

import bzrlib
from bzrlib.branch import Branch
import bzrlib.errors as errors
from bzrlib.errors import BzrBadParameterNotString, NoSuchFile, ReadOnlyError
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.lockdir import LockDir
from bzrlib.tests import TestCaseInTempDir
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


# This method of adapting tests to parameters is different to 
# the TestProviderAdapters used elsewhere, but seems simpler for this 
# case.  
class TestLockableFiles_TransportLock(TestCaseInTempDir,
                                      _TestLockableFiles_mixin):

    def setUp(self):
        super(TestLockableFiles_TransportLock, self).setUp()
        transport = get_transport('.')
        transport.mkdir('.bzr')
        self.sub_transport = transport.clone('.bzr')
        self.lockable = self.get_lockable()
        self.lockable.create_lock()

    def tearDown(self):
        super(TestLockableFiles_TransportLock, self).tearDown()
        del self.sub_transport

    def get_lockable(self):
        return LockableFiles(self.sub_transport, 'my-lock', TransportLock)
        

class TestLockableFiles_LockDir(TestCaseInTempDir,
                              _TestLockableFiles_mixin):
    """LockableFile tests run with LockDir underneath"""

    def setUp(self):
        super(TestLockableFiles_LockDir, self).setUp()
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

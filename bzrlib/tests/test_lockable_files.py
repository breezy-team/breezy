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

from bzrlib.branch import Branch
from bzrlib.errors import BzrBadParameterNotString, NoSuchFile, ReadOnlyError
from bzrlib.lockable_files import LockableFiles
from bzrlib.lockdir import LockDir
from bzrlib.tests import TestCaseInTempDir
from bzrlib.transactions import PassThroughTransaction, ReadOnlyTransaction
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
                      PassThroughTransaction)
        self.lockable.unlock()

    def test__escape(self):
        self.assertEqual('%25', self.lockable._escape('%'))
        
    def test__escape_empty(self):
        self.assertEqual('', self.lockable._escape(''))


# This method of adapting tests to parameters is different to 
# the TestProviderAdapters used elsewhere, but seems simpler for this 
# case.  
class TestLockableFiles_TransportLock(TestCaseInTempDir,
                                      _TestLockableFiles_mixin):

    def setUp(self):
        super(TestLockableFiles_TransportLock, self).setUp()
        transport = get_transport('.')
        transport.mkdir('.bzr')
        transport.put('.bzr/my-lock', StringIO(''))
        sub_transport = transport.clone('.bzr')
        self.lockable = LockableFiles(sub_transport, 'my-lock')
        

class TestLockableFiles_LockDir(TestCaseInTempDir,
                              _TestLockableFiles_mixin):
    """LockableFile tests run with LockDir underneath"""

    def setUp(self):
        super(TestLockableFiles_LockDir, self).setUp()
        transport = get_transport('.')
        self.lockable = LockableFiles(transport, 'my-lock', LockDir)

    def test_lock_is_lockdir(self):
        """Created instance should use a LockDir.
        
        This primarily tests the mixin adapter works properly.
        """
        ## self.assertIsInstance(self.lockable, LockableFiles)
        ## self.assertIsInstance(self.lockable._lock_strategy,
                              ## LockDirStrategy)

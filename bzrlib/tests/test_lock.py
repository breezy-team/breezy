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

"""Tests for OS level locks."""

from bzrlib import (
    errors,
    lock,
    osutils,
    tests,
    )


class TestLock(tests.TestCaseInTempDir):

    def setUp(self):
        super(TestLock, self).setUp()
        self.build_tree(['a-file'])

    def test_read_lock(self):
        """Smoke test for read locks."""
        a_lock = lock.ReadLock('a-file')
        self.addCleanup(a_lock.unlock)
        # The lock file should be opened for reading
        txt = a_lock.f.read()
        self.assertEqual('contents of a-file\n', txt)

    def test_create_if_needed_read(self):
        """We will create the file if it doesn't exist yet."""
        a_lock = lock.ReadLock('other-file')
        self.addCleanup(a_lock.unlock)
        txt = a_lock.f.read()
        self.assertEqual('', txt)

    def test_create_if_needed_write(self):
        """We will create the file if it doesn't exist yet."""
        a_lock = lock.WriteLock('other-file')
        self.addCleanup(a_lock.unlock)
        txt = a_lock.f.read()
        self.assertEqual('', txt)
        a_lock.f.write('foo\n')
        a_lock.f.seek(0)
        txt = a_lock.f.read()
        self.assertEqual('foo\n', txt)

    def test_readonly_file(self):
        """If the file is readonly, we can take a read lock.

        But we shouldn't be able to take a write lock.
        """
        osutils.make_readonly('a-file')
        # Make sure the file is read-only (on all platforms)
        self.assertRaises(IOError, open, 'a-file', 'rb+')
        a_lock = lock.ReadLock('a-file')
        a_lock.unlock()

        # TODO: jam 20070313 This should be a specific subclass
        self.assertRaises(errors.ReadOnlyLockError, lock.WriteLock, 'a-file')

    def test_write_lock(self):
        """Smoke test for write locks."""
        a_lock = lock.WriteLock('a-file')
        self.addCleanup(a_lock.unlock)
        # You should be able to read and write to the lock file.
        txt = a_lock.f.read()
        self.assertEqual('contents of a-file\n', txt)
        # Win32 requires that you call seek() when switching between a read
        # operation and a write operation.
        a_lock.f.seek(0, 2)
        a_lock.f.write('more content\n')
        a_lock.f.seek(0)
        txt = a_lock.f.read()
        self.assertEqual('contents of a-file\nmore content\n', txt)

    def test_multiple_read_locks(self):
        """You can take out more than one read lock on the same file."""
        a_lock = lock.ReadLock('a-file')
        self.addCleanup(a_lock.unlock)
        b_lock = lock.ReadLock('a-file')
        self.addCleanup(b_lock.unlock)

    def test_multiple_write_locks_exclude(self):
        """Taking out more than one write lock should fail."""
        a_lock = lock.WriteLock('a-file')
        self.addCleanup(a_lock.unlock)
        # Taking out a lock on a locked file should raise LockContention
        self.assertRaises(errors.LockContention, lock.WriteLock, 'a-file')

    def _disabled_test_read_then_write_excludes(self):
        """If a file is read-locked, taking out a write lock should fail."""
        a_lock = lock.ReadLock('a-file')
        self.addCleanup(a_lock.unlock)
        # Taking out a lock on a locked file should raise LockContention
        self.assertRaises(errors.LockContention, lock.WriteLock, 'a-file')

    def _disabled_test_write_then_read_excludes(self):
        """If a file is write-locked, taking out a read lock should fail.

        The file is exclusively owned by the write lock, so we shouldn't be
        able to take out a shared read lock.
        """
        a_lock = lock.WriteLock('a-file')
        self.addCleanup(a_lock.unlock)
        # Taking out a lock on a locked file should raise LockContention
        self.assertRaises(errors.LockContention, lock.ReadLock, 'a-file')

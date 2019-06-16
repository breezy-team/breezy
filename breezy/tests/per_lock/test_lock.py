# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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

"""Tests for OS level locks."""

from breezy import (
    errors,
    osutils,
    )

from breezy.tests import (
    features,
    )
from breezy.tests.per_lock import TestCaseWithLock


class TestLock(TestCaseWithLock):

    def setUp(self):
        super(TestLock, self).setUp()
        self.build_tree(['a-file'])

    def test_read_lock(self):
        """Smoke test for read locks."""
        a_lock = self.read_lock('a-file')
        self.addCleanup(a_lock.unlock)
        # The lock file should be opened for reading
        txt = a_lock.f.read()
        self.assertEqual(b'contents of a-file\n', txt)

    def test_create_if_needed_read(self):
        """We will create the file if it doesn't exist yet."""
        a_lock = self.read_lock('other-file')
        self.addCleanup(a_lock.unlock)
        txt = a_lock.f.read()
        self.assertEqual(b'', txt)

    def test_create_if_needed_write(self):
        """We will create the file if it doesn't exist yet."""
        a_lock = self.write_lock('other-file')
        self.addCleanup(a_lock.unlock)
        txt = a_lock.f.read()
        self.assertEqual(b'', txt)
        a_lock.f.seek(0)
        a_lock.f.write(b'foo\n')
        a_lock.f.seek(0)
        txt = a_lock.f.read()
        self.assertEqual(b'foo\n', txt)

    def test_readonly_file(self):
        """If the file is readonly, we can take a read lock.

        But we shouldn't be able to take a write lock.
        """
        self.requireFeature(features.not_running_as_root)
        osutils.make_readonly('a-file')
        # Make sure the file is read-only (on all platforms)
        self.assertRaises(IOError, open, 'a-file', 'rb+')
        a_lock = self.read_lock('a-file')
        a_lock.unlock()

        self.assertRaises(errors.LockFailed, self.write_lock, 'a-file')

    def test_write_lock(self):
        """Smoke test for write locks."""
        a_lock = self.write_lock('a-file')
        self.addCleanup(a_lock.unlock)
        # You should be able to read and write to the lock file.
        txt = a_lock.f.read()
        self.assertEqual(b'contents of a-file\n', txt)
        # Win32 requires that you call seek() when switching between a read
        # operation and a write operation.
        a_lock.f.seek(0, 2)
        a_lock.f.write(b'more content\n')
        a_lock.f.seek(0)
        txt = a_lock.f.read()
        self.assertEqual(b'contents of a-file\nmore content\n', txt)

    def test_multiple_read_locks(self):
        """You can take out more than one read lock on the same file."""
        a_lock = self.read_lock('a-file')
        self.addCleanup(a_lock.unlock)
        b_lock = self.read_lock('a-file')
        self.addCleanup(b_lock.unlock)

    def test_multiple_write_locks_exclude(self):
        """Taking out more than one write lock should fail."""
        a_lock = self.write_lock('a-file')
        self.addCleanup(a_lock.unlock)
        # Taking out a lock on a locked file should raise LockContention
        self.assertRaises(errors.LockContention, self.write_lock, 'a-file')

    def _disabled_test_read_then_write_excludes(self):
        """If a file is read-locked, taking out a write lock should fail."""
        a_lock = self.read_lock('a-file')
        self.addCleanup(a_lock.unlock)
        # Taking out a lock on a locked file should raise LockContention
        self.assertRaises(errors.LockContention, self.write_lock, 'a-file')

    def test_read_unlock_write(self):
        """Make sure that unlocking allows us to lock write"""
        a_lock = self.read_lock('a-file')
        a_lock.unlock()
        a_lock = self.write_lock('a-file')
        a_lock.unlock()

    # TODO: jam 20070319 fcntl read locks are not currently fully
    #       mutually exclusive with write locks. This will be fixed
    #       in the next release.
    def _disabled_test_write_then_read_excludes(self):
        """If a file is write-locked, taking out a read lock should fail.

        The file is exclusively owned by the write lock, so we shouldn't be
        able to take out a shared read lock.
        """
        a_lock = self.write_lock('a-file')
        self.addCleanup(a_lock.unlock)
        # Taking out a lock on a locked file should raise LockContention
        self.assertRaises(errors.LockContention, self.read_lock, 'a-file')

    # TODO: jam 20070319 fcntl write locks are not currently fully
    #       mutually exclusive with read locks. This will be fixed
    #       in the next release.
    def _disabled_test_write_unlock_read(self):
        """If we have removed the write lock, we can grab a read lock."""
        a_lock = self.write_lock('a-file')
        a_lock.unlock()
        a_lock = self.read_lock('a-file')
        a_lock.unlock()

    def _disabled_test_multiple_read_unlock_write(self):
        """We can only grab a write lock if all read locks are done."""
        a_lock = b_lock = c_lock = None
        try:
            a_lock = self.read_lock('a-file')
            b_lock = self.read_lock('a-file')
            self.assertRaises(errors.LockContention, self.write_lock, 'a-file')
            a_lock.unlock()
            a_lock = None
            self.assertRaises(errors.LockContention, self.write_lock, 'a-file')
            b_lock.unlock()
            b_lock = None
            c_lock = self.write_lock('a-file')
            c_lock.unlock()
            c_lock = None
        finally:
            # Cleanup as needed
            if a_lock is not None:
                a_lock.unlock()
            if b_lock is not None:
                b_lock.unlock()
            if c_lock is not None:
                c_lock.unlock()


class TestLockUnicodePath(TestCaseWithLock):

    _test_needs_features = [features.UnicodeFilenameFeature]

    def test_read_lock(self):
        self.build_tree([u'\u1234'])
        u_lock = self.read_lock(u'\u1234')
        self.addCleanup(u_lock.unlock)

    def test_write_lock(self):
        self.build_tree([u'\u1234'])
        u_lock = self.write_lock(u'\u1234')
        self.addCleanup(u_lock.unlock)

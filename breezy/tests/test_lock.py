# Copyright (C) 2009, 2011 Canonical Ltd
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

"""Tests for OS Locks."""

from .. import _transport_rs, errors, lock, tests


class TestOSLock(tests.TestCaseInTempDir):
    read_lock = _transport_rs.ReadLock
    write_lock = _transport_rs.WriteLock

    def setUp(self):
        super().setUp()
        self.build_tree(["a-lock-file"])

    def test_create_read_lock(self):
        r_lock = self.read_lock("a-lock-file")
        r_lock.unlock()

    def test_create_write_lock(self):
        w_lock = self.write_lock("a-lock-file")
        w_lock.unlock()

    def test_read_locks_share(self):
        r_lock = self.read_lock("a-lock-file")
        try:
            lock2 = self.read_lock("a-lock-file")
            lock2.unlock()
        finally:
            r_lock.unlock()

    def test_write_locks_are_exclusive(self):
        w_lock = self.write_lock("a-lock-file")
        try:
            self.assertRaises(errors.LockContention, self.write_lock, "a-lock-file")
        finally:
            w_lock.unlock()

    def test_read_locks_block_write_locks(self):
        r_lock = self.read_lock("a-lock-file")
        try:
            if lock.have_fcntl:
                # With -Dlock, fcntl locks are properly exclusive
                self.assertRaises(
                    errors.LockContention, self.write_lock, "a-lock-file", True
                )
                # But not without it
                try:
                    w_lock = self.write_lock("a-lock-file", False)
                except errors.LockContention:
                    self.fail(
                        "Unexpected success. fcntl read locks"
                        " do not usually block write locks"
                    )
                else:
                    w_lock.unlock()
                    self.knownFailure(
                        "fcntl read locks don't block write locks without -Dlock"
                    )
            else:
                w_lock.unlock()
                self.knownFailure(
                    "fcntl read locks don't block write locks without -Dlock"
                )
        finally:
            r_lock.unlock()

    def test_write_locks_block_read_lock(self):
        w_lock = self.write_lock("a-lock-file")
        try:
            if lock.have_fcntl:
                # With -Dlock, fcntl locks are properly exclusive
                self.assertRaises(
                    errors.LockContention, self.read_lock, "a-lock-file", True
                )
                # But not without it
                try:
                    r_lock = self.read_lock("a-lock-file", False)
                except errors.LockContention:
                    self.fail(
                        "Unexpected success. fcntl write locks"
                        " do not usually block read locks"
                    )
                else:
                    r_lock.unlock()
                    self.knownFailure(
                        "fcntl write locks don't block read locks without -Dlock"
                    )
            else:
                r_lock.unlock()
                self.knownFailure(
                    "fcntl write locks don't block read locks without -Dlock"
                )
        finally:
            w_lock.unlock()

    def test_temporary_write_lock(self):
        r_lock = self.read_lock("a-lock-file")
        try:
            status, w_lock = r_lock.temporary_write_lock()
            self.assertTrue(status)
            # This should block another write lock
            try:
                self.assertRaises(errors.LockContention, self.write_lock, "a-lock-file")
            finally:
                r_lock = w_lock.restore_read_lock()
            # We should be able to take a read lock now
            r_lock2 = self.read_lock("a-lock-file")
            r_lock2.unlock()
        finally:
            r_lock.unlock()

    def test_temporary_write_lock_fails(self):
        r_lock = self.read_lock("a-lock-file")
        try:
            r_lock2 = self.read_lock("a-lock-file")
            try:
                status, w_lock = r_lock.temporary_write_lock()
                self.assertFalse(status)
                # Taking out the lock requires unlocking and locking again, so
                # we have to replace the original object
                r_lock = w_lock
            finally:
                r_lock2.unlock()
            # We should be able to take a read lock now
            r_lock2 = self.read_lock("a-lock-file")
            r_lock2.unlock()
        finally:
            r_lock.unlock()

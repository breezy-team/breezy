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

"""Test locks across all branch implemenations"""

from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib.tests.LockHelpers import TestPreventLocking, LockWrapper


class TestBranchLocking(TestCaseWithBranch):

    def get_instrumented_branch(self):
        """Get a Branch object which has been instrumented"""
        # TODO: jam 20060630 It may be that not all formats have a 
        # 'control_files' member. So we should fail gracefully if
        # not there. But assuming it has them lets us test the exact 
        # lock/unlock order.
        self.locks = []
        b = LockWrapper(self.locks, self.get_branch(), 'b')
        b.repository = LockWrapper(self.locks, b.repository, 'r')
        bcf = b.control_files
        rcf = b.repository.control_files

        # Look out for branch types that reuse their control files
        self.combined_control = bcf is rcf

        b.control_files = LockWrapper(self.locks, b.control_files, 'bc')
        b.repository.control_files = \
            LockWrapper(self.locks, b.repository.control_files, 'rc')
        return b

    def test_01_lock_read(self):
        # Test that locking occurs in the correct order
        b = self.get_instrumented_branch()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_read()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
        finally:
            b.unlock()
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lr', True),
                          ('r', 'lr', True),
                          ('rc', 'lr', True),
                          ('bc', 'lr', True),
                          ('b', 'ul', True),
                          ('bc', 'ul', True),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_02_lock_write(self):
        # Test that locking occurs in the correct order
        b = self.get_instrumented_branch()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_write()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
        finally:
            b.unlock()
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lw', True),
                          ('r', 'lw', True),
                          ('rc', 'lw', True),
                          ('bc', 'lw', True),
                          ('b', 'ul', True),
                          ('bc', 'ul', True),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_03_lock_fail_unlock_repo(self):
        # Make sure branch.unlock() is called, even if there is a
        # failure while unlocking the repository.
        b = self.get_instrumented_branch()
        b.repository.disable_unlock()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_write()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
            self.assertRaises(TestPreventLocking, b.unlock)
            if self.combined_control:
                self.assertTrue(b.is_locked())
            else:
                self.assertFalse(b.is_locked())
            self.assertTrue(b.repository.is_locked())

            # We unlock the branch control files, even if 
            # we fail to unlock the repository
            self.assertEqual([('b', 'lw', True),
                              ('r', 'lw', True),
                              ('rc', 'lw', True),
                              ('bc', 'lw', True),
                              ('b', 'ul', True),
                              ('bc', 'ul', True),
                              ('r', 'ul', False), 
                             ], self.locks)

        finally:
            # For cleanup purposes, make sure we are unlocked
            b.repository._other.unlock()

    def test_04_lock_fail_unlock_control(self):
        # Make sure repository.unlock() is called, if we fail to unlock self
        b = self.get_instrumented_branch()
        b.control_files.disable_unlock()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_write()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
            self.assertRaises(TestPreventLocking, b.unlock)
            self.assertTrue(b.is_locked())
            if self.combined_control:
                self.assertTrue(b.repository.is_locked())
            else:
                self.assertFalse(b.repository.is_locked())

            # We unlock the repository even if 
            # we fail to unlock the control files
            self.assertEqual([('b', 'lw', True),
                              ('r', 'lw', True),
                              ('rc', 'lw', True),
                              ('bc', 'lw', True),
                              ('b', 'ul', True),
                              ('bc', 'ul', False),
                              ('r', 'ul', True), 
                              ('rc', 'ul', True), 
                             ], self.locks)

        finally:
            # For cleanup purposes, make sure we are unlocked
            b.control_files._other.unlock()

    def test_05_lock_read_fail_repo(self):
        # Test that the branch is not locked if it cannot lock the repository
        b = self.get_instrumented_branch()
        b.repository.disable_lock_read()

        self.assertRaises(TestPreventLocking, b.lock_read)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lr', True),
                          ('r', 'lr', False), 
                         ], self.locks)

    def test_06_lock_write_fail_repo(self):
        # Test that the branch is not locked if it cannot lock the repository
        b = self.get_instrumented_branch()
        b.repository.disable_lock_write()

        self.assertRaises(TestPreventLocking, b.lock_write)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lw', True),
                          ('r', 'lw', False), 
                         ], self.locks)

    def test_07_lock_read_fail_control(self):
        # Test the repository is unlocked if we can't lock self
        b = self.get_instrumented_branch()
        b.control_files.disable_lock_read()

        self.assertRaises(TestPreventLocking, b.lock_read)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lr', True),
                          ('r', 'lr', True),
                          ('rc', 'lr', True),
                          ('bc', 'lr', False),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_08_lock_write_fail_control(self):
        # Test the repository is unlocked if we can't lock self
        b = self.get_instrumented_branch()
        b.control_files.disable_lock_write()

        self.assertRaises(TestPreventLocking, b.lock_write)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lw', True),
                          ('r', 'lw', True),
                          ('rc', 'lw', True),
                          ('bc', 'lw', False),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)


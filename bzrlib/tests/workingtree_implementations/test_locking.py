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

from bzrlib.tests.LockHelpers import TestPreventLocking, LockWrapper
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestWorkingTreeLocking(TestCaseWithWorkingTree):

    def get_instrumented_tree(self):
        """Get a WorkingTree object which has been instrumented"""
        # TODO: jam 20060630 It may be that not all formats have a 
        # '_control_files' member. So we should fail gracefully if
        # not there. But assuming it has them lets us test the exact 
        # lock/unlock order.
        self.locks = []
        wt = self.make_branch_and_tree('.')
        wt = LockWrapper(self.locks, wt, 't')
        wt._branch = LockWrapper(self.locks, wt._branch, 'b')

        tcf = wt._control_files
        bcf = wt.branch.control_files

        # Look out for AllInOne
        self.combined_control = tcf is bcf

        wt._control_files = LockWrapper(self.locks, wt._control_files, 'tc')
        wt.branch.control_files = \
            LockWrapper(self.locks, wt.branch.control_files, 'bc')
        return wt

    def test_01_lock_read(self):
        # Test that locking occurs in the correct order
        wt = self.get_instrumented_tree()

        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())
        wt.lock_read()
        try:
            self.assertTrue(wt.is_locked())
            self.assertTrue(wt.branch.is_locked())
        finally:
            wt.unlock()
        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())

        self.assertEqual([('t', 'lr', True),
                          ('b', 'lr', True),
                          ('bc', 'lr', True),
                          ('tc', 'lr', True),
                          ('t', 'ul', True),
                          ('tc', 'ul', True),
                          ('b', 'ul', True),
                          ('bc', 'ul', True),
                         ], self.locks)

    def test_02_lock_write(self):
        # Test that locking occurs in the correct order
        wt = self.get_instrumented_tree()

        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())
        wt.lock_write()
        try:
            self.assertTrue(wt.is_locked())
            self.assertTrue(wt.branch.is_locked())
        finally:
            wt.unlock()
        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())

        self.assertEqual([('t', 'lw', True),
                          ('b', 'lw', True),
                          ('bc', 'lw', True),
                          ('tc', 'lw', True),
                          ('t', 'ul', True),
                          ('tc', 'ul', True),
                          ('b', 'ul', True),
                          ('bc', 'ul', True),
                         ], self.locks)

    def test_03_lock_fail_unlock_branch(self):
        # Make sure tree.unlock() is called, even if there is a
        # failure while unlocking the branch.
        wt = self.get_instrumented_tree()
        wt.branch.disable_unlock()

        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())
        wt.lock_write()
        try:
            self.assertTrue(wt.is_locked())
            self.assertTrue(wt.branch.is_locked())
            self.assertRaises(TestPreventLocking, wt.unlock)
            if self.combined_control:
                self.assertTrue(wt.is_locked())
            else:
                self.assertFalse(wt.is_locked())
            self.assertTrue(wt.branch.is_locked())

            self.assertEqual([('t', 'lw', True),
                              ('b', 'lw', True),
                              ('bc', 'lw', True),
                              ('tc', 'lw', True),
                              ('t', 'ul', True),
                              ('tc', 'ul', True),
                              ('b', 'ul', False), 
                             ], self.locks)

        finally:
            # For cleanup purposes, make sure we are unlocked
            wt.branch._other.unlock()

    def test_04_lock_fail_unlock_control(self):
        # Make sure that branch is unlocked, even if we fail to unlock self
        wt = self.get_instrumented_tree()
        wt._control_files.disable_unlock()

        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())
        wt.lock_write()
        try:
            self.assertTrue(wt.is_locked())
            self.assertTrue(wt.branch.is_locked())
            self.assertRaises(TestPreventLocking, wt.unlock)
            self.assertTrue(wt.is_locked())
            if self.combined_control:
                self.assertTrue(wt.branch.is_locked())
            else:
                self.assertFalse(wt.branch.is_locked())

            self.assertEqual([('t', 'lw', True),
                              ('b', 'lw', True),
                              ('bc', 'lw', True),
                              ('tc', 'lw', True),
                              ('t', 'ul', True),
                              ('tc', 'ul', False),
                              ('b', 'ul', True), 
                              ('bc', 'ul', True), 
                             ], self.locks)

        finally:
            # For cleanup purposes, make sure we are unlocked
            wt._control_files._other.unlock()

    def test_05_lock_read_fail_branch(self):
        # Test that the tree is not locked if it cannot lock the branch
        wt = self.get_instrumented_tree()
        wt.branch.disable_lock_read()

        self.assertRaises(TestPreventLocking, wt.lock_read)
        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())

        self.assertEqual([('t', 'lr', True),
                          ('b', 'lr', False), 
                         ], self.locks)

    def test_06_lock_write_fail_branch(self):
        # Test that the tree is not locked if it cannot lock the branch
        wt = self.get_instrumented_tree()
        wt.branch.disable_lock_write()

        self.assertRaises(TestPreventLocking, wt.lock_write)
        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())

        self.assertEqual([('t', 'lw', True),
                          ('b', 'lw', False), 
                         ], self.locks)

    def test_07_lock_read_fail_control(self):
        # We should unlock the branch if we can't lock the tree
        wt = self.get_instrumented_tree()
        wt._control_files.disable_lock_read()

        self.assertRaises(TestPreventLocking, wt.lock_read)
        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())

        self.assertEqual([('t', 'lr', True),
                          ('b', 'lr', True),
                          ('bc', 'lr', True),
                          ('tc', 'lr', False),
                          ('b', 'ul', True),
                          ('bc', 'ul', True)
                         ], self.locks)

    def test_08_lock_write_fail_control(self):
        # We shouldn't try to lock the repo if we can't lock the branch
        wt = self.get_instrumented_tree()
        wt._control_files.disable_lock_write()

        self.assertRaises(TestPreventLocking, wt.lock_write)
        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())

        self.assertEqual([('t', 'lw', True),
                          ('b', 'lw', True),
                          ('bc', 'lw', True),
                          ('tc', 'lw', False),
                          ('b', 'ul', True),
                          ('bc', 'ul', True)
                         ], self.locks)

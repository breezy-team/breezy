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

"""Tests for the (un)lock interfaces on all working tree implemenations."""

import bzrlib.branch as branch
import bzrlib.errors as errors
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestWorkingTreeLocking(TestCaseWithWorkingTree):

    def test_trivial_lock_read_unlock(self):
        """Locking and unlocking should work trivially."""
        wt = self.make_branch_and_tree('.')

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

    def test_trivial_lock_write_unlock(self):
        """Locking for write and unlocking should work trivially."""
        wt = self.make_branch_and_tree('.')

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
        
    def test_unlock_branch_failures(self):
        """If the branch unlock fails the tree must still unlock."""
        # The public interface for WorkingTree requires a branch, but
        # does not require that the working tree use the branch - its
        # implementation specific how the WorkingTree, Branch, and Repository
        # hang together.
        # in order to test that implementations which *do* unlock via the branch
        # do so correctly, we unlock the branch after locking the working tree.
        # The next unlock on working tree should trigger a LockNotHeld exception
        # from the branch object, which must be exposed to the caller. To meet 
        # our object model - where locking a tree locks its branch, and
        # unlocking a branch does not unlock a working tree, *even* for 
        # all-in-one implementations like bzr 0.6, git, and hg, implementations
        # must have some separate counter for each object, so our explicit 
        # unlock should trigger some error on all implementations, and 
        # requiring that to be LockNotHeld seems reasonable.
        #
        # we use this approach rather than decorating the Branch, because the
        # public interface of WorkingTree does not permit altering the branch
        # object - and we cannot tell which attribute might allow us to 
        # backdoor-in and change it reliably. For implementation specific tests
        # we can do such skullduggery, but not for interface specific tests.
        # And, its simpler :)
        wt = self.make_branch_and_tree('.')

        self.assertFalse(wt.is_locked())
        self.assertFalse(wt.branch.is_locked())
        wt.lock_write()
        self.assertTrue(wt.is_locked())
        self.assertTrue(wt.branch.is_locked())

        # manually unlock the branch, preparing a LockNotHeld error.
        wt.branch.unlock()
        # the branch *may* still be locked here, if its an all-in-one
        # implementation
        self.assertRaises(errors.LockNotHeld, wt.unlock)
        # but now, the tree must be unlocked
        self.assertFalse(wt.is_locked())
        # and the branch too.
        self.assertFalse(wt.branch.is_locked())

    def test_failing_to_lock_branch_does_not_lock(self):
        """If the branch cannot be locked, dont lock the tree."""
        # Many implementations treat read-locks as non-blocking, but some
        # treat them as blocking with writes.. Accordingly we test this by
        # opening the branch twice, and locking the branch for write in the
        # second instance.  Our lock contract requires separate instances to
        # mutually exclude if a lock is exclusive at all: If we get no error
        # locking, the test still passes.
        wt = self.make_branch_and_tree('.')
        branch_copy = branch.Branch.open('.')
        branch_copy.lock_write()
        try:
            try:
                wt.lock_read()
            except:
                # any error here means the locks are exclusive in some 
                # manner
                self.assertFalse(wt.is_locked())
                self.assertFalse(wt.branch.is_locked())
                return
            else:
                # no error - the branch allows read locks while writes
                # are taken, just pass.
                wt.unlock()
        finally:
            branch_copy.unlock()

    def test_failing_to_lock_write_branch_does_not_lock(self):
        """If the branch cannot be write locked, dont lock the tree."""
        # all implementations of branch are required to treat write 
        # locks as blocking (compare to repositories which are not required
        # to do so).
        # Accordingly we test this by opening the branch twice, and locking the
        # branch for write in the second instance.  Our lock contract requires
        # separate instances to mutually exclude.
        wt = self.make_branch_and_tree('.')
        branch_copy = branch.Branch.open('.')
        branch_copy.lock_write()
        try:
            try:
                self.assertRaises(errors.LockError, wt.lock_write)
                self.assertFalse(wt.is_locked())
                self.assertFalse(wt.branch.is_locked())
            finally:
                if wt.is_locked():
                    wt.unlock()
        finally:
            branch_copy.unlock()

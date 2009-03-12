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

"""Tests for bzrlib.switch."""


import os

from bzrlib import branch, errors, switch, tests


class TestSwitch(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestSwitch, self).setUp()
        self.lightweight = True

    def _setup_tree(self):
        tree = self.make_branch_and_tree('branch-1')
        self.build_tree(['branch-1/file-1'])
        tree.add('file-1')
        tree.commit('rev1')
        return tree

    def test_switch_updates(self):
        """Test switch updates tree and keeps uncommitted changes."""
        tree = self._setup_tree()
        to_branch = tree.bzrdir.sprout('branch-2').open_branch()
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        switch.switch(checkout.bzrdir, to_branch)
        self.failUnlessExists('checkout/file-1')
        self.failIfExists('checkout/file-2')
        self.failUnlessExists('checkout/file-3')

    def test_switch_after_branch_moved(self):
        """Test switch after the branch is moved."""
        tree = self._setup_tree()
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        checkout_dir = checkout.bzrdir
        # rename the branch on disk, the checkout object is now invalid.
        os.rename('branch-1', 'branch-2')
        to_branch = branch.Branch.open('branch-2')
        # Check fails without --force
        err = self.assertRaises((errors.NotBranchError,
            errors.BoundBranchConnectionFailure),
            switch.switch, checkout.bzrdir, to_branch)
        switch.switch(checkout.bzrdir, to_branch, force=True)
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        self.failUnlessExists('checkout/file-3')

    def test_switch_when_pending_merges(self):
        """Test graceful failure if pending merges are outstanding."""
        # Create 2 branches and a checkout
        tree = self._setup_tree()
        tree2 = tree.bzrdir.sprout('branch-2').open_workingtree()
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        # Change tree2 and merge it into the checkout without committing
        self.build_tree(['branch-2/file-2'])
        tree2.add('file-2')
        tree2.commit('rev2')
        checkout.merge_from_branch(tree2.branch)
        # Check the error reporting is as expected
        err = self.assertRaises(errors.BzrCommandError,
            switch.switch, checkout.bzrdir, tree2.branch)
        self.assertContainsRe(str(err),
            "Pending merges must be committed or reverted before using switch")


class TestSwitchHeavyweight(TestSwitch):

    def setUp(self):
        super(TestSwitchHeavyweight, self).setUp()
        self.lightweight = False

    def test_switch_with_local_commits(self):
        """Test switch complains about local commits unless --force given."""
        tree = self._setup_tree()
        to_branch = tree.bzrdir.sprout('branch-2').open_branch()
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        checkout = tree.branch.create_checkout('checkout')
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        checkout.commit(message='local only commit', local=True)
        self.build_tree(['checkout/file-4'])
        # Check the error reporting is as expected
        err = self.assertRaises(errors.BzrCommandError,
            switch.switch, checkout.bzrdir, to_branch)
        self.assertContainsRe(str(err),
            'Cannot switch as local commits found in the checkout.')
        # Check all is ok when force is given
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        switch.switch(checkout.bzrdir, to_branch, force=True)
        self.failUnlessExists('checkout/file-1')
        self.failIfExists('checkout/file-2')
        self.failIfExists('checkout/file-3')
        self.failUnlessExists('checkout/file-4')
        # Check that the checkout is a true mirror of the bound branch
        self.assertEqual(to_branch.last_revision_info(),
                         checkout.branch.last_revision_info())

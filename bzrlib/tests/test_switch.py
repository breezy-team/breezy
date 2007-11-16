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

    def test_switch_moved(self):
        tree = self.make_branch_and_tree('branch-1')
        self.build_tree(['branch-1/file-1'])
        tree.add('file-1')
        tree.commit('rev1')
        checkout = tree.branch.create_checkout('checkout', lightweight=True)
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        os.rename('branch-1', 'branch-2')
        to_branch = branch.Branch.open('branch-2')
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        switch.switch(checkout.bzrdir, to_branch)
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        self.failUnlessExists('checkout/file-3')

    def test_switch_old(self):
        tree = self.make_branch_and_tree('branch-1')
        self.build_tree(['branch-1/file-1'])
        tree.add('file-1')
        tree.commit('rev1')
        to_branch = tree.bzrdir.sprout('branch-2').open_branch()
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        checkout = tree.branch.create_checkout('checkout', lightweight=True)
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        switch.switch(checkout.bzrdir, to_branch)
        self.failUnlessExists('checkout/file-1')
        self.failIfExists('checkout/file-2')
        self.failUnlessExists('checkout/file-3')

    def test_switch_heavy_checkout(self):
        tree = self.make_branch_and_tree('branch-1')
        self.build_tree(['branch-1/file-1'])
        tree.add('file-1')
        tree.commit('rev1')
        tree.branch.create_checkout('checkout-1', lightweight=False)
        branch2 = self.make_branch('branch-2')
        err = self.assertRaises(errors.BzrCommandError,
                                switch.switch, tree.bzrdir, branch2)
        self.assertContainsRe(str(err),
            "The switch command can only be used on a lightweight checkout")

# Copyright (C) 2007 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Tests for the switch command of bzr."""

import os

from bzrlib.tests.blackbox import ExternalBase


class TestSwitch(ExternalBase):

    def test_switch_up_to_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('branch branch branch2')
        self.run_bzr('checkout --lightweight branch checkout')
        os.chdir('checkout')
        out, err = self.run_bzr('switch ../branch2')
        self.assertContainsRe(err, 'Tree is up to date at revision 0.\n')
        self.assertContainsRe(err, 'Switched to branch: .*/branch2.\n')
        self.assertEqual('', out)

    def test_switch_out_of_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('branch branch branch2')
        self.build_tree(['branch2/file'])
        self.run_bzr('add branch2/file')
        self.run_bzr('commit -m add-file branch2')
        self.run_bzr('checkout --lightweight branch checkout')
        os.chdir('checkout')
        out, err = self.run_bzr('switch ../branch2')
        #self.assertContainsRe(err, '\+N  file')
        self.assertContainsRe(err, 'Updated to revision 1.\n')
        self.assertContainsRe(err, 'Switched to branch: .*/branch2.\n')
        self.assertEqual('', out)

    def test_switch_finds_relative_branch(self):
        """Switch will find 'foo' relative to the branch that the checkout is of."""
        self.build_tree(['repo/'])
        tree1 = self.make_branch_and_tree('repo/brancha')
        tree1.commit('foo')
        tree2 = self.make_branch_and_tree('repo/branchb')
        tree2.pull(tree1.branch)
        branchb_id = tree2.commit('bar')
        checkout =  tree1.branch.create_checkout('checkout', lightweight=True)
        self.run_bzr(['switch', 'branchb'], working_dir='checkout')
        self.assertEqual(branchb_id, checkout.last_revision())
        checkout = checkout.bzrdir.open_workingtree()
        self.assertEqual(tree2.branch.base, checkout.branch.base)
        

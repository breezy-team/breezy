# Copyright (C) 2006 Canonical Ltd

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

"""Tests for lock-breaking user interface"""

import os

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.tests.blackbox import ExternalBase


class TestBreakLock(ExternalBase):

    # General principal for break-lock: All the elements that might be locked
    # by a bzr operation on PATH, are candidates that break-lock may unlock.
    # so pathologically if we have a lightweight checkout A, of branch B, which
    # is bound to location C, the following things should be checked for locks
    # to break:
    # wt = WorkingTree(A)
    # wt.branch
    # wt.branch.repository
    # wt.branch.get_master_branch()
    # wt.branch.get_master_branch().repository
    # so for smoke tests all we need is a bound branch with a checkout of that
    # and we can then use different urls to test individual cases, for as much
    # granularity as needed.

    def setUp(self):
        super(TestBreakLock, self).setUp()
        self.build_tree(
            ['master-repo/',
             'master-repo/master-branch/',
             'repo/',
             'repo/branch/',
             'checkout/'])
        bzrlib.bzrdir.BzrDir.create('master-repo').create_repository()
        self.master_branch = bzrlib.bzrdir.create_branch_convenience(
            'master-repo/master-branch')
        bzrlib.bzrdir.BzrDir.create('repo').create_repository()
        bzrlib.bzrdir.create_branch_convenience('repo/branch')
        local_branch = bzrlib.bzrdir.create_branch_convenience('repo/branch')
        local_branch.bind(self.master_branch)
        checkoutdir = bzrlib.bzrdir.BzrDir.create('checkout')
        bzrlib.branch.BranchReferenceFormat().initialize(
            checkoutdir, local_branch)
        self.wt = bzrlib.workingtree.WorkingTree.open('checkout')

    def test_break_lock_help(self):
        out, err = self.run_bzr('break-lock', '--help')
        # shouldn't fail and should not produce error output
        self.assertEqual('', err)

    def test_break_lock_everything_locked(self):
        ### if everything is locked, we should be able to unlock the lot.
        # sketch of test:
        # setup a ui factory with precanned answers to the 'should I break lock
        # tests' 
        ### bzrlib.ui.ui_factory = ...
        # lock the lot:
        self.wt.lock_write()
        self.master_branch.lock_write()
        # run the break-lock
        self.run_bzr('break-lock', 'checkout')
        # restore (in a finally) the ui
        bzrlib.ui.ui_factory = originalfactory

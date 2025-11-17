# Copyright (C) 2006, 2007, 2009, 2010 Canonical Ltd
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

"""Tests for lock-breaking user interface."""

from breezy import branch, config, controldir, errors, osutils, tests
from breezy.tests.script import run_script


class TestBreakLock(tests.TestCaseWithTransport):
    # General principal for break-lock: All the elements that might be locked
    # by a brz operation on PATH, are candidates that break-lock may unlock.
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
        super().setUp()
        self.build_tree(
            [
                "master-repo/",
                "master-repo/master-branch/",
                "repo/",
                "repo/branch/",
                "checkout/",
            ]
        )
        controldir.ControlDir.create("master-repo").create_repository()
        self.master_branch = controldir.ControlDir.create_branch_convenience(
            "master-repo/master-branch"
        )
        controldir.ControlDir.create("repo").create_repository()
        local_branch = controldir.ControlDir.create_branch_convenience("repo/branch")
        try:
            local_branch.bind(self.master_branch)
        except branch.BindingUnsupported:
            raise tests.TestNotApplicable(
                "default format does not support bound branches"
            )
        checkoutdir = controldir.ControlDir.create("checkout")
        checkoutdir.set_branch_reference(local_branch)
        self.wt = checkoutdir.create_workingtree()

    def test_break_lock_help(self):
        _out, err = self.run_bzr("break-lock --help")
        # shouldn't fail and should not produce error output
        self.assertEqual("", err)

    def test_break_lock_no_interaction(self):
        """With --force, the user isn't asked for confirmation."""
        self.master_branch.lock_write()
        run_script(
            self,
            """
        $ brz break-lock --force master-repo/master-branch
        Broke lock ...master-branch/.bzr/...
        """,
        )
        # lock should now be dead
        self.assertRaises(errors.LockBroken, self.master_branch.unlock)

    def test_break_lock_everything_locked(self):
        # if everything is locked, we should be able to unlock the lot.
        # however, we dont test breaking the working tree because we
        # cannot accurately do so right now: the dirstate lock is held
        # by an os lock, and we need to spawn a separate process to lock it
        # then kill -9 it.
        # sketch of test:
        # lock most of the dir:
        self.wt.branch.lock_write()
        self.master_branch.lock_write()
        # run the break-lock
        # we need 5 yes's - wt, branch, repo, bound branch, bound repo.
        self.run_bzr("break-lock checkout", stdin="y\ny\ny\ny\n")
        # a new tree instance should be lockable
        br = branch.Branch.open("checkout")
        br.lock_write()
        br.unlock()
        # and a new instance of the master branch
        mb = br.get_master_branch()
        mb.lock_write()
        mb.unlock()
        self.assertRaises(errors.LockBroken, self.wt.unlock)
        self.assertRaises(errors.LockBroken, self.master_branch.unlock)


class TestConfigBreakLock(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.config_file_name = "./my.conf"
        self.build_tree_contents([(self.config_file_name, b"[DEFAULT]\none=1\n")])
        self.config = config.LockableConfig(file_name=self.config_file_name)
        self.config.lock_write()

    def test_create_pending_lock(self):
        self.addCleanup(self.config.unlock)
        self.assertTrue(self.config._lock.is_held)

    def test_break_lock(self):
        self.run_bzr(
            "break-lock --config {}".format(osutils.dirname(self.config_file_name)),
            stdin="y\n",
        )
        self.assertRaises(errors.LockBroken, self.config.unlock)

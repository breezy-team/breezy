# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Tests for InterBranch.pull behaviour."""

from bzrlib.branch import Branch
from bzrlib.controldir import ControlDir
from bzrlib import errors
from bzrlib.memorytree import MemoryTree
from bzrlib.revision import NULL_REVISION
from bzrlib.tests.per_interbranch import TestCaseWithInterBranch


# The tests here are based on the tests in 
# bzrlib.tests.per_branch.test_pull


class TestPull(TestCaseWithInterBranch):

    def test_pull_convergence_simple(self):
        # when revisions are pulled, the left-most accessible parents must
        # become the revision-history.
        parent = self.make_from_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = self.sprout_to(parent.bzrdir, 'mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        parent.merge_from_branch(mine.branch)
        parent.commit('merge my change', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual('P2', mine.branch.last_revision())

    def test_pull_merged_indirect(self):
        # it should be possible to do a pull from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        parent = self.make_from_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = self.sprout_to(parent.bzrdir, 'mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        other = self.sprout_to(parent.bzrdir, 'other').open_workingtree()
        other.merge_from_branch(mine.branch)
        other.commit('merge my change', rev_id='O2')
        parent.merge_from_branch(other.branch)
        parent.commit('merge other', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual('P2', mine.branch.last_revision())

    def test_pull_updates_checkout_and_master(self):
        """Pulling into a checkout updates the checkout and the master branch"""
        master_tree = self.make_from_branch_and_tree('master')
        rev1 = master_tree.commit('master')
        checkout = master_tree.branch.create_checkout('checkout')
        other = self.sprout_to(master_tree.branch.bzrdir, 'other').open_workingtree()
        rev2 = other.commit('other commit')
        # now pull, which should update both checkout and master.
        checkout.branch.pull(other.branch)
        self.assertEqual(rev2, checkout.branch.last_revision())
        self.assertEqual(rev2, master_tree.branch.last_revision())

    def test_pull_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_from_branch_and_tree('master')
        checkout = master_tree.branch.create_checkout('checkout')
        other = self.sprout_to(master_tree.branch.bzrdir, 'other').open_branch()
        # move the branch out of the way on disk to cause a connection
        # error.
        master_tree.branch.bzrdir.destroy_branch()
        # try to pull, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(errors.BoundBranchConnectionFailure,
                checkout.branch.pull, other)

    def test_pull_returns_result(self):
        parent = self.make_from_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1')
        mine = self.sprout_to(parent.bzrdir, 'mine').open_workingtree()
        mine.commit('my change', rev_id='M1')
        result = parent.branch.pull(mine.branch)
        self.assertIsNot(None, result)
        self.assertIs(mine.branch, result.source_branch)
        self.assertIs(parent.branch, result.target_branch)
        self.assertIs(parent.branch, result.master_branch)
        self.assertIs(None, result.local_branch)
        self.assertEqual(1, result.old_revno)
        self.assertEqual('P1', result.old_revid)
        self.assertEqual(2, result.new_revno)
        self.assertEqual('M1', result.new_revid)
        self.assertEqual([], result.tag_conflicts)

    def test_pull_overwrite(self):
        tree_a = self.make_from_branch_and_tree('tree_a')
        tree_a.commit('message 1')
        tree_b = self.sprout_to(tree_a.bzrdir, 'tree_b').open_workingtree()
        tree_a.commit('message 2', rev_id='rev2a')
        tree_b.commit('message 2', rev_id='rev2b')
        self.assertRaises(errors.DivergedBranches, tree_a.pull, tree_b.branch)
        self.assertRaises(errors.DivergedBranches,
                          tree_a.branch.pull, tree_b.branch,
                          overwrite=False, stop_revision='rev2b')
        # It should not have updated the branch tip, but it should have fetched
        # the revision if the repository supports "invisible" revisions.
        self.assertEqual('rev2a', tree_a.branch.last_revision())
        if tree_a.branch.repository._format.supports_unreferenced_revisions:
            self.assertTrue(tree_a.branch.repository.has_revision('rev2b'))
        tree_a.branch.pull(tree_b.branch, overwrite=True,
                           stop_revision='rev2b')
        self.assertEqual('rev2b', tree_a.branch.last_revision())
        self.assertEqual(tree_b.branch.last_revision(),
                         tree_a.branch.last_revision())


class TestPullHook(TestCaseWithInterBranch):

    def setUp(self):
        self.hook_calls = []
        super(TestPullHook, self).setUp()

    def capture_post_pull_hook(self, result):
        """Capture post pull hook calls to self.hook_calls.

        The call is logged, as is some state of the two branches.
        """
        if result.local_branch:
            local_locked = result.local_branch.is_locked()
            local_base = result.local_branch.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            ('post_pull', result.source_branch, local_base,
             result.master_branch.base, result.old_revno,
             result.old_revid,
             result.new_revno, result.new_revid,
             result.source_branch.is_locked(), local_locked,
             result.master_branch.is_locked()))

    def test_post_pull_empty_history(self):
        target = self.make_to_branch('target')
        source = self.make_from_branch('source')
        Branch.hooks.install_named_hook('post_pull',
            self.capture_post_pull_hook, None)
        target.pull(source)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_pull', source, None, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, None, True)
            ],
            self.hook_calls)

    def test_post_pull_bound_branch(self):
        # pulling to a bound branch should pass in the master branch to the
        # hook, allowing the correct number of emails to be sent, while still
        # allowing hooks that want to modify the target to do so to both
        # instances.
        target = self.make_to_branch('target')
        local = self.make_from_branch('local')
        try:
            local.bind(target)
        except errors.UpgradeRequired:
            # We can't bind this format to itself- typically it is the local
            # branch that doesn't support binding.  As of May 2007
            # remotebranches can't be bound.  Let's instead make a new local
            # branch of the default type, which does allow binding.
            # See https://bugs.launchpad.net/bzr/+bug/112020
            local = ControlDir.create_branch_convenience('local2')
            local.bind(target)
        source = self.make_from_branch('source')
        Branch.hooks.install_named_hook('post_pull',
            self.capture_post_pull_hook, None)
        local.pull(source)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_pull', source, local.base, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, True, True)
            ],
            self.hook_calls)

    def test_post_pull_nonempty_history(self):
        target = self.make_to_branch_and_memory_tree('target')
        target.lock_write()
        target.add('')
        rev1 = target.commit('rev 1')
        target.unlock()
        sourcedir = target.bzrdir.clone(self.get_url('source'))
        source = MemoryTree.create_on_branch(sourcedir.open_branch())
        rev2 = source.commit('rev 2')
        Branch.hooks.install_named_hook('post_pull',
            self.capture_post_pull_hook, None)
        target.branch.pull(source.branch)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_pull', source.branch, None, target.branch.base, 1, rev1,
             2, rev2, True, None, True)
            ],
            self.hook_calls)

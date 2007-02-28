# Copyright (C) 2004, 2005 Canonical Ltd
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

"""Tests for branch.pull behaviour."""

import os

from bzrlib.branch import Branch
from bzrlib import errors
from bzrlib.memorytree import MemoryTree
from bzrlib.revision import NULL_REVISION
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch


class TestPull(TestCaseWithBranch):

    def test_pull_convergence_simple(self):
        # when revisions are pulled, the left-most accessible parents must 
        # become the revision-history.
        parent = self.make_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = parent.bzrdir.sprout('mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        parent.merge_from_branch(mine.branch)
        parent.commit('merge my change', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual(['P1', 'P2'], mine.branch.revision_history())

    def test_pull_merged_indirect(self):
        # it should be possible to do a pull from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        parent = self.make_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = parent.bzrdir.sprout('mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        other = parent.bzrdir.sprout('other').open_workingtree()
        other.merge_from_branch(mine.branch)
        other.commit('merge my change', rev_id='O2')
        parent.merge_from_branch(other.branch)
        parent.commit('merge other', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual(['P1', 'P2'], mine.branch.revision_history())

    def test_pull_updates_checkout_and_master(self):
        """Pulling into a checkout updates the checkout and the master branch"""
        master_tree = self.make_branch_and_tree('master')
        rev1 = master_tree.commit('master')
        checkout = master_tree.branch.create_checkout('checkout')

        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        rev2 = other.commit('other commit')
        # now pull, which should update both checkout and master.
        checkout.branch.pull(other.branch)
        self.assertEqual([rev1, rev2], checkout.branch.revision_history())
        self.assertEqual([rev1, rev2], master_tree.branch.revision_history())

    def test_pull_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_branch_and_tree('master')
        checkout = master_tree.branch.create_checkout('checkout')
        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        os.rename('master', 'master_gone')
        # try to pull, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(errors.BoundBranchConnectionFailure,
                checkout.branch.pull, other.branch)


class TestPullHook(TestCaseWithBranch):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithBranch.setUp(self)

    def capture_post_pull_hook(self, source, local, master, old_revno,
        old_revid, new_revno, new_revid):
        """Capture post pull hook calls to self.hook_calls.
        
        The call is logged, as is some state of the two branches.
        """
        if local:
            local_locked = local.is_locked()
            local_base = local.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            ('post_pull', source, local_base, master.base, old_revno, old_revid,
             new_revno, new_revid, source.is_locked(), local_locked,
             master.is_locked()))

    def test_post_pull_empty_history(self):
        target = self.make_branch('target')
        source = self.make_branch('source')
        Branch.hooks.install_hook('post_pull', self.capture_post_pull_hook)
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
        target = self.make_branch('target')
        local = self.make_branch('local')
        try:
            local.bind(target)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        source = self.make_branch('source')
        Branch.hooks.install_hook('post_pull', self.capture_post_pull_hook)
        local.pull(source)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_pull', source, local.base, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, True, True)
            ],
            self.hook_calls)

    def test_post_pull_nonempty_history(self):
        target = self.make_branch_and_memory_tree('target')
        target.lock_write()
        target.add('')
        rev1 = target.commit('rev 1')
        target.unlock()
        sourcedir = target.bzrdir.clone(self.get_url('source'))
        source = MemoryTree.create_on_branch(sourcedir.open_branch())
        rev2 = source.commit('rev 2')
        Branch.hooks.install_hook('post_pull', self.capture_post_pull_hook)
        target.branch.pull(source.branch)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_pull', source.branch, None, target.branch.base, 1, rev1,
             2, rev2, True, None, True)
            ],
            self.hook_calls)

    def test_pull_overwrite(self):
        tree_a = self.make_branch_and_tree('tree_a')
        tree_a.commit('message 1')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        tree_a.commit('message 2', rev_id='rev2a')
        tree_b.commit('message 2', rev_id='rev2b')
        try:
            tree_a.pull(tree_b.branch)
        except:
            pass
        tree_a.branch.pull(tree_a.branch, overwrite=True,
                           stop_revision='rev2b')
        self.assertEqual(tree_a.branch.last_revision(), 'rev2b')

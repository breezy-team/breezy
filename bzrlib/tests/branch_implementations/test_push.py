# Copyright (C) 2004, 2005, 2007 Canonical Ltd
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

"""Tests for branch.push behaviour."""

import os
 
from bzrlib import bzrdir, errors
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.memorytree import MemoryTree
from bzrlib.remote import RemoteBranch
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestSkipped
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib.transport.local import LocalURLServer


class TestPush(TestCaseWithBranch):

    def test_push_convergence_simple(self):
        # when revisions are pushed, the left-most accessible parents must 
        # become the revision-history.
        mine = self.make_branch_and_tree('mine')
        mine.commit('1st post', rev_id='P1', allow_pointless=True)
        other = mine.bzrdir.sprout('other').open_workingtree()
        other.commit('my change', rev_id='M1', allow_pointless=True)
        mine.merge_from_branch(other.branch)
        mine.commit('merge my change', rev_id='P2')
        result = mine.branch.push(other.branch)
        self.assertEqual(['P1', 'P2'], other.branch.revision_history())
        # result object contains some structured data
        self.assertEqual(result.old_revid, 'M1')
        self.assertEqual(result.new_revid, 'P2')
        # and it can be treated as an integer for compatibility
        self.assertEqual(int(result), 0)

    def test_push_merged_indirect(self):
        # it should be possible to do a push from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        mine = self.make_branch_and_tree('mine')
        mine.commit('1st post', rev_id='P1', allow_pointless=True)
        target = mine.bzrdir.sprout('target').open_workingtree()
        target.commit('my change', rev_id='M1', allow_pointless=True)
        other = mine.bzrdir.sprout('other').open_workingtree()
        other.merge_from_branch(target.branch)
        other.commit('merge my change', rev_id='O2')
        mine.merge_from_branch(other.branch)
        mine.commit('merge other', rev_id='P2')
        mine.branch.push(target.branch)
        self.assertEqual(['P1', 'P2'], target.branch.revision_history())

    def test_push_to_checkout_updates_master(self):
        """Pushing into a checkout updates the checkout and the master branch"""
        master_tree = self.make_branch_and_tree('master')
        checkout = self.make_branch_and_tree('checkout')
        try:
            checkout.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        rev1 = checkout.commit('master')

        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        rev2 = other.commit('other commit')
        # now push, which should update both checkout and master.
        other.branch.push(checkout.branch)
        self.assertEqual([rev1, rev2], checkout.branch.revision_history())
        self.assertEqual([rev1, rev2], master_tree.branch.revision_history())

    def test_push_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_branch_and_tree('master')
        checkout = self.make_branch_and_tree('checkout')
        try:
            checkout.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        os.rename('master', 'master_gone')
        # try to push, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(errors.BoundBranchConnectionFailure,
                other.branch.push, checkout.branch)

    def test_push_uses_read_lock(self):
        """Push should only need a read lock on the source side."""
        source = self.make_branch_and_tree('source')
        target = self.make_branch('target')

        self.build_tree(['source/a'])
        source.add(['a'])
        source.commit('a')

        source.branch.lock_read()
        try:
            target.lock_write()
            try:
                source.branch.push(target, stop_revision=source.last_revision())
            finally:
                target.unlock()
        finally:
            source.branch.unlock()

    def test_push_within_repository(self):
        """Push from one branch to another inside the same repository."""
        try:
            repo = self.make_repository('repo', shared=True)
        except (errors.IncompatibleFormat, errors.UninitializableFormat):
            # This Branch format cannot create shared repositories
            return
        # This is a little bit trickier because make_branch_and_tree will not
        # re-use a shared repository.
        a_bzrdir = self.make_bzrdir('repo/tree')
        try:
            a_branch = self.branch_format.initialize(a_bzrdir)
        except (errors.UninitializableFormat):
            # Cannot create these branches
            return
        try:
            tree = a_branch.bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            if self.vfs_transport_factory is LocalURLServer:
                # the branch is colocated on disk, we cannot create a checkout.
                # hopefully callers will expect this.
                local_controldir= bzrdir.BzrDir.open(self.get_vfs_only_url('repo/tree'))
                tree = local_controldir.create_workingtree()
            else:
                tree = a_branch.create_checkout('repo/tree', lightweight=True)
        self.build_tree(['repo/tree/a'])
        tree.add(['a'])
        tree.commit('a')

        to_bzrdir = self.make_bzrdir('repo/branch')
        to_branch = self.branch_format.initialize(to_bzrdir)
        tree.branch.push(to_branch)

        self.assertEqual(tree.branch.last_revision(),
                         to_branch.last_revision())


class TestPushHook(TestCaseWithBranch):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithBranch.setUp(self)

    def capture_post_push_hook(self, result):
        """Capture post push hook calls to self.hook_calls.
        
        The call is logged, as is some state of the two branches.
        """
        if result.local_branch:
            local_locked = result.local_branch.is_locked()
            local_base = result.local_branch.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            ('post_push', result.source_branch, local_base,
             result.master_branch.base,
             result.old_revno, result.old_revid,
             result.new_revno, result.new_revid,
             result.source_branch.is_locked(), local_locked,
             result.master_branch.is_locked()))

    def test_post_push_empty_history(self):
        target = self.make_branch('target')
        source = self.make_branch('source')
        Branch.hooks.install_hook('post_push', self.capture_post_push_hook)
        source.push(target)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_push', source, None, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, None, True)
            ],
            self.hook_calls)

    def test_post_push_bound_branch(self):
        # pushing to a bound branch should pass in the master branch to the
        # hook, allowing the correct number of emails to be sent, while still
        # allowing hooks that want to modify the target to do so to both 
        # instances.
        target = self.make_branch('target')
        local = self.make_branch('local')
        try:
            local.bind(target)
        except errors.UpgradeRequired:
            # We can't bind this format to itself- typically it is the local
            # branch that doesn't support binding.  As of May 2007
            # remotebranches can't be bound.  Let's instead make a new local
            # branch of the default type, which does allow binding.
            # See https://bugs.launchpad.net/bzr/+bug/112020
            local = BzrDir.create_branch_convenience('local2')
            local.bind(target)
        source = self.make_branch('source')
        Branch.hooks.install_hook('post_push', self.capture_post_push_hook)
        source.push(local)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_push', source, local.base, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, True, True)
            ],
            self.hook_calls)

    def test_post_push_nonempty_history(self):
        target = self.make_branch_and_memory_tree('target')
        target.lock_write()
        target.add('')
        rev1 = target.commit('rev 1')
        target.unlock()
        sourcedir = target.bzrdir.clone(self.get_url('source'))
        source = MemoryTree.create_on_branch(sourcedir.open_branch())
        rev2 = source.commit('rev 2')
        Branch.hooks.install_hook('post_push', self.capture_post_push_hook)
        source.branch.push(target.branch)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_push', source.branch, None, target.branch.base, 1, rev1,
             2, rev2, True, None, True)
            ],
            self.hook_calls)

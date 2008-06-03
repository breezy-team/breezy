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

"""Tests for the contract of commit on branches."""

from bzrlib.branch import Branch
from bzrlib import errors
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib.revision import NULL_REVISION
from bzrlib.transport import get_transport
from bzrlib.delta import TreeDelta


class TestCommit(TestCaseWithBranch):

    def test_commit_nicks(self):
        """Nicknames are committed to the revision"""
        get_transport(self.get_url()).mkdir('bzr.dev')
        wt = self.make_branch_and_tree('bzr.dev')
        branch = wt.branch
        branch.nick = "My happy branch"
        wt.commit('My commit respect da nick.')
        committed = branch.repository.get_revision(branch.last_revision())
        self.assertEqual(committed.properties["branch-nick"], 
                         "My happy branch")


class TestCommitHook(TestCaseWithBranch):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithBranch.setUp(self)

    def capture_post_commit_hook(self, local, master, old_revno,
        old_revid, new_revno, new_revid):
        """Capture post commit hook calls to self.hook_calls.
        
        The call is logged, as is some state of the two branches.
        """
        if local:
            local_locked = local.is_locked()
            local_base = local.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            ('post_commit', local_base, master.base, old_revno, old_revid,
             new_revno, new_revid, local_locked, master.is_locked()))

    def capture_pre_commit_hook(self, local, master, old_revno, old_revid,
                                new_revno, new_revid,
                                tree_delta, future_tree):
        self.hook_calls.append(('pre_commit', old_revno, old_revid,
                                new_revno, new_revid, tree_delta))

    def test_post_commit_to_origin(self):
        tree = self.make_branch_and_memory_tree('branch')
        Branch.hooks.install_named_hook('post_commit',
            self.capture_post_commit_hook, None)
        tree.lock_write()
        tree.add('')
        revid = tree.commit('a revision')
        # should have had one notification, from origin, and
        # have the branch locked at notification time.
        self.assertEqual([
            ('post_commit', None, tree.branch.base, 0, NULL_REVISION, 1, revid,
             None, True)
            ],
            self.hook_calls)
        tree.unlock()

    def test_post_commit_bound(self):
        master = self.make_branch('master')
        tree = self.make_branch_and_memory_tree('local')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        Branch.hooks.install_named_hook('post_commit',
            self.capture_post_commit_hook, None)
        tree.lock_write()
        tree.add('')
        revid = tree.commit('a revision')
        # with a bound branch, local is set.
        self.assertEqual([
            ('post_commit', tree.branch.base, master.base, 0, NULL_REVISION,
             1, revid, True, True)
            ],
            self.hook_calls)
        tree.unlock()

    def test_post_commit_not_to_origin(self):
        tree = self.make_branch_and_memory_tree('branch')
        tree.lock_write()
        tree.add('')
        revid = tree.commit('first revision')
        Branch.hooks.install_named_hook('post_commit',
            self.capture_post_commit_hook, None)
        revid2 = tree.commit('second revision')
        # having committed from up the branch, we should get the
        # before and after revnos and revids correctly.
        self.assertEqual([
            ('post_commit', None, tree.branch.base, 1, revid, 2, revid2,
             None, True)
            ],
            self.hook_calls)
        tree.unlock()
    
    def test_pre_commit_passes(self):
        empty_delta = TreeDelta()
        root_delta = TreeDelta()
        tree = self.make_branch_and_memory_tree('branch')
        tree.lock_write()
        tree.add('')
        root_delta.added = [('', tree.path2id(''), 'directory')]
        Branch.hooks.install_named_hook("pre_commit",
            self.capture_pre_commit_hook, None)
        revid1 = tree.commit('first revision')
        revid2 = tree.commit('second revision')
        self.assertEqual([
            ('pre_commit', 0, NULL_REVISION, 1, revid1, root_delta),
            ('pre_commit', 1, revid1, 2, revid2, empty_delta)
            ],
            self.hook_calls)
        tree.unlock()

    def test_pre_commit_fails(self):
        empty_delta = TreeDelta()
        root_delta = TreeDelta()
        tree = self.make_branch_and_memory_tree('branch')
        tree.lock_write()
        tree.add('')
        root_delta.added = [('', tree.path2id(''), 'directory')]
        class PreCommitException(Exception): pass
        def hook_func(local, master,
                      old_revno, old_revid, new_revno, new_revid,
                      tree_delta, future_tree):
            raise PreCommitException(new_revid)
        Branch.hooks.install_named_hook("pre_commit",
            self.capture_pre_commit_hook, None)
        Branch.hooks.install_named_hook("pre_commit", hook_func, None)
        revids = [None, None, None]
        # this commit will raise an exception
        # so the commit is rolled back and revno unchanged
        err = self.assertRaises(PreCommitException, tree.commit, 'message')
        # we have to record the revid to use in assertEqual later
        revids[0] = str(err)
        # unregister all pre_commit hooks
        Branch.hooks["pre_commit"] = []
        # and re-register the capture hook
        Branch.hooks.install_named_hook("pre_commit",
            self.capture_pre_commit_hook, None)
        # now these commits should go through
        for i in range(1, 3):
            revids[i] = tree.commit('message')
        self.assertEqual([
            ('pre_commit', 0, NULL_REVISION, 1, revids[0], root_delta),
            ('pre_commit', 0, NULL_REVISION, 1, revids[1], root_delta),
            ('pre_commit', 1, revids[1], 2, revids[2], empty_delta)
            ],
            self.hook_calls)
        tree.unlock()

    def test_pre_commit_delta(self):
        # This tests the TreeDelta object passed to pre_commit hook.
        # This does not try to validate data correctness in the delta.
        self.build_tree(['rootfile', 'dir/', 'dir/subfile'])
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        try:
            # setting up a playground
            tree.set_root_id('root_id')
            tree.add('rootfile', 'rootfile_id')
            tree.put_file_bytes_non_atomic('rootfile_id', 'abc')
            tree.add('dir', 'dir_id')
            tree.add('dir/subfile', 'dir_subfile_id')
            tree.mkdir('to_be_unversioned', 'to_be_unversioned_id')
            tree.put_file_bytes_non_atomic('dir_subfile_id', 'def')
            revid1 = tree.commit('first revision')
        finally:
            tree.unlock()
        
        tree.lock_write()
        try:
            # making changes
            tree.put_file_bytes_non_atomic('rootfile_id', 'jkl')
            tree.rename_one('dir/subfile', 'dir/subfile_renamed')
            tree.unversion(['to_be_unversioned_id'])
            tree.mkdir('added_dir', 'added_dir_id')
            # start to capture pre_commit delta
            Branch.hooks.install_named_hook("pre_commit",
                self.capture_pre_commit_hook, None)
            revid2 = tree.commit('second revision')
        finally:
            tree.unlock()
        
        expected_delta = TreeDelta()
        expected_delta.added = [('added_dir', 'added_dir_id', 'directory')]
        expected_delta.removed = [('to_be_unversioned',
                                   'to_be_unversioned_id', 'directory')]
        expected_delta.renamed = [('dir/subfile', 'dir/subfile_renamed',
                                   'dir_subfile_id', 'file', False, False)]
        expected_delta.modified=[('rootfile', 'rootfile_id', 'file', True,
                                  False)]
        self.assertEqual([('pre_commit', 1, revid1, 2, revid2,
                           expected_delta)], self.hook_calls)

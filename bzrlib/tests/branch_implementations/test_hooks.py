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

"""Tests that branch classes implement hook callouts correctly."""

from bzrlib.branch import Branch
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCaseWithMemoryTransport


class TestSetRevisionHistoryHook(TestCaseWithMemoryTransport):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithMemoryTransport.setUp(self)

    def capture_set_rh_hook(self, branch, rev_history):
        """Capture post set-rh hook calls to self.hook_calls.
        
        The call is logged, as is some state of the branch.
        """
        self.hook_calls.append(
            ('set_rh', branch, rev_history, branch.is_locked()))

    def test_set_rh_empty_history(self):
        branch = self.make_branch('source')
        Branch.hooks.install_named_hook('set_rh', self.capture_set_rh_hook,
                                        None)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True)])

    def test_set_rh_nonempty_history(self):
        tree = self.make_branch_and_memory_tree('source')
        tree.lock_write()
        tree.add('')
        tree.commit('another commit', rev_id='f\xc2\xb5')
        tree.commit('empty commit', rev_id='foo')
        tree.unlock()
        branch = tree.branch
        Branch.hooks.install_named_hook('set_rh', self.capture_set_rh_hook,
                                        None)
        # some branches require that their history be set to a revision in the
        # repository
        branch.set_revision_history(['f\xc2\xb5'])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, ['f\xc2\xb5'], True)])

    def test_set_rh_branch_is_locked(self):
        branch = self.make_branch('source')
        Branch.hooks.install_named_hook('set_rh', self.capture_set_rh_hook,
                                        None)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True)])

    def test_set_rh_calls_all_hooks_no_errors(self):
        branch = self.make_branch('source')
        Branch.hooks.install_named_hook('set_rh', self.capture_set_rh_hook,
                                        None)
        Branch.hooks.install_named_hook('set_rh', self.capture_set_rh_hook,
                                        None)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True),
             ('set_rh', branch, [], True),
            ])


class TestPostChangeBranchTip(TestCaseWithMemoryTransport):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithMemoryTransport.setUp(self)

    def capture_post_change_branch_tip_hook(self, params):
        """Capture post_change_branch_tip hook calls to self.hook_calls.

        The call is logged, as is some state of the branch.
        """
        self.hook_calls.append((params, params.branch.is_locked()))
        self.assertEquals(params.branch.last_revision_info(),
                          (params.new_revno, params.new_revid))

    def test_post_change_branch_tip_empty_history(self):
        branch = self.make_branch('source')
        Branch.hooks.install_named_hook(
            'post_change_branch_tip',
            self.capture_post_change_branch_tip_hook,
            None)
        branch.set_last_revision_info(0, NULL_REVISION)
        self.assertEqual(len(self.hook_calls), 1)
        self.assertEqual(self.hook_calls[0][0].branch, branch)
        self.assertEqual(self.hook_calls[0][0].old_revid, NULL_REVISION)
        self.assertEqual(self.hook_calls[0][0].old_revno, 0)
        self.assertEqual(self.hook_calls[0][0].new_revid, NULL_REVISION)
        self.assertEqual(self.hook_calls[0][0].new_revno, 0)

    def test_post_change_branch_tip_nonempty_history(self):
        tree = self.make_branch_and_memory_tree('source')
        tree.lock_write()
        tree.add('')
        tree.commit('another commit', rev_id='f\xc2\xb5')
        tree.commit('empty commit', rev_id='foo')
        tree.unlock()
        branch = tree.branch
        Branch.hooks.install_named_hook(
            'post_change_branch_tip',
            self.capture_post_change_branch_tip_hook,
            None)
        # some branches require that their history be set to a revision in the
        # repository
        branch.set_last_revision_info(1, 'f\xc2\xb5')
        self.assertEqual(len(self.hook_calls), 1)
        self.assertEqual(self.hook_calls[0][0].branch, branch)
        self.assertEqual(self.hook_calls[0][0].old_revid, 'foo')
        self.assertEqual(self.hook_calls[0][0].old_revno, 2)
        self.assertEqual(self.hook_calls[0][0].new_revid, 'f\xc2\xb5')
        self.assertEqual(self.hook_calls[0][0].new_revno, 1)

    def test_post_change_branch_tip_branch_is_locked(self):
        branch = self.make_branch('source')
        Branch.hooks.install_named_hook(
            'post_change_branch_tip',
            self.capture_post_change_branch_tip_hook,
            None)
        branch.set_last_revision_info(0, NULL_REVISION)
        self.assertEqual(len(self.hook_calls), 1)
        self.assertEqual(self.hook_calls[0][0].branch, branch)
        self.assertEqual(self.hook_calls[0][1], True)

    def test_post_change_branch_tip_calls_all_hooks_no_errors(self):
        branch = self.make_branch('source')
        Branch.hooks.install_named_hook(
            'post_change_branch_tip',
            self.capture_post_change_branch_tip_hook,
            None)
        Branch.hooks.install_named_hook(
            'post_change_branch_tip',
            self.capture_post_change_branch_tip_hook,
            None)
        branch.set_last_revision_info(0, NULL_REVISION)
        self.assertEqual(len(self.hook_calls), 2)
        self.assertEqual(self.hook_calls[0][0].branch, branch)
        self.assertEqual(self.hook_calls[1][0].branch, branch)

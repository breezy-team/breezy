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

from bzrlib.branch import Branch, ChangeBranchTipParams
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


class ChangeBranchTipTestCase(TestCaseWithMemoryTransport):
    """Base TestCase for testing pre/post_change_branch_tip hooks."""

    def install_logging_hook(self, prefix):
        """Add a hook that logs calls made to it.
        
        :returns: the list that the calls will be appended to.
        """
        hook_calls = []
        Branch.hooks.install_named_hook(
            'pre_change_branch_tip', hook_calls.append, None)
        return hook_calls

    def make_branch_with_revision_ids(self, *revision_ids):
        """Makes a branch with the given commits."""
        tree = self.make_branch_and_memory_tree('source')
        tree.lock_write()
        tree.add('')
        for revision_id in revision_ids:
            tree.commit('Message of ' + revision_id, rev_id=revision_id)
        tree.unlock()
        branch = tree.branch
        return branch


class TestPreChangeBranchTip(ChangeBranchTipTestCase):
    """Tests for pre_change_branch_tip hook.
    
    Most of these tests are very similar to the tests in
    TestPostChangeBranchTip.
    """

    def test_hook_runs_before_change(self):
        """The hook runs *before* the branch's last_revision_info has changed.
        """
        branch = self.make_branch_with_revision_ids('revid-one')
        def assertBranchAtRevision1(params):
            self.assertEquals(
                (1, 'revid-one'), params.branch.last_revision_info())
        Branch.hooks.install_named_hook(
            'pre_change_branch_tip', assertBranchAtRevision1, None)
        branch.set_last_revision_info(0, NULL_REVISION)

    def test_reject_by_hook(self):
        """If a hook raises an exception, the change does not take effect.
        
        Also, the exception will be propogated.
        """
        branch = self.make_branch_with_revision_ids(
            'one-\xc2\xb5', 'two-\xc2\xb5')
        class PearShapedError(Exception):
            pass
        def hook_that_raises(params):
            raise PearShapedError()
        Branch.hooks.install_named_hook(
            'pre_change_branch_tip', hook_that_raises, None)
        self.assertRaises(
            PearShapedError, branch.set_last_revision_info, 0, NULL_REVISION)
        # The revision info is unchanged.
        self.assertEqual((2, 'two-\xc2\xb5'), branch.last_revision_info())
        
    def test_empty_history(self):
        branch = self.make_branch('source')
        hook_calls = self.install_logging_hook('pre')
        branch.set_last_revision_info(0, NULL_REVISION)
        expected_params = ChangeBranchTipParams(
            branch, 0, 0, NULL_REVISION, NULL_REVISION)
        self.assertEqual([expected_params], hook_calls)

    def test_nonempty_history(self):
        # some branches require that their history be set to a revision in the
        # repository, so we need to make a branch with non-empty history for
        # this test.
        branch = self.make_branch_with_revision_ids(
            'one-\xc2\xb5', 'two-\xc2\xb5')
        hook_calls = self.install_logging_hook('pre')
        branch.set_last_revision_info(1, 'one-\xc2\xb5')
        expected_params = ChangeBranchTipParams(
            branch, 2, 1, 'two-\xc2\xb5', 'one-\xc2\xb5')
        self.assertEqual([expected_params], hook_calls)

    def test_branch_is_locked(self):
        branch = self.make_branch('source')
        def assertBranchIsLocked(params):
            self.assertTrue(params.branch.is_locked())
        Branch.hooks.install_named_hook(
            'pre_change_branch_tip', assertBranchIsLocked, None)
        branch.set_last_revision_info(0, NULL_REVISION)

    def test_calls_all_hooks_no_errors(self):
        """If multiple hooks are registered, all are called (if none raise
        errors).
        """
        branch = self.make_branch('source')
        hook_calls_1 = self.install_logging_hook('pre')
        hook_calls_2 = self.install_logging_hook('pre')
        self.assertIsNot(hook_calls_1, hook_calls_2)
        branch.set_last_revision_info(0, NULL_REVISION)
        # Both hooks are called.
        self.assertEqual(len(hook_calls_1), 1)
        self.assertEqual(len(hook_calls_2), 1)


class TestPostChangeBranchTip(ChangeBranchTipTestCase):
    """Tests for post_change_branch_tip hook.

    Most of these tests are very similar to the tests in
    TestPostChangeBranchTip.
    """

    def test_hook_runs_after_change(self):
        """The hook runs *after* the branch's last_revision_info has changed.
        """
        branch = self.make_branch_with_revision_ids('revid-one')
        def assertBranchAtRevision1(params):
            self.assertEquals(
                (0, NULL_REVISION), params.branch.last_revision_info())
        Branch.hooks.install_named_hook(
            'post_change_branch_tip', assertBranchAtRevision1, None)
        branch.set_last_revision_info(0, NULL_REVISION)

    def test_empty_history(self):
        branch = self.make_branch('source')
        hook_calls = self.install_logging_hook('post')
        branch.set_last_revision_info(0, NULL_REVISION)
        expected_params = ChangeBranchTipParams(
            branch, 0, 0, NULL_REVISION, NULL_REVISION)
        self.assertEqual([expected_params], hook_calls)

    def test_nonempty_history(self):
        # some branches require that their history be set to a revision in the
        # repository, so we need to make a branch with non-empty history for
        # this test.
        branch = self.make_branch_with_revision_ids(
            'one-\xc2\xb5', 'two-\xc2\xb5')
        hook_calls = self.install_logging_hook('post')
        branch.set_last_revision_info(1, 'one-\xc2\xb5')
        expected_params = ChangeBranchTipParams(
            branch, 2, 1, 'two-\xc2\xb5', 'one-\xc2\xb5')
        self.assertEqual([expected_params], hook_calls)

    def test_branch_is_locked(self):
        """The branch passed to the hook is locked."""
        branch = self.make_branch('source')
        def assertBranchIsLocked(params):
            self.assertTrue(params.branch.is_locked())
        Branch.hooks.install_named_hook(
            'post_change_branch_tip', assertBranchIsLocked, None)
        branch.set_last_revision_info(0, NULL_REVISION)

    def test_calls_all_hooks_no_errors(self):
        """If multiple hooks are registered, all are called (if none raise
        errors).
        """
        branch = self.make_branch('source')
        hook_calls_1 = self.install_logging_hook('post')
        hook_calls_2 = self.install_logging_hook('post')
        self.assertIsNot(hook_calls_1, hook_calls_2)
        branch.set_last_revision_info(0, NULL_REVISION)
        # Both hooks are called.
        self.assertEqual(len(hook_calls_1), 1)
        self.assertEqual(len(hook_calls_2), 1)

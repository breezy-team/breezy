# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Tests that branch classes implement hook callouts correctly."""

from breezy import (
    branch as _mod_branch,
    errors,
    revision,
    tests,
    )
from breezy.bzr import (
    remote,
    )
from breezy.tests import test_server


class ChangeBranchTipTestCase(tests.TestCaseWithMemoryTransport):
    """Base TestCase for testing pre/post_change_branch_tip hooks."""

    def install_logging_hook(self, prefix):
        """Add a hook that logs calls made to it.

        :returns: the list that the calls will be appended to.
        """
        hook_calls = []
        _mod_branch.Branch.hooks.install_named_hook(
            prefix + '_change_branch_tip', hook_calls.append, None)
        return hook_calls

    def make_branch_with_revision_ids(self, *revision_ids):
        """Makes a branch with the given commits."""
        tree = self.make_branch_and_memory_tree('source')
        tree.lock_write()
        tree.add('')
        for revision_id in revision_ids:
            tree.commit(u'Message of ' + revision_id.decode('utf8'),
                        rev_id=revision_id)
        tree.unlock()
        branch = tree.branch
        return branch

    def assertHookCalls(self, expected_params, branch, hook_calls=None,
                        pre=False):
        if hook_calls is None:
            hook_calls = self.hook_calls
        if isinstance(branch, remote.RemoteBranch):
            # For a remote branch, both the server and the client will raise
            # this hook, and we see both in the test environment. The remote
            # instance comes in between the clients - the client doe pre, the
            # server does pre, the server does post, the client does post.
            if pre:
                offset = 0
            else:
                offset = 1
            self.assertEqual(expected_params, hook_calls[offset])
            self.assertEqual(2, len(hook_calls))
        else:
            self.assertEqual([expected_params], hook_calls)


class TestOpen(tests.TestCaseWithMemoryTransport):

    def capture_hook(self, branch):
        self.hook_calls.append(branch)

    def install_hook(self):
        self.hook_calls = []
        _mod_branch.Branch.hooks.install_named_hook(
            'open', self.capture_hook, None)

    def test_create(self):
        self.install_hook()
        b = self.make_branch('.')
        if isinstance(b, remote.RemoteBranch):
            # RemoteBranch creation:
            if (self.transport_readonly_server
                    == test_server.ReadonlySmartTCPServer_for_testing_v2_only):
                # Older servers:
                self.assertEqual(3, len(self.hook_calls))
                # creates the branch via the VFS (for older servers)
                self.assertEqual(b._real_branch, self.hook_calls[0])
                # creates a RemoteBranch object
                self.assertEqual(b, self.hook_calls[1])
                # get_stacked_on_url RPC
                self.assertRealBranch(self.hook_calls[2])
            else:
                self.assertEqual(2, len(self.hook_calls))
                # create_branch RPC
                self.assertRealBranch(self.hook_calls[0])
                # create RemoteBranch locally
                self.assertEqual(b, self.hook_calls[1])
        else:
            self.assertEqual([b], self.hook_calls)

    def test_open(self):
        branch_url = self.make_branch('.').controldir.root_transport.base
        self.install_hook()
        b = _mod_branch.Branch.open(branch_url)
        if isinstance(b, remote.RemoteBranch):
            self.assertEqual(3, len(self.hook_calls))
            # open_branchV2 RPC
            self.assertRealBranch(self.hook_calls[0])
            # create RemoteBranch locally
            self.assertEqual(b, self.hook_calls[1])
            # get_stacked_on_url RPC
            self.assertRealBranch(self.hook_calls[2])
        else:
            self.assertEqual([b], self.hook_calls)

    def assertRealBranch(self, b):
        # Branches opened on the server don't have comparable URLs, so we just
        # assert that it is not a RemoteBranch.
        self.assertIsInstance(b, _mod_branch.Branch)
        self.assertFalse(isinstance(b, remote.RemoteBranch))


class TestPreChangeBranchTip(ChangeBranchTipTestCase):
    """Tests for pre_change_branch_tip hook.

    Most of these tests are very similar to the tests in
    TestPostChangeBranchTip.
    """

    def test_hook_runs_before_change(self):
        """The hook runs *before* the branch's last_revision_info has changed.
        """
        branch = self.make_branch_with_revision_ids(b'revid-one')

        def assertBranchAtRevision1(params):
            self.assertEqual(
                (1, b'revid-one'), params.branch.last_revision_info())
        _mod_branch.Branch.hooks.install_named_hook(
            'pre_change_branch_tip', assertBranchAtRevision1, None)
        branch.set_last_revision_info(0, revision.NULL_REVISION)

    def test_hook_failure_prevents_change(self):
        """If a hook raises an exception, the change does not take effect."""
        branch = self.make_branch_with_revision_ids(
            b'one-\xc2\xb5', b'two-\xc2\xb5')

        class PearShapedError(Exception):
            pass

        def hook_that_raises(params):
            raise PearShapedError()
        _mod_branch.Branch.hooks.install_named_hook(
            'pre_change_branch_tip', hook_that_raises, None)
        hook_failed_exc = self.assertRaises(
            PearShapedError,
            branch.set_last_revision_info, 0, revision.NULL_REVISION)
        # The revision info is unchanged.
        self.assertEqual((2, b'two-\xc2\xb5'), branch.last_revision_info())

    def test_empty_history(self):
        branch = self.make_branch('source')
        hook_calls = self.install_logging_hook('pre')
        branch.set_last_revision_info(0, revision.NULL_REVISION)
        expected_params = _mod_branch.ChangeBranchTipParams(
            branch, 0, 0, revision.NULL_REVISION, revision.NULL_REVISION)
        self.assertHookCalls(expected_params, branch, hook_calls, pre=True)

    def test_nonempty_history(self):
        # some branches require that their history be set to a revision in the
        # repository, so we need to make a branch with non-empty history for
        # this test.
        branch = self.make_branch_with_revision_ids(
            b'one-\xc2\xb5', b'two-\xc2\xb5')
        hook_calls = self.install_logging_hook('pre')
        branch.set_last_revision_info(1, b'one-\xc2\xb5')
        expected_params = _mod_branch.ChangeBranchTipParams(
            branch, 2, 1, b'two-\xc2\xb5', b'one-\xc2\xb5')
        self.assertHookCalls(expected_params, branch, hook_calls, pre=True)

    def test_branch_is_locked(self):
        branch = self.make_branch('source')

        def assertBranchIsLocked(params):
            self.assertTrue(params.branch.is_locked())
        _mod_branch.Branch.hooks.install_named_hook(
            'pre_change_branch_tip', assertBranchIsLocked, None)
        branch.set_last_revision_info(0, revision.NULL_REVISION)

    def test_calls_all_hooks_no_errors(self):
        """If multiple hooks are registered, all are called (if none raise
        errors).
        """
        branch = self.make_branch('source')
        hook_calls_1 = self.install_logging_hook('pre')
        hook_calls_2 = self.install_logging_hook('pre')
        self.assertIsNot(hook_calls_1, hook_calls_2)
        branch.set_last_revision_info(0, revision.NULL_REVISION)
        # Both hooks are called.
        if isinstance(branch, remote.RemoteBranch):
            count = 2
        else:
            count = 1
        self.assertEqual(len(hook_calls_1), count)
        self.assertEqual(len(hook_calls_2), count)

    def test_explicit_reject_by_hook(self):
        """If a hook raises TipChangeRejected, the change does not take effect.

        TipChangeRejected exceptions are propagated, not wrapped in HookFailed.
        """
        branch = self.make_branch_with_revision_ids(
            b'one-\xc2\xb5', b'two-\xc2\xb5')

        def hook_that_rejects(params):
            raise errors.TipChangeRejected('rejection message')
        _mod_branch.Branch.hooks.install_named_hook(
            'pre_change_branch_tip', hook_that_rejects, None)
        self.assertRaises(
            errors.TipChangeRejected,
            branch.set_last_revision_info, 0, revision.NULL_REVISION)
        # The revision info is unchanged.
        self.assertEqual((2, b'two-\xc2\xb5'), branch.last_revision_info())


class TestPostChangeBranchTip(ChangeBranchTipTestCase):
    """Tests for post_change_branch_tip hook.

    Most of these tests are very similar to the tests in
    TestPostChangeBranchTip.
    """

    def test_hook_runs_after_change(self):
        """The hook runs *after* the branch's last_revision_info has changed.
        """
        branch = self.make_branch_with_revision_ids(b'revid-one')

        def assertBranchAtRevision1(params):
            self.assertEqual(
                (0, revision.NULL_REVISION), params.branch.last_revision_info())
        _mod_branch.Branch.hooks.install_named_hook(
            'post_change_branch_tip', assertBranchAtRevision1, None)
        branch.set_last_revision_info(0, revision.NULL_REVISION)

    def test_empty_history(self):
        branch = self.make_branch('source')
        hook_calls = self.install_logging_hook('post')
        branch.set_last_revision_info(0, revision.NULL_REVISION)
        expected_params = _mod_branch.ChangeBranchTipParams(
            branch, 0, 0, revision.NULL_REVISION, revision.NULL_REVISION)
        self.assertHookCalls(expected_params, branch, hook_calls)

    def test_nonempty_history(self):
        # some branches require that their history be set to a revision in the
        # repository, so we need to make a branch with non-empty history for
        # this test.
        branch = self.make_branch_with_revision_ids(
            b'one-\xc2\xb5', b'two-\xc2\xb5')
        hook_calls = self.install_logging_hook('post')
        branch.set_last_revision_info(1, b'one-\xc2\xb5')
        expected_params = _mod_branch.ChangeBranchTipParams(
            branch, 2, 1, b'two-\xc2\xb5', b'one-\xc2\xb5')
        self.assertHookCalls(expected_params, branch, hook_calls)

    def test_branch_is_locked(self):
        """The branch passed to the hook is locked."""
        branch = self.make_branch('source')

        def assertBranchIsLocked(params):
            self.assertTrue(params.branch.is_locked())
        _mod_branch.Branch.hooks.install_named_hook(
            'post_change_branch_tip', assertBranchIsLocked, None)
        branch.set_last_revision_info(0, revision.NULL_REVISION)

    def test_calls_all_hooks_no_errors(self):
        """If multiple hooks are registered, all are called (if none raise
        errors).
        """
        branch = self.make_branch('source')
        hook_calls_1 = self.install_logging_hook('post')
        hook_calls_2 = self.install_logging_hook('post')
        self.assertIsNot(hook_calls_1, hook_calls_2)
        branch.set_last_revision_info(0, revision.NULL_REVISION)
        # Both hooks are called.
        if isinstance(branch, remote.RemoteBranch):
            count = 2
        else:
            count = 1
        self.assertEqual(len(hook_calls_1), count)
        self.assertEqual(len(hook_calls_2), count)


class TestAllMethodsThatChangeTipWillRunHooks(ChangeBranchTipTestCase):
    """Every method of Branch that changes a branch tip will invoke the
    pre/post_change_branch_tip hooks.
    """

    def setUp(self):
        super(TestAllMethodsThatChangeTipWillRunHooks, self).setUp()
        self.installPreAndPostHooks()

    def installPreAndPostHooks(self):
        self.pre_hook_calls = self.install_logging_hook('pre')
        self.post_hook_calls = self.install_logging_hook('post')

    def resetHookCalls(self):
        del self.pre_hook_calls[:], self.post_hook_calls[:]

    def assertPreAndPostHooksWereInvoked(self, branch, smart_enabled):
        """assert that both pre and post hooks were called

        :param smart_enabled: The method invoked is one that should be
            smart server ready.
        """
        # Check for the number of invocations expected. One invocation is
        # local, one is remote (if the branch is remote).
        if smart_enabled and isinstance(branch, remote.RemoteBranch):
            length = 2
        else:
            length = 1
        self.assertEqual(length, len(self.pre_hook_calls))
        self.assertEqual(length, len(self.post_hook_calls))

    def test_set_last_revision_info(self):
        branch = self.make_branch('')
        branch.set_last_revision_info(0, revision.NULL_REVISION)
        self.assertPreAndPostHooksWereInvoked(branch, True)

    def test_generate_revision_history(self):
        branch = self.make_branch('')
        branch.generate_revision_history(revision.NULL_REVISION)
        # NB: for HPSS protocols < v3, the server does not invoke branch tip
        # change events on generate_revision_history, as the change is done
        # directly by the client over the VFS.
        self.assertPreAndPostHooksWereInvoked(branch, True)

    def test_pull(self):
        source_branch = self.make_branch_with_revision_ids(b'rev-1', b'rev-2')
        self.resetHookCalls()
        destination_branch = self.make_branch('destination')
        destination_branch.pull(source_branch)
        self.assertPreAndPostHooksWereInvoked(destination_branch, False)

    def test_push(self):
        source_branch = self.make_branch_with_revision_ids(b'rev-1', b'rev-2')
        self.resetHookCalls()
        destination_branch = self.make_branch('destination')
        source_branch.push(destination_branch)
        self.assertPreAndPostHooksWereInvoked(destination_branch, True)

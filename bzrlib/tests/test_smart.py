# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for the smart wire/domain protocol.

This module contains tests for the domain-level smart requests and responses,
such as the 'Branch.lock_write' request. Many of these use specific disk
formats to exercise calls that only make sense for formats with specific
properties.

Tests for low-level protocol encoding are found in test_smart_transport.
"""

import bz2
from cStringIO import StringIO
import tarfile

from bzrlib import (
    bzrdir,
    errors,
    pack,
    smart,
    tests,
    urlutils,
    )
from bzrlib.branch import Branch, BranchReferenceFormat
import bzrlib.smart.branch
import bzrlib.smart.bzrdir
import bzrlib.smart.repository
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SmartServerResponse,
    SuccessfulSmartServerResponse,
    )
from bzrlib.tests import (
    iter_suite_tests,
    split_suite_by_re,
    TestScenarioApplier,
    )
from bzrlib.transport import chroot, get_transport
from bzrlib.util import bencode


def load_tests(standard_tests, module, loader):
    """Multiply tests version and protocol consistency."""
    # FindRepository tests.
    bzrdir_mod = bzrlib.smart.bzrdir
    applier = TestScenarioApplier()
    applier.scenarios = [
        ("find_repository", {
            "_request_class":bzrdir_mod.SmartServerRequestFindRepositoryV1}),
        ("find_repositoryV2", {
            "_request_class":bzrdir_mod.SmartServerRequestFindRepositoryV2}),
        ]
    to_adapt, result = split_suite_by_re(standard_tests,
        "TestSmartServerRequestFindRepository")
    v2_only, v1_and_2 = split_suite_by_re(to_adapt,
        "_v2")
    for test in iter_suite_tests(v1_and_2):
        result.addTests(applier.adapt(test))
    del applier.scenarios[0]
    for test in iter_suite_tests(v2_only):
        result.addTests(applier.adapt(test))
    return result


class TestCaseWithChrootedTransport(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self._chroot_server = None

    def get_transport(self, relpath=None):
        if self._chroot_server is None:
            backing_transport = tests.TestCaseWithTransport.get_transport(self)
            self._chroot_server = chroot.ChrootServer(backing_transport)
            self._chroot_server.setUp()
            self.addCleanup(self._chroot_server.tearDown)
        t = get_transport(self._chroot_server.get_url())
        if relpath is not None:
            t = t.clone(relpath)
        return t


class TestCaseWithSmartMedium(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithSmartMedium, self).setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.transport_server = self.make_transport_server

    def make_transport_server(self):
        return smart.server.SmartTCPServer_for_testing('-' + self.id())

    def get_smart_medium(self):
        """Get a smart medium to use in tests."""
        return self.get_transport().get_smart_medium()


class TestSmartServerResponse(tests.TestCase):

    def test__eq__(self):
        self.assertEqual(SmartServerResponse(('ok', )),
            SmartServerResponse(('ok', )))
        self.assertEqual(SmartServerResponse(('ok', ), 'body'),
            SmartServerResponse(('ok', ), 'body'))
        self.assertNotEqual(SmartServerResponse(('ok', )),
            SmartServerResponse(('notok', )))
        self.assertNotEqual(SmartServerResponse(('ok', ), 'body'),
            SmartServerResponse(('ok', )))
        self.assertNotEqual(None,
            SmartServerResponse(('ok', )))

    def test__str__(self):
        """SmartServerResponses can be stringified."""
        self.assertEqual(
            "<SmartServerResponse status=OK args=('args',) body='body'>",
            str(SuccessfulSmartServerResponse(('args',), 'body')))
        self.assertEqual(
            "<SmartServerResponse status=ERR args=('args',) body='body'>",
            str(FailedSmartServerResponse(('args',), 'body')))


class TestSmartServerRequest(tests.TestCaseWithMemoryTransport):

    def test_translate_client_path(self):
        transport = self.get_transport()
        request = SmartServerRequest(transport, 'foo/')
        self.assertEqual('./', request.translate_client_path('foo/'))
        self.assertRaises(
            errors.InvalidURLJoin, request.translate_client_path, 'foo/..')
        self.assertRaises(
            errors.PathNotChild, request.translate_client_path, '/')
        self.assertRaises(
            errors.PathNotChild, request.translate_client_path, 'bar/')
        self.assertEqual('./baz', request.translate_client_path('foo/baz'))

    def test_transport_from_client_path(self):
        transport = self.get_transport()
        request = SmartServerRequest(transport, 'foo/')
        self.assertEqual(
            transport.base,
            request.transport_from_client_path('foo/').base)


class TestSmartServerRequestFindRepository(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.find_repository."""

    def test_no_repository(self):
        """When there is no repository to be found, ('norepository', ) is returned."""
        backing = self.get_transport()
        request = self._request_class(backing)
        self.make_bzrdir('.')
        self.assertEqual(SmartServerResponse(('norepository', )),
            request.execute(''))

    def test_nonshared_repository(self):
        # nonshared repositorys only allow 'find' to return a handle when the 
        # path the repository is being searched on is the same as that that 
        # the repository is at.
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result()
        self.assertEqual(result, request.execute(''))
        self.make_bzrdir('subdir')
        self.assertEqual(SmartServerResponse(('norepository', )),
            request.execute('subdir'))

    def _make_repository_and_result(self, shared=False, format=None):
        """Convenience function to setup a repository.

        :result: The SmartServerResponse to expect when opening it.
        """
        repo = self.make_repository('.', shared=shared, format=format)
        if repo.supports_rich_root():
            rich_root = 'yes'
        else:
            rich_root = 'no'
        if repo._format.supports_tree_reference:
            subtrees = 'yes'
        else:
            subtrees = 'no'
        if (smart.bzrdir.SmartServerRequestFindRepositoryV2 ==
            self._request_class):
            # All tests so far are on formats, and for non-external
            # repositories.
            return SuccessfulSmartServerResponse(
                ('ok', '', rich_root, subtrees, 'no'))
        else:
            return SuccessfulSmartServerResponse(('ok', '', rich_root, subtrees))

    def test_shared_repository(self):
        """When there is a shared repository, we get 'ok', 'relpath-to-repo'."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(shared=True)
        self.assertEqual(result, request.execute(''))
        self.make_bzrdir('subdir')
        result2 = SmartServerResponse(result.args[0:1] + ('..', ) + result.args[2:])
        self.assertEqual(result2,
            request.execute('subdir'))
        self.make_bzrdir('subdir/deeper')
        result3 = SmartServerResponse(result.args[0:1] + ('../..', ) + result.args[2:])
        self.assertEqual(result3,
            request.execute('subdir/deeper'))

    def test_rich_root_and_subtree_encoding(self):
        """Test for the format attributes for rich root and subtree support."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(format='dirstate-with-subtree')
        # check the test will be valid
        self.assertEqual('yes', result.args[2])
        self.assertEqual('yes', result.args[3])
        self.assertEqual(result, request.execute(''))

    def test_supports_external_lookups_no_v2(self):
        """Test for the supports_external_lookups attribute."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(format='dirstate-with-subtree')
        # check the test will be valid
        self.assertEqual('no', result.args[4])
        self.assertEqual(result, request.execute(''))


class TestSmartServerRequestInitializeBzrDir(tests.TestCaseWithMemoryTransport):

    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.assertEqual(SmartServerResponse(('ok', )),
            request.execute(''))
        made_dir = bzrdir.BzrDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current 
        # default formart.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.assertRaises(errors.NoSuchFile,
            request.execute, 'subdir')

    def test_initialized_dir(self):
        """Initializing an extant bzrdir should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.FileExists,
            request.execute, 'subdir')


class TestSmartServerRequestOpenBranch(TestCaseWithChrootedTransport):

    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        self.make_bzrdir('.')
        self.assertEqual(SmartServerResponse(('nobranch', )),
            request.execute(''))

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', '')),
            request.execute(''))

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        reference_url = BranchReferenceFormat().get_reference(checkout.bzrdir)
        self.assertFileEqual(reference_url, 'reference/.bzr/branch/location')
        self.assertEqual(SmartServerResponse(('ok', reference_url)),
            request.execute('reference'))


class TestSmartServerRequestRevisionHistory(tests.TestCaseWithMemoryTransport):

    def test_empty(self):
        """For an empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', ), ''),
            request.execute(''))

    def test_not_empty(self):
        """For a non-empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()
        self.assertEqual(
            SmartServerResponse(('ok', ), ('\x00'.join([r1, r2]))),
            request.execute(''))


class TestSmartServerBranchRequest(tests.TestCaseWithMemoryTransport):

    def test_no_branch(self):
        """When there is a bzrdir and no branch, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequest(backing)
        self.make_bzrdir('.')
        self.assertRaises(errors.NotBranchError,
            request.execute, '')

    def test_branch_reference(self):
        """When there is a branch reference, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequest(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        self.assertRaises(errors.NotBranchError,
            request.execute, 'checkout')


class TestSmartServerBranchRequestLastRevisionInfo(tests.TestCaseWithMemoryTransport):

    def test_empty(self):
        """For an empty branch, the result is ('ok', '0', 'null:')."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLastRevisionInfo(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', '0', 'null:')),
            request.execute(''))

    def test_not_empty(self):
        """For a non-empty branch, the result is ('ok', 'revno', 'revid')."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLastRevisionInfo(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=rev_id_utf8)
        tree.unlock()
        self.assertEqual(
            SmartServerResponse(('ok', '2', rev_id_utf8)),
            request.execute(''))


class TestSmartServerBranchRequestGetConfigFile(tests.TestCaseWithMemoryTransport):

    def test_default(self):
        """With no file, we get empty content."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        # there should be no file by default
        content = ''
        self.assertEqual(SmartServerResponse(('ok', ), content),
            request.execute(''))

    def test_with_content(self):
        # SmartServerBranchGetConfigFile should return the content from
        # branch.control_files.get('branch.conf') for now - in the future it may
        # perform more complex processing. 
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        branch._transport.put_bytes('branch.conf', 'foo bar baz')
        self.assertEqual(SmartServerResponse(('ok', ), 'foo bar baz'),
            request.execute(''))


class SetLastRevisionTestBase(tests.TestCaseWithMemoryTransport):
    """Base test case for verbs that implement set_last_revision."""

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)
        backing_transport = self.get_transport()
        self.request = self.request_class(backing_transport)
        self.tree = self.make_branch_and_memory_tree('.')

    def lock_branch(self):
        b = self.tree.branch
        branch_token = b.lock_write()
        repo_token = b.repository.lock_write()
        b.repository.unlock()
        return branch_token, repo_token

    def unlock_branch(self):
        self.tree.branch.unlock()
        
    def set_last_revision(self, revision_id, revno):
        branch_token, repo_token = self.lock_branch()
        response = self._set_last_revision(
            revision_id, revno, branch_token, repo_token)
        self.unlock_branch()
        return response

    def assertRequestSucceeds(self, revision_id, revno):
        response = self.set_last_revision(revision_id, revno)
        self.assertEqual(SuccessfulSmartServerResponse(('ok',)), response)

        
class TestSetLastRevisionVerbMixin(object):
    """Mixin test case for verbs that implement set_last_revision."""

    def test_set_null_to_null(self):
        """An empty branch can have its last revision set to 'null:'."""
        self.assertRequestSucceeds('null:', 0)

    def test_NoSuchRevision(self):
        """If the revision_id is not present, the verb returns NoSuchRevision.
        """
        revision_id = 'non-existent revision'
        self.assertEqual(
            FailedSmartServerResponse(('NoSuchRevision', revision_id)),
            self.set_last_revision(revision_id, 1))

    def make_tree_with_two_commits(self):
        self.tree.lock_write()
        self.tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = self.tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = self.tree.commit('2nd commit', rev_id='rev-2')
        self.tree.unlock()

    def test_branch_last_revision_info_is_updated(self):
        """A branch's tip can be set to a revision that is present in its
        repository.
        """
        # Make a branch with an empty revision history, but two revisions in
        # its repository.
        self.make_tree_with_two_commits()
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        self.tree.branch.set_revision_history([])
        self.assertEqual(
            (0, 'null:'), self.tree.branch.last_revision_info())
        # We can update the branch to a revision that is present in the
        # repository.
        self.assertRequestSucceeds(rev_id_utf8, 1)
        self.assertEqual(
            (1, rev_id_utf8), self.tree.branch.last_revision_info())

    def test_branch_last_revision_info_rewind(self):
        """A branch's tip can be set to a revision that is an ancestor of the
        current tip.
        """
        self.make_tree_with_two_commits()
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        self.assertEqual(
            (2, 'rev-2'), self.tree.branch.last_revision_info())
        self.assertRequestSucceeds(rev_id_utf8, 1)
        self.assertEqual(
            (1, rev_id_utf8), self.tree.branch.last_revision_info())

    def test_TipChangeRejected(self):
        """If a pre_change_branch_tip hook raises TipChangeRejected, the verb
        returns TipChangeRejected.
        """
        rejection_message = u'rejection message\N{INTERROBANG}'
        def hook_that_rejects(params):
            raise errors.TipChangeRejected(rejection_message)
        Branch.hooks.install_named_hook(
            'pre_change_branch_tip', hook_that_rejects, None)
        self.assertEqual(
            FailedSmartServerResponse(
                ('TipChangeRejected', rejection_message.encode('utf-8'))),
            self.set_last_revision('null:', 0))


class TestSmartServerBranchRequestSetLastRevision(
        SetLastRevisionTestBase, TestSetLastRevisionVerbMixin):
    """Tests for Branch.set_last_revision verb."""

    request_class = smart.branch.SmartServerBranchRequestSetLastRevision

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(
            '', branch_token, repo_token, revision_id)


class TestSmartServerBranchRequestSetLastRevisionInfo(
        SetLastRevisionTestBase, TestSetLastRevisionVerbMixin):
    """Tests for Branch.set_last_revision_info verb."""

    request_class = smart.branch.SmartServerBranchRequestSetLastRevisionInfo

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(
            '', branch_token, repo_token, revno, revision_id)

    def test_NoSuchRevision(self):
        """Branch.set_last_revision_info does not have to return
        NoSuchRevision if the revision_id is absent.
        """
        raise tests.TestNotApplicable()


class TestSmartServerBranchRequestSetLastRevisionEx(
        SetLastRevisionTestBase, TestSetLastRevisionVerbMixin):
    """Tests for Branch.set_last_revision_ex verb."""

    request_class = smart.branch.SmartServerBranchRequestSetLastRevisionEx

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(
            '', branch_token, repo_token, revision_id, 0, 0)

    def assertRequestSucceeds(self, revision_id, revno):
        response = self.set_last_revision(revision_id, revno)
        self.assertEqual(
            SuccessfulSmartServerResponse(('ok', revno, revision_id)),
            response)
        
    def test_branch_last_revision_info_rewind(self):
        """A branch's tip can be set to a revision that is an ancestor of the
        current tip, but only if allow_overwrite_descendant is passed.
        """
        self.make_tree_with_two_commits()
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        self.assertEqual(
            (2, 'rev-2'), self.tree.branch.last_revision_info())
        # If allow_overwrite_descendant flag is 0, then trying to set the tip
        # to an older revision ID has no effect.
        branch_token, repo_token = self.lock_branch()
        response = self.request.execute(
            '', branch_token, repo_token, rev_id_utf8, 0, 0)
        self.assertEqual(
            SuccessfulSmartServerResponse(('ok', 2, 'rev-2')),
            response)
        self.assertEqual(
            (2, 'rev-2'), self.tree.branch.last_revision_info())

        # If allow_overwrite_descendant flag is 1, then setting the tip to an
        # ancestor works.
        response = self.request.execute(
            '', branch_token, repo_token, rev_id_utf8, 0, 1)
        self.assertEqual(
            SuccessfulSmartServerResponse(('ok', 1, rev_id_utf8)),
            response)
        self.unlock_branch()
        self.assertEqual(
            (1, rev_id_utf8), self.tree.branch.last_revision_info())

    def make_branch_with_divergent_history(self):
        """Make a branch with divergent history in its repo.

        The branch's tip will be 'child-2', and the repo will also contain
        'child-1', which diverges from a common base revision.
        """
        self.tree.lock_write()
        self.tree.add('')
        r1 = self.tree.commit('1st commit')
        revno_1, revid_1 = self.tree.branch.last_revision_info()
        r2 = self.tree.commit('2nd commit', rev_id='child-1')
        # Undo the second commit
        self.tree.branch.set_last_revision_info(revno_1, revid_1)
        self.tree.set_parent_ids([revid_1])
        # Make a new second commit, child-2.  child-2 has diverged from
        # child-1.
        new_r2 = self.tree.commit('2nd commit', rev_id='child-2')
        self.tree.unlock()
        
    def test_not_allow_diverged(self):
        """If allow_diverged is not passed, then setting a divergent history
        returns a Diverged error.
        """
        self.make_branch_with_divergent_history()
        self.assertEqual(
            FailedSmartServerResponse(('Diverged',)),
            self.set_last_revision('child-1', 2))
        # The branch tip was not changed.
        self.assertEqual('child-2', self.tree.branch.last_revision())

    def test_allow_diverged(self):
        """If allow_diverged is passed, then setting a divergent history
        succeeds.
        """
        self.make_branch_with_divergent_history()
        branch_token, repo_token = self.lock_branch()
        response = self.request.execute(
            '', branch_token, repo_token, 'child-1', 1, 0)
        self.assertEqual(
            SuccessfulSmartServerResponse(('ok', 2, 'child-1')),
            response)
        self.unlock_branch()
        # The branch tip was changed.
        self.assertEqual('child-1', self.tree.branch.last_revision())


class TestSmartServerBranchRequestLockWrite(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_lock_write_on_unlocked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        repository = branch.repository
        response = request.execute('')
        branch_nonce = branch.control_files._lock.peek().get('nonce')
        repository_nonce = repository.control_files._lock.peek().get('nonce')
        self.assertEqual(
            SmartServerResponse(('ok', branch_nonce, repository_nonce)),
            response)
        # The branch (and associated repository) is now locked.  Verify that
        # with a new branch object.
        new_branch = repository.bzrdir.open_branch()
        self.assertRaises(errors.LockContention, new_branch.lock_write)

    def test_lock_write_on_locked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.')
        branch.lock_write()
        branch.leave_lock_in_place()
        branch.unlock()
        response = request.execute('')
        self.assertEqual(
            SmartServerResponse(('LockContention',)), response)

    def test_lock_write_with_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch_token = branch.lock_write()
        repo_token = branch.repository.lock_write()
        branch.repository.unlock()
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute('',
                                   branch_token, repo_token)
        self.assertEqual(
            SmartServerResponse(('ok', branch_token, repo_token)), response)

    def test_lock_write_with_mismatched_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch_token = branch.lock_write()
        repo_token = branch.repository.lock_write()
        branch.repository.unlock()
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute('',
                                   branch_token+'xxx', repo_token)
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch.repository.lock_write()
        branch.repository.leave_lock_in_place()
        branch.repository.unlock()
        response = request.execute('')
        self.assertEqual(
            SmartServerResponse(('LockContention',)), response)

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.')
        root = self.get_transport().clone('/')
        path = urlutils.relative_url(root.base, self.get_transport().base)
        response = request.execute(path)
        error_name, lock_str, why_str = response.args
        self.assertFalse(response.is_successful())
        self.assertEqual('LockFailed', error_name)


class TestSmartServerBranchRequestUnlock(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_unlock_on_locked_branch_and_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        # Lock the branch
        branch_token = branch.lock_write()
        repo_token = branch.repository.lock_write()
        branch.repository.unlock()
        # Unlock the branch (and repo) object, leaving the physical locks
        # in place.
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute('',
                                   branch_token, repo_token)
        self.assertEqual(
            SmartServerResponse(('ok',)), response)
        # The branch is now unlocked.  Verify that with a new branch
        # object.
        new_branch = branch.bzrdir.open_branch()
        new_branch.lock_write()
        new_branch.unlock()

    def test_unlock_on_unlocked_branch_unlocked_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        response = request.execute(
            '', 'branch token', 'repo token')
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)

    def test_unlock_on_unlocked_branch_locked_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        # Lock the repository.
        repo_token = branch.repository.lock_write()
        branch.repository.leave_lock_in_place()
        branch.repository.unlock()
        # Issue branch lock_write request on the unlocked branch (with locked
        # repo).
        response = request.execute(
            '', 'branch token', repo_token)
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)


class TestSmartServerRepositoryRequest(tests.TestCaseWithMemoryTransport):

    def test_no_repository(self):
        """Raise NoRepositoryPresent when there is a bzrdir and no repo."""
        # we test this using a shared repository above the named path,
        # thus checking the right search logic is used - that is, that
        # its the exact path being looked at and the server is not
        # searching.
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryRequest(backing)
        self.make_repository('.', shared=True)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.NoRepositoryPresent,
            request.execute, 'subdir')


class TestSmartServerRepositoryGetParentMap(tests.TestCaseWithMemoryTransport):

    def test_trivial_bzipped(self):
        # This tests that the wire encoding is actually bzipped
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetParentMap(backing)
        tree = self.make_branch_and_memory_tree('.')

        self.assertEqual(None,
            request.execute('', 'missing-id'))
        # Note that it returns a body (of '' bzipped).
        self.assertEqual(
            SuccessfulSmartServerResponse(('ok', ), bz2.compress('')),
            request.do_body('\n\n0\n'))


class TestSmartServerRepositoryGetRevisionGraph(tests.TestCaseWithMemoryTransport):

    def test_none_argument(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()

        # the lines of revision_id->revision_parent_list has no guaranteed
        # order coming out of a dict, so sort both our test and response
        lines = sorted([' '.join([r2, r1]), r1])
        response = request.execute('', '')
        response.body = '\n'.join(sorted(response.body.split('\n')))

        self.assertEqual(
            SmartServerResponse(('ok', ), '\n'.join(lines)), response)

    def test_specific_revision_argument(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc9'.encode('utf-8')
        r1 = tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()

        self.assertEqual(SmartServerResponse(('ok', ), rev_id_utf8),
            request.execute('', rev_id_utf8))
    
    def test_no_such_revision(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        tree.unlock()

        # Note that it still returns body (of zero bytes).
        self.assertEqual(
            SmartServerResponse(('nosuchrevision', 'missingrevision', ), ''),
            request.execute('', 'missingrevision'))


class TestSmartServerRequestHasRevision(tests.TestCaseWithMemoryTransport):

    def test_missing_revision(self):
        """For a missing revision, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRequestHasRevision(backing)
        self.make_repository('.')
        self.assertEqual(SmartServerResponse(('no', )),
            request.execute('', 'revid'))

    def test_present_revision(self):
        """For a present revision, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRequestHasRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        r1 = tree.commit('a commit', rev_id=rev_id_utf8)
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(rev_id_utf8))
        self.assertEqual(SmartServerResponse(('yes', )),
            request.execute('', rev_id_utf8))


class TestSmartServerRepositoryGatherStats(tests.TestCaseWithMemoryTransport):

    def test_empty_revid(self):
        """With an empty revid, we get only size an number and revisions"""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        repository = self.make_repository('.')
        stats = repository.gather_stats()
        expected_body = 'revisions: 0\n'
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute('', '', 'no'))

    def test_revid_with_committers(self):
        """For a revid we get more infos."""
        backing = self.get_transport()
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600)
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    rev_id=rev_id_utf8)
        tree.unlock()

        stats = tree.branch.repository.gather_stats()
        expected_body = ('firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n')
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute('',
                                         rev_id_utf8, 'no'))

    def test_not_empty_repository_with_committers(self):
        """For a revid and requesting committers we get the whole thing."""
        backing = self.get_transport()
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600,
                    committer='foo')
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    committer='bar', rev_id=rev_id_utf8)
        tree.unlock()
        stats = tree.branch.repository.gather_stats()

        expected_body = ('committers: 2\n'
                         'firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n')
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute('',
                                         rev_id_utf8, 'yes'))


class TestSmartServerRepositoryIsShared(tests.TestCaseWithMemoryTransport):

    def test_is_shared(self):
        """For a shared repository, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=True)
        self.assertEqual(SmartServerResponse(('yes', )),
            request.execute('', ))

    def test_is_not_shared(self):
        """For a shared repository, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=False)
        self.assertEqual(SmartServerResponse(('no', )),
            request.execute('', ))


class TestSmartServerRepositoryLockWrite(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_lock_write_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('')
        nonce = repository.control_files._lock.peek().get('nonce')
        self.assertEqual(SmartServerResponse(('ok', nonce)), response)
        # The repository is now locked.  Verify that with a new repository
        # object.
        new_repo = repository.bzrdir.open_repository()
        self.assertRaises(errors.LockContention, new_repo.lock_write)

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        repository.lock_write()
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute('')
        self.assertEqual(
            SmartServerResponse(('LockContention',)), response)

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart.repository.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('')
        self.assertFalse(response.is_successful())
        self.assertEqual('LockFailed', response.args[0])


class TestSmartServerRepositoryUnlock(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_unlock_on_locked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository('.', format='knit')
        token = repository.lock_write()
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute('', token)
        self.assertEqual(
            SmartServerResponse(('ok',)), response)
        # The repository is now unlocked.  Verify that with a new repository
        # object.
        new_repo = repository.bzrdir.open_repository()
        new_repo.lock_write()
        new_repo.unlock()

    def test_unlock_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('', 'some token')
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)


class TestSmartServerIsReadonly(tests.TestCaseWithMemoryTransport):

    def test_is_readonly_no(self):
        backing = self.get_transport()
        request = smart.request.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(
            SmartServerResponse(('no',)), response)

    def test_is_readonly_yes(self):
        backing = self.get_readonly_transport()
        request = smart.request.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(
            SmartServerResponse(('yes',)), response)


class TestHandlers(tests.TestCase):
    """Tests for the request.request_handlers object."""

    def test_all_registrations_exist(self):
        """All registered request_handlers can be found."""
        # If there's a typo in a register_lazy call, this loop will fail with
        # an AttributeError.
        for key, item in smart.request.request_handlers.iteritems():
            pass

    def test_registered_methods(self):
        """Test that known methods are registered to the correct object."""
        self.assertEqual(
            smart.request.request_handlers.get('Branch.get_config_file'),
            smart.branch.SmartServerBranchGetConfigFile)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.lock_write'),
            smart.branch.SmartServerBranchRequestLockWrite)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.last_revision_info'),
            smart.branch.SmartServerBranchRequestLastRevisionInfo)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.revision_history'),
            smart.branch.SmartServerRequestRevisionHistory)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.set_last_revision'),
            smart.branch.SmartServerBranchRequestSetLastRevision)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.set_last_revision_info'),
            smart.branch.SmartServerBranchRequestSetLastRevisionInfo)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.unlock'),
            smart.branch.SmartServerBranchRequestUnlock)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.find_repository'),
            smart.bzrdir.SmartServerRequestFindRepositoryV1)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.find_repositoryV2'),
            smart.bzrdir.SmartServerRequestFindRepositoryV2)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDirFormat.initialize'),
            smart.bzrdir.SmartServerRequestInitializeBzrDir)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.open_branch'),
            smart.bzrdir.SmartServerRequestOpenBranch)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.gather_stats'),
            smart.repository.SmartServerRepositoryGatherStats)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.get_parent_map'),
            smart.repository.SmartServerRepositoryGetParentMap)
        self.assertEqual(
            smart.request.request_handlers.get(
                'Repository.get_revision_graph'),
            smart.repository.SmartServerRepositoryGetRevisionGraph)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.has_revision'),
            smart.repository.SmartServerRequestHasRevision)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.is_shared'),
            smart.repository.SmartServerRepositoryIsShared)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.lock_write'),
            smart.repository.SmartServerRepositoryLockWrite)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.tarball'),
            smart.repository.SmartServerRepositoryTarball)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.unlock'),
            smart.repository.SmartServerRepositoryUnlock)
        self.assertEqual(
            smart.request.request_handlers.get('Transport.is_readonly'),
            smart.request.SmartServerIsReadonly)

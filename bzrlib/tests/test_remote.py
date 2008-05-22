# Copyright (C) 2006, 2007, 2008 Canonical Ltd
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

"""Tests for remote bzrdir/branch/repo/etc

These are proxy objects which act on remote objects by sending messages
through a smart client.  The proxies are to be created when attempting to open
the object given a transport that supports smartserver rpc operations. 

These tests correspond to tests.test_smart, which exercises the server side.
"""

import bz2
from cStringIO import StringIO

from bzrlib import (
    errors,
    graph,
    pack,
    remote,
    repository,
    tests,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.remote import (
    RemoteBranch,
    RemoteBzrDir,
    RemoteBzrDirFormat,
    RemoteRepository,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import server, medium
from bzrlib.smart.client import _SmartClient
from bzrlib.symbol_versioning import one_four
from bzrlib.transport import get_transport, http
from bzrlib.transport.memory import MemoryTransport
from bzrlib.transport.remote import RemoteTransport, RemoteTCPTransport


class BasicRemoteObjectTests(tests.TestCaseWithTransport):

    def setUp(self):
        self.transport_server = server.SmartTCPServer_for_testing
        super(BasicRemoteObjectTests, self).setUp()
        self.transport = self.get_transport()
        # make a branch that can be opened over the smart transport
        self.local_wt = BzrDir.create_standalone_workingtree('.')

    def tearDown(self):
        self.transport.disconnect()
        tests.TestCaseWithTransport.tearDown(self)

    def test_create_remote_bzrdir(self):
        b = remote.RemoteBzrDir(self.transport)
        self.assertIsInstance(b, BzrDir)

    def test_open_remote_branch(self):
        # open a standalone branch in the working directory
        b = remote.RemoteBzrDir(self.transport)
        branch = b.open_branch()
        self.assertIsInstance(branch, Branch)

    def test_remote_repository(self):
        b = BzrDir.open_from_transport(self.transport)
        repo = b.open_repository()
        revid = u'\xc823123123'.encode('utf8')
        self.assertFalse(repo.has_revision(revid))
        self.local_wt.commit(message='test commit', rev_id=revid)
        self.assertTrue(repo.has_revision(revid))

    def test_remote_branch_revision_history(self):
        b = BzrDir.open_from_transport(self.transport).open_branch()
        self.assertEqual([], b.revision_history())
        r1 = self.local_wt.commit('1st commit')
        r2 = self.local_wt.commit('1st commit', rev_id=u'\xc8'.encode('utf8'))
        self.assertEqual([r1, r2], b.revision_history())

    def test_find_correct_format(self):
        """Should open a RemoteBzrDir over a RemoteTransport"""
        fmt = BzrDirFormat.find_format(self.transport)
        self.assertTrue(RemoteBzrDirFormat
                        in BzrDirFormat._control_server_formats)
        self.assertIsInstance(fmt, remote.RemoteBzrDirFormat)

    def test_open_detected_smart_format(self):
        fmt = BzrDirFormat.find_format(self.transport)
        d = fmt.open(self.transport)
        self.assertIsInstance(d, BzrDir)

    def test_remote_branch_repr(self):
        b = BzrDir.open_from_transport(self.transport).open_branch()
        self.assertStartsWith(str(b), 'RemoteBranch(')


class FakeProtocol(object):
    """Lookalike SmartClientRequestProtocolOne allowing body reading tests."""

    def __init__(self, body, fake_client):
        self.body = body
        self._body_buffer = None
        self._fake_client = fake_client

    def read_body_bytes(self, count=-1):
        if self._body_buffer is None:
            self._body_buffer = StringIO(self.body)
        bytes = self._body_buffer.read(count)
        if self._body_buffer.tell() == len(self._body_buffer.getvalue()):
            self._fake_client.expecting_body = False
        return bytes

    def cancel_read_body(self):
        self._fake_client.expecting_body = False

    def read_streamed_body(self):
        return self.body


class FakeClient(_SmartClient):
    """Lookalike for _SmartClient allowing testing."""
    
    def __init__(self, fake_medium_base='fake base'):
        """Create a FakeClient.

        :param responses: A list of response-tuple, body-data pairs to be sent
            back to callers.  A special case is if the response-tuple is
            'unknown verb', then a UnknownSmartMethod will be raised for that
            call, using the second element of the tuple as the verb in the
            exception.
        """
        self.responses = []
        self._calls = []
        self.expecting_body = False
        _SmartClient.__init__(self, FakeMedium(self._calls, fake_medium_base))

    def add_success_response(self, *args):
        self.responses.append(('success', args, None))

    def add_success_response_with_body(self, body, *args):
        self.responses.append(('success', args, body))

    def add_error_response(self, *args):
        self.responses.append(('error', args))

    def add_unknown_method_response(self, verb):
        self.responses.append(('unknown', verb))

    def _get_next_response(self):
        response_tuple = self.responses.pop(0)
        if response_tuple[0] == 'unknown':
            raise errors.UnknownSmartMethod(response_tuple[1])
        elif response_tuple[0] == 'error':
            raise errors.ErrorFromSmartServer(response_tuple[1])
        return response_tuple

    def call(self, method, *args):
        self._calls.append(('call', method, args))
        return self._get_next_response()[1]

    def call_expecting_body(self, method, *args):
        self._calls.append(('call_expecting_body', method, args))
        result = self._get_next_response()
        self.expecting_body = True
        return result[1], FakeProtocol(result[2], self)

    def call_with_body_bytes_expecting_body(self, method, args, body):
        self._calls.append(('call_with_body_bytes_expecting_body', method,
            args, body))
        result = self._get_next_response()
        self.expecting_body = True
        return result[1], FakeProtocol(result[2], self)


class FakeMedium(medium.SmartClientMedium):

    def __init__(self, client_calls, base):
        self._remote_is_at_least_1_2 = True
        self._client_calls = client_calls
        self.base = base

    def disconnect(self):
        self._client_calls.append(('disconnect medium',))


class TestVfsHas(tests.TestCase):

    def test_unicode_path(self):
        client = FakeClient('/')
        client.add_success_response('yes',)
        transport = RemoteTransport('bzr://localhost/', _client=client)
        filename = u'/hell\u00d8'.encode('utf8')
        result = transport.has(filename)
        self.assertEqual(
            [('call', 'has', (filename,))],
            client._calls)
        self.assertTrue(result)


class Test_ClientMedium_remote_path_from_transport(tests.TestCase):
    """Tests for the behaviour of client_medium.remote_path_from_transport."""

    def assertRemotePath(self, expected, client_base, transport_base):
        """Assert that the result of
        SmartClientMedium.remote_path_from_transport is the expected value for
        a given client_base and transport_base.
        """
        client_medium = medium.SmartClientMedium(client_base)
        transport = get_transport(transport_base)
        result = client_medium.remote_path_from_transport(transport)
        self.assertEqual(expected, result)

    def test_remote_path_from_transport(self):
        """SmartClientMedium.remote_path_from_transport calculates a URL for
        the given transport relative to the root of the client base URL.
        """
        self.assertRemotePath('xyz/', 'bzr://host/path', 'bzr://host/xyz')
        self.assertRemotePath(
            'path/xyz/', 'bzr://host/path', 'bzr://host/path/xyz')

    def assertRemotePathHTTP(self, expected, transport_base, relpath):
        """Assert that the result of
        HttpTransportBase.remote_path_from_transport is the expected value for
        a given transport_base and relpath of that transport.  (Note that
        HttpTransportBase is a subclass of SmartClientMedium)
        """
        base_transport = get_transport(transport_base)
        client_medium = base_transport.get_smart_medium()
        cloned_transport = base_transport.clone(relpath)
        result = client_medium.remote_path_from_transport(cloned_transport)
        self.assertEqual(expected, result)
        
    def test_remote_path_from_transport_http(self):
        """Remote paths for HTTP transports are calculated differently to other
        transports.  They are just relative to the client base, not the root
        directory of the host.
        """
        for scheme in ['http:', 'https:', 'bzr+http:', 'bzr+https:']:
            self.assertRemotePathHTTP(
                '../xyz/', scheme + '//host/path', '../xyz/')
            self.assertRemotePathHTTP(
                'xyz/', scheme + '//host/path', 'xyz/')


class TestBzrDirOpenBranch(tests.TestCase):

    def test_branch_present(self):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        client = FakeClient(transport.base)
        client.add_success_response('ok', '')
        client.add_success_response('ok', '', 'no', 'no', 'no')
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_branch()
        self.assertEqual(
            [('call', 'BzrDir.open_branch', ('quack/',)),
             ('call', 'BzrDir.find_repositoryV2', ('quack/',))],
            client._calls)
        self.assertIsInstance(result, RemoteBranch)
        self.assertEqual(bzrdir, result.bzrdir)

    def test_branch_missing(self):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        client = FakeClient(transport.base)
        client.add_error_response('nobranch')
        bzrdir = RemoteBzrDir(transport, _client=client)
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch)
        self.assertEqual(
            [('call', 'BzrDir.open_branch', ('quack/',))],
            client._calls)

    def test__get_tree_branch(self):
        # _get_tree_branch is a form of open_branch, but it should only ask for
        # branch opening, not any other network requests.
        calls = []
        def open_branch():
            calls.append("Called")
            return "a-branch"
        transport = MemoryTransport()
        # no requests on the network - catches other api calls being made.
        client = FakeClient(transport.base)
        bzrdir = RemoteBzrDir(transport, _client=client)
        # patch the open_branch call to record that it was called.
        bzrdir.open_branch = open_branch
        self.assertEqual((None, "a-branch"), bzrdir._get_tree_branch())
        self.assertEqual(["Called"], calls)
        self.assertEqual([], client._calls)

    def test_url_quoting_of_path(self):
        # Relpaths on the wire should not be URL-escaped.  So "~" should be
        # transmitted as "~", not "%7E".
        transport = RemoteTCPTransport('bzr://localhost/~hello/')
        client = FakeClient(transport.base)
        client.add_success_response('ok', '')
        client.add_success_response('ok', '', 'no', 'no', 'no')
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_branch()
        self.assertEqual(
            [('call', 'BzrDir.open_branch', ('~hello/',)),
             ('call', 'BzrDir.find_repositoryV2', ('~hello/',))],
            client._calls)

    def check_open_repository(self, rich_root, subtrees, external_lookup='no'):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        if rich_root:
            rich_response = 'yes'
        else:
            rich_response = 'no'
        if subtrees:
            subtree_response = 'yes'
        else:
            subtree_response = 'no'
        client = FakeClient(transport.base)
        client.add_success_response(
            'ok', '', rich_response, subtree_response, external_lookup)
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_repository()
        self.assertEqual(
            [('call', 'BzrDir.find_repositoryV2', ('quack/',))],
            client._calls)
        self.assertIsInstance(result, RemoteRepository)
        self.assertEqual(bzrdir, result.bzrdir)
        self.assertEqual(rich_root, result._format.rich_root_data)
        self.assertEqual(subtrees, result._format.supports_tree_reference)

    def test_open_repository_sets_format_attributes(self):
        self.check_open_repository(True, True)
        self.check_open_repository(False, True)
        self.check_open_repository(True, False)
        self.check_open_repository(False, False)
        self.check_open_repository(False, False, 'yes')

    def test_old_server(self):
        """RemoteBzrDirFormat should fail to probe if the server version is too
        old.
        """
        self.assertRaises(errors.NotBranchError,
            RemoteBzrDirFormat.probe_transport, OldServerTransport())


class TestBzrDirOpenRepository(tests.TestCase):

    def test_backwards_compat_1_2(self):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        client = FakeClient(transport.base)
        client.add_unknown_method_response('RemoteRepository.find_repositoryV2')
        client.add_success_response('ok', '', 'no', 'no')
        bzrdir = RemoteBzrDir(transport, _client=client)
        repo = bzrdir.open_repository()
        self.assertEqual(
            [('call', 'BzrDir.find_repositoryV2', ('quack/',)),
             ('call', 'BzrDir.find_repository', ('quack/',))],
            client._calls)


class OldSmartClient(object):
    """A fake smart client for test_old_version that just returns a version one
    response to the 'hello' (query version) command.
    """

    def get_request(self):
        input_file = StringIO('ok\x011\n')
        output_file = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input_file, output_file)
        return medium.SmartClientStreamMediumRequest(client_medium)

    def protocol_version(self):
        return 1


class OldServerTransport(object):
    """A fake transport for test_old_server that reports it's smart server
    protocol version as version one.
    """

    def __init__(self):
        self.base = 'fake:'

    def get_smart_client(self):
        return OldSmartClient()


class TestBranchLastRevisionInfo(tests.TestCase):

    def test_empty_branch(self):
        # in an empty branch we decode the response properly
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_success_response('ok', '0', 'null:')
        transport.mkdir('quack')
        transport = transport.clone('quack')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.last_revision_info()

        self.assertEqual(
            [('call', 'Branch.last_revision_info', ('quack/',))],
            client._calls)
        self.assertEqual((0, NULL_REVISION), result)

    def test_non_empty_branch(self):
        # in a non-empty branch we also decode the response properly
        revid = u'\xc8'.encode('utf8')
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_success_response('ok', '2', revid)
        transport.mkdir('kwaak')
        transport = transport.clone('kwaak')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.last_revision_info()

        self.assertEqual(
            [('call', 'Branch.last_revision_info', ('kwaak/',))],
            client._calls)
        self.assertEqual((2, revid), result)


class TestBranchSetLastRevision(tests.TestCase):

    def test_set_empty(self):
        # set_revision_history([]) is translated to calling
        # Branch.set_last_revision(path, '') on the wire.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

        client = FakeClient(transport.base)
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_success_response('ok')
        # unlock
        client.add_success_response('ok')
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        branch.lock_write()
        client._calls = []
        result = branch.set_revision_history([])
        self.assertEqual(
            [('call', 'Branch.set_last_revision',
                ('branch/', 'branch token', 'repo token', 'null:'))],
            client._calls)
        branch.unlock()
        self.assertEqual(None, result)

    def test_set_nonempty(self):
        # set_revision_history([rev-id1, ..., rev-idN]) is translated to calling
        # Branch.set_last_revision(path, rev-idN) on the wire.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

        client = FakeClient(transport.base)
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_success_response('ok')
        # unlock
        client.add_success_response('ok')
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        result = branch.set_revision_history(['rev-id1', 'rev-id2'])
        self.assertEqual(
            [('call', 'Branch.set_last_revision',
                ('branch/', 'branch token', 'repo token', 'rev-id2'))],
            client._calls)
        branch.unlock()
        self.assertEqual(None, result)

    def test_no_such_revision(self):
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        # A response of 'NoSuchRevision' is translated into an exception.
        client = FakeClient(transport.base)
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_error_response('NoSuchRevision', 'rev-id')
        # unlock
        client.add_success_response('ok')

        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        branch._ensure_real = lambda: None
        branch.lock_write()
        client._calls = []

        self.assertRaises(
            errors.NoSuchRevision, branch.set_revision_history, ['rev-id'])
        branch.unlock()


class TestBranchSetLastRevisionInfo(tests.TestCase):

    def test_set_last_revision_info(self):
        # set_last_revision_info(num, 'rev-id') is translated to calling
        # Branch.set_last_revision_info(num, 'rev-id') on the wire.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_success_response('ok')
        # unlock
        client.add_success_response('ok')

        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []
        result = branch.set_last_revision_info(1234, 'a-revision-id')
        self.assertEqual(
            [('call', 'Branch.set_last_revision_info',
                ('branch/', 'branch token', 'repo token',
                 '1234', 'a-revision-id'))],
            client._calls)
        self.assertEqual(None, result)

    def test_no_such_revision(self):
        # A response of 'NoSuchRevision' is translated into an exception.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_error_response('NoSuchRevision', 'revid')
        # unlock
        client.add_success_response('ok')

        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        self.assertRaises(
            errors.NoSuchRevision, branch.set_last_revision_info, 123, 'revid')
        branch.unlock()

    def lock_remote_branch(self, branch):
        """Trick a RemoteBranch into thinking it is locked."""
        branch._lock_mode = 'w'
        branch._lock_count = 2
        branch._lock_token = 'branch token'
        branch._repo_lock_token = 'repo token'

    def test_backwards_compatibility(self):
        """If the server does not support the Branch.set_last_revision_info
        verb (which is new in 1.4), then the client falls back to VFS methods.
        """
        # This test is a little messy.  Unlike most tests in this file, it
        # doesn't purely test what a Remote* object sends over the wire, and
        # how it reacts to responses from the wire.  It instead relies partly
        # on asserting that the RemoteBranch will call
        # self._real_branch.set_last_revision_info(...).

        # First, set up our RemoteBranch with a FakeClient that raises
        # UnknownSmartMethod, and a StubRealBranch that logs how it is called.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        client.add_unknown_method_response('Branch.set_last_revision_info')
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        class StubRealBranch(object):
            def __init__(self):
                self.calls = []
            def set_last_revision_info(self, revno, revision_id):
                self.calls.append(
                    ('set_last_revision_info', revno, revision_id))
        real_branch = StubRealBranch()
        branch._real_branch = real_branch
        self.lock_remote_branch(branch)

        # Call set_last_revision_info, and verify it behaved as expected.
        result = branch.set_last_revision_info(1234, 'a-revision-id')
        self.assertEqual(
            [('call', 'Branch.set_last_revision_info',
                ('branch/', 'branch token', 'repo token',
                 '1234', 'a-revision-id')),],
            client._calls)
        self.assertEqual(
            [('set_last_revision_info', 1234, 'a-revision-id')],
            real_branch.calls)

    def test_unexpected_error(self):
        # A response of 'NoSuchRevision' is translated into an exception.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_error_response('UnexpectedError')
        # unlock
        client.add_success_response('ok')

        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        err = self.assertRaises(
            errors.ErrorFromSmartServer,
            branch.set_last_revision_info, 123, 'revid')
        self.assertEqual(('UnexpectedError',), err.error_tuple)
        branch.unlock()


class TestBranchControlGetBranchConf(tests.TestCaseWithMemoryTransport):
    """Getting the branch configuration should use an abstract method not vfs.
    """

    def test_get_branch_conf(self):
        raise tests.KnownFailure('branch.conf is not retrieved by get_config_file')
        # We should see that branch.get_config() does a single rpc to get the
        # remote configuration file, abstracting away where that is stored on
        # the server.  However at the moment it always falls back to using the
        # vfs, and this would need some changes in config.py.

        # in an empty branch we decode the response properly
        client = FakeClient(self.get_url())
        client.add_success_response_with_body('# config file body', 'ok')
        # we need to make a real branch because the remote_branch.control_files
        # will trigger _ensure_real.
        branch = self.make_branch('quack')
        transport = branch.bzrdir.root_transport
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        config = branch.get_config()
        self.assertEqual(
            [('call_expecting_body', 'Branch.get_config_file', ('quack/',))],
            client._calls)


class TestBranchLockWrite(tests.TestCase):

    def test_lock_write_unlockable(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_error_response('UnlockableTransport')
        transport.mkdir('quack')
        transport = transport.clone('quack')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        self.assertRaises(errors.UnlockableTransport, branch.lock_write)
        self.assertEqual(
            [('call', 'Branch.lock_write', ('quack/', '', ''))],
            client._calls)


class TestTransportIsReadonly(tests.TestCase):

    def test_true(self):
        client = FakeClient()
        client.add_success_response('yes')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(True, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)

    def test_false(self):
        client = FakeClient()
        client.add_success_response('no')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(False, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)

    def test_error_from_old_server(self):
        """bzr 0.15 and earlier servers don't recognise the is_readonly verb.
        
        Clients should treat it as a "no" response, because is_readonly is only
        advisory anyway (a transport could be read-write, but then the
        underlying filesystem could be readonly anyway).
        """
        client = FakeClient()
        client.add_unknown_method_response('Transport.is_readonly')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(False, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)


class TestRemoteRepository(tests.TestCase):
    """Base for testing RemoteRepository protocol usage.
    
    These tests contain frozen requests and responses.  We want any changes to 
    what is sent or expected to be require a thoughtful update to these tests
    because they might break compatibility with different-versioned servers.
    """

    def setup_fake_client_and_repository(self, transport_path):
        """Create the fake client and repository for testing with.
        
        There's no real server here; we just have canned responses sent
        back one by one.
        
        :param transport_path: Path below the root of the MemoryTransport
            where the repository will be created.
        """
        transport = MemoryTransport()
        transport.mkdir(transport_path)
        client = FakeClient(transport.base)
        transport = transport.clone(transport_path)
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return repo, client


class TestRepositoryGatherStats(TestRemoteRepository):

    def test_revid_none(self):
        # ('ok',), body with revisions and size
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(
            'revisions: 2\nsize: 18\n', 'ok')
        result = repo.gather_stats(None)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
             ('quack/','','no'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18}, result)

    def test_revid_no_committers(self):
        # ('ok',), body without committers
        body = ('firstrev: 123456.300 3600\n'
                'latestrev: 654231.400 0\n'
                'revisions: 2\n'
                'size: 18\n')
        transport_path = 'quick'
        revid = u'\xc8'.encode('utf8')
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(body, 'ok')
        result = repo.gather_stats(revid)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
              ('quick/', revid, 'no'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)

    def test_revid_with_committers(self):
        # ('ok',), body with committers
        body = ('committers: 128\n'
                'firstrev: 123456.300 3600\n'
                'latestrev: 654231.400 0\n'
                'revisions: 2\n'
                'size: 18\n')
        transport_path = 'buick'
        revid = u'\xc8'.encode('utf8')
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(body, 'ok')
        result = repo.gather_stats(revid, True)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
              ('buick/', revid, 'yes'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'committers': 128,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)


class TestRepositoryGetGraph(TestRemoteRepository):

    def test_get_graph(self):
        # get_graph returns a graph with the repository as the
        # parents_provider.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        graph = repo.get_graph()
        self.assertEqual(graph._real_graph._parents_provider, repo)

    def test_heads(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        graph = repo.get_graph()
        client.add_success_response('revision-a', 'revision-b')
        heads = graph.heads(['revision-a', 'revision-b', 'revision-c'])
        self.assertEqual(
            [('call', 'Repository.graph_heads',
              ('quack/', 'revision-a', 'revision-b', 'revision-c'))],
            client._calls)
        self.assertEqual(set(['revision-a', 'revision-b']), heads)




class TestRepositoryGetParentMap(TestRemoteRepository):

    def test_get_parent_map_caching(self):
        # get_parent_map returns from cache until unlock()
        # setup a reponse with two revisions
        r1 = u'\u0e33'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r1]), r1]
        encoded_body = bz2.compress('\n'.join(lines))

        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, 'ok')
        client.add_success_response_with_body(encoded_body, 'ok')
        repo.lock_read()
        graph = repo.get_graph()
        parents = graph.get_parent_map([r2])
        self.assertEqual({r2: (r1,)}, parents)
        # locking and unlocking deeper should not reset
        repo.lock_read()
        repo.unlock()
        parents = graph.get_parent_map([r1])
        self.assertEqual({r1: (NULL_REVISION,)}, parents)
        self.assertEqual(
            [('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', r2), '\n\n0')],
            client._calls)
        repo.unlock()
        # now we call again, and it should use the second response.
        repo.lock_read()
        graph = repo.get_graph()
        parents = graph.get_parent_map([r1])
        self.assertEqual({r1: (NULL_REVISION,)}, parents)
        self.assertEqual(
            [('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', r2), '\n\n0'),
             ('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', r1), '\n\n0'),
            ],
            client._calls)
        repo.unlock()

    def test_get_parent_map_reconnects_if_unknown_method(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_unknown_method_response('Repository,get_parent_map')
        client.add_success_response_with_body('', 'ok')
        self.assertTrue(client._medium._remote_is_at_least_1_2)
        rev_id = 'revision-id'
        expected_deprecations = [
            'bzrlib.remote.RemoteRepository.get_revision_graph was deprecated '
            'in version 1.4.']
        parents = self.callDeprecated(
            expected_deprecations, repo.get_parent_map, [rev_id])
        self.assertEqual(
            [('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', rev_id), '\n\n0'),
             ('disconnect medium',),
             ('call_expecting_body', 'Repository.get_revision_graph',
              ('quack/', ''))],
            client._calls)
        # The medium is now marked as being connected to an older server
        self.assertFalse(client._medium._remote_is_at_least_1_2)

    def test_get_parent_map_fallback_parentless_node(self):
        """get_parent_map falls back to get_revision_graph on old servers.  The
        results from get_revision_graph are tweaked to match the get_parent_map
        API.

        Specifically, a {key: ()} result from get_revision_graph means "no
        parents" for that key, which in get_parent_map results should be
        represented as {key: ('null:',)}.

        This is the test for https://bugs.launchpad.net/bzr/+bug/214894
        """
        rev_id = 'revision-id'
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(rev_id, 'ok')
        client._medium._remote_is_at_least_1_2 = False
        expected_deprecations = [
            'bzrlib.remote.RemoteRepository.get_revision_graph was deprecated '
            'in version 1.4.']
        parents = self.callDeprecated(
            expected_deprecations, repo.get_parent_map, [rev_id])
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('quack/', ''))],
            client._calls)
        self.assertEqual({rev_id: ('null:',)}, parents)

    def test_get_parent_map_unexpected_response(self):
        repo, client = self.setup_fake_client_and_repository('path')
        client.add_success_response('something unexpected!')
        self.assertRaises(
            errors.UnexpectedSmartServerResponse,
            repo.get_parent_map, ['a-revision-id'])


class TestRepositoryGetRevisionGraph(TestRemoteRepository):
    
    def test_null_revision(self):
        # a null revision has the predictable result {}, we should have no wire
        # traffic when calling it with this argument
        transport_path = 'empty'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('notused')
        result = self.applyDeprecated(one_four, repo.get_revision_graph,
            NULL_REVISION)
        self.assertEqual([], client._calls)
        self.assertEqual({}, result)

    def test_none_revision(self):
        # with none we want the entire graph
        r1 = u'\u0e33'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r1]), r1]
        encoded_body = '\n'.join(lines)

        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, 'ok')
        result = self.applyDeprecated(one_four, repo.get_revision_graph)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('sinhala/', ''))],
            client._calls)
        self.assertEqual({r1: (), r2: (r1, )}, result)

    def test_specific_revision(self):
        # with a specific revision we want the graph for that
        # with none we want the entire graph
        r11 = u'\u0e33'.encode('utf8')
        r12 = u'\xc9'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r11, r12]), r11, r12]
        encoded_body = '\n'.join(lines)

        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, 'ok')
        result = self.applyDeprecated(one_four, repo.get_revision_graph, r2)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('sinhala/', r2))],
            client._calls)
        self.assertEqual({r11: (), r12: (), r2: (r11, r12), }, result)

    def test_no_such_revision(self):
        revid = '123'
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('nosuchrevision', revid)
        # also check that the right revision is reported in the error
        self.assertRaises(errors.NoSuchRevision,
            self.applyDeprecated, one_four, repo.get_revision_graph, revid)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('sinhala/', revid))],
            client._calls)

    def test_unexpected_error(self):
        revid = '123'
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('AnUnexpectedError')
        e = self.assertRaises(errors.ErrorFromSmartServer,
            self.applyDeprecated, one_four, repo.get_revision_graph, revid)
        self.assertEqual(('AnUnexpectedError',), e.error_tuple)

        
class TestRepositoryIsShared(TestRemoteRepository):

    def test_is_shared(self):
        # ('yes', ) for Repository.is_shared -> 'True'.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('yes')
        result = repo.is_shared()
        self.assertEqual(
            [('call', 'Repository.is_shared', ('quack/',))],
            client._calls)
        self.assertEqual(True, result)

    def test_is_not_shared(self):
        # ('no', ) for Repository.is_shared -> 'False'.
        transport_path = 'qwack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('no')
        result = repo.is_shared()
        self.assertEqual(
            [('call', 'Repository.is_shared', ('qwack/',))],
            client._calls)
        self.assertEqual(False, result)


class TestRepositoryLockWrite(TestRemoteRepository):

    def test_lock_write(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('ok', 'a token')
        result = repo.lock_write()
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', ''))],
            client._calls)
        self.assertEqual('a token', result)

    def test_lock_write_already_locked(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('LockContention')
        self.assertRaises(errors.LockContention, repo.lock_write)
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', ''))],
            client._calls)

    def test_lock_write_unlockable(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('UnlockableTransport')
        self.assertRaises(errors.UnlockableTransport, repo.lock_write)
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', ''))],
            client._calls)


class TestRepositoryUnlock(TestRemoteRepository):

    def test_unlock(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('ok', 'a token')
        client.add_success_response('ok')
        repo.lock_write()
        repo.unlock()
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', '')),
             ('call', 'Repository.unlock', ('quack/', 'a token'))],
            client._calls)

    def test_unlock_wrong_token(self):
        # If somehow the token is wrong, unlock will raise TokenMismatch.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('ok', 'a token')
        client.add_error_response('TokenMismatch')
        repo.lock_write()
        self.assertRaises(errors.TokenMismatch, repo.unlock)


class TestRepositoryHasRevision(TestRemoteRepository):

    def test_none(self):
        # repo.has_revision(None) should not cause any traffic.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)

        # The null revision is always there, so has_revision(None) == True.
        self.assertEqual(True, repo.has_revision(NULL_REVISION))

        # The remote repo shouldn't be accessed.
        self.assertEqual([], client._calls)


class TestRepositoryTarball(TestRemoteRepository):

    # This is a canned tarball reponse we can validate against
    tarball_content = (
        'QlpoOTFBWSZTWdGkj3wAAWF/k8aQACBIB//A9+8cIX/v33AACEAYABAECEACNz'
        'JqsgJJFPTSnk1A3qh6mTQAAAANPUHkagkSTEkaA09QaNAAAGgAAAcwCYCZGAEY'
        'mJhMJghpiaYBUkKammSHqNMZQ0NABkNAeo0AGneAevnlwQoGzEzNVzaYxp/1Uk'
        'xXzA1CQX0BJMZZLcPBrluJir5SQyijWHYZ6ZUtVqqlYDdB2QoCwa9GyWwGYDMA'
        'OQYhkpLt/OKFnnlT8E0PmO8+ZNSo2WWqeCzGB5fBXZ3IvV7uNJVE7DYnWj6qwB'
        'k5DJDIrQ5OQHHIjkS9KqwG3mc3t+F1+iujb89ufyBNIKCgeZBWrl5cXxbMGoMs'
        'c9JuUkg5YsiVcaZJurc6KLi6yKOkgCUOlIlOpOoXyrTJjK8ZgbklReDdwGmFgt'
        'dkVsAIslSVCd4AtACSLbyhLHryfb14PKegrVDba+U8OL6KQtzdM5HLjAc8/p6n'
        '0lgaWU8skgO7xupPTkyuwheSckejFLK5T4ZOo0Gda9viaIhpD1Qn7JqqlKAJqC'
        'QplPKp2nqBWAfwBGaOwVrz3y1T+UZZNismXHsb2Jq18T+VaD9k4P8DqE3g70qV'
        'JLurpnDI6VS5oqDDPVbtVjMxMxMg4rzQVipn2Bv1fVNK0iq3Gl0hhnnHKm/egy'
        'nWQ7QH/F3JFOFCQ0aSPfA='
        ).decode('base64')

    def test_repository_tarball(self):
        # Test that Repository.tarball generates the right operations
        transport_path = 'repo'
        expected_calls = [('call_expecting_body', 'Repository.tarball',
                           ('repo/', 'bz2',),),
            ]
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(self.tarball_content, 'ok')
        # Now actually ask for the tarball
        tarball_file = repo._get_tarball('bz2')
        try:
            self.assertEqual(expected_calls, client._calls)
            self.assertEqual(self.tarball_content, tarball_file.read())
        finally:
            tarball_file.close()


class TestRemoteRepositoryCopyContent(tests.TestCaseWithTransport):
    """RemoteRepository.copy_content_into optimizations"""

    def test_copy_content_remote_to_local(self):
        self.transport_server = server.SmartTCPServer_for_testing
        src_repo = self.make_repository('repo1')
        src_repo = repository.Repository.open(self.get_url('repo1'))
        # At the moment the tarball-based copy_content_into can't write back
        # into a smart server.  It would be good if it could upload the
        # tarball; once that works we'd have to create repositories of
        # different formats. -- mbp 20070410
        dest_url = self.get_vfs_only_url('repo2')
        dest_bzrdir = BzrDir.create(dest_url)
        dest_repo = dest_bzrdir.create_repository()
        self.assertFalse(isinstance(dest_repo, RemoteRepository))
        self.assertTrue(isinstance(src_repo, RemoteRepository))
        src_repo.copy_content_into(dest_repo)


class TestRepositoryStreamKnitData(TestRemoteRepository):

    def make_pack_file(self, records):
        pack_file = StringIO()
        pack_writer = pack.ContainerWriter(pack_file.write)
        pack_writer.begin()
        for bytes, names in records:
            pack_writer.add_bytes_record(bytes, names)
        pack_writer.end()
        pack_file.seek(0)
        return pack_file

    def make_pack_stream(self, records):
        pack_serialiser = pack.ContainerSerialiser()
        yield pack_serialiser.begin()
        for bytes, names in records:
            yield pack_serialiser.bytes_record(bytes, names)
        yield pack_serialiser.end()

    def test_bad_pack_from_server(self):
        """A response with invalid data (e.g. it has a record with multiple
        names) triggers an exception.
        
        Not all possible errors will be caught at this stage, but obviously
        malformed data should be.
        """
        record = ('bytes', [('name1',), ('name2',)])
        pack_stream = self.make_pack_stream([record])
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(pack_stream, 'ok')
        search = graph.SearchResult(set(['revid']), set(), 1, set(['revid']))
        stream = repo.get_data_stream_for_search(search)
        self.assertRaises(errors.SmartProtocolError, list, stream)
    
    def test_backwards_compatibility(self):
        """If the server doesn't recognise this request, fallback to VFS."""
        repo, client = self.setup_fake_client_and_repository('path')
        client.add_unknown_method_response(
            'Repository.stream_revisions_chunked')
        self.mock_called = False
        repo._real_repository = MockRealRepository(self)
        search = graph.SearchResult(set(['revid']), set(), 1, set(['revid']))
        repo.get_data_stream_for_search(search)
        self.assertTrue(self.mock_called)
        self.failIf(client.expecting_body,
            "The protocol has been left in an unclean state that will cause "
            "TooManyConcurrentRequests errors.")


class MockRealRepository(object):
    """Helper class for TestRepositoryStreamKnitData.test_unknown_method."""

    def __init__(self, test):
        self.test = test

    def get_data_stream_for_search(self, search):
        self.test.assertEqual(set(['revid']), search.get_keys())
        self.test.mock_called = True



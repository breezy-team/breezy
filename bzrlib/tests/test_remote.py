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

"""Tests for remote bzrdir/branch/repo/etc

These are proxy objects which act on remote objects by sending messages
through a smart client.  The proxies are to be created when attempting to open
the object given a transport that supports smartserver rpc operations. 

These tests correspond to tests.test_smart, which exercises the server side.
"""

from cStringIO import StringIO

from bzrlib import (
    bzrdir,
    errors,
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
from bzrlib.transport.memory import MemoryTransport
from bzrlib.transport.remote import RemoteTransport


class BasicRemoteObjectTests(tests.TestCaseWithTransport):

    def setUp(self):
        self.transport_server = server.SmartTCPServer_for_testing
        super(BasicRemoteObjectTests, self).setUp()
        self.transport = self.get_transport()
        self.client = self.transport.get_smart_client()
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

    def __init__(self, body):
        self._body_buffer = StringIO(body)

    def read_body_bytes(self, count=-1):
        return self._body_buffer.read(count)


class FakeClient(_SmartClient):
    """Lookalike for _SmartClient allowing testing."""
    
    def __init__(self, responses):
        # We don't call the super init because there is no medium.
        """create a FakeClient.

        :param respones: A list of response-tuple, body-data pairs to be sent
            back to callers.
        """
        self.responses = responses
        self._calls = []

    def call(self, method, *args):
        self._calls.append(('call', method, args))
        return self.responses.pop(0)[0]

    def call_expecting_body(self, method, *args):
        self._calls.append(('call_expecting_body', method, args))
        result = self.responses.pop(0)
        return result[0], FakeProtocol(result[1])


class TestBzrDirOpenBranch(tests.TestCase):

    def test_branch_present(self):
        client = FakeClient([(('ok', ''), ), (('ok', '', 'no', 'no'), )])
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_branch()
        self.assertEqual(
            [('call', 'BzrDir.open_branch', ('///quack/',)),
             ('call', 'BzrDir.find_repository', ('///quack/',))],
            client._calls)
        self.assertIsInstance(result, RemoteBranch)
        self.assertEqual(bzrdir, result.bzrdir)

    def test_branch_missing(self):
        client = FakeClient([(('nobranch',), )])
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        bzrdir = RemoteBzrDir(transport, _client=client)
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch)
        self.assertEqual(
            [('call', 'BzrDir.open_branch', ('///quack/',))],
            client._calls)

    def check_open_repository(self, rich_root, subtrees):
        if rich_root:
            rich_response = 'yes'
        else:
            rich_response = 'no'
        if subtrees:
            subtree_response = 'yes'
        else:
            subtree_response = 'no'
        client = FakeClient([(('ok', '', rich_response, subtree_response), ),])
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_repository()
        self.assertEqual(
            [('call', 'BzrDir.find_repository', ('///quack/',))],
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

    def test_old_server(self):
        """RemoteBzrDirFormat should fail to probe if the server version is too
        old.
        """
        self.assertRaises(errors.NotBranchError,
            RemoteBzrDirFormat.probe_transport, OldServerTransport())


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
        client = FakeClient([(('ok', '0', 'null:'), )])
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.last_revision_info()

        self.assertEqual(
            [('call', 'Branch.last_revision_info', ('///quack/',))],
            client._calls)
        self.assertEqual((0, NULL_REVISION), result)

    def test_non_empty_branch(self):
        # in a non-empty branch we also decode the response properly
        revid = u'\xc8'.encode('utf8')
        client = FakeClient([(('ok', '2', revid), )])
        transport = MemoryTransport()
        transport.mkdir('kwaak')
        transport = transport.clone('kwaak')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.last_revision_info()

        self.assertEqual(
            [('call', 'Branch.last_revision_info', ('///kwaak/',))],
            client._calls)
        self.assertEqual((2, revid), result)


class TestBranchSetLastRevision(tests.TestCase):

    def test_set_empty(self):
        # set_revision_history([]) is translated to calling
        # Branch.set_last_revision(path, '') on the wire.
        client = FakeClient([
            # lock_write
            (('ok', 'branch token', 'repo token'), ),
            # set_last_revision
            (('ok',), ),
            # unlock
            (('ok',), )])
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

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
                ('///branch/', 'branch token', 'repo token', 'null:'))],
            client._calls)
        branch.unlock()
        self.assertEqual(None, result)

    def test_set_nonempty(self):
        # set_revision_history([rev-id1, ..., rev-idN]) is translated to calling
        # Branch.set_last_revision(path, rev-idN) on the wire.
        client = FakeClient([
            # lock_write
            (('ok', 'branch token', 'repo token'), ),
            # set_last_revision
            (('ok',), ),
            # unlock
            (('ok',), )])
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

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
                ('///branch/', 'branch token', 'repo token', 'rev-id2'))],
            client._calls)
        branch.unlock()
        self.assertEqual(None, result)

    def test_no_such_revision(self):
        # A response of 'NoSuchRevision' is translated into an exception.
        client = FakeClient([
            # lock_write
            (('ok', 'branch token', 'repo token'), ),
            # set_last_revision
            (('NoSuchRevision', 'rev-id'), ),
            # unlock
            (('ok',), )])
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        branch._ensure_real = lambda: None
        branch.lock_write()
        client._calls = []

        self.assertRaises(
            errors.NoSuchRevision, branch.set_revision_history, ['rev-id'])
        branch.unlock()


class TestBranchControlGetBranchConf(tests.TestCaseWithMemoryTransport):
    """Test branch.control_files api munging...

    We special case RemoteBranch.control_files.get('branch.conf') to
    call a specific API so that RemoteBranch's can intercept configuration
    file reading, allowing them to signal to the client about things like
    'email is configured for commits'.
    """

    def test_get_branch_conf(self):
        # in an empty branch we decode the response properly
        client = FakeClient([(('ok', ), 'config file body')])
        # we need to make a real branch because the remote_branch.control_files
        # will trigger _ensure_real.
        branch = self.make_branch('quack')
        transport = branch.bzrdir.root_transport
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.control_files.get('branch.conf')
        self.assertEqual(
            [('call_expecting_body', 'Branch.get_config_file', ('///quack/',))],
            client._calls)
        self.assertEqual('config file body', result.read())


class TestBranchLockWrite(tests.TestCase):

    def test_lock_write_unlockable(self):
        client = FakeClient([(('UnlockableTransport', ), '')])
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        self.assertRaises(errors.UnlockableTransport, branch.lock_write)
        self.assertEqual(
            [('call', 'Branch.lock_write', ('///quack/', '', ''))],
            client._calls)


class TestTransportIsReadonly(tests.TestCase):

    def test_true(self):
        client = FakeClient([(('yes',), '')])
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(True, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)

    def test_false(self):
        client = FakeClient([(('no',), '')])
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
        client = FakeClient([(
            ('error', "Generic bzr smart protocol error: "
                      "bad request 'Transport.is_readonly'"), '')])
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

    def setup_fake_client_and_repository(self, responses, transport_path):
        """Create the fake client and repository for testing with.
        
        There's no real server here; we just have canned responses sent
        back one by one.
        
        :param transport_path: Path below the root of the MemoryTransport
            where the repository will be created.
        """
        client = FakeClient(responses)
        transport = MemoryTransport()
        transport.mkdir(transport_path)
        transport = transport.clone(transport_path)
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return repo, client


class TestRepositoryGatherStats(TestRemoteRepository):

    def test_revid_none(self):
        # ('ok',), body with revisions and size
        responses = [(('ok', ), 'revisions: 2\nsize: 18\n')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.gather_stats(None)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
             ('///quack/','','no'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18}, result)

    def test_revid_no_committers(self):
        # ('ok',), body without committers
        responses = [(('ok', ),
                      'firstrev: 123456.300 3600\n'
                      'latestrev: 654231.400 0\n'
                      'revisions: 2\n'
                      'size: 18\n')]
        transport_path = 'quick'
        revid = u'\xc8'.encode('utf8')
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.gather_stats(revid)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
              ('///quick/', revid, 'no'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)

    def test_revid_with_committers(self):
        # ('ok',), body with committers
        responses = [(('ok', ),
                      'committers: 128\n'
                      'firstrev: 123456.300 3600\n'
                      'latestrev: 654231.400 0\n'
                      'revisions: 2\n'
                      'size: 18\n')]
        transport_path = 'buick'
        revid = u'\xc8'.encode('utf8')
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.gather_stats(revid, True)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
              ('///buick/', revid, 'yes'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'committers': 128,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)


class TestRepositoryGetRevisionGraph(TestRemoteRepository):
    
    def test_null_revision(self):
        # a null revision has the predictable result {}, we should have no wire
        # traffic when calling it with this argument
        responses = [(('notused', ), '')]
        transport_path = 'empty'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.get_revision_graph(NULL_REVISION)
        self.assertEqual([], client._calls)
        self.assertEqual({}, result)

    def test_none_revision(self):
        # with none we want the entire graph
        r1 = u'\u0e33'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r1]), r1]
        encoded_body = '\n'.join(lines)

        responses = [(('ok', ), encoded_body)]
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.get_revision_graph()
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('///sinhala/', ''))],
            client._calls)
        self.assertEqual({r1: [], r2: [r1]}, result)

    def test_specific_revision(self):
        # with a specific revision we want the graph for that
        # with none we want the entire graph
        r11 = u'\u0e33'.encode('utf8')
        r12 = u'\xc9'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r11, r12]), r11, r12]
        encoded_body = '\n'.join(lines)

        responses = [(('ok', ), encoded_body)]
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.get_revision_graph(r2)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('///sinhala/', r2))],
            client._calls)
        self.assertEqual({r11: [], r12: [], r2: [r11, r12], }, result)

    def test_no_such_revision(self):
        revid = '123'
        responses = [(('nosuchrevision', revid), '')]
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        # also check that the right revision is reported in the error
        self.assertRaises(errors.NoSuchRevision,
            repo.get_revision_graph, revid)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('///sinhala/', revid))],
            client._calls)

        
class TestRepositoryIsShared(TestRemoteRepository):

    def test_is_shared(self):
        # ('yes', ) for Repository.is_shared -> 'True'.
        responses = [(('yes', ), )]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.is_shared()
        self.assertEqual(
            [('call', 'Repository.is_shared', ('///quack/',))],
            client._calls)
        self.assertEqual(True, result)

    def test_is_not_shared(self):
        # ('no', ) for Repository.is_shared -> 'False'.
        responses = [(('no', ), )]
        transport_path = 'qwack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.is_shared()
        self.assertEqual(
            [('call', 'Repository.is_shared', ('///qwack/',))],
            client._calls)
        self.assertEqual(False, result)


class TestRepositoryLockWrite(TestRemoteRepository):

    def test_lock_write(self):
        responses = [(('ok', 'a token'), '')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.lock_write()
        self.assertEqual(
            [('call', 'Repository.lock_write', ('///quack/', ''))],
            client._calls)
        self.assertEqual('a token', result)

    def test_lock_write_already_locked(self):
        responses = [(('LockContention', ), '')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        self.assertRaises(errors.LockContention, repo.lock_write)
        self.assertEqual(
            [('call', 'Repository.lock_write', ('///quack/', ''))],
            client._calls)

    def test_lock_write_unlockable(self):
        responses = [(('UnlockableTransport', ), '')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        self.assertRaises(errors.UnlockableTransport, repo.lock_write)
        self.assertEqual(
            [('call', 'Repository.lock_write', ('///quack/', ''))],
            client._calls)


class TestRepositoryUnlock(TestRemoteRepository):

    def test_unlock(self):
        responses = [(('ok', 'a token'), ''),
                     (('ok',), '')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        repo.lock_write()
        repo.unlock()
        self.assertEqual(
            [('call', 'Repository.lock_write', ('///quack/', '')),
             ('call', 'Repository.unlock', ('///quack/', 'a token'))],
            client._calls)

    def test_unlock_wrong_token(self):
        # If somehow the token is wrong, unlock will raise TokenMismatch.
        responses = [(('ok', 'a token'), ''),
                     (('TokenMismatch',), '')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        repo.lock_write()
        self.assertRaises(errors.TokenMismatch, repo.unlock)


class TestRepositoryHasRevision(TestRemoteRepository):

    def test_none(self):
        # repo.has_revision(None) should not cause any traffic.
        transport_path = 'quack'
        responses = None
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)

        # The null revision is always there, so has_revision(None) == True.
        self.assertEqual(True, repo.has_revision(None))

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
        expected_responses = [(('ok',), self.tarball_content),
            ]
        expected_calls = [('call_expecting_body', 'Repository.tarball',
                           ('///repo/', 'bz2',),),
            ]
        remote_repo, client = self.setup_fake_client_and_repository(
            expected_responses, transport_path)
        # Now actually ask for the tarball
        tarball_file = remote_repo._get_tarball('bz2')
        try:
            self.assertEqual(expected_calls, client._calls)
            self.assertEqual(self.tarball_content, tarball_file.read())
        finally:
            tarball_file.close()

    def test_sprout_uses_tarball(self):
        # RemoteRepository.sprout should try to use the
        # tarball command rather than accessing all the files
        transport_path = 'srcrepo'
        expected_responses = [(('ok',), self.tarball_content),
            ]
        expected_calls = [('call2', 'Repository.tarball', ('///srcrepo/', 'bz2',),),
            ]
        remote_repo, client = self.setup_fake_client_and_repository(
            expected_responses, transport_path)
        # make a regular local repository to receive the results
        dest_transport = MemoryTransport()
        dest_transport.mkdir('destrepo')
        bzrdir_format = bzrdir.format_registry.make_bzrdir('default')
        dest_bzrdir = bzrdir_format.initialize_on_transport(dest_transport)
        # try to copy...
        remote_repo.sprout(dest_bzrdir)


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

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
"""

from cStringIO import StringIO

from bzrlib import bzrdir, remote, tests
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.remote import (
    RemoteBranch,
    RemoteBzrDir,
    RemoteBzrDirFormat,
    RemoteRepository,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import server
from bzrlib.smart.client import SmartClient
from bzrlib.transport import remote as remote_transport
from bzrlib.transport.memory import MemoryTransport


class BasicRemoteObjectTests(tests.TestCaseWithTransport):

    def setUp(self):
        super(BasicRemoteObjectTests, self).setUp()
        self.transport_server = server.SmartTCPServer_for_testing
        self.transport = self.get_transport()
        self.client = self.transport.get_smart_client()
        # make a branch that can be opened over the smart transport
        self.local_wt = BzrDir.create_standalone_workingtree('.')

    def test_create_remote_bzrdir(self):
        b = remote.RemoteBzrDir(self.transport)
        self.assertIsInstance(b, BzrDir)

    def test_open_remote_branch(self):
        # open a standalone branch in the working directory
        b = remote.RemoteBzrDir(self.transport)
        branch = b.open_branch()

    def test_remote_repository(self):
        b = BzrDir.open_from_transport(self.transport)
        repo = b.open_repository()
        revid = u'\xc823123123'
        self.assertFalse(repo.has_revision(revid))
        self.local_wt.commit(message='test commit', rev_id=revid)
        self.assertTrue(repo.has_revision(revid))

    def test_remote_branch_revision_history(self):
        b = BzrDir.open_from_transport(self.transport).open_branch()
        self.assertEqual([], b.revision_history())
        r1 = self.local_wt.commit('1st commit')
        r2 = self.local_wt.commit('1st commit', rev_id=u'\xc8')
        self.assertEqual([r1, r2], b.revision_history())

    def test_find_correct_format(self):
        """Should open a RemoteBzrDir over a RemoteTransport"""
        fmt = BzrDirFormat.find_format(self.transport)
        self.assertTrue(RemoteBzrDirFormat in BzrDirFormat._control_formats)
        self.assertIsInstance(fmt, remote.RemoteBzrDirFormat)

    def test_open_detected_smart_format(self):
        fmt = BzrDirFormat.find_format(self.transport)
        d = fmt.open(self.transport)
        self.assertIsInstance(d, BzrDir)


class FakeProtocol(object):
    """Lookalike SmartClientRequestProtocolOne allowing body reading tests."""

    def __init__(self, body):
        self._body_buffer = StringIO(body)

    def read_body_bytes(self, count=-1):
        return self._body_buffer.read(count)


class FakeClient(SmartClient):
    """Lookalike for SmartClient allowing testing."""
    
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

    def call2(self, method, *args):
        self._calls.append(('call2', method, args))
        result = self.responses.pop(0)
        return result[0], FakeProtocol(result[1])


class TestBranchLastRevisionInfo(tests.TestCase):

    def test_empty_branch(self):
        # in an empty branch we decode the response properly
        client = FakeClient([(('ok', '0', ''), )])
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

        client = FakeClient([(('ok', '2', u'\xc8'.encode('utf8')), )])
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
        self.assertEqual((2, u'\xc8'), result)


class TestBranchControlGetBranchConf(tests.TestCase):
    """Test branch.control_files api munging...

    we special case RemoteBranch.control_files.get('branch.conf') to 
    call a specific API so that RemoteBranch's can intercept configuration
    file reading, allowing them to signal to the client about things like
    'email is configured for commits'.
    """

    def test_get_branch_conf(self):
        # in an empty branch we decode the response properly
        client = FakeClient([(('ok', ), 'config file body')])
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.control_files.get('branch.conf')
        self.assertEqual(
            [('call2', 'Branch.get_config_file', ('///quack/',))],
            client._calls)
        self.assertEqual('config file body', result.read())


class TestRepositoryGatherStats(tests.TestCase):

    def setup_fake_client_and_repository(self, responses, transport_path):
        """Create the fake client and repository for testing with."""
        client = FakeClient(responses)
        transport = MemoryTransport()
        transport.mkdir(transport_path)
        transport = transport.clone(transport_path)
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return repo, client

    def test_revid_none(self):
        # ('ok',), body with revisions and size
        responses = [(('ok', ), 'revisions: 2\nsize: 18\n')]
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.gather_stats(None)
        self.assertEqual(
            [('call2', 'Repository.gather_stats', ('///quack/','','no'))],
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
        revid = u'\xc8'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.gather_stats(revid)
        self.assertEqual(
            [('call2', 'Repository.gather_stats',
              ('///quick/', revid.encode('utf8'), 'no'))],
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
        revid = u'\xc8'
        repo, client = self.setup_fake_client_and_repository(
            responses, transport_path)
        result = repo.gather_stats(revid, True)
        self.assertEqual(
            [('call2', 'Repository.gather_stats',
              ('///buick/', revid.encode('utf8'), 'yes'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'committers': 128,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)


class TestRepositoryIsShared(tests.TestCase):

    def setup_fake_client_and_repository(self, responses, transport_path):
        """Create the fake client and repository for testing with."""
        client = FakeClient(responses)
        transport = MemoryTransport()
        transport.mkdir(transport_path)
        transport = transport.clone(transport_path)
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return repo, client

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

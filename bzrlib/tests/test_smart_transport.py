# Copyright (C) 2006 Canonical Ltd
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

"""Tests for smart transport"""

# all of this deals with byte strings so this is safe
from cStringIO import StringIO
import subprocess
import sys

import bzrlib
from bzrlib import (
        bzrdir,
        errors,
        tests,
        )
from bzrlib.transport import (
        get_transport,
        local,
        memory,
        smart,
        )


class SmartClientTests(tests.TestCase):

    def test_construct_smart_stream_client(self):
        # make a new client; this really wants a connector function that returns
        # two fifos or sockets but the constructor should not do any IO
        client = smart.SmartStreamClient(None)


class TCPClientTests(tests.TestCaseWithTransport):

    def setUp(self):
        super(TCPClientTests, self).setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.transport_server = smart.SmartTCPServer_for_testing

    def test_plausible_url(self):
        self.assert_(self.get_url().startswith('bzr://'))

    def test_probe_transport(self):
        t = self.get_transport()
        self.assertIsInstance(t, smart.SmartTransport)

    def test_get_client_from_transport(self):
        t = self.get_transport()
        client = t.get_smart_client()
        self.assertIsInstance(client, smart.SmartStreamClient)


class BasicSmartTests(tests.TestCase):
    
    def test_smart_query_version(self):
        """Feed a canned query version to a server"""
        to_server = StringIO('hello\n')
        from_server = StringIO()
        server = smart.SmartStreamServer(to_server, from_server, local.LocalTransport('file:///'))
        server._serve_one_request()
        self.assertEqual('ok\0011\n',
                         from_server.getvalue())

    def test_canned_get_response(self):
        transport = memory.MemoryTransport('memory:///')
        transport.put_bytes('testfile', 'contents\nof\nfile\n')
        to_server = StringIO('get\001./testfile\n')
        from_server = StringIO()
        server = smart.SmartStreamServer(to_server, from_server, transport)
        server._serve_one_request()
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation"""
        class FlakyTransport(object):
            def get(self, path):
                raise Exception("some random exception from inside server")
        server = smart.SmartTCPServer(backing_transport=FlakyTransport())
        server.start_background_thread()
        try:
            transport = smart.SmartTCPTransport(server.get_url())
            try:
                transport.get('something')
            except errors.TransportError, e:
                self.assertContainsRe(str(e), 'some random exception')
            else:
                self.fail("get did not raise expected error")
        finally:
            server.stop_background_thread()

    def test_server_subprocess(self):
        """Talk to a server started as a subprocess
        
        This is similar to running it over ssh, except that it runs in the same machine 
        without ssh intermediating.
        """
        args = [sys.executable, sys.argv[0], 'serve', '--inet']
        child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 close_fds=True)
        conn = smart.SmartStreamClient(lambda: (child.stdout, child.stdin))
        conn.query_version()
        conn.query_version()
        conn.disconnect()
        returncode = child.wait()
        self.assertEquals(0, returncode)


class SmartTCPTests(tests.TestCase):
    """Tests for connection to TCP server.
    
    All of these tests are run with a server running on another thread serving
    a MemoryTransport, and a connection to it already open.
    """

    def setUp(self):
        super(SmartTCPTests, self).setUp()
        self.backing_transport = memory.MemoryTransport()
        self.server = smart.SmartTCPServer(self.backing_transport)
        self.server.start_background_thread()
        self.transport = smart.SmartTCPTransport(self.server.get_url())

    def tearDown(self):
        if getattr(self, 'transport', None):
            self.transport.disconnect()
        if getattr(self, 'server', None):
            self.server.stop_background_thread()
        super(SmartTCPTests, self).tearDown()
        
    def test_start_tcp_server(self):
        url = self.server.get_url()
        self.assertContainsRe(url, r'^bzr://127\.0\.0\.1:[0-9]{2,}/')

    def test_smart_transport_has(self):
        """Checking for file existence over smart."""
        self.backing_transport.put_bytes("foo", "contents of foo\n")
        self.assertTrue(self.transport.has("foo"))
        self.assertFalse(self.transport.has("non-foo"))

    def test_smart_transport_get(self):
        """Read back a file over smart."""
        self.backing_transport.put_bytes("foo", "contents\nof\nfoo\n")
        fp = self.transport.get("foo")
        self.assertEqual('contents\nof\nfoo\n', fp.read())
        
    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        # The path in a raised NoSuchFile exception should be the precise path
        # asked for by the client. This gives meaningful and unsurprising errors
        # for users.
        try:
            self.transport.get('not%20a%20file')
        except errors.NoSuchFile, e:
            self.assertEqual('not%20a%20file', e.path)
        else:
            self.fail("get did not raise expected error")

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = self.transport.clone('.')
        self.assertTrue(self.transport._client is conn2._client)

    def test__remote_path(self):
        self.assertEquals('/foo/bar',
                          self.transport._remote_path('foo/bar'))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location"""
        conn2 = self.transport.clone('subdir')
        self.assertEquals(self.transport.base + 'subdir/',
                          conn2.base)

    def test_open_dir(self):
        """Test changing directory"""
        transport = self.transport
        self.backing_transport.mkdir('toffee')
        self.backing_transport.mkdir('toffee/apple')
        self.assertEquals('/toffee', transport._remote_path('toffee'))
        self.assertTrue(transport.has('toffee'))
        sub_conn = transport.clone('toffee')
        self.assertTrue(sub_conn.has('apple'))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over smart transport"""
        transport = self.transport
        t = self.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = bzrdir.BzrDir.open_containing_from_transport(transport)


class SmartServerTests(tests.TestCaseWithTransport):
    """Test that call directly into the server logic, bypassing the network."""

    def test_hello(self):
        server = smart.SmartServer(None)
        response = server.dispatch_command('hello', ())
        self.assertEqual(('ok', '1'), response.args)
        self.assertEqual(None, response.body)
        
    def test_get_bundle(self):
        from bzrlib.bundle import serializer
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id='rev-1')
        
        server = smart.SmartServer(self.get_transport())
        response = server.dispatch_command('get_bundle', ('.', 'rev-1'))
        self.assert_(response.body.startswith('# Bazaar revision bundle '),
                     "doesn't look like a bundle: %r" % response.body)
        bundle = serializer.read_bundle(StringIO(response.body))


class SmartTransportRegistration(tests.TestCase):

    def test_registration(self):
        t = get_transport('bzr+ssh://example.com/path')
        self.assertIsInstance(t, smart.SmartSSHTransport)
        self.assertEqual('example.com', t._host)


class FakeClient(smart.SmartStreamClient):
    """Emulate a client for testing a transport's use of the client."""

    def __init__(self):
        smart.SmartStreamClient.__init__(self, None)
        self._calls = []

    def _call(self, *args):
        self._calls.append(('_call', args))
        return ('ok', )

    def _recv_bulk(self):
        return 'bar'


class TestSmartTransport(tests.TestCase):
        
    def test_use_connection_factory(self):
        # We want to be able to pass a client as a parameter to SmartTransport.
        client = FakeClient()
        transport = smart.SmartTransport('bzr://localhost/', client=client)

        # We want to make sure the client is used when the first remote
        # method is called.  No method should have been called yet.
        self.assertEqual([], client._calls)

        # Now call a method that should result in a single request.
        self.assertEqual('bar', transport.get_bytes('foo'))
        # The only call to _call should have been to get /foo.
        self.assertEqual([('_call', ('get', '/foo'))], client._calls)


# TODO: Client feature that does get_bundle and then installs that into a
# branch; this can be used in place of the regular pull/fetch operation when
# coming from a smart server.
#
# TODO: Eventually, want to do a 'branch' command by fetching the whole
# history as one big bundle.  How?  
#
# The branch command does 'br_from.sprout', which tries to preserve the same
# format.  We don't necessarily even want that.  
#
# It might be simpler to handle cmd_pull first, which does a simpler fetch()
# operation from one branch into another.  It already has some code for
# pulling from a bundle, which it does by trying to see if the destination is
# a bundle file.  So it seems the logic for pull ought to be:
# 
#  - if it's a smart server, get a bundle from there and install that
#  - if it's a bundle, install that
#  - if it's a branch, pull from there
#
# Getting a bundle from a smart server is a bit different from reading a
# bundle from a URL:
#
#  - we can reasonably remember the URL we last read from 
#  - you can specify a revision number to pull, and we need to pass it across
#    to the server as a limit on what will be requested
#
# TODO: Given a URL, determine whether it is a smart server or not (or perhaps
# otherwise whether it's a bundle?)  Should this be a property or method of
# the transport?  For the ssh protocol, we always know it's a smart server.
# For http, we potentially need to probe.  But if we're explicitly given
# bzr+http:// then we can skip that for now. 

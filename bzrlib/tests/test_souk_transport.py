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

"""Tests for souk transport"""

# TODO: Try sending multiple requests; they should all get answers.

# TODO: If the server raises an error within its processing that should be
# caught and propagated back to the client.

# all of this deals with byte strings so this is safe
from cStringIO import StringIO
import subprocess
import sys

import bzrlib
from bzrlib import tests, errors, bzrdir
from bzrlib.transport import local, memory, souk

class BasicSoukTests(tests.TestCase):
    
    def test_souk_query_version(self):
        """Feed a canned query version to a server"""
        to_server = StringIO('hello\0011\n')
        from_server = StringIO()
        server = souk.SoukStreamServer(to_server, from_server, local.LocalTransport('file:///'))
        server._serve_one_request()
        self.assertEqual('bzr server\0011\n',
                         from_server.getvalue())

    def test_canned_get_response(self):
        transport = memory.MemoryTransport('memory:///')
        transport.put('hello', StringIO('contents\nof\nfile\n'))
        to_server = StringIO('get\001./hello\n')
        from_server = StringIO()
        server = souk.SoukStreamServer(to_server, from_server, transport)
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
        server = souk.SoukTCPServer(backing_transport=FlakyTransport())
        server.start_background_thread()
        try:
            conn = souk.SoukTCPClient(server.get_url()) 
            try:
                conn.get('something')
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
        conn = souk.SoukStreamClient(to_server=child.stdin, from_server=child.stdout)
        conn.query_version()
        conn.query_version()
        conn.disconnect()
        returncode = child.wait()
        self.assertEquals(0, returncode)


class SoukTCPTests(tests.TestCase):
    """Tests for connection to TCP server.
    
    All of these tests are run with a server running on another thread serving
    a MemoryTransport, and a connection to it already open.
    """

    def setUp(self):
        super(SoukTCPTests, self).setUp()
        self.backing_transport = memory.MemoryTransport()
        self.server = souk.SoukTCPServer(self.backing_transport)
        self.server.start_background_thread()
        self.conn = souk.SoukTCPClient(self.server.get_url())

    def tearDown(self):
        if hasattr(self, 'conn'):
            self.conn.disconnect()
        if hasattr(self, 'server'):
            self.server.stop_background_thread()
        super(SoukTCPTests, self).tearDown()
        
    def test_start_tcp_server(self):
        url = self.server.get_url()
        self.assertContainsRe(url, r'^bzr://127\.0\.0\.1:[0-9]{2,}/')

    def test_connect_to_tcp_server(self):
        self.conn.query_version()

    def test_multiple_requests(self):
        version = self.conn.query_version()
        self.assertEqual(1, version)
        version = self.conn.query_version()
        self.assertEqual(1, version)

    def test_souk_transport_has(self):
        """Checking for file existence over souk."""
        self.backing_transport.put("foo", StringIO("contents of foo\n"))
        self.assertTrue(self.conn.has("foo"))
        self.assertFalse(self.conn.has("non-foo"))

    def test_souk_transport_get(self):
        """Read back a file over souk."""
        self.backing_transport.put("foo", StringIO("contents\nof\nfoo\n"))
        fp = self.conn.get("foo")
        self.assertEqual('contents\nof\nfoo\n', fp.read())
        
    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        try:
            self.conn.get('not a file')
        except errors.NoSuchFile, e:
            self.assertEqual('/not a file', e.path)
        else:
            self.fail("get did not raise expected error")

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn = self.conn
        conn2 = souk.SoukTransport(self.conn.base, clone_from=self.conn)
        conn.query_version()
        conn2.query_version()

    def test_remote_path(self):
        self.assertEquals('/foo/bar',
                          self.conn._remote_path('foo/bar'))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location"""
        conn = self.conn
        conn2 = conn.clone('subdir')
        self.assertEquals(conn.base + 'subdir/',
                          conn2.base)

    def test_open_dir(self):
        """Test changing directory"""
        conn = self.conn
        self.backing_transport.mkdir('toffee')
        self.backing_transport.mkdir('toffee/apple')
        self.assertEquals('/toffee', conn._remote_path('toffee'))
        self.assertTrue(conn.has('toffee'))
        sub_conn = conn.clone('toffee')
        self.assertTrue(sub_conn.has('apple'))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over souk transport"""
        conn = self.conn
        t = self.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = bzrdir.BzrDir.open_containing_from_transport(conn)

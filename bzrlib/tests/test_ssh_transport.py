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

"""Tests for ssh transport"""

# TODO: Try sending multiple requests; they should all get answers.

# TODO: If the server raises an error within its processing that should be
# caught and propagated back to the client.

# all of this deals with byte strings so this is safe
from cStringIO import StringIO

import bzrlib
from bzrlib import tests, errors, bzrdir
from bzrlib.transport import local, memory, ssh

class TestSSHTransport(tests.TestCase):
    
    def test_loopback_ssh_connection_exists(self):
        ssh.LoopbackSSHConnection()

    def test_ssh_query_version(self):
        """Feed a canned query version to a server"""
        to_server = StringIO('hello\0011\n')
        from_server = StringIO()
        server = ssh.Server(to_server, from_server, local.LocalTransport('file:///'))
        server._serve_one_request()
        self.assertEqual('bzr server\0011\n',
                         from_server.getvalue())

    def test_canned_get_response(self):
        transport = memory.MemoryTransport('memory:///')
        transport.put('hello', StringIO('contents\nof\nfile\n'))
        to_server = StringIO('get\001./hello\n')
        from_server = StringIO()
        server = ssh.Server(to_server, from_server, transport)
        server._serve_one_request()
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_open_loopback_server(self):
        conn = ssh.LoopbackSSHConnection()
        version = conn.query_version()
        self.assertEqual(1, version)

    def test_server_shutdown_on_client_disconnect(self):
        conn = ssh.LoopbackSSHConnection()
        conn.disconnect()
        conn._server_thread.join()
        self.assertFalse(conn._server_thread.isAlive())

    def test_multiple_requests(self):
        conn = ssh.LoopbackSSHConnection()
        version = conn.query_version()
        self.assertEqual(1, version)
        version = conn.query_version()
        self.assertEqual(1, version)

    def test_ssh_transport_has(self):
        """Checking for file existence over ssh."""
        conn = ssh.LoopbackSSHConnection()
        conn.backing_transport.put("foo", StringIO("contents of foo\n"))
        self.assertTrue(conn.has("foo"))
        self.assertFalse(conn.has("non-foo"))

    def test_ssh_transport_get(self):
        """Read back a file over ssh."""
        conn = ssh.LoopbackSSHConnection()
        conn.backing_transport.put("foo", StringIO("contents\nof\nfoo\n"))
        fp = conn.get("foo")
        self.assertEqual('contents\nof\nfoo\n', fp.read())
        
    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        conn = ssh.LoopbackSSHConnection()
        try:
            conn.get('not a file')
        except errors.NoSuchFile, e:
            self.assertEqual('not a file', e.path)
        else:
            self.fail("get did not raise expected error")

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation"""
        class FlakyTransport(object):
            def get(self, path):
                raise Exception("some random exception from inside server")
        conn = ssh.LoopbackSSHConnection(backing_transport=FlakyTransport())
        try:
            conn.get('something')
        except errors.TransportError, e:
            self.assertContainsRe(str(e), 'some random exception')
        else:
            self.fail("get did not raise expected error")

    def test_loopback_conn_has_base_url(self):
        conn = ssh.LoopbackSSHConnection()
        self.assertEquals('ssh+loopback:///', conn.base)

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        conn = ssh.LoopbackSSHConnection()
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = ssh.SSHConnection('ssh+loopback:///', clone_from=conn)
        conn2.query_version()

    def test_abspath(self):
        conn = ssh.LoopbackSSHConnection()
        self.assertEquals('ssh+loopback:///foo/bar',
                          conn.abspath('foo/bar'))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location"""
        conn = ssh.LoopbackSSHConnection()
        conn2 = conn.clone('subdir')
        self.assertEquals(conn.base + 'subdir/',
                          conn2.base)

    def test_open_dir(self):
        """Test changing directory"""
        conn = ssh.LoopbackSSHConnection()
        conn.backing_transport.mkdir('toffee')
        conn.backing_transport.mkdir('toffee/apple')
        self.assertTrue(conn.has('toffee'))
        return ################################################
        sub_conn = conn.clone('toffee')
        self.assertTrue(sub_conn.has('apple'))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over ssh transport"""
        return ################################################
        conn = ssh.LoopbackSSHConnection()
        t = conn.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = bzrdir.BzrDir.open_containing_from_transport(conn)

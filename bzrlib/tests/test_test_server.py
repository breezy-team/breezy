# Copyright (C) 2010, 2011 Canonical Ltd
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

import errno
import socket
import SocketServer
import threading

from bzrlib import (
    osutils,
    tests,
    )
from bzrlib.tests import test_server
from bzrlib.tests.scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


class TCPClient(object):

    def __init__(self):
        self.sock = None

    def connect(self, addr):
        if self.sock is not None:
            raise AssertionError('Already connected to %r'
                                 % (self.sock.getsockname(),))
        self.sock = osutils.connect_socket(addr)

    def disconnect(self):
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except socket.error, e:
                if e[0] in (errno.EBADF, errno.ENOTCONN):
                    # Right, the socket is already down
                    pass
                else:
                    raise
            self.sock = None

    def write(self, s):
        return self.sock.sendall(s)

    def read(self, bufsize=4096):
        return self.sock.recv(bufsize)


class TCPConnectionHandler(SocketServer.StreamRequestHandler):

    def handle(self):
        self.done = False
        self.handle_connection()
        while not self.done:
            self.handle_connection()

    def handle_connection(self):
        req = self.rfile.readline()
        if not req:
            self.done = True
        elif req == 'ping\n':
            self.wfile.write('pong\n')
        else:
            raise ValueError('[%s] not understood' % req)


class TestTCPServerInAThread(tests.TestCase):

    scenarios = [ 
        (name, {'server_class': getattr(test_server, name)})
        for name in
        ('TestingTCPServer', 'TestingThreadingTCPServer')]

    # Set by load_tests()
    server_class = None

    def get_server(self, server_class=None, connection_handler_class=None):
        if server_class is not None:
            self.server_class = server_class
        if connection_handler_class is None:
            connection_handler_class = TCPConnectionHandler
        server =  test_server.TestingTCPServerInAThread(
            ('localhost', 0), self.server_class, connection_handler_class)
        server.start_server()
        self.addCleanup(server.stop_server)
        return server

    def get_client(self):
        client = TCPClient()
        self.addCleanup(client.disconnect)
        return client

    def get_server_connection(self, server, conn_rank):
        return server.server.clients[conn_rank]

    def assertClientAddr(self, client, server, conn_rank):
        conn = self.get_server_connection(server, conn_rank)
        self.assertEquals(client.sock.getsockname(), conn[1])

    def test_start_stop(self):
        server = self.get_server()
        client = self.get_client()
        server.stop_server()
        # since the server doesn't accept connections anymore attempting to
        # connect should fail
        client = self.get_client()
        self.assertRaises(socket.error,
                          client.connect, (server.host, server.port))

    def test_client_talks_server_respond(self):
        server = self.get_server()
        client = self.get_client()
        client.connect((server.host, server.port))
        self.assertIs(None, client.write('ping\n'))
        resp = client.read()
        self.assertClientAddr(client, server, 0)
        self.assertEquals('pong\n', resp)

    def test_server_fails_to_start(self):
        class CantStart(Exception):
            pass

        class CantStartServer(test_server.TestingTCPServer):

            def server_bind(self):
                raise CantStart()

        # The exception is raised in the main thread
        self.assertRaises(CantStart,
                          self.get_server, server_class=CantStartServer)

    def test_server_fails_while_serving_or_stopping(self):
        class CantConnect(Exception):
            pass

        class FailingConnectionHandler(TCPConnectionHandler):

            def handle(self):
                raise CantConnect()

        server = self.get_server(
            connection_handler_class=FailingConnectionHandler)
        # The server won't fail until a client connect
        client = self.get_client()
        client.connect((server.host, server.port))
        try:
            # Now we must force the server to answer by sending the request and
            # waiting for some answer. But since we don't control when the
            # server thread will be given cycles, we don't control either
            # whether our reads or writes may hang.
            client.sock.settimeout(0.1)
            client.write('ping\n')
            client.read()
        except socket.error:
            pass
        # Now the server has raised the exception in its own thread
        self.assertRaises(CantConnect, server.stop_server)

    def test_server_crash_while_responding(self):
        sync = threading.Event()
        sync.clear()
        class FailToRespond(Exception):
            pass

        class FailingDuringResponseHandler(TCPConnectionHandler):

            def handle_connection(self):
                req = self.rfile.readline()
                threading.currentThread().set_sync_event(sync)
                raise FailToRespond()

        server = self.get_server(
            connection_handler_class=FailingDuringResponseHandler)
        client = self.get_client()
        client.connect((server.host, server.port))
        client.write('ping\n')
        sync.wait()
        self.assertRaises(FailToRespond, server.pending_exception)

    def test_exception_swallowed_while_serving(self):
        sync = threading.Event()
        sync.clear()
        class CantServe(Exception):
            pass

        class FailingWhileServingConnectionHandler(TCPConnectionHandler):

            def handle(self):
                # We want to sync with the thread that is serving the
                # connection.
                threading.currentThread().set_sync_event(sync)
                raise CantServe()

        server = self.get_server(
            connection_handler_class=FailingWhileServingConnectionHandler)
        # Install the exception swallower
        server.set_ignored_exceptions(CantServe)
        client = self.get_client()
        # Connect to the server so the exception is raised there
        client.connect((server.host, server.port))
        # Wait for the exception to propagate.
        sync.wait()
        # The connection wasn't served properly but the exception should have
        # been swallowed.
        server.pending_exception()

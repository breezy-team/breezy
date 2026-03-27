# Copyright (C) 2010, 2011, 2016 Canonical Ltd
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
import socketserver
import threading
import unittest

from dromedary.tests import test_server


def portable_socket_pair():
    """Return a pair of TCP sockets connected to each other.

    Unlike socket.socketpair, this should work on Windows.
    """
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_sock.bind(("127.0.0.1", 0))
    listen_sock.listen(1)
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect(listen_sock.getsockname())
    server_sock, _addr = listen_sock.accept()
    listen_sock.close()
    return server_sock, client_sock


class TCPClient:
    def __init__(self):
        self.sock = None

    def connect(self, addr):
        if self.sock is not None:
            raise AssertionError(f"Already connected to {self.sock.getsockname()!r}")
        self.sock = test_server.connect_socket(addr)

    def disconnect(self):
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except OSError as e:
                if e.errno in (errno.EBADF, errno.ENOTCONN, errno.ECONNRESET):
                    pass
                else:
                    raise
            self.sock = None

    def write(self, s):
        return self.sock.sendall(s)

    def read(self, bufsize=4096):
        try:
            return self.sock.recv(bufsize)
        except OSError as e:
            if e.errno == errno.ECONNRESET:
                return b""
            raise


class TCPConnectionHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.done = False
        self.handle_connection()
        while not self.done:
            self.handle_connection()

    def readline(self):
        req = self.request.recv(4096)
        if not req or (req.endswith(b"\n") and req.count(b"\n") == 1):
            return req
        raise ValueError(f"[{req!r}] not a simple line")

    def handle_connection(self):
        req = self.readline()
        if not req:
            self.done = True
        elif req == b"ping\n":
            self.request.sendall(b"pong\n")
        else:
            raise ValueError(f"[{req}] not understood")


class TestTCPServerInAThreadBase:
    """Mixin with test methods for TCP server implementations."""

    server_class = None

    def get_server(self, server_class=None, connection_handler_class=None):
        if server_class is not None:
            self.server_class = server_class
        if connection_handler_class is None:
            connection_handler_class = TCPConnectionHandler
        server = test_server.TestingTCPServerInAThread(
            ("localhost", 0), self.server_class, connection_handler_class
        )
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
        self.assertEqual(client.sock.getsockname(), conn[1])

    def test_start_stop(self):
        server = self.get_server()
        client = self.get_client()
        server.stop_server()
        # since the server doesn't accept connections anymore attempting to
        # connect should fail
        client = self.get_client()
        self.assertRaises(socket.error, client.connect, (server.host, server.port))

    def test_client_talks_server_respond(self):
        server = self.get_server()
        client = self.get_client()
        client.connect((server.host, server.port))
        self.assertIs(None, client.write(b"ping\n"))
        resp = client.read()
        self.assertClientAddr(client, server, 0)
        self.assertEqual(b"pong\n", resp)

    def test_server_fails_to_start(self):
        class CantStart(Exception):
            pass

        class CantStartServer(test_server.TestingTCPServer):
            def server_bind(self):
                raise CantStart()

        # The exception is raised in the main thread
        self.assertRaises(CantStart, self.get_server, server_class=CantStartServer)

    def test_server_fails_while_serving_or_stopping(self):
        class CantConnect(Exception):
            pass

        class FailingConnectionHandler(TCPConnectionHandler):
            def handle(self):
                raise CantConnect()

        server = self.get_server(connection_handler_class=FailingConnectionHandler)
        client = self.get_client()
        client.connect((server.host, server.port))
        client.write(b"ping\n")
        try:
            self.assertEqual(b"", client.read())
        except OSError as e:
            WSAECONNRESET = 10054
            if e.errno in (WSAECONNRESET,):
                pass
        self.assertRaises(CantConnect, server.stop_server)

    def test_server_crash_while_responding(self):
        caught = threading.Event()
        caught.clear()
        self.connection_thread = None

        class FailToRespond(Exception):
            pass

        class FailingDuringResponseHandler(TCPConnectionHandler):
            def handle_connection(request):  # noqa: N805
                request.readline()
                self.connection_thread = threading.current_thread()
                self.connection_thread.set_sync_event(caught)
                raise FailToRespond()

        server = self.get_server(connection_handler_class=FailingDuringResponseHandler)
        client = self.get_client()
        client.connect((server.host, server.port))
        client.write(b"ping\n")
        caught.wait()
        self.assertEqual(b"", client.read())
        self.assertRaises(FailToRespond, self.connection_thread.pending_exception)

    def test_exception_swallowed_while_serving(self):
        caught = threading.Event()
        caught.clear()
        self.connection_thread = None

        class CantServe(Exception):
            pass

        class FailingWhileServingConnectionHandler(TCPConnectionHandler):
            def handle(request):  # noqa: N805
                self.connection_thread = threading.current_thread()
                self.connection_thread.set_sync_event(caught)
                raise CantServe()

        server = self.get_server(
            connection_handler_class=FailingWhileServingConnectionHandler
        )
        self.assertEqual(True, server.server.serving)
        server.set_ignored_exceptions(CantServe)
        client = self.get_client()
        client.connect((server.host, server.port))
        caught.wait()
        self.assertEqual(b"", client.read())
        self.assertIs(None, self.connection_thread.pending_exception())
        self.assertIs(None, server.pending_exception())

    def test_handle_request_closes_if_it_doesnt_process(self):
        server = self.get_server()
        client = self.get_client()
        server.server.serving = False
        try:
            client.connect((server.host, server.port))
            self.assertEqual(b"", client.read())
        except OSError as e:
            if e.errno != errno.ECONNRESET:
                raise


class TestTCPServerInAThread_TestingTCPServer(
    TestTCPServerInAThreadBase, unittest.TestCase
):
    server_class = test_server.TestingTCPServer


class TestTCPServerInAThread_TestingThreadingTCPServer(
    TestTCPServerInAThreadBase, unittest.TestCase
):
    server_class = test_server.TestingThreadingTCPServer

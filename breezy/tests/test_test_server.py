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


from breezy import (
    osutils,
    tests,
    )
from breezy.tests import test_server
from breezy.tests.scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


def portable_socket_pair():
    """Return a pair of TCP sockets connected to each other.

    Unlike socket.socketpair, this should work on Windows.
    """
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_sock.bind(('127.0.0.1', 0))
    listen_sock.listen(1)
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect(listen_sock.getsockname())
    server_sock, addr = listen_sock.accept()
    listen_sock.close()
    return server_sock, client_sock


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
            except socket.error as e:
                if e.errno in (errno.EBADF, errno.ENOTCONN, errno.ECONNRESET):
                    # Right, the socket is already down
                    pass
                else:
                    raise
            self.sock = None

    def write(self, s):
        return self.sock.sendall(s)

    def read(self, bufsize=4096):
        return self.sock.recv(bufsize)


class TCPConnectionHandler(socketserver.BaseRequestHandler):

    def handle(self):
        self.done = False
        self.handle_connection()
        while not self.done:
            self.handle_connection()

    def readline(self):
        # TODO: We should be buffering any extra data sent, etc. However, in
        #       practice, we don't send extra content, so we haven't bothered
        #       to implement it yet.
        req = self.request.recv(4096)
        # An empty string is allowed, to indicate the end of the connection
        if not req or (req.endswith(b'\n') and req.count(b'\n') == 1):
            return req
        raise ValueError('[%r] not a simple line' % (req,))

    def handle_connection(self):
        req = self.readline()
        if not req:
            self.done = True
        elif req == b'ping\n':
            self.request.sendall(b'pong\n')
        else:
            raise ValueError('[%s] not understood' % req)


class TestTCPServerInAThread(tests.TestCase):

    scenarios = [
        (name, {'server_class': getattr(test_server, name)})
        for name in
        ('TestingTCPServer', 'TestingThreadingTCPServer')]

    def get_server(self, server_class=None, connection_handler_class=None):
        if server_class is not None:
            self.server_class = server_class
        if connection_handler_class is None:
            connection_handler_class = TCPConnectionHandler
        server = test_server.TestingTCPServerInAThread(
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
        self.assertEqual(client.sock.getsockname(), conn[1])

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
        self.assertIs(None, client.write(b'ping\n'))
        resp = client.read()
        self.assertClientAddr(client, server, 0)
        self.assertEqual(b'pong\n', resp)

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
        # We make sure the server wants to handle a request, but the request is
        # guaranteed to fail. However, the server should make sure that the
        # connection gets closed, and stop_server should then raise the
        # original exception.
        client.write(b'ping\n')
        try:
            self.assertEqual(b'', client.read())
        except socket.error as e:
            # On Windows, failing during 'handle' means we get
            # 'forced-close-of-connection'. Possibly because we haven't
            # processed the write request before we close the socket.
            WSAECONNRESET = 10054
            if e.errno in (WSAECONNRESET,):
                pass
        # Now the server has raised the exception in its own thread
        self.assertRaises(CantConnect, server.stop_server)

    def test_server_crash_while_responding(self):
        # We want to ensure the exception has been caught
        caught = threading.Event()
        caught.clear()
        # The thread that will serve the client, this needs to be an attribute
        # so the handler below can modify it when it's executed (it's
        # instantiated when the request is processed)
        self.connection_thread = None

        class FailToRespond(Exception):
            pass

        class FailingDuringResponseHandler(TCPConnectionHandler):

            # We use 'request' instead of 'self' below because the test matters
            # more and we need a container to properly set connection_thread.
            def handle_connection(request):
                request.readline()
                # Capture the thread and make it use 'caught' so we can wait on
                # the event that will be set when the exception is caught. We
                # also capture the thread to know where to look.
                self.connection_thread = threading.currentThread()
                self.connection_thread.set_sync_event(caught)
                raise FailToRespond()

        server = self.get_server(
            connection_handler_class=FailingDuringResponseHandler)
        client = self.get_client()
        client.connect((server.host, server.port))
        client.write(b'ping\n')
        # Wait for the exception to be caught
        caught.wait()
        self.assertEqual(b'', client.read())  # connection closed
        # Check that the connection thread did catch the exception,
        # http://pad.lv/869366 was wrongly checking the server thread which
        # works for TestingTCPServer where the connection is handled in the
        # same thread than the server one but was racy for
        # TestingThreadingTCPServer. Since the connection thread detaches
        # itself before handling the request, we are guaranteed that the
        # exception won't leak into the server thread anymore.
        self.assertRaises(FailToRespond,
                          self.connection_thread.pending_exception)

    def test_exception_swallowed_while_serving(self):
        # We need to ensure the exception has been caught
        caught = threading.Event()
        caught.clear()
        # The thread that will serve the client, this needs to be an attribute
        # so the handler below can access it when it's executed (it's
        # instantiated when the request is processed)
        self.connection_thread = None

        class CantServe(Exception):
            pass

        class FailingWhileServingConnectionHandler(TCPConnectionHandler):

            # We use 'request' instead of 'self' below because the test matters
            # more and we need a container to properly set connection_thread.
            def handle(request):
                # Capture the thread and make it use 'caught' so we can wait on
                # the event that will be set when the exception is caught. We
                # also capture the thread to know where to look.
                self.connection_thread = threading.currentThread()
                self.connection_thread.set_sync_event(caught)
                raise CantServe()

        server = self.get_server(
            connection_handler_class=FailingWhileServingConnectionHandler)
        self.assertEqual(True, server.server.serving)
        # Install the exception swallower
        server.set_ignored_exceptions(CantServe)
        client = self.get_client()
        # Connect to the server so the exception is raised there
        client.connect((server.host, server.port))
        # Wait for the exception to be caught
        caught.wait()
        self.assertEqual(b'', client.read())  # connection closed
        # The connection wasn't served properly but the exception should have
        # been swallowed (see test_server_crash_while_responding remark about
        # http://pad.lv/869366 explaining why we can't check the server thread
        # here). More precisely, the exception *has* been caught and captured
        # but it is cleared when joining the thread (or trying to acquire the
        # exception) and as such won't propagate to the server thread.
        self.assertIs(None, self.connection_thread.pending_exception())
        self.assertIs(None, server.pending_exception())

    def test_handle_request_closes_if_it_doesnt_process(self):
        server = self.get_server()
        client = self.get_client()
        server.server.serving = False
        try:
            client.connect((server.host, server.port))
            self.assertEqual(b'', client.read())
        except socket.error as e:
            if e.errno != errno.ECONNRESET:
                raise


class TestTestingSmartServer(tests.TestCase):

    def test_sets_client_timeout(self):
        server = test_server.TestingSmartServer(
            ('localhost', 0), None, None,
            root_client_path='/no-such-client/path')
        self.assertEqual(test_server._DEFAULT_TESTING_CLIENT_TIMEOUT,
                         server._client_timeout)
        sock = socket.socket()
        h = server._make_handler(sock)
        self.assertEqual(test_server._DEFAULT_TESTING_CLIENT_TIMEOUT,
                         h._client_timeout)


class FakeServer(object):
    """Minimal implementation to pass to TestingSmartConnectionHandler"""
    backing_transport = None
    root_client_path = '/'


class TestTestingSmartConnectionHandler(tests.TestCase):

    def test_connection_timeout_suppressed(self):
        self.overrideAttr(test_server, '_DEFAULT_TESTING_CLIENT_TIMEOUT', 0.01)
        s = FakeServer()
        server_sock, client_sock = portable_socket_pair()
        # This should timeout quickly, but not generate an exception.
        test_server.TestingSmartConnectionHandler(
            server_sock, server_sock.getpeername(), s)

    def test_connection_shutdown_while_serving_no_error(self):
        s = FakeServer()
        server_sock, client_sock = portable_socket_pair()

        class ShutdownConnectionHandler(
                test_server.TestingSmartConnectionHandler):

            def _build_protocol(self):
                self.finished = True
                return super(ShutdownConnectionHandler, self)._build_protocol()
        # This should trigger shutdown after the entering _build_protocol, and
        # we should exit cleanly, without raising an exception.
        ShutdownConnectionHandler(server_sock, server_sock.getpeername(), s)

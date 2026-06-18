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

"""Tests for the smart server test infrastructure."""

import socket

from dromedary.tests.test_test_server import portable_socket_pair

from breezy import tests
from breezy.tests import test_server


class TestTestingSmartServer(tests.TestCase):
    def test_sets_client_timeout(self):
        server = test_server.TestingSmartServer(
            ("localhost", 0), None, None, root_client_path="/no-such-client/path"
        )
        self.assertEqual(
            test_server._DEFAULT_TESTING_CLIENT_TIMEOUT, server._client_timeout
        )
        sock = socket.socket()
        h = server._make_handler(sock)
        self.assertEqual(test_server._DEFAULT_TESTING_CLIENT_TIMEOUT, h._client_timeout)


class FakeServer:
    """Minimal implementation to pass to TestingSmartConnectionHandler."""

    backing_transport = None
    root_client_path = "/"


class TestTestingSmartConnectionHandler(tests.TestCase):
    def test_connection_timeout_suppressed(self):
        self.overrideAttr(test_server, "_DEFAULT_TESTING_CLIENT_TIMEOUT", 0.01)
        s = FakeServer()
        server_sock, _client_sock = portable_socket_pair()
        # This should timeout quickly, but not generate an exception.
        test_server.TestingSmartConnectionHandler(
            server_sock, server_sock.getpeername(), s
        )

    def test_connection_shutdown_while_serving_no_error(self):
        s = FakeServer()
        server_sock, _client_sock = portable_socket_pair()

        class ShutdownConnectionHandler(test_server.TestingSmartConnectionHandler):
            def _build_protocol(self):
                self.finished = True
                return super()._build_protocol()

        # This should trigger shutdown after the entering _build_protocol, and
        # we should exit cleanly, without raising an exception.
        ShutdownConnectionHandler(server_sock, server_sock.getpeername(), s)

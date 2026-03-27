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

"""Test server implementations for the smart server."""

import socket
import socketserver

from breezy import errors, transport
from breezy.bzr.smart import medium, server
from dromedary import chroot

# Re-export from dromedary for backward compatibility
from dromedary.tests import test_server as _dromedary_test_server
from dromedary.tests.test_server import (  # noqa: F401
    BrokenRenameServer,
    DecoratorServer,
    FakeNFSServer,
    FakeVFATServer,
    LocalURLServer,
    LogDecoratorServer,
    NoSmartTransportServer,
    ReadonlyServer,
    TestingChrootServer,
    TestingPathFilteringServer,
    TestingTCPServer,
    TestingTCPServerInAThread,
    TestingTCPServerMixin,
    TestingThreadingTCPServer,
    TestServer,
    TestThread,
    TraceServer,
    UnlistableServer,
    debug_threads,
)


def _breezy_debug_threads():
    from breezy import tests
    return "threads" in tests.selftest_debug_flags


_dromedary_test_server.debug_threads_hook = _breezy_debug_threads


class TestingSmartConnectionHandler(
    socketserver.BaseRequestHandler, medium.SmartServerSocketStreamMedium
):
    def __init__(self, request, client_address, server):
        medium.SmartServerSocketStreamMedium.__init__(
            self,
            request,
            server.backing_transport,
            server.root_client_path,
            timeout=_DEFAULT_TESTING_CLIENT_TIMEOUT,
        )
        request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        socketserver.BaseRequestHandler.__init__(self, request, client_address, server)

    def handle(self):
        try:
            while not self.finished:
                server_protocol = self._build_protocol()
                self._serve_one_request(server_protocol)
        except errors.ConnectionTimeout:
            # idle connections aren't considered a failure of the server
            return


_DEFAULT_TESTING_CLIENT_TIMEOUT = 60.0


class TestingSmartServer(TestingThreadingTCPServer, server.SmartTCPServer):
    def __init__(
        self, server_address, request_handler_class, backing_transport, root_client_path
    ):
        TestingThreadingTCPServer.__init__(self, server_address, request_handler_class)
        server.SmartTCPServer.__init__(
            self,
            backing_transport,
            root_client_path,
            client_timeout=_DEFAULT_TESTING_CLIENT_TIMEOUT,
        )

    def serve(self):
        self.run_server_started_hooks()
        try:
            TestingThreadingTCPServer.serve(self)
        finally:
            self.run_server_stopped_hooks()

    def get_url(self):
        """Return the url of the server."""
        return "bzr://%s:%d/" % self.server_address


class SmartTCPServer_for_testing(TestingTCPServerInAThread):
    """Server suitable for use by transport tests.

    This server is backed by the process's cwd.
    """

    def __init__(self, thread_name_suffix=""):
        self.client_path_extra = None
        self.thread_name_suffix = thread_name_suffix
        self.host = "127.0.0.1"
        self.port = 0
        super().__init__(
            (self.host, self.port), TestingSmartServer, TestingSmartConnectionHandler
        )

    def create_server(self):
        return self.server_class(
            (self.host, self.port),
            self.request_handler_class,
            self.backing_transport,
            self.root_client_path,
        )

    def start_server(self, backing_transport_server=None, client_path_extra="/extra/"):
        """Set up server for testing.

        :param backing_transport_server: backing server to use.  If not
            specified, a LocalURLServer at the current working directory will
            be used.
        :param client_path_extra: a path segment starting with '/' to append to
            the root URL for this server.  For instance, a value of '/foo/bar/'
            will mean the root of the backing transport will be published at a
            URL like `bzr://127.0.0.1:nnnn/foo/bar/`, rather than
            `bzr://127.0.0.1:nnnn/`.  Default value is `extra`, so that tests
            by default will fail unless they do the necessary path translation.
        """
        if not client_path_extra.startswith("/"):
            raise ValueError(client_path_extra)
        self.root_client_path = self.client_path_extra = client_path_extra
        if backing_transport_server is None:
            backing_transport_server = LocalURLServer()
        self.chroot_server = chroot.ChrootServer(
            self.get_backing_transport(backing_transport_server)
        )
        self.chroot_server.start_server()
        self.backing_transport = transport.get_transport_from_url(
            self.chroot_server.get_url()
        )
        super().start_server()

    def stop_server(self):
        try:
            super().stop_server()
        finally:
            self.chroot_server.stop_server()

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        return transport.get_transport_from_url(backing_transport_server.get_url())

    def get_url(self):
        url = self.server.get_url()
        return url[:-1] + self.client_path_extra

    def get_bogus_url(self):
        """Return a URL which will fail to connect."""
        return "bzr://127.0.0.1:1/"


class ReadonlySmartTCPServer_for_testing(SmartTCPServer_for_testing):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = "readonly+" + backing_transport_server.get_url()
        return transport.get_transport_from_url(url)


class SmartTCPServer_for_testing_v2_only(SmartTCPServer_for_testing):
    """A variation of SmartTCPServer_for_testing that limits the client to
    using RPCs in protocol v2 (i.e. bzr <= 1.5).
    """

    def get_url(self):
        url = super().get_url()
        url = "bzr-v2://" + url[len("bzr://") :]
        return url


class ReadonlySmartTCPServer_for_testing_v2_only(SmartTCPServer_for_testing_v2_only):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = "readonly+" + backing_transport_server.get_url()
        return transport.get_transport_from_url(url)

# Copyright (C) 2005-2013, 2016 Canonical Ltd
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

"""Tests for mergeable content reading functionality."""

import socketserver

from .. import errors, tests
from ..bzr.tests import test_read_bundle
from ..directory_service import directories
from ..mergeable import read_mergeable_from_url
from . import test_server


class TestReadMergeableFromUrl(tests.TestCaseWithTransport):
    """Tests for reading mergeable content from URLs."""

    def test_read_mergeable_skips_local(self):
        """A local bundle named like the URL should not be read."""
        out, _wt = test_read_bundle.create_bundle_file(self)

        class FooService:
            """A directory service that always returns source."""

            def look_up(self, name, url):
                return "source"

        directories.register("foo:", FooService, "Testing directory service")
        self.addCleanup(directories.remove, "foo:")
        self.build_tree_contents([("./foo:bar", out.getvalue())])
        self.assertRaises(errors.NotABundle, read_mergeable_from_url, "foo:bar")

    def test_infinite_redirects_are_not_a_bundle(self):
        """If a URL causes TooManyRedirections then NotABundle is raised."""
        from .blackbox.test_push import RedirectingMemoryServer

        server = RedirectingMemoryServer()
        self.start_server(server)
        url = server.get_url() + "infinite-loop"
        self.assertRaises(errors.NotABundle, read_mergeable_from_url, url)

    def test_smart_server_connection_reset(self):
        """If a smart server connection fails during the attempt to read a
        bundle, then the ConnectionReset error should be propagated.
        """
        # Instantiate a server that will provoke a ConnectionReset
        sock_server = DisconnectingServer()
        self.start_server(sock_server)
        # We don't really care what the url is since the server will close the
        # connection without interpreting it
        url = sock_server.get_url()
        self.assertRaises(ConnectionResetError, read_mergeable_from_url, url)


class DisconnectingHandler(socketserver.BaseRequestHandler):
    """A request handler that immediately closes any connection made to it."""

    def handle(self):
        """Handle incoming request by immediately closing the connection."""
        self.request.close()


class DisconnectingServer(test_server.TestingTCPServerInAThread):
    """Test server that immediately disconnects clients."""

    def __init__(self):
        """Initialize the disconnecting server."""
        super().__init__(
            ("127.0.0.1", 0), test_server.TestingTCPServer, DisconnectingHandler
        )

    def get_url(self):
        """Return the url of the server."""
        return "bzr://%s:%d/" % self.server.server_address

# Copyright (C) 2007-2010 Canonical Ltd
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

"""Utilities for testing transport connections and hooks."""

import sys

from ..transport import Transport

# SFTPTransport is the only bundled transport that properly counts connections
# at the moment.
from . import TestSkipped, test_sftp_transport


class TestCaseWithConnectionHookedTransport(test_sftp_transport.TestCaseWithSFTPServer):
    """Test case that tracks transport connections using hooks."""

    def setUp(self):
        """Set up the test case with connection tracking."""
        if sys.platform == "win32":
            # The SFTP loopback vendor passes socket.detach() to
            # paramiko's SFTPClient. On Windows the resulting SOCKET
            # handle isn't a usable fd, so the client never completes
            # negotiation and the server thread fails with OSError 87.
            raise TestSkipped("SFTP loopback transport is not functional on Windows")
        super().setUp()
        self.reset_connections()

    def start_logging_connections(self):
        """Start logging transport connections using transport hooks."""
        Transport.hooks.install_named_hook(
            "post_connect", self.connections.append, None
        )

    def reset_connections(self):
        """Reset the connections list to start fresh tracking."""
        self.connections = []

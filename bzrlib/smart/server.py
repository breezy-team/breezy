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

"""Server for smart-server protocol."""

import socket
import os
import threading

from bzrlib.smart import medium
from bzrlib import (
    trace,
    transport,
    urlutils,
)


class SmartTCPServer(object):
    """Listens on a TCP socket and accepts connections from smart clients.
    
    Each connection will be served by a SmartServerSocketStreamMedium running in
    thread.
    """

    def __init__(self, backing_transport, host='127.0.0.1', port=0):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param host: Name of the interface to listen on.
        :param port: TCP port to listen on, or 0 to allocate a transient port.
        """
        self._server_socket = socket.socket()
        self._server_socket.bind((host, port))
        self.port = self._server_socket.getsockname()[1]
        self._server_socket.listen(1)
        self._server_socket.settimeout(1)
        self.backing_transport = backing_transport

    def serve(self):
        # let connections timeout so that we get a chance to terminate
        # Keep a reference to the exceptions we want to catch because the socket
        # module's globals get set to None during interpreter shutdown.
        from socket import timeout as socket_timeout
        from socket import error as socket_error
        self._should_terminate = False
        while not self._should_terminate:
            try:
                self.accept_and_serve()
            except socket_timeout:
                # just check if we're asked to stop
                pass
            except socket_error, e:
                trace.warning("client disconnected: %s", e)
                pass

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._server_socket.getsockname()

    def accept_and_serve(self):
        conn, client_addr = self._server_socket.accept()
        # For WIN32, where the timeout value from the listening socket
        # propogates to the newly accepted socket.
        conn.setblocking(True)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        handler = medium.SmartServerSocketStreamMedium(conn, self.backing_transport)
        connection_thread = threading.Thread(
            None, handler.serve, name='smart-server-child')
        connection_thread.setDaemon(True)
        connection_thread.start()

    def start_background_thread(self):
        self._server_thread = threading.Thread(None,
                self.serve,
                name='server-' + self.get_url())
        self._server_thread.setDaemon(True)
        self._server_thread.start()

    def stop_background_thread(self):
        self._should_terminate = True
        # self._server_socket.close()
        # we used to join the thread, but it's not really necessary; it will
        # terminate in time
        ## self._server_thread.join()



class SmartTCPServer_for_testing(SmartTCPServer):
    """Server suitable for use by transport tests.
    
    This server has a _homedir of the current cwd.
    """

    def __init__(self):
        # The server is set up by default like for inetd access: the backing
        # transport is connected to a local path that is not '/'.
        SmartTCPServer.__init__(self, None)

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        return transport.get_transport('chroot+' + backing_transport_server.get_url())

    def setUp(self, backing_transport_server):
        """Set up server for testing"""
        self.backing_transport = self.get_backing_transport(backing_transport_server)
        self.start_background_thread()

    def tearDown(self):
        self.stop_background_thread()

    def get_url(self):
        """Return the url of the server"""
        host, port = self._server_socket.getsockname()
        return "bzr://%s:%d/" % (host, port)

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class ReadonlySmartTCPServer_for_testing(SmartTCPServer_for_testing):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'chroot+readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)

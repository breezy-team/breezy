# Copyright (C) 2006, 2007 Canonical Ltd
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

import errno
import socket
import threading

from bzrlib.hooks import Hooks
from bzrlib import (
    trace,
    transport,
)
from bzrlib.smart.medium import SmartServerSocketStreamMedium


class SmartTCPServer(object):
    """Listens on a TCP socket and accepts connections from smart clients.

    Each connection will be served by a SmartServerSocketStreamMedium running in
    a thread.

    hooks: An instance of SmartServerHooks.
    """

    def __init__(self, backing_transport, host='127.0.0.1', port=0):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param host: Name of the interface to listen on.
        :param port: TCP port to listen on, or 0 to allocate a transient port.
        """
        # let connections timeout so that we get a chance to terminate
        # Keep a reference to the exceptions we want to catch because the socket
        # module's globals get set to None during interpreter shutdown.
        from socket import timeout as socket_timeout
        from socket import error as socket_error
        self._socket_error = socket_error
        self._socket_timeout = socket_timeout
        self._server_socket = socket.socket()
        self._server_socket.bind((host, port))
        self._sockname = self._server_socket.getsockname()
        self.port = self._sockname[1]
        self._server_socket.listen(1)
        self._server_socket.settimeout(1)
        self.backing_transport = backing_transport
        self._started = threading.Event()
        self._stopped = threading.Event()

    def serve(self):
        self._should_terminate = False
        for hook in SmartTCPServer.hooks['server_started']:
            hook(self.backing_transport.base, self.get_url())
        self._started.set()
        try:
            try:
                while not self._should_terminate:
                    try:
                        conn, client_addr = self._server_socket.accept()
                    except self._socket_timeout:
                        # just check if we're asked to stop
                        pass
                    except self._socket_error, e:
                        # if the socket is closed by stop_background_thread
                        # we might get a EBADF here, any other socket errors
                        # should get logged.
                        if e.args[0] != errno.EBADF:
                            trace.warning("listening socket error: %s", e)
                    else:
                        self.serve_conn(conn)
            except KeyboardInterrupt:
                # dont log when CTRL-C'd.
                raise
            except Exception, e:
                trace.error("Unhandled smart server error.")
                trace.log_exception_quietly()
                raise
        finally:
            self._stopped.set()
            try:
                # ensure the server socket is closed.
                self._server_socket.close()
            except self._socket_error:
                # ignore errors on close
                pass
            for hook in SmartTCPServer.hooks['server_stopped']:
                hook(self.backing_transport.base, self.get_url())

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._sockname

    def serve_conn(self, conn):
        # For WIN32, where the timeout value from the listening socket
        # propogates to the newly accepted socket.
        conn.setblocking(True)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        handler = SmartServerSocketStreamMedium(conn, self.backing_transport)
        connection_thread = threading.Thread(None, handler.serve, name='smart-server-child')
        connection_thread.setDaemon(True)
        connection_thread.start()

    def start_background_thread(self):
        self._started.clear()
        self._server_thread = threading.Thread(None,
                self.serve,
                name='server-' + self.get_url())
        self._server_thread.setDaemon(True)
        self._server_thread.start()
        self._started.wait()

    def stop_background_thread(self):
        self._stopped.clear()
        # tell the main loop to quit on the next iteration.
        self._should_terminate = True
        # close the socket - gives error to connections from here on in,
        # rather than a connection reset error to connections made during
        # the period between setting _should_terminate = True and 
        # the current request completing/aborting. It may also break out the
        # main loop if it was currently in accept() (on some platforms).
        try:
            self._server_socket.close()
        except self._socket_error:
            # ignore errors on close
            pass
        if not self._stopped.isSet():
            # server has not stopped (though it may be stopping)
            # its likely in accept(), so give it a connection
            temp_socket = socket.socket()
            temp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if not temp_socket.connect_ex(self._sockname):
                # and close it immediately: we dont choose to send any requests.
                temp_socket.close()
        self._stopped.wait()
        self._server_thread.join()


class SmartServerHooks(Hooks):
    """Hooks for the smart server."""

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        Hooks.__init__(self)
        # Introduced in 0.16:
        # invoked whenever the server starts serving a directory.
        # The api signature is (backing url, public url).
        self['server_started'] = []
        # Introduced in 0.16:
        # invoked whenever the server stops serving a directory.
        # The api signature is (backing url, public url).
        self['server_stopped'] = []

SmartTCPServer.hooks = SmartServerHooks()


class SmartTCPServer_for_testing(SmartTCPServer):
    """Server suitable for use by transport tests.
    
    This server is backed by the process's cwd.
    """

    def __init__(self):
        SmartTCPServer.__init__(self, None)
        
    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        return transport.get_transport(backing_transport_server.get_url())

    def setUp(self, backing_transport_server=None):
        """Set up server for testing"""
        from bzrlib.transport.chroot import ChrootServer
        if backing_transport_server is None:
            from bzrlib.transport.local import LocalURLServer
            backing_transport_server = LocalURLServer()
        self.chroot_server = ChrootServer(
            self.get_backing_transport(backing_transport_server))
        self.chroot_server.setUp()
        self.backing_transport = transport.get_transport(
            self.chroot_server.get_url())
        self.start_background_thread()

    def tearDown(self):
        self.stop_background_thread()
        self.chroot_server.tearDown()

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class ReadonlySmartTCPServer_for_testing(SmartTCPServer_for_testing):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)


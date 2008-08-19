# Copyright (C) 2006, 2007, 2008 Canonical Ltd
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
import sys
import threading

from bzrlib.hooks import Hooks
from bzrlib import (
    errors,
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

    def __init__(self, backing_transport, host='127.0.0.1', port=0,
                 root_client_path='/'):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param backing_transport: The transport to serve.
        :param host: Name of the interface to listen on.
        :param port: TCP port to listen on, or 0 to allocate a transient port.
        :param root_client_path: The client path that will correspond to root
            of backing_transport.
        """
        # let connections timeout so that we get a chance to terminate
        # Keep a reference to the exceptions we want to catch because the socket
        # module's globals get set to None during interpreter shutdown.
        from socket import timeout as socket_timeout
        from socket import error as socket_error
        self._socket_error = socket_error
        self._socket_timeout = socket_timeout
        self._server_socket = socket.socket()
        # SO_REUSERADDR has a different meaning on Windows
        if sys.platform != 'win32':
            self._server_socket.setsockopt(socket.SOL_SOCKET,
                socket.SO_REUSEADDR, 1)
        try:
            self._server_socket.bind((host, port))
        except self._socket_error, message:
            raise errors.CannotBindAddress(host, port, message)
        self._sockname = self._server_socket.getsockname()
        self.port = self._sockname[1]
        self._server_socket.listen(1)
        self._server_socket.settimeout(1)
        self.backing_transport = backing_transport
        self._started = threading.Event()
        self._stopped = threading.Event()
        self.root_client_path = root_client_path

    def serve(self, thread_name_suffix=''):
        self._should_terminate = False
        # for hooks we are letting code know that a server has started (and
        # later stopped).
        # There are three interesting urls:
        # The URL the server can be contacted on. (e.g. bzr://host/)
        # The URL that a commit done on the same machine as the server will
        # have within the servers space. (e.g. file:///home/user/source)
        # The URL that will be given to other hooks in the same process -
        # the URL of the backing transport itself. (e.g. chroot+:///)
        # We need all three because:
        #  * other machines see the first
        #  * local commits on this machine should be able to be mapped to
        #    this server 
        #  * commits the server does itself need to be mapped across to this
        #    server.
        # The latter two urls are different aliases to the servers url,
        # so we group those in a list - as there might be more aliases 
        # in the future.
        backing_urls = [self.backing_transport.base]
        try:
            backing_urls.append(self.backing_transport.external_url())
        except errors.InProcessTransport:
            pass
        for hook in SmartTCPServer.hooks['server_started']:
            hook(backing_urls, self.get_url())
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
                        self.serve_conn(conn, thread_name_suffix)
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
                hook(backing_urls, self.get_url())

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._sockname

    def serve_conn(self, conn, thread_name_suffix):
        # For WIN32, where the timeout value from the listening socket
        # propogates to the newly accepted socket.
        conn.setblocking(True)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        handler = SmartServerSocketStreamMedium(
            conn, self.backing_transport, self.root_client_path)
        thread_name = 'smart-server-child' + thread_name_suffix
        connection_thread = threading.Thread(
            None, handler.serve, name=thread_name)
        connection_thread.setDaemon(True)
        connection_thread.start()

    def start_background_thread(self, thread_name_suffix=''):
        self._started.clear()
        self._server_thread = threading.Thread(None,
                self.serve, args=(thread_name_suffix,),
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
        # The api signature is (backing urls, public url).
        self['server_started'] = []
        # Introduced in 0.16:
        # invoked whenever the server stops serving a directory.
        # The api signature is (backing urls, public url).
        self['server_stopped'] = []

SmartTCPServer.hooks = SmartServerHooks()


class SmartTCPServer_for_testing(SmartTCPServer):
    """Server suitable for use by transport tests.
    
    This server is backed by the process's cwd.
    """

    def __init__(self, thread_name_suffix=''):
        SmartTCPServer.__init__(self, None)
        self.client_path_extra = None
        self.thread_name_suffix = thread_name_suffix
        
    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        return transport.get_transport(backing_transport_server.get_url())

    def setUp(self, backing_transport_server=None,
              client_path_extra='/extra/'):
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
        if not client_path_extra.startswith('/'):
            raise ValueError(client_path_extra)
        from bzrlib.transport.chroot import ChrootServer
        if backing_transport_server is None:
            from bzrlib.transport.local import LocalURLServer
            backing_transport_server = LocalURLServer()
        self.chroot_server = ChrootServer(
            self.get_backing_transport(backing_transport_server))
        self.chroot_server.setUp()
        self.backing_transport = transport.get_transport(
            self.chroot_server.get_url())
        self.root_client_path = self.client_path_extra = client_path_extra
        self.start_background_thread(self.thread_name_suffix)

    def tearDown(self):
        self.stop_background_thread()
        self.chroot_server.tearDown()

    def get_url(self):
        url = super(SmartTCPServer_for_testing, self).get_url()
        return url[:-1] + self.client_path_extra

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class ReadonlySmartTCPServer_for_testing(SmartTCPServer_for_testing):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)


class SmartTCPServer_for_testing_v2_only(SmartTCPServer_for_testing):
    """A variation of SmartTCPServer_for_testing that limits the client to
    using RPCs in protocol v2 (i.e. bzr <= 1.5).
    """

    def get_url(self):
        url = super(SmartTCPServer_for_testing_v2_only, self).get_url()
        url = 'bzr-v2://' + url[len('bzr://'):]
        return url


class ReadonlySmartTCPServer_for_testing_v2_only(SmartTCPServer_for_testing_v2_only):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)



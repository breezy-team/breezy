# Copyright (C) 2010 Canonical Ltd
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

import socket
import select


from bzrlib import (
    transport,
    urlutils,
    )
from bzrlib.transport import (
    chroot,
    pathfilter,
    )
from bzrlib.smart import server


class TestServer(transport.Server):
    """A Transport Server dedicated to tests.

    The TestServer interface provides a server for a given transport. We use
    these servers as loopback testing tools. For any given transport the
    Servers it provides must either allow writing, or serve the contents
    of os.getcwdu() at the time start_server is called.

    Note that these are real servers - they must implement all the things
    that we want bzr transports to take advantage of.
    """

    def get_url(self):
        """Return a url for this server.

        If the transport does not represent a disk directory (i.e. it is
        a database like svn, or a memory only transport, it should return
        a connection to a newly established resource for this Server.
        Otherwise it should return a url that will provide access to the path
        that was os.getcwdu() when start_server() was called.

        Subsequent calls will return the same resource.
        """
        raise NotImplementedError

    def get_bogus_url(self):
        """Return a url for this protocol, that will fail to connect.

        This may raise NotImplementedError to indicate that this server cannot
        provide bogus urls.
        """
        raise NotImplementedError


class LocalURLServer(TestServer):
    """A pretend server for local transports, using file:// urls.

    Of course no actual server is required to access the local filesystem, so
    this just exists to tell the test code how to get to it.
    """

    def start_server(self):
        pass

    def get_url(self):
        """See Transport.Server.get_url."""
        return urlutils.local_path_to_url('')


class DecoratorServer(TestServer):
    """Server for the TransportDecorator for testing with.

    To use this when subclassing TransportDecorator, override override the
    get_decorator_class method.
    """

    def start_server(self, server=None):
        """See bzrlib.transport.Server.start_server.

        :server: decorate the urls given by server. If not provided a
        LocalServer is created.
        """
        if server is not None:
            self._made_server = False
            self._server = server
        else:
            self._made_server = True
            self._server = LocalURLServer()
            self._server.start_server()

    def stop_server(self):
        if self._made_server:
            self._server.stop_server()

    def get_decorator_class(self):
        """Return the class of the decorators we should be constructing."""
        raise NotImplementedError(self.get_decorator_class)

    def get_url_prefix(self):
        """What URL prefix does this decorator produce?"""
        return self.get_decorator_class()._get_url_prefix()

    def get_bogus_url(self):
        """See bzrlib.transport.Server.get_bogus_url."""
        return self.get_url_prefix() + self._server.get_bogus_url()

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self.get_url_prefix() + self._server.get_url()


class BrokenRenameServer(DecoratorServer):
    """Server for the BrokenRenameTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import brokenrename
        return brokenrename.BrokenRenameTransportDecorator


class FakeNFSServer(DecoratorServer):
    """Server for the FakeNFSTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import fakenfs
        return fakenfs.FakeNFSTransportDecorator


class FakeVFATServer(DecoratorServer):
    """A server that suggests connections through FakeVFATTransportDecorator

    For use in testing.
    """

    def get_decorator_class(self):
        from bzrlib.transport import fakevfat
        return fakevfat.FakeVFATTransportDecorator


class LogDecoratorServer(DecoratorServer):
    """Server for testing."""

    def get_decorator_class(self):
        from bzrlib.transport import log
        return log.TransportLogDecorator


class NoSmartTransportServer(DecoratorServer):
    """Server for the NoSmartTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import nosmart
        return nosmart.NoSmartTransportDecorator


class ReadonlyServer(DecoratorServer):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import readonly
        return readonly.ReadonlyTransportDecorator


class TraceServer(DecoratorServer):
    """Server for the TransportTraceDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import trace
        return trace.TransportTraceDecorator


class UnlistableServer(DecoratorServer):
    """Server for the UnlistableTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import unlistable
        return unlistable.UnlistableTransportDecorator


class TestingPathFilteringServer(pathfilter.PathFilteringServer):

    def __init__(self):
        """TestingPathFilteringServer is not usable until start_server
        is called."""

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = transport.get_transport(
                backing_server.get_url())
        else:
            self.backing_transport = transport.get_transport('.')
        self.backing_transport.clone('added-by-filter').ensure_base()
        self.filter_func = lambda x: 'added-by-filter/' + x
        super(TestingPathFilteringServer, self).start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class TestingChrootServer(chroot.ChrootServer):

    def __init__(self):
        """TestingChrootServer is not usable until start_server is called."""
        super(TestingChrootServer, self).__init__(None)

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = transport.get_transport(
                backing_server.get_url())
        else:
            self.backing_transport = transport.get_transport('.')
        super(TestingChrootServer, self).start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class SmartTCPServer_for_testing(server.SmartTCPServer):
    """Server suitable for use by transport tests.

    This server is backed by the process's cwd.
    """

    def __init__(self, thread_name_suffix=''):
        super(SmartTCPServer_for_testing, self).__init__(None)
        self.client_path_extra = None
        self.thread_name_suffix = thread_name_suffix
        # We collect the sockets/threads used by the clients so we can
        # close/join them when shutting down
        self.clients = []

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        return transport.get_transport(backing_transport_server.get_url())

    def start_server(self, backing_transport_server=None,
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
            backing_transport_server = LocalURLServer()
        self.chroot_server = ChrootServer(
            self.get_backing_transport(backing_transport_server))
        self.chroot_server.start_server()
        self.backing_transport = transport.get_transport(
            self.chroot_server.get_url())
        self.root_client_path = self.client_path_extra = client_path_extra
        self.start_background_thread(self.thread_name_suffix)

    def serve_conn(self, conn, thread_name_suffix):
        conn_thread = super(SmartTCPServer_for_testing, self).serve_conn(
            conn, thread_name_suffix)
        self.clients.append((conn, conn_thread))
        return conn_thread

    def shutdown_client(self, client_socket):
        """Properly shutdown a client socket.

        Under some circumstances (as in bug #383920), we need to force the
        shutdown as python delays it until gc occur otherwise and the client
        may hang.

        This should be called only when no other thread is trying to use the
        socket.
        """
        try:
            # The request process has been completed, the thread is about to
            # die, let's shutdown the socket if we can.
            client_socket.shutdown(socket.SHUT_RDWR)
        except (socket.error, select.error), e:
            if e[0] in (errno.EBADF, errno.ENOTCONN):
                # Right, the socket is already down
                pass
            else:
                raise

    def stop_server(self):
        self.stop_background_thread()
        # Let's close all our pending clients too
        for sock, thread in self.clients:
            self.shutdown_client(sock)
            thread.join()
            del thread
        self.clients = []
        self.chroot_server.stop_server()

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


class ReadonlySmartTCPServer_for_testing_v2_only(
    SmartTCPServer_for_testing_v2_only):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)





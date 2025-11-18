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

import errno
import socket
import socketserver
import sys
import threading

from breezy import cethread, errors, osutils, transport, urlutils
from breezy.bzr.smart import medium, server
from breezy.transport import chroot, pathfilter


def debug_threads():
    # FIXME: There is a dependency loop between breezy.tests and
    # breezy.tests.test_server that needs to be fixed. In the mean time
    # defining this function is enough for our needs. -- vila 20100611
    from breezy import tests

    return "threads" in tests.selftest_debug_flags


class TestServer(transport.Server):
    """A Transport Server dedicated to tests.

    The TestServer interface provides a server for a given transport. We use
    these servers as loopback testing tools. For any given transport the
    Servers it provides must either allow writing, or serve the contents
    of osutils.getcwd() at the time start_server is called.

    Note that these are real servers - they must implement all the things
    that we want bzr transports to take advantage of.
    """

    def get_url(self):
        """Return a url for this server.

        If the transport does not represent a disk directory (i.e. it is
        a database like svn, or a memory only transport, it should return
        a connection to a newly established resource for this Server.
        Otherwise it should return a url that will provide access to the path
        that was osutils.getcwd() when start_server() was called.

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
        return urlutils.local_path_to_url("")


class DecoratorServer(TestServer):
    """Server for the TransportDecorator for testing with.

    To use this when subclassing TransportDecorator, override override the
    get_decorator_class method.
    """

    def start_server(self, server=None):
        """See breezy.transport.Server.start_server.

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
        """See breezy.transport.Server.get_bogus_url."""
        return self.get_url_prefix() + self._server.get_bogus_url()

    def get_url(self):
        """See breezy.transport.Server.get_url."""
        return self.get_url_prefix() + self._server.get_url()


class BrokenRenameServer(DecoratorServer):
    """Server for the BrokenRenameTransportDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import brokenrename

        return brokenrename.BrokenRenameTransportDecorator


class FakeNFSServer(DecoratorServer):
    """Server for the FakeNFSTransportDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import fakenfs

        return fakenfs.FakeNFSTransportDecorator


class FakeVFATServer(DecoratorServer):
    """A server that suggests connections through FakeVFATTransportDecorator.

    For use in testing.
    """

    def get_decorator_class(self):
        from breezy.transport import fakevfat

        return fakevfat.FakeVFATTransportDecorator


class LogDecoratorServer(DecoratorServer):
    """Server for testing."""

    def get_decorator_class(self):
        from breezy.transport import log

        return log.TransportLogDecorator


class NoSmartTransportServer(DecoratorServer):
    """Server for the NoSmartTransportDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import nosmart

        return nosmart.NoSmartTransportDecorator


class ReadonlyServer(DecoratorServer):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import readonly

        return readonly.ReadonlyTransportDecorator


class TraceServer(DecoratorServer):
    """Server for the TransportTraceDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import trace

        return trace.TransportTraceDecorator


class UnlistableServer(DecoratorServer):
    """Server for the UnlistableTransportDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import unlistable

        return unlistable.UnlistableTransportDecorator


class TestingPathFilteringServer(pathfilter.PathFilteringServer):
    def __init__(self):
        """TestingPathFilteringServer is not usable until start_server
        is called.
        """

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = transport.get_transport_from_url(
                backing_server.get_url()
            )
        else:
            self.backing_transport = transport.get_transport_from_path(".")
        self.backing_transport.clone("added-by-filter").ensure_base()
        self.filter_func = lambda x: "added-by-filter/" + x
        super().start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class TestingChrootServer(chroot.ChrootServer):
    def __init__(self):
        """TestingChrootServer is not usable until start_server is called."""
        super().__init__(None)

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = transport.get_transport_from_url(
                backing_server.get_url()
            )
        else:
            self.backing_transport = transport.get_transport_from_path(".")
        super().start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class TestThread(cethread.CatchingExceptionThread):
    def join(self, timeout=5):
        """Overrides to use a default timeout.

        The default timeout is set to 5 and should expire only when a thread
        serving a client connection is hung.
        """
        super().join(timeout)
        if timeout and self.is_alive():
            # The timeout expired without joining the thread, the thread is
            # therefore stucked and that's a failure as far as the test is
            # concerned. We used to hang here.

            # FIXME: we need to kill the thread, but as far as the test is
            # concerned, raising an assertion is too strong. On most of the
            # platforms, this doesn't occur, so just mentioning the problem is
            # enough for now -- vila 2010824
            sys.stderr.write("thread {} hung\n".format(self.name))
            # raise AssertionError('thread %s hung' % (self.name,))


class TestingTCPServerMixin:
    """Mixin to support running socketserver.TCPServer in a thread.

    Tests are connecting from the main thread, the server has to be run in a
    separate thread.
    """

    def __init__(self):
        self.started = threading.Event()
        self.serving = None
        self.stopped = threading.Event()
        # We collect the resources used by the clients so we can release them
        # when shutting down
        self.clients = []
        self.ignored_exceptions = None

    def server_bind(self):
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def serve(self):
        self.serving = True
        # We are listening and ready to accept connections
        self.started.set()
        try:
            while self.serving:
                # Really a connection but the python framework is generic and
                # call them requests
                self.handle_request()
            # Let's close the listening socket
            self.server_close()
        finally:
            self.stopped.set()

    def handle_request(self):
        """Handle one request.

        The python version swallows some socket exceptions and we don't use
        timeout, so we override it to better control the server behavior.
        """
        request, client_address = self.get_request()
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except BaseException:
                self.handle_error(request, client_address)
        else:
            self.close_request(request)

    def get_request(self):
        return self.socket.accept()

    def verify_request(self, request, client_address):
        """Verify the request.

        Return True if we should proceed with this request, False if we should
        not even touch a single byte in the socket ! This is useful when we
        stop the server with a dummy last connection.
        """
        return self.serving

    def handle_error(self, request, client_address):
        # Stop serving and re-raise the last exception seen
        self.serving = False
        # The following can be used for debugging purposes, it will display the
        # exception and the traceback just when it occurs instead of waiting
        # for the thread to be joined.
        # socketserver.BaseServer.handle_error(self, request, client_address)

        # We call close_request manually, because we are going to raise an
        # exception. The socketserver implementation calls:
        #   handle_error(...)
        #   close_request(...)
        # But because we raise the exception, close_request will never be
        # triggered. This helps client not block waiting for a response when
        # the server gets an exception.
        self.close_request(request)
        raise

    def ignored_exceptions_during_shutdown(self, e):
        if sys.platform == "win32":
            accepted_errnos = [
                errno.EBADF,
                errno.EPIPE,
                errno.WSAEBADF,
                errno.WSAENOTSOCK,
                errno.WSAECONNRESET,
                errno.WSAENOTCONN,
                errno.WSAESHUTDOWN,
            ]
        else:
            accepted_errnos = [
                errno.EBADF,
                errno.ECONNRESET,
                errno.ENOTCONN,
                errno.EPIPE,
            ]
        return bool(isinstance(e, socket.error) and e.errno in accepted_errnos)

    # The following methods are called by the main thread

    def stop_client_connections(self):
        while self.clients:
            c = self.clients.pop()
            self.shutdown_client(c)

    def shutdown_socket(self, sock):
        """Properly shutdown a socket.

        This should be called only when no other thread is trying to use the
        socket.
        """
        try:
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        except Exception as e:
            if self.ignored_exceptions(e):
                pass
            else:
                raise

    # The following methods are called by the main thread

    def set_ignored_exceptions(self, thread, ignored_exceptions):
        self.ignored_exceptions = ignored_exceptions
        thread.set_ignored_exceptions(self.ignored_exceptions)

    def _pending_exception(self, thread):
        """Raise server uncaught exception.

        Daughter classes can override this if they use daughter threads.
        """
        thread.pending_exception()


class TestingTCPServer(TestingTCPServerMixin, socketserver.TCPServer):
    def __init__(self, server_address, request_handler_class):
        TestingTCPServerMixin.__init__(self)
        socketserver.TCPServer.__init__(self, server_address, request_handler_class)

    def get_request(self):
        """Get the request and client address from the socket."""
        sock, addr = TestingTCPServerMixin.get_request(self)
        self.clients.append((sock, addr))
        return sock, addr

    # The following methods are called by the main thread

    def shutdown_client(self, client):
        sock, _addr = client
        self.shutdown_socket(sock)


class TestingThreadingTCPServer(TestingTCPServerMixin, socketserver.ThreadingTCPServer):
    def __init__(self, server_address, request_handler_class):
        TestingTCPServerMixin.__init__(self)
        socketserver.ThreadingTCPServer.__init__(
            self, server_address, request_handler_class
        )

    def get_request(self):
        """Get the request and client address from the socket."""
        sock, addr = TestingTCPServerMixin.get_request(self)
        # The thread is not created yet, it will be updated in process_request
        self.clients.append((sock, addr, None))
        return sock, addr

    def process_request_thread(
        self, started, detached, stopped, request, client_address
    ):
        started.set()
        # We will be on our own once the server tells us we're detached
        detached.wait()
        socketserver.ThreadingTCPServer.process_request_thread(
            self, request, client_address
        )
        self.close_request(request)
        stopped.set()

    def process_request(self, request, client_address):
        """Start a new thread to process the request."""
        started = threading.Event()
        detached = threading.Event()
        stopped = threading.Event()
        t = TestThread(
            sync_event=stopped,
            name="{} -> {}".format(client_address, self.server_address),
            target=self.process_request_thread,
            args=(started, detached, stopped, request, client_address),
        )
        # Update the client description
        self.clients.pop()
        self.clients.append((request, client_address, t))
        # Propagate the exception handler since we must use the same one as
        # TestingTCPServer for connections running in their own threads.
        t.set_ignored_exceptions(self.ignored_exceptions)
        t.start()
        started.wait()
        # If an exception occured during the thread start, it will get raised.
        t.pending_exception()
        if debug_threads():
            sys.stderr.write("Client thread {} started\n".format(t.name))
        # Tell the thread, it's now on its own for exception handling.
        detached.set()

    # The following methods are called by the main thread

    def shutdown_client(self, client):
        sock, _addr, connection_thread = client
        self.shutdown_socket(sock)
        if connection_thread is not None:
            # The thread has been created only if the request is processed but
            # after the connection is inited. This could happen during server
            # shutdown. If an exception occurred in the thread it will be
            # re-raised
            if debug_threads():
                sys.stderr.write(
                    "Client thread {} will be joined\n".format(connection_thread.name)
                )
            connection_thread.join()

    def set_ignored_exceptions(self, thread, ignored_exceptions):
        TestingTCPServerMixin.set_ignored_exceptions(self, thread, ignored_exceptions)
        for _sock, _addr, connection_thread in self.clients:
            if connection_thread is not None:
                connection_thread.set_ignored_exceptions(self.ignored_exceptions)

    def _pending_exception(self, thread):
        for _sock, _addr, connection_thread in self.clients:
            if connection_thread is not None:
                connection_thread.pending_exception()
        TestingTCPServerMixin._pending_exception(self, thread)


class TestingTCPServerInAThread(transport.Server):
    """A server in a thread that re-raise thread exceptions."""

    def __init__(self, server_address, server_class, request_handler_class):
        self.server_class = server_class
        self.request_handler_class = request_handler_class
        self.host, self.port = server_address
        self.server = None
        self._server_thread = None

    def __repr__(self):
        return "{}({}:{})".format(self.__class__.__name__, self.host, self.port)

    def create_server(self):
        return self.server_class((self.host, self.port), self.request_handler_class)

    def start_server(self):
        self.server = self.create_server()
        self._server_thread = TestThread(
            sync_event=self.server.started, target=self.run_server
        )
        self._server_thread.start()
        # Wait for the server thread to start (i.e. release the lock)
        self.server.started.wait()
        # Get the real address, especially the port
        self.host, self.port = self.server.server_address
        self._server_thread.name = self.server.server_address
        if debug_threads():
            sys.stderr.write(
                "Server thread {} started\n".format(self._server_thread.name)
            )
        # If an exception occured during the server start, it will get raised,
        # otherwise, the server is blocked on its accept() call.
        self._server_thread.pending_exception()
        # From now on, we'll use a different event to ensure the server can set
        # its exception
        self._server_thread.set_sync_event(self.server.stopped)

    def run_server(self):
        self.server.serve()

    def stop_server(self):
        if self.server is None:
            return
        try:
            # The server has been started successfully, shut it down now.  As
            # soon as we stop serving, no more connection are accepted except
            # one to get out of the blocking listen.
            self.set_ignored_exceptions(self.server.ignored_exceptions_during_shutdown)
            self.server.serving = False
            if debug_threads():
                sys.stderr.write(
                    "Server thread {} will be joined\n".format(self._server_thread.name)
                )
            # The server is listening for a last connection, let's give it:
            last_conn = None
            try:
                last_conn = osutils.connect_socket((self.host, self.port))
            except OSError:
                # But ignore connection errors as the point is to unblock the
                # server thread, it may happen that it's not blocked or even
                # not started.
                pass
            # We start shutting down the clients while the server itself is
            # shutting down.
            self.server.stop_client_connections()
            # Now we wait for the thread running self.server.serve() to finish
            self.server.stopped.wait()
            if last_conn is not None:
                # Close the last connection without trying to use it. The
                # server will not process a single byte on that socket to avoid
                # complications (SSL starts with a handshake for example).
                last_conn.close()
            # Check for any exception that could have occurred in the server
            # thread
            try:
                self._server_thread.join()
            except Exception as e:
                if self.server.ignored_exceptions(e):
                    pass
                else:
                    raise
        finally:
            # Make sure we can be called twice safely, note that this means
            # that we will raise a single exception even if several occurred in
            # the various threads involved.
            self.server = None

    def set_ignored_exceptions(self, ignored_exceptions):
        """Install an exception handler for the server."""
        self.server.set_ignored_exceptions(self._server_thread, ignored_exceptions)

    def pending_exception(self):
        """Raise uncaught exception in the server."""
        self.server._pending_exception(self._server_thread)


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
        from breezy.transport.chroot import ChrootServer

        if backing_transport_server is None:
            backing_transport_server = LocalURLServer()
        self.chroot_server = ChrootServer(
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

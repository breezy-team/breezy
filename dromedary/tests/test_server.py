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

"""Test server implementations for transport decorators and TCP testing."""

import errno
import socket
import socketserver
import sys
import threading

import dromedary
from dromedary import chroot, pathfilter, urlutils
from dromedary.cethread import CatchingExceptionThread


def connect_socket(address):
    """Connect to the given address, trying all results from getaddrinfo."""
    err = socket.error("getaddrinfo returns an empty list")
    host, port = address
    for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, socktype, proto, _canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            sock.connect(sa)
            return sock
        except OSError as e:
            err = e
            if sock is not None:
                sock.close()
    raise err


# Set by test frameworks to enable debug output for thread operations.
debug_threads_hook = None


def debug_threads():
    """Return True if thread debugging is enabled."""
    if debug_threads_hook is not None:
        return debug_threads_hook()
    return False


class TestServer(dromedary.Server):
    """A Transport Server dedicated to tests.

    The TestServer interface provides a server for a given transport. We use
    these servers as loopback testing tools. For any given transport the
    Servers it provides must either allow writing, or serve the contents
    of osutils.getcwd() at the time start_server is called.

    Note that these are real servers - they must implement all the things
    that we want bzr transports to take advantage of.
    """

    def get_url(self):
        """Return a url for this server."""
        raise NotImplementedError

    def get_bogus_url(self):
        """Return a url for this protocol, that will fail to connect."""
        raise NotImplementedError


class LocalURLServer(TestServer):
    """A pretend server for local transports, using file:// urls."""

    def start_server(self):
        pass

    def get_url(self):
        return urlutils.local_path_to_url("")


class DecoratorServer(TestServer):
    """Server for the TransportDecorator for testing with."""

    def start_server(self, server=None):
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
        raise NotImplementedError(self.get_decorator_class)

    def get_url_prefix(self):
        return self.get_decorator_class()._get_url_prefix()

    def get_bogus_url(self):
        return self.get_url_prefix() + self._server.get_bogus_url()

    def get_url(self):
        return self.get_url_prefix() + self._server.get_url()


class BrokenRenameServer(DecoratorServer):
    """Server for the BrokenRenameTransportDecorator for testing with."""

    def get_decorator_class(self):
        from dromedary import brokenrename

        return brokenrename.BrokenRenameTransportDecorator


class FakeNFSServer(DecoratorServer):
    """Server for the FakeNFSTransportDecorator for testing with."""

    def get_decorator_class(self):
        from dromedary import fakenfs

        return fakenfs.FakeNFSTransportDecorator


class FakeVFATServer(DecoratorServer):
    """A server that suggests connections through FakeVFATTransportDecorator."""

    def get_decorator_class(self):
        from dromedary import fakevfat

        return fakevfat.FakeVFATTransportDecorator


class LogDecoratorServer(DecoratorServer):
    """Server for testing."""

    def get_decorator_class(self):
        from dromedary import log

        return log.TransportLogDecorator


class NoSmartTransportServer(DecoratorServer):
    """Server for the NoSmartTransportDecorator for testing with."""

    def get_decorator_class(self):
        from breezy.transport import nosmart

        return nosmart.NoSmartTransportDecorator


class ReadonlyServer(DecoratorServer):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def get_decorator_class(self):
        from dromedary import readonly

        return readonly.ReadonlyTransportDecorator


class TraceServer(DecoratorServer):
    """Server for the TransportTraceDecorator for testing with."""

    def get_decorator_class(self):
        from dromedary import trace

        return trace.TransportTraceDecorator


class UnlistableServer(DecoratorServer):
    """Server for the UnlistableTransportDecorator for testing with."""

    def get_decorator_class(self):
        from dromedary import unlistable

        return unlistable.UnlistableTransportDecorator


class TestingPathFilteringServer(pathfilter.PathFilteringServer):
    def __init__(self):
        """TestingPathFilteringServer is not usable until start_server
        is called.
        """

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = dromedary.get_transport_from_url(
                backing_server.get_url()
            )
        else:
            self.backing_transport = dromedary.get_transport_from_path(".")
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
            self.backing_transport = dromedary.get_transport_from_url(
                backing_server.get_url()
            )
        else:
            self.backing_transport = dromedary.get_transport_from_path(".")
        super().start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class TestThread(CatchingExceptionThread):
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
            sys.stderr.write(f"thread {self.name} hung\n")


class TestingTCPServerMixin:
    """Mixin to support running socketserver.TCPServer in a thread.

    Tests are connecting from the main thread, the server has to be run in a
    separate thread.
    """

    def __init__(self):
        self.started = threading.Event()
        self.serving = None
        self.stopped = threading.Event()
        self.clients = []
        self.ignored_exceptions = None

    def server_bind(self):
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def serve(self):
        self.serving = True
        self.started.set()
        try:
            while self.serving:
                self.handle_request()
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
        self.clients.append((sock, addr, None))
        return sock, addr

    def process_request_thread(
        self, started, detached, stopped, request, client_address
    ):
        started.set()
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
            name=f"{client_address} -> {self.server_address}",
            target=self.process_request_thread,
            args=(started, detached, stopped, request, client_address),
        )
        self.clients.pop()
        self.clients.append((request, client_address, t))
        t.set_ignored_exceptions(self.ignored_exceptions)
        t.start()
        started.wait()
        t.pending_exception()
        if debug_threads():
            sys.stderr.write(f"Client thread {t.name} started\n")
        detached.set()

    def shutdown_client(self, client):
        sock, _addr, connection_thread = client
        self.shutdown_socket(sock)
        if connection_thread is not None:
            if debug_threads():
                sys.stderr.write(
                    f"Client thread {connection_thread.name} will be joined\n"
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


class TestingTCPServerInAThread(dromedary.Server):
    """A server in a thread that re-raise thread exceptions."""

    def __init__(self, server_address, server_class, request_handler_class):
        self.server_class = server_class
        self.request_handler_class = request_handler_class
        self.host, self.port = server_address
        self.server = None
        self._server_thread = None

    def __repr__(self):
        return f"{self.__class__.__name__}({self.host}:{self.port})"

    def create_server(self):
        return self.server_class((self.host, self.port), self.request_handler_class)

    def start_server(self):
        self.server = self.create_server()
        self._server_thread = TestThread(
            sync_event=self.server.started, target=self.run_server
        )
        self._server_thread.start()
        self.server.started.wait()
        self.host, self.port = self.server.server_address
        self._server_thread.name = self.server.server_address
        if debug_threads():
            sys.stderr.write(f"Server thread {self._server_thread.name} started\n")
        self._server_thread.pending_exception()
        self._server_thread.set_sync_event(self.server.stopped)

    def run_server(self):
        self.server.serve()

    def stop_server(self):
        if self.server is None:
            return
        try:
            self.set_ignored_exceptions(self.server.ignored_exceptions_during_shutdown)
            self.server.serving = False
            if debug_threads():
                sys.stderr.write(
                    f"Server thread {self._server_thread.name} will be joined\n"
                )
            last_conn = None
            try:
                last_conn = connect_socket((self.host, self.port))
            except OSError:
                pass
            self.server.stop_client_connections()
            self.server.stopped.wait()
            if last_conn is not None:
                last_conn.close()
            try:
                self._server_thread.join()
            except Exception as e:
                if self.server.ignored_exceptions(e):
                    pass
                else:
                    raise
        finally:
            self.server = None

    def set_ignored_exceptions(self, ignored_exceptions):
        """Install an exception handler for the server."""
        self.server.set_ignored_exceptions(self._server_thread, ignored_exceptions)

    def pending_exception(self):
        """Raise uncaught exception in the server."""
        self.server._pending_exception(self._server_thread)

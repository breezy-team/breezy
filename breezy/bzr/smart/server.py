# Copyright (C) 2006-2011 Canonical Ltd
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

"""Server for smart-server protocol."""

import errno
import os.path
import socket
import sys
import time
import threading

from ...hooks import Hooks
from ... import (
    errors,
    trace,
    transport as _mod_transport,
)
from ...i18n import gettext
from ...lazy_import import lazy_import
lazy_import(globals(), """
from breezy.bzr.smart import (
    medium,
    signals,
    )
from breezy.transport import (
    chroot,
    pathfilter,
    )
from breezy import (
    config,
    urlutils,
    )
""")


class SmartTCPServer(object):
    """Listens on a TCP socket and accepts connections from smart clients.

    Each connection will be served by a SmartServerSocketStreamMedium running in
    a thread.

    hooks: An instance of SmartServerHooks.
    """

    # This is the timeout on the socket we use .accept() on. It is exposed here
    # so the test suite can set it faster. (It thread.interrupt_main() will not
    # fire a KeyboardInterrupt during socket.accept)
    _ACCEPT_TIMEOUT = 1.0
    _SHUTDOWN_POLL_TIMEOUT = 1.0
    _LOG_WAITING_TIMEOUT = 10.0

    _timer = time.time

    def __init__(self, backing_transport, root_client_path='/',
                 client_timeout=None):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param backing_transport: The transport to serve.
        :param root_client_path: The client path that will correspond to root
            of backing_transport.
        :param client_timeout: See SmartServerSocketStreamMedium's timeout
            parameter.
        """
        self.backing_transport = backing_transport
        self.root_client_path = root_client_path
        self._client_timeout = client_timeout
        self._active_connections = []
        # This is set to indicate we want to wait for clients to finish before
        # we disconnect.
        self._gracefully_stopping = False

    def start_server(self, host, port):
        """Create the server listening socket.

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
        addrs = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
                                   socket.SOCK_STREAM, 0, socket.AI_PASSIVE)[0]

        (family, socktype, proto, canonname, sockaddr) = addrs

        self._server_socket = socket.socket(family, socktype, proto)
        # SO_REUSERADDR has a different meaning on Windows
        if sys.platform != 'win32':
            self._server_socket.setsockopt(socket.SOL_SOCKET,
                                           socket.SO_REUSEADDR, 1)
        try:
            self._server_socket.bind(sockaddr)
        except self._socket_error as message:
            raise errors.CannotBindAddress(host, port, message)
        self._sockname = self._server_socket.getsockname()
        self.port = self._sockname[1]
        self._server_socket.listen(1)
        self._server_socket.settimeout(self._ACCEPT_TIMEOUT)
        # Once we start accept()ing connections, we set started.
        self._started = threading.Event()
        # Once we stop accept()ing connections (and are closing the socket) we
        # set _stopped
        self._stopped = threading.Event()
        # Once we have finished waiting for all clients, etc. We set
        # _fully_stopped
        self._fully_stopped = threading.Event()

    def _backing_urls(self):
        # There are three interesting urls:
        # The URL the server can be contacted on. (e.g. bzr://host/)
        # The URL that a commit done on the same machine as the server will
        # have within the servers space. (e.g. file:///home/user/source)
        # The URL that will be given to other hooks in the same process -
        # the URL of the backing transport itself. (e.g. filtered-36195:///)
        # We need all three because:
        #  * other machines see the first
        #  * local commits on this machine should be able to be mapped to
        #    this server
        #  * commits the server does itself need to be mapped across to this
        #    server.
        # The latter two urls are different aliases to the servers url,
        # so we group those in a list - as there might be more aliases
        # in the future.
        urls = [self.backing_transport.base]
        try:
            urls.append(self.backing_transport.external_url())
        except errors.InProcessTransport:
            pass
        return urls

    def run_server_started_hooks(self, backing_urls=None):
        if backing_urls is None:
            backing_urls = self._backing_urls()
        for hook in SmartTCPServer.hooks['server_started']:
            hook(backing_urls, self.get_url())
        for hook in SmartTCPServer.hooks['server_started_ex']:
            hook(backing_urls, self)

    def run_server_stopped_hooks(self, backing_urls=None):
        if backing_urls is None:
            backing_urls = self._backing_urls()
        for hook in SmartTCPServer.hooks['server_stopped']:
            hook(backing_urls, self.get_url())

    def _stop_gracefully(self):
        trace.note(gettext('Requested to stop gracefully'))
        self._should_terminate = True
        self._gracefully_stopping = True
        for handler, _ in self._active_connections:
            handler._stop_gracefully()

    def _wait_for_clients_to_disconnect(self):
        self._poll_active_connections()
        if not self._active_connections:
            return
        trace.note(gettext('Waiting for %d client(s) to finish')
                   % (len(self._active_connections),))
        t_next_log = self._timer() + self._LOG_WAITING_TIMEOUT
        while self._active_connections:
            now = self._timer()
            if now >= t_next_log:
                trace.note(gettext('Still waiting for %d client(s) to finish')
                           % (len(self._active_connections),))
                t_next_log = now + self._LOG_WAITING_TIMEOUT
            self._poll_active_connections(self._SHUTDOWN_POLL_TIMEOUT)

    def serve(self, thread_name_suffix=''):
        # Note: There is a temptation to do
        #       signals.register_on_hangup(id(self), self._stop_gracefully)
        #       However, that creates a temporary object which is a bound
        #       method. signals._on_sighup is a WeakKeyDictionary so it
        #       immediately gets garbage collected, because nothing else
        #       references it. Instead, we need to keep a real reference to the
        #       bound method for the lifetime of the serve() function.
        stop_gracefully = self._stop_gracefully
        signals.register_on_hangup(id(self), stop_gracefully)
        self._should_terminate = False
        # for hooks we are letting code know that a server has started (and
        # later stopped).
        self.run_server_started_hooks()
        self._started.set()
        try:
            try:
                while not self._should_terminate:
                    try:
                        conn, client_addr = self._server_socket.accept()
                    except self._socket_timeout:
                        # just check if we're asked to stop
                        pass
                    except self._socket_error as e:
                        # if the socket is closed by stop_background_thread
                        # we might get a EBADF here, or if we get a signal we
                        # can get EINTR, any other socket errors should get
                        # logged.
                        if e.args[0] not in (errno.EBADF, errno.EINTR):
                            trace.warning(gettext("listening socket error: %s")
                                          % (e,))
                    else:
                        if self._should_terminate:
                            conn.close()
                            break
                        self.serve_conn(conn, thread_name_suffix)
                    # Cleanout any threads that have finished processing.
                    self._poll_active_connections()
            except KeyboardInterrupt:
                # dont log when CTRL-C'd.
                raise
            except Exception as e:
                trace.report_exception(sys.exc_info(), sys.stderr)
                raise
        finally:
            try:
                # ensure the server socket is closed.
                self._server_socket.close()
            except self._socket_error:
                # ignore errors on close
                pass
            self._stopped.set()
            signals.unregister_on_hangup(id(self))
            self.run_server_stopped_hooks()
        if self._gracefully_stopping:
            self._wait_for_clients_to_disconnect()
        self._fully_stopped.set()

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%s/" % (self._sockname[0], self._sockname[1])

    def _make_handler(self, conn):
        return medium.SmartServerSocketStreamMedium(
            conn, self.backing_transport, self.root_client_path,
            timeout=self._client_timeout)

    def _poll_active_connections(self, timeout=0.0):
        """Check to see if any active connections have finished.

        This will iterate through self._active_connections, and update any
        connections that are finished.

        :param timeout: The timeout to pass to thread.join(). By default, we
            set it to 0, so that we don't hang if threads are not done yet.
        :return: None
        """
        still_active = []
        for handler, thread in self._active_connections:
            thread.join(timeout)
            if thread.is_alive():
                still_active.append((handler, thread))
        self._active_connections = still_active

    def serve_conn(self, conn, thread_name_suffix):
        # For WIN32, where the timeout value from the listening socket
        # propagates to the newly accepted socket.
        conn.setblocking(True)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        thread_name = 'smart-server-child' + thread_name_suffix
        handler = self._make_handler(conn)
        connection_thread = threading.Thread(
            None, handler.serve, name=thread_name, daemon=True)
        self._active_connections.append((handler, connection_thread))
        connection_thread.start()
        return connection_thread

    def start_background_thread(self, thread_name_suffix=''):
        self._started.clear()
        self._server_thread = threading.Thread(
            None, self.serve, args=(thread_name_suffix,),
            name='server-' + self.get_url(),
            daemon=True)
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
        if not self._stopped.is_set():
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
        Hooks.__init__(self, "breezy.bzr.smart.server", "SmartTCPServer.hooks")
        self.add_hook('server_started',
                      "Called by the bzr server when it starts serving a directory. "
                      "server_started is called with (backing urls, public url), "
                      "where backing_url is a list of URLs giving the "
                      "server-specific directory locations, and public_url is the "
                      "public URL for the directory being served.", (0, 16))
        self.add_hook('server_started_ex',
                      "Called by the bzr server when it starts serving a directory. "
                      "server_started is called with (backing_urls, server_obj).",
                      (1, 17))
        self.add_hook('server_stopped',
                      "Called by the bzr server when it stops serving a directory. "
                      "server_stopped is called with the same parameters as the "
                      "server_started hook: (backing_urls, public_url).", (0, 16))
        self.add_hook('server_exception',
                      "Called by the bzr server when an exception occurs. "
                      "server_exception is called with the sys.exc_info() tuple "
                      "return true for the hook if the exception has been handled, "
                      "in which case the server will exit normally.", (2, 4))


SmartTCPServer.hooks = SmartServerHooks()


def _local_path_for_transport(transport):
    """Return a local path for transport, if reasonably possible.

    This function works even if transport's url has a "readonly+" prefix,
    unlike local_path_from_url.

    This essentially recovers the --directory argument the user passed to "bzr
    serve" from the transport passed to serve_bzr.
    """
    try:
        base_url = transport.external_url()
    except (errors.InProcessTransport, NotImplementedError):
        return None
    else:
        # Strip readonly prefix
        if base_url.startswith('readonly+'):
            base_url = base_url[len('readonly+'):]
        try:
            return urlutils.local_path_from_url(base_url)
        except urlutils.InvalidURL:
            return None


class BzrServerFactory(object):
    """Helper class for serve_bzr."""

    def __init__(self, userdir_expander=None, get_base_path=None):
        self.cleanups = []
        self.base_path = None
        self.backing_transport = None
        if userdir_expander is None:
            userdir_expander = os.path.expanduser
        self.userdir_expander = userdir_expander
        if get_base_path is None:
            get_base_path = _local_path_for_transport
        self.get_base_path = get_base_path

    def _expand_userdirs(self, path):
        """Translate /~/ or /~user/ to e.g. /home/foo, using
        self.userdir_expander (os.path.expanduser by default).

        If the translated path would fall outside base_path, or the path does
        not start with ~, then no translation is applied.

        If the path is inside, it is adjusted to be relative to the base path.

        e.g. if base_path is /home, and the expanded path is /home/joe, then
        the translated path is joe.
        """
        result = path
        if path.startswith('~'):
            expanded = self.userdir_expander(path)
            if not expanded.endswith('/'):
                expanded += '/'
            if expanded.startswith(self.base_path):
                result = expanded[len(self.base_path):]
        return result

    def _make_expand_userdirs_filter(self, transport):
        return pathfilter.PathFilteringServer(transport, self._expand_userdirs)

    def _make_backing_transport(self, transport):
        """Chroot transport, and decorate with userdir expander."""
        self.base_path = self.get_base_path(transport)
        chroot_server = chroot.ChrootServer(transport)
        chroot_server.start_server()
        self.cleanups.append(chroot_server.stop_server)
        transport = _mod_transport.get_transport_from_url(
            chroot_server.get_url())
        if self.base_path is not None:
            # Decorate the server's backing transport with a filter that can
            # expand homedirs.
            expand_userdirs = self._make_expand_userdirs_filter(transport)
            expand_userdirs.start_server()
            self.cleanups.append(expand_userdirs.stop_server)
            transport = _mod_transport.get_transport_from_url(
                expand_userdirs.get_url())
        self.transport = transport

    def _get_stdin_stdout(self):
        return sys.stdin.buffer, sys.stdout.buffer

    def _make_smart_server(self, host, port, inet, timeout):
        if timeout is None:
            c = config.GlobalStack()
            timeout = c.get('serve.client_timeout')
        if inet:
            stdin, stdout = self._get_stdin_stdout()
            smart_server = medium.SmartServerPipeStreamMedium(
                stdin, stdout, self.transport, timeout=timeout)
        else:
            if host is None:
                host = medium.BZR_DEFAULT_INTERFACE
            if port is None:
                port = medium.BZR_DEFAULT_PORT
            smart_server = SmartTCPServer(self.transport,
                                          client_timeout=timeout)
            smart_server.start_server(host, port)
            trace.note(gettext('listening on port: %s'),
                       str(smart_server.port))
        self.smart_server = smart_server

    def _change_globals(self):
        from breezy import lockdir, ui
        # For the duration of this server, no UI output is permitted. note
        # that this may cause problems with blackbox tests. This should be
        # changed with care though, as we dont want to use bandwidth sending
        # progress over stderr to smart server clients!
        old_factory = ui.ui_factory
        old_lockdir_timeout = lockdir._DEFAULT_TIMEOUT_SECONDS

        def restore_default_ui_factory_and_lockdir_timeout():
            ui.ui_factory = old_factory
            lockdir._DEFAULT_TIMEOUT_SECONDS = old_lockdir_timeout
        self.cleanups.append(restore_default_ui_factory_and_lockdir_timeout)
        ui.ui_factory = ui.SilentUIFactory()
        lockdir._DEFAULT_TIMEOUT_SECONDS = 0
        orig = signals.install_sighup_handler()

        def restore_signals():
            signals.restore_sighup_handler(orig)
        self.cleanups.append(restore_signals)

    def set_up(self, transport, host, port, inet, timeout):
        self._make_backing_transport(transport)
        self._make_smart_server(host, port, inet, timeout)
        self._change_globals()

    def tear_down(self):
        for cleanup in reversed(self.cleanups):
            cleanup()


def serve_bzr(transport, host=None, port=None, inet=False, timeout=None):
    """This is the default implementation of 'bzr serve'.

    It creates a TCP or pipe smart server on 'transport, and runs it.  The
    transport will be decorated with a chroot and pathfilter (using
    os.path.expanduser).
    """
    bzr_server = BzrServerFactory()
    try:
        bzr_server.set_up(transport, host, port, inet, timeout)
        bzr_server.smart_server.serve()
    except:
        hook_caught_exception = False
        for hook in SmartTCPServer.hooks['server_exception']:
            hook_caught_exception = hook(sys.exc_info())
        if not hook_caught_exception:
            raise
    finally:
        bzr_server.tear_down()

# Copyright (C) 2006-2010 Canonical Ltd
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
import threading

from bzrlib.hooks import HookPoint, Hooks
from bzrlib import (
    errors,
    trace,
    transport as _mod_transport,
)
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib.smart import medium
from bzrlib.transport import (
    chroot,
    pathfilter,
    )
from bzrlib import (
    urlutils,
    )
""")


class SmartTCPServer(object):
    """Listens on a TCP socket and accepts connections from smart clients.

    Each connection will be served by a SmartServerSocketStreamMedium running in
    a thread.

    hooks: An instance of SmartServerHooks.
    """

    def __init__(self, backing_transport, root_client_path='/'):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param backing_transport: The transport to serve.
        :param root_client_path: The client path that will correspond to root
            of backing_transport.
        """
        self.backing_transport = backing_transport
        self.root_client_path = root_client_path

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
        except self._socket_error, message:
            raise errors.CannotBindAddress(host, port, message)
        self._sockname = self._server_socket.getsockname()
        self.port = self._sockname[1]
        self._server_socket.listen(1)
        self._server_socket.settimeout(1)
        self._started = threading.Event()
        self._stopped = threading.Event()

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

    def serve(self, thread_name_suffix=''):
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
                    except self._socket_error, e:
                        # if the socket is closed by stop_background_thread
                        # we might get a EBADF here, any other socket errors
                        # should get logged.
                        if e.args[0] != errno.EBADF:
                            trace.warning("listening socket error: %s", e)
                    else:
                        if self._should_terminate:
                            break
                        self.serve_conn(conn, thread_name_suffix)
            except KeyboardInterrupt:
                # dont log when CTRL-C'd.
                raise
            except Exception, e:
                trace.report_exception(sys.exc_info(), sys.stderr)
                raise
        finally:
            self._stopped.set()
            try:
                # ensure the server socket is closed.
                self._server_socket.close()
            except self._socket_error:
                # ignore errors on close
                pass
            self.run_server_stopped_hooks()

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%s/" % (self._sockname[0], self._sockname[1])

    def serve_conn(self, conn, thread_name_suffix):
        # For WIN32, where the timeout value from the listening socket
        # propagates to the newly accepted socket.
        conn.setblocking(True)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        handler = medium.SmartServerSocketStreamMedium(
            conn, self.backing_transport, self.root_client_path)
        thread_name = 'smart-server-child' + thread_name_suffix
        connection_thread = threading.Thread(
            None, handler.serve, name=thread_name)
        # FIXME: This thread is never joined, it should at least be collected
        # somewhere so that tests that want to check for leaked threads can get
        # rid of them -- vila 20100531
        connection_thread.setDaemon(True)
        connection_thread.start()
        return connection_thread

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
        self.create_hook(HookPoint('server_started',
            "Called by the bzr server when it starts serving a directory. "
            "server_started is called with (backing urls, public url), "
            "where backing_url is a list of URLs giving the "
            "server-specific directory locations, and public_url is the "
            "public URL for the directory being served.", (0, 16), None))
        self.create_hook(HookPoint('server_started_ex',
            "Called by the bzr server when it starts serving a directory. "
            "server_started is called with (backing_urls, server_obj).",
            (1, 17), None))
        self.create_hook(HookPoint('server_stopped',
            "Called by the bzr server when it stops serving a directory. "
            "server_stopped is called with the same parameters as the "
            "server_started hook: (backing_urls, public_url).", (0, 16), None))

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
        except errors.InvalidURL:
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
        transport = _mod_transport.get_transport(chroot_server.get_url())
        if self.base_path is not None:
            # Decorate the server's backing transport with a filter that can
            # expand homedirs.
            expand_userdirs = self._make_expand_userdirs_filter(transport)
            expand_userdirs.start_server()
            self.cleanups.append(expand_userdirs.stop_server)
            transport = _mod_transport.get_transport(expand_userdirs.get_url())
        self.transport = transport

    def _make_smart_server(self, host, port, inet):
        if inet:
            smart_server = medium.SmartServerPipeStreamMedium(
                sys.stdin, sys.stdout, self.transport)
        else:
            if host is None:
                host = medium.BZR_DEFAULT_INTERFACE
            if port is None:
                port = medium.BZR_DEFAULT_PORT
            smart_server = SmartTCPServer(self.transport)
            smart_server.start_server(host, port)
            trace.note('listening on port: %s' % smart_server.port)
        self.smart_server = smart_server

    def _change_globals(self):
        from bzrlib import lockdir, ui
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

    def set_up(self, transport, host, port, inet):
        self._make_backing_transport(transport)
        self._make_smart_server(host, port, inet)
        self._change_globals()

    def tear_down(self):
        for cleanup in reversed(self.cleanups):
            cleanup()


def serve_bzr(transport, host=None, port=None, inet=False):
    """This is the default implementation of 'bzr serve'.
    
    It creates a TCP or pipe smart server on 'transport, and runs it.  The
    transport will be decorated with a chroot and pathfilter (using
    os.path.expanduser).
    """
    bzr_server = BzrServerFactory()
    try:
        bzr_server.set_up(transport, host, port, inet)
        bzr_server.smart_server.serve()
    finally:
        bzr_server.tear_down()


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

import errno
import httplib
import os
import posixpath
import random
import re
import select
import SimpleHTTPServer
import socket
import SocketServer
import sys
import threading
import time
import urllib
import urlparse

from bzrlib import (
    tests,
    transport,
    )
from bzrlib.tests import test_server
from bzrlib.transport import local


class BadWebserverPath(ValueError):
    def __str__(self):
        return 'path %s is not in %s' % self.args


class TestingHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    """Handles one request.

    A TestingHTTPRequestHandler is instantiated for every request received by
    the associated server. Note that 'request' here is inherited from the base
    TCPServer class, for the HTTP server it is really a connection which itself
    will handle one or several HTTP requests.
    """
    # Default protocol version
    protocol_version = 'HTTP/1.1'

    # The Message-like class used to parse the request headers
    MessageClass = httplib.HTTPMessage

    def setup(self):
        SimpleHTTPServer.SimpleHTTPRequestHandler.setup(self)
        self._cwd = self.server._home_dir
        tcs = self.server.test_case_server
        if tcs.protocol_version is not None:
            # If the test server forced a protocol version, use it
            self.protocol_version = tcs.protocol_version

    def log_message(self, format, *args):
        tcs = self.server.test_case_server
        tcs.log('webserver - %s - - [%s] %s "%s" "%s"',
                self.address_string(),
                self.log_date_time_string(),
                format % args,
                self.headers.get('referer', '-'),
                self.headers.get('user-agent', '-'))

    def handle_one_request(self):
        """Handle a single HTTP request.

        We catch all socket errors occurring when the client close the
        connection early to avoid polluting the test results.
        """
        try:
            self._handle_one_request()
        except socket.error, e:
            # Any socket error should close the connection, but some errors are
            # due to the client closing early and we don't want to pollute test
            # results, so we raise only the others.
            self.close_connection = 1
            if (len(e.args) == 0
                or e.args[0] not in (errno.EPIPE, errno.ECONNRESET,
                                     errno.ECONNABORTED, errno.EBADF)):
                raise

    def _handle_one_request(self):
        SimpleHTTPServer.SimpleHTTPRequestHandler.handle_one_request(self)

    _range_regexp = re.compile(r'^(?P<start>\d+)-(?P<end>\d+)$')
    _tail_regexp = re.compile(r'^-(?P<tail>\d+)$')

    def parse_ranges(self, ranges_header):
        """Parse the range header value and returns ranges and tail.

        RFC2616 14.35 says that syntactically invalid range
        specifiers MUST be ignored. In that case, we return 0 for
        tail and [] for ranges.
        """
        tail = 0
        ranges = []
        if not ranges_header.startswith('bytes='):
            # Syntactically invalid header
            return 0, []

        ranges_header = ranges_header[len('bytes='):]
        for range_str in ranges_header.split(','):
            # FIXME: RFC2616 says end is optional and default to file_size
            range_match = self._range_regexp.match(range_str)
            if range_match is not None:
                start = int(range_match.group('start'))
                end = int(range_match.group('end'))
                if start > end:
                    # Syntactically invalid range
                    return 0, []
                ranges.append((start, end))
            else:
                tail_match = self._tail_regexp.match(range_str)
                if tail_match is not None:
                    tail = int(tail_match.group('tail'))
                else:
                    # Syntactically invalid range
                    return 0, []
        return tail, ranges

    def _header_line_length(self, keyword, value):
        header_line = '%s: %s\r\n' % (keyword, value)
        return len(header_line)

    def send_head(self):
        """Overrides base implementation to work around a bug in python2.5."""
        path = self.translate_path(self.path)
        if os.path.isdir(path) and not self.path.endswith('/'):
            # redirect browser - doing basically what apache does when
            # DirectorySlash option is On which is quite common (braindead, but
            # common)
            self.send_response(301)
            self.send_header("Location", self.path + "/")
            # Indicates that the body is empty for HTTP/1.1 clients
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None

        return SimpleHTTPServer.SimpleHTTPRequestHandler.send_head(self)

    def send_range_content(self, file, start, length):
        file.seek(start)
        self.wfile.write(file.read(length))

    def get_single_range(self, file, file_size, start, end):
        self.send_response(206)
        length = end - start + 1
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header("Content-Length", "%d" % length)

        self.send_header("Content-Type", 'application/octet-stream')
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start,
                                                              end,
                                                              file_size))
        self.end_headers()
        self.send_range_content(file, start, length)

    def get_multiple_ranges(self, file, file_size, ranges):
        self.send_response(206)
        self.send_header('Accept-Ranges', 'bytes')
        boundary = '%d' % random.randint(0,0x7FFFFFFF)
        self.send_header('Content-Type',
                         'multipart/byteranges; boundary=%s' % boundary)
        boundary_line = '--%s\r\n' % boundary
        # Calculate the Content-Length
        content_length = 0
        for (start, end) in ranges:
            content_length += len(boundary_line)
            content_length += self._header_line_length(
                'Content-type', 'application/octet-stream')
            content_length += self._header_line_length(
                'Content-Range', 'bytes %d-%d/%d' % (start, end, file_size))
            content_length += len('\r\n') # end headers
            content_length += end - start + 1
        content_length += len(boundary_line)
        self.send_header('Content-length', content_length)
        self.end_headers()

        # Send the multipart body
        for (start, end) in ranges:
            self.wfile.write(boundary_line)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Content-Range', 'bytes %d-%d/%d'
                             % (start, end, file_size))
            self.end_headers()
            self.send_range_content(file, start, end - start + 1)
        # Final boundary
        self.wfile.write(boundary_line)

    def do_GET(self):
        """Serve a GET request.

        Handles the Range header.
        """
        # Update statistics
        self.server.test_case_server.GET_request_nb += 1

        path = self.translate_path(self.path)
        ranges_header_value = self.headers.get('Range')
        if ranges_header_value is None or os.path.isdir(path):
            # Let the mother class handle most cases
            return SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)

        try:
            # Always read in binary mode. Opening files in text
            # mode may cause newline translations, making the
            # actual size of the content transmitted *less* than
            # the content-length!
            file = open(path, 'rb')
        except IOError:
            self.send_error(404, "File not found")
            return

        file_size = os.fstat(file.fileno())[6]
        tail, ranges = self.parse_ranges(ranges_header_value)
        # Normalize tail into ranges
        if tail != 0:
            ranges.append((file_size - tail, file_size))

        self._satisfiable_ranges = True
        if len(ranges) == 0:
            self._satisfiable_ranges = False
        else:
            def check_range(range_specifier):
                start, end = range_specifier
                # RFC2616 14.35, ranges are invalid if start >= file_size
                if start >= file_size:
                    self._satisfiable_ranges = False # Side-effect !
                    return 0, 0
                # RFC2616 14.35, end values should be truncated
                # to file_size -1 if they exceed it
                end = min(end, file_size - 1)
                return start, end

            ranges = map(check_range, ranges)

        if not self._satisfiable_ranges:
            # RFC2616 14.16 and 14.35 says that when a server
            # encounters unsatisfiable range specifiers, it
            # SHOULD return a 416.
            file.close()
            # FIXME: We SHOULD send a Content-Range header too,
            # but the implementation of send_error does not
            # allows that. So far.
            self.send_error(416, "Requested range not satisfiable")
            return

        if len(ranges) == 1:
            (start, end) = ranges[0]
            self.get_single_range(file, file_size, start, end)
        else:
            self.get_multiple_ranges(file, file_size, ranges)
        file.close()

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        If the server requires it, proxy the path before the usual translation
        """
        if self.server.test_case_server.proxy_requests:
            # We need to act as a proxy and accept absolute urls,
            # which SimpleHTTPRequestHandler (parent) is not
            # ready for. So we just drop the protocol://host:port
            # part in front of the request-url (because we know
            # we would not forward the request to *another*
            # proxy).

            # So we do what SimpleHTTPRequestHandler.translate_path
            # do beginning with python 2.4.3: abandon query
            # parameters, scheme, host port, etc (which ensure we
            # provide the right behaviour on all python versions).
            path = urlparse.urlparse(path)[2]
            # And now, we can apply *our* trick to proxy files
            path += '-proxied'

        return self._translate_path(path)

    def _translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Note that we're translating http URLs here, not file URLs.
        The URL root location is the server's startup directory.
        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        Override from python standard library to stop it calling os.getcwd()
        """
        # abandon query parameters
        path = urlparse.urlparse(path)[2]
        path = posixpath.normpath(urllib.unquote(path))
        path = path.decode('utf-8')
        words = path.split('/')
        words = filter(None, words)
        path = self._cwd
        for num, word in enumerate(words):
            if num == 0:
                drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir): continue
            path = os.path.join(path, word)
        return path


class TestingHTTPServerMixin:

    def __init__(self, test_case_server):
        # test_case_server can be used to communicate between the
        # tests and the server (or the request handler and the
        # server), allowing dynamic behaviors to be defined from
        # the tests cases.
        self.test_case_server = test_case_server
        self._home_dir = test_case_server._home_dir
        self.serving = None
        self.is_shut_down = threading.Event()
        # We collect the sockets/threads used by the clients so we can
        # close/join them when shutting down
        self.clients = []

    def get_request (self):
        """Get the request and client address from the socket.
        """
        sock, addr = self._get_request()
        self.clients.append([sock, addr])
        return sock, addr

    def verify_request(self, request, client_address):
        """Verify the request.

        Return True if we should proceed with this request, False if we should
        not even touch a single byte in the socket !
        """
        return self.serving is not None and self.serving.isSet()

    def handle_request(self):
        request, client_address = self.get_request()
        try:
            if self.verify_request(request, client_address):
                self.process_request(request, client_address)
        except:
            if self.serving is not None and self.serving.isSet():
                self.handle_error(request, client_address)
            else:
                # Exceptions raised while we shut down are just noise, but feel
                # free to put a breakpoint here if you suspect something
                # else. Such an example is the SSL handshake: it's automatic
                # once we start processing the request but the last connection
                # will close immediately and will not be able to correctly
                # reply.
                pass
            self.close_request(request)

    def server_bind(self):
        # The following has been fixed in 2.5 so we need to provide it for
        # older python versions.
        if sys.version < (2, 5):
            self.server_address = self.socket.getsockname()

    def serve(self, started):
        self.serving  = threading.Event()
        self.serving.set()
        self.is_shut_down.clear()
        if 'threads' in tests.selftest_debug_flags:
            print 'Starting %r' % (self.server_address,)
        # We are listening and ready to accept connections
        started.set()
        while self.serving.isSet():
            if 'threads' in tests.selftest_debug_flags:
                print 'Accepting on %r' % (self.server_address,)
            # Really a connection but the python framework is generic and
            # call them requests
            self.handle_request()
        if 'threads' in tests.selftest_debug_flags:
            print 'Closing  %r' % (self.server_address,)
        # Let's close the listening socket
        self.server_close()
        if 'threads' in tests.selftest_debug_flags:
            print 'Closed   %r' % (self.server_address,)
        self.is_shut_down.set()

    def connect_socket(self):
        err = socket.error('getaddrinfo returns an empty list')
        for res in socket.getaddrinfo(*self.server_address):
            af, socktype, proto, canonname, sa = res
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                sock.connect(sa)
                return sock

            except socket.error, err:
                # 'err' is now the most recent error
                if sock is not None:
                    sock.close()
        raise err

    def join_thread(self, thread, timeout=2):
        thread.join(timeout)
        if thread.isAlive():
            # The timeout expired without joining the thread, the thread is
            # therefore stucked and that's a failure as far as the test is
            # concerned. We used to hang here.
            raise AssertionError('thread %s hung' % (thread.name,))

    def shutdown(self):
        """Stops the serve() loop.

        Blocks until the loop has finished. This must be called while serve()
        is running in another thread, or it will deadlock.
        """
        if self.serving is None:
            # If the server wasn't properly started, there is nothing to
            # shutdown.
            return
        # As soon as we stop serving, no more connection are accepted except
        # one to get out of the blocking listen.
        self.serving.clear()
        # The server is listening for a last connection, let's give it:
        last_conn = None
        try:
            last_conn = self.connect_socket()
        except socket.error, e:
            # But ignore connection errors as the point is to unblock the
            # server thread, it may happen that it's not blocked or even not
            # started (when something went wrong during test case setup
            # leading to self.setUp() *not* being called but self.tearDown()
            # still being called)
            pass
        # We don't have to wait for the server to shut down to start shutting
        # down the clients, so let's start now.
        for c in self.clients:
            self.shutdown_client(c)
        self.clients = []
        # Now we wait for the thread running serve() to finish
        self.is_shut_down.wait()
        if last_conn is not None:
            # Close the last connection without trying to use it. The server
            # will not process a single byte on that socket to avoid
            # complications (SSL starts with a handshake for example).
            last_conn.close()

    def shutdown_client(self, client):
        sock, addr = client[:2]
        self.shutdown_client_socket(sock)

    def shutdown_client_socket(self, sock):
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
            sock.shutdown(socket.SHUT_RDWR)
        except (socket.error, select.error), e:
            if e[0] in (errno.EBADF, errno.ENOTCONN):
                # Right, the socket is already down
                pass
            else:
                raise


class TestingHTTPServer(TestingHTTPServerMixin, SocketServer.TCPServer):

    def __init__(self, server_address, request_handler_class,
                 test_case_server):
        TestingHTTPServerMixin.__init__(self, test_case_server)
        SocketServer.TCPServer.__init__(self, server_address,
                                        request_handler_class)

    def _get_request (self):
        return SocketServer.TCPServer.get_request(self)

    def server_bind(self):
        SocketServer.TCPServer.server_bind(self)
        TestingHTTPServerMixin.server_bind(self)


class TestingThreadingHTTPServer(TestingHTTPServerMixin,
                                 SocketServer.ThreadingTCPServer,
                                 ):
    """A threading HTTP test server for HTTP 1.1.

    Since tests can initiate several concurrent connections to the same http
    server, we need an independent connection for each of them. We achieve that
    by spawning a new thread for each connection.
    """

    def __init__(self, server_address, request_handler_class,
                 test_case_server):
        TestingHTTPServerMixin.__init__(self, test_case_server)
        SocketServer.ThreadingTCPServer.__init__(self, server_address,
                                                 request_handler_class)
        # Decides how threads will act upon termination of the main
        # process. This is prophylactic as we should not leave the threads
        # lying around.
        self.daemon_threads = True

    def _get_request (self):
        return SocketServer.ThreadingTCPServer.get_request(self)

    def process_request_thread(self, started, request, client_address):
        if 'threads' in tests.selftest_debug_flags:
            print 'Processing: %s' % (threading.currentThread().name,)
        started.set()
        SocketServer.ThreadingTCPServer.process_request_thread(
            self, request, client_address)
        # Shutdown the socket as soon as possible, the thread will be joined
        # later if needed during server shutdown thread.
        self.shutdown_client_socket(request)

    def process_request(self, request, client_address):
        """Start a new thread to process the request."""
        client = self.clients.pop()
        started = threading.Event()
        t = threading.Thread(target = self.process_request_thread,
                             args = (started, request, client_address))
        t.name = '%s -> %s' % (client_address, self.server_address)
        client.append(t)
        self.clients.append(client)
        if self.daemon_threads:
            t.setDaemon (1)
        t.start()
        started.wait()

    def shutdown_client(self, client):
        TestingHTTPServerMixin.shutdown_client(self, client)
        if len(client) == 3:
            # The thread has been created only if the request is processed but
            # after the connection is inited. This could happne when the server
            # is shut down.
            sock, addr, thread = client
            if 'threads' in tests.selftest_debug_flags:
                print 'Try    joining: %s' % (thread.name,)
            self.join_thread(thread)

    def server_bind(self):
        SocketServer.ThreadingTCPServer.server_bind(self)
        TestingHTTPServerMixin.server_bind(self)


class HttpServer(transport.Server):
    """A test server for http transports.

    Subclasses can provide a specific request handler.
    """

    # The real servers depending on the protocol
    http_server_class = {'HTTP/1.0': TestingHTTPServer,
                         'HTTP/1.1': TestingThreadingHTTPServer,
                         }

    # Whether or not we proxy the requests (see
    # TestingHTTPRequestHandler.translate_path).
    proxy_requests = False

    # used to form the url that connects to this server
    _url_protocol = 'http'

    def __init__(self, request_handler=TestingHTTPRequestHandler,
                 protocol_version=None):
        """Constructor.

        :param request_handler: a class that will be instantiated to handle an
            http connection (one or several requests).

        :param protocol_version: if specified, will override the protocol
            version of the request handler.
        """
        transport.Server.__init__(self)
        self.request_handler = request_handler
        self.host = 'localhost'
        self.port = 0
        self._httpd = None
        self.protocol_version = protocol_version
        # Allows tests to verify number of GET requests issued
        self.GET_request_nb = 0

    def create_httpd(self, serv_cls, rhandler_cls):
        return serv_cls((self.host, self.port), self.request_handler, self)

    def __repr__(self):
        return "%s(%s:%s)" % \
            (self.__class__.__name__, self.host, self.port)

    def _get_httpd(self):
        if self._httpd is None:
            rhandler = self.request_handler
            # Depending on the protocol version, we will create the approriate
            # server
            if self.protocol_version is None:
                # Use the request handler one
                proto_vers = rhandler.protocol_version
            else:
                # Use our own, it will be used to override the request handler
                # one too.
                proto_vers = self.protocol_version
            # Create the appropriate server for the required protocol
            serv_cls = self.http_server_class.get(proto_vers, None)
            if serv_cls is None:
                raise httplib.UnknownProtocol(proto_vers)
            else:
                self._httpd = self.create_httpd(serv_cls, rhandler)
            # Ensure we get the right port and an updated host if needed
            self.host, self.port = self._httpd.server_address
        return self._httpd

    def _http_start(self, started):
        """Server thread main entry point. """
        server = None
        try:
            server = self._get_httpd()
            self._http_base_url = '%s://%s:%s/' % (self._url_protocol,
                                                   self.host, self.port)
        except:
            # Whatever goes wrong, we save the exception for the main
            # thread. Note that since we are running in a thread, no signal
            # can be received, so we don't care about KeyboardInterrupt.
            self._http_exception = sys.exc_info()

        if server is not None:
            # From now on, exceptions are taken care of by the
            # SocketServer.BaseServer or the request handler.
            server.serve(started)
        if not started.isSet():
            # Hmm, something went wrong, but we can release the caller anyway
            started.set()

    def _get_remote_url(self, path):
        path_parts = path.split(os.path.sep)
        if os.path.isabs(path):
            if path_parts[:len(self._local_path_parts)] != \
                   self._local_path_parts:
                raise BadWebserverPath(path, self.test_dir)
            remote_path = '/'.join(path_parts[len(self._local_path_parts):])
        else:
            remote_path = '/'.join(path_parts)

        return self._http_base_url + remote_path

    def log(self, format, *args):
        """Capture Server log output."""
        self.logs.append(format % args)

    def start_server(self, backing_transport_server=None):
        """See bzrlib.transport.Server.start_server.

        :param backing_transport_server: The transport that requests over this
            protocol should be forwarded to. Note that this is currently not
            supported for HTTP.
        """
        # XXX: TODO: make the server back onto vfs_server rather than local
        # disk.
        if not (backing_transport_server is None
                or isinstance(backing_transport_server,
                              test_server.LocalURLServer)):
            raise AssertionError(
                "HTTPServer currently assumes local transport, got %s" %
                backing_transport_server)
        self._home_dir = os.getcwdu()
        self._local_path_parts = self._home_dir.split(os.path.sep)
        self._http_base_url = None

        # Create the server thread
        started = threading.Event()
        self._http_thread = threading.Thread(target=self._http_start,
                                             args = (started,))
        self._http_thread.setDaemon(True)
        self._http_exception = None
        self._http_thread.start()
        # Wait for the server thread to start (i.e release the lock)
        started.wait()
        self._http_thread.name = self._http_base_url
        if 'threads' in tests.selftest_debug_flags:
            print 'Thread started: %s' % (self._http_thread.name,)


        if self._http_exception is not None:
            # Something went wrong during server start
            exc_class, exc_value, exc_tb = self._http_exception
            raise exc_class, exc_value, exc_tb
        self.logs = []

    def stop_server(self):
        """See bzrlib.transport.Server.tearDown."""
        self._httpd.shutdown()
        if 'threads' in tests.selftest_debug_flags:
            print 'Try    joining: %s' % (self._http_thread.name,)
        self._httpd.join_thread(self._http_thread)
        if 'threads' in tests.selftest_debug_flags:
            print 'Thread  joined: %s' % (self._http_thread.name,)

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self._get_remote_url(self._home_dir)

    def get_bogus_url(self):
        """See bzrlib.transport.Server.get_bogus_url."""
        # this is chosen to try to prevent trouble with proxies, weird dns,
        # etc
        return self._url_protocol + '://127.0.0.1:1/'


class HttpServer_urllib(HttpServer):
    """Subclass of HttpServer that gives http+urllib urls.

    This is for use in testing: connections to this server will always go
    through urllib where possible.
    """

    # urls returned by this server should require the urllib client impl
    _url_protocol = 'http+urllib'


class HttpServer_PyCurl(HttpServer):
    """Subclass of HttpServer that gives http+pycurl urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    """

    # We don't care about checking the pycurl availability as
    # this server will be required only when pycurl is present

    # urls returned by this server should require the pycurl client impl
    _url_protocol = 'http+pycurl'

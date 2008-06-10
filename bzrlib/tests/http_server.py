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

import errno
import httplib
import os
import posixpath
import random
import re
import SimpleHTTPServer
import socket
import SocketServer
import sys
import threading
import time
import urllib
import urlparse

from bzrlib import transport
from bzrlib.transport import local


class WebserverNotAvailable(Exception):
    pass


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
            SimpleHTTPServer.SimpleHTTPRequestHandler.handle_one_request(self)
        except socket.error, e:
            # Any socket error should close the connection, but some errors are
            # due to the client closing early and we don't want to pollute test
            # results, so we raise only the others.
            self.close_connection = 1
            if (len(e.args) == 0
                or e.args[0] not in (errno.EPIPE, errno.ECONNRESET,
                                     errno.ECONNABORTED, errno.EBADF)):
                raise

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
            content_length += end - start # + 1
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

    def tearDown(self):
         """Called to clean-up the server.
 
         Since the server may be (surely is, even) in a blocking listen, we
         shutdown its socket before closing it.
         """
         # Note that is this executed as part of the implicit tear down in the
         # main thread while the server runs in its own thread. The clean way
         # to tear down the server is to instruct him to stop accepting
         # connections and wait for the current connection(s) to end
         # naturally. To end the connection naturally, the http transports
         # should close their socket when they do not need to talk to the
         # server anymore. This happens naturally during the garbage collection
         # phase of the test transport objetcs (the server clients), so we
         # don't have to worry about them.  So, for the server, we must tear
         # down here, from the main thread, when the test have ended.  Note
         # that since the server is in a blocking operation and since python
         # use select internally, shutting down the socket is reliable and
         # relatively clean.
         try:
             self.socket.shutdown(socket.SHUT_RDWR)
         except socket.error, e:
             # WSAENOTCONN (10057) 'Socket is not connected' is harmless on
             # windows (occurs before the first connection attempt
             # vila--20071230)
             if not len(e.args) or e.args[0] != 10057:
                 raise
         # Let the server properly close the socket
         self.server_close()


class TestingHTTPServer(SocketServer.TCPServer, TestingHTTPServerMixin):

    def __init__(self, server_address, request_handler_class,
                 test_case_server):
        TestingHTTPServerMixin.__init__(self, test_case_server)
        SocketServer.TCPServer.__init__(self, server_address,
                                        request_handler_class)


class TestingThreadingHTTPServer(SocketServer.ThreadingTCPServer,
                                 TestingHTTPServerMixin):
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
                self._httpd = serv_cls((self.host, self.port), rhandler, self)
            host, self.port = self._httpd.socket.getsockname()
        return self._httpd

    def _http_start(self):
        """Server thread main entry point. """
        self._http_running = False
        try:
            try:
                httpd = self._get_httpd()
                self._http_base_url = '%s://%s:%s/' % (self._url_protocol,
                                                       self.host, self.port)
                self._http_running = True
            except:
                # Whatever goes wrong, we save the exception for the main
                # thread. Note that since we are running in a thread, no signal
                # can be received, so we don't care about KeyboardInterrupt.
                self._http_exception = sys.exc_info()
        finally:
            # Release the lock or the main thread will block and the whole
            # process will hang.
            self._http_starting.release()

        # From now on, exceptions are taken care of by the
        # SocketServer.BaseServer or the request handler.
        while self._http_running:
            try:
                # Really an HTTP connection but the python framework is generic
                # and call them requests
                httpd.handle_request()
            except socket.timeout:
                pass

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

    def setUp(self, backing_transport_server=None):
        """See bzrlib.transport.Server.setUp.
        
        :param backing_transport_server: The transport that requests over this
            protocol should be forwarded to. Note that this is currently not
            supported for HTTP.
        """
        # XXX: TODO: make the server back onto vfs_server rather than local
        # disk.
        if not (backing_transport_server is None or \
                isinstance(backing_transport_server, local.LocalURLServer)):
            raise AssertionError(
                "HTTPServer currently assumes local transport, got %s" % \
                backing_transport_server)
        self._home_dir = os.getcwdu()
        self._local_path_parts = self._home_dir.split(os.path.sep)
        self._http_base_url = None

        # Create the server thread
        self._http_starting = threading.Lock()
        self._http_starting.acquire()
        self._http_thread = threading.Thread(target=self._http_start)
        self._http_thread.setDaemon(True)
        self._http_exception = None
        self._http_thread.start()

        # Wait for the server thread to start (i.e release the lock)
        self._http_starting.acquire()

        if self._http_exception is not None:
            # Something went wrong during server start
            exc_class, exc_value, exc_tb = self._http_exception
            raise exc_class, exc_value, exc_tb
        self._http_starting.release()
        self.logs = []

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        self._httpd.tearDown()
        self._http_running = False
        # We don't need to 'self._http_thread.join()' here since the thread is
        # a daemonic one and will be garbage collected anyway. Joining just
        # slows us down for no added benefit.

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

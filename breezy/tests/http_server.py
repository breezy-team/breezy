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

import errno
import http.client as http_client
import http.server as http_server
import os
import posixpath
import random
import re
from urllib.parse import urlparse

from .. import osutils, urlutils
from . import test_server


class BadWebserverPath(ValueError):
    def __str__(self):
        return "path {} is not in {}".format(*self.args)


class TestingHTTPRequestHandler(http_server.SimpleHTTPRequestHandler):
    """Handles one request.

    A TestingHTTPRequestHandler is instantiated for every request received by
    the associated server. Note that 'request' here is inherited from the base
    TCPServer class, for the HTTP server it is really a connection which itself
    will handle one or several HTTP requests.
    """

    # Default protocol version
    protocol_version = "HTTP/1.1"

    # The Message-like class used to parse the request headers
    MessageClass = http_client.HTTPMessage

    def setup(self):
        http_server.SimpleHTTPRequestHandler.setup(self)
        self._cwd = self.server._home_dir
        tcs = self.server.test_case_server
        if tcs.protocol_version is not None:
            # If the test server forced a protocol version, use it
            self.protocol_version = tcs.protocol_version

    def log_message(self, format, *args):
        tcs = self.server.test_case_server
        tcs.log(
            'webserver - %s - - [%s] %s "%s" "%s"',
            self.address_string(),
            self.log_date_time_string(),
            format % args,
            self.headers.get("referer", "-"),
            self.headers.get("user-agent", "-"),
        )

    def handle_one_request(self):
        """Handle a single HTTP request.

        We catch all socket errors occurring when the client close the
        connection early to avoid polluting the test results.
        """
        try:
            self._handle_one_request()
        except OSError as e:
            # Any socket error should close the connection, but some errors are
            # due to the client closing early and we don't want to pollute test
            # results, so we raise only the others.
            self.close_connection = 1
            if len(e.args) == 0 or e.args[0] not in (
                errno.EPIPE,
                errno.ECONNRESET,
                errno.ECONNABORTED,
                errno.EBADF,
            ):
                raise

    error_content_type = "text/plain"
    error_message_format = """\
Error code: %(code)s.
Message: %(message)s.
"""

    def send_error(self, code, message=None):
        """Send and log an error reply.

        We redefine the python-provided version to be able to set a
        ``Content-Length`` header as some http/1.1 clients complain otherwise
        (see bug #568421).

        :param code: The HTTP error code.

        :param message: The explanation of the error code, Defaults to a short
             entry.
        """
        if message is None:
            try:
                message = self.responses[code][0]
            except KeyError:
                message = "???"
        self.log_error("code %d, message %s", code, message)
        content = self.error_message_format % {"code": code, "message": message}
        self.send_response(code, message)
        self.send_header("Content-Type", self.error_content_type)
        self.send_header("Content-Length", "%d" % len(content))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD" and code >= 200 and code not in (204, 304):
            self.wfile.write(content.encode("utf-8"))

    def _handle_one_request(self):
        http_server.SimpleHTTPRequestHandler.handle_one_request(self)

    _range_regexp = re.compile(r"^(?P<start>\d+)-(?P<end>\d+)?$")
    _tail_regexp = re.compile(r"^-(?P<tail>\d+)$")

    def _parse_ranges(self, ranges_header, file_size):
        """Parse the range header value and returns ranges.

        RFC2616 14.35 says that syntactically invalid range specifiers MUST be
        ignored. In that case, we return None instead of a range list.

        :param ranges_header: The 'Range' header value.

        :param file_size: The size of the requested file.

        :return: A list of (start, end) tuples or None if some invalid range
            specifier is encountered.
        """
        if not ranges_header.startswith("bytes="):
            # Syntactically invalid header
            return None

        tail = None
        ranges = []
        ranges_header = ranges_header[len("bytes=") :]
        for range_str in ranges_header.split(","):
            range_match = self._range_regexp.match(range_str)
            if range_match is not None:
                start = int(range_match.group("start"))
                end_match = range_match.group("end")
                if end_match is None:
                    # RFC2616 says end is optional and default to file_size
                    end = file_size
                else:
                    end = int(end_match)
                if start > end:
                    # Syntactically invalid range
                    return None
                ranges.append((start, end))
            else:
                tail_match = self._tail_regexp.match(range_str)
                if tail_match is not None:
                    tail = int(tail_match.group("tail"))
                else:
                    # Syntactically invalid range
                    return None
        if tail is not None:
            # Normalize tail into ranges
            ranges.append((max(0, file_size - tail), file_size))

        checked_ranges = []
        for start, end in ranges:
            if start >= file_size:
                # RFC2616 14.35, ranges are invalid if start >= file_size
                return None
            # RFC2616 14.35, end values should be truncated
            # to file_size -1 if they exceed it
            end = min(end, file_size - 1)
            checked_ranges.append((start, end))
        return checked_ranges

    def _header_line_length(self, keyword, value):
        header_line = "{}: {}\r\n".format(keyword, value)
        return len(header_line)

    def send_range_content(self, file, start, length):
        file.seek(start)
        self.wfile.write(file.read(length))

    def get_single_range(self, file, file_size, start, end):
        self.send_response(206)
        length = end - start + 1
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", "%d" % length)

        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, file_size))
        self.end_headers()
        self.send_range_content(file, start, length)

    def get_multiple_ranges(self, file, file_size, ranges):
        self.send_response(206)
        self.send_header("Accept-Ranges", "bytes")
        boundary = "%d" % random.randint(0, 0x7FFFFFFF)
        self.send_header(
            "Content-Type", "multipart/byteranges; boundary={}".format(boundary)
        )
        boundary_line = b"--%s\r\n" % boundary.encode("ascii")
        # Calculate the Content-Length
        content_length = 0
        for start, end in ranges:
            content_length += len(boundary_line)
            content_length += self._header_line_length(
                "Content-type", "application/octet-stream"
            )
            content_length += self._header_line_length(
                "Content-Range", "bytes %d-%d/%d" % (start, end, file_size)
            )
            content_length += len("\r\n")  # end headers
            content_length += end - start + 1
        content_length += len(boundary_line)
        self.send_header("Content-length", content_length)
        self.end_headers()

        # Send the multipart body
        for start, end in ranges:
            self.wfile.write(boundary_line)
            self.send_header("Content-type", "application/octet-stream")
            self.send_header(
                "Content-Range", "bytes %d-%d/%d" % (start, end, file_size)
            )
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
        ranges_header_value = self.headers.get("Range")
        if ranges_header_value is None or os.path.isdir(path):
            # Let the mother class handle most cases
            return http_server.SimpleHTTPRequestHandler.do_GET(self)

        try:
            # Always read in binary mode. Opening files in text
            # mode may cause newline translations, making the
            # actual size of the content transmitted *less* than
            # the content-length!
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return

        file_size = os.fstat(f.fileno())[6]
        ranges = self._parse_ranges(ranges_header_value, file_size)
        if not ranges:
            # RFC2616 14.16 and 14.35 says that when a server
            # encounters unsatisfiable range specifiers, it
            # SHOULD return a 416.
            f.close()
            # FIXME: We SHOULD send a Content-Range header too,
            # but the implementation of send_error does not
            # allows that. So far.
            self.send_error(416, "Requested range not satisfiable")
            return

        if len(ranges) == 1:
            (start, end) = ranges[0]
            self.get_single_range(f, file_size, start, end)
        else:
            self.get_multiple_ranges(f, file_size, ranges)
        f.close()

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
            path = urlparse(path)[2]
            # And now, we can apply *our* trick to proxy files
            path += "-proxied"

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
        path = urlparse(path)[2]
        path = posixpath.normpath(urlutils.unquote(path))
        words = path.split("/")
        path = self._cwd
        for num, word in enumerate(w for w in words if w):
            if num == 0:
                drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir):
                continue
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


class TestingHTTPServer(test_server.TestingTCPServer, TestingHTTPServerMixin):
    def __init__(self, server_address, request_handler_class, test_case_server):
        test_server.TestingTCPServer.__init__(
            self, server_address, request_handler_class
        )
        TestingHTTPServerMixin.__init__(self, test_case_server)


class TestingThreadingHTTPServer(
    test_server.TestingThreadingTCPServer, TestingHTTPServerMixin
):
    """A threading HTTP test server for HTTP 1.1.

    Since tests can initiate several concurrent connections to the same http
    server, we need an independent connection for each of them. We achieve that
    by spawning a new thread for each connection.
    """

    def __init__(self, server_address, request_handler_class, test_case_server):
        test_server.TestingThreadingTCPServer.__init__(
            self, server_address, request_handler_class
        )
        TestingHTTPServerMixin.__init__(self, test_case_server)


class HttpServer(test_server.TestingTCPServerInAThread):
    """A test server for http transports.

    Subclasses can provide a specific request handler.
    """

    # The real servers depending on the protocol
    http_server_class = {
        "HTTP/1.0": TestingHTTPServer,
        "HTTP/1.1": TestingThreadingHTTPServer,
    }

    # Whether or not we proxy the requests (see
    # TestingHTTPRequestHandler.translate_path).
    proxy_requests = False

    # used to form the url that connects to this server
    _url_protocol = "http"

    def __init__(
        self, request_handler=TestingHTTPRequestHandler, protocol_version=None
    ):
        """Constructor.

        :param request_handler: a class that will be instantiated to handle an
            http connection (one or several requests).

        :param protocol_version: if specified, will override the protocol
            version of the request handler.
        """
        # Depending on the protocol version, we will create the approriate
        # server
        if protocol_version is None:
            # Use the request handler one
            proto_vers = request_handler.protocol_version
        else:
            # Use our own, it will be used to override the request handler
            # one too.
            proto_vers = protocol_version
        # Get the appropriate server class for the required protocol
        serv_cls = self.http_server_class.get(proto_vers, None)
        if serv_cls is None:
            raise http_client.UnknownProtocol(proto_vers)
        self.host = "localhost"
        self.port = 0
        super().__init__((self.host, self.port), serv_cls, request_handler)
        self.protocol_version = proto_vers
        # Allows tests to verify number of GET requests issued
        self.GET_request_nb = 0
        self._http_base_url = None
        self.logs = []

    def create_server(self):
        return self.server_class(
            (self.host, self.port), self.request_handler_class, self
        )

    def _get_remote_url(self, path):
        path_parts = path.split(os.path.sep)
        if os.path.isabs(path):
            if path_parts[: len(self._local_path_parts)] != self._local_path_parts:
                raise BadWebserverPath(path, self.test_dir)
            remote_path = "/".join(path_parts[len(self._local_path_parts) :])
        else:
            remote_path = "/".join(path_parts)

        return self._http_base_url + remote_path

    def log(self, format, *args):
        """Capture Server log output."""
        self.logs.append(format % args)

    def start_server(self, backing_transport_server=None):
        """See breezy.transport.Server.start_server.

        :param backing_transport_server: The transport that requests over this
            protocol should be forwarded to. Note that this is currently not
            supported for HTTP.
        """
        # XXX: TODO: make the server back onto vfs_server rather than local
        # disk.
        if not (
            backing_transport_server is None
            or isinstance(backing_transport_server, test_server.LocalURLServer)
        ):
            raise AssertionError(
                "HTTPServer currently assumes local transport, got {}".format(
                    backing_transport_server
                )
            )
        self._home_dir = osutils.getcwd()
        self._local_path_parts = self._home_dir.split(os.path.sep)
        self.logs = []

        super().start_server()
        self._http_base_url = "{}://{}:{}/".format(
            self._url_protocol, self.host, self.port
        )

    def get_url(self):
        """See breezy.transport.Server.get_url."""
        return self._get_remote_url(self._home_dir)

    def get_bogus_url(self):
        """See breezy.transport.Server.get_bogus_url."""
        # this is chosen to try to prevent trouble with proxies, weird dns,
        # etc
        return self._url_protocol + "://127.0.0.1:1/"

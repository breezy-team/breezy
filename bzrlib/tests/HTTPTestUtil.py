# Copyright (C) 2005 Canonical Ltd
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

from cStringIO import StringIO
import errno
from SimpleHTTPServer import SimpleHTTPRequestHandler
import socket

from bzrlib.tests import TestCaseWithTransport
from bzrlib.tests.HttpServer import (
    HttpServer,
    TestingHTTPRequestHandler,
    )
from bzrlib.transport import (
    get_transport,
    smart,
    )


class WallRequestHandler(TestingHTTPRequestHandler):
    """Whatever request comes in, close the connection"""

    def handle_one_request(self):
        """Handle a single HTTP request, by abruptly closing the connection"""
        self.close_connection = 1


class BadStatusRequestHandler(TestingHTTPRequestHandler):
    """Whatever request comes in, returns a bad status"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = TestingHTTPRequestHandler.parse_request(self)
        try:
            self.send_response(0, "Bad status")
            self.end_headers()
        except socket.error, e:
            if (len(e.args) > 0) and (e.args[0] == errno.EPIPE):
                # We don't want to pollute the test reuslts with
                # spurious server errors while test succeed. In
                # our case, it may occur that the test have
                # already read the 'Bad Status' and closed the
                # socket while we are still trying to send some
                # headers... So the test is ok but if we raise
                # the exception the output is dirty. So we don't
                # raise, but we close the connection, just to be
                # safe :)
                self.close_connection = 1
                pass
            else:
                raise
        return False


class InvalidStatusRequestHandler(TestingHTTPRequestHandler):
    """Whatever request comes in, returns am invalid status"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = TestingHTTPRequestHandler.parse_request(self)
        self.wfile.write("Invalid status line\r\n")
        return False


class BadProtocolRequestHandler(TestingHTTPRequestHandler):
    """Whatever request comes in, returns a bad protocol version"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = TestingHTTPRequestHandler.parse_request(self)
        # Returns an invalid protocol version, but curl just
        # ignores it and those cannot be tested.
        self.wfile.write("%s %d %s\r\n" % ('HTTP/0.0',
                                           404,
                                           'Look at my protocol version'))
        return False


class ForbiddenRequestHandler(TestingHTTPRequestHandler):
    """Whatever request comes in, returns a 403 code"""

    def parse_request(self):
        """Handle a single HTTP request, by replying we cannot handle it"""
        ignored = TestingHTTPRequestHandler.parse_request(self)
        self.send_error(403)
        return False


class HTTPServerWithSmarts(HttpServer):
    """HTTPServerWithSmarts extends the HttpServer with POST methods that will
    trigger a smart server to execute with a transport rooted at the rootdir of
    the HTTP server.
    """

    def __init__(self):
        HttpServer.__init__(self, SmartRequestHandler)


class SmartRequestHandler(TestingHTTPRequestHandler):
    """Extend TestingHTTPRequestHandler to support smart client POSTs."""

    def do_POST(self):
        """Hand the request off to a smart server instance."""
        self.send_response(200)
        self.send_header("Content-type", "application/octet-stream")
        transport = get_transport(self.server.test_case._home_dir)
        # TODO: We might like to support streaming responses.  1.0 allows no
        # Content-length in this case, so for integrity we should perform our
        # own chunking within the stream.
        # 1.1 allows chunked responses, and in this case we could chunk using
        # the HTTP chunking as this will allow HTTP persistence safely, even if
        # we have to stop early due to error, but we would also have to use the
        # HTTP trailer facility which may not be widely available.
        out_buffer = StringIO()
        smart_protocol_request = smart.SmartServerRequestProtocolOne(
                transport, out_buffer.write)
        # if this fails, we should return 400 bad request, but failure is
        # failure for now - RBC 20060919
        data_length = int(self.headers['Content-Length'])
        # Perhaps there should be a SmartServerHTTPMedium that takes care of
        # feeding the bytes in the http request to the smart_protocol_request,
        # but for now it's simpler to just feed the bytes directly.
        smart_protocol_request.accept_bytes(self.rfile.read(data_length))
        assert smart_protocol_request.next_read_size() == 0, (
            "not finished reading, but all data sent to protocol.")
        self.send_header("Content-Length", str(len(out_buffer.getvalue())))
        self.end_headers()
        self.wfile.write(out_buffer.getvalue())


class SingleRangeRequestHandler(TestingHTTPRequestHandler):
    """Always reply to range request as if they were single.

    Don't be explicit about it, just to annoy the clients.
    """

    def get_multiple_ranges(self, file, file_size, ranges):
        """Answer as if it was a single range request and ignores the rest"""
        (start, end) = ranges[0]
        return self.get_single_range(file, file_size, start, end)


class NoRangeRequestHandler(TestingHTTPRequestHandler):
    """Ignore range requests without notice"""

    # Just bypass the range handling done by TestingHTTPRequestHandler
    do_GET = SimpleHTTPRequestHandler.do_GET


class TestCaseWithWebserver(TestCaseWithTransport):
    """A support class that provides readonly urls that are http://.

    This is done by forcing the readonly server to be an http
    one. This will currently fail if the primary transport is not
    backed by regular disk files.
    """
    def setUp(self):
        super(TestCaseWithWebserver, self).setUp()
        self.transport_readonly_server = HttpServer

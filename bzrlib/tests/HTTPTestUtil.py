# Copyright (C) 2005 by Canonical Ltd
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
import socket

from bzrlib.tests import TestCaseWithTransport
from bzrlib.tests.HttpServer import (
    HttpServer,
    TestingHTTPRequestHandler,
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


class TestCaseWithWebserver(TestCaseWithTransport):
    """A support class that provides readonly urls that are http://.

    This is done by forcing the readonly server to be an http
    one. This will currently fail if the primary transport is not
    backed by regular disk files.
    """
    def setUp(self):
        super(TestCaseWithWebserver, self).setUp()
        self.transport_readonly_server = HttpServer

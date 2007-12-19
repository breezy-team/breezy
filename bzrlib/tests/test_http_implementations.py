# Copyright (C) 2007 Canonical Ltd
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

"""Tests for HTTP transports and servers implementations.

(transport, server) implementations tested here are supplied by
HTTPTestProviderAdapter. Note that a server is characterized by a request
handler class.

Transport implementations are normally tested via
test_transport_implementations. The tests here are about the variations in HTTP
protocol implementation to guarantee the robustness of our transports.
"""

import SimpleHTTPServer
import socket

import bzrlib
from bzrlib import (
    errors,
    tests,
    transport,
    )
from bzrlib.tests import (
    http_server,
    http_utils,
    )
from bzrlib.transport.http._urllib import HttpTransport_urllib


try:
    from bzrlib.transport.http._pycurl import PyCurlTransport
    pycurl_present = True
except errors.DependencyNotPresent:
    pycurl_present = False

class HTTPImplementationsTestProviderAdapter(tests.TestScenarioApplier):

    def __init__(self):
        transport_scenarios = [('urllib',
                                dict(_transport=HttpTransport_urllib,
                                     _server=http_server.HttpServer_urllib,
                                     _qualified_prefix='http+urllib',
                                     )),]
        if pycurl_present:
            transport_scenarios.append(
                ('pycurl', dict(_transport=PyCurlTransport,
                                _server=http_server.HttpServer_PyCurl,
                                _qualified_prefix='http+pycurl',
                                )))
        self.scenarios = transport_scenarios


def load_tests(standard_tests, module, loader):
    """Multiply tests for http clients and protocol versions."""
    adapter = HTTPImplementationsTestProviderAdapter()
    result = loader.suiteClass()
    for test in tests.iter_suite_tests(standard_tests):
        result.addTests(adapter.adapt(test))
    return result


class TestHttpTransportUrls(tests.TestCase):
    """Test the http urls."""

    def test_abs_url(self):
        """Construction of absolute http URLs"""
        t = self._transport('http://bazaar-vcs.org/bzr/bzr.dev/')
        eq = self.assertEqualDiff
        eq(t.abspath('.'), 'http://bazaar-vcs.org/bzr/bzr.dev')
        eq(t.abspath('foo/bar'), 'http://bazaar-vcs.org/bzr/bzr.dev/foo/bar')
        eq(t.abspath('.bzr'), 'http://bazaar-vcs.org/bzr/bzr.dev/.bzr')
        eq(t.abspath('.bzr/1//2/./3'),
           'http://bazaar-vcs.org/bzr/bzr.dev/.bzr/1/2/3')

    def test_invalid_http_urls(self):
        """Trap invalid construction of urls"""
        t = self._transport('http://bazaar-vcs.org/bzr/bzr.dev/')
        self.assertRaises(errors.InvalidURL,
                          self._transport,
                          'http://http://bazaar-vcs.org/bzr/bzr.dev/')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = self._transport('http://bzr.ozlabs.org/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://bzr.ozlabs.org/.bzr/tree-version')

    def test_http_impl_urls(self):
        """There are servers which ask for particular clients to connect"""
        server = self._server()
        try:
            server.setUp()
            url = server.get_url()
            self.assertTrue(url.startswith('%s://' % self._qualified_prefix))
        finally:
            server.tearDown()


class TestHttpConnections(http_utils.TestCaseWithWebserver):
    """Test the http connections."""

    def setUp(self):
        http_utils.TestCaseWithWebserver.setUp(self)
        self.build_tree(['foo/', 'foo/bar'], line_endings='binary',
                        transport=self.get_transport())

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertEqual(t.has('foo/bar'), True)
        self.assertEqual(len(server.logs), 1)
        self.assertContainsRe(server.logs[0],
            r'"HEAD /foo/bar HTTP/1.." (200|302) - "-" "bzr/')

    def test_http_has_not_found(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertEqual(t.has('not-found'), False)
        self.assertContainsRe(server.logs[1],
            r'"HEAD /not-found HTTP/1.." 404 - "-" "bzr/')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        fp = t.get('foo/bar')
        self.assertEqualDiff(
            fp.read(),
            'contents of foo/bar\n')
        self.assertEqual(len(server.logs), 1)
        self.assertTrue(server.logs[0].find(
            '"GET /foo/bar HTTP/1.1" 200 - "-" "bzr/%s'
            % bzrlib.__version__) > -1)

    def test_get_smart_medium(self):
        # For HTTP, get_smart_medium should return the transport object.
        server = self.get_readonly_server()
        http_transport = self._transport(server.get_url())
        medium = http_transport.get_smart_medium()
        self.assertIs(medium, http_transport)

    def test_has_on_bogus_host(self):
        # Get a free address and don't 'accept' on it, so that we
        # can be sure there is no http handler there, but set a
        # reasonable timeout to not slow down tests too much.
        default_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(2)
            s = socket.socket()
            s.bind(('localhost', 0))
            t = self._transport('http://%s:%s/' % s.getsockname())
            self.assertRaises(errors.ConnectionError, t.has, 'foo/bar')
        finally:
            socket.setdefaulttimeout(default_timeout)


class TestPost(tests.TestCase):

    def test_post_body_is_received(self):
        server = http_utils.RecordingServer(expect_body_tail='end-of-body')
        server.setUp()
        self.addCleanup(server.tearDown)
        scheme = self._qualified_prefix
        url = '%s://%s:%s/' % (scheme, server.host, server.port)
        try:
            http_transport = transport.get_transport(url)
        except errors.UnsupportedProtocol:
            raise tests.TestSkipped('%s not available' % scheme)
        code, response = http_transport._post('abc def end-of-body')
        self.assertTrue(
            server.received_bytes.startswith('POST /.bzr/smart HTTP/1.'))
        self.assertTrue('content-length: 19\r' in server.received_bytes.lower())
        # The transport should not be assuming that the server can accept
        # chunked encoding the first time it connects, because HTTP/1.1, so we
        # check for the literal string.
        self.assertTrue(
            server.received_bytes.endswith('\r\n\r\nabc def end-of-body'))


class TestHttpTransportRegistration(tests.TestCase):
    """Test registrations of various http implementations"""

    def test_http_registered(self):
        t = transport.get_transport('%s://foo.com/' % self._qualified_prefix)
        self.assertIsInstance(t, transport.Transport)
        self.assertIsInstance(t, self._transport)


class TestSpecificRequestHandler(http_utils.TestCaseWithWebserver):
    """Tests a specific request handler.


    Daughter class are expected to override _req_handler_class
    """

    # Provide a useful default
    _req_handler_class = http_server.TestingHTTPRequestHandler

    def create_transport_readonly_server(self):
        return http_server.HttpServer(self._req_handler_class)


class WallRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, close the connection"""

    def handle_one_request(self):
        """Handle a single HTTP request, by abruptly closing the connection"""
        self.close_connection = 1


class TestWallServer(TestSpecificRequestHandler):
    """Tests exceptions during the connection phase"""

    _req_handler_class = WallRequestHandler

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # Unfortunately httplib (see HTTPResponse._read_status
        # for details) make no distinction between a closed
        # socket and badly formatted status line, so we can't
        # just test for ConnectionError, we have to test
        # InvalidHttpResponse too.
        self.assertRaises((errors.ConnectionError, errors.InvalidHttpResponse),
                          t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises((errors.ConnectionError, errors.InvalidHttpResponse),
                          t.get, 'foo/bar')


class BadStatusRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, returns a bad status"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = http_server.TestingHTTPRequestHandler.parse_request(self)
        try:
            self.send_response(0, "Bad status")
            self.end_headers()
        except socket.error, e:
            # We don't want to pollute the test results with
            # spurious server errors while test succeed. In our
            # case, it may occur that the test has already read
            # the 'Bad Status' and closed the socket while we are
            # still trying to send some headers... So the test is
            # ok, but if we raise the exception, the output is
            # dirty. So we don't raise, but we close the
            # connection, just to be safe :)
            spurious = [errno.EPIPE,
                        errno.ECONNRESET,
                        errno.ECONNABORTED,
                        ]
            if (len(e.args) > 0) and (e.args[0] in spurious):
                self.close_connection = 1
                pass
            else:
                raise
        return False


class TestBadStatusServer(TestSpecificRequestHandler):
    """Tests bad status from server."""

    _req_handler_class = BadStatusRequestHandler

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'foo/bar')


class InvalidStatusRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, returns am invalid status"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = http_server.TestingHTTPRequestHandler.parse_request(self)
        self.wfile.write("Invalid status line\r\n")
        return False


class TestInvalidStatusServer(TestBadStatusServer):
    """Tests invalid status from server.

    Both implementations raises the same error as for a bad status.
    """

    _req_handler_class = InvalidStatusRequestHandler


class BadProtocolRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, returns a bad protocol version"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = http_server.TestingHTTPRequestHandler.parse_request(self)
        # Returns an invalid protocol version, but curl just
        # ignores it and those cannot be tested.
        self.wfile.write("%s %d %s\r\n" % ('HTTP/0.0',
                                           404,
                                           'Look at my protocol version'))
        return False


class TestBadProtocolServer(TestSpecificRequestHandler):
    """Tests bad protocol from server."""

    _req_handler_class = BadProtocolRequestHandler

    def setUp(self):
        if pycurl_present and self._transport == PyCurlTransport:
            raise tests.TestNotApplicable(
                "pycurl doesn't check the protocol version")
        super(TestBadProtocolServer, self).setUp()

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'foo/bar')


class ForbiddenRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, returns a 403 code"""

    def parse_request(self):
        """Handle a single HTTP request, by replying we cannot handle it"""
        ignored = http_server.TestingHTTPRequestHandler.parse_request(self)
        self.send_error(403)
        return False


class TestForbiddenServer(TestSpecificRequestHandler):
    """Tests forbidden server"""

    _req_handler_class = ForbiddenRequestHandler

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.TransportError, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.TransportError, t.get, 'foo/bar')


class TestRangeRequestServer(TestSpecificRequestHandler):
    """Tests readv requests against server.

    We test against default "normal" server.
    """

    def setUp(self):
        super(TestRangeRequestServer, self).setUp()
        self.build_tree_contents([('a', '0123456789')],)

    def test_readv(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        l = list(t.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (3, '34'))
        self.assertEqual(l[3], (9, '9'))

    def test_readv_out_of_order(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        l = list(t.readv('a', ((1, 1), (9, 1), (0, 1), (3, 2))))
        self.assertEqual(l[0], (1, '1'))
        self.assertEqual(l[1], (9, '9'))
        self.assertEqual(l[2], (0, '0'))
        self.assertEqual(l[3], (3, '34'))

    def test_readv_invalid_ranges(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())

        # This is intentionally reading off the end of the file
        # since we are sure that it cannot get there
        self.assertListRaises((errors.InvalidRange, errors.ShortReadvError,),
                              t.readv, 'a', [(1,1), (8,10)])

        # This is trying to seek past the end of the file, it should
        # also raise a special error
        self.assertListRaises((errors.InvalidRange, errors.ShortReadvError,),
                              t.readv, 'a', [(12,2)])

    def test_readv_multiple_get_requests(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # force transport to issue multiple requests
        t._max_readv_combine = 1
        t._max_get_ranges = 1
        l = list(t.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (3, '34'))
        self.assertEqual(l[3], (9, '9'))
        # The server should have issued 4 requests
        self.assertEqual(4, server.GET_request_nb)

    def test_readv_get_max_size(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # force transport to issue multiple requests by limiting the number of
        # bytes by request. Note that this apply to coalesced offsets only, a
        # single range ill keep its size even if bigger than the limit.
        t._get_max_size = 2
        l = list(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (2, '2345'))
        self.assertEqual(l[3], (6, '6789'))
        # The server should have issued 3 requests
        self.assertEqual(3, server.GET_request_nb)


class SingleRangeRequestHandler(http_server.TestingHTTPRequestHandler):
    """Always reply to range request as if they were single.

    Don't be explicit about it, just to annoy the clients.
    """

    def get_multiple_ranges(self, file, file_size, ranges):
        """Answer as if it was a single range request and ignores the rest"""
        (start, end) = ranges[0]
        return self.get_single_range(file, file_size, start, end)


class TestSingleRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which accept only single range requests"""

    _req_handler_class = SingleRangeRequestHandler


class SingleOnlyRangeRequestHandler(http_server.TestingHTTPRequestHandler):
    """Only reply to simple range requests, errors out on multiple"""

    def get_multiple_ranges(self, file, file_size, ranges):
        """Refuses the multiple ranges request"""
        if len(ranges) > 1:
            file.close()
            self.send_error(416, "Requested range not satisfiable")
            return
        (start, end) = ranges[0]
        return self.get_single_range(file, file_size, start, end)


class TestSingleOnlyRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which only accept single range requests"""

    _req_handler_class = SingleOnlyRangeRequestHandler


class NoRangeRequestHandler(http_server.TestingHTTPRequestHandler):
    """Ignore range requests without notice"""

    def do_GET(self):
        # Update the statistics
        self.server.test_case_server.GET_request_nb += 1
        # Just bypass the range handling done by TestingHTTPRequestHandler
        return SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)


class TestNoRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which do not accept range requests"""

    _req_handler_class = NoRangeRequestHandler


class LimitedRangeRequestHandler(http_server.TestingHTTPRequestHandler):
    """Errors out when range specifiers exceed the limit"""

    def get_multiple_ranges(self, file, file_size, ranges):
        """Refuses the multiple ranges request"""
        tcs = self.server.test_case_server
        if tcs.range_limit is not None and len(ranges) > tcs.range_limit:
            file.close()
            # Emulate apache behavior
            self.send_error(400, "Bad Request")
            return
        return http_server.TestingHTTPRequestHandler.get_multiple_ranges(
            self, file, file_size, ranges)


class LimitedRangeHTTPServer(http_server.HttpServer):
    """An HttpServer erroring out on requests with too much range specifiers"""

    def __init__(self, request_handler=LimitedRangeRequestHandler,
                 range_limit=None):
        http_server.HttpServer.__init__(self, request_handler)
        self.range_limit = range_limit


class TestLimitedRangeRequestServer(http_utils.TestCaseWithWebserver):
    """Tests readv requests against a server erroring out on too much ranges."""

    range_limit = 3

    def create_transport_readonly_server(self):
        # Requests with more range specifiers will error out
        return LimitedRangeHTTPServer(range_limit=self.range_limit)

    def get_transport(self):
        return self._transport(self.get_readonly_server().get_url())

    def setUp(self):
        http_utils.TestCaseWithWebserver.setUp(self)
        # We need to manipulate ranges that correspond to real chunks in the
        # response, so we build a content appropriately.
        filler = ''.join(['abcdefghij' for x in range(102)])
        content = ''.join(['%04d' % v + filler for v in range(16)])
        self.build_tree_contents([('a', content)],)

    def test_few_ranges(self):
        t = self.get_transport()
        l = list(t.readv('a', ((0, 4), (1024, 4), )))
        self.assertEqual(l[0], (0, '0000'))
        self.assertEqual(l[1], (1024, '0001'))
        self.assertEqual(1, self.get_readonly_server().GET_request_nb)

    def test_more_ranges(self):
        t = self.get_transport()
        l = list(t.readv('a', ((0, 4), (1024, 4), (4096, 4), (8192, 4))))
        self.assertEqual(l[0], (0, '0000'))
        self.assertEqual(l[1], (1024, '0001'))
        self.assertEqual(l[2], (4096, '0004'))
        self.assertEqual(l[3], (8192, '0008'))
        # The server will refuse to serve the first request (too much ranges),
        # a second request will succeeds.
        self.assertEqual(2, self.get_readonly_server().GET_request_nb)



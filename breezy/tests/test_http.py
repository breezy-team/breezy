# Copyright (C) 2005-2012, 2015, 2016, 2017 Canonical Ltd
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

"""Tests for HTTP implementations.

This module defines a load_tests() method that parametrize tests classes for
transport implementation, http protocol versions and authentication schemes.
"""

# TODO: Should be renamed to breezy.transport.http.tests?
# TODO: What about renaming to breezy.tests.transport.http ?

from http.client import UnknownProtocol, parse_headers
from http.server import SimpleHTTPRequestHandler
import io
import socket
import sys
import threading

import breezy
from .. import (
    config,
    controldir,
    debug,
    errors,
    osutils,
    tests,
    trace,
    transport,
    ui,
    urlutils,
    )
from ..bzr import (
    remote as _mod_remote,
    )
from . import (
    features,
    http_server,
    http_utils,
    test_server,
    )
from .scenarios import (
    load_tests_apply_scenarios,
    multiply_scenarios,
    )
from ..transport import (
    remote,
    )
from ..transport.http import urllib
from ..transport.http.urllib import (
    AbstractAuthHandler,
    BasicAuthHandler,
    HttpTransport,
    HTTPAuthHandler,
    HTTPConnection,
    HTTPSConnection,
    ProxyHandler,
    Request,
    )


load_tests = load_tests_apply_scenarios


def vary_by_http_client_implementation():
    """Test the libraries we can use, currently just urllib."""
    transport_scenarios = [
        ('urllib', dict(_transport=HttpTransport,
                        _server=http_server.HttpServer,
                        _url_protocol='http',)),
        ]
    return transport_scenarios


def vary_by_http_protocol_version():
    """Test on http/1.0 and 1.1"""
    return [
        ('HTTP/1.0', dict(_protocol_version='HTTP/1.0')),
        ('HTTP/1.1', dict(_protocol_version='HTTP/1.1')),
        ]


def vary_by_http_auth_scheme():
    scenarios = [
        ('basic', dict(_auth_server=http_utils.HTTPBasicAuthServer)),
        ('digest', dict(_auth_server=http_utils.HTTPDigestAuthServer)),
        ('basicdigest',
            dict(_auth_server=http_utils.HTTPBasicAndDigestAuthServer)),
        ]
    # Add some attributes common to all scenarios
    for scenario_id, scenario_dict in scenarios:
        scenario_dict.update(_auth_header='Authorization',
                             _username_prompt_prefix='',
                             _password_prompt_prefix='')
    return scenarios


def vary_by_http_proxy_auth_scheme():
    scenarios = [
        ('proxy-basic', dict(_auth_server=http_utils.ProxyBasicAuthServer)),
        ('proxy-digest', dict(_auth_server=http_utils.ProxyDigestAuthServer)),
        ('proxy-basicdigest',
            dict(_auth_server=http_utils.ProxyBasicAndDigestAuthServer)),
        ]
    # Add some attributes common to all scenarios
    for scenario_id, scenario_dict in scenarios:
        scenario_dict.update(_auth_header='Proxy-Authorization',
                             _username_prompt_prefix='Proxy ',
                             _password_prompt_prefix='Proxy ')
    return scenarios


def vary_by_http_activity():
    activity_scenarios = [
        ('urllib,http', dict(_activity_server=ActivityHTTPServer,
                             _transport=HttpTransport,)),
        ]
    if features.HTTPSServerFeature.available():
        # FIXME: Until we have a better way to handle self-signed certificates
        # (like allowing them in a test specific authentication.conf for
        # example), we need some specialized urllib transport for tests.
        # -- vila 2012-01-20
        from . import (
            ssl_certs,
            )

        class HTTPS_transport(HttpTransport):

            def __init__(self, base, _from_transport=None):
                super(HTTPS_transport, self).__init__(
                    base, _from_transport=_from_transport,
                    ca_certs=ssl_certs.build_path('ca.crt'))

        activity_scenarios.append(
            ('urllib,https', dict(_activity_server=ActivityHTTPSServer,
                                  _transport=HTTPS_transport,)),)
    return activity_scenarios


class FakeManager(object):

    def __init__(self):
        self.credentials = []

    def add_password(self, realm, host, username, password):
        self.credentials.append([realm, host, username, password])


class RecordingServer(object):
    """A fake HTTP server.

    It records the bytes sent to it, and replies with a 200.
    """

    def __init__(self, expect_body_tail=None, scheme=''):
        """Constructor.

        :type expect_body_tail: str
        :param expect_body_tail: a reply won't be sent until this string is
            received.
        """
        self._expect_body_tail = expect_body_tail
        self.host = None
        self.port = None
        self.received_bytes = b''
        self.scheme = scheme

    def get_url(self):
        return '%s://%s:%s/' % (self.scheme, self.host, self.port)

    def start_server(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(('127.0.0.1', 0))
        self.host, self.port = self._sock.getsockname()
        self._ready = threading.Event()
        self._thread = test_server.TestThread(
            sync_event=self._ready, target=self._accept_read_and_reply)
        self._thread.start()
        if 'threads' in tests.selftest_debug_flags:
            sys.stderr.write('Thread started: %s\n' % (self._thread.ident,))
        self._ready.wait()

    def _accept_read_and_reply(self):
        self._sock.listen(1)
        self._ready.set()
        conn, address = self._sock.accept()
        if self._expect_body_tail is not None:
            while not self.received_bytes.endswith(self._expect_body_tail):
                self.received_bytes += conn.recv(4096)
            conn.sendall(b'HTTP/1.1 200 OK\r\n')
        try:
            self._sock.close()
        except socket.error:
            # The client may have already closed the socket.
            pass

    def stop_server(self):
        try:
            # Issue a fake connection to wake up the server and allow it to
            # finish quickly
            fake_conn = osutils.connect_socket((self.host, self.port))
            fake_conn.close()
        except socket.error:
            # We might have already closed it.  We don't care.
            pass
        self.host = None
        self.port = None
        self._thread.join()
        if 'threads' in tests.selftest_debug_flags:
            sys.stderr.write('Thread  joined: %s\n' % (self._thread.ident,))


class TestAuthHeader(tests.TestCase):

    def parse_header(self, header, auth_handler_class=None):
        if auth_handler_class is None:
            auth_handler_class = AbstractAuthHandler
        self.auth_handler = auth_handler_class()
        return self.auth_handler._parse_auth_header(header)

    def test_empty_header(self):
        scheme, remainder = self.parse_header('')
        self.assertEqual('', scheme)
        self.assertIs(None, remainder)

    def test_negotiate_header(self):
        scheme, remainder = self.parse_header('Negotiate')
        self.assertEqual('negotiate', scheme)
        self.assertIs(None, remainder)

    def test_basic_header(self):
        scheme, remainder = self.parse_header(
            'Basic realm="Thou should not pass"')
        self.assertEqual('basic', scheme)
        self.assertEqual('realm="Thou should not pass"', remainder)

    def test_build_basic_header_with_long_creds(self):
        handler = BasicAuthHandler()
        user = 'user' * 10  # length 40
        password = 'password' * 5  # length 40
        header = handler.build_auth_header(
            dict(user=user, password=password), None)
        # https://bugs.launchpad.net/bzr/+bug/1606203 was caused by incorrectly
        # creating a header value with an embedded '\n'
        self.assertFalse('\n' in header)

    def test_basic_extract_realm(self):
        scheme, remainder = self.parse_header(
            'Basic realm="Thou should not pass"',
            BasicAuthHandler)
        match, realm = self.auth_handler.extract_realm(remainder)
        self.assertTrue(match is not None)
        self.assertEqual(u'Thou should not pass', realm)

    def test_digest_header(self):
        scheme, remainder = self.parse_header(
            'Digest realm="Thou should not pass"')
        self.assertEqual('digest', scheme)
        self.assertEqual('realm="Thou should not pass"', remainder)


class TestHTTPRangeParsing(tests.TestCase):

    def setUp(self):
        super(TestHTTPRangeParsing, self).setUp()
        # We focus on range  parsing here and ignore everything else

        class RequestHandler(http_server.TestingHTTPRequestHandler):
            def setup(self): pass

            def handle(self): pass

            def finish(self): pass

        self.req_handler = RequestHandler(None, None, None)

    def assertRanges(self, ranges, header, file_size):
        self.assertEqual(ranges,
                         self.req_handler._parse_ranges(header, file_size))

    def test_simple_range(self):
        self.assertRanges([(0, 2)], 'bytes=0-2', 12)

    def test_tail(self):
        self.assertRanges([(8, 11)], 'bytes=-4', 12)

    def test_tail_bigger_than_file(self):
        self.assertRanges([(0, 11)], 'bytes=-99', 12)

    def test_range_without_end(self):
        self.assertRanges([(4, 11)], 'bytes=4-', 12)

    def test_invalid_ranges(self):
        self.assertRanges(None, 'bytes=12-22', 12)
        self.assertRanges(None, 'bytes=1-3,12-22', 12)
        self.assertRanges(None, 'bytes=-', 12)


class TestHTTPServer(tests.TestCase):
    """Test the HTTP servers implementations."""

    def test_invalid_protocol(self):
        class BogusRequestHandler(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/0.1'

        self.assertRaises(UnknownProtocol,
                          http_server.HttpServer, BogusRequestHandler)

    def test_force_invalid_protocol(self):
        self.assertRaises(UnknownProtocol,
                          http_server.HttpServer, protocol_version='HTTP/0.1')

    def test_server_start_and_stop(self):
        server = http_server.HttpServer()
        self.addCleanup(server.stop_server)
        server.start_server()
        self.assertTrue(server.server is not None)
        self.assertTrue(server.server.serving is not None)
        self.assertTrue(server.server.serving)

    def test_create_http_server_one_zero(self):
        class RequestHandlerOneZero(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.0'

        server = http_server.HttpServer(RequestHandlerOneZero)
        self.start_server(server)
        self.assertIsInstance(server.server, http_server.TestingHTTPServer)

    def test_create_http_server_one_one(self):
        class RequestHandlerOneOne(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.1'

        server = http_server.HttpServer(RequestHandlerOneOne)
        self.start_server(server)
        self.assertIsInstance(server.server,
                              http_server.TestingThreadingHTTPServer)

    def test_create_http_server_force_one_one(self):
        class RequestHandlerOneZero(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.0'

        server = http_server.HttpServer(RequestHandlerOneZero,
                                        protocol_version='HTTP/1.1')
        self.start_server(server)
        self.assertIsInstance(server.server,
                              http_server.TestingThreadingHTTPServer)

    def test_create_http_server_force_one_zero(self):
        class RequestHandlerOneOne(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.1'

        server = http_server.HttpServer(RequestHandlerOneOne,
                                        protocol_version='HTTP/1.0')
        self.start_server(server)
        self.assertIsInstance(server.server,
                              http_server.TestingHTTPServer)


class TestHttpTransportUrls(tests.TestCase):
    """Test the http urls."""

    scenarios = vary_by_http_client_implementation()

    def test_abs_url(self):
        """Construction of absolute http URLs"""
        t = self._transport('http://example.com/bzr/bzr.dev/')
        eq = self.assertEqualDiff
        eq(t.abspath('.'), 'http://example.com/bzr/bzr.dev')
        eq(t.abspath('foo/bar'), 'http://example.com/bzr/bzr.dev/foo/bar')
        eq(t.abspath('.bzr'), 'http://example.com/bzr/bzr.dev/.bzr')
        eq(t.abspath('.bzr/1//2/./3'),
           'http://example.com/bzr/bzr.dev/.bzr/1/2/3')

    def test_invalid_http_urls(self):
        """Trap invalid construction of urls"""
        self._transport('http://example.com/bzr/bzr.dev/')
        self.assertRaises(urlutils.InvalidURL,
                          self._transport,
                          'http://example.com:port/bzr/bzr.dev/')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = self._transport('http://example.com/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://example.com/.bzr/tree-version')

    def test_http_impl_urls(self):
        """There are servers which ask for particular clients to connect"""
        server = self._server()
        server.start_server()
        try:
            url = server.get_url()
            self.assertTrue(url.startswith('%s://' % self._url_protocol))
        finally:
            server.stop_server()


class TestHTTPConnections(http_utils.TestCaseWithWebserver):
    """Test the http connections."""

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(TestHTTPConnections, self).setUp()
        self.build_tree(['foo/', 'foo/bar'], line_endings='binary',
                        transport=self.get_transport())

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        self.assertEqual(t.has('foo/bar'), True)
        self.assertEqual(len(server.logs), 1)
        self.assertContainsRe(server.logs[0],
                              r'"HEAD /foo/bar HTTP/1.." (200|302) - "-" "Breezy/')

    def test_http_has_not_found(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        self.assertEqual(t.has('not-found'), False)
        self.assertContainsRe(server.logs[1],
                              r'"HEAD /not-found HTTP/1.." 404 - "-" "Breezy/')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        fp = t.get('foo/bar')
        self.assertEqualDiff(
            fp.read(),
            b'contents of foo/bar\n')
        self.assertEqual(len(server.logs), 1)
        self.assertTrue(server.logs[0].find(
            '"GET /foo/bar HTTP/1.1" 200 - "-" "Breezy/%s'
            % breezy.__version__) > -1)

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


class TestHttpTransportRegistration(tests.TestCase):
    """Test registrations of various http implementations"""

    scenarios = vary_by_http_client_implementation()

    def test_http_registered(self):
        t = transport.get_transport_from_url(
            '%s://foo.com/' % self._url_protocol)
        self.assertIsInstance(t, transport.Transport)
        self.assertIsInstance(t, self._transport)


class TestPost(tests.TestCase):

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def test_post_body_is_received(self):
        server = RecordingServer(expect_body_tail=b'end-of-body',
                                 scheme=self._url_protocol)
        self.start_server(server)
        url = server.get_url()
        # FIXME: needs a cleanup -- vila 20100611
        http_transport = transport.get_transport_from_url(url)
        code, response = http_transport._post(b'abc def end-of-body')
        self.assertTrue(
            server.received_bytes.startswith(b'POST /.bzr/smart HTTP/1.'))
        self.assertTrue(
            b'content-length: 19\r' in server.received_bytes.lower())
        self.assertTrue(b'content-type: application/octet-stream\r'
                        in server.received_bytes.lower())
        # The transport should not be assuming that the server can accept
        # chunked encoding the first time it connects, because HTTP/1.1, so we
        # check for the literal string.
        self.assertTrue(
            server.received_bytes.endswith(b'\r\n\r\nabc def end-of-body'))


class TestRangeHeader(tests.TestCase):
    """Test range_header method"""

    def check_header(self, value, ranges=[], tail=0):
        offsets = [(start, end - start + 1) for start, end in ranges]
        coalesce = transport.Transport._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        range_header = HttpTransport._range_header
        self.assertEqual(value, range_header(coalesced, tail))

    def test_range_header_single(self):
        self.check_header('0-9', ranges=[(0, 9)])
        self.check_header('100-109', ranges=[(100, 109)])

    def test_range_header_tail(self):
        self.check_header('-10', tail=10)
        self.check_header('-50', tail=50)

    def test_range_header_multi(self):
        self.check_header('0-9,100-200,300-5000',
                          ranges=[(0, 9), (100, 200), (300, 5000)])

    def test_range_header_mixed(self):
        self.check_header('0-9,300-5000,-50',
                          ranges=[(0, 9), (300, 5000)],
                          tail=50)


class TestSpecificRequestHandler(http_utils.TestCaseWithWebserver):
    """Tests a specific request handler.

    Daughter classes are expected to override _req_handler_class
    """

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    # Provide a useful default
    _req_handler_class = http_server.TestingHTTPRequestHandler

    def create_transport_readonly_server(self):
        server = http_server.HttpServer(self._req_handler_class,
                                        protocol_version=self._protocol_version)
        server._url_protocol = self._url_protocol
        return server


class WallRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, close the connection"""

    def _handle_one_request(self):
        """Handle a single HTTP request, by abruptly closing the connection"""
        self.close_connection = 1


class TestWallServer(TestSpecificRequestHandler):
    """Tests exceptions during the connection phase"""

    _req_handler_class = WallRequestHandler

    def test_http_has(self):
        t = self.get_readonly_transport()
        # Unfortunately httplib (see HTTPResponse._read_status
        # for details) make no distinction between a closed
        # socket and badly formatted status line, so we can't
        # just test for ConnectionError, we have to test
        # InvalidHttpResponse too.
        self.assertRaises((errors.ConnectionError,
                           errors.InvalidHttpResponse),
                          t.has, 'foo/bar')

    def test_http_get(self):
        t = self.get_readonly_transport()
        self.assertRaises((errors.ConnectionError, errors.ConnectionReset,
                           errors.InvalidHttpResponse),
                          t.get, 'foo/bar')


class BadStatusRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, returns a bad status"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = http_server.TestingHTTPRequestHandler.parse_request(self)
        self.send_response(0, "Bad status")
        self.close_connection = 1
        return False


class TestBadStatusServer(TestSpecificRequestHandler):
    """Tests bad status from server."""

    _req_handler_class = BadStatusRequestHandler

    def setUp(self):
        super(TestBadStatusServer, self).setUp()
        # See https://bugs.launchpad.net/bzr/+bug/1451448 for details.
        # TD;LR: Running both a TCP client and server in the same process and
        # thread uncovers a race in python. The fix is to run the server in a
        # different process. Trying to fix yet another race here is not worth
        # the effort. -- vila 2015-09-06
        if 'HTTP/1.0' in self.id():
            raise tests.TestSkipped(
                'Client/Server in the same process and thread can hang')

    def test_http_has(self):
        t = self.get_readonly_transport()
        self.assertRaises((errors.ConnectionError, errors.ConnectionReset,
                           errors.InvalidHttpResponse),
                          t.has, 'foo/bar')

    def test_http_get(self):
        t = self.get_readonly_transport()
        self.assertRaises((errors.ConnectionError, errors.ConnectionReset,
                           errors.InvalidHttpResponse),
                          t.get, 'foo/bar')


class InvalidStatusRequestHandler(http_server.TestingHTTPRequestHandler):
    """Whatever request comes in, returns an invalid status"""

    def parse_request(self):
        """Fakes handling a single HTTP request, returns a bad status"""
        ignored = http_server.TestingHTTPRequestHandler.parse_request(self)
        self.wfile.write(b"Invalid status line\r\n")
        # If we don't close the connection pycurl will hang. Since this is a
        # stress test we don't *have* to respect the protocol, but we don't
        # have to sabotage it too much either.
        self.close_connection = True
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
        self.wfile.write(b"%s %d %s\r\n" % (
            b'HTTP/0.0', 404, b'Look at my protocol version'))
        return False


class TestBadProtocolServer(TestSpecificRequestHandler):
    """Tests bad protocol from server."""

    _req_handler_class = BadProtocolRequestHandler

    def test_http_has(self):
        t = self.get_readonly_transport()
        self.assertRaises(errors.InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        t = self.get_readonly_transport()
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
        t = self.get_readonly_transport()
        self.assertRaises(errors.TransportError, t.has, 'foo/bar')

    def test_http_get(self):
        t = self.get_readonly_transport()
        self.assertRaises(errors.TransportError, t.get, 'foo/bar')


class TestRecordingServer(tests.TestCase):

    def test_create(self):
        server = RecordingServer(expect_body_tail=None)
        self.assertEqual(b'', server.received_bytes)
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_setUp_and_stop(self):
        server = RecordingServer(expect_body_tail=None)
        server.start_server()
        try:
            self.assertNotEqual(None, server.host)
            self.assertNotEqual(None, server.port)
        finally:
            server.stop_server()
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_send_receive_bytes(self):
        server = RecordingServer(expect_body_tail=b'c', scheme='http')
        self.start_server(server)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server.host, server.port))
        sock.sendall(b'abc')
        self.assertEqual(b'HTTP/1.1 200 OK\r\n',
                         osutils.recv_all(sock, 4096))
        self.assertEqual(b'abc', server.received_bytes)


class TestRangeRequestServer(TestSpecificRequestHandler):
    """Tests readv requests against server.

    We test against default "normal" server.
    """

    def setUp(self):
        super(TestRangeRequestServer, self).setUp()
        self.build_tree_contents([('a', b'0123456789')],)

    def test_readv(self):
        t = self.get_readonly_transport()
        l = list(t.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(l[0], (0, b'0'))
        self.assertEqual(l[1], (1, b'1'))
        self.assertEqual(l[2], (3, b'34'))
        self.assertEqual(l[3], (9, b'9'))

    def test_readv_out_of_order(self):
        t = self.get_readonly_transport()
        l = list(t.readv('a', ((1, 1), (9, 1), (0, 1), (3, 2))))
        self.assertEqual(l[0], (1, b'1'))
        self.assertEqual(l[1], (9, b'9'))
        self.assertEqual(l[2], (0, b'0'))
        self.assertEqual(l[3], (3, b'34'))

    def test_readv_invalid_ranges(self):
        t = self.get_readonly_transport()

        # This is intentionally reading off the end of the file
        # since we are sure that it cannot get there
        self.assertListRaises((errors.InvalidRange, errors.ShortReadvError,),
                              t.readv, 'a', [(1, 1), (8, 10)])

        # This is trying to seek past the end of the file, it should
        # also raise a special error
        self.assertListRaises((errors.InvalidRange, errors.ShortReadvError,),
                              t.readv, 'a', [(12, 2)])

    def test_readv_multiple_get_requests(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        # force transport to issue multiple requests
        t._max_readv_combine = 1
        t._max_get_ranges = 1
        l = list(t.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(l[0], (0, b'0'))
        self.assertEqual(l[1], (1, b'1'))
        self.assertEqual(l[2], (3, b'34'))
        self.assertEqual(l[3], (9, b'9'))
        # The server should have issued 4 requests
        self.assertEqual(4, server.GET_request_nb)

    def test_readv_get_max_size(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        # force transport to issue multiple requests by limiting the number of
        # bytes by request. Note that this apply to coalesced offsets only, a
        # single range will keep its size even if bigger than the limit.
        t._get_max_size = 2
        l = list(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        self.assertEqual(l[0], (0, b'0'))
        self.assertEqual(l[1], (1, b'1'))
        self.assertEqual(l[2], (2, b'2345'))
        self.assertEqual(l[3], (6, b'6789'))
        # The server should have issued 3 requests
        self.assertEqual(3, server.GET_request_nb)

    def test_complete_readv_leave_pipe_clean(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        # force transport to issue multiple requests
        t._get_max_size = 2
        list(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        # The server should have issued 3 requests
        self.assertEqual(3, server.GET_request_nb)
        self.assertEqual(b'0123456789', t.get_bytes('a'))
        self.assertEqual(4, server.GET_request_nb)

    def test_incomplete_readv_leave_pipe_clean(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        # force transport to issue multiple requests
        t._get_max_size = 2
        # Don't collapse readv results into a list so that we leave unread
        # bytes on the socket
        ireadv = iter(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        self.assertEqual((0, b'0'), next(ireadv))
        # The server should have issued one request so far
        self.assertEqual(1, server.GET_request_nb)
        self.assertEqual(b'0123456789', t.get_bytes('a'))
        # get_bytes issued an additional request, the readv pending ones are
        # lost
        self.assertEqual(2, server.GET_request_nb)


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
        return SimpleHTTPRequestHandler.do_GET(self)


class TestNoRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which do not accept range requests"""

    _req_handler_class = NoRangeRequestHandler


class MultipleRangeWithoutContentLengthRequestHandler(
        http_server.TestingHTTPRequestHandler):
    """Reply to multiple range requests without content length header."""

    def get_multiple_ranges(self, file, file_size, ranges):
        self.send_response(206)
        self.send_header('Accept-Ranges', 'bytes')
        # XXX: this is strange; the 'random' name below seems undefined and
        # yet the tests pass -- mbp 2010-10-11 bug 658773
        boundary = "%d" % random.randint(0, 0x7FFFFFFF)
        self.send_header("Content-Type",
                         "multipart/byteranges; boundary=%s" % boundary)
        self.end_headers()
        for (start, end) in ranges:
            self.wfile.write(b"--%s\r\n" % boundary.encode('ascii'))
            self.send_header("Content-type", 'application/octet-stream')
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start,
                                                                  end,
                                                                  file_size))
            self.end_headers()
            self.send_range_content(file, start, end - start + 1)
        # Final boundary
        self.wfile.write(b"--%s\r\n" % boundary)


class TestMultipleRangeWithoutContentLengthServer(TestRangeRequestServer):

    _req_handler_class = MultipleRangeWithoutContentLengthRequestHandler


class TruncatedMultipleRangeRequestHandler(
        http_server.TestingHTTPRequestHandler):
    """Reply to multiple range requests truncating the last ones.

    This server generates responses whose Content-Length describes all the
    ranges, but fail to include the last ones leading to client short reads.
    This has been observed randomly with lighttpd (bug #179368).
    """

    _truncated_ranges = 2

    def get_multiple_ranges(self, file, file_size, ranges):
        self.send_response(206)
        self.send_header('Accept-Ranges', 'bytes')
        boundary = 'tagada'
        self.send_header('Content-Type',
                         'multipart/byteranges; boundary=%s' % boundary)
        boundary_line = b'--%s\r\n' % boundary.encode('ascii')
        # Calculate the Content-Length
        content_length = 0
        for (start, end) in ranges:
            content_length += len(boundary_line)
            content_length += self._header_line_length(
                'Content-type', 'application/octet-stream')
            content_length += self._header_line_length(
                'Content-Range', 'bytes %d-%d/%d' % (start, end, file_size))
            content_length += len('\r\n')  # end headers
            content_length += end - start  # + 1
        content_length += len(boundary_line)
        self.send_header('Content-length', content_length)
        self.end_headers()

        # Send the multipart body
        cur = 0
        for (start, end) in ranges:
            self.wfile.write(boundary_line)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Content-Range', 'bytes %d-%d/%d'
                             % (start, end, file_size))
            self.end_headers()
            if cur + self._truncated_ranges >= len(ranges):
                # Abruptly ends the response and close the connection
                self.close_connection = 1
                return
            self.send_range_content(file, start, end - start + 1)
            cur += 1
        # Final boundary
        self.wfile.write(boundary_line)


class TestTruncatedMultipleRangeServer(TestSpecificRequestHandler):

    _req_handler_class = TruncatedMultipleRangeRequestHandler

    def setUp(self):
        super(TestTruncatedMultipleRangeServer, self).setUp()
        self.build_tree_contents([('a', b'0123456789')],)

    def test_readv_with_short_reads(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        # Force separate ranges for each offset
        t._bytes_to_read_before_seek = 0
        ireadv = iter(t.readv('a', ((0, 1), (2, 1), (4, 2), (9, 1))))
        self.assertEqual((0, b'0'), next(ireadv))
        self.assertEqual((2, b'2'), next(ireadv))
        # Only one request have been issued so far
        self.assertEqual(1, server.GET_request_nb)
        self.assertEqual((4, b'45'), next(ireadv))
        self.assertEqual((9, b'9'), next(ireadv))
        # We issue 3 requests: two multiple (4 ranges, then 2 ranges) then a
        # single range.
        self.assertEqual(3, server.GET_request_nb)
        # Finally the client have tried a single range request and stays in
        # that mode
        self.assertEqual('single', t._range_hint)


class TruncatedBeforeBoundaryRequestHandler(
        http_server.TestingHTTPRequestHandler):
    """Truncation before a boundary, like in bug 198646"""

    _truncated_ranges = 1

    def get_multiple_ranges(self, file, file_size, ranges):
        self.send_response(206)
        self.send_header('Accept-Ranges', 'bytes')
        boundary = 'tagada'
        self.send_header('Content-Type',
                         'multipart/byteranges; boundary=%s' % boundary)
        boundary_line = b'--%s\r\n' % boundary.encode('ascii')
        # Calculate the Content-Length
        content_length = 0
        for (start, end) in ranges:
            content_length += len(boundary_line)
            content_length += self._header_line_length(
                'Content-type', 'application/octet-stream')
            content_length += self._header_line_length(
                'Content-Range', 'bytes %d-%d/%d' % (start, end, file_size))
            content_length += len('\r\n')  # end headers
            content_length += end - start  # + 1
        content_length += len(boundary_line)
        self.send_header('Content-length', content_length)
        self.end_headers()

        # Send the multipart body
        cur = 0
        for (start, end) in ranges:
            if cur + self._truncated_ranges >= len(ranges):
                # Abruptly ends the response and close the connection
                self.close_connection = 1
                return
            self.wfile.write(boundary_line)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Content-Range', 'bytes %d-%d/%d'
                             % (start, end, file_size))
            self.end_headers()
            self.send_range_content(file, start, end - start + 1)
            cur += 1
        # Final boundary
        self.wfile.write(boundary_line)


class TestTruncatedBeforeBoundary(TestSpecificRequestHandler):
    """Tests the case of bug 198646, disconnecting before a boundary."""

    _req_handler_class = TruncatedBeforeBoundaryRequestHandler

    def setUp(self):
        super(TestTruncatedBeforeBoundary, self).setUp()
        self.build_tree_contents([('a', b'0123456789')],)

    def test_readv_with_short_reads(self):
        server = self.get_readonly_server()
        t = self.get_readonly_transport()
        # Force separate ranges for each offset
        t._bytes_to_read_before_seek = 0
        ireadv = iter(t.readv('a', ((0, 1), (2, 1), (4, 2), (9, 1))))
        self.assertEqual((0, b'0'), next(ireadv))
        self.assertEqual((2, b'2'), next(ireadv))
        self.assertEqual((4, b'45'), next(ireadv))
        self.assertEqual((9, b'9'), next(ireadv))


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
                 protocol_version=None,
                 range_limit=None):
        http_server.HttpServer.__init__(self, request_handler,
                                        protocol_version=protocol_version)
        self.range_limit = range_limit


class TestLimitedRangeRequestServer(http_utils.TestCaseWithWebserver):
    """Tests readv requests against a server erroring out on too much ranges."""

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    # Requests with more range specifiers will error out
    range_limit = 3

    def create_transport_readonly_server(self):
        return LimitedRangeHTTPServer(range_limit=self.range_limit,
                                      protocol_version=self._protocol_version)

    def setUp(self):
        super(TestLimitedRangeRequestServer, self).setUp()
        # We need to manipulate ranges that correspond to real chunks in the
        # response, so we build a content appropriately.
        filler = b''.join([b'abcdefghij' for x in range(102)])
        content = b''.join([b'%04d' % v + filler for v in range(16)])
        self.build_tree_contents([('a', content)],)

    def test_few_ranges(self):
        t = self.get_readonly_transport()
        l = list(t.readv('a', ((0, 4), (1024, 4), )))
        self.assertEqual(l[0], (0, b'0000'))
        self.assertEqual(l[1], (1024, b'0001'))
        self.assertEqual(1, self.get_readonly_server().GET_request_nb)

    def test_more_ranges(self):
        t = self.get_readonly_transport()
        l = list(t.readv('a', ((0, 4), (1024, 4), (4096, 4), (8192, 4))))
        self.assertEqual(l[0], (0, b'0000'))
        self.assertEqual(l[1], (1024, b'0001'))
        self.assertEqual(l[2], (4096, b'0004'))
        self.assertEqual(l[3], (8192, b'0008'))
        # The server will refuse to serve the first request (too much ranges),
        # a second request will succeed.
        self.assertEqual(2, self.get_readonly_server().GET_request_nb)


class TestHttpProxyWhiteBox(tests.TestCase):
    """Whitebox test proxy http authorization.

    Only the urllib implementation is tested here.
    """

    def _proxied_request(self):
        handler = ProxyHandler()
        request = Request('GET', 'http://baz/buzzle')
        handler.set_proxy(request, 'http')
        return request

    def assertEvaluateProxyBypass(self, expected, host, no_proxy):
        handler = ProxyHandler()
        self.assertEqual(expected,
                         handler.evaluate_proxy_bypass(host, no_proxy))

    def test_empty_user(self):
        self.overrideEnv('http_proxy', 'http://bar.com')
        request = self._proxied_request()
        self.assertFalse('Proxy-authorization' in request.headers)

    def test_user_with_at(self):
        self.overrideEnv('http_proxy',
                         'http://username@domain:password@proxy_host:1234')
        request = self._proxied_request()
        self.assertFalse('Proxy-authorization' in request.headers)

    def test_invalid_proxy(self):
        """A proxy env variable without scheme"""
        self.overrideEnv('http_proxy', 'host:1234')
        self.assertRaises(urlutils.InvalidURL, self._proxied_request)

    def test_evaluate_proxy_bypass_true(self):
        """The host is not proxied"""
        self.assertEvaluateProxyBypass(True, 'example.com', 'example.com')
        self.assertEvaluateProxyBypass(True, 'bzr.example.com', '*example.com')

    def test_evaluate_proxy_bypass_false(self):
        """The host is proxied"""
        self.assertEvaluateProxyBypass(False, 'bzr.example.com', None)

    def test_evaluate_proxy_bypass_unknown(self):
        """The host is not explicitly proxied"""
        self.assertEvaluateProxyBypass(None, 'example.com', 'not.example.com')
        self.assertEvaluateProxyBypass(None, 'bzr.example.com', 'example.com')

    def test_evaluate_proxy_bypass_empty_entries(self):
        """Ignore empty entries"""
        self.assertEvaluateProxyBypass(None, 'example.com', '')
        self.assertEvaluateProxyBypass(None, 'example.com', ',')
        self.assertEvaluateProxyBypass(None, 'example.com', 'foo,,bar')


class TestProxyHttpServer(http_utils.TestCaseWithTwoWebservers):
    """Tests proxy server.

    Be aware that we do not setup a real proxy here. Instead, we
    check that the *connection* goes through the proxy by serving
    different content (the faked proxy server append '-proxied'
    to the file names).
    """

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    # FIXME: We don't have an https server available, so we don't
    # test https connections. --vila toolongago

    def setUp(self):
        super(TestProxyHttpServer, self).setUp()
        self.transport_secondary_server = http_utils.ProxyServer
        self.build_tree_contents([('foo', b'contents of foo\n'),
                                  ('foo-proxied', b'proxied contents of foo\n')])
        # Let's setup some attributes for tests
        server = self.get_readonly_server()
        self.server_host_port = '%s:%d' % (server.host, server.port)
        self.no_proxy_host = self.server_host_port
        # The secondary server is the proxy
        self.proxy_url = self.get_secondary_url()

    def assertProxied(self):
        t = self.get_readonly_transport()
        self.assertEqual(b'proxied contents of foo\n', t.get('foo').read())

    def assertNotProxied(self):
        t = self.get_readonly_transport()
        self.assertEqual(b'contents of foo\n', t.get('foo').read())

    def test_http_proxy(self):
        self.overrideEnv('http_proxy', self.proxy_url)
        self.assertProxied()

    def test_HTTP_PROXY(self):
        self.overrideEnv('HTTP_PROXY', self.proxy_url)
        self.assertProxied()

    def test_all_proxy(self):
        self.overrideEnv('all_proxy', self.proxy_url)
        self.assertProxied()

    def test_ALL_PROXY(self):
        self.overrideEnv('ALL_PROXY', self.proxy_url)
        self.assertProxied()

    def test_http_proxy_with_no_proxy(self):
        self.overrideEnv('no_proxy', self.no_proxy_host)
        self.overrideEnv('http_proxy', self.proxy_url)
        self.assertNotProxied()

    def test_HTTP_PROXY_with_NO_PROXY(self):
        self.overrideEnv('NO_PROXY', self.no_proxy_host)
        self.overrideEnv('HTTP_PROXY', self.proxy_url)
        self.assertNotProxied()

    def test_all_proxy_with_no_proxy(self):
        self.overrideEnv('no_proxy', self.no_proxy_host)
        self.overrideEnv('all_proxy', self.proxy_url)
        self.assertNotProxied()

    def test_ALL_PROXY_with_NO_PROXY(self):
        self.overrideEnv('NO_PROXY', self.no_proxy_host)
        self.overrideEnv('ALL_PROXY', self.proxy_url)
        self.assertNotProxied()

    def test_http_proxy_without_scheme(self):
        self.overrideEnv('http_proxy', self.server_host_port)
        self.assertRaises(urlutils.InvalidURL, self.assertProxied)


class TestRanges(http_utils.TestCaseWithWebserver):
    """Test the Range header in GET methods."""

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(TestRanges, self).setUp()
        self.build_tree_contents([('a', b'0123456789')],)

    def create_transport_readonly_server(self):
        return http_server.HttpServer(protocol_version=self._protocol_version)

    def _file_contents(self, relpath, ranges):
        t = self.get_readonly_transport()
        offsets = [(start, end - start + 1) for start, end in ranges]
        coalesce = t._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        code, data = t._get(relpath, coalesced)
        self.assertTrue(code in (200, 206), '_get returns: %d' % code)
        for start, end in ranges:
            data.seek(start)
            yield data.read(end - start + 1)

    def _file_tail(self, relpath, tail_amount):
        t = self.get_readonly_transport()
        code, data = t._get(relpath, [], tail_amount)
        self.assertTrue(code in (200, 206), '_get returns: %d' % code)
        data.seek(-tail_amount, 2)
        return data.read(tail_amount)

    def test_range_header(self):
        # Valid ranges
        self.assertEqual(
            [b'0', b'234'], list(self._file_contents('a', [(0, 0), (2, 4)])))

    def test_range_header_tail(self):
        self.assertEqual(b'789', self._file_tail('a', 3))

    def test_syntactically_invalid_range_header(self):
        self.assertListRaises(errors.InvalidHttpRange,
                              self._file_contents, 'a', [(4, 3)])

    def test_semantically_invalid_range_header(self):
        self.assertListRaises(errors.InvalidHttpRange,
                              self._file_contents, 'a', [(42, 128)])


class TestHTTPRedirections(http_utils.TestCaseWithRedirectedWebserver):
    """Test redirection between http servers."""

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(TestHTTPRedirections, self).setUp()
        self.build_tree_contents([('a', b'0123456789'),
                                  ('bundle',
                                   b'# Bazaar revision bundle v0.9\n#\n')
                                  ],)

    def test_redirected(self):
        self.assertRaises(errors.RedirectRequested,
                          self.get_old_transport().get, 'a')
        self.assertEqual(
            b'0123456789',
            self.get_new_transport().get('a').read())


class RedirectedRequest(Request):
    """Request following redirections. """

    init_orig = Request.__init__

    def __init__(self, method, url, *args, **kwargs):
        """Constructor.

        """
        # Since the tests using this class will replace
        # Request, we can't just call the base class __init__
        # or we'll loop.
        RedirectedRequest.init_orig(self, method, url, *args, **kwargs)
        self.follow_redirections = True


def install_redirected_request(test):
    test.overrideAttr(urllib, 'Request', RedirectedRequest)


def cleanup_http_redirection_connections(test):
    # Some sockets are opened but never seen by _urllib, so we trap them at
    # the http level to be able to clean them up.
    def socket_disconnect(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        except socket.error:
            pass

    def connect(connection):
        test.http_connect_orig(connection)
        test.addCleanup(socket_disconnect, connection.sock)
    test.http_connect_orig = test.overrideAttr(
        HTTPConnection, 'connect', connect)

    def connect(connection):
        test.https_connect_orig(connection)
        test.addCleanup(socket_disconnect, connection.sock)
    test.https_connect_orig = test.overrideAttr(
        HTTPSConnection, 'connect', connect)


class TestHTTPSilentRedirections(http_utils.TestCaseWithRedirectedWebserver):
    """Test redirections.

    http implementations do not redirect silently anymore (they
    do not redirect at all in fact). The mechanism is still in
    place at the Request level and these tests
    exercise it.
    """

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(TestHTTPSilentRedirections, self).setUp()
        install_redirected_request(self)
        cleanup_http_redirection_connections(self)
        self.build_tree_contents([('a', b'a'),
                                  ('1/',),
                                  ('1/a', b'redirected once'),
                                  ('2/',),
                                  ('2/a', b'redirected twice'),
                                  ('3/',),
                                  ('3/a', b'redirected thrice'),
                                  ('4/',),
                                  ('4/a', b'redirected 4 times'),
                                  ('5/',),
                                  ('5/a', b'redirected 5 times'),
                                  ],)

    def test_one_redirection(self):
        t = self.get_old_transport()
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = \
            [('(.*)', r'%s/1\1' % (new_prefix), 301), ]
        self.assertEqual(
            b'redirected once',
            t.request('GET', t._remote_path('a'), retries=1).read())

    def test_five_redirections(self):
        t = self.get_old_transport()
        old_prefix = 'http://%s:%s' % (self.old_server.host,
                                       self.old_server.port)
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = [
            ('/1(.*)', r'%s/2\1' % (old_prefix), 302),
            ('/2(.*)', r'%s/3\1' % (old_prefix), 303),
            ('/3(.*)', r'%s/4\1' % (old_prefix), 307),
            ('/4(.*)', r'%s/5\1' % (new_prefix), 301),
            ('(/[^/]+)', r'%s/1\1' % (old_prefix), 301),
            ]
        self.assertEqual(
            b'redirected 5 times',
            t.request('GET', t._remote_path('a'), retries=6).read())


class TestDoCatchRedirections(http_utils.TestCaseWithRedirectedWebserver):
    """Test transport.do_catching_redirections."""

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(TestDoCatchRedirections, self).setUp()
        self.build_tree_contents([('a', b'0123456789'), ],)
        cleanup_http_redirection_connections(self)

        self.old_transport = self.get_old_transport()

    def get_a(self, t):
        return t.get('a')

    def test_no_redirection(self):
        t = self.get_new_transport()

        # We use None for redirected so that we fail if redirected
        self.assertEqual(b'0123456789',
                         transport.do_catching_redirections(
                             self.get_a, t, None).read())

    def test_one_redirection(self):
        self.redirections = 0

        def redirected(t, exception, redirection_notice):
            self.redirections += 1
            redirected_t = t._redirected_to(exception.source, exception.target)
            return redirected_t

        self.assertEqual(b'0123456789',
                         transport.do_catching_redirections(
                             self.get_a, self.old_transport, redirected).read())
        self.assertEqual(1, self.redirections)

    def test_redirection_loop(self):

        def redirected(transport, exception, redirection_notice):
            # By using the redirected url as a base dir for the
            # *old* transport, we create a loop: a => a/a =>
            # a/a/a
            return self.old_transport.clone(exception.target)

        self.assertRaises(errors.TooManyRedirections,
                          transport.do_catching_redirections,
                          self.get_a, self.old_transport, redirected)


def _setup_authentication_config(**kwargs):
    conf = config.AuthenticationConfig()
    conf._get_config().update({'httptest': kwargs})
    conf._save()


class TestUrllib2AuthHandler(tests.TestCaseWithTransport):
    """Unit tests for glue by which urllib2 asks us for authentication"""

    def test_get_user_password_without_port(self):
        """We cope if urllib2 doesn't tell us the port.

        See https://bugs.launchpad.net/bzr/+bug/654684
        """
        user = 'joe'
        password = 'foo'
        _setup_authentication_config(scheme='http', host='localhost',
                                     user=user, password=password)
        handler = HTTPAuthHandler()
        got_pass = handler.get_user_password(dict(
            user='joe',
            protocol='http',
            host='localhost',
            path='/',
            realm=u'Realm',
            ))
        self.assertEqual((user, password), got_pass)


class TestAuth(http_utils.TestCaseWithWebserver):
    """Test authentication scheme"""

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        vary_by_http_auth_scheme(),
        )

    def setUp(self):
        super(TestAuth, self).setUp()
        self.server = self.get_readonly_server()
        self.build_tree_contents([('a', b'contents of a\n'),
                                  ('b', b'contents of b\n'), ])

    def create_transport_readonly_server(self):
        server = self._auth_server(protocol_version=self._protocol_version)
        server._url_protocol = self._url_protocol
        return server

    def get_user_url(self, user, password):
        """Build an url embedding user and password"""
        url = '%s://' % self.server._url_protocol
        if user is not None:
            url += user
            if password is not None:
                url += ':' + password
            url += '@'
        url += '%s:%s/' % (self.server.host, self.server.port)
        return url

    def get_user_transport(self, user, password):
        t = transport.get_transport_from_url(
            self.get_user_url(user, password))
        return t

    def test_no_user(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport(None, None)
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_empty_pass(self):
        self.server.add_user('joe', '')
        t = self.get_user_transport('joe', '')
        self.assertEqual(b'contents of a\n', t.get('a').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_user_pass(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'foo')
        self.assertEqual(b'contents of a\n', t.get('a').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_unknown_user(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('bill', 'foo')
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and 'I don't know you, who are
        # you').
        self.assertEqual(2, self.server.auth_required_errors)

    def test_wrong_pass(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'bar')
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and 'this is not you, who are you')
        self.assertEqual(2, self.server.auth_required_errors)

    def test_prompt_for_username(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport(None, None)
        ui.ui_factory = tests.TestUIFactory(stdin='joe\nfoo\n')
        stdout, stderr = ui.ui_factory.stdout, ui.ui_factory.stderr
        self.assertEqual(b'contents of a\n', t.get('a').read())
        # stdin should be empty
        self.assertEqual('', ui.ui_factory.stdin.readline())
        stderr.seek(0)
        expected_prompt = self._expected_username_prompt(t._unqualified_scheme)
        self.assertEqual(expected_prompt, stderr.read(len(expected_prompt)))
        self.assertEqual('', stdout.getvalue())
        self._check_password_prompt(t._unqualified_scheme, 'joe',
                                    stderr.readline())

    def test_prompt_for_password(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', None)
        ui.ui_factory = tests.TestUIFactory(stdin='foo\n')
        stdout, stderr = ui.ui_factory.stdout, ui.ui_factory.stderr
        self.assertEqual(b'contents of a\n', t.get('a').read())
        # stdin should be empty
        self.assertEqual('', ui.ui_factory.stdin.readline())
        self._check_password_prompt(t._unqualified_scheme, 'joe',
                                    stderr.getvalue())
        self.assertEqual('', stdout.getvalue())
        # And we shouldn't prompt again for a different request
        # against the same transport.
        self.assertEqual(b'contents of b\n', t.get('b').read())
        t2 = t.clone()
        # And neither against a clone
        self.assertEqual(b'contents of b\n', t2.get('b').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def _check_password_prompt(self, scheme, user, actual_prompt):
        expected_prompt = (self._password_prompt_prefix
                           + ("%s %s@%s:%d, Realm: '%s' password: "
                              % (scheme.upper(),
                                 user, self.server.host, self.server.port,
                                 self.server.auth_realm)))
        self.assertEqual(expected_prompt, actual_prompt)

    def _expected_username_prompt(self, scheme):
        return (self._username_prompt_prefix
                + "%s %s:%d, Realm: '%s' username: " % (scheme.upper(),
                                                        self.server.host, self.server.port,
                                                        self.server.auth_realm))

    def test_no_prompt_for_password_when_using_auth_config(self):
        user = ' joe'
        password = 'foo'
        stdin_content = 'bar\n'  # Not the right password
        self.server.add_user(user, password)
        t = self.get_user_transport(user, None)
        ui.ui_factory = tests.TestUIFactory(stdin=stdin_content)
        # Create a minimal config file with the right password
        _setup_authentication_config(scheme='http', port=self.server.port,
                                     user=user, password=password)
        # Issue a request to the server to connect
        with t.get('a') as f:
            self.assertEqual(b'contents of a\n', f.read())
        # stdin should have  been left untouched
        self.assertEqual(stdin_content, ui.ui_factory.stdin.readline())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_changing_nonce(self):
        if self._auth_server not in (http_utils.HTTPDigestAuthServer,
                                     http_utils.ProxyDigestAuthServer):
            raise tests.TestNotApplicable('HTTP/proxy auth digest only test')
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'foo')
        with t.get('a') as f:
            self.assertEqual(b'contents of a\n', f.read())
        with t.get('b') as f:
            self.assertEqual(b'contents of b\n', f.read())
        # Only one 'Authentication Required' error should have
        # occured so far
        self.assertEqual(1, self.server.auth_required_errors)
        # The server invalidates the current nonce
        self.server.auth_nonce = self.server.auth_nonce + '. No, now!'
        self.assertEqual(b'contents of a\n', t.get('a').read())
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and a second 'who are you' with the new nonce)
        self.assertEqual(2, self.server.auth_required_errors)

    def test_user_from_auth_conf(self):
        user = 'joe'
        password = 'foo'
        self.server.add_user(user, password)
        _setup_authentication_config(scheme='http', port=self.server.port,
                                     user=user, password=password)
        t = self.get_user_transport(None, None)
        # Issue a request to the server to connect
        with t.get('a') as f:
            self.assertEqual(b'contents of a\n', f.read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_no_credential_leaks_in_log(self):
        self.overrideAttr(debug, 'debug_flags', {'http'})
        user = 'joe'
        password = 'very-sensitive-password'
        self.server.add_user(user, password)
        t = self.get_user_transport(user, password)
        # Capture the debug calls to mutter
        self.mutters = []

        def mutter(*args):
            lines = args[0] % args[1:]
            # Some calls output multiple lines, just split them now since we
            # care about a single one later.
            self.mutters.extend(lines.splitlines())
        self.overrideAttr(trace, 'mutter', mutter)
        # Issue a request to the server to connect
        self.assertEqual(True, t.has('a'))
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)
        # Since the authentification succeeded, there should be a corresponding
        # debug line
        sent_auth_headers = [line for line in self.mutters
                             if line.startswith('> %s' % (self._auth_header,))]
        self.assertLength(1, sent_auth_headers)
        self.assertStartsWith(sent_auth_headers[0],
                              '> %s: <masked>' % (self._auth_header,))


class TestProxyAuth(TestAuth):
    """Test proxy authentication schemes.

    This inherits from TestAuth to tweak the setUp and filter some failing
    tests.
    """

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        vary_by_http_proxy_auth_scheme(),
        )

    def setUp(self):
        super(TestProxyAuth, self).setUp()
        # Override the contents to avoid false positives
        self.build_tree_contents([('a', b'not proxied contents of a\n'),
                                  ('b', b'not proxied contents of b\n'),
                                  ('a-proxied', b'contents of a\n'),
                                  ('b-proxied', b'contents of b\n'),
                                  ])

    def get_user_transport(self, user, password):
        proxy_url = self.get_user_url(user, password)
        self.overrideEnv('all_proxy', proxy_url)
        return TestAuth.get_user_transport(self, user, password)


class NonClosingBytesIO(io.BytesIO):

    def close(self):
        """Ignore and leave file open."""


class SampleSocket(object):
    """A socket-like object for use in testing the HTTP request handler."""

    def __init__(self, socket_read_content):
        """Constructs a sample socket.

        :param socket_read_content: a byte sequence
        """
        self.readfile = io.BytesIO(socket_read_content)
        self.writefile = NonClosingBytesIO()

    def close(self):
        """Ignore and leave files alone."""

    def sendall(self, bytes):
        self.writefile.write(bytes)

    def makefile(self, mode='r', bufsize=None):
        if 'r' in mode:
            return self.readfile
        else:
            return self.writefile


class SmartHTTPTunnellingTest(tests.TestCaseWithTransport):

    scenarios = multiply_scenarios(
        vary_by_http_client_implementation(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(SmartHTTPTunnellingTest, self).setUp()
        # We use the VFS layer as part of HTTP tunnelling tests.
        self.overrideEnv('BRZ_NO_SMART_VFS', None)
        self.transport_readonly_server = http_utils.HTTPServerWithSmarts
        self.http_server = self.get_readonly_server()

    def create_transport_readonly_server(self):
        server = http_utils.HTTPServerWithSmarts(
            protocol_version=self._protocol_version)
        server._url_protocol = self._url_protocol
        return server

    def test_open_controldir(self):
        branch = self.make_branch('relpath')
        url = self.http_server.get_url() + 'relpath'
        bd = controldir.ControlDir.open(url)
        self.addCleanup(bd.transport.disconnect)
        self.assertIsInstance(bd, _mod_remote.RemoteBzrDir)

    def test_bulk_data(self):
        # We should be able to send and receive bulk data in a single message.
        # The 'readv' command in the smart protocol both sends and receives
        # bulk data, so we use that.
        self.build_tree(['data-file'])
        http_transport = transport.get_transport_from_url(
            self.http_server.get_url())
        medium = http_transport.get_smart_medium()
        # Since we provide the medium, the url below will be mostly ignored
        # during the test, as long as the path is '/'.
        remote_transport = remote.RemoteTransport('bzr://fake_host/',
                                                  medium=medium)
        self.assertEqual(
            [(0, b"c")], list(remote_transport.readv("data-file", [(0, 1)])))

    def test_http_send_smart_request(self):

        post_body = b'hello\n'
        expected_reply_body = b'ok\x012\n'

        http_transport = transport.get_transport_from_url(
            self.http_server.get_url())
        medium = http_transport.get_smart_medium()
        response = medium.send_http_smart_request(post_body)
        reply_body = response.read()
        self.assertEqual(expected_reply_body, reply_body)

    def test_smart_http_server_post_request_handler(self):
        httpd = self.http_server.server

        socket = SampleSocket(
            b'POST /.bzr/smart %s \r\n' % self._protocol_version.encode('ascii') +
            # HTTP/1.1 posts must have a Content-Length (but it doesn't hurt
            # for 1.0)
            b'Content-Length: 6\r\n'
            b'\r\n'
            b'hello\n')
        # Beware: the ('localhost', 80) below is the
        # client_address parameter, but we don't have one because
        # we have defined a socket which is not bound to an
        # address. The test framework never uses this client
        # address, so far...
        request_handler = http_utils.SmartRequestHandler(socket,
                                                         ('localhost', 80),
                                                         httpd)
        response = socket.writefile.getvalue()
        self.assertStartsWith(
            response,
            b'%s 200 ' % self._protocol_version.encode('ascii'))
        # This includes the end of the HTTP headers, and all the body.
        expected_end_of_response = b'\r\n\r\nok\x012\n'
        self.assertEndsWith(response, expected_end_of_response)


class ForbiddenRequestHandler(http_server.TestingHTTPRequestHandler):
    """No smart server here request handler."""

    def do_POST(self):
        self.send_error(403, "Forbidden")


class SmartClientAgainstNotSmartServer(TestSpecificRequestHandler):
    """Test smart client behaviour against an http server without smarts."""

    _req_handler_class = ForbiddenRequestHandler

    def test_probe_smart_server(self):
        """Test error handling against server refusing smart requests."""
        t = self.get_readonly_transport()
        # No need to build a valid smart request here, the server will not even
        # try to interpret it.
        self.assertRaises(errors.SmartProtocolError,
                          t.get_smart_medium().send_http_smart_request,
                          b'whatever')


class Test_redirected_to(tests.TestCase):

    scenarios = vary_by_http_client_implementation()

    def test_redirected_to_subdir(self):
        t = self._transport('http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'http://www.example.com/foo/subdir')
        self.assertIsInstance(r, type(t))
        # Both transports share the some connection
        self.assertEqual(t._get_connection(), r._get_connection())
        self.assertEqual('http://www.example.com/foo/subdir/', r.base)

    def test_redirected_to_self_with_slash(self):
        t = self._transport('http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'http://www.example.com/foo/')
        self.assertIsInstance(r, type(t))
        # Both transports share the some connection (one can argue that we
        # should return the exact same transport here, but that seems
        # overkill).
        self.assertEqual(t._get_connection(), r._get_connection())

    def test_redirected_to_host(self):
        t = self._transport('http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'http://foo.example.com/foo/subdir')
        self.assertIsInstance(r, type(t))
        self.assertEqual('http://foo.example.com/foo/subdir/',
                         r.external_url())

    def test_redirected_to_same_host_sibling_protocol(self):
        t = self._transport('http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'https://www.example.com/foo')
        self.assertIsInstance(r, type(t))
        self.assertEqual('https://www.example.com/foo/',
                         r.external_url())

    def test_redirected_to_same_host_different_protocol(self):
        t = self._transport('http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'bzr://www.example.com/foo')
        self.assertNotEqual(type(r), type(t))
        self.assertEqual('bzr://www.example.com/foo/', r.external_url())

    def test_redirected_to_same_host_specific_implementation(self):
        t = self._transport('http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'https+urllib://www.example.com/foo')
        self.assertEqual('https://www.example.com/foo/', r.external_url())

    def test_redirected_to_different_host_same_user(self):
        t = self._transport('http://joe@www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'https://foo.example.com/foo')
        self.assertIsInstance(r, type(t))
        self.assertEqual(t._parsed_url.user, r._parsed_url.user)
        self.assertEqual('https://joe@foo.example.com/foo/', r.external_url())


class PredefinedRequestHandler(http_server.TestingHTTPRequestHandler):
    """Request handler for a unique and pre-defined request.

    The only thing we care about here is how many bytes travel on the wire. But
    since we want to measure it for a real http client, we have to send it
    correct responses.

    We expect to receive a *single* request nothing more (and we won't even
    check what request it is, we just measure the bytes read until an empty
    line.
    """

    def _handle_one_request(self):
        tcs = self.server.test_case_server
        requestline = self.rfile.readline()
        headers = parse_headers(self.rfile)
        bytes_read = len(headers.as_bytes())
        bytes_read += headers.as_bytes().count(b'\n')
        bytes_read += len(requestline)
        if requestline.startswith(b'POST'):
            # The body should be a single line (or we don't know where it ends
            # and we don't want to issue a blocking read)
            body = self.rfile.readline()
            bytes_read += len(body)
        tcs.bytes_read = bytes_read

        # We set the bytes written *before* issuing the write, the client is
        # supposed to consume every produced byte *before* checking that value.

        # Doing the oppposite may lead to test failure: we may be interrupted
        # after the write but before updating the value. The client can then
        # continue and read the value *before* we can update it. And yes,
        # this has been observed -- vila 20090129
        tcs.bytes_written = len(tcs.canned_response)
        self.wfile.write(tcs.canned_response)


class ActivityServerMixin(object):

    def __init__(self, protocol_version):
        super(ActivityServerMixin, self).__init__(
            request_handler=PredefinedRequestHandler,
            protocol_version=protocol_version)
        # Bytes read and written by the server
        self.bytes_read = 0
        self.bytes_written = 0
        self.canned_response = None


class ActivityHTTPServer(ActivityServerMixin, http_server.HttpServer):
    pass


if features.HTTPSServerFeature.available():
    from . import https_server

    class ActivityHTTPSServer(ActivityServerMixin, https_server.HTTPSServer):
        pass


class TestActivityMixin(object):
    """Test socket activity reporting.

    We use a special purpose server to control the bytes sent and received and
    be able to predict the activity on the client socket.
    """

    def setUp(self):
        self.server = self._activity_server(self._protocol_version)
        self.server.start_server()
        self.addCleanup(self.server.stop_server)
        _activities = {}  # Don't close over self and create a cycle

        def report_activity(t, bytes, direction):
            count = _activities.get(direction, 0)
            count += bytes
            _activities[direction] = count
        self.activities = _activities
        # We override at class level because constructors may propagate the
        # bound method and render instance overriding ineffective (an
        # alternative would be to define a specific ui factory instead...)
        self.overrideAttr(self._transport, '_report_activity', report_activity)

    def get_transport(self):
        t = self._transport(self.server.get_url())
        # FIXME: Needs cleanup -- vila 20100611
        return t

    def assertActivitiesMatch(self):
        self.assertEqual(self.server.bytes_read,
                         self.activities.get('write', 0), 'written bytes')
        self.assertEqual(self.server.bytes_written,
                         self.activities.get('read', 0), 'read bytes')

    def test_get(self):
        self.server.canned_response = b'''HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: 35\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
Bazaar-NG meta directory, format 1
'''
        t = self.get_transport()
        self.assertEqual(b'Bazaar-NG meta directory, format 1\n',
                         t.get('foo/bar').read())
        self.assertActivitiesMatch()

    def test_has(self):
        self.server.canned_response = b'''HTTP/1.1 200 OK\r
Server: SimpleHTTP/0.6 Python/2.5.2\r
Date: Thu, 29 Jan 2009 20:21:47 GMT\r
Content-type: application/octet-stream\r
Content-Length: 20\r
Last-Modified: Thu, 29 Jan 2009 20:21:47 GMT\r
\r
'''
        t = self.get_transport()
        self.assertTrue(t.has('foo/bar'))
        self.assertActivitiesMatch()

    def test_readv(self):
        self.server.canned_response = b'''HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:49:48 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 1534\r
Connection: close\r
Content-Type: multipart/byteranges; boundary=418470f848b63279b\r
\r
\r
--418470f848b63279b\r
Content-type: text/plain; charset=UTF-8\r
Content-range: bytes 0-254/93890\r
\r
mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e7627
mbp@sourcefrog.net-20050309040957-6cad07f466bb0bb8
mbp@sourcefrog.net-20050309041501-c840e09071de3b67
mbp@sourcefrog.net-20050309044615-c24a3250be83220a
\r
--418470f848b63279b\r
Content-type: text/plain; charset=UTF-8\r
Content-range: bytes 1000-2049/93890\r
\r
40-fd4ec249b6b139ab
mbp@sourcefrog.net-20050311063625-07858525021f270b
mbp@sourcefrog.net-20050311231934-aa3776aff5200bb9
mbp@sourcefrog.net-20050311231953-73aeb3a131c3699a
mbp@sourcefrog.net-20050311232353-f5e33da490872c6a
mbp@sourcefrog.net-20050312071639-0a8f59a34a024ff0
mbp@sourcefrog.net-20050312073432-b2c16a55e0d6e9fb
mbp@sourcefrog.net-20050312073831-a47c3335ece1920f
mbp@sourcefrog.net-20050312085412-13373aa129ccbad3
mbp@sourcefrog.net-20050313052251-2bf004cb96b39933
mbp@sourcefrog.net-20050313052856-3edd84094687cb11
mbp@sourcefrog.net-20050313053233-e30a4f28aef48f9d
mbp@sourcefrog.net-20050313053853-7c64085594ff3072
mbp@sourcefrog.net-20050313054757-a86c3f5871069e22
mbp@sourcefrog.net-20050313061422-418f1f73b94879b9
mbp@sourcefrog.net-20050313120651-497bd231b19df600
mbp@sourcefrog.net-20050314024931-eae0170ef25a5d1a
mbp@sourcefrog.net-20050314025438-d52099f915fe65fc
mbp@sourcefrog.net-20050314025539-637a636692c055cf
mbp@sourcefrog.net-20050314025737-55eb441f430ab4ba
mbp@sourcefrog.net-20050314025901-d74aa93bb7ee8f62
mbp@source\r
--418470f848b63279b--\r
'''
        t = self.get_transport()
        # Remember that the request is ignored and that the ranges below
        # doesn't have to match the canned response.
        l = list(t.readv('/foo/bar', ((0, 255), (1000, 1050))))
        # Force consumption of the last bytesrange boundary
        t._get_connection().cleanup_pipe()
        self.assertEqual(2, len(l))
        self.assertActivitiesMatch()

    def test_post(self):
        self.server.canned_response = b'''HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: 35\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
lalala whatever as long as itsssss
'''
        t = self.get_transport()
        # We must send a single line of body bytes, see
        # PredefinedRequestHandler._handle_one_request
        code, f = t._post(b'abc def end-of-body\n')
        self.assertEqual(b'lalala whatever as long as itsssss\n', f.read())
        self.assertActivitiesMatch()


class TestActivity(tests.TestCase, TestActivityMixin):

    scenarios = multiply_scenarios(
        vary_by_http_activity(),
        vary_by_http_protocol_version(),
        )

    def setUp(self):
        super(TestActivity, self).setUp()
        TestActivityMixin.setUp(self)


class TestNoReportActivity(tests.TestCase, TestActivityMixin):

    # Unlike TestActivity, we are really testing ReportingFileSocket and
    # ReportingSocket, so we don't need all the parametrization. Since
    # ReportingFileSocket and ReportingSocket are wrappers, it's easier to
    # test them through their use by the transport than directly (that's a
    # bit less clean but far more simpler and effective).
    _activity_server = ActivityHTTPServer
    _protocol_version = 'HTTP/1.1'

    def setUp(self):
        super(TestNoReportActivity, self).setUp()
        self._transport = HttpTransport
        TestActivityMixin.setUp(self)

    def assertActivitiesMatch(self):
        # Nothing to check here
        pass


class TestAuthOnRedirected(http_utils.TestCaseWithRedirectedWebserver):
    """Test authentication on the redirected http server."""

    scenarios = vary_by_http_protocol_version()

    _auth_header = 'Authorization'
    _password_prompt_prefix = ''
    _username_prompt_prefix = ''
    _auth_server = http_utils.HTTPBasicAuthServer
    _transport = HttpTransport

    def setUp(self):
        super(TestAuthOnRedirected, self).setUp()
        self.build_tree_contents([('a', b'a'),
                                  ('1/',),
                                  ('1/a', b'redirected once'),
                                  ],)
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = [
            ('(.*)', r'%s/1\1' % (new_prefix), 301), ]
        self.old_transport = self.get_old_transport()
        self.new_server.add_user('joe', 'foo')
        cleanup_http_redirection_connections(self)

    def create_transport_readonly_server(self):
        server = self._auth_server(protocol_version=self._protocol_version)
        server._url_protocol = self._url_protocol
        return server

    def get_a(self, t):
        return t.get('a')

    def test_auth_on_redirected_via_do_catching_redirections(self):
        self.redirections = 0

        def redirected(t, exception, redirection_notice):
            self.redirections += 1
            redirected_t = t._redirected_to(exception.source, exception.target)
            self.addCleanup(redirected_t.disconnect)
            return redirected_t

        ui.ui_factory = tests.TestUIFactory(stdin='joe\nfoo\n')
        self.assertEqual(b'redirected once',
                         transport.do_catching_redirections(
                             self.get_a, self.old_transport, redirected).read())
        self.assertEqual(1, self.redirections)
        # stdin should be empty
        self.assertEqual('', ui.ui_factory.stdin.readline())
        # stdout should be empty, stderr will contains the prompts
        self.assertEqual('', ui.ui_factory.stdout.getvalue())

    def test_auth_on_redirected_via_following_redirections(self):
        self.new_server.add_user('joe', 'foo')
        ui.ui_factory = tests.TestUIFactory(stdin='joe\nfoo\n')
        t = self.old_transport
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = [
            ('(.*)', r'%s/1\1' % (new_prefix), 301), ]
        self.assertEqual(
            b'redirected once',
            t.request('GET', t.abspath('a'), retries=3).read())
        # stdin should be empty
        self.assertEqual('', ui.ui_factory.stdin.readline())
        # stdout should be empty, stderr will contains the prompts
        self.assertEqual('', ui.ui_factory.stdout.getvalue())

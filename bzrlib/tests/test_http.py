# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Tests for HTTP implementations.

This module defines a load_tests() method that parametrize tests classes for
transport implementation, http protocol versions and authentication schemes.
"""

# TODO: Should be renamed to bzrlib.transport.http.tests?
# TODO: What about renaming to bzrlib.tests.transport.http ?

from cStringIO import StringIO
import httplib
import os
import select
import SimpleHTTPServer
import socket
import sys
import threading

import bzrlib
from bzrlib import (
    bzrdir,
    config,
    errors,
    osutils,
    remote as _mod_remote,
    tests,
    transport,
    ui,
    urlutils,
    )
from bzrlib.tests import (
    http_server,
    http_utils,
    )
from bzrlib.transport import (
    http,
    remote,
    )
from bzrlib.transport.http import (
    _urllib,
    _urllib2_wrappers,
    )


try:
    from bzrlib.transport.http._pycurl import PyCurlTransport
    pycurl_present = True
except errors.DependencyNotPresent:
    pycurl_present = False


class TransportAdapter(tests.TestScenarioApplier):
    """Generate the same test for each transport implementation."""

    def __init__(self):
        transport_scenarios = [
            ('urllib', dict(_transport=_urllib.HttpTransport_urllib,
                            _server=http_server.HttpServer_urllib,
                            _qualified_prefix='http+urllib',)),
            ]
        if pycurl_present:
            transport_scenarios.append(
                ('pycurl', dict(_transport=PyCurlTransport,
                                _server=http_server.HttpServer_PyCurl,
                                _qualified_prefix='http+pycurl',)))
        self.scenarios = transport_scenarios


class TransportProtocolAdapter(TransportAdapter):
    """Generate the same test for each protocol implementation.

    In addition to the transport adaptatation that we inherit from.
    """

    def __init__(self):
        super(TransportProtocolAdapter, self).__init__()
        protocol_scenarios = [
            ('HTTP/1.0',  dict(_protocol_version='HTTP/1.0')),
            ('HTTP/1.1',  dict(_protocol_version='HTTP/1.1')),
            ]
        self.scenarios = tests.multiply_scenarios(self.scenarios,
                                                  protocol_scenarios)


class TransportProtocolAuthenticationAdapter(TransportProtocolAdapter):
    """Generate the same test for each authentication scheme implementation.

    In addition to the protocol adaptatation that we inherit from.
    """

    def __init__(self):
        super(TransportProtocolAuthenticationAdapter, self).__init__()
        auth_scheme_scenarios = [
            ('basic', dict(_auth_scheme='basic')),
            ('digest', dict(_auth_scheme='digest')),
            ]

        self.scenarios = tests.multiply_scenarios(self.scenarios,
                                                  auth_scheme_scenarios)

def load_tests(standard_tests, module, loader):
    """Multiply tests for http clients and protocol versions."""
    # one for each transport
    t_adapter = TransportAdapter()
    t_classes= (TestHttpTransportRegistration,
                TestHttpTransportUrls,
                )
    is_testing_for_transports = tests.condition_isinstance(t_classes)

    # multiplied by one for each protocol version
    tp_adapter = TransportProtocolAdapter()
    tp_classes= (SmartHTTPTunnellingTest,
                 TestDoCatchRedirections,
                 TestHTTPConnections,
                 TestHTTPRedirections,
                 TestHTTPSilentRedirections,
                 TestLimitedRangeRequestServer,
                 TestPost,
                 TestProxyHttpServer,
                 TestRanges,
                 TestSpecificRequestHandler,
                 )
    is_also_testing_for_protocols = tests.condition_isinstance(tp_classes)

    # multiplied by one for each authentication scheme
    tpa_adapter = TransportProtocolAuthenticationAdapter()
    tpa_classes = (TestAuth,
                   )
    is_also_testing_for_authentication = tests.condition_isinstance(
        tpa_classes)

    result = loader.suiteClass()
    for test_class in tests.iter_suite_tests(standard_tests):
        # Each test class is either standalone or testing for some combination
        # of transport, protocol version, authentication scheme. Use the right
        # adpater (or none) depending on the class.
        if is_testing_for_transports(test_class):
            result.addTests(t_adapter.adapt(test_class))
        elif is_also_testing_for_protocols(test_class):
            result.addTests(tp_adapter.adapt(test_class))
        elif is_also_testing_for_authentication(test_class):
            result.addTests(tpa_adapter.adapt(test_class))
        else:
            result.addTest(test_class)
    return result


class FakeManager(object):

    def __init__(self):
        self.credentials = []

    def add_password(self, realm, host, username, password):
        self.credentials.append([realm, host, username, password])


class RecordingServer(object):
    """A fake HTTP server.
    
    It records the bytes sent to it, and replies with a 200.
    """

    def __init__(self, expect_body_tail=None):
        """Constructor.

        :type expect_body_tail: str
        :param expect_body_tail: a reply won't be sent until this string is
            received.
        """
        self._expect_body_tail = expect_body_tail
        self.host = None
        self.port = None
        self.received_bytes = ''

    def setUp(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(('127.0.0.1', 0))
        self.host, self.port = self._sock.getsockname()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._accept_read_and_reply)
        self._thread.setDaemon(True)
        self._thread.start()
        self._ready.wait(5)

    def _accept_read_and_reply(self):
        self._sock.listen(1)
        self._ready.set()
        self._sock.settimeout(5)
        try:
            conn, address = self._sock.accept()
            # On win32, the accepted connection will be non-blocking to start
            # with because we're using settimeout.
            conn.setblocking(True)
            while not self.received_bytes.endswith(self._expect_body_tail):
                self.received_bytes += conn.recv(4096)
            conn.sendall('HTTP/1.1 200 OK\r\n')
        except socket.timeout:
            # Make sure the client isn't stuck waiting for us to e.g. accept.
            self._sock.close()
        except socket.error:
            # The client may have already closed the socket.
            pass

    def tearDown(self):
        try:
            self._sock.close()
        except socket.error:
            # We might have already closed it.  We don't care.
            pass
        self.host = None
        self.port = None


class TestHTTPServer(tests.TestCase):
    """Test the HTTP servers implementations."""

    def test_invalid_protocol(self):
        class BogusRequestHandler(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/0.1'

        server = http_server.HttpServer(BogusRequestHandler)
        try:
            self.assertRaises(httplib.UnknownProtocol,server.setUp)
        except:
            server.tearDown()
            self.fail('HTTP Server creation did not raise UnknownProtocol')

    def test_force_invalid_protocol(self):
        server = http_server.HttpServer(protocol_version='HTTP/0.1')
        try:
            self.assertRaises(httplib.UnknownProtocol,server.setUp)
        except:
            server.tearDown()
            self.fail('HTTP Server creation did not raise UnknownProtocol')

    def test_server_start_and_stop(self):
        server = http_server.HttpServer()
        server.setUp()
        self.assertTrue(server._http_running)
        server.tearDown()
        self.assertFalse(server._http_running)

    def test_create_http_server_one_zero(self):
        class RequestHandlerOneZero(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.0'

        server = http_server.HttpServer(RequestHandlerOneZero)
        server.setUp()
        self.addCleanup(server.tearDown)
        self.assertIsInstance(server._httpd, http_server.TestingHTTPServer)

    def test_create_http_server_one_one(self):
        class RequestHandlerOneOne(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.1'

        server = http_server.HttpServer(RequestHandlerOneOne)
        server.setUp()
        self.addCleanup(server.tearDown)
        self.assertIsInstance(server._httpd,
                              http_server.TestingThreadingHTTPServer)

    def test_create_http_server_force_one_one(self):
        class RequestHandlerOneZero(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.0'

        server = http_server.HttpServer(RequestHandlerOneZero,
                                        protocol_version='HTTP/1.1')
        server.setUp()
        self.addCleanup(server.tearDown)
        self.assertIsInstance(server._httpd,
                              http_server.TestingThreadingHTTPServer)

    def test_create_http_server_force_one_zero(self):
        class RequestHandlerOneOne(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.1'

        server = http_server.HttpServer(RequestHandlerOneOne,
                                        protocol_version='HTTP/1.0')
        server.setUp()
        self.addCleanup(server.tearDown)
        self.assertIsInstance(server._httpd,
                              http_server.TestingHTTPServer)


class TestWithTransport_pycurl(object):
    """Test case to inherit from if pycurl is present"""

    def _get_pycurl_maybe(self):
        try:
            from bzrlib.transport.http._pycurl import PyCurlTransport
            return PyCurlTransport
        except errors.DependencyNotPresent:
            raise tests.TestSkipped('pycurl not present')

    _transport = property(_get_pycurl_maybe)


class TestHttpUrls(tests.TestCase):

    # TODO: This should be moved to authorization tests once they
    # are written.

    def test_url_parsing(self):
        f = FakeManager()
        url = http.extract_auth('http://example.com', f)
        self.assertEquals('http://example.com', url)
        self.assertEquals(0, len(f.credentials))
        url = http.extract_auth(
            'http://user:pass@www.bazaar-vcs.org/bzr/bzr.dev', f)
        self.assertEquals('http://www.bazaar-vcs.org/bzr/bzr.dev', url)
        self.assertEquals(1, len(f.credentials))
        self.assertEquals([None, 'www.bazaar-vcs.org', 'user', 'pass'],
                          f.credentials[0])


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


class TestHttps_pycurl(TestWithTransport_pycurl, tests.TestCase):

    # TODO: This should really be moved into another pycurl
    # specific test. When https tests will be implemented, take
    # this one into account.
    def test_pycurl_without_https_support(self):
        """Test that pycurl without SSL do not fail with a traceback.

        For the purpose of the test, we force pycurl to ignore
        https by supplying a fake version_info that do not
        support it.
        """
        try:
            import pycurl
        except ImportError:
            raise tests.TestSkipped('pycurl not present')

        version_info_orig = pycurl.version_info
        try:
            # Now that we have pycurl imported, we can fake its version_info
            # This was taken from a windows pycurl without SSL
            # (thanks to bialix)
            pycurl.version_info = lambda : (2,
                                            '7.13.2',
                                            462082,
                                            'i386-pc-win32',
                                            2576,
                                            None,
                                            0,
                                            None,
                                            ('ftp', 'gopher', 'telnet',
                                             'dict', 'ldap', 'http', 'file'),
                                            None,
                                            0,
                                            None)
            self.assertRaises(errors.DependencyNotPresent, self._transport,
                              'https://launchpad.net')
        finally:
            # Restore the right function
            pycurl.version_info = version_info_orig


class TestHTTPConnections(http_utils.TestCaseWithWebserver):
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


class TestHttpTransportRegistration(tests.TestCase):
    """Test registrations of various http implementations"""

    def test_http_registered(self):
        t = transport.get_transport('%s://foo.com/' % self._qualified_prefix)
        self.assertIsInstance(t, transport.Transport)
        self.assertIsInstance(t, self._transport)


class TestPost(tests.TestCase):

    def test_post_body_is_received(self):
        server = RecordingServer(expect_body_tail='end-of-body')
        server.setUp()
        self.addCleanup(server.tearDown)
        scheme = self._qualified_prefix
        url = '%s://%s:%s/' % (scheme, server.host, server.port)
        http_transport = self._transport(url)
        code, response = http_transport._post('abc def end-of-body')
        self.assertTrue(
            server.received_bytes.startswith('POST /.bzr/smart HTTP/1.'))
        self.assertTrue('content-length: 19\r' in server.received_bytes.lower())
        # The transport should not be assuming that the server can accept
        # chunked encoding the first time it connects, because HTTP/1.1, so we
        # check for the literal string.
        self.assertTrue(
            server.received_bytes.endswith('\r\n\r\nabc def end-of-body'))


class TestRangeHeader(tests.TestCase):
    """Test range_header method"""

    def check_header(self, value, ranges=[], tail=0):
        offsets = [ (start, end - start + 1) for start, end in ranges]
        coalesce = transport.Transport._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        range_header = http.HttpTransportBase._range_header
        self.assertEqual(value, range_header(coalesced, tail))

    def test_range_header_single(self):
        self.check_header('0-9', ranges=[(0,9)])
        self.check_header('100-109', ranges=[(100,109)])

    def test_range_header_tail(self):
        self.check_header('-10', tail=10)
        self.check_header('-50', tail=50)

    def test_range_header_multi(self):
        self.check_header('0-9,100-200,300-5000',
                          ranges=[(0,9), (100, 200), (300,5000)])

    def test_range_header_mixed(self):
        self.check_header('0-9,300-5000,-50',
                          ranges=[(0,9), (300,5000)],
                          tail=50)


class TestSpecificRequestHandler(http_utils.TestCaseWithWebserver):
    """Tests a specific request handler.

    Daughter classes are expected to override _req_handler_class
    """

    # Provide a useful default
    _req_handler_class = http_server.TestingHTTPRequestHandler

    def create_transport_readonly_server(self):
        return http_server.HttpServer(self._req_handler_class,
                                      protocol_version=self._protocol_version)

    def _testing_pycurl(self):
        return pycurl_present and self._transport == PyCurlTransport


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
        self.send_response(0, "Bad status")
        self.close_connection = 1
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
    """Whatever request comes in, returns an invalid status"""

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

    def test_http_has(self):
        if self._testing_pycurl() and self._protocol_version == 'HTTP/1.1':
            raise tests.KnownFailure(
                'pycurl hangs if the server send back garbage')
        super(TestInvalidStatusServer, self).test_http_has()

    def test_http_get(self):
        if self._testing_pycurl() and self._protocol_version == 'HTTP/1.1':
            raise tests.KnownFailure(
                'pycurl hangs if the server send back garbage')
        super(TestInvalidStatusServer, self).test_http_get()


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


class TestRecordingServer(tests.TestCase):

    def test_create(self):
        server = RecordingServer(expect_body_tail=None)
        self.assertEqual('', server.received_bytes)
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_setUp_and_tearDown(self):
        server = RecordingServer(expect_body_tail=None)
        server.setUp()
        try:
            self.assertNotEqual(None, server.host)
            self.assertNotEqual(None, server.port)
        finally:
            server.tearDown()
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_send_receive_bytes(self):
        server = RecordingServer(expect_body_tail='c')
        server.setUp()
        self.addCleanup(server.tearDown)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server.host, server.port))
        sock.sendall('abc')
        self.assertEqual('HTTP/1.1 200 OK\r\n',
                         osutils.recv_all(sock, 4096))
        self.assertEqual('abc', server.received_bytes)


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
        # single range will keep its size even if bigger than the limit.
        t._get_max_size = 2
        l = list(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (2, '2345'))
        self.assertEqual(l[3], (6, '6789'))
        # The server should have issued 3 requests
        self.assertEqual(3, server.GET_request_nb)

    def test_complete_readv_leave_pipe_clean(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # force transport to issue multiple requests
        t._get_max_size = 2
        l = list(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        # The server should have issued 3 requests
        self.assertEqual(3, server.GET_request_nb)
        self.assertEqual('0123456789', t.get_bytes('a'))
        self.assertEqual(4, server.GET_request_nb)

    def test_incomplete_readv_leave_pipe_clean(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # force transport to issue multiple requests
        t._get_max_size = 2
        # Don't collapse readv results into a list so that we leave unread
        # bytes on the socket
        ireadv = iter(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        self.assertEqual((0, '0'), ireadv.next())
        # The server should have issued one request so far 
        self.assertEqual(1, server.GET_request_nb)
        self.assertEqual('0123456789', t.get_bytes('a'))
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
        return SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)


class TestNoRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which do not accept range requests"""

    _req_handler_class = NoRangeRequestHandler


class MultipleRangeWithoutContentLengthRequestHandler(
    http_server.TestingHTTPRequestHandler):
    """Reply to multiple range requests without content length header."""

    def get_multiple_ranges(self, file, file_size, ranges):
        self.send_response(206)
        self.send_header('Accept-Ranges', 'bytes')
        boundary = "%d" % random.randint(0,0x7FFFFFFF)
        self.send_header("Content-Type",
                         "multipart/byteranges; boundary=%s" % boundary)
        self.end_headers()
        for (start, end) in ranges:
            self.wfile.write("--%s\r\n" % boundary)
            self.send_header("Content-type", 'application/octet-stream')
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start,
                                                                  end,
                                                                  file_size))
            self.end_headers()
            self.send_range_content(file, start, end - start + 1)
        # Final boundary
        self.wfile.write("--%s\r\n" % boundary)


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
        # No final boundary
        self.wfile.write(boundary_line)


class TestTruncatedMultipleRangeServer(TestSpecificRequestHandler):

    _req_handler_class = TruncatedMultipleRangeRequestHandler

    def setUp(self):
        super(TestTruncatedMultipleRangeServer, self).setUp()
        self.build_tree_contents([('a', '0123456789')],)

    def test_readv_with_short_reads(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # Force separate ranges for each offset
        t._bytes_to_read_before_seek = 0
        ireadv = iter(t.readv('a', ((0, 1), (2, 1), (4, 2), (9, 1))))
        self.assertEqual((0, '0'), ireadv.next())
        self.assertEqual((2, '2'), ireadv.next())
        if not self._testing_pycurl():
            # Only one request have been issued so far (except for pycurl that
            # try to read the whole response at once)
            self.assertEqual(1, server.GET_request_nb)
        self.assertEqual((4, '45'), ireadv.next())
        self.assertEqual((9, '9'), ireadv.next())
        # Both implementations issue 3 requests but:
        # - urllib does two multiple (4 ranges, then 2 ranges) then a single
        #   range,
        # - pycurl does two multiple (4 ranges, 4 ranges) then a single range
        self.assertEqual(3, server.GET_request_nb)
        # Finally the client have tried a single range request and stays in
        # that mode
        self.assertEqual('single', t._range_hint)

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

    # Requests with more range specifiers will error out
    range_limit = 3

    def create_transport_readonly_server(self):
        return LimitedRangeHTTPServer(range_limit=self.range_limit,
                                      protocol_version=self._protocol_version)

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
        # a second request will succeed.
        self.assertEqual(2, self.get_readonly_server().GET_request_nb)


class TestHttpProxyWhiteBox(tests.TestCase):
    """Whitebox test proxy http authorization.

    Only the urllib implementation is tested here.
    """

    def setUp(self):
        tests.TestCase.setUp(self)
        self._old_env = {}

    def tearDown(self):
        self._restore_env()
        tests.TestCase.tearDown(self)

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def _proxied_request(self):
        handler = _urllib2_wrappers.ProxyHandler()
        request = _urllib2_wrappers.Request('GET','http://baz/buzzle')
        handler.set_proxy(request, 'http')
        return request

    def test_empty_user(self):
        self._install_env({'http_proxy': 'http://bar.com'})
        request = self._proxied_request()
        self.assertFalse(request.headers.has_key('Proxy-authorization'))

    def test_invalid_proxy(self):
        """A proxy env variable without scheme"""
        self._install_env({'http_proxy': 'host:1234'})
        self.assertRaises(errors.InvalidURL, self._proxied_request)


class TestProxyHttpServer(http_utils.TestCaseWithTwoWebservers):
    """Tests proxy server.

    Be aware that we do not setup a real proxy here. Instead, we
    check that the *connection* goes through the proxy by serving
    different content (the faked proxy server append '-proxied'
    to the file names).
    """

    # FIXME: We don't have an https server available, so we don't
    # test https connections.

    def setUp(self):
        super(TestProxyHttpServer, self).setUp()
        self.build_tree_contents([('foo', 'contents of foo\n'),
                                  ('foo-proxied', 'proxied contents of foo\n')])
        # Let's setup some attributes for tests
        self.server = self.get_readonly_server()
        self.proxy_address = '%s:%d' % (self.server.host, self.server.port)
        if self._testing_pycurl():
            # Oh my ! pycurl does not check for the port as part of
            # no_proxy :-( So we just test the host part
            self.no_proxy_host = 'localhost'
        else:
            self.no_proxy_host = self.proxy_address
        # The secondary server is the proxy
        self.proxy = self.get_secondary_server()
        self.proxy_url = self.proxy.get_url()
        self._old_env = {}

    def _testing_pycurl(self):
        return pycurl_present and self._transport == PyCurlTransport

    def create_transport_secondary_server(self):
        """Creates an http server that will serve files with
        '-proxied' appended to their names.
        """
        return http_utils.ProxyServer(protocol_version=self._protocol_version)

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def proxied_in_env(self, env):
        self._install_env(env)
        url = self.server.get_url()
        t = self._transport(url)
        try:
            self.assertEqual(t.get('foo').read(), 'proxied contents of foo\n')
        finally:
            self._restore_env()

    def not_proxied_in_env(self, env):
        self._install_env(env)
        url = self.server.get_url()
        t = self._transport(url)
        try:
            self.assertEqual(t.get('foo').read(), 'contents of foo\n')
        finally:
            self._restore_env()

    def test_http_proxy(self):
        self.proxied_in_env({'http_proxy': self.proxy_url})

    def test_HTTP_PROXY(self):
        if self._testing_pycurl():
            # pycurl does not check HTTP_PROXY for security reasons
            # (for use in a CGI context that we do not care
            # about. Should we ?)
            raise tests.TestNotApplicable(
                'pycurl does not check HTTP_PROXY for security reasons')
        self.proxied_in_env({'HTTP_PROXY': self.proxy_url})

    def test_all_proxy(self):
        self.proxied_in_env({'all_proxy': self.proxy_url})

    def test_ALL_PROXY(self):
        self.proxied_in_env({'ALL_PROXY': self.proxy_url})

    def test_http_proxy_with_no_proxy(self):
        self.not_proxied_in_env({'http_proxy': self.proxy_url,
                                 'no_proxy': self.no_proxy_host})

    def test_HTTP_PROXY_with_NO_PROXY(self):
        if self._testing_pycurl():
            raise tests.TestNotApplicable(
                'pycurl does not check HTTP_PROXY for security reasons')
        self.not_proxied_in_env({'HTTP_PROXY': self.proxy_url,
                                 'NO_PROXY': self.no_proxy_host})

    def test_all_proxy_with_no_proxy(self):
        self.not_proxied_in_env({'all_proxy': self.proxy_url,
                                 'no_proxy': self.no_proxy_host})

    def test_ALL_PROXY_with_NO_PROXY(self):
        self.not_proxied_in_env({'ALL_PROXY': self.proxy_url,
                                 'NO_PROXY': self.no_proxy_host})

    def test_http_proxy_without_scheme(self):
        if self._testing_pycurl():
            # pycurl *ignores* invalid proxy env variables. If that ever change
            # in the future, this test will fail indicating that pycurl do not
            # ignore anymore such variables.
            self.not_proxied_in_env({'http_proxy': self.proxy_address})
        else:
            self.assertRaises(errors.InvalidURL,
                              self.proxied_in_env,
                              {'http_proxy': self.proxy_address})


class TestRanges(http_utils.TestCaseWithWebserver):
    """Test the Range header in GET methods."""

    def setUp(self):
        http_utils.TestCaseWithWebserver.setUp(self)
        self.build_tree_contents([('a', '0123456789')],)
        server = self.get_readonly_server()
        self.transport = self._transport(server.get_url())

    def create_transport_readonly_server(self):
        return http_server.HttpServer(protocol_version=self._protocol_version)

    def _file_contents(self, relpath, ranges):
        offsets = [ (start, end - start + 1) for start, end in ranges]
        coalesce = self.transport._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        code, data = self.transport._get(relpath, coalesced)
        self.assertTrue(code in (200, 206),'_get returns: %d' % code)
        for start, end in ranges:
            data.seek(start)
            yield data.read(end - start + 1)

    def _file_tail(self, relpath, tail_amount):
        code, data = self.transport._get(relpath, [], tail_amount)
        self.assertTrue(code in (200, 206),'_get returns: %d' % code)
        data.seek(-tail_amount, 2)
        return data.read(tail_amount)

    def test_range_header(self):
        # Valid ranges
        map(self.assertEqual,['0', '234'],
            list(self._file_contents('a', [(0,0), (2,4)])),)

    def test_range_header_tail(self):
        self.assertEqual('789', self._file_tail('a', 3))

    def test_syntactically_invalid_range_header(self):
        self.assertListRaises(errors.InvalidHttpRange,
                          self._file_contents, 'a', [(4, 3)])

    def test_semantically_invalid_range_header(self):
        self.assertListRaises(errors.InvalidHttpRange,
                          self._file_contents, 'a', [(42, 128)])


class TestHTTPRedirections(http_utils.TestCaseWithRedirectedWebserver):
    """Test redirection between http servers."""

    def create_transport_secondary_server(self):
        """Create the secondary server redirecting to the primary server"""
        new = self.get_readonly_server()

        redirecting = http_utils.HTTPServerRedirecting(
            protocol_version=self._protocol_version)
        redirecting.redirect_to(new.host, new.port)
        return redirecting

    def setUp(self):
        super(TestHTTPRedirections, self).setUp()
        self.build_tree_contents([('a', '0123456789'),
                                  ('bundle',
                                  '# Bazaar revision bundle v0.9\n#\n')
                                  ],)

        self.old_transport = self._transport(self.old_server.get_url())

    def test_redirected(self):
        self.assertRaises(errors.RedirectRequested, self.old_transport.get, 'a')
        t = self._transport(self.new_server.get_url())
        self.assertEqual('0123456789', t.get('a').read())

    def test_read_redirected_bundle_from_url(self):
        from bzrlib.bundle import read_bundle_from_url
        url = self.old_transport.abspath('bundle')
        bundle = read_bundle_from_url(url)
        # If read_bundle_from_url was successful we get an empty bundle
        self.assertEqual([], bundle.revisions)


class RedirectedRequest(_urllib2_wrappers.Request):
    """Request following redirections. """

    init_orig = _urllib2_wrappers.Request.__init__

    def __init__(self, method, url, *args, **kwargs):
        """Constructor.

        """
        # Since the tests using this class will replace
        # _urllib2_wrappers.Request, we can't just call the base class __init__
        # or we'll loop.
        RedirectedRequest.init_orig(self, method, url, args, kwargs)
        self.follow_redirections = True


class TestHTTPSilentRedirections(http_utils.TestCaseWithRedirectedWebserver):
    """Test redirections.

    http implementations do not redirect silently anymore (they
    do not redirect at all in fact). The mechanism is still in
    place at the _urllib2_wrappers.Request level and these tests
    exercise it.

    For the pycurl implementation
    the redirection have been deleted as we may deprecate pycurl
    and I have no place to keep a working implementation.
    -- vila 20070212
    """

    def setUp(self):
        if pycurl_present and self._transport == PyCurlTransport:
            raise tests.TestNotApplicable(
                "pycurl doesn't redirect silently annymore")
        super(TestHTTPSilentRedirections, self).setUp()
        self.setup_redirected_request()
        self.addCleanup(self.cleanup_redirected_request)
        self.build_tree_contents([('a','a'),
                                  ('1/',),
                                  ('1/a', 'redirected once'),
                                  ('2/',),
                                  ('2/a', 'redirected twice'),
                                  ('3/',),
                                  ('3/a', 'redirected thrice'),
                                  ('4/',),
                                  ('4/a', 'redirected 4 times'),
                                  ('5/',),
                                  ('5/a', 'redirected 5 times'),
                                  ],)

        self.old_transport = self._transport(self.old_server.get_url())

    def setup_redirected_request(self):
        self.original_class = _urllib2_wrappers.Request
        _urllib2_wrappers.Request = RedirectedRequest

    def cleanup_redirected_request(self):
        _urllib2_wrappers.Request = self.original_class

    def create_transport_secondary_server(self):
        """Create the secondary server, redirections are defined in the tests"""
        return http_utils.HTTPServerRedirecting(
            protocol_version=self._protocol_version)

    def test_one_redirection(self):
        t = self.old_transport

        req = RedirectedRequest('GET', t.abspath('a'))
        req.follow_redirections = True
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = \
            [('(.*)', r'%s/1\1' % (new_prefix), 301),]
        self.assertEquals('redirected once',t._perform(req).read())

    def test_five_redirections(self):
        t = self.old_transport

        req = RedirectedRequest('GET', t.abspath('a'))
        req.follow_redirections = True
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
        self.assertEquals('redirected 5 times',t._perform(req).read())


class TestDoCatchRedirections(http_utils.TestCaseWithRedirectedWebserver):
    """Test transport.do_catching_redirections."""

    def setUp(self):
        super(TestDoCatchRedirections, self).setUp()
        self.build_tree_contents([('a', '0123456789'),],)

        self.old_transport = self._transport(self.old_server.get_url())

    def get_a(self, transport):
        return transport.get('a')

    def test_no_redirection(self):
        t = self._transport(self.new_server.get_url())

        # We use None for redirected so that we fail if redirected
        self.assertEquals('0123456789',
                          transport.do_catching_redirections(
                self.get_a, t, None).read())

    def test_one_redirection(self):
        self.redirections = 0

        def redirected(transport, exception, redirection_notice):
            self.redirections += 1
            dir, file = urlutils.split(exception.target)
            return self._transport(dir)

        self.assertEquals('0123456789',
                          transport.do_catching_redirections(
                self.get_a, self.old_transport, redirected).read())
        self.assertEquals(1, self.redirections)

    def test_redirection_loop(self):

        def redirected(transport, exception, redirection_notice):
            # By using the redirected url as a base dir for the
            # *old* transport, we create a loop: a => a/a =>
            # a/a/a
            return self.old_transport.clone(exception.target)

        self.assertRaises(errors.TooManyRedirections,
                          transport.do_catching_redirections,
                          self.get_a, self.old_transport, redirected)


class TestAuth(http_utils.TestCaseWithWebserver):
    """Test authentication scheme"""

    _auth_header = 'Authorization'
    _password_prompt_prefix = ''

    def setUp(self):
        super(TestAuth, self).setUp()
        self.server = self.get_readonly_server()
        self.build_tree_contents([('a', 'contents of a\n'),
                                  ('b', 'contents of b\n'),])

    def create_transport_readonly_server(self):
        if self._auth_scheme == 'basic':
            server = http_utils.HTTPBasicAuthServer(
                protocol_version=self._protocol_version)
        else:
            if self._auth_scheme != 'digest':
                raise AssertionError('Unknown auth scheme: %r'
                                     % self._auth_scheme)
            server = http_utils.HTTPDigestAuthServer(
                protocol_version=self._protocol_version)
        return server

    def _testing_pycurl(self):
        return pycurl_present and self._transport == PyCurlTransport

    def get_user_url(self, user=None, password=None):
        """Build an url embedding user and password"""
        url = '%s://' % self.server._url_protocol
        if user is not None:
            url += user
            if password is not None:
                url += ':' + password
            url += '@'
        url += '%s:%s/' % (self.server.host, self.server.port)
        return url

    def get_user_transport(self, user=None, password=None):
        return self._transport(self.get_user_url(user, password))

    def test_no_user(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport()
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_empty_pass(self):
        self.server.add_user('joe', '')
        t = self.get_user_transport('joe', '')
        self.assertEqual('contents of a\n', t.get('a').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_user_pass(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'foo')
        self.assertEqual('contents of a\n', t.get('a').read())
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

    def test_prompt_for_password(self):
        if self._testing_pycurl():
            raise tests.TestNotApplicable(
                'pycurl cannot prompt, it handles auth by embedding'
                ' user:pass in urls only')

        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', None)
        stdout = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin='foo\n', stdout=stdout)
        self.assertEqual('contents of a\n',t.get('a').read())
        # stdin should be empty
        self.assertEqual('', ui.ui_factory.stdin.readline())
        self._check_password_prompt(t._unqualified_scheme, 'joe',
                                    stdout.getvalue())
        # And we shouldn't prompt again for a different request
        # against the same transport.
        self.assertEqual('contents of b\n',t.get('b').read())
        t2 = t.clone()
        # And neither against a clone
        self.assertEqual('contents of b\n',t2.get('b').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def _check_password_prompt(self, scheme, user, actual_prompt):
        expected_prompt = (self._password_prompt_prefix
                           + ("%s %s@%s:%d, Realm: '%s' password: "
                              % (scheme.upper(),
                                 user, self.server.host, self.server.port,
                                 self.server.auth_realm)))
        self.assertEquals(expected_prompt, actual_prompt)

    def test_no_prompt_for_password_when_using_auth_config(self):
        if self._testing_pycurl():
            raise tests.TestNotApplicable(
                'pycurl does not support authentication.conf'
                ' since it cannot prompt')

        user =' joe'
        password = 'foo'
        stdin_content = 'bar\n'  # Not the right password
        self.server.add_user(user, password)
        t = self.get_user_transport(user, None)
        ui.ui_factory = tests.TestUIFactory(stdin=stdin_content,
                                            stdout=tests.StringIOWrapper())
        # Create a minimal config file with the right password
        conf = config.AuthenticationConfig()
        conf._get_config().update(
            {'httptest': {'scheme': 'http', 'port': self.server.port,
                          'user': user, 'password': password}})
        conf._save()
        # Issue a request to the server to connect
        self.assertEqual('contents of a\n',t.get('a').read())
        # stdin should have  been left untouched
        self.assertEqual(stdin_content, ui.ui_factory.stdin.readline())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_changing_nonce(self):
        if self._auth_scheme != 'digest':
            raise tests.TestNotApplicable('HTTP auth digest only test')
        if self._testing_pycurl():
            raise tests.KnownFailure(
                'pycurl does not handle a nonce change')
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'foo')
        self.assertEqual('contents of a\n', t.get('a').read())
        self.assertEqual('contents of b\n', t.get('b').read())
        # Only one 'Authentication Required' error should have
        # occured so far
        self.assertEqual(1, self.server.auth_required_errors)
        # The server invalidates the current nonce
        self.server.auth_nonce = self.server.auth_nonce + '. No, now!'
        self.assertEqual('contents of a\n', t.get('a').read())
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and a second 'who are you' with the new nonce)
        self.assertEqual(2, self.server.auth_required_errors)



class TestProxyAuth(TestAuth):
    """Test proxy authentication schemes."""

    _auth_header = 'Proxy-authorization'
    _password_prompt_prefix='Proxy '

    def setUp(self):
        super(TestProxyAuth, self).setUp()
        self._old_env = {}
        self.addCleanup(self._restore_env)
        # Override the contents to avoid false positives
        self.build_tree_contents([('a', 'not proxied contents of a\n'),
                                  ('b', 'not proxied contents of b\n'),
                                  ('a-proxied', 'contents of a\n'),
                                  ('b-proxied', 'contents of b\n'),
                                  ])

    def create_transport_readonly_server(self):
        if self._auth_scheme == 'basic':
            server = http_utils.ProxyBasicAuthServer(
                protocol_version=self._protocol_version)
        else:
            if self._auth_scheme != 'digest':
                raise AssertionError('Unknown auth scheme: %r'
                                     % self._auth_scheme)
            server = http_utils.ProxyDigestAuthServer(
                protocol_version=self._protocol_version)
        return server

    def get_user_transport(self, user=None, password=None):
        self._install_env({'all_proxy': self.get_user_url(user, password)})
        return self._transport(self.server.get_url())

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def test_empty_pass(self):
        if self._testing_pycurl():
            import pycurl
            if pycurl.version_info()[1] < '7.16.0':
                raise tests.KnownFailure(
                    'pycurl < 7.16.0 does not handle empty proxy passwords')
        super(TestProxyAuth, self).test_empty_pass()


class SampleSocket(object):
    """A socket-like object for use in testing the HTTP request handler."""

    def __init__(self, socket_read_content):
        """Constructs a sample socket.

        :param socket_read_content: a byte sequence
        """
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        self.readfile = StringIO(socket_read_content)
        self.writefile = StringIO()
        self.writefile.close = lambda: None

    def makefile(self, mode='r', bufsize=None):
        if 'r' in mode:
            return self.readfile
        else:
            return self.writefile


class SmartHTTPTunnellingTest(tests.TestCaseWithTransport):

    def setUp(self):
        super(SmartHTTPTunnellingTest, self).setUp()
        # We use the VFS layer as part of HTTP tunnelling tests.
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.transport_readonly_server = http_utils.HTTPServerWithSmarts

    def create_transport_readonly_server(self):
        return http_utils.HTTPServerWithSmarts(
            protocol_version=self._protocol_version)

    def test_open_bzrdir(self):
        branch = self.make_branch('relpath')
        http_server = self.get_readonly_server()
        url = http_server.get_url() + 'relpath'
        bd = bzrdir.BzrDir.open(url)
        self.assertIsInstance(bd, _mod_remote.RemoteBzrDir)

    def test_bulk_data(self):
        # We should be able to send and receive bulk data in a single message.
        # The 'readv' command in the smart protocol both sends and receives
        # bulk data, so we use that.
        self.build_tree(['data-file'])
        http_server = self.get_readonly_server()
        http_transport = self._transport(http_server.get_url())
        medium = http_transport.get_smart_medium()
        # Since we provide the medium, the url below will be mostly ignored
        # during the test, as long as the path is '/'.
        remote_transport = remote.RemoteTransport('bzr://fake_host/',
                                                  medium=medium)
        self.assertEqual(
            [(0, "c")], list(remote_transport.readv("data-file", [(0,1)])))

    def test_http_send_smart_request(self):

        post_body = 'hello\n'
        expected_reply_body = 'ok\x012\n'

        http_server = self.get_readonly_server()
        http_transport = self._transport(http_server.get_url())
        medium = http_transport.get_smart_medium()
        response = medium.send_http_smart_request(post_body)
        reply_body = response.read()
        self.assertEqual(expected_reply_body, reply_body)

    def test_smart_http_server_post_request_handler(self):
        httpd = self.get_readonly_server()._get_httpd()

        socket = SampleSocket(
            'POST /.bzr/smart %s \r\n' % self._protocol_version
            # HTTP/1.1 posts must have a Content-Length (but it doesn't hurt
            # for 1.0)
            + 'Content-Length: 6\r\n'
            '\r\n'
            'hello\n')
        # Beware: the ('localhost', 80) below is the
        # client_address parameter, but we don't have one because
        # we have defined a socket which is not bound to an
        # address. The test framework never uses this client
        # address, so far...
        request_handler = http_utils.SmartRequestHandler(socket,
                                                         ('localhost', 80),
                                                         httpd)
        response = socket.writefile.getvalue()
        self.assertStartsWith(response, '%s 200 ' % self._protocol_version)
        # This includes the end of the HTTP headers, and all the body.
        expected_end_of_response = '\r\n\r\nok\x012\n'
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
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # No need to build a valid smart request here, the server will not even
        # try to interpret it.
        self.assertRaises(errors.SmartProtocolError,
                          t.send_http_smart_request, 'whatever')


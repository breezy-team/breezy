# Copyright (C) 2005, 2006 Canonical
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

# FIXME: This test should be repeated for each available http client
# implementation; at the moment we have urllib and pycurl.

# TODO: Should be renamed to bzrlib.transport.http.tests?

import socket

import bzrlib
from bzrlib.errors import (
    DependencyNotPresent,
    ConnectionError,
    InvalidHttpResponse,
    )
from bzrlib.tests import (
    TestCase,
    TestSkipped,
    )
from bzrlib.tests.HttpServer import (
    HttpServer,
    HttpServer_PyCurl,
    HttpServer_urllib,
    )
from bzrlib.tests.HTTPTestUtil import (
    BadProtocolRequestHandler,
    BadStatusRequestHandler,
    InvalidStatusRequestHandler,
    TestCaseWithWebserver,
    WallRequestHandler,
    )
from bzrlib.transport import (
    get_transport,
    Transport,
    )
from bzrlib.transport.http import (
    extract_auth,
    HttpTransportBase,
    )
from bzrlib.transport.http._urllib import HttpTransport_urllib


class FakeManager (object):

    def __init__(self):
        self.credentials = []

    def add_password(self, realm, host, username, password):
        self.credentials.append([realm, host, username, password])


class TestHttpUrls(TestCase):

    def test_url_parsing(self):
        f = FakeManager()
        url = extract_auth('http://example.com', f)
        self.assertEquals('http://example.com', url)
        self.assertEquals(0, len(f.credentials))
        url = extract_auth('http://user:pass@www.bazaar-vcs.org/bzr/bzr.dev', f)
        self.assertEquals('http://www.bazaar-vcs.org/bzr/bzr.dev', url)
        self.assertEquals(1, len(f.credentials))
        self.assertEquals([None, 'www.bazaar-vcs.org', 'user', 'pass'],
                          f.credentials[0])

    def test_abs_url(self):
        """Construction of absolute http URLs"""
        t = HttpTransport_urllib('http://bazaar-vcs.org/bzr/bzr.dev/')
        eq = self.assertEqualDiff
        eq(t.abspath('.'),
           'http://bazaar-vcs.org/bzr/bzr.dev')
        eq(t.abspath('foo/bar'),
           'http://bazaar-vcs.org/bzr/bzr.dev/foo/bar')
        eq(t.abspath('.bzr'),
           'http://bazaar-vcs.org/bzr/bzr.dev/.bzr')
        eq(t.abspath('.bzr/1//2/./3'),
           'http://bazaar-vcs.org/bzr/bzr.dev/.bzr/1/2/3')

    def test_invalid_http_urls(self):
        """Trap invalid construction of urls"""
        t = HttpTransport_urllib('http://bazaar-vcs.org/bzr/bzr.dev/')
        self.assertRaises(ValueError,
            t.abspath,
            '.bzr/')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = HttpTransport_urllib('http://bzr.ozlabs.org/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://bzr.ozlabs.org/.bzr/tree-version')

    def test_http_impl_urls(self):
        """There are servers which ask for particular clients to connect"""
        server = HttpServer_PyCurl()
        try:
            server.setUp()
            url = server.get_url()
            self.assertTrue(url.startswith('http+pycurl://'))
        finally:
            server.tearDown()


class TestHttpConnections(object):
    """Test the http connections.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithWebserver.

    We can't inherit directly from TestCaseWithWebserver or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self.build_tree(['xxx', 'foo/', 'foo/bar'], line_endings='binary',
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
            self.assertRaises(ConnectionError, t.has, 'foo/bar')
        finally:
            socket.setdefaulttimeout(default_timeout)


class TestWithTransport_pycurl(object):
    """Test case to inherit from if pycurl is present"""
    def _get_pycurl_maybe(self):
        try:
            from bzrlib.transport.http._pycurl import PyCurlTransport
            return PyCurlTransport
        except DependencyNotPresent:
            raise TestSkipped('pycurl not present')

    _transport = property(_get_pycurl_maybe)


class TestHttpConnections_urllib(TestHttpConnections, TestCaseWithWebserver):
    """Test http connections with urllib"""

    _transport = HttpTransport_urllib



class TestHttpConnections_pycurl(TestWithTransport_pycurl,
                                 TestHttpConnections,
                                 TestCaseWithWebserver):
    """Test http connections with pycurl"""


class TestHttpTransportRegistration(TestCase):
    """Test registrations of various http implementations"""

    def test_http_registered(self):
        # urlllib should always be present
        t = get_transport('http+urllib://bzr.google.com/')
        self.assertIsInstance(t, Transport)
        self.assertIsInstance(t, HttpTransport_urllib)


class TestOffsets(TestCase):
    """Test offsets_to_ranges method"""

    def test_offsets_to_ranges_simple(self):
        to_range = HttpTransportBase.offsets_to_ranges
        ranges = to_range([(10, 1)])
        self.assertEqual([[10, 10]], ranges)

        ranges = to_range([(0, 1), (1, 1)])
        self.assertEqual([[0, 1]], ranges)

        ranges = to_range([(1, 1), (0, 1)])
        self.assertEqual([[0, 1]], ranges)

    def test_offset_to_ranges_overlapped(self):
        to_range = HttpTransportBase.offsets_to_ranges

        ranges = to_range([(10, 1), (20, 2), (22, 5)])
        self.assertEqual([[10, 10], [20, 26]], ranges)

        ranges = to_range([(10, 1), (11, 2), (22, 5)])
        self.assertEqual([[10, 12], [22, 26]], ranges)


class TestRangeHeader(TestCase):
    """Test range_header method"""

    def check_header(self, value, ranges=[], tail=0):
        range_header = HttpTransportBase.range_header
        self.assertEqual(value, range_header(ranges, tail))

    def test_range_header_single(self):
        self.check_header('0-9', ranges=[[0,9]])
        self.check_header('100-109', ranges=[[100,109]])

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


class TestWallServer(object):
    """Tests exceptions during the connection phase"""

    def create_transport_readonly_server(self):
        return HttpServer(WallRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(ConnectionError, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(ConnectionError, t.get, 'foo/bar')


class TestWallServer_urllib(TestWallServer, TestCaseWithWebserver):
    """Tests WallServer for urllib implementation"""

    _transport = HttpTransport_urllib


class TestWallServer_pycurl(TestWithTransport_pycurl,
                            TestWallServer,
                            TestCaseWithWebserver):
    """Tests WallServer for pycurl implementation"""


class TestBadStatusServer(object):
    """Tests bad status from server."""

    def create_transport_readonly_server(self):
        return HttpServer(BadStatusRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(InvalidHttpResponse, t.get, 'foo/bar')


class TestBadStatusServer_urllib(TestBadStatusServer, TestCaseWithWebserver):
    """Tests BadStatusServer for urllib implementation"""

    _transport = HttpTransport_urllib


class TestBadStatusServer_pycurl(TestWithTransport_pycurl,
                                 TestBadStatusServer,
                                 TestCaseWithWebserver):
    """Tests BadStatusServer for pycurl implementation"""


class TestInvalidStatusServer(TestBadStatusServer):
    """Tests invalid status from server.

    Both implementations raises the same error as for a bad status.
    """

    def create_transport_readonly_server(self):
        return HttpServer(InvalidStatusRequestHandler)


class TestInvalidStatusServer_urllib(TestInvalidStatusServer,
                                     TestCaseWithWebserver):
    """Tests InvalidStatusServer for urllib implementation"""

    _transport = HttpTransport_urllib


class TestInvalidStatusServer_pycurl(TestWithTransport_pycurl,
                                     TestInvalidStatusServer,
                                     TestCaseWithWebserver):
    """Tests InvalidStatusServer for pycurl implementation"""


class TestBadProtocolServer(object):
    """Tests bad status from server."""

    def create_transport_readonly_server(self):
        return HttpServer(BadProtocolRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(InvalidHttpResponse, t.get, 'foo/bar')


class TestBadProtocolServer_urllib(TestBadProtocolServer,
                                   TestCaseWithWebserver):
    """Tests BadProtocolServer for urllib implementation"""

    _transport = HttpTransport_urllib

# curl don't check the protocol version
#class TestBadProtocolServer_pycurl(TestWithTransport_pycurl,
#                                   TestBadProtocolServer,
#                                   TestCaseWithWebserver):
#    """Tests BadProtocolServer for pycurl implementation"""


class TestRangesServer(object):
    """Tests range requests against a server.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithWebserver.

    We can't inherit directly from TestCaseWithWebserver or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        transport = self.get_transport()
        if transport.is_readonly():
            file('a', 'w').write('0123456789')
        else:
            transport.put_bytes('a', '0123456789')

    def test_single_range(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        content = t.readv(_file_10, )

        self.assertRaises(errors.InvalidRange, out.read, 20)

        out.seek(100)
        self.assertEqual(_single_range_response[2], out.read(100))

    def test_single_range_no_content(self):
        out = self.get_response(_single_range_no_content_type)
        self.assertIsInstance(out, response.HttpRangeResponse)

        self.assertRaises(errors.InvalidRange, out.read, 20)

        out.seek(100)
        self.assertEqual(_single_range_no_content_type[2], out.read(100))

    def test_multi_range(self):
        out = self.get_response(_multipart_range_response)
        self.assertIsInstance(out, response.HttpMultipartRangeResponse)

        # Just make sure we can read the right contents
        out.seek(0)
        out.read(255)

        out.seek(1000)
        out.read(1050)

    def test_multi_squid_range(self):
        out = self.get_response(_multipart_squid_range_response)
        self.assertIsInstance(out, response.HttpMultipartRangeResponse)

        # Just make sure we can read the right contents
        out.seek(0)
        out.read(100)

        out.seek(300)
        out.read(200)

    def test_full_text_no_content_type(self):
        # We should not require Content-Type for a full response
        a_response = _full_text_response
        headers = http._extract_headers(a_response[1], 'http://foo')
        del headers['Content-Type']
        out = response.handle_response('http://foo', a_response[0], headers,
                                        StringIO(a_response[2]))
        self.assertEqual(_full_text_response[2], out.read())

    def test_missing_content_range(self):
        a_response = _single_range_response
        headers = http._extract_headers(a_response[1], 'http://nocontent')
        del headers['Content-Range']
        self.assertRaises(errors.InvalidHttpResponse,
            response.handle_response, 'http://nocontent', a_response[0],
                                      headers, StringIO(a_response[2]))

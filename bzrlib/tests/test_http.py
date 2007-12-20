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

"""Tests for HTTP test framework and implementation neutral code.

Code that need to be tested against implementations or variations of the HTTP
protocol should go in test_http_implementations.py
"""

# TODO: Should be renamed to bzrlib.transport.http.tests?
# TODO: What about renaming to bzrlib.tests.transport.http ?

from cStringIO import StringIO
import httplib
import os
import select
import socket
import sys
import threading

import bzrlib
from bzrlib import (
    config,
    errors,
    osutils,
    tests,
    transport,
    ui,
    urlutils,
    )
from bzrlib.tests import (
    http_server,
    http_utils,
    )
from bzrlib.tests.http_utils import (
    HTTPBasicAuthServer,
    HTTPDigestAuthServer,
    HTTPServerRedirecting,
    ProxyBasicAuthServer,
    ProxyDigestAuthServer,
    ProxyServer,
    TestCaseWithRedirectedWebserver,
    TestCaseWithTwoWebservers,
    TestCaseWithWebserver,
    )
from bzrlib.transport.http import (
    extract_auth,
    HttpTransportBase,
    _urllib2_wrappers,
    )
from bzrlib.transport.http._urllib import HttpTransport_urllib
from bzrlib.transport.http._urllib2_wrappers import (
    ProxyHandler,
    Request,
    )


class FakeManager(object):

    def __init__(self):
        self.credentials = []

    def add_password(self, realm, host, username, password):
        self.credentials.append([realm, host, username, password])


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
        try:
            self.assertIsInstance(server._httpd, http_server.TestingHTTPServer)
        finally:
            server.tearDown()

    def test_create_http_server_one_one(self):
        class RequestHandlerOneOne(http_server.TestingHTTPRequestHandler):

            protocol_version = 'HTTP/1.1'

        server = http_server.HttpServer(RequestHandlerOneOne)
        server.setUp()
        try:
            self.assertIsInstance(server._httpd,
                                  http_server.TestingThreadingHTTPServer)
        finally:
            server.tearDown()


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
        url = extract_auth('http://example.com', f)
        self.assertEquals('http://example.com', url)
        self.assertEquals(0, len(f.credentials))
        url = extract_auth('http://user:pass@www.bazaar-vcs.org/bzr/bzr.dev', f)
        self.assertEquals('http://www.bazaar-vcs.org/bzr/bzr.dev', url)
        self.assertEquals(1, len(f.credentials))
        self.assertEquals([None, 'www.bazaar-vcs.org', 'user', 'pass'],
                          f.credentials[0])


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

class TestRangeHeader(tests.TestCase):
    """Test range_header method"""

    def check_header(self, value, ranges=[], tail=0):
        offsets = [ (start, end - start + 1) for start, end in ranges]
        coalesce = transport.Transport._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        range_header = HttpTransportBase._range_header
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


class TestRecordingServer(tests.TestCase):

    def test_create(self):
        server = http_utils.RecordingServer(expect_body_tail=None)
        self.assertEqual('', server.received_bytes)
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_setUp_and_tearDown(self):
        server = http_utils.RecordingServer(expect_body_tail=None)
        server.setUp()
        try:
            self.assertNotEqual(None, server.host)
            self.assertNotEqual(None, server.port)
        finally:
            server.tearDown()
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_send_receive_bytes(self):
        server = http_utils.RecordingServer(expect_body_tail='c')
        server.setUp()
        self.addCleanup(server.tearDown)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server.host, server.port))
        sock.sendall('abc')
        self.assertEqual('HTTP/1.1 200 OK\r\n',
                         osutils.recv_all(sock, 4096))
        self.assertEqual('abc', server.received_bytes)


class TestHttpProxyWhiteBox(tests.TestCase):
    """Whitebox test proxy http authorization.

    Only the urllib implementation is tested here.
    """

    def setUp(self):
        tests.TestCase.setUp(self)
        self._old_env = {}

    def tearDown(self):
        self._restore_env()

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def _proxied_request(self):
        handler = ProxyHandler()
        request = Request('GET','http://baz/buzzle')
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



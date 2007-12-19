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



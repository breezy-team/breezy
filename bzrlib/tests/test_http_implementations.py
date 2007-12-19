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

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.tests import (
    http_server,
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



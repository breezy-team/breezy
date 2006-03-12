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

import bzrlib
import bzrlib.errors as errors
from bzrlib.tests import TestCase
from bzrlib.transport import Transport
from bzrlib.transport.http import extract_auth
from bzrlib.transport.http._urllib import HttpTransport_urllib
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver

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
        url = extract_auth('http://user:pass@www.bazaar-ng.org/bzr/bzr.dev', f)
        self.assertEquals('http://www.bazaar-ng.org/bzr/bzr.dev', url)
        self.assertEquals(1, len(f.credentials))
        self.assertEquals([None, 'www.bazaar-ng.org', 'user', 'pass'], f.credentials[0])
        
    def test_abs_url(self):
        """Construction of absolute http URLs"""
        t = HttpTransport_urllib('http://bazaar-ng.org/bzr/bzr.dev/')
        eq = self.assertEqualDiff
        eq(t.abspath('.'),
           'http://bazaar-ng.org/bzr/bzr.dev')
        eq(t.abspath('foo/bar'), 
           'http://bazaar-ng.org/bzr/bzr.dev/foo/bar')
        eq(t.abspath('.bzr'),
           'http://bazaar-ng.org/bzr/bzr.dev/.bzr')
        eq(t.abspath('.bzr/1//2/./3'),
           'http://bazaar-ng.org/bzr/bzr.dev/.bzr/1/2/3')

    def test_invalid_http_urls(self):
        """Trap invalid construction of urls"""
        t = HttpTransport_urllib('http://bazaar-ng.org/bzr/bzr.dev/')
        self.assertRaises(ValueError,
            t.abspath,
            '.bzr/')
        self.assertRaises(ValueError,
            t.abspath,
            '/.bzr')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = HttpTransport_urllib('http://bzr.ozlabs.org/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://bzr.ozlabs.org/.bzr/tree-version')

    def test_http_impl_urls(self):
        """There are servers which ask for particular clients to connect"""
        try:
            from bzrlib.transport.http._pycurl import HttpServer_PyCurl
            server = HttpServer_PyCurl()
            try:
                server.setUp()
                url = server.get_url()
                self.assertTrue(url.startswith('http+pycurl://'))
            finally:
                server.tearDown()
        except errors.DependencyNotPresent:
            raise TestSkipped('pycurl not present')

class TestHttpConnections(TestCaseWithWebserver):

    _transport = HttpTransport_urllib

    def setUp(self):
        super(TestHttpConnections, self).setUp()
        self.build_tree(['xxx', 'foo/', 'foo/bar'], line_endings='binary')

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
            '"GET /foo/bar HTTP/1.1" 200 - "-" "bzr/%s' % bzrlib.__version__) > -1)


class TestHttpConnections_pycurl(TestHttpConnections):

    def setUp(self):
        super(TestHttpConnections_pycurl, self).setUp()
        try:
            from bzrlib.transport.http._pycurl import PyCurlTransport
            self._transport = PyCurlTransport
        except errors.DependencyNotPresent:
            raise TestSkipped('pycurl not present')


class TestHttpTransportRegistration(TestCase):
    """Test registrations of various http implementations"""

    def test_http_registered(self):
        import bzrlib.transport.http._urllib
        from bzrlib.transport import get_transport
        # urlllib should always be present
        t = get_transport('http+urllib://bzr.google.com/')
        self.assertIsInstance(t, Transport)
        self.assertIsInstance(t, bzrlib.transport.http._urllib.HttpTransport_urllib)

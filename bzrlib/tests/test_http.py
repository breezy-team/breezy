# (C) 2005 Canonical

import threading
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
import urllib2

import bzrlib
from bzrlib.tests import TestCase
from bzrlib.transport.http import HttpTransport, extract_auth

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
        t = HttpTransport('http://bazaar-ng.org/bzr/bzr.dev/')
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
        t = HttpTransport('http://bazaar-ng.org/bzr/bzr.dev/')
        self.assertRaises(ValueError,
            t.abspath,
            '.bzr/')
        self.assertRaises(ValueError,
            t.abspath,
            '/.bzr')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = HttpTransport('http://bzr.ozlabs.org/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://bzr.ozlabs.org/.bzr/tree-version')


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain;charset=UTF-8')
        self.end_headers()
        self.wfile.write('Path: %s\nUser-agent: %s\n' %
                         (self.path, self.headers.getheader('user-agent', '')))
        self.close_connection = True


class TestHttpConnections(TestCase):

    def setUp(self):
        """Set up a dummy HTTP server as a thread.

        The server will serve a single request and then quit.
        """
        super(TestHttpConnections, self).setUp()
        self.httpd = HTTPServer(('127.0.0.1', 0), RequestHandler)
        host, port = self.httpd.socket.getsockname()
        self.baseurl = 'http://127.0.0.1:%d/' % port
        self.quit_server = False
        self.thread = threading.Thread(target=self._run_http)
        self.thread.start()

    def _run_http(self):
        while not self.quit_server:
            self.httpd.handle_request()
        self.httpd.server_close()

    def tearDown(self):
        # tell the server to quit, and issue a request to make sure the
        # mainloop gets run
        self.quit_server = True
        try:
            response = urllib2.urlopen(self.baseurl)
            response.read()
        except IOError:
            # ignore error, in case server has already quit
            pass
        self.thread.join()
        
        super(TestHttpConnections, self).tearDown()

    def test_http_has(self):
        t = HttpTransport(self.baseurl)
        self.assertEqual(t.has('foo/bar'), True)

    def test_http_get(self):
        t = HttpTransport(self.baseurl)
        fp = t.get('foo/bar')
        self.assertEqualDiff(
            fp.read(),
            'Path: /foo/bar\nUser-agent: bzr/%s\n' % bzrlib.__version__)

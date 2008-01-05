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

"""HTTPS test server, available when ssl python module is available"""

import ssl

from bzrlib.tests import (
    http_server,
    ssl_certs,
    )


class TestingHTTPSServerMixin:

    def __init__(self, key_file, cert_file):
        self.key_file = key_file
        self.cert_file = cert_file

    def get_request (self):
        """Get the request and client address from the socket.

        This is called in response to a connection issued to the server, we
        wrap the socket with SSL.
        """
        sock, addr = self.socket.accept()
        sslconn = ssl.wrap_socket(sock, server_side=True,
                                  keyfile=self.key_file,
                                  certfile=self.cert_file)
        return sslconn, addr

class TestingHTTPSServer(TestingHTTPSServerMixin,
                         http_server.TestingHTTPServer):

    def __init__(self, server_address, request_handler_class,
                 test_case_server, key_file, cert_file):
        TestingHTTPSServerMixin.__init__(self, key_file, cert_file)
        http_server.TestingHTTPServer.__init__(
            self, server_address, request_handler_class, test_case_server)


class TestingThreadingHTTPSServer(TestingHTTPSServerMixin,
                                  http_server.TestingThreadingHTTPServer):

    def __init__(self, server_address, request_handler_class,
                 test_case_server, key_file, cert_file):
        TestingHTTPSServerMixin.__init__(self, key_file, cert_file)
        http_server.TestingThreadingHTTPServer.__init__(
            self, server_address, request_handler_class, test_case_server)


class HTTPSServer(http_server.HttpServer):

    _url_protocol = 'https'

    # The real servers depending on the protocol
    http_server_class = {'HTTP/1.0': TestingHTTPSServer,
                         'HTTP/1.1': TestingThreadingHTTPSServer,
                         }

    # Provides usable defaults since an https server requires both a
    # private key and certificate to work.
    def __init__(self, request_handler=http_server.TestingHTTPRequestHandler,
                 key_file=ssl_certs.build_path('server_without_pass.key'),
                 cert_file=ssl_certs.build_path('server.crt')):
        http_server.HttpServer.__init__(self, request_handler)
        self.key_file = key_file
        self.cert_file = cert_file
        self.temp_files = []

    def create_httpd(self, serv_cls, rhandler_cls):
        return serv_cls((self.host, self.port), self.request_handler,
                        self, self.key_file, self.cert_file)


class HTTPSServer_urllib(HTTPSServer):
    """Subclass of HTTPSServer that gives https+urllib urls.

    This is for use in testing: connections to this server will always go
    through urllib where possible.
    """

    # urls returned by this server should require the urllib client impl
    _url_protocol = 'https+urllib'


class HTTPSServer_PyCurl(HTTPSServer):
    """Subclass of HTTPSServer that gives http+pycurl urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    """

    # We don't care about checking the pycurl availability as
    # this server will be required only when pycurl is present

    # urls returned by this server should require the pycurl client impl
    _url_protocol = 'https+pycurl'

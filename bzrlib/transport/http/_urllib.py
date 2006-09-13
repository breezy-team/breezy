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

import errno
import urllib, urllib2
import errno
from StringIO import StringIO

import bzrlib  # for the version
from bzrlib.errors import (TransportNotPossible,
                           NoSuchFile,
                           BzrError,
                           TransportError,
                           ConnectionError,
                           )
from bzrlib.trace import mutter
from bzrlib.transport import register_urlparse_netloc_protocol
from bzrlib.transport.http import (HttpTransportBase,
                                   HttpServer,
                                   extract_auth)
# TODO: handle_response should integrated into the _urllib2_wrappers
from bzrlib.transport.http.response import (
    handle_response
    )
from bzrlib.transport.http._urllib2_wrappers import (
    Request,
    Opener,
    )

register_urlparse_netloc_protocol('http+urllib')

class HttpTransport_urllib(HttpTransportBase):
    """Python urllib transport for http and https."""

    # In order to debug we have to issue our traces in syc with
    # httplib, which use print :(
    _debuglevel = 0

    # TODO: Implement pipelined versions of all of the *_multi() functions.

    def __init__(self, base, from_transport=None, opener=Opener()):
        """Set the base path where files will be stored."""
        super(HttpTransport_urllib, self).__init__(base)
        if from_transport is not None:
            self._accept_ranges = from_transport._accept_ranges
            self._connection = from_transport._connection
        else:
            self._accept_ranges = True
            self._connection = None
        self._opener = opener

    def _perform(self, request):
        """Send the request to the server and handles common errors.
        """
        # Give back connection if we have one (see below)
        if self._connection is not None:
            request.connection = self._connection

        mutter('%s: [%s]' % (request.method, request.get_full_url()))
        if self._debuglevel > 0:
            print 'perform: %s base: %s, url: %s' % (request.method, self.base,
                                                     request.get_full_url())

        response = self._opener.open(request)
        if self._connection is None:
            # Acquire connection when the first request is able
            # to connect to the server
            self._connection = request.connection

        if request.redirected_to is not None:
            # TODO: Update the transport so that subsequent
            # requests goes directly to the right host
            mutter('redirected from: %s to: %s' % (request.get_full_url(),
                                                   request.redirected_to))

        return response

    def _get(self, relpath, ranges, tail_amount=0):
        """See HttpTransport._get"""

        abspath = self._real_abspath(relpath)
        headers = {}
        if ranges or tail_amount:
            bytes = 'bytes=' + self.range_header(ranges, tail_amount)
            headers = {'Range': bytes}
        
        request = Request('GET', abspath, None, headers)
        response = self._perform(request)

        code = response.code
        if code == 404: # not found
            # FIXME: Check that there is really no message to be read
            self._connection.fake_close()
            raise NoSuchFile(abspath)

        data = handle_response(abspath, code, response.headers, response)
        # Close response to free the httplib.HTTPConnection pipeline
        self._connection.fake_close()
        return code, data

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._real_abspath(relpath)
        request = Request('HEAD', abspath)
        response = self._perform(request)

        self._connection.fake_close()
        return response

    def has(self, relpath):
        """Does the target location exist?
        """
        response = self._head(relpath)

        code = response.code
        # FIXME: 302 MAY have been already processed by the
        # redirection handler
        if code in (200, 302): # "ok", "found"
            return True
        else:
            assert(code == 404, 'Only 200, 404 or may be 302 are correct')
            return False


class HttpServer_urllib(HttpServer):
    """Subclass of HttpServer that gives http+urllib urls.

    This is for use in testing: connections to this server will always go
    through urllib where possible.
    """

    # urls returned by this server should require the urllib client impl
    _url_protocol = 'http+urllib'


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(HttpTransport_urllib, HttpServer_urllib),
            ]

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

from cStringIO import StringIO
import urllib
import urlparse

from bzrlib import (
    errors,
    urlutils,
    )
from bzrlib.trace import mutter
from bzrlib.transport import register_urlparse_netloc_protocol
from bzrlib.transport.http import HttpTransportBase
# TODO: handle_response should be integrated into the _urllib2_wrappers
from bzrlib.transport.http.response import handle_response
from bzrlib.transport.http._urllib2_wrappers import (
    Opener,
    Request,
    extract_authentication_uri,
    extract_credentials,
    )


register_urlparse_netloc_protocol('http+urllib')


class HttpTransport_urllib(HttpTransportBase):
    """Python urllib transport for http and https."""

    # In order to debug we have to issue our traces in sync with
    # httplib, which use print :(
    _debuglevel = 0

    _opener_class = Opener

    def __init__(self, base, from_transport=None):
        super(HttpTransport_urllib, self).__init__(base, from_transport)
        if from_transport is not None:
            self._opener = from_transport._opener
        else:
            self._opener = self._opener_class()

    def _remote_path(self, relpath):
        """Produce absolute path, adjusting protocol."""
        relative = urlutils.unescape(relpath).encode('utf-8')
        path = self._combine_paths(self._path, relative)
        # urllib2 will be confused if it find authentication
        # info (user, password) in the urls. So we handle them separatly.
        return self._unsplit_url(self._unqualified_scheme,
                                 None, None, self._host, self._port, path)

    def _perform(self, request):
        """Send the request to the server and handles common errors.

        :returns: urllib2 Response object
        """
        connection = self._get_connection()
        if connection is not None:
            # Give back shared info
            request.connection = connection
            (auth, proxy_auth) = self._get_credentials()
        else:
            # First request, intialize credentials
            user = self._user
            password = self._password
            authuri = self._remote_path('.')
            auth = {'user': user, 'password': password, 'authuri': authuri}

            if user and password is not None: # '' is a valid password
                # Make the (user, password) available to urllib2
                # We default to a realm of None to catch them all.
                self._opener.password_manager.add_password(None, authuri,
                                                           user, password)
            proxy_auth = {}
        # Ensure authentication info is provided
        request.auth = auth
        request.proxy_auth = proxy_auth

        mutter('%s: [%s]' % (request.method, request.get_full_url()))
        if self._debuglevel > 0:
            print 'perform: %s base: %s, url: %s' % (request.method, self.base,
                                                     request.get_full_url())
        response = self._opener.open(request)
        if self._get_connection() is not request.connection:
            # First connection or reconnection
            self._set_connection(request.connection,
                                 (request.auth, request.proxy_auth))
        else:
            # http may change the credentials while keeping the
            # connection opened
            self._update_credentials((request.auth, request.proxy_auth))

        code = response.code
        if request.follow_redirections is False \
                and code in (301, 302, 303, 307):
            raise errors.RedirectRequested(request.get_full_url(),
                                           request.redirected_to,
                                           is_permament=(code == 301),
                                           qual_proto=self._scheme)

        if request.redirected_to is not None:
            mutter('redirected from: %s to: %s' % (request.get_full_url(),
                                                   request.redirected_to))

        return response

    def _get(self, relpath, ranges, tail_amount=0):
        """See HttpTransport._get"""

        abspath = self._remote_path(relpath)
        headers = {}
        if ranges or tail_amount:
            range_header = self.attempted_range_header(ranges, tail_amount)
            if range_header is not None:
                bytes = 'bytes=' + range_header
                headers = {'Range': bytes}

        request = Request('GET', abspath, None, headers)
        response = self._perform(request)

        code = response.code
        if code == 404: # not found
            self._get_connection().fake_close()
            raise errors.NoSuchFile(abspath)

        data = handle_response(abspath, code, response.headers, response)
        # Close response to free the httplib.HTTPConnection pipeline
        self._get_connection().fake_close()
        return code, data

    def _post(self, body_bytes):
        abspath = self._remote_path('.bzr/smart')
        response = self._perform(Request('POST', abspath, body_bytes))
        code = response.code
        data = handle_response(abspath, code, response.headers, response)
        # Close response to free the httplib.HTTPConnection pipeline
        self._get_connection().fake_close()
        return code, data

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._remote_path(relpath)
        request = Request('HEAD', abspath)
        response = self._perform(request)

        self._get_connection().fake_close()
        return response

    def has(self, relpath):
        """Does the target location exist?
        """
        response = self._head(relpath)

        code = response.code
        if code == 200: # "ok",
            return True
        else:
            assert(code == 404, 'Only 200 or 404 are correct')
            return False


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from bzrlib.tests.HttpServer import HttpServer_urllib
    return [(HttpTransport_urllib, HttpServer_urllib),
            ]

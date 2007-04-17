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
    ui,
    errors,
    )
from bzrlib.trace import mutter
from bzrlib.transport import register_urlparse_netloc_protocol
from bzrlib.transport.http import HttpTransportBase
# TODO: handle_response should be integrated into the _urllib2_wrappers
from bzrlib.transport.http.response import handle_response
from bzrlib.transport.http._urllib2_wrappers import (
    Opener,
    Request,
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
        """Set the base path where files will be stored."""
        if from_transport is not None:
            super(HttpTransport_urllib, self).__init__(base, from_transport)
            self._connection = from_transport._connection
            self._auth_scheme = from_transport._auth_scheme
            self._user = from_transport._user
            self._password = from_transport._password
            self._opener = from_transport._opener
        else:
            # urllib2 will be confused if it find authentication
            # info in the urls. So we handle them separatly.
            # Note: we don't need to when cloning because it was
            # already done.
            clean_base, user, password = extract_credentials(base)
            super(HttpTransport_urllib, self).__init__(clean_base,
                                                       from_transport)
            self._connection = None
            # auth_scheme will be set once we authenticate
            # successfully after a 401 error.
            self._auth_scheme = None
            self._user = user
            self._password = password
            self._opener = self._opener_class()
            if user and password is not None: # '' is a valid password
                # Make the (user, password) available to urllib2
                pm = self._opener.password_manager
                pm.add_password(None, self.base, self._user, self._password)

    def _ask_password(self):
        """Ask for a password if none is already available"""
        if self._password is None:
            # We can't predict realm, let's try None, we'll get a
            # 401 if we are wrong anyway
            realm = None
            # Query the password manager first
            authuri = self.base
            pm = self._opener.password_manager
            user, password = pm.find_user_password(None, authuri)
            if user == self._user and password is not None:
                self._password = password
            else:
                # Ask the user if we MUST
                http_pass = 'HTTP %(user)s@%(host)s password'
                self._password = ui.ui_factory.get_password(prompt=http_pass,
                                                            user=self._user,
                                                            host=self._host)
                pm.add_password(None, authuri, self._user, self._password)

    def _perform(self, request):
        """Send the request to the server and handles common errors.

        :returns: urllib2 Response object
        """
        if self._connection is not None:
            # Give back shared info
            request.connection = self._connection
        elif self._user:
            # We will issue our first request, time to ask for a
            # password if needed
            self._ask_password()
        # Ensure authentication info is provided
        request.set_auth(self._auth_scheme, self._user, self._password)

        mutter('%s: [%s]' % (request.method, request.get_full_url()))
        if self._debuglevel > 0:
            print 'perform: %s base: %s, url: %s' % (request.method, self.base,
                                                     request.get_full_url())

        response = self._opener.open(request)
        if self._connection is None:
            # Acquire connection when the first request is able
            # to connect to the server
            self._connection = request.connection
            # And get auth parameters too
            self._auth_scheme = request.auth_scheme
            self._user = request.user
            self._password = request.password

        code = response.code
        if request.follow_redirections is False \
                and code in (301, 302, 303, 307):
            raise errors.RedirectRequested(request.get_full_url(),
                                           request.redirected_to,
                                           is_permament=(code == 301),
                                           qual_proto=self._qualified_proto)

        if request.redirected_to is not None:
            mutter('redirected from: %s to: %s' % (request.get_full_url(),
                                                   request.redirected_to))

        return response

    def _get(self, relpath, ranges, tail_amount=0):
        """See HttpTransport._get"""

        abspath = self._real_abspath(relpath)
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
            self._connection.fake_close()
            raise errors.NoSuchFile(abspath)

        data = handle_response(abspath, code, response.headers, response)
        # Close response to free the httplib.HTTPConnection pipeline
        self._connection.fake_close()
        return code, data

    def _post(self, body_bytes):
        abspath = self._real_abspath('.bzr/smart')
        response = self._perform(Request('POST', abspath, body_bytes))
        code = response.code
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

# Copyright (C) 2006-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from __future__ import absolute_import

from bzrlib import (
    errors,
    trace,
    )
from bzrlib.transport import http
# TODO: handle_response should be integrated into the http/__init__.py
from bzrlib.transport.http.response import handle_response
from bzrlib.transport.http._urllib2_wrappers import (
    Opener,
    Request,
    )


class HttpTransport_urllib(http.HttpTransportBase):
    """Python urllib transport for http and https."""

    # In order to debug we have to issue our traces in sync with
    # httplib, which use print :(
    _debuglevel = 0

    _opener_class = Opener

    def __init__(self, base, _from_transport=None, ca_certs=None):
        super(HttpTransport_urllib, self).__init__(
            base, 'urllib', _from_transport=_from_transport)
        if _from_transport is not None:
            self._opener = _from_transport._opener
        else:
            self._opener = self._opener_class(
                report_activity=self._report_activity, ca_certs=ca_certs)

    def _perform(self, request):
        """Send the request to the server and handles common errors.

        :returns: urllib2 Response object
        """
        connection = self._get_connection()
        if connection is not None:
            # Give back shared info
            request.connection = connection
            (auth, proxy_auth) = self._get_credentials()
            # Clean the httplib.HTTPConnection pipeline in case the previous
            # request couldn't do it
            connection.cleanup_pipe()
        else:
            # First request, initialize credentials.
            # scheme and realm will be set by the _urllib2_wrappers.AuthHandler
            auth = self._create_auth()
            # Proxy initialization will be done by the first proxied request
            proxy_auth = dict()
        # Ensure authentication info is provided
        request.auth = auth
        request.proxy_auth = proxy_auth

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
        if (request.follow_redirections is False
            and code in (301, 302, 303, 307)):
            raise errors.RedirectRequested(request.get_full_url(),
                                           request.redirected_to,
                                           is_permanent=(code == 301))

        if request.redirected_to is not None:
            trace.mutter('redirected from: %s to: %s' % (request.get_full_url(),
                                                         request.redirected_to))

        return response

    def disconnect(self):
        connection = self._get_connection()
        if connection is not None:
            connection.close()

    def _get(self, relpath, offsets, tail_amount=0):
        """See HttpTransport._get"""
        abspath = self._remote_path(relpath)
        headers = {}
        accepted_errors = [200, 404]
        if offsets or tail_amount:
            range_header = self._attempted_range_header(offsets, tail_amount)
            if range_header is not None:
                accepted_errors.append(206)
                accepted_errors.append(400)
                accepted_errors.append(416)
                bytes = 'bytes=' + range_header
                headers = {'Range': bytes}

        request = Request('GET', abspath, None, headers,
                          accepted_errors=accepted_errors)
        response = self._perform(request)

        code = response.code
        if code == 404: # not found
            raise errors.NoSuchFile(abspath)
        elif code in (400, 416):
            # We don't know which, but one of the ranges we specified was
            # wrong.
            raise errors.InvalidHttpRange(abspath, range_header,
                                          'Server return code %d' % code)

        data = handle_response(abspath, code, response.info(), response)
        return code, data

    def _post(self, body_bytes):
        abspath = self._remote_path('.bzr/smart')
        # We include 403 in accepted_errors so that send_http_smart_request can
        # handle a 403.  Otherwise a 403 causes an unhandled TransportError.
        response = self._perform(
            Request('POST', abspath, body_bytes,
                    {'Content-Type': 'application/octet-stream'},
                    accepted_errors=[200, 403]))
        code = response.code
        data = handle_response(abspath, code, response.info(), response)
        return code, data

    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._remote_path(relpath)
        request = Request('HEAD', abspath,
                          accepted_errors=[200, 404])
        response = self._perform(request)

        return response

    def has(self, relpath):
        """Does the target location exist?
        """
        response = self._head(relpath)

        code = response.code
        if code == 200: # "ok",
            return True
        else:
            return False


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from bzrlib.tests import (
        features,
        http_server,
        )
    permutations = [(HttpTransport_urllib, http_server.HttpServer_urllib),]
    if features.HTTPSServerFeature.available():
        from bzrlib.tests import (
            https_server,
            ssl_certs,
            )

        class HTTPS_urllib_transport(HttpTransport_urllib):

            def __init__(self, base, _from_transport=None):
                super(HTTPS_urllib_transport, self).__init__(
                    base, _from_transport=_from_transport,
                    ca_certs=ssl_certs.build_path('ca.crt'))

        permutations.append((HTTPS_urllib_transport,
                             https_server.HTTPSServer_urllib))
    return permutations

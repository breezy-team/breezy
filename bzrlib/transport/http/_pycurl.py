# Copyright (C) 2006 Canonical Ltd
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

"""http/https transport using pycurl"""

# TODO: test reporting of http errors
#
# TODO: Transport option to control caching of particular requests; broadly we
# would want to offer "caching allowed" or "must revalidate", depending on
# whether we expect a particular file will be modified after it's committed.
# It's probably safer to just always revalidate.  mbp 20060321

# TODO: Some refactoring could be done to avoid the strange idiom
# used to capture data and headers while setting up the request
# (and having to pass 'header' to _curl_perform to handle
# redirections) . This could be achieved by creating a
# specialized Curl object and returning code, headers and data
# from _curl_perform.  Not done because we may deprecate pycurl in the
# future -- vila 20070212

import os
from cStringIO import StringIO
import httplib
import sys

from bzrlib import (
    debug,
    errors,
    trace,
    __version__ as bzrlib_version,
    )
import bzrlib
from bzrlib.trace import mutter
from bzrlib.transport.http import (
    ca_bundle,
    HttpTransportBase,
    response,
    )

try:
    import pycurl
except ImportError, e:
    mutter("failed to import pycurl: %s", e)
    raise errors.DependencyNotPresent('pycurl', e)

try:
    # see if we can actually initialize PyCurl - sometimes it will load but
    # fail to start up due to this bug:
    #  
    #   32. (At least on Windows) If libcurl is built with c-ares and there's
    #   no DNS server configured in the system, the ares_init() call fails and
    #   thus curl_easy_init() fails as well. This causes weird effects for
    #   people who use numerical IP addresses only.
    #
    # reported by Alexander Belchenko, 2006-04-26
    pycurl.Curl()
except pycurl.error, e:
    mutter("failed to initialize pycurl: %s", e)
    raise errors.DependencyNotPresent('pycurl', e)




def _get_pycurl_errcode(symbol, default):
    """
    Returns the numerical error code for a symbol defined by pycurl.

    Different pycurl implementations define different symbols for error
    codes. Old versions never define some symbols (wether they can return the
    corresponding error code or not). The following addresses the problem by
    defining the symbols we care about.  Note: this allows to define symbols
    for errors that older versions will never return, which is fine.
    """
    return pycurl.__dict__.get(symbol, default)

CURLE_SSL_CACERT_BADFILE = _get_pycurl_errcode('E_SSL_CACERT_BADFILE', 77)
CURLE_COULDNT_CONNECT = _get_pycurl_errcode('E_COULDNT_CONNECT', 7)
CURLE_COULDNT_RESOLVE_HOST = _get_pycurl_errcode('E_COULDNT_RESOLVE_HOST', 6)
CURLE_COULDNT_RESOLVE_PROXY = _get_pycurl_errcode('E_COULDNT_RESOLVE_PROXY', 5)
CURLE_GOT_NOTHING = _get_pycurl_errcode('E_GOT_NOTHING', 52)
CURLE_PARTIAL_FILE = _get_pycurl_errcode('E_PARTIAL_FILE', 18)


class PyCurlTransport(HttpTransportBase):
    """http client transport using pycurl

    PyCurl is a Python binding to the C "curl" multiprotocol client.

    This transport can be significantly faster than the builtin
    Python client.  Advantages include: DNS caching.
    """

    def __init__(self, base, _from_transport=None):
        super(PyCurlTransport, self).__init__(base,
                                              _from_transport=_from_transport)
        if base.startswith('https'):
            # Check availability of https into pycurl supported
            # protocols
            supported = pycurl.version_info()[8]
            if 'https' not in supported:
                raise errors.DependencyNotPresent('pycurl', 'no https support')
        self.cabundle = ca_bundle.get_ca_path()

    def _get_curl(self):
        connection = self._get_connection()
        if connection is None:
            # First connection ever. There is no credentials for pycurl, either
            # the password was embedded in the URL or it's not needed. The
            # connection for pycurl is just the Curl object, it will not
            # connect to the http server until the first request (which had
            # just called us).
            connection = pycurl.Curl()
            # First request, initialize credentials.
            auth = self._create_auth()
            # Proxy handling is out of reach, so we punt
            self._set_connection(connection, auth)
        return connection

    def has(self, relpath):
        """See Transport.has()"""
        # We set NO BODY=0 in _get_full, so it should be safe
        # to re-use the non-range curl object
        curl = self._get_curl()
        abspath = self._remote_path(relpath)
        curl.setopt(pycurl.URL, abspath)
        self._set_curl_options(curl)
        curl.setopt(pycurl.HTTPGET, 1)
        # don't want the body - ie just do a HEAD request
        # This means "NO BODY" not 'nobody'
        curl.setopt(pycurl.NOBODY, 1)
        # But we need headers to handle redirections
        header = StringIO()
        curl.setopt(pycurl.HEADERFUNCTION, header.write)
        # In some erroneous cases, pycurl will emit text on
        # stdout if we don't catch it (see InvalidStatus tests
        # for one such occurrence).
        blackhole = StringIO()
        curl.setopt(pycurl.WRITEFUNCTION, blackhole.write)
        self._curl_perform(curl, header)
        code = curl.getinfo(pycurl.HTTP_CODE)
        if code == 404: # not found
            return False
        elif code == 200: # "ok"
            return True
        else:
            self._raise_curl_http_error(curl)

    def _get(self, relpath, offsets, tail_amount=0):
        # This just switches based on the type of request
        if offsets is not None or tail_amount not in (0, None):
            return self._get_ranged(relpath, offsets, tail_amount=tail_amount)
        else:
            return self._get_full(relpath)

    def _setup_get_request(self, curl, relpath):
        # Make sure we do a GET request. versions > 7.14.1 also set the
        # NO BODY flag, but we'll do it ourselves in case it is an older
        # pycurl version
        curl.setopt(pycurl.NOBODY, 0)
        curl.setopt(pycurl.HTTPGET, 1)
        return self._setup_request(curl, relpath)

    def _setup_request(self, curl, relpath):
        """Do the common setup stuff for making a request

        :param curl: The curl object to place the request on
        :param relpath: The relative path that we want to get
        :return: (abspath, data, header) 
                 abspath: full url
                 data: file that will be filled with the body
                 header: file that will be filled with the headers
        """
        abspath = self._remote_path(relpath)
        curl.setopt(pycurl.URL, abspath)
        self._set_curl_options(curl)

        data = StringIO()
        header = StringIO()
        curl.setopt(pycurl.WRITEFUNCTION, data.write)
        curl.setopt(pycurl.HEADERFUNCTION, header.write)

        return abspath, data, header

    def _get_full(self, relpath):
        """Make a request for the entire file"""
        curl = self._get_curl()
        abspath, data, header = self._setup_get_request(curl, relpath)
        self._curl_perform(curl, header)

        code = curl.getinfo(pycurl.HTTP_CODE)
        data.seek(0)

        if code == 404:
            raise errors.NoSuchFile(abspath)
        if code != 200:
            self._raise_curl_http_error(
                curl, 'expected 200 or 404 for full response.')

        return code, data

    # The parent class use 0 to minimize the requests, but since we can't
    # exploit the results as soon as they are received (pycurl limitation) we'd
    # better issue more requests and provide a more responsive UI do the cost
    # of more latency costs.
    # If you modify this, think about modifying the comment in http/__init__.py
    # too.
    _get_max_size = 4 * 1024 * 1024

    def _get_ranged(self, relpath, offsets, tail_amount):
        """Make a request for just part of the file."""
        curl = self._get_curl()
        abspath, data, header = self._setup_get_request(curl, relpath)

        range_header = self._attempted_range_header(offsets, tail_amount)
        if range_header is None:
            # Forget ranges, the server can't handle them
            return self._get_full(relpath)

        self._curl_perform(curl, header, ['Range: bytes=%s' % range_header])
        data.seek(0)

        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404: # not found
            raise errors.NoSuchFile(abspath)
        elif code in (400, 416):
            # We don't know which, but one of the ranges we specified was
            # wrong.
            raise errors.InvalidHttpRange(abspath, range_header,
                                          'Server return code %d'
                                          % curl.getinfo(pycurl.HTTP_CODE))
        msg = self._parse_headers(header)
        return code, response.handle_response(abspath, code, msg, data)

    def _parse_headers(self, status_and_headers):
        """Transform the headers provided by curl into an HTTPMessage"""
        status_and_headers.seek(0)
        # Ignore status line
        status_and_headers.readline()
        msg = httplib.HTTPMessage(status_and_headers)
        return msg

    def _post(self, body_bytes):
        fake_file = StringIO(body_bytes)
        curl = self._get_curl()
        # Other places that use the Curl object (returned by _get_curl)
        # for GET requests explicitly set HTTPGET, so it should be safe to
        # re-use the same object for both GETs and POSTs.
        curl.setopt(pycurl.POST, 1)
        curl.setopt(pycurl.POSTFIELDSIZE, len(body_bytes))
        curl.setopt(pycurl.READFUNCTION, fake_file.read)
        abspath, data, header = self._setup_request(curl, '.bzr/smart')
        # We override the Expect: header so that pycurl will send the POST
        # body immediately.
        self._curl_perform(curl, header, ['Expect: '])
        data.seek(0)
        code = curl.getinfo(pycurl.HTTP_CODE)
        msg = self._parse_headers(header)
        return code, response.handle_response(abspath, code, msg, data)

    def _raise_curl_http_error(self, curl, info=None):
        code = curl.getinfo(pycurl.HTTP_CODE)
        url = curl.getinfo(pycurl.EFFECTIVE_URL)
        # Some error codes can be handled the same way for all
        # requests
        if code == 403:
            raise errors.TransportError(
                'Server refuses to fulfill the request (403 Forbidden)'
                ' for %s' % url)
        else:
            if info is None:
                msg = ''
            else:
                msg = ': ' + info
            raise errors.InvalidHttpResponse(
                url, 'Unable to handle http code %d%s' % (code,msg))

    def _set_curl_options(self, curl):
        """Set options for all requests"""
        if 'http' in debug.debug_flags:
            curl.setopt(pycurl.VERBOSE, 1)
            # pycurl doesn't implement the CURLOPT_STDERR option, so we can't
            # do : curl.setopt(pycurl.STDERR, trace._trace_file)

        ua_str = 'bzr/%s (pycurl: %s)' % (bzrlib.__version__, pycurl.version)
        curl.setopt(pycurl.USERAGENT, ua_str)
        if self.cabundle:
            curl.setopt(pycurl.CAINFO, self.cabundle)
        # Set accepted auth methods
        curl.setopt(pycurl.HTTPAUTH, pycurl.HTTPAUTH_ANY)
        curl.setopt(pycurl.PROXYAUTH, pycurl.HTTPAUTH_ANY)
        auth = self._get_credentials()
        user = auth.get('user', None)
        password = auth.get('password', None)
        userpass = None
        if user is not None:
            userpass = user + ':'
            if password is not None: # '' is a valid password
                userpass += password
            curl.setopt(pycurl.USERPWD, userpass)

    def _curl_perform(self, curl, header, more_headers=[]):
        """Perform curl operation and translate exceptions."""
        try:
            # There's no way in http/1.0 to say "must
            # revalidate"; we don't want to force it to always
            # retrieve.  so just turn off the default Pragma
            # provided by Curl.
            headers = ['Cache-control: max-age=0',
                       'Pragma: no-cache',
                       'Connection: Keep-Alive']
            curl.setopt(pycurl.HTTPHEADER, headers + more_headers)
            curl.perform()
        except pycurl.error, e:
            url = curl.getinfo(pycurl.EFFECTIVE_URL)
            mutter('got pycurl error: %s, %s, %s, url: %s ',
                    e[0], e[1], e, url)
            if e[0] in (CURLE_SSL_CACERT_BADFILE,
                        CURLE_COULDNT_RESOLVE_HOST,
                        CURLE_COULDNT_CONNECT,
                        CURLE_GOT_NOTHING,
                        CURLE_COULDNT_RESOLVE_PROXY,):
                raise errors.ConnectionError(
                    'curl connection error (%s)\non %s' % (e[1], url))
            elif e[0] == CURLE_PARTIAL_FILE:
                # Pycurl itself has detected a short read.  We do not have all
                # the information for the ShortReadvError, but that should be
                # enough
                raise errors.ShortReadvError(url,
                                             offset='unknown', length='unknown',
                                             actual='unknown',
                                             extra='Server aborted the request')
            raise
        code = curl.getinfo(pycurl.HTTP_CODE)
        if code in (301, 302, 303, 307):
            url = curl.getinfo(pycurl.EFFECTIVE_URL)
            msg = self._parse_headers(header)
            redirected_to = msg.getheader('location')
            raise errors.RedirectRequested(url,
                                           redirected_to,
                                           is_permanent=(code == 301),
                                           qual_proto=self._scheme)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from bzrlib.tests.http_server import HttpServer_PyCurl
    return [(PyCurlTransport, HttpServer_PyCurl),
            ]

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

import os
from cStringIO import StringIO

from bzrlib import errors
import bzrlib
from bzrlib.errors import (TransportNotPossible, NoSuchFile,
                           TransportError, ConnectionError,
                           DependencyNotPresent)
from bzrlib.trace import mutter
from bzrlib.transport import register_urlparse_netloc_protocol
from bzrlib.transport.http import (HttpTransportBase, HttpServer,
                                   _extract_headers,
                                   response, _pycurl_errors)

try:
    import pycurl
except ImportError, e:
    mutter("failed to import pycurl: %s", e)
    raise DependencyNotPresent('pycurl', e)

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
    raise DependencyNotPresent('pycurl', e)


register_urlparse_netloc_protocol('http+pycurl')


class PyCurlTransport(HttpTransportBase):
    """http client transport using pycurl

    PyCurl is a Python binding to the C "curl" multiprotocol client.

    This transport can be significantly faster than the builtin Python client. 
    Advantages include: DNS caching, connection keepalive, and ability to 
    set headers to allow caching.
    """

    def __init__(self, base, from_transport=None):
        super(PyCurlTransport, self).__init__(base)
        if from_transport is not None:
            self._curl = from_transport._curl
        else:
            mutter('using pycurl %s' % pycurl.version)
            self._curl = pycurl.Curl()

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def has(self, relpath):
        """See Transport.has()"""
        # We set NO BODY=0 in _get_full, so it should be safe
        # to re-use the non-range curl object
        curl = self._curl
        abspath = self._real_abspath(relpath)
        curl.setopt(pycurl.URL, abspath)
        self._set_curl_options(curl)
        curl.setopt(pycurl.HTTPGET, 1)
        # don't want the body - ie just do a HEAD request
        # This means "NO BODY" not 'nobody'
        curl.setopt(pycurl.NOBODY, 1)
        self._curl_perform(curl)
        code = curl.getinfo(pycurl.HTTP_CODE)
        if code == 404: # not found
            return False
        elif code in (200, 302): # "ok", "found"
            return True
        else:
            self._raise_curl_http_error(curl)

    def _get(self, relpath, ranges, tail_amount=0):
        # This just switches based on the type of request
        if ranges is not None or tail_amount not in (0, None):
            return self._get_ranged(relpath, ranges, tail_amount=tail_amount)
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
        abspath = self._real_abspath(relpath)
        curl.setopt(pycurl.URL, abspath)
        self._set_curl_options(curl)

        data = StringIO()
        header = StringIO()
        curl.setopt(pycurl.WRITEFUNCTION, data.write)
        curl.setopt(pycurl.HEADERFUNCTION, header.write)

        return abspath, data, header

    def _get_full(self, relpath):
        """Make a request for the entire file"""
        curl = self._curl
        abspath, data, header = self._setup_get_request(curl, relpath)
        self._curl_perform(curl)

        code = curl.getinfo(pycurl.HTTP_CODE)
        data.seek(0)

        if code == 404:
            raise NoSuchFile(abspath)
        if code != 200:
            self._raise_curl_http_error(
                curl, 'expected 200 or 404 for full response.')

        return code, data

    def _get_ranged(self, relpath, ranges, tail_amount):
        """Make a request for just part of the file."""
        curl = self._curl
        abspath, data, header = self._setup_get_request(curl, relpath)

        self._curl_perform(curl, ['Range: bytes=%s'
                                  % self.range_header(ranges, tail_amount)])
        data.seek(0)

        code = curl.getinfo(pycurl.HTTP_CODE)
        # mutter('header:\n%r', header.getvalue())
        headers = _extract_headers(header.getvalue(), abspath)
        # handle_response will raise NoSuchFile, etc based on the response code
        return code, response.handle_response(abspath, code, headers, data)

    def _post(self, body_bytes):
        fake_file = StringIO(body_bytes)
        curl = self._curl
        # Other places that use _base_curl for GET requests explicitly set
        # HTTPGET, so it should be safe to re-use the same object for both GETs
        # and POSTs.
        curl.setopt(pycurl.POST, 1)
        curl.setopt(pycurl.POSTFIELDSIZE, len(body_bytes))
        curl.setopt(pycurl.READFUNCTION, fake_file.read)
        abspath, data, header = self._setup_request(curl, '.bzr/smart')
        # We override the Expect: header so that pycurl will send the POST
        # body immediately.
        self._curl_perform(curl,['Expect: '])
        data.seek(0)
        code = curl.getinfo(pycurl.HTTP_CODE)
        headers = _extract_headers(header.getvalue(), abspath)
        return code, response.handle_response(abspath, code, headers, data)

    def _raise_curl_http_error(self, curl, info=None):
        code = curl.getinfo(pycurl.HTTP_CODE)
        url = curl.getinfo(pycurl.EFFECTIVE_URL)
        if info is None:
            msg = ''
        else:
            msg = ': ' + info
        raise errors.InvalidHttpResponse(url, 'Unable to handle http code %d%s'
                                              % (code,msg))

    def _set_curl_options(self, curl):
        """Set options for all requests"""
        ## curl.setopt(pycurl.VERBOSE, 1)
        # TODO: maybe include a summary of the pycurl version
        ua_str = 'bzr/%s (pycurl)' % (bzrlib.__version__,)
        curl.setopt(pycurl.USERAGENT, ua_str)
        curl.setopt(pycurl.FOLLOWLOCATION, 1) # follow redirect responses

    def _curl_perform(self, curl, more_headers=[]):
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
            # XXX: There seem to be no symbolic constants for these values.
            url = curl.getinfo(pycurl.EFFECTIVE_URL)
            mutter('got pycurl error: %s, %s, %s, url: %s ',
                    e[0], _pycurl_errors.errorcode[e[0]], e, url)
            if e[0] in (_pycurl_errors.CURLE_COULDNT_RESOLVE_HOST,
                        _pycurl_errors.CURLE_COULDNT_CONNECT,
                        _pycurl_errors.CURLE_COULDNT_RESOLVE_PROXY):
                raise ConnectionError('curl connection error (%s)\non %s'
                              % (e[1], url))
            # jam 20060713 The code didn't use to re-raise the exception here
            # but that seemed bogus
            raise


class HttpServer_PyCurl(HttpServer):
    """Subclass of HttpServer that gives http+pycurl urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    """

    # urls returned by this server should require the pycurl client impl
    _url_protocol = 'http+pycurl'


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(PyCurlTransport, HttpServer_PyCurl),
            ]

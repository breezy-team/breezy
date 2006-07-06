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

# TODO: Transport option to control caching of particular requests; broadly we
# would want to offer "caching allowed" or "must revalidate", depending on
# whether we expect a particular file will be modified after it's committed.
# It's probably safer to just always revalidate.  mbp 20060321

import mimetools
import os
from StringIO import StringIO

import bzrlib
from bzrlib.errors import (TransportNotPossible, NoSuchFile,
                           TransportError, ConnectionError,
                           DependencyNotPresent)
from bzrlib.trace import mutter
from bzrlib.transport import register_urlparse_netloc_protocol
from bzrlib.transport.http import HttpTransportBase, HttpServer

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


class CurlResponse(object):
    """Make a curl response look like a urllib response."""

    def __init__(self, curl_handle):
        # This will hold all the returned data
        self._data = StringIO()
        # And the returned headers go here
        self._header = StringIO()
        self._curl_handle = curl_handle
        self._curl_handle.setopt(pycurl.WRITEFUNCTION, self._data.write)
        self._curl_handle.setopt(pycurl.HEADERFUNCTION, self._header.write)
        
        # Will be filled out by calling update()
        self.headers = None
        self.code = None

        # Overload some functions used elsewhere
        self.read = self._data.read
        self.seek = self._data.seek
        self.tell = self._data.tell

    def update(self):
        """Update self after the action has been performed."""
        self.code = self._curl_handle.getinfo(pycurl.HTTP_CODE)
        self._build_headers()
        self._data.seek(0, 0)

    def _build_headers(self):
        """Parse the headers into RFC822 format"""
        url = self._curl_handle.getinfo(pycurl.EFFECTIVE_URL)

        # Content-type should be parsed here
        # We need specific http headers like Content-type
        # so for now, we must assert that content is correct
        assert url.startswith('http:') or url.startswith('https:')
        self._header.seek(0, 0)
        self._header.readline()
        m = mimetools.Message(self._header)

        # jam 20060706 More headers are available if we decide to use them
        # get the contents as of 
        # revid: john@arbash-meinel.com-20060617155251-c445c9574fcdf6aa
        # to see the other options
        m['effective-url'] = url
        m['http-code'] = str(self._curl_handle.getinfo(pycurl.HTTP_CODE))
        self.headers = m


class PyCurlTransport(HttpTransportBase):
    """http client transport using pycurl

    PyCurl is a Python binding to the C "curl" multiprotocol client.

    This transport can be significantly faster than the builtin Python client. 
    Advantages include: DNS caching, connection keepalive, and ability to 
    set headers to allow caching.
    """

    def __init__(self, base):
        super(PyCurlTransport, self).__init__(base)
        mutter('using pycurl %s' % pycurl.version)
        self._base_curl = pycurl.Curl()
        self._range_curl = pycurl.Curl()

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def has(self, relpath):
        curl = pycurl.Curl()
        abspath = self._real_abspath(relpath)
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.FOLLOWLOCATION, 1) # follow redirect responses
        self._set_curl_options(curl)
        # don't want the body - ie just do a HEAD request
        curl.setopt(pycurl.NOBODY, 1)
        self._curl_perform(curl)
        code = curl.getinfo(pycurl.HTTP_CODE)
        if code == 404: # not found
            return False
        elif code in (200, 302): # "ok", "found"
            return True
        elif code == 0:
            self._raise_curl_connection_error(curl)
        else:
            self._raise_curl_http_error(curl)
        
    def _get(self, relpath, ranges, tail_amount=0):
        # Documentation says 'Pass in NULL to disable the use of ranges'
        # None is the closest we have, but at least with pycurl 7.13.1
        # It raises an 'invalid arguments' response
        #curl.setopt(pycurl.RANGE, None)
        # So instead we hack around this by using a separate object for
        # range requests
        curl = self._base_curl
        if ranges is not None:
            curl = self._range_curl

        abspath = self._real_abspath(relpath)
        curl.setopt(pycurl.URL, abspath)
        self._set_curl_options(curl)
        curl.setopt(pycurl.NOBODY, 0)

        response = CurlResponse(curl)

        if ranges is not None or tail_amount:
            curl.setopt(pycurl.RANGE, self._range_header(ranges, tail_amount))
        self._curl_perform(curl)
        response.update()
        if response.code == 0:
            self._raise_curl_connection_error(curl)
        return response.code, self._handle_response(relpath, response)

    def _raise_curl_connection_error(self, curl):
        curl_errno = curl.getinfo(pycurl.OS_ERRNO)
        url = curl.getinfo(pycurl.EFFECTIVE_URL)
        raise ConnectionError('curl connection error (%s) on %s'
                              % (os.strerror(curl_errno), url))

    def _raise_curl_http_error(self, curl):
        code = curl.getinfo(pycurl.HTTP_CODE)
        url = curl.getinfo(pycurl.EFFECTIVE_URL)
        raise TransportError('http error %d probing for %s' %
                             (code, url))

    def _set_curl_options(self, curl):
        """Set options for all requests"""
        # There's no way in http/1.0 to say "must revalidate"; we don't want
        # to force it to always retrieve.  so just turn off the default Pragma
        # provided by Curl.
        headers = ['Cache-control: max-age=0',
                   'Pragma: no-cache']
        ## curl.setopt(pycurl.VERBOSE, 1)
        # TODO: maybe include a summary of the pycurl version
        ua_str = 'bzr/%s (pycurl)' % (bzrlib.__version__)
        curl.setopt(pycurl.USERAGENT, ua_str)
        curl.setopt(pycurl.HTTPHEADER, headers)
        curl.setopt(pycurl.FOLLOWLOCATION, 1) # follow redirect responses

    def _curl_perform(self, curl):
        """Perform curl operation and translate exceptions."""
        try:
            curl.perform()
        except pycurl.error, e:
            # XXX: There seem to be no symbolic constants for these values.
            if e[0] == 6:
                # couldn't resolve host
                raise NoSuchFile(curl.getinfo(pycurl.EFFECTIVE_URL), e)


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

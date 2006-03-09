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

from StringIO import StringIO

import bzrlib
from bzrlib.errors import (TransportNotPossible, NoSuchFile,
                           TransportError, ConnectionError,
                           DependencyNotPresent)
from bzrlib.trace import mutter
from bzrlib.transport import Transport
from bzrlib.transport.http import HttpTransportBase, extract_auth, HttpServer

try:
    import pycurl
except ImportError, e:
    mutter("failed to import pycurl: %s", e)
    raise DependencyNotPresent('pycurl', e)


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

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def _real_abspath(self, relpath):
        """Produce absolute path, adjusting protocol if needed"""
        abspath = self.abspath(relpath)
        if abspath.startswith('http+pycurl'):
            abspath = 'http' + abspath[11:]
        elif abspath.startswith('https+pycurl'):
            abspath = 'https' + abspath[12:]
        if isinstance(abspath, unicode):
            abspath = abspath.encode('ascii', 'strict')
        return abspath

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
        else:
            raise TransportError('http error %d probing for %s' %
                    (code, curl.getinfo(pycurl.EFFECTIVE_URL)))
        
    def get(self, relpath):
        curl = pycurl.Curl()
        abspath = self._real_abspath(relpath)
        sio = StringIO()
        curl.setopt(pycurl.URL, abspath)
        self._set_curl_options(curl)
        curl.setopt(pycurl.WRITEFUNCTION, sio.write)
        curl.setopt(pycurl.NOBODY, 0)
        self._curl_perform(curl)
        code = curl.getinfo(pycurl.HTTP_CODE)
        if code == 404:
            raise NoSuchFile(abspath)
        elif code == 200:
            sio.seek(0)
            return sio
        else:
            raise TransportError('http error %d acccessing %s' % 
                    (code, curl.getinfo(pycurl.EFFECTIVE_URL)))

    def _set_curl_options(self, curl):
        """Set options for all requests"""
        # There's no way in http/1.0 to say "must revalidate"; we don't want
        # to force it to always retrieve.  so just turn off the default Pragma
        # provided by Curl.
        headers = ['Cache-control: must-revalidate',
                   'Pragma:']
        ## curl.setopt(pycurl.VERBOSE, 1)
        # TODO: maybe show a summary of the pycurl version
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

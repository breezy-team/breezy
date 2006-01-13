# Copyright (C) 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""http/https transport using pycurl"""

# TODO: test reporting of http errors

from StringIO import StringIO
import pycurl

from bzrlib.trace import mutter
from bzrlib.errors import (TransportNotPossible, NoSuchFile, 
                           TransportError, ConnectionError)
from bzrlib.transport import Transport
from bzrlib.transport.http import HttpTransportBase

class PyCurlTransport(HttpTransportBase):
    """http client transport using pycurl

    PyCurl is a Python binding to the C "curl" multiprotocol client.

    This transport can be significantly faster than the builtin Python client. 
    Advantages include: DNS caching, connection keepalive, and ability to 
    set headers to allow caching.
    """

    def __init__(self, base):
        super(PyCurlTransport, self).__init__(base)
        mutter('imported pycurl %s' % pycurl.version)

    def has(self, relpath):
        self.curl = pycurl.Curl()

        abspath = self.abspath(relpath)
        if isinstance(abspath, unicode):
            # probably should raise an error instead; transport paths should
            # always simply be ascii.
            abspath = abspath.encode('ascii')

        self.curl.setopt(pycurl.URL, abspath)
        self._set_curl_cache_headers()
        # don't want the body - ie just do a HEAD request
        self.curl.setopt(pycurl.NOBODY, 1)

        self._curl_perform()

        try:
            code = self.curl.getinfo(pycurl.HTTP_CODE)
            if code == 404: # not found
                return False
            elif code in (200, 302): # "ok", "found"
                return True
            else:
                raise TransportError('http error %d probing for %s' %
                        (code, self.curl.getinfo(pycurl.EFFECTIVE_URL)))
        finally:
            del self.curl
        
    def get(self, relpath):
        self.curl = pycurl.Curl()
        abspath = self.abspath(relpath)
        sio = StringIO()
        # pycurl needs plain ascii
        if isinstance(abspath, unicode):
            # XXX: HttpTransportBase.abspath should probably url-escape
            # unicode characters if any in the path - domain name must be
            # IDNA-escaped
            abspath = abspath.encode('ascii')
        self.curl.setopt(pycurl.URL, abspath)
        ## self.curl.setopt(pycurl.VERBOSE, 1)
        self._set_curl_cache_headers()
        self.curl.setopt(pycurl.WRITEFUNCTION, sio.write)
        self.curl.setopt(pycurl.NOBODY, 0)

        self._curl_perform()

        code = self.curl.getinfo(pycurl.HTTP_CODE)
        if code == 404:
            raise NoSuchFile(abspath)
        elif not 200 <= code <= 399:
            raise TransportError('http error %d acccessing %s' % 
                    (code, self.curl.getinfo(pycurl.EFFECTIVE_URL)))
        sio.seek(0)
        del self.curl
        return sio

    def _set_curl_cache_headers(self):
        headers = ['Cache-control: must-revalidate',
                   'Pragma:']
        self.curl.setopt(pycurl.HTTPHEADER, headers)

    def _curl_perform(self):
        """Perform curl operation and translate exceptions."""
        try:
            self.curl.perform()
        except pycurl.error, e:
            # XXX: There seem to be no symbolic constants for these values.
            if e[0] == 6:
                # couldn't resolve host
                raise NoSuchFile(self.curl.getinfo(pycurl.EFFECTIVE_URL), e)



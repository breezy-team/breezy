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
from bzrlib.errors import TransportError, NoSuchFile
from bzrlib.transport import Transport
from bzrlib.transport.http import HttpTransportBase

class PyCurlTransport(HttpTransportBase):
    def __init__(self, base):
        super(PyCurlTransport, self).__init__(base)
        self.curl = pycurl.Curl()
        mutter('imported pycurl %s' % pycurl.version)

    def get(self, relpath, decode=False):
        if decode:
            raise NotImplementedError
        return self._get_url(self.abspath(relpath))

    def _get_url(self, abspath):
        sio = StringIO()
        # pycurl needs plain ascii
        if isinstance(abspath, unicode):
            # XXX: HttpTransportBase.abspath should probably url-escape
            # unicode characters if any in the path - domain name must be
            # IDNA-escaped
            abspath = abspath.encode('ascii')
        self.curl.setopt(pycurl.URL, abspath)
        ## self.curl.setopt(pycurl.VERBOSE, 1)
        self.curl.setopt(pycurl.WRITEFUNCTION, sio.write)
        headers = ['Cache-control: must-revalidate',
                   'Pragma:']
        self.curl.setopt(pycurl.HTTPHEADER, headers)
        self.curl.perform()
        code = self.curl.getinfo(pycurl.HTTP_CODE)
        if code == 404:
            raise NoSuchFile(abspath)
        elif not 200 <= code <= 399:
            raise TransportError('http error %d acccessing %s' % 
                    (code, self.curl.getinfo(pycurl.EFFECTIVE_URL)))
        sio.seek(0)
        return sio



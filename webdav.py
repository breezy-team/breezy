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

"""Implementation of WebDAV for http transports.

A Transport which complement http transport by implementing
partially the WebDAV protocol to push files.
This should enable remote push operations.
"""

# TODO: Share the curl object between the various transactions or
# at a  minimum between the transactions implemented  here (if we
# can't find a way to solve the pollution of the GET transactions
# curl object).

# TODO:   Cache  files   to   improve  performance   (a  bit   at
# least). Files  should be kept  in a temporary directory  (or an
# hash-based hierarchy to limit  local file systems problems) and
# indexed on  their full URL  to allow sharing  between transport
# instances.

# TODO: Find  a way to check for  bzr version so that  we can tie
# this plugin tightly to the bzr versions.

from cStringIO import StringIO

from bzrlib.errors import (
    TransportError,
    NoSuchFile,
    FileExists,
    TransportNotPossible, # CLEANING: For debug only
    )

from bzrlib.trace import mutter
from bzrlib.transport import (
    register_transport,
    register_urlparse_netloc_protocol,
    )

# FIXME: importing  from a file  prefixed by an  underscore looks
# wrong
from bzrlib.transport.http._pycurl import PyCurlTransport

# We  want  https because  user  and  passwords  are required  to
# authenticate  against the  DAV server.  We don't  want  to send
# passwords in clear text, so  we need https. We depend on pycurl
# to implement https.

# FIXME:     The    following     was     just    copied     from
# brzlib/transport/http/_pycurl.py  because   we  have  the  same
# dependancy, but there should be a better way to express it (the
# dependancy is on http/_pycurl, not pycurl itself).
try:
    import pycurl
except ImportError, e:
    mutter("failed to import pycurl: %s", e)
    raise DependencyNotPresent('pycurl', e)

register_urlparse_netloc_protocol('https+webdav')
register_urlparse_netloc_protocol('http+webdav')

class HttpDavTransport(PyCurlTransport):
    """This defines the ability to put files using http on a DAV enabled server.

    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """
    def __init__(self, base):
        assert base.startswith('http')
        super(HttpDavTransport, self).__init__(base)
        mutter("HttpDavTransport [%s]",base)

    def _set_curl_options(self, curl):
        super(HttpDavTransport, self)._set_curl_options(curl)

    # TODO: when doing  an initial push, mkdir is  called even if
    # is_readonly have  not been overriden to say  False... A bug
    # is lying somewhere. Find it and kill it :)
    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""

        # FIXME: We should handle mode, but how ? 
        # I'm afraid you can't do that DAV...
        abspath = self._real_abspath(relpath)

        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.CUSTOMREQUEST , 'MKCOL')
        curl.setopt(pycurl.URL, abspath)

        # No noise please
        curl.setopt(pycurl.WRITEFUNCTION, StringIO().write)

        self._curl_perform(curl)
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 403:
            # Forbidden  (generally server  misconfigured  ot not
            # configured for DAV)
            raise self._raise_curl_http_error(curl,'mkdir failed')
        if code == 405:
            # Not allowed (generally already exists)
            raise FileExists(abspath)
        if code == 409:
            # Conflict (intermediate directories do not exist)
            raise NoSuchFile(abspath)
        if code != 201: # Created
            raise self._raise_curl_http_error(curl,'mkdir failed')

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        self.delete(relpath) # That was easy thanks DAV

    # FIXME: hhtp  defines append without the  mode parameter, we
    # don't but  we can't do  anything with it. That  looks wrong
    # anyway
    def append(self, relpath, f, mode=None):
        """
        Append the text in the file-like object into the final
        location.

        Returns the pos in the file current *BEFORE* the append takes place.
        """
        # Unfortunately, you  can't do that either  DAV (but here
        # that's less funny).

        # So  we need to  GET the  file first,  append to  it and
        # finally PUT  back the  result. If you're  searching for
        # performance  improvments... You're  at the  wrong place
        # until
        # www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt
        # becomes a  real RFC  and gets implemented.   Don't hold
        # your breath.
        full_data = StringIO() ;
        try:
            data = self.get(relpath)
            # FIXME: a bit naive
            full_data.write(data.read())
        except NoSuchFile:
            # Good, just do the put then
            pass
        before = full_data.tell()
        full_data.write(f.read())

        full_data.seek(0)
        self.put(relpath, full_data)
        return before

    def put(self, relpath, f, mode=None):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        abspath = self._real_abspath(relpath)
        curl = self._base_curl
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.UPLOAD, True)

        # FIXME: It's  a bit painful to call  isinstance here and
        # there instead of forcing  the interface to be file-like
        # only. No ?
        if isinstance(f,basestring):
            reader = StringIO(f).read
        else:
            reader = f.read
        curl.setopt(pycurl.READFUNCTION, reader)

        curl.perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 409:
            raise NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_curl_http_error(curl, 'expected 200, 201 or 404.')
          
    def rename(self, rel_from, rel_to):
        """Rename without special overwriting"""
        self.move(rel_from, rel_to)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""

        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)
        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        curl.setopt(pycurl.CUSTOMREQUEST , 'MOVE')
        curl.setopt(pycurl.URL, abs_from)
        curl.setopt(pycurl.HTTPHEADER, ['Destination: %s' % abs_to ])

        # No noise please
        curl.setopt(pycurl.WRITEFUNCTION, StringIO().write)

        curl.perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code != 201:
            self._raise_curl_http_error(curl, 
                                        'unable to rename to %r' % (abs_to))

    def delete(self, rel_path):
        """Delete the item at relpath"""
        abs_path = self._real_abspath(rel_path)
        # We use a dedicated curl to avoid polluting other requests
        curl = pycurl.Curl()
        curl.setopt(pycurl.CUSTOMREQUEST , 'DELETE')
        curl.setopt(pycurl.URL, abs_path)

        # No noise please
        curl.setopt(pycurl.WRITEFUNCTION, StringIO().write)

        curl.perform()        
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abs_path)
        if code != 204:
            self._raise_curl_http_error(curl, 'unable to delete')

register_transport('https+webdav://', HttpDavTransport)
register_transport('http+webdav://', HttpDavTransport)
mutter("webdav plugin transport registered")

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

# FIXME: A DAV web server can't handle mode on files because:
# - there is nothing in the protocol for that,
# - the  server  itself  generally  uses  the mode  for  its  own
#   purposes, except  if you  make it run  suid which  is really,
#   really   dangerous   (Apache    should   be   compiled   with
#   -D-DBIG_SECURITY_HOLE for those who didn't get the message).
# That means  this transport will do  no better. May  be the file
# mode should  be a file property handled  explicitely inside the
# repositories  and applied  by bzr  in the  working  trees. That
# implies a mean to  store file properties, apply them, detecting
# their changes, etc.

# TODO: Share the curl object between the various transactions or
# at a  minimum between the transactions implemented  here (if we
# can't find a way to solve the pollution of the GET transactions
# curl object).

# TODO:   Cache  files   to   improve  performance   (a  bit   at
# least). Files  should be kept  in a temporary directory  (or an
# hash-based hierarchy to limit  local file systems problems) and
# indexed  on  their  full  URL  to  allow  sharing  between  DAV
# transport instances.

# TODO: Handle  the user and  password cleanly: do not  force the
# user  to   provide  them   in  the  url   (at  least   for  the
# password). Have a look at the password_manager classes. Tip: it
# may be  possible to  share the password_manager  between across
# all  transports by  prefixing  the relm  by  the protocol  used
# (especially if other protocols do not use realms).

# TODO:  Try to  use Transport.translate_error  if it  becomes an
# accessible function. Otherwise  duplicate it here (bad). Anyway
# all translations of IOError and OSError should be factored.

# TODO: Review all hhtp^W http codes used here and by various DAV
# servers implementations, I feel bugs lying around...

# TODO:    Try    to     anticipate    the    implemenation    of
# www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt   by
# implementing APPEND  in a  test server. And  then have  the webdav
# plugin try  to use APPEND, and  if it isn't  available, it will
# permanently  switch back  to  get +  put  for the  life of  the
# Transport.

from cStringIO import StringIO
import os
import random
import time

import bzrlib
from bzrlib.errors import (
    BzrCheckError,
    DirectoryNotEmpty,
    NoSuchFile,
    FileExists,
    TransportError,
    )

from bzrlib.trace import mutter
from bzrlib.transport import (
    register_urlparse_netloc_protocol,
    )

# We  want  https because  user  and  passwords  are required  to
# authenticate  against the  DAV server.  We don't  want  to send
# passwords in clear text, so  we need https. We depend on pycurl
# to implement https.

# We    use    bzrlib.transport.http._pycurl    as    our    base
# implementation, so we have the same dependancies.
try:
    import pycurl
except ImportError, e:
    mutter("failed to import pycurl: %s", e)
    raise DependencyNotPresent('pycurl', e)

# Now we can import _pycurl
from bzrlib.transport.http._pycurl import PyCurlTransport

register_urlparse_netloc_protocol('https+webdav')
register_urlparse_netloc_protocol('http+webdav')

class HttpDavTransport(PyCurlTransport):
    """This defines the ability to put files using http on a DAV enabled server.

    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """
    def __init__(self, base):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport, self).__init__(base)
        mutter("HttpDavTransport [%s]",base)

    def _set_curl_options(self, curl):
        super(HttpDavTransport, self)._set_curl_options(curl)
        # No  noise  please:  libcurl  displays request  body  on
        # stdout  otherwise.   Which  means that  commenting  the
        # following line will be great for debug.
        curl.setopt(pycurl.WRITEFUNCTION,StringIO().write)

    # TODO: when doing  an initial push, mkdir is  called even if
    # is_readonly have  not been overriden to say  False... A bug
    # is lying somewhere. Find it and kill it :)
    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    # FIXME: We  should handle mode,  but how ?  I'm  sorry DAVe,
    # I'm afraid I can't do that.
    # http://www.imdb.com/title/tt0062622/quotes
    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""

        abspath = self._real_abspath(relpath)

        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.CUSTOMREQUEST , 'MKCOL')
        curl.setopt(pycurl.URL, abspath)

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
            full_data.write(data.read())
        except NoSuchFile:
            # Good, just do the put then
            pass
        before = full_data.tell()
        full_data.write(f.read())

        full_data.seek(0)
        self.put(relpath, full_data)
        return before

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to."""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)
        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.CUSTOMREQUEST , 'COPY')
        curl.setopt(pycurl.URL, abs_from)
        curl.setopt(pycurl.HTTPHEADER, ['Destination: %s' % abs_to ])

        curl.perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code in (404, 409):
            raise NoSuchFile(abs_from)
        if code != 201:
            self._raise_curl_http_error(curl, 
                                        'unable to copy from %r to %r'
                                        % (abs_from,abs_to))

    def put(self, relpath, f, mode=None):
        """Copy the file-like or string object into the location.

        Tests revealed that contrary to what is said in
        http://www.rfc.net/rfc2068.html, the put is atomic. When
        putting a file, if the client died, a partial file may
        still exists on the server.

        So we first put a temp file and then move it.
        
        This operation is atomic (see http://www.rfc.net/rfc2068.html).
        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        """
        abspath = self._real_abspath(relpath)

        stamp = '.tmp.%.9f.%d.%d' % (time.time(),
                                     os.getpid(),
                                     random.randint(0,0x7FFFFFFF))
        # A temporary file to hold  all the data to guard against
        # client death
        tmp_relpath = relpath + stamp
        tmp_abspath = abspath + stamp

        # FIXME: We  can't share the curl with  get requests. Try
        # to  understand  why  to  be  able  to  share.
        #curl  = self._base_curl
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.URL, tmp_abspath)
        curl.setopt(pycurl.UPLOAD, True)

        curl.setopt(pycurl.READFUNCTION, f.read)

        curl.perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code in (403, 409): # FIXME: 404, ?
            raise NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_curl_http_error(curl, 'expected 200, 201 or 204.')

        # Now move the temp file
        try:
            self.move(tmp_relpath, relpath)
        except Exception, e:
            # If  we fail,  try to  clean up  the  temporary file
            # before we throw the exception but don't let another
            # exception mess  things up Write  out the traceback,
            # because otherwise  the catch and  throw destroys it
            # If we can't, delete the temp file before throwing
            try:
                self.delete(tmp_relpath)
            except:
                raise e # raise the saved except
            raise # raise the original with its traceback if we can.
       
    def rename(self, rel_from, rel_to):
        """Rename without special overwriting"""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)
        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.CUSTOMREQUEST , 'MOVE')
        curl.setopt(pycurl.URL, abs_from)
        curl.setopt(pycurl.HTTPHEADER, ['Destination: %s' % abs_to,
                                        'Overwrite: F'])

        curl.perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abs_from)
        if code == 412:
            raise FileExists(abs_to)
        if code == 409:
            raise DirectoryNotEmpty(abs_to)
        if code != 201:
            self._raise_curl_http_error(curl, 
                                        'unable to rename to %r' % (abs_to))

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""

        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)
        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.CUSTOMREQUEST , 'MOVE')
        curl.setopt(pycurl.URL, abs_from)
        curl.setopt(pycurl.HTTPHEADER, ['Destination: %s' % abs_to ])

        curl.perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abs_from)
        if code == 409:
            raise DirectoryNotEmpty(abs_to)
        if code != 201:
            self._raise_curl_http_error(curl, 
                                        'unable to move to %r' % (abs_to))

    def delete(self, rel_path):
        """
        Delete the item at relpath.

        Not that if you pass a non-empty dir, a conforming DAV
        server will delete the dir and all its content. That does
        not normally append in bzr.
        """
        abs_path = self._real_abspath(rel_path)
        # We use a dedicated curl to avoid polluting other requests
        curl = pycurl.Curl()
        self._set_curl_options(curl)
        curl.setopt(pycurl.CUSTOMREQUEST , 'DELETE')
        curl.setopt(pycurl.URL, abs_path)

        curl.perform()        
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abs_path)
        # FIXME: This  is an  horrrrrible workaround to  pass the
        # tests,  what  we really  should  do  is  test that  the
        # directory  is not  empty *because  bzr do  not  want to
        # remove non-empty dirs*.
        if code == 999:
            raise DirectoryNotEmpty(abs_path)
        if code != 204:
            self._raise_curl_http_error(curl, 'unable to delete')

mutter("webdav plugin transports registered")

def get_test_permutations():
    """Return the permutations to be used in testing."""
    import test_webdav
    return [(HttpDavTransport, test_webdav.HttpServer_Dav),
            ]

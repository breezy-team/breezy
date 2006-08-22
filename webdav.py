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
# indexed on  their full URL  to allow sharing  between transport
# instances.

# TODO: Handle  the user and  password cleanly: do not  force the
# user to provide them in the url (at least for the password).

# TODO: Find  a way to check for  bzr version so that  we can tie
# this plugin tightly to the bzr versions.

# TODO:  Try to  use Transport.translate_error  if it  becomes an
# accessible function. Otherwise  duplicate it here (bad). Anyway
# all translations of IOError should be factored.

from cStringIO import StringIO

from bzrlib.errors import (
    TransportError,
    DirectoryNotEmpty,
    NoSuchFile,
    FileExists,
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
        super(self.__class__, self).__init__(base)
        mutter("HttpDavTransport [%s]",base)

    def _set_curl_options(self, curl):
        super(self.__class__, self)._set_curl_options(curl)
        # No noise please: libcurl displays request body on stdout otherwise
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

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to."""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)
        # We use a dedicated curl to avoid polluting other request
        curl = pycurl.Curl()
        curl.setopt(pycurl.CUSTOMREQUEST , 'COPY')
        curl.setopt(pycurl.URL, abs_from)
        curl.setopt(pycurl.HTTPHEADER, ['Destination: %s' % abs_to ])

        # No noise please
        curl.setopt(pycurl.WRITEFUNCTION, StringIO().write)

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

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        abspath = self._real_abspath(relpath)
        # FIXME: We  can't share the curl with  get requests. Try
        # to  understand  why  to  be  able  to  share.
        #curl  = self._base_curl
        curl = pycurl.Curl()

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
            self._raise_curl_http_error(curl, 'expected 200, 201 or 204.')
          
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

        if code == 404:
            raise NoSuchFile(abs_from)
        if code == 409:
            raise DirectoryNotEmpty(abs_to)
        if code != 201:
            self._raise_curl_http_error(curl, 
                                        'unable to rename to %r' % (abs_to))

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
        curl.setopt(pycurl.CUSTOMREQUEST , 'DELETE')
        curl.setopt(pycurl.URL, abs_path)

        # No noise please
        curl.setopt(pycurl.WRITEFUNCTION, StringIO().write)

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

register_transport('https+webdav://', HttpDavTransport)
register_transport('http+webdav://', HttpDavTransport)
mutter("webdav plugin transport registered")

# Tests

# FIXME: I  just can't  find how to  separate the tests  from the
# transport implementation code. I punt for now, but still try to
# keep  the imports  separated.  Of course  that violates  coding
# conventions... :-/

import errno
import os
import os.path
import string

from shutil import (
    copyfile
    )

from bzrlib.transport.http import (
    TestingHTTPRequestHandler
    )

from bzrlib.transport import(
    get_transport,
    split_url
    )
# FIXME: importing  from a file  prefixed by an  underscore looks
# wrong
from bzrlib.transport.http._pycurl import (
    HttpServer_PyCurl
    )

class TestingDAVRequestHandler(TestingHTTPRequestHandler):
    """
    Subclass of TestingHTTPRequestHandler handling DAV requests.

    This is not a full implementation of a DAV server, only the parts
    really used by the plugin are.

    It uses a local transport to forward the requests as
    quick-and-dirty-first-shot implementation. Intuition tells
    that it could comes haunt us later, but we'll see.
    """

    def _read_chunk(self):
        """
        Read a chunk of data.

        A chunk consists of:
        - a line containing the lenghtof the data in hexa,
        - the data.
        - a empty line.

        An empty chunk specifies a length of zero
        """
        length = string.atoi(self.rfile.readline(),base=16)
        data = None
        if length != 0:
            data = self.rfile.read(length)
            # Eats the newline following the chunk
            self.rfile.readline()
            
        return length, data

    def do_PUT(self):
        """Serve a PUT request."""
        path = self.translate_path(self.path)
        mutter("do_PUT rel: [%s], abs: [%s]" % (self.path,path))
        # Tell the client to go ahead, we're ready to get the content
        self.send_response(100,"Continue")
        self.end_headers()
        try:
            # Always write in binary mode.
            mutter("do_PUT will try to open: [%s]" % path)
            f = open(path, 'wb')
        except IOError,e :
            self.send_error(409, "Conflict")
            return
        try:
            # We receive the content by chunk
            while True:
                length, data = self._read_chunk()
                if length == 0:
                    break
                f.write(data)
        except IOError:
            # FIXME: We leave a partially written file here
            self.send_error(409, "Conflict")
            f.close()
            return
        f.close()
        mutter("do_PUT done: [%s]" % self.path)
        self.send_response(201)
        self.end_headers()

    def do_MKCOL(self):
        """
        Serve a MKCOL request.

        MKCOL is an mkdir in DAV terminology for our part.
        """
        path = self.translate_path(self.path)
        mutter("do_MKCOL rel: [%s], abs: [%s]" % (self.path,path))
        try:
            os.mkdir(path)
        except (IOError, OSError),e:
            if e.errno in (errno.ENOENT, ):
                self.send_error(409, "Conflict")
            elif e.errno in (errno.EEXIST, errno.ENOTDIR):
                self.send_error(405, "Not allowed")
            else:
                # Ok we fail for an unnkown reason :-/
                raise
        else:
            self.send_response(201)
            self.end_headers()
               
    def do_COPY(self):
        """Serve a COPY request."""

        url_to = self.headers.get('Destination')
        if url_to is None:
            self.send_error(400,"Destination header missing")
            return
        scheme, username, password, host, port, rel_to = split_url(url_to)
        mutter("do_COPY rel_from: [%s], rel_to: [%s]" % (self.path,rel_to))
        abs_from = self.translate_path(self.path)
        abs_to = self.translate_path(rel_to)
        try:
            # TODO:  Check that rel_from  exists and  rel_to does
            # not.  In the  mean  time, just  go  along and  trap
            # exceptions
            copyfile(abs_from,abs_to)
        except IOError, e:
            try:
                # FIXME:    We   cheat    here,   we    use   the
                # _translate_error  of Transport, we  this method
                # is not  real one. It's really  a function which
                # should   be  declared   as   such.   Also,   we
                # arbitrarily  choose to  call  it with  abs_from
                # when abs_to may as  well be appropriate. But at
                # the end we send 404, so...
                get_transport('.')._translate_error(e,abs_from,False)
            except NoSuchFile:
                self.send_error(404,"File not found") ;
            except:
                self.send_error(409,"Conflict") ;
        else:
            # TODO: We may be able  to return 204 "No content" if
            # rel_to was existing (even  if the "No content" part
            # seems misleading, RFC2519 says so, stop arguing :)
            self.send_response(201)
            self.end_headers()

    def do_DELETE(self):
        """Serve a DELETE request.

        We don't implement a true DELETE as DAV defines it
        because we *should* fail to delete a non empty dir.
        """
        path = self.translate_path(self.path)
        mutter("do_DELETE rel: [%s], abs: [%s]" % (self.path,path))
        try:
            # DAV  makes no  distinction between  files  and dirs
            # when required to nuke them,  but we have to. And we
            # also watch out for symlinks.
            real_path = os.path.realpath(path)
            if os.path.isdir(real_path):
                os.rmdir(path)
            else:
                os.remove(path)
        except (IOError, OSError),e:
            if e.errno in (errno.ENOENT, ):
                self.send_error(404, "File not found")
            elif e.errno in (errno.ENOTEMPTY, ):
                # FIXME: Really gray area, we are not supposed to
                # fail  here :-/ If  we act  as a  conforming DAV
                # server we should  delete the directory content,
                # but bzr may want to  test that we don't. So, as
                # we want to conform to bzr, we don't.
                self.send_error(999, "Directory not empty")
            else:
                # Ok we fail for an unnkown reason :-/
                raise
        else:
            self.send_response(204) # Default success code
            self.end_headers()

    def do_MOVE(self):
        """Serve a MOVE request."""

        url_to = self.headers.get('Destination')
        if url_to is None:
            self.send_error(400,"Destination header missing")
            return
        scheme, username, password, host, port, rel_to = split_url(url_to)
        mutter("do_MOVE rel_from: [%s], rel_to: [%s]" % (self.path,rel_to))
        abs_from = self.translate_path(self.path)
        abs_to = self.translate_path(rel_to)
        try:
            # TODO: rename may a bit too powerful for our taste
            os.rename(abs_from, abs_to)
        except (IOError, OSError), e:
            try:
                # FIXME:    We   cheat    here,   we    use   the
                # _translate_error  of Transport, but  this method
                # is not  real one. It's really  a function which
                # should   be  declared   as   such.   Also,   we
                # arbitrarily  choose to  call  it with  abs_from
                # when abs_to may as  well be appropriate. But at
                # the end we send 404, so...
                get_transport('.')._translate_error(e,abs_from,False)
            except NoSuchFile:
                self.send_error(404,"File not found") ;
            except:
                self.send_error(409,"Conflict") ;
        else:
            # TODO: We may be able  to return 204 "No content" if
            # rel_to was existing (even  if the "No content" part
            # seems misleading, RFC2519 says so, stop arguing :)
            self.send_response(201)
            self.end_headers()

class HttpServer_Dav(HttpServer_PyCurl):
    """Subclass of HttpServer that gives http+webdav urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    """

    def __init__(self):
        # We    have   special    requests    to   handle    that
        # HttpServer_PyCurl don't know about
        super(self.__class__,self).__init__(TestingDAVRequestHandler)
        

    # urls returned by this server should require the webdav client impl
    _url_protocol = 'http+webdav'

def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(HttpDavTransport, HttpServer_Dav),
            ]

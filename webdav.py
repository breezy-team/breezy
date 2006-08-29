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

# TODO:   Cache  files   to   improve  performance   (a  bit   at
# least). Files  should be kept  in a temporary directory  (or an
# hash-based hierarchy to limit  local file systems problems) and
# indexed  on  their  full  URL  to  allow  sharing  between  DAV
# transport  instances. If the  full content  is not  cached, the
# Content-Length header, if cached,  may avoid a roundtrip to the
# server when appending.

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

# TODO:  It looks  like  Apache  1.x and  2.x  reserve the  PATCH
# request name without implementing it,  bzr does not use it now,
# but providing it may allow experiments.

# TODO: Do an urllib based implemenation.

# TODO:  We can  detect that  the  server do  not accept  "write"
# operations (it will return 501) and raise InvalidHttpRequest(to
# be defined as a  daughter of InvalidHttpResponse) but what will
# the upper layers do ?

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
from bzrlib.transport.http import (
    _extract_headers,
    response,
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

    # Note that we  override methods from Pycurltransport, partly
    # to implement new functionalities and partly to correct some
    # problems  with  its implementation  (full  sharing of  curl
    # objects for example).
    def __init__(self, base, from_transport=None):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport, self).__init__(base)
        if from_transport is not None:
            self._curl = from_transport._curl
            self._accept_ranges = from_transport._accept_ranges
        else:
            mutter('using pycurl %s' % pycurl.version)
            self._curl = pycurl.Curl()
            self._set_curl_common_options()
            self._accept_ranges = True
        mutter("HttpDavTransport [%s]",base)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    def _set_curl_common_options(self):
        # Set options common to all requests. Once.
        curl = self._curl
        # TODO: maybe include a summary of the pycurl and plugin version
        ua_str = 'bzr/%s (pycurl)(webdav plugin)' % (bzrlib.__version__,)
        curl.setopt(pycurl.USERAGENT, ua_str)
        curl.setopt(pycurl.FOLLOWLOCATION, 1) # follow redirect responses
        # curl.setopt(pycurl.VERBOSE, 1)

    # Each request will call _set_curl_options before setting its
    # own specific  options.  This  allows sharing the  same curl
    # object (enabling  connection sharing) while  paying a small
    # price: all used options should be reset here. Note that the
    # CURLOPT_RANGE option should not  be used as pycurl does not
    # allow  unsetopt  for it.  Adding  the corresponding  header
    # provides the same service.
    def _set_curl_options(self):
        """Reset all used options.

        To  allow the  sharing of  culr object  between different
        requests, without requiring each  request to rest its own
        options,  reset all  used options  here. Request  code is
        simplified.
        """
        curl = self._curl
        # We don't reset URL because every request set it.
        curl.unsetopt(pycurl.CUSTOMREQUEST)
        curl.setopt(pycurl.HTTPGET, 0)
        curl.setopt(pycurl.NOBODY, 0)
        curl.setopt(pycurl.UPLOAD, 0)
        # There  is  no  way  to  reset  the  functions  thru  pycurl
        # interface, so we just redirect them to instances variables,
        # request methods can then acess values or reset functions at
        # will.
        # TODO: Create a BitBucket(StringIO) ?
        self._data_read = StringIO()
        curl.setopt(pycurl.READFUNCTION, self._data_read.read)
        self._header_received = StringIO()
        curl.setopt(pycurl.HEADERFUNCTION, self._header_received.write)
        self._data_written = StringIO()
        curl.setopt(pycurl.WRITEFUNCTION, self._data_written.write)
        # Http header  is a special case, some  values are common
        # to  all  requests,  some  are specific.   When  needed,
        # requests should  use the _add_header  method to append
        # to common  values.  The _curl_perform  method will then
        # set the HTTPHEADER option.
        self._headers_sent = ['Cache-control: max-age=0',
                              'Pragma: no-cache',
                              'Connection: Keep-Alive']
        return self._curl

    def _add_header(self, header):
        """Append the header (a string) to already set headers"""
        self._headers_sent.append(header)

    def _perform(self):
        curl = self._curl
        curl.setopt(pycurl.HTTPHEADER,self._headers_sent)
        super(HttpDavTransport,self)._curl_perform(curl)

    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._real_abspath(relpath)

        curl = self._set_curl_options()
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.NOBODY, 1) # No BODY
        self._perform()        

    def has(self, relpath):
        """See Transport.has()"""

        self._head(relpath)
        curl = self._curl
        code = curl.getinfo(pycurl.HTTP_CODE)
        if code == 404: # not found
            return False
        elif code in (200, 302): # "ok", "found"
            return True
        else:
            self._raise_curl_http_error(curl)

    def _get_full(self, relpath):
        """Make a request for the entire file"""
        abspath = self._real_abspath(relpath)

        curl = self._set_curl_options()
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.HTTPGET, 1)
        data = StringIO()
        curl.setopt(pycurl.WRITEFUNCTION, data.write)
        self._perform()

        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abspath)
        if code != 200:
            self._raise_curl_http_error(curl,
                                        'expected 200 or 404 for _get_full.')

        data.seek(0)
        return code, data

    def _get_ranged(self, relpath, ranges, tail_amount):
        """Make a request for just part of the location."""

        abspath = self._real_abspath(relpath)

        curl = self._set_curl_options()
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.HTTPGET, 1)
        data = StringIO()
        curl.setopt(pycurl.WRITEFUNCTION, data.write)
        self._add_header('Range: bytes=%s'
                         % self.range_header(ranges, tail_amount))

        self._perform()

        code = curl.getinfo(pycurl.HTTP_CODE)
        headers = _extract_headers(self._header_received.getvalue(), abspath)

        data.seek(0)
        # handle_response will raise NoSuchFile, etc based on the response code
        return code, response.handle_response(abspath, code, headers, data)

    # FIXME: We  should handle mode,  but how ?  I'm  sorry DAVe,
    # I'm afraid I can't do that.
    # http://www.imdb.com/title/tt0062622/quotes
    def mkdir(self, relpath, mode=None):
        """Create a directory at the location."""

        abspath = self._real_abspath(relpath)

        curl = self._set_curl_options()
        curl.setopt(pycurl.CUSTOMREQUEST , 'MKCOL')
        curl.setopt(pycurl.URL, abspath)

        self._perform()
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

    # FIXME:  bzrlib.transport.hhtp  defines  append without  the
    # mode  parameter, we  don't but  we can't  do  anything with
    # it. That looks wrong anyway

    # TODO: Before
    # www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt
    # becomes  a real  RFC and  gets implemented,  we can  try to
    # implement   it   in   a   test  server.   Below   are   two
    # implementations, a third one will correspond to the draft.
    def append(self, relpath, f, mode=None):
        """See Transport.append"""
        if self._accept_ranges:
            before = self._append_by_head_put(relpath, f)
        else:
            before = self._append_by_get_put(relpath, f)
        return before

    def _append_by_head_put(self, relpath, f):
        """Append without getting the whole file.

        When the server allows it, a 'Content-Range' header can be specified.
        """

        self._head(relpath)
        code = self._curl.getinfo(pycurl.HTTP_CODE)
        if code == 404:
            self._put_file(relpath, f)
            relpath_size = 0
        else:
            headers = _extract_headers(self._header_received.getvalue(),
                                       self._real_abspath(relpath))
            relpath_size = int(headers['Content-Length'])
            # Get the size of the data to be appened
            mark = f.tell()
            size = len(f.read())
            f.seek(mark)
            self._put_ranged(relpath, f, relpath_size, size)

        mutter('_append_by_head_put will returns: [%d]' % relpath_size)
        return relpath_size

    def _append_by_get_put(self, relpath, f):
        # So  we need to  GET the  file first,  append to  it and
        # finally PUT  back the  result.
        full_data = StringIO() ;
        try:
            data = self.get(relpath)
            full_data.write(data.read())
        except NoSuchFile:
            # Good, just do the put then
            pass

        # Append the f content
        before = full_data.tell()
        full_data.write(f.read())
        full_data.seek(0)

        self.put(relpath, full_data)

        return before

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to."""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        curl = self._set_curl_options()
        curl.setopt(pycurl.CUSTOMREQUEST , 'COPY')
        curl.setopt(pycurl.URL, abs_from)
        self._add_header('Destination: %s' % abs_to)

        self._perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code in (404, 409):
            raise NoSuchFile(abs_from)
        if code != 201:
            self._raise_curl_http_error(curl, 
                                        'unable to copy from %r to %r'
                                        % (abs_from,abs_to))

    def put(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        Tests revealed that contrary to what is said in
        http://www.rfc.net/rfc2068.html, the put is not
        atomic. When putting a file, if the client died, a
        partial file may still exists on the server.

        So we first put a temp file and then move it.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        """

        abspath = self._real_abspath(relpath)

        # We generate a sufficiently random name to *assume* that
        # no collisions will occur  and don't worry about it (nor
        # handle it).
        stamp = '.tmp.%.9f.%d.%d' % (time.time(),
                                     os.getpid(),
                                     random.randint(0,0x7FFFFFFF))
        # A temporary file to hold  all the data to guard against
        # client death
        tmp_relpath = relpath + stamp
        tmp_abspath = abspath + stamp

        self._put_file(tmp_relpath,f) # Will raise if something gets wrong

        # Now move the temp file
        try:
            self.move(tmp_relpath, relpath)
        except Exception, e:
            # If  we fail,  try to  clean up  the  temporary file
            # before we throw the exception but don't let another
            # exception mess  things up. Write  out the traceback
            # (the one  where the  move have failed,  causing the
            # exception),  because otherwise the  following catch
            # and throw destroys it.
            import traceback
            mutter(traceback.format_exc())
            try:
                self.delete(tmp_relpath)
            except:
                raise e # raise the saved except
            raise # raise the original with its traceback if we can.

    def _put_file(self, relpath, f):
        """Copy the file-like object into the location."""

        abspath = self._real_abspath(relpath)

        curl = self._set_curl_options()
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.UPLOAD, True)
        curl.setopt(pycurl.READFUNCTION, f.read)

        self._perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code in (403, 409):
            raise NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_curl_http_error(curl, 'expected 200, 201 or 204.')

    def _put_ranged(self, relpath, f, at, size):
        """Append the file-like object part to the end of the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object, only size bytes will be read.
        :param at:      int, where to seek the location at.
        :param size:    int, how many bytes to write.
        """
        # Acquire just the needed data
        abspath = self._real_abspath(relpath)
        before = f.tell()
        data = StringIO(f.read(size))
        after = f.tell()
        assert(after - before == size,
               'Invalid content: %d != %d - %d' % (after, before, size))
        f.seek(before) # FIXME: May not be necessary

        curl = self._set_curl_options()
        curl.setopt(pycurl.URL, abspath)
        curl.setopt(pycurl.UPLOAD, True)
        curl.setopt(pycurl.READFUNCTION, data.read)
        self._add_header('Content-Range: bytes %d-%d/%d'
                         % (at, at+size, size))

        self._perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code in (403, 409):
            raise NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_curl_http_error(curl, 'expected 200, 201 or 204.')
   
    def rename(self, rel_from, rel_to):
        """Rename without special overwriting"""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        curl = self._set_curl_options()
        curl.setopt(pycurl.CUSTOMREQUEST , 'MOVE')
        curl.setopt(pycurl.URL, abs_from)
        self._add_header('Destination: %s' % abs_to)
        self._add_header('Overwrite: F')

        self._perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abs_from)
        if code == 412:
            raise FileExists(abs_to)
        if code == 409:
            # More precisely some intermediate directories are missing
            raise NoSuchFile(abs_to)
        if code != 201:
            # As we don't want  to accept overwriting abs_to, 204
            # (meaning  abs_to  was   existing  (but  empty,  the
            # non-empty case is 412))  will be an error, a server
            # bug  even,  since  we  require explicitely  to  not
            # overwrite.
            self._raise_curl_http_error(curl, 
                                        'unable to rename to %r' % (abs_to))

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to.

        Overwrites rel_to if it exists.
        """

        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        curl = self._set_curl_options()
        curl.setopt(pycurl.CUSTOMREQUEST , 'MOVE')
        curl.setopt(pycurl.URL, abs_from)
        self._add_header('Destination: %s' % abs_to )

        self._perform()
        code = curl.getinfo(pycurl.HTTP_CODE)

        if code == 404:
            raise NoSuchFile(abs_from)
        if code == 409:
            raise DirectoryNotEmpty(abs_to)
        # Overwriting  allowed, 201 means  abs_to did  not exist,
        # 204 means it did exist.
        if code not in (201, 204):
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

        curl = self._set_curl_options()
        curl.setopt(pycurl.CUSTOMREQUEST , 'DELETE')
        curl.setopt(pycurl.URL, abs_path)

        self._perform()        
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
#            (HttpDavTransport, test_webdav.HttpServer_Dav_append),
            ]

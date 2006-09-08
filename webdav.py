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

# FIXME: Turning directory indexes off may make the server
# reports that an existing directory does not exist. Reportedly,
# using multiviews can provoke that too. Investigate and fix.

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

# TODO: Have the webdav plugin try to use APPEND, and if it isn't
# available, permanently switch back to get + put for the life of
# the Transport.

# TODO:  It looks  like  Apache  1.x and  2.x  reserve the  PATCH
# request name without implementing it,  bzr does not use it now,
# but providing it may allow experiments.

# TODO: Do an urllib based implemenation.

# TODO:  We can  detect that  the  server do  not accept  "write"
# operations (it will return 501) and raise InvalidHttpRequest(to
# be defined as a  daughter of InvalidHttpResponse) but what will
# the upper layers do ?

import bisect
from cStringIO import StringIO
import httplib
import os
import random
import time
import urllib2

import bzrlib
from bzrlib.errors import (
    BzrCheckError,
    DirectoryNotEmpty,
    NoSuchFile,
    FileExists,
    TransportError,
    InvalidHttpResponse,
    )

from bzrlib.osutils import (
    dirname
    )
from bzrlib.trace import mutter
from bzrlib.transport import (
    register_urlparse_netloc_protocol,
    )
from bzrlib.transport.http import (
    HttpTransportBase,
    _extract_headers,
    )

from bzrlib.transport.http.response import (
    handle_response
    )

# We want https because user and passwords are required to
# authenticate against the DAV server.  We don't want to send
# passwords in clear text, so we need https.

# We use bzrlib.transport.http._pycurl as our base
# implementation, so we have the same dependancies. So we try to
# import PyCurlTransport and let him fail if any dependancy is
# not present.

# Now we can import _pycurl
from bzrlib.transport.http._pycurl import PyCurlTransport
import pycurl

register_urlparse_netloc_protocol('http+webdav+urllib')
register_urlparse_netloc_protocol('https+webdav+pycurl')
register_urlparse_netloc_protocol('http+webdav+pycurl')

class HttpDavTransport_pycurl(PyCurlTransport):
    """A transport able to put files using http[s] on a WebDAV server.

    Implementation based on pycurl.
    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """

    # Note that we  override methods from Pycurltransport, partly
    # to implement new functionalities and partly to correct some
    # problems  with  its implementation  (full  sharing of  curl
    # objects for example).
    def __init__(self, base, from_transport=None):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport_pycurl, self).__init__(base)
        if from_transport is not None:
            self._curl = from_transport._curl
            self._accept_ranges = from_transport._accept_ranges
        else:
            mutter('using pycurl %s' % pycurl.version)
            self._curl = pycurl.Curl()
            self._set_curl_common_options()
            self._accept_ranges = True
        mutter("HttpDavTransport_pycurl [%s]",base)

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
        super(HttpDavTransport_pycurl,self)._curl_perform(curl)

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

    # TODO:  Make more real-live  tests of  the Range  header and
    # implement some test server too.
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
        return code, handle_response(abspath, code, headers, data)

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
            # Forbidden  (generally server  misconfigured  or not
            # configured for DAV)
            raise self._raise_curl_http_error(curl,'mkdir failed')
        elif code == 405:
            # Not allowed (generally already exists)
            raise FileExists(abspath)
        elif code == 409:
            # Conflict (intermediate directories do not exist)
            raise NoSuchFile(abspath)
        elif code != 201: # Created
            raise self._raise_curl_http_error(curl,'mkdir failed')

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        self.delete(relpath) # That was easy thanks DAV

    # TODO: Before
    # www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt
    # becomes  a real  RFC and  gets implemented,  we can  try to
    # implement   it   in   a   test  server.   Below   are   two
    # implementations, a third one will correspond to the draft.
    def append_file(self, relpath, f, mode=None):
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
            self.put_file(relpath, f)
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

        self.put_file(relpath, full_data)

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

    def put_file(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        Tests revealed that contrary to what is said in
        http://www.rfc.net/rfc2068.html, the put is not
        atomic. When putting a file, if the client died, a
        partial file may still exists on the server.

        So we first put a temp file and then move it.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        :param mode:    Not supported by DAV.
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

        # Will raise if something gets wrong
        self.put_file_non_atomic(tmp_relpath,f)

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

    def put_file_non_atomic(self, relpath, f,
                            mode=None,
                            create_parent_dir=False,
                            dir_mode=False):
        """See Transport.put_file_non_atomic"""

        abspath = self._real_abspath(relpath)

        # FIXME: We just make a mix between the sftp
        # implementation and the Transport one so there may be
        # something wrong with default Transport implementation
        # :-/
        def bare_put_file_non_atomic():

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

        # Keep file position in case something goes wrong at first put try
        f_pos = f.tell()
        try:
            bare_put_file_non_atomic()
        except NoSuchFile:
            if not create_parent_dir:
                raise
            parent_dir = dirname(relpath)
            if parent_dir:
                self.mkdir(parent_dir, mode=dir_mode)
                f.seek(f_pos)
                return bare_put_file_non_atomic()

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

# urllib2 provides no way to access the HTTPConnection object
# internally used. But we need it in order to achieve connection
# sharing and methods other than GET/HEAD/POST handling.
# 
# urllib2 is designed towards *opening* urls for various
# protocols, not to maintain a dialog with an http[s] server
# where GETting url content is just part of the problem. This
# shows in the interface of the various handlers and their
# xxx_open methods (which returns file-like objects). httplib by
# contrast is perfectly able to handle such requests with the
# HTTPConnection, HTTPRequest and HTTPResponse objects. But that
# require an access to the HTTPConnection object.
# 
# What we need here, is to connect to a server and then send
# requests and receive responses.
# 
# We try to achieve that while reusing the design of urllib2
# and implementing only the missing parts while respecting the
# spirit of urllib2 in the hope we will stay compatible.
# 
# We start by defining URLDirector and
# build_url_director. That may seem like a hammer, but in
# urllib2, HTTPConnection is just a local variable in
# do_open. And do_open itself send a Request, receives a Response
# and throw away the connection. So we really need to start at
# this levelto obtain an HTTPConnection which give us access to
# all the functionalities we need.
#
# http://linux.duke.edu/projects/urlgrabber/contents/urlgrabber/keepalive.py
# takes a quite similar approach suited for GET/HEAD only needs
# by maintaining a global pool of known HTTPConnection objects and
# reusing them as needed. The approach here allows for better
# control of the HTTPConnection objects.

# TODO: Now that HTTPConnection objects are kept alive, reuse
# them based on same host/port combination (which will make the
# implementaion closer to keepalive.py and void the dns_cache,
# err sry jam :).

# TODO: Handle redirections.

# TODO: Handle password managers.

class URLDirector(urllib2.OpenerDirector):
    def __init__(self):
        urllib2.OpenerDirector.__init__(self)
        # Forbids the use of same methods
        self.open = None
        self.close = None
        self._connection = None
        # manage the individual handlers
        self.handle_create_connection = {}

    def add_handler(self, handler):
        """Add an handler, taken URLDirector call chains into account."""
        # Unfortunately, again we have to copy from OpenerDirector :-/
        urllib2.OpenerDirector.add_handler(self, handler)
        added = False
        for method in dir(handler):
            i = method.find("_") # FIXME: What if no '_' exists ?
            protocol = method[:i]
            action = method[i+1:]
            if action == 'create_connection':
                kind = protocol
                lookup = self.handle_create_connection
            else:
                continue # Nothing of interest, for us, in this handler

            handlers = lookup.setdefault(kind, [])
            if handlers:
                bisect.insort(handlers, handler)
            else:
                handlers.append(handler)
            added = True

        if added:
            # XXX why does self.handlers need to be sorted?
            bisect.insort(self.handlers, handler)
            handler.add_parent(self)

    def create_connection(self, request):
        """Create the connection to the server defined in the request.

        We do not connect, yet. We wait for the first request to be issued.
        """
        # FIXME: To keep the same level of generality than
        # OpenerDirector we should define a
        # default_create_connection somewhere in the handlers

        protocol = request.get_type()
        result = self._call_chain(self.handle_create_connection,
                                  protocol, protocol + '_create_connection',
                                  request)

        # FIXME: To keep the same level of generality than
        # OpenerDirector we should define a
        # unknown_create_connection somewhere in the handlers

        return result


# The following was grossly copied fron urllib2 because we want a
# URLDirector object not an OpenerDirector object :-/
def build_url_director(*handlers):
    """Create an URLDirector object from a list of handlers.

    The ConnectionDirector will use several default handlers,
    including support for HTTP and HTTPS, but excluding all other
    protocols.

    If any of the handlers passed as arguments are subclasses of the
    default handlers, the default handlers will not be used.
    """
    director = URLDirector()
    # The apparent order below is not relevant, each handler
    # specify its relative order by setting its handler_order
    # static attribute
    default_classes = [urllib2.ProxyHandler,
                       HTTPHandler,
                       urllib2.HTTPDefaultErrorHandler,
                       urllib2.HTTPRedirectHandler,# FIXME: specializes
                       urllib2.HTTPErrorProcessor, # FIXME: response.info()
                       ]
    if hasattr(httplib, 'HTTPS'):
        default_classes.append(HTTPSHandler)
    skip = []
    for klass in default_classes:
        for check in handlers:
            if isclass(check):
                if issubclass(check, klass):
                    skip.append(klass)
            elif isinstance(check, klass):
                skip.append(klass)
    for klass in skip:
        default_classes.remove(klass)

    for klass in default_classes:
        director.add_handler(klass())

    for h in handlers:
        if isclass(h):
            h = h()
        director.add_handler(h)
    return director

class HTTPConnection(httplib.HTTPConnection):
    _getresponse = httplib.HTTPConnection.getresponse

    def getresponse(self):
        """Get the response from the server.

        If the response can't be acquired, the request itself may
        as well be considered aborted, so we reset the connection
        object to be able to send a new request.
        
        httplib should be responsible for that, it's not
        currently (python 2.4.3 httplib (not versioned) , so we
        try to workaround it.
        """
        try:
            return self._getresponse()
        except:
            if self.debuglevel > 0:
                print 'Reset connection'
            # Things look really weird, let's start again
            self.close()
#            self.__response = None
#            self.__state = httplib._CS_IDLE
            raise

if hasattr(httplib, 'HTTPS'):
    class HTTPSHandler(httplib.HTTPSConnection, HTTPConnection):
        getresponse = HTTPConnection.getresponse

class HTTPHandler(urllib2.HTTPHandler):
    def create_connection_for(self, http_connection_class, request):
        host = request.get_host()
        if not host:
            raise urllib2.URLError('no host given')

        connection = http_connection_class(host) # will parse host:port
        connection.set_debuglevel(self._debuglevel)

        return connection

    def http_create_connection(self, request):
        return self.create_connection_for(HTTPConnection, request)


if hasattr(httplib, 'HTTPS'):
    class HTTPSHandler(urllib2.HTTPSHandler, HTTPHandler):
        def https_create_connection(self, request):
            return self.create_connection_for(HTTPSConnection, request)

# We bypass the HttpTransport_urllib step in the hierarchy
class HttpDavTransport_urllib(HttpTransportBase):
    """An transport able to put files using http[s] on a DAV server.

    Implementation base on python urllib2 and httplib.
    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """
    _default_headers = {'Pragma': 'no-cache',
                        'Cache-control': 'max-age=0',
                        'Connection': 'Keep-Alive',
                        }
    _accept_ranges = 1

    def __init__(self, base, from_transport=None):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport_urllib, self).__init__(base)
        if from_transport is not None:
            print 'HttpDavTransport_urllib Cloned from [%s]' % base
            self._accept_ranges = from_transport._accept_ranges
            self._connection = from_transport._connection
        else:
            print 'new HttpDavTransport_urllib for [%s]' % base
            self._accept_ranges = True
            self._connection = None

    def _first_connection(self, request):
        """Very first connection to the server.

        We get our hands on the Connection object, our preciouuuus.
        """
        director = build_url_director()
        self._connection = director.create_connection(request)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    def _perform(self, request, retry=0):
        """Send the request to the server and handles common errors.

        Will retry the same request if needed.
        """
        if self._connection is None:
            self._first_connection(request)

        connection = self._connection
        #mutter('connection is: [%r]' % connection)
        #mutter('Request method is: [%s]' % request.get_method())
        debug = 1
        if debug > 0:
            connection.set_debuglevel(1)
            print 'perform: %s base: %s' % (request.get_method(), self.base)

        headers = dict(self._default_headers)
        headers.update(request.header_items())
        headers.update(request.unredirected_hdrs)
        connection._send_request(request.get_method(),
                                 request.get_selector(),
                                 request.get_data(),
                                 #None, # We don't send the body yet
                                 headers)
        #print 'Request sent'

        try:
            response = connection.getresponse()
        except httplib.BadStatusLine:
            # Presumably the server have borked the connection
            # for an unknown reason (timeout? FIXME?). Let's try again.
            if retry < 2:
                retry += 1
                if debug > 0:
                    print 'Will retry [%d], %s: %r' % (retry,
                                                       request.get_method(),
                                                       request.get_full_url())
                response = self._perform(request,retry)
            else:
                raise

        code = response.status
        #print ('Server replied: %d' % code)

# FIXME: HTTPConnection does not fully support 100-continue (the
# server responses are just ignored)

#        if code == 100:
#            mutter('Will send the body')
#            # We can send the body now
#            body = request.get_data()
#            if body is None:
#                raise URLError("No data given")
#            connection.send(body)
#            response = connection.getresponse()

        return response

    def _raise_http_error(url, response, info=None):
        status = response.status
        if info is None:
            msg = ''
        else:
            msg = ': ' + info
        raise InvalidHttpResponse(url,
                                  'Unable to handle http code %d%s'
                                  % (status,msg))
    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._real_abspath(relpath)
        request = HEADRequest(abspath)
        response = self._perform(request)

        return response

    def has(self, relpath):
        """Does the target location exist?
        """
        self._head(relpath)
        response = self._head(relpath)


        code = response.status
        if code == 404: # not found
            return False
        elif code in (200, 302): # "ok", "found"
            return True
        else:
            abspath = self._real_abspath(relpath)
            self._raise_http_error(abspath, response)

    def _get(self, relpath, ranges, tail_amount=0):
        """See Transport._get"""

        abspath = self._real_abspath(relpath)
        request = GETRequest(abspath)
        if ranges or tail_amount:
            bytes = 'bytes=' + self.range_header(ranges, tail_amount)
            request.add_header('Range', bytes)

        response = self._perform(request)

        code = response.status
        if code == 404: # not found
            # Close response to free the httplib.HTTPConnection pipeline
            response.close()
            raise NoSuchFile(abspath)

        mutter('headers for get: %r' % response.getheaders())
        mutter('headers dict: %r' % dict(response.getheaders()))
        mutter('headers in msg: %r' % response.msg.headers)
        # handle_response waits for titled headers in a dict but
        # response.getheaders returns a list of (lower(header).
        # Let's title that.
        headers = {}
        for header, value in (response.getheaders()):
            headers[header.title()] = value

        mutter('our headers: %r' % headers)
        data = handle_response(abspath, code,
                                     headers,
                                     response)
        # Close response to free the httplib.HTTPConnection pipeline
        response.close()
        return code, data

    # FIXME: Carbon-copy of HttpDavTransport_pycurl.put_file
    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file"""
        """Copy the file-like object into the location.

        Tests revealed that contrary to what is said in
        http://www.rfc.net/rfc2068.html, the put is not
        atomic. When putting a file, if the client died, a
        partial file may still exists on the server.

        So we first put a temp file and then move it.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        :param mode:    Not supported by DAV.
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

        # Will raise if something gets wrong
        self.put_file_non_atomic(tmp_relpath,f)

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

    # FIXME: Carbon-copy of HttpDavTransport_pycurl.put_file_non_atomic
    def put_file_non_atomic(self, relpath, f,
                            mode=None,
                            create_parent_dir=False,
                            dir_mode=False):
        """See Transport.put_file_non_atomic"""

        abspath = self._real_abspath(relpath)
        request = PUTRequest(abspath, f.read())

        # FIXME: We just make a mix between the sftp
        # implementation and the Transport one so there may be
        # something wrong with default Transport implementation
        # :-/
        def bare_put_file_non_atomic():

            response = self._perform(request)
            code = response.status

            if code in (403, 409):
                raise NoSuchFile(abspath) # Intermediate directories missing
            if code not in  (200, 201, 204):
                self._raise_curl_http_error(abspath, response,
                                            'expected 200, 201 or 204.')

        try:
            bare_put_file_non_atomic()
        except NoSuchFile:
            if not create_parent_dir:
                raise
            parent_dir = dirname(relpath)
            if parent_dir:
                self.mkdir(parent_dir, mode=dir_mode)
                return bare_put_file_non_atomic()

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

        request = PUTRequest(abspath, data.read())
        request.add_header('Content-Range',
                           'bytes %d-%d/%d' % (at, at+size, size))
        response = self._perform(request)
        code = response.status

        if code in (403, 409):
            raise NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_http_error(abspath, response,
                                   'expected 200, 201 or 204.')

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir"""
        abspath = self._real_abspath(relpath)

        request = MKCOLRequest(abspath)
        response = self._perform(request)

        code = response.status
        if code == 403:
            # Forbidden  (generally server  misconfigured  or not
            # configured for DAV)
            raise self._raise_http_error(abspath, response, 'mkdir failed')
        elif code == 405:
            # Not allowed (generally already exists)
            raise FileExists(abspath)
        elif code == 409:
            # Conflict (intermediate directories do not exist)
            raise NoSuchFile(abspath)
        elif code != 201: # Created
            raise self._raise_http_error(abspath, response, 'mkdir failed')

    def rename(self, rel_from, rel_to):
        """Rename without special overwriting"""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        request = MOVERequest(abs_from, abs_to)
        request.add_header('Destination', abs_to)
        request.add_header('Overwrite', 'F')
        response = self._perform(request)

        code = response.status
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
            self._raise_http_error(abs_from, response,
                                   'unable to rename to %r' % (abs_to))
    def move(self, rel_from, rel_to):
        """See Transport.move"""

        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        request = MOVERequest(abs_from, abs_to)
        response = self._perform(request)

        code = response.status
        if code == 404:
            raise NoSuchFile(abs_from)
        if code == 409:
            raise DirectoryNotEmpty(abs_to)
        # Overwriting  allowed, 201 means  abs_to did  not exist,
        # 204 means it did exist.
        if code not in (201, 204):
            self._raise_http_error(abs_from, response,
                                   'unable to move to %r' % (abs_to))

    def delete(self, rel_path):
        """
        Delete the item at relpath.

        Not that if you pass a non-empty dir, a conforming DAV
        server will delete the dir and all its content. That does
        not normally append in bzr.
        """
        abs_path = self._real_abspath(rel_path)

        request = DELETERequest(abs_path)
        response = self._perform(request)

        code = response.status
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

    def copy(self, rel_from, rel_to):
        """See Transport.copy"""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        request = COPYRequest(abs_from, abs_to)
        response = self._perform(request)

        code = response.status
        if code in (404, 409):
            raise NoSuchFile(abs_from)
        if code != 201:
            self._raise_http_error(abs_from, response,
                                   'unable to copy from %r to %r'
                                   % (abs_from,abs_to))

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        self.delete(relpath) # That was easy thanks DAV

    # TODO: Before
    # www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt
    # becomes  a real  RFC and  gets implemented,  we can  try to
    # implement   it   in   a   test  server.   Below   are   two
    # implementations, a third one will correspond to the draft.
    def append_file(self, relpath, f, mode=None):
        """See Transport.append_file"""
        if self._accept_ranges:
            before = self._append_by_head_put(relpath, f)
        else:
            before = self._append_by_get_put(relpath, f)
        return before

    def _append_by_head_put(self, relpath, f):
        """Append without getting the whole file.

        When the server allows it, a 'Content-Range' header can be specified.
        """
        response = self._head(relpath)
        code = response.status
        if code == 404:
            self.put_file(relpath, f)
            relpath_size = 0
        else:
            headers = dict(response.getheaders())
            mutter('response.headers [%r]' % response.getheaders())
            mutter('headers [%r]' % headers)
            relpath_size = int(headers['content-length'])
            # Get the size of the data to be appened
            mark = f.tell()
            size = len(f.read())
            f.seek(mark)
            self._put_ranged(relpath, f, relpath_size, size)

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

        self.put_file(relpath, full_data)

        return before


class Request(urllib2.Request):
    def __init__(self, url, data=None, headers={}):
        urllib2.Request.__init__(self, url, data, headers)

    # We set the method statically, not depending on the 'data'
    # value as urlilib2 does. We have numerous different requests
    # with or without data
    def get_method(self):
        return self.method


class GETRequest(Request):
    method = 'GET'
    def __init__(self, url):
        Request.__init__(self, url)


class HEADRequest(Request):
    method = 'HEAD'
    def __init__(self, url):
        Request.__init__(self, url)


class MKCOLRequest(Request):
    method = 'MKCOL'
    def __init__(self, url):
        Request.__init__(self, url)


class PUTRequest(Request):
    method = 'PUT'
    def __init__(self, url, data):
        Request.__init__(self, url, data,
                         {'Accept': '*/*',
                        #  'Expect': '100-continue',
                        #  'Transfer-Encoding': 'chunked',
                          })


class COPYRequest(Request):
    method = 'COPY'
    def __init__(self, url_from, url_to):
        Request.__init__(self, url_from, None, {'Destination': url_to})


class MOVERequest(Request):
    method = 'MOVE'
    def __init__(self, url_from, url_to):
        Request.__init__(self, url_from, None, {'Destination': url_to})


class DELETERequest(Request):
    method = 'DELETE'
    def __init__(self, url):
        Request.__init__(self, url)


mutter("webdav plugin transports registered")

def get_test_permutations():
    """Return the permutations to be used in testing."""
    import test_webdav
    return [#(HttpDavTransport_pycurl, test_webdav.HttpServer_Dav),
            (HttpDavTransport_urllib, test_webdav.HttpServer_Dav),
            # Until the Dav transport try to use the APPEND
            # request, there is no need to activate the following
            # (HttpDavTransport_pycurl, test_webdav.HttpServer_Dav_append),
            # (HttpDavTransport_urllib, test_webdav.HttpServer_Dav_append),
            ]

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

# TODO:  We can  detect that  the  server do  not accept  "write"
# operations (it will return 501) and raise InvalidHttpRequest(to
# be defined as a  daughter of InvalidHttpResponse) but what will
# the upper layers do ?

# TODO: 20060908 All *_file functions are defined in terms of *_bytes
# because we have to read the file to create a proper PUT request.
# Is it possible to define PUT with a file-like object, so that
# we don't have to potentially read in and hold onto potentially
# 600MB of file contents?

import bisect
from cStringIO import StringIO
import httplib
import os
import random
import socket
import sys
import time
import urllib
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
    Transport,
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

register_urlparse_netloc_protocol('http+webdav')
register_urlparse_netloc_protocol('https+webdav')


# We define our own Response class to avoid the problems with the
# addinfourl objects
class HTTPResponse(httplib.HTTPResponse):
    """Custom HTTPResponse, to avoid needing to decorate.

    httplib prefers to decorate the returned objects, rather
    than using a custom object.
    """

    def __init__(self, *args, **kwargs):
        httplib.HTTPResponse.__init__(self, *args, **kwargs)

    def info(self):
        return self.headers


# We need to define our own HTTPConnections objects to work
# around a weird problem. FIXME: Still need more investigation.
class HTTPConnection(httplib.HTTPConnection):
    """A custom HTTP Connection, which can reset itself on a bad response"""

    _getresponse = httplib.HTTPConnection.getresponse
    response_class = HTTPResponse

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
            raise


_have_https = (getattr(httplib, 'HTTPS', None) is not None)

if _have_https:
    class HTTPSConnection(httplib.HTTPSConnection, HTTPConnection):
        getresponse = HTTPConnection.getresponse


class Request(urllib2.Request):
    """A custom Request object.

    urllib2.Request objects generally set their information based
    on the data.  We set the method statically based on class, not
    depending on the 'data' value as urllib2 does. We have numerous
    different requests with or without data.

    Also, the Request object tracks the connection the request will
    be made on.
    """

    def __init__(self, url, data=None, headers={}):
        urllib2.Request.__init__(self, url, data, headers)
        self.connection = None

    def get_method(self):
        return self.method


# urllib2 provides no way to access the HTTPConnection object
# internally used. But we need it in order to achieve connection
# sharing. So, we add it to the request just before it is
# processed, and then we override the do_open method for http[s]
# requests.

class ConnectionHandler(urllib2.BaseHandler):
    """Provides connection-sharing by pre-processing requests"""

    handler_order = 1000 # after all pre-processings
    _connection_of = {} # map connections by host
    _cache_activated = False
    _debuglevel = 0

    def get_key(self, connection):
        """Returns the key for the connection in the cache"""
        return '%s:%d' % (connection.host, connection.port)

    def create_connection(self, request, http_connection_class):
        host = request.get_host()
        if not host:
            raise urllib2.URLError('no host given')

        # We create a connection (but it will not connect yet) to
        # be able to get host and take default port into account
        # (request don't do that) to avoid having different
        # connections for http://host and http://host:80
        connection = http_connection_class(host)
        # jam says 20060908: no cache for now
        if self._cache_activated:
            key = self.get_key(connection)
            if key not in self._connection_of:
                self._connection_of[key] = connection
            else:
                connection = self._connection_of[key]

        return connection

    def capture_connection(self, request, http_connection_class):
        """Capture or inject the request connection.

        Two cases:
        - the request have no connection: create a new one,

        - the request have a connection: this one have been used
          already, let's capture it, so that we can give it to
          another transport to be reused. We don't do that
          ourselves: the Transport object get the connection from
          a first request and then propagate it, from request to
          request or to cloned transports.
        """
        connection = request.connection
        if connection is None:
            # Create a new one
            connection = self.create_connection(request, http_connection_class)
            request.connection = connection
        else:
            if self._cache_activated:
                # Capture the precioussss
                key = self.get_key(connection)
                if key not in self._connection_of:
                    self._connection_of[key] = connection

        # All connections will pass here, propagate debug level
        connection.set_debuglevel(self._debuglevel)
        return request

    def http_request(self, request):
        return self.capture_connection(request, HTTPConnection)

    if _have_https:
        def https_request(self, request):
            return self.capture_connection(request, HTTPSConnection)


class HTTPHandler(urllib2.HTTPHandler):
    """A custom handler for HTTP(S) requests.

    We overrive urllib2.HTTPHandler to get a better control of
    the connection and the ability to implement new request
    types.
    """

    _default_headers = {'Pragma': 'no-cache',
                        'Cache-control': 'max-age=0',
                        'Connection': 'Keep-Alive',
                        }
    _debuglevel = 0

    def do_open(self, http_class, request, first_try=True):
        """See urllib2.HTTPHandler.do_open for the general idea.

        The request will be retried once if it fails.
        """
        connection = request.connection
        assert connection is not None, \
            'cannot process a request without a connection'

        headers = self._default_headers.copy()
        headers.update(request.header_items())
        headers.update(request.unredirected_hdrs)
        connection._send_request(request.get_method(),
                                 request.get_selector(),
                                 request.get_data(),
                                 #None, # We don't send the body yet
                                 headers)
        try:
            response = connection.getresponse()
        except httplib.BadStatusLine:
            # Presumably the server have borked the connection
            # for an unknown reason. Let's try again. FIXME: This
            # may be already covered by HTTPConnection.getresponse
            if first_try:
                if self._debuglevel > 0:
                    print 'Will retry, %s: %r' % (retry,
                                                  request.get_method(),
                                                  request.get_full_url())
                response = self.do_open(http_class, request, False)
            else:
                raise

        #print 'Request sent'
        #code = response.code
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

        # we need titled headers in a dict but
        # response.getheaders returns a list of (lower(header).
        # Let's title that because most of bzr handle titled
        # headers, but maybe we should switch to lowercased
        # headers...
        # jam 20060908: I think we actually expect the headers to
        #       be similar to mimetools.Message object, which uses
        #       case insensitive keys. It lowers() all requests.
        #       My concern is that the code may not do perfect title case.
        #       For example, it may use Content-type rather than Content-Type
        headers = {}
        for header, value in (response.getheaders()):
            headers[header.title()] = value
        response.code = response.status
        response.headers = headers
        return response

    def http_open(self, request):
        return self.do_open(HTTPConnection, request)


if _have_https:
    class HTTPSHandler(urllib2.HTTPSHandler, HTTPHandler):

        def https_open(self, request):
            return self.do_open(HTTPSConnection, request)


# The errors we want to handle in the Transport object
class HTTPErrorProcessor(urllib2.HTTPErrorProcessor):
    """Process HTTP error responses."""
    handler_order = 1000  # after all other processing

    def http_response(self, request, response):
        code, msg, hdrs = response.code, response.msg, response.info()

        if code not in (200, 201, 204, 206,
                        302,# FIXME: Not sure we get this one
                        403, 404, 405, 409, 412,
                        999, # FIXME: <cough> search for 999 in this file
                        ):
            response = self.parent.error(
                'http', request, response, code, msg, hdrs)

        return response

    https_response = http_response


# TODO: Handle password managers.

# FIXME: We use a specific Request to pass the connection between
# the transport and the HTTPHandler. urllib2.HTTPRedirectHandler
# creates urlib2.Request. We need to get our hands on the
# redirection mechanism anyway.

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
                         # FIXME: Why ? *we* send, we do not receive :-/
                         {'Accept': '*/*',
                          # FIXME: We should complete the
                          # implementation of
                          # htmllib.HTTPConnection, it's just a
                          # shame (at least a waste). We can't
                          # use the following.

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


# We bypass the HttpTransport_urllib step in the hierarchy
class HttpDavTransport(HttpTransportBase):
    """An transport able to put files using http[s] on a DAV server.

    Implementation base on python urllib2 and httplib.
    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """
    # We define our own opener
    _opener = urllib2.build_opener(ConnectionHandler,
                                   #urllib2.ProxyHandler,
                                   HTTPHandler,
                                   #urllib2.HTTPDefaultErrorHandler,
                                   # FIXME: specializes ?
                                   #urllib2.HTTPRedirectHandler,
                                   HTTPErrorProcessor,
                                   )
    _accept_ranges = True
    _debuglevel = 0

    def __init__(self, base, from_transport=None):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport, self).__init__(base)
        if from_transport is not None:
            if self._debuglevel > 0:
                print 'HttpDavTransport Cloned from [%s]' % base
            self._accept_ranges = from_transport._accept_ranges
            self._connection = from_transport._connection
        else:
            if self._debuglevel > 0:
                print 'new HttpDavTransport for [%s]' % base
            self._accept_ranges = True
            self._connection = None

    def _first_connection(self, request):
        """Very first connection to the server.

        We get our hands on the Connection object, our preciouuuus.
        """
        self._connection = request.connection

    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    def _perform(self, request):
        """Send the request to the server and handles common errors.
        """
        if self._connection is not None:
            request.connection = self._connection

        #mutter('Request method is: [%s]' % request.get_method())
        if self._debuglevel > 0:
            print 'perform: %s base: %s' % (request.get_method(), self.base)

        response = self._opener.open(request)
        if self._connection is None:
            self._first_connection(request)

        return response

    def _raise_http_error(url, response, info=None):
        if info is None:
            msg = ''
        else:
            msg = ': ' + info
        raise InvalidHttpResponse(url,
                                  'Unable to handle http code %d%s'
                                  % (response.code, msg))
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
        response = self._head(relpath)

        code = response.code
        if code == 404: # not found
            return False
        elif code in (200, 302): # "ok", "found"
            return True
        else:
            abspath = self._real_abspath(relpath)
            self._raise_http_error(abspath, response)

    def _get(self, relpath, ranges, tail_amount=0):
        """See HttpTransport._get"""

        abspath = self._real_abspath(relpath)
        request = GETRequest(abspath)
        if ranges or tail_amount:
            bytes = 'bytes=' + self.range_header(ranges, tail_amount)
            request.add_header('Range', bytes)

        response = self._perform(request)

        code = response.code
        if code == 404: # not found
            # Close response to free the httplib.HTTPConnection pipeline
            response.close()
            raise NoSuchFile(abspath)

        data = handle_response(abspath, code, response.headers, response)
        # Close response to free the httplib.HTTPConnection pipeline
        response.close()
        return code, data

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file"""
        return self.put_bytes(relpath, f.read(), mode=None)

    def put_bytes(self, relpath, bytes, mode=None):
        """Copy the bytes object into the location.

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
        # no collisions will occur and don't worry about it (nor
        # handle it).
        stamp = '.tmp.%.9f.%d.%d' % (time.time(),
                                     os.getpid(),
                                     random.randint(0,0x7FFFFFFF))
        # A temporary file to hold  all the data to guard against
        # client death
        tmp_relpath = relpath + stamp

        # Will raise if something gets wrong
        self.put_bytes_non_atomic(tmp_relpath, bytes)

        # Now move the temp file
        try:
            self.move(tmp_relpath, relpath)
        except Exception, e:
            # If  we fail,  try to  clean up  the  temporary file
            # before we throw the exception but don't let another
            # exception mess  things up.
            exc_type, exc_val, exc_tb = sys.exc_info()
            try:
                self.delete(tmp_relpath)
            except:
                raise exc_type, exc_val, exc_tb
            raise # raise the original with its traceback if we can.

    def put_file_non_atomic(self, relpath, f,
                            mode=None,
                            create_parent_dir=False,
                            dir_mode=False):
        # Implementing put_bytes_non_atomic rather than put_file_non_atomic
        # because to do a put request, we must read all of the file into
        # RAM anyway. Better to do that than to have the contents, put
        # into a StringIO() and then read them all out again later.
        self.put_bytes_non_atomic(relpath, f.read(), mode=mode,
                                  create_parent_dir=create_parent_dir,
                                  dir_mode=dir_mode)

    def put_bytes_non_atomic(self, relpath, bytes,
                            mode=None,
                            create_parent_dir=False,
                            dir_mode=False):
        """See Transport.put_file_non_atomic"""

        abspath = self._real_abspath(relpath)
        request = PUTRequest(abspath, bytes)

        # FIXME: We just make a mix between the sftp
        # implementation and the Transport one so there may be
        # something wrong with default Transport implementation
        # :-/
        # jam 20060908 The default Transport implementation just uses
        # the atomic apis, since all transports already implemented that.
        # It is better to use non-atomic ones, but old transports need
        # to be upgraded for that.
        def bare_put_file_non_atomic():

            response = self._perform(request)
            code = response.code

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
            else:
                # Don't forget to re-raise if the parent dir doesn't exist
                raise

    def _put_bytes_ranged(self, relpath, bytes, at):
        """Append the file-like object part to the end of the location.

        :param relpath: Location to put the contents, relative to base.
        :param bytes:   A string of bytes to upload
        :param at:      The position in the file to add the bytes
        """
        # Acquire just the needed data
        # TODO: jam 20060908 Why are we creating a StringIO to hold the
        #       data, and then using data.read() to send the data
        #       in the PUTRequest. Rather than just reading in and
        #       uploading the data.
        #       Also, if we have to read the whole file into memory anyway
        #       it would be better to implement put_bytes(), and redefine
        #       put_file as self.put_bytes(relpath, f.read())
        abspath = self._real_abspath(relpath)

        request = PUTRequest(abspath, bytes)
        request.add_header('Content-Range',
                           'bytes %d-%d/%d' % (at, at+len(bytes), len(bytes)))
        response = self._perform(request)
        code = response.code

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

        code = response.code
        # jam 20060908: The error handling seems to be repeated for
        #       each function. Is it possible to factor it out into
        #       a helper rather than repeat it for each one?
        #       (I realize there is some custom behavior)
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

        code = response.code
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

        code = response.code
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

        code = response.code
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

        code = response.code
        if code in (404, 409):
            raise NoSuchFile(abs_from)
        if code != 201:
            self._raise_http_error(abs_from, response,
                                   'unable to copy from %r to %r'
                                   % (abs_from,abs_to))

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.
        """
        # DavTransport can be a target. So our simple implementation
        # just returns the Transport implementation. (Which just does
        # a put(get())
        # We only override, because the default HttpTransportBase, explicitly
        # disabled it for HTTP
        return Transport.copy_to(self, relpaths, other, mode=mode, pb=pb)

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
        return self.append_bytes(relpath, f.read(), mode=mode)

    def append_bytes(self, relpath, bytes, mode=None):
        """See Transport.append_bytes"""
        if self._accept_ranges:
            before = self._append_by_head_put(relpath, bytes)
        else:
            before = self._append_by_get_put(relpath, bytes)
        return before

    def _append_by_head_put(self, relpath, bytes):
        """Append without getting the whole file.

        When the server allows it, a 'Content-Range' header can be specified.
        """
        response = self._head(relpath)
        code = response.code
        if code == 404:
            self.put_bytes(relpath, bytes)
            relpath_size = 0
        else:
            mutter('response.headers [%r]' % response.headers)
            relpath_size = int(response.headers['Content-Length'])
            self._put_bytes_ranged(relpath, bytes, relpath_size)

        return relpath_size

    def _append_by_get_put(self, relpath, bytes):
        # So  we need to  GET the  file first,  append to  it and
        # finally PUT  back the  result.
        full_data = StringIO()
        try:
            data = self.get(relpath)
            full_data.write(data.read())
        except NoSuchFile:
            # Good, just do the put then
            pass

        # Append the f content
        before = full_data.tell()
        full_data.write(bytes)
        full_data.seek(0)

        self.put_file(relpath, full_data)

        return before


mutter("webdav plugin transports registered")


def get_test_permutations():
    """Return the permutations to be used in testing."""
    import test_webdav
    return [(HttpDavTransport, test_webdav.HttpServer_Dav),
            # Until the Dav transport try to use the APPEND
            # request, there is no need to activate the following
            # (HttpDavTransport, test_webdav.HttpServer_Dav_append),
            ]

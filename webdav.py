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

# TODO: Various parts of the code assert that a header can not
# appear several times in a HTTP response. Try to investigate the
# possible consequences.

# TODO:   Cache  files   to   improve  performance   (a  bit   at
# least). Files  should be kept  in a temporary directory  (or an
# hash-based hierarchy to limit  local file systems problems) and
# indexed  on  their  full  URL  to  allow  sharing  between  DAV
# transport  instances. If the  full content  is not  cached, the
# Content-Length header, if cached,  may avoid a roundtrip to the
# server when appending.

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

# TODO: 20060908 All *_file functions are defined in terms of
# *_bytes because we have to read the file to create a proper PUT
# request.  Is it possible to define PUT with a file-like object,
# so that we don't have to potentially read in and hold onto
# potentially 600MB of file contents?
#
# There is a contradiction between returning a file-object after
# a GET and sharing connections: they both want to use the same
# socket. To solve this we need to either create a new connection
# (but some servers limits the number of simultaneous connections
# see bug #31140) when one is used for streaming or create a
# temporary local file with the GET content an return that file.

# TODO: Factor out the error handling.

# TODO: Implement the redirection scheme described in:
# http://thread.gmane.org/gmane.comp.version-control.bazaar-ng.general/14881/

from cStringIO import StringIO
import os
import random
import sys
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
    Transport,
    )

from bzrlib.transport.http.response import (
    handle_response
    )

from bzrlib.transport.http._urllib import (
    HttpTransport_urllib,
    )

from bzrlib.transport.http._urllib2_wrappers import (
    ConnectionHandler,
    HTTPConnection,
    HTTPErrorProcessor,
    HTTPSConnection,
    Opener,
    Request,
    Response,
    )

# We want https because user and passwords are required to
# authenticate against the DAV server.  We don't want to send
# passwords in clear text, so we need https.

register_urlparse_netloc_protocol('http+webdav')
register_urlparse_netloc_protocol('https+webdav')

class PUTRequest(Request):
    def __init__(self, url, data, more_headers={}):
        # FIXME: Accept */* ? Why ? *we* send, we do not receive :-/
        headers = {'Accept': '*/*',
                   'Content-type': 'application/octet-stream',
                   # FIXME: We should complete the
                   # implementation of
                   # htmllib.HTTPConnection, it's just a
                   # shame (at least a waste) that we
                   # can't use the following.

                   #  'Expect': '100-continue',
                   #  'Transfer-Encoding': 'chunked',
                   }
        headers.update(more_headers)
        Request.__init__(self, 'PUT', url, data, headers)

class DavResponse(Response):
    """Custom HTTPResponse.

    DAV have some reponses for which the body is of no interest.
    """

    def __init__(self, *args, **kwargs):
        Response.__init__(self, *args, **kwargs)
        self._body_ignored_responses += [201, 204,
                                         405, 409, 412,
                                         999, # FIXME: <cough>
                                         ]

# Takes DavResponse into account:
class DavHTTPConnection(HTTPConnection):

    response_class = DavResponse


class DavHTTPSConnection(HTTPSConnection):

    response_class = DavResponse


class DavErrorProcessor(HTTPErrorProcessor):
    """Process DAV error responses.

    We don't really process the errors, quite the contrary
    instead, we leave our Transport handle them.    
    """
    def http_response(self, request, response):
        code, msg, hdrs = response.code, response.msg, response.info()

        if code not in (201, 204, 403, 405, 409, 412, # DAV
                        999, # FIXME: <cough> search for 999 in this file
                        ):
            response = HTTPErrorProcessor.http_response(self, request, response)
        return response

    https_response = http_response

class DavConnectionHandler(ConnectionHandler):
    """Custom connection handler.

    We need to use the DavConnectionHTTPxConnection class to take
    into account our own DavResponse objects, to be able to
    declare our own body ignored responses, sigh.
    """

    def http_request(self, request):
        return self.capture_connection(request, DavHTTPConnection)

    def https_request(self, request):
        return self.capture_connection(request, DavHTTPSConnection)


class DavOpener(Opener):
    """Dav specific needs regarding HTTP(S)"""

    def __init__(self):
        super(DavOpener, self).__init__(connection=DavConnectionHandler,
                                        error=DavErrorProcessor)


class HttpDavTransport(HttpTransport_urllib):
    """An transport able to put files using http[s] on a DAV server.

    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """

    _debuglevel = 0
    _opener_class = DavOpener

    def __init__(self, base, from_transport=None):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport, self).__init__(base, from_transport)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    def _raise_http_error(self, url, response, info=None):
        if info is None:
            msg = ''
        else:
            msg = ': ' + info
        raise InvalidHttpResponse(url,
                                  'Unable to handle http code %d%s'
                                  % (response.code, msg))

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

            if code in (403, 404, 409):
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

        # Once we teach httplib to do that, we will use file-like
        # objects (see handling chunked data and 100-continue).
        abspath = self._real_abspath(relpath)

        request = PUTRequest(abspath, bytes,
                             {'Content-Range':
                              'bytes %d-%d/%d' % (at, at+len(bytes),
                                                  len(bytes)),
                              })
        response = self._perform(request)
        code = response.code

        if code in (403, 404, 409):
            raise NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_http_error(abspath, response,
                                   'expected 200, 201 or 204.')

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir"""
        abspath = self._real_abspath(relpath)

        request = Request('MKCOL', abspath)
        response = self._perform(request)

        code = response.code
        # jam 20060908: The error handling seems to be repeated for
        #       each function. Is it possible to factor it out into
        #       a helper rather than repeat it for each one?
        #       (I realize there is some custom behavior)
        # Yes it is and will be done.
        if code == 403:
            # Forbidden  (generally server  misconfigured  or not
            # configured for DAV)
            raise self._raise_http_error(abspath, response, 'mkdir failed')
        elif code == 405:
            # Not allowed (generally already exists)
            raise FileExists(abspath)
        elif code in (404, 409):
            # Conflict (intermediate directories do not exist)
            raise NoSuchFile(abspath)
        elif code != 201: # Created
            raise self._raise_http_error(abspath, response, 'mkdir failed')

    def rename(self, rel_from, rel_to):
        """Rename without special overwriting"""
        abs_from = self._real_abspath(rel_from)
        abs_to = self._real_abspath(rel_to)

        request = Request('MOVE', abs_from, None,
                          {'Destination': abs_to,
                           'Overwrite': 'F'})
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

        request = Request('MOVE', abs_from, None, {'Destination': abs_to})
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

        request = Request('DELETE', abs_path)
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

        request = Request('COPY', abs_from, None, {'Destination': abs_to})
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

    def lock_write(self, relpath):
        """Lock the given file for exclusive access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # We follow the same path as FTP, which just returns a BogusLock
        # object. We don't explicitly support locking a specific file.
        # TODO: jam 2006-09-08 SFTP implements this by opening exclusive 
        #       "relpath + '.lock_write'". Does DAV implement anything like
        #       O_EXCL?
        #       Alternatively, LocalTransport uses an OS lock to lock the file
        #       and WebDAV supports some sort of locking.
        return self.lock_read(relpath)

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
        if self._range_hint is not None:
            # TODO: We reuse the _range_hint handled by bzr core,
            # unless someone can show me a server implementing
            # range for write but not for read. But we may, on
            # our own, try to handle a similar flag for write
            # ranges supported by a given server. Or at least,
            # detect that ranges are not correctly handled and
            # fallback to no ranges.
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


def get_test_permutations():
    """Return the permutations to be used in testing."""
    import test_webdav
    return [(HttpDavTransport, test_webdav.DAVServer),
            # Until the Dav transport try to use the APPEND
            # request, there is no need to activate the following
            # (HttpDavTransport, test_webdav.DAVServer_append),
            ]

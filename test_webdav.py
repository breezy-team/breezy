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

"""Tests for the wedav plugin.

This defines the TestingDAVRequestHandler and the HttpServer_Dav
classes which implements the DAV specification parts used by the
webdav plugin.
"""

# TODO: Implement the  testing of the range header  for both GET
# and PUT requests. The server should be able to refuse the Range
# headers optionally (or two servers should be available).

# TODO: Apache ignores bad formatted Content-Range headers. So we
# don't receive a  501 response if he don't  handle them but just
# trash the  files instead. May  be a small  test can be  done in
# __init__ to recognize bogus servers:
# put(tmp,'good');append(tmp,'bad'),get(tmp).startswith('good').

import errno
import os
import os.path
import re
import socket
import string
from shutil import (
    copyfile
    )
import sys
import time

from bzrlib.errors import (
    NoSuchFile,
    )
from bzrlib.trace import mutter
from bzrlib.transport import(
    get_transport,
    split_url
    )
from bzrlib.tests.HttpServer import (
    HttpServer,
    TestingHTTPRequestHandler,
    )

class TestingDAVRequestHandler(TestingHTTPRequestHandler):
    """
    Subclass of TestingHTTPRequestHandler handling DAV requests.

    This is not a full implementation of a DAV server, only the parts
    really used by the plugin are.
    """

    _RANGE_HEADER_RE = re.compile(
        r'bytes (?P<begin>\d+)-(?P<end>\d+)/(?P<size>\d+|\*)')

    # On Mac OS X 10.3 + fink, we get EAGAIN (ressource temporary
    # unavailable)...   permanently :)  when  reading the  client
    # socket.  The  following helps,  but still, some  tests fail
    # with a "Broken  pipe".  I guess it may be  a problem in the
    # test framework, but more investigations are still neeeded.
    def _retry_if_not_available(self,func,*args):
        if sys.platform != 'darwin':
            return func(*args)
        else:
            for i in range(1,10):
                try:
                    if i > 1: mutter('DAV request retry : [%d]' % i)
                    return func(*args)
                except socket.error, e:
                    if e.args[0] == errno.EAGAIN:
                        time.sleep(0.05)
                        continue
                    mutter("Hmm, that's worse than I thought")
                    raise

    def _read(self, length):
        """Read the client socket"""
        return self._retry_if_not_available(self.rfile.read,length)

    def _readline(self):
        """Read a full line on the client socket"""
        return self._retry_if_not_available(self.rfile.readline)

    def read_body(self):
        """Read the body either by chunk or as a whole."""
        content_length = self.headers.get('Content-Length')
        encoding = self.headers.get('Transfer-Encoding')
        if encoding is not None:
            assert encoding == 'chunked'
            body = []
            # We receive the content by chunk
            while True:
                length, data = self.read_chunk()
                if length == 0:
                    break
                body.append(data)
            body = ''.join(body)

        else:
            if content_length is not None:
                body = self._read(int(content_length))

        return body

    def read_chunk(self):
        """Read a chunk of data.

        A chunk consists of:
        - a line containing the length of the data in hexa,
        - the data.
        - a empty line.

        An empty chunk specifies a length of zero
        """
        length = int(self._readline(),16)
        data = None
        if length != 0:
            data = self._read(length)
            # Eats the newline following the chunk
            self._readline()
        return length, data

    def do_PUT(self):
        """Serve a PUT request."""
        path = self.translate_path(self.path)
        mutter("do_PUT rel: [%s], abs: [%s]" % (self.path,path))

        do_append = False
        # Check the Content-Range header
        range_header = self.headers.get('Content-Range')
        if range_header is not None:
            match = self._RANGE_HEADER_RE.match(range_header)
            if match is None:
                # FIXME: RFC2616 says to return a 501 if we don't
                # understand the Content-Range header, but Apache
                # just ignores them (bad Apache).
                self.send_error(501, 'Not Implemented')
                return
            else:
                (begin, size) = match.group('begin','size')
                begin = int(begin)
                size = int(size)
                do_append = True

        if self.headers.get('Expect') == '100-continue':
            # Tell the client to go ahead, we're ready to get the content
            self.send_response(100,"Continue")
            self.end_headers()

        try:
            mutter("do_PUT will try to open: [%s]" % path)
            # Always write in binary mode.
            if do_append:
                f = open(path,'ab')
                f.seek(begin)
            else:
                f = open(path, 'wb')
        except (IOError, OSError), e :
            self.send_error(409, 'Conflict')
            return

        try:
            data = self.read_body()
            f.write(data)
        except (IOError, OSError):
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
                # _translate_error of  Transport, but this method
                # is not a real one. It's really a function which
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
            # seems misleading, RFC2518 says so, stop arguing :)
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
        overwrite_header = self.headers.get('Overwrite')
        if overwrite_header == 'F':
            should_overwrite = False
        else:
            should_overwrite = True
        scheme, username, password, host, port, rel_to = split_url(url_to)
        mutter("do_MOVE rel_from: [%s], rel_to: [%s]" % (self.path,rel_to))
        abs_from = self.translate_path(self.path)
        abs_to = self.translate_path(rel_to)
        if should_overwrite is False and os.access(abs_to, os.F_OK):
            self.send_error(412,"Precondition Failed")
            return
        try:
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
            # seems misleading, RFC2518 says so, stop arguing :)
            self.send_response(201)
            self.end_headers()

class TestingDAVAppendRequestHandler(TestingDAVRequestHandler):
    """
    Subclass of TestingDAVRequestHandler implementing te APPEND command.

    http://www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt
    propose two new commands: APPEND and PATCH. Their description
    is sparse, this is a best effort attempt to implement the
    APPEND command.
    """
    def do_APPEND(self):
        """Serve an APPEND request"""
        path = self.translate_path(self.path)
        mutter("do_APPEND rel: [%s], abs: [%s]" % (self.path,path))

        if self.headers.get('Expect') == '100-continue':
            # Tell the client to go ahead, we're ready to get the content
            self.send_response(100,"Continue")
            self.end_headers()

        try:
            # Always write in binary mode.
            mutter("do_APPEND will try to open: [%s]" % path)
            f = open(path, 'wb+')
        except (IOError, OSError), e :
            self.send_error(409, "Conflict")
            return

        try:
            data = self.read_body()
            f.write(data)
        except (IOError, OSError):
            # FIXME: We leave a partially updated file here
            self.send_error(409, "Conflict")
            f.close()
            return
        f.close()
        mutter("do_APPEND done: [%s]" % self.path)
        # FIXME: We should send 204 if the file didn't exist before
        self.send_response(201)
        self.end_headers()


class HttpServer_Dav(HttpServer):
    """Subclass of HttpServer that gives http+webdav urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    """

    def __init__(self):
        # We    have   special    requests    to   handle    that
        # HttpServer_PyCurl don't know about
        super(HttpServer_Dav,self).__init__(TestingDAVRequestHandler)

    # urls returned by this server should require the webdav client impl
    _url_protocol = 'http+webdav'

class HttpServer_Dav_append(HttpServer_Dav):
    """Subclass of HttpServer that gives http+webdav urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    This server implements the proposed
    (www.ietf.org/internet-drafts/draft-suma-append-patch-00.txt)
    APPEND request.
    """

    def __init__(self):
        # We    have   special    requests    to   handle    that
        # HttpServer_PyCurl don't know about
        super(HttpServer_Dav,self).__init__(TestingDAVAppendRequestHandler)

    # urls returned by this server should require the webdav client impl
    _url_protocol = 'http+webdav'

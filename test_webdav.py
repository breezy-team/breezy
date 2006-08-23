# Tests for the wedav plugin.

import errno
import os
import os.path
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
from bzrlib.transport.http import (
    TestingHTTPRequestHandler
    )
from bzrlib.transport.http._pycurl import (
    HttpServer_PyCurl
    )

class TestingDAVRequestHandler(TestingHTTPRequestHandler):
    """
    Subclass of TestingHTTPRequestHandler handling DAV requests.

    This is not a full implementation of a DAV server, only the parts
    really used by the plugin are.
    """

    # On   Mac  OS   X,  we   get  EAGAIN   (ressource  temporary
    # unavailable)... permanently :) when reading the client socket
    def _retry_if_not_available(self,func,*args):
        if sys.platform != 'darwin':
            return func(*args)
        else:
            for i in range(1,10):
                try:
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

    def _read_chunk(self):
        """
        Read a chunk of data.

        A chunk consists of:
        - a line containing the lenghtof the data in hexa,
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
        # Tell the client to go ahead, we're ready to get the content
        self.send_response(100,"Continue")
        self.end_headers()
        try:
            # Always write in binary mode.
            mutter("do_PUT will try to open: [%s]" % path)
            f = open(path, 'wb')
        except (IOError, OSError), e :
            self.send_error(409, "Conflict")
            return
        try:
            # We receive the content by chunk
            while True:
                length, data = self._read_chunk()
                if length == 0:
                    break
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

class HttpServer_Dav(HttpServer_PyCurl):
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


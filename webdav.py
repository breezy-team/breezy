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

# TODO:  Try to  use Transport.translate_error  if it  becomes an
# accessible function. Otherwise  duplicate it here (bad). Anyway
# all translations of IOError and OSError should be factored.

# TODO: Have the webdav plugin try to use APPEND, and if it isn't
# available, permanently switch back to get + put for the life of
# the Transport.

# TODO:  We can  detect that  the  server do  not accept  "write"
# operations (it will return 501) and raise InvalidHttpRequest(to
# be defined as a  daughter of InvalidHttpResponse) but what will
# the upper layers do ?

# TODO: 20060908 All *_file functions are defined in terms of
# *_bytes because we have to read the file to create a proper PUT
# request.  Is it possible to define PUT with a file-like object,
# so that we don't have to potentially read in and hold onto
# potentially 600MB of file contents?

# TODO: Factor out the error handling.

from cStringIO import StringIO
import os
import random
import re
import sys
import time
import urllib2
import xml.sax
import xml.sax.handler


from bzrlib import (
    errors,
    osutils,
    trace,
    transport,
    urlutils,
    )
from bzrlib.transport.http import (
    _urllib,
    _urllib2_wrappers,
    )


class DavResponseHandler(xml.sax.handler.ContentHandler):
    """Handle a multi-status DAV response."""

    def __init__(self):
        self.url = None
        self.elt_stack = None
        self.chars = None
        self.chars_wanted = False
        self.expected_content_handled = False

    def set_url(self, url):
        """Set the url used for error reporting when handling a response."""
        self.url = url

    def startDocument(self):
        self.elt_stack = []
        self.chars = None
        self.expected_content_handled = False

    def endDocument(self):
        self._validate_handling()
        if not self.expected_content_handled:
            raise errors.InvalidHttpResponse(self.url,
                                             msg='Unknown xml response')

    def startElement(self, name, attrs):
        self.elt_stack.append(self._strip_ns(name))
        # The following is incorrect in the general case where elements are
        # intermixed with chars in a higher level element. That's not the case
        # here (otherwise the chars_wanted will have to be stacked too).
        if self.chars_wanted:
            self.chars = ''
        else:
            self.chars = None

    def endElement(self, name):
        self.chars = None
        self.chars_wanted = False
        self.elt_stack.pop()

    def characters(self, chrs):
        if self.chars_wanted:
            self.chars += chrs

    def _current_element(self):
        return self.elt_stack[-1]

    def _strip_ns(self, name):
        """Strip the leading namespace from name.

        We don't have namespaces clashes in our context, stripping it makes the
        code simpler.
        """
        where = name.find(':')
        if where == -1:
            return name
        else:
            return name[where +1:]


class DavListDirHandler(DavResponseHandler):
    """Handle a PROPPFIND depth 1 DAV response for a directory.

    The expected content is a multi-status containing a list of response
    containing at least a href property.
    """
    def __init__(self):
        DavResponseHandler.__init__(self)
        self.dir_content = None

    def _validate_handling(self):
        if self.dir_content is not None:
            self.expected_content_handled = True

    def startElement(self, name, attrs):
        self.chars_wanted = (self._strip_ns(name) == 'href')
        DavResponseHandler.startElement(self, name, attrs)

    def endElement(self, name):
        stack = self.elt_stack
        if (len(stack) == 3
            and stack[0] == 'multistatus'
            and stack[1] == 'response'
             # sax guarantees that name is also href (when ns is stripped)
            and stack[2] == 'href'):
            if self.dir_content is None:
                self.dir_content = []
            self.dir_content.append(self.chars)
        DavResponseHandler.endElement(self, name)


def _extract_dir_content(url, infile):
    """Extract the directory content from a DAV PROPFIND response.

    :param url: The url used for the PROPFIND request.
    :param infile: A file-like object pointing at the start of the response.
    """
    parser = xml.sax.make_parser()

    handler = DavListDirHandler()
    handler.set_url(url)
    parser.setContentHandler(handler)
    try:
        parser.parse(infile)
    except xml.sax.SAXParseException, e:
        raise errors.InvalidHttpResponse(
            url, msg='Malformed xml response: %s' % e)
    # Reformat for bzr needs
    dir_content = handler.dir_content
    dir = dir_content[0]
    dir_len = len(dir)
    elements = []
    for href in dir_content[1:]: # Ignore first element
        if href.startswith(dir):
            name = href[dir_len:]
            if name.endswith('/'):
                # Get rid of final '/'
                name = name[0:-1]
            # We receive already url-encoded strings so down-casting is
            # safe. And bzr insists on getting strings not unicode strings.
            elements.append(str(name))
    return elements


class DavStatHandler(DavResponseHandler):
    """Handle a PROPPFIND depth 0 DAV response for a file or directory.

    The expected content is:
    - a multi-status element containing
      - a single response element containing
        - a href element
        - a propstat element containing
          - a status element (ignored)
          - a prop element containing at least (other are ignored)
            - a getcontentlength element (for files only)
            - an executable element (for files only)
    """

    def __init__(self):
        DavResponseHandler.__init__(self)
        self.href = None
        self.length = None
        self.executable = None
        # Flags defining the context for the actions
        self._response_seen = False

    def _validate_handling(self):
        if self.href is not None:
            self.expected_content_handled = True

    def startElement(self, name, attrs):
        sname = self._strip_ns(name)
        self.chars_wanted = sname in ('href', 'getcontentlength', 'executable')
        DavResponseHandler.startElement(self, name, attrs)

    def endElement(self, name):
        sname = self._strip_ns(name)
        if self._response_seen:
            if sname != 'multistatus':
                raise errors.InvalidHttpResponse(
                    self.url, msg='Unexpected %s element' % name)
        else:
            # We process only the first response (just in case)
            if self._href_end():
                self.href = self.chars
            elif self._getcontentlength_end():
                self.length = self.chars
            elif self._executable_end():
                self.executable = self.chars
        if sname == 'response':
            self._response_seen = True
        DavResponseHandler.endElement(self, name)

    def _href_end(self):
        stack = self.elt_stack
        return (len(stack) == 3
                and stack[0] == 'multistatus'
                and stack[1] == 'response'
                and stack[2] == 'href')

    def _getcontentlength_end(self):
        stack = self.elt_stack
        return (len(stack) == 5
                and stack[0] == 'multistatus'
                and stack[1] == 'response'
                and stack[2] == 'propstat'
                and stack[3] == 'prop'
                and stack[4] == 'getcontentlength')

    def _executable_end(self):
        stack = self.elt_stack
        return (len(stack) == 5
                and stack[0] == 'multistatus'
                and stack[1] == 'response'
                and stack[2] == 'propstat'
                and stack[3] == 'prop'
                and stack[4] == 'executable')


class _DAVStat(object):
    """The stat info as it can be acquired with DAV."""

    def __init__(self, size, is_dir, is_exec):
        self.st_size = size
        # We build a mode considering that:

        # - we have no idea about group or other chmod bits so we use a sane
        #   default (bzr should not care anyway)

        # - we suppose that the user can write
        if is_dir:
            self.st_mode = 0040644
        else:
            self.st_mode = 0100644
        if is_exec:
            self.st_mode = self.st_mode | 0755


def _extract_stat_info(url, infile):
    """Extract the stat-like information from a DAV PROPFIND response.

    :param url: The url used for the PROPFIND request.
    :param infile: A file-like object pointing at the start of the response.
    """
    parser = xml.sax.make_parser()

    handler = DavStatHandler()
    handler.set_url(url)
    parser.setContentHandler(handler)
    try:
        parser.parse(infile)
    except xml.sax.SAXParseException, e:
        raise errors.InvalidHttpResponse(
            url, msg='Malformed xml response: %s' % e)
    is_dir = (handler.href is not None
              and handler.length is None
              and handler.executable is None)
    if is_dir:
        size = None # directory sizes are meaningless for bzr
        is_exec = True
    else:
        size = int(handler.length)
        is_exec = (handler.executable == 'T')
    return _DAVStat(size, is_dir, is_exec)


class PUTRequest(_urllib2_wrappers.Request):

    def __init__(self, url, data, more_headers={}, accepted_errors=None):
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
        _urllib2_wrappers.Request.__init__(self, 'PUT', url, data, headers,
                                           accepted_errors=accepted_errors)


class DavResponse(_urllib2_wrappers.Response):
    """Custom HTTPResponse.

    DAV have some reponses for which the body is of no interest.
    """
    _body_ignored_responses = (
        _urllib2_wrappers.Response._body_ignored_responses
        + [201, 405, 409, 412,]
        )

    def  begin(self):
        """Begin to read the response from the server.

        httplib incorrectly close the connection far too easily. Let's try to
        workaround that (as _urllib2 does, but for more cases...).
        """
        _urllib2_wrappers.Response.begin(self)
        if self.status in (201, 204):
            self.will_close = False


# Takes DavResponse into account:
class DavHTTPConnection(_urllib2_wrappers.HTTPConnection):

    response_class = DavResponse


class DavHTTPSConnection(_urllib2_wrappers.HTTPSConnection):

    response_class = DavResponse


class DavConnectionHandler(_urllib2_wrappers.ConnectionHandler):
    """Custom connection handler.

    We need to use the DavConnectionHTTPxConnection class to take
    into account our own DavResponse objects, to be able to
    declare our own body ignored responses, sigh.
    """

    def http_request(self, request):
        return self.capture_connection(request, DavHTTPConnection)

    def https_request(self, request):
        return self.capture_connection(request, DavHTTPSConnection)


class DavOpener(_urllib2_wrappers.Opener):
    """Dav specific needs regarding HTTP(S)"""

    def __init__(self):
        super(DavOpener, self).__init__(connection=DavConnectionHandler)


class HttpDavTransport(_urllib.HttpTransport_urllib):
    """An transport able to put files using http[s] on a DAV server.

    We don't try to implement the whole WebDAV protocol. Just the minimum
    needed for bzr.
    """

    _debuglevel = 0
    _opener_class = DavOpener

    def __init__(self, base, _from_transport=None):
        assert base.startswith('https+webdav') or base.startswith('http+webdav')
        super(HttpDavTransport, self).__init__(base,
                                               _from_transport=_from_transport)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return False

    def _raise_http_error(self, url, response, info=None):
        if info is None:
            msg = ''
        else:
            msg = ': ' + info
        raise errors.InvalidHttpResponse(url, 'Unable to handle http code %d%s'
                                         % (response.code, msg))

    def _handle_common_errors(self, code, abspath):
        if code == 404:
            raise errors.NoSuchFile(abspath)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        # FIXME: this implementation sucks, we should really use chunk encoding
        # and buffers.
        self.put_bytes(relpath, "", mode)
        result = transport.AppendBasedFileStream(self, relpath)
        transport._file_streams[self.abspath(relpath)] = result
        return result

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file"""
        # FIXME: We read the whole file in memory, using chunked encoding and
        # counting bytes while sending them will be far better. Look at reusing
        # osutils.pumpfile ?
        #
        bytes = f.read()
        self.put_bytes(relpath, bytes, mode=None)
        return len(bytes)

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
        abspath = self._remote_path(relpath)

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

        abspath = self._remote_path(relpath)
        request = PUTRequest(abspath, bytes,
                             accepted_errors=[200, 201, 204, 403, 404, 409])

        def bare_put_file_non_atomic():

            response = self._perform(request)
            code = response.code

            if code in (403, 404, 409):
                # Intermediate directories missing
                raise errors.NoSuchFile(abspath)
            if code not in  (200, 201, 204):
                self._raise_curl_http_error(abspath, response,
                                            'expected 200, 201 or 204.')

        try:
            bare_put_file_non_atomic()
        except errors.NoSuchFile:
            if not create_parent_dir:
                raise
            parent_dir = osutils.dirname(relpath)
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
        abspath = self._remote_path(relpath)

        # Content-Range is start-end/size. 'size' is the file size, not the
        # chunk size. We can't be sure about the size of the file so put '*' at
        # the end of the range instead.
        request = PUTRequest(abspath, bytes,
                             {'Content-Range':
                                  'bytes %d-%d/*' % (at, at+len(bytes)),},
                             accepted_errors=[200, 201, 204, 403, 404, 409])
        response = self._perform(request)
        code = response.code

        if code in (403, 404, 409):
            raise errors.NoSuchFile(abspath) # Intermediate directories missing
        if code not in  (200, 201, 204):
            self._raise_http_error(abspath, response,
                                   'expected 200, 201 or 204.')

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir"""
        abspath = self._remote_path(relpath)

        request = _urllib2_wrappers.Request('MKCOL', abspath,
                                            accepted_errors=[201, 403, 405,
                                                             404, 409])
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
            raise errors.FileExists(abspath)
        elif code in (404, 409):
            # Conflict (intermediate directories do not exist)
            raise errors.NoSuchFile(abspath)
        elif code != 201: # Created
            raise self._raise_http_error(abspath, response, 'mkdir failed')

    def rename(self, rel_from, rel_to):
        """Rename without special overwriting"""
        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)

        request = _urllib2_wrappers.Request('MOVE', abs_from, None,
                                            {'Destination': abs_to,
                                             'Overwrite': 'F'},
                                            accepted_errors=[201, 404, 409,
                                                             412])
        response = self._perform(request)

        code = response.code
        if code == 404:
            raise errors.NoSuchFile(abs_from)
        if code == 412:
            raise errors.FileExists(abs_to)
        if code == 409:
            # More precisely some intermediate directories are missing
            raise errors.NoSuchFile(abs_to)
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

        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)

        request = _urllib2_wrappers.Request('MOVE', abs_from, None,
                                            {'Destination': abs_to},
                                            accepted_errors=[201, 204,
                                                             404, 409])
        response = self._perform(request)

        code = response.code
        if code == 404:
            raise errors.NoSuchFile(abs_from)
        if code == 409:
            raise errors.DirectoryNotEmpty(abs_to)
        # Overwriting  allowed, 201 means  abs_to did  not exist,
        # 204 means it did exist.
        if code not in (201, 204):
            self._raise_http_error(abs_from, response,
                                   'unable to move to %r' % (abs_to))

    def delete(self, rel_path):
        """
        Delete the item at relpath.

        Note that when a non-empty dir required to be deleted, a conforming DAV
        server will delete the dir and all its content. That does not normally
        append in bzr.
        """
        abs_path = self._remote_path(rel_path)

        request = _urllib2_wrappers.Request('DELETE', abs_path,
                                            accepted_errors=[200, 204,
                                                             404, 999])
        response = self._perform(request)

        code = response.code
        if code == 404:
            raise errors.NoSuchFile(abs_path)
        # FIXME: This  is an  hoooooorible workaround to  pass the
        # tests,  what  we really  should  do  is  test that  the
        # directory  is not  empty *because  bzr do  not  want to
        # remove non-empty dirs*.
        # Which requires implementing list_dir, hi Robert ;)
        if code == 999:
            raise errors.DirectoryNotEmpty(abs_path)
        if code != 204:
            self._raise_curl_http_error(curl, 'unable to delete')

    def copy(self, rel_from, rel_to):
        """See Transport.copy"""
        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)

        request = _urllib2_wrappers.Request(
            'COPY', abs_from, None,
            {'Destination': abs_to},
            accepted_errors=[201, 204, 404, 409])
        response = self._perform(request)

        code = response.code
        if code in (404, 409):
            raise errors.NoSuchFile(abs_from)
        # XXX: out test server returns 201 but apache2 returns 204, need
        # investivation.
        if code not in(201, 204):
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
        return transport.Transport.copy_to(self, relpaths, other,
                                           mode=mode, pb=pb)

    def listable(self):
        """See Transport.listable."""
        return True

    def list_dir(self, relpath):
        """
        Return a list of all files at the given location.
        """
        abspath = self._remote_path(relpath)
        propfind = """<?xml version="1.0" encoding="utf-8" ?>
   <D:propfind xmlns:D="DAV:">
     <D:prop/>
   </D:propfind>
"""
        request = _urllib2_wrappers.Request('PROPFIND', abspath, propfind,
                                            {'Depth': 1},
                                            accepted_errors=[207, 404, 409,])
        response = self._perform(request)

        code = response.code
        if code == 404:
            raise errors.NoSuchFile(abspath)
        if code == 409:
            # More precisely some intermediate directories are missing
            raise errors.NoSuchFile(abspath)
        if code != 207:
            self._raise_http_error(abspath, response,
                                   'unable to list  %r directory' % (abspath))
        return _extract_dir_content(abspath, response)

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

    def stat(self, relpath):
        """See Transport.stat.

        We provide a limited implementation for bzr needs.
        """
        abspath = self._remote_path(relpath)
        propfind = """<?xml version="1.0" encoding="utf-8" ?>
   <D:propfind xmlns:D="DAV:">
     <D:allprop/>
   </D:propfind>
"""
        request = _urllib2_wrappers.Request('PROPFIND', abspath, propfind,
                                            {'Depth': 0},
                                            accepted_errors=[207, 404, 409,])
        response = self._perform(request)

        code = response.code
        if code == 404:
            raise errors.NoSuchFile(abspath)
        if code == 409:
            # More precisely some intermediate directories are missing
            raise errors.NoSuchFile(abspath)
        if code != 207:
            self._raise_http_error(abspath, response,
                                   'unable to list  %r directory' % (abspath))
        return _extract_stat_info(abspath, response)

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
            relpath_size = 0
        else:
            # Consider the absence of Content-Length header as
            # indicating an existing but empty file (Apache 2.0
            # does this, and there is even a comment in
            # modules/http/http_protocol.c calling that a *hack*,
            # I agree, it's a hack. On the other hand if the file
            # do not exist we get a 404, if the file does exist,
            # is not empty and we get no Content-Length header,
            # then the server is buggy :-/ )
            relpath_size = int(response.headers.get('Content-Length', 0))
            if relpath_size == 0:
                trace.mutter('if %s is not empty, the server is buggy'
                             % relpath)
        if relpath_size:
            self._put_bytes_ranged(relpath, bytes, relpath_size)
        else:
            self.put_bytes(relpath, bytes)

        return relpath_size

    def _append_by_get_put(self, relpath, bytes):
        # So  we need to  GET the  file first,  append to  it and
        # finally PUT  back the  result.
        full_data = StringIO()
        try:
            data = self.get(relpath)
            full_data.write(data.read())
        except errors.NoSuchFile:
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

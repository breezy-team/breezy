# Copyright (C) 2005, 2006 Canonical Ltd
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

import urllib, urllib2
import errno
from StringIO import StringIO

import bzrlib  # for the version
from bzrlib.trace import mutter
from bzrlib.transport import register_urlparse_netloc_protocol
from bzrlib.transport.http import HttpTransportBase, extract_auth, HttpServer
from bzrlib.transport.http._response import (HttpMultipartRangeResponse,
                                             HttpRangeResponse)
from bzrlib.errors import (TransportNotPossible, NoSuchFile, BzrError,
                           TransportError, ConnectionError)

register_urlparse_netloc_protocol('http+urllib')


class Request(urllib2.Request):
    """Request object for urllib2 that allows the method to be overridden."""

    method = None

    def get_method(self):
        if self.method is not None:
            return self.method
        else:
            return urllib2.Request.get_method(self)


class HttpTransport_urllib(HttpTransportBase):
    """Python urllib transport for http and https.
    """

    # TODO: Implement pipelined versions of all of the *_multi() functions.

    def __init__(self, base):
        """Set the base path where files will be stored."""
        super(HttpTransport_urllib, self).__init__(base)

    def readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param offsets: A list of (offset, size) tuples.
        :param return: A list or generator of (offset, data) tuples
        """
        mutter('readv of %s [%s]', relpath, offsets)
        ranges = self._offsets_to_ranges(offsets)
        code, f = self._get(relpath, ranges)
        for start, size in offsets:
            f.seek(start, 0)
            data = f.read(size)
            assert len(data) == size
            yield start, data

    def _is_multipart(self, content_type):
        return content_type.startswith('multipart/byteranges;')

    def _handle_response(self, path, response):
        """Interpret the code & headers and return a HTTP response.

        This is a factory method which returns an appropriate HTTP response
        based on the code & headers it's given.
        """
        content_type = response.headers['Content-Type']
        mutter('handling response code %s ctype %s', response.code,
            content_type)

        if response.code == 206 and self._is_multipart(content_type):
            # Full fledged multipart response
            return HttpMultipartRangeResponse(path, content_type, response)
        elif response.code == 206:
            # A response to a range request, but not multipart
            content_range = response.headers['Content-Range']
            return HttpRangeResponse(path, content_range, response)
        elif response.code == 200:
            # A regular non-range response, unfortunately the result from
            # urllib doesn't support seek, so we wrap it in a StringIO
            return StringIO(response.read())
        elif response.code == 404:
            raise NoSuchFile(path)

        raise BzrError("HTTP couldn't handle code %s", response.code)

    def _get(self, relpath, ranges):
        path = relpath
        try:
            path = self._real_abspath(relpath)
            response = self._get_url_impl(path, method='GET', ranges=ranges)
            return response.code, self._handle_response(path, response)
        except urllib2.HTTPError, e:
            mutter('url error code: %s for has url: %r', e.code, path)
            if e.code == 404:
                raise NoSuchFile(path, extra=e)
            raise
        except (BzrError, IOError), e:
            if hasattr(e, 'errno'):
                mutter('io error: %s %s for has url: %r',
                    e.errno, errno.errorcode.get(e.errno), path)
                if e.errno == errno.ENOENT:
                    raise NoSuchFile(path, extra=e)
            raise ConnectionError(msg = "Error retrieving %s: %s" 
                             % (self.abspath(relpath), str(e)),
                             orig_error=e)

    def _get_url_impl(self, url, method, ranges):
        """Actually pass get request into urllib

        :returns: urllib Response object
        """
        manager = urllib2.HTTPPasswordMgrWithDefaultRealm()
        url = extract_auth(url, manager)
        auth_handler = urllib2.HTTPBasicAuthHandler(manager)
        opener = urllib2.build_opener(auth_handler)
        request = Request(url)
        request.method = method
        request.add_header('Pragma', 'no-cache')
        request.add_header('Cache-control', 'max-age=0')
        request.add_header('User-Agent', 'bzr/%s (urllib)' % bzrlib.__version__)
        if ranges:
            request.add_header('Range', self._range_header(ranges))
        mutter("GET %s [%s]" % (url, request.get_header('Range')))
        response = opener.open(request)
        return response

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def has(self, relpath):
        """Does the target location exist?
        """
        abspath = self._real_abspath(relpath)
        try:
            f = self._get_url_impl(abspath, 'HEAD', [])
            # Without the read and then close()
            # we tend to have busy sockets.
            f.read()
            f.close()
            return True
        except urllib2.URLError, e:
            mutter('url error code: %s for has url: %r', e.code, abspath)
            if e.code == 404:
                return False
            raise
        except IOError, e:
            mutter('io error: %s %s for has url: %r',
                e.errno, errno.errorcode.get(e.errno), abspath)
            if e.errno == errno.ENOENT:
                return False
            raise TransportError(orig_error=e)

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.

        TODO: if other is LocalTransport, is it possible to
              do better than put(get())?
        """
        # At this point HttpTransport_urllib might be able to check and see if
        # the remote location is the same, and rather than download, and
        # then upload, it could just issue a remote copy_this command.
        if isinstance(other, HttpTransport_urllib):
            raise TransportNotPossible('http cannot be the target of copy_to()')
        else:
            return super(HttpTransport_urllib, self).copy_to(relpaths, other, mode=mode, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise TransportNotPossible('http does not support delete()')


class HttpServer_urllib(HttpServer):
    """Subclass of HttpServer that gives http+urllib urls.

    This is for use in testing: connections to this server will always go
    through urllib where possible.
    """

    # urls returned by this server should require the urllib client impl
    _url_protocol = 'http+urllib'


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(HttpTransport_urllib, HttpServer_urllib),
            ]

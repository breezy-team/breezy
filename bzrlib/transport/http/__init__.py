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

"""Base implementation of Transport over http.

There are separate implementation modules for each http client implementation.
"""

from cStringIO import StringIO
import mimetools
import re
import urlparse
import urllib

from bzrlib import errors, ui
from bzrlib.trace import mutter
from bzrlib.transport import (
    smart,
    Transport,
    )


# TODO: This is not used anymore by HttpTransport_urllib
# (extracting the auth info and prompting the user for a password
# have been split), only the tests still use it. It should be
# deleted and the tests rewritten ASAP to stay in sync.
def extract_auth(url, password_manager):
    """Extract auth parameters from am HTTP/HTTPS url and add them to the given
    password manager.  Return the url, minus those auth parameters (which
    confuse urllib2).
    """
    assert re.match(r'^(https?)(\+\w+)?://', url), \
            'invalid absolute url %r' % url
    scheme, netloc, path, query, fragment = urlparse.urlsplit(url)

    if '@' in netloc:
        auth, netloc = netloc.split('@', 1)
        if ':' in auth:
            username, password = auth.split(':', 1)
        else:
            username, password = auth, None
        if ':' in netloc:
            host = netloc.split(':', 1)[0]
        else:
            host = netloc
        username = urllib.unquote(username)
        if password is not None:
            password = urllib.unquote(password)
        else:
            password = ui.ui_factory.get_password(
                prompt='HTTP %(user)s@%(host)s password',
                user=username, host=host)
        password_manager.add_password(None, host, username, password)
    url = urlparse.urlunsplit((scheme, netloc, path, query, fragment))
    return url


def _extract_headers(header_text, url):
    """Extract the mapping for an rfc2822 header

    This is a helper function for the test suite and for _pycurl.
    (urllib already parses the headers for us)

    In the case that there are multiple headers inside the file,
    the last one is returned.

    :param header_text: A string of header information.
        This expects that the first line of a header will always be HTTP ...
    :param url: The url we are parsing, so we can raise nice errors
    :return: mimetools.Message object, which basically acts like a case 
        insensitive dictionary.
    """
    first_header = True
    remaining = header_text

    if not remaining:
        raise errors.InvalidHttpResponse(url, 'Empty headers')

    while remaining:
        header_file = StringIO(remaining)
        first_line = header_file.readline()
        if not first_line.startswith('HTTP'):
            if first_header: # The first header *must* start with HTTP
                raise errors.InvalidHttpResponse(url,
                    'Opening header line did not start with HTTP: %s'
                    % (first_line,))
                assert False, 'Opening header line was not HTTP'
            else:
                break # We are done parsing
        first_header = False
        m = mimetools.Message(header_file)

        # mimetools.Message parses the first header up to a blank line
        # So while there is remaining data, it probably means there is
        # another header to be parsed.
        # Get rid of any preceeding whitespace, which if it is all whitespace
        # will get rid of everything.
        remaining = header_file.read().lstrip()
    return m


class HttpTransportBase(Transport, smart.SmartClientMedium):
    """Base class for http implementations.

    Does URL parsing, etc, but not any network IO.

    The protocol can be given as e.g. http+urllib://host/ to use a particular
    implementation.
    """

    # _proto: "http" or "https"
    # _qualified_proto: may have "+pycurl", etc

    def __init__(self, base, from_transport=None):
        """Set the base path where files will be stored."""
        proto_match = re.match(r'^(https?)(\+\w+)?://', base)
        if not proto_match:
            raise AssertionError("not a http url: %r" % base)
        self._proto = proto_match.group(1)
        impl_name = proto_match.group(2)
        if impl_name:
            impl_name = impl_name[1:]
        self._impl_name = impl_name
        if base[-1] != '/':
            base = base + '/'
        super(HttpTransportBase, self).__init__(base)
        (apparent_proto, self._host,
            self._path, self._parameters,
            self._query, self._fragment) = urlparse.urlparse(self.base)
        self._qualified_proto = apparent_proto
        # range hint is handled dynamically throughout the life
        # of the object. We start by trying mulri-range requests
        # and if the server returns bougs results, we retry with
        # single range requests and, finally, we forget about
        # range if the server really can't understand. Once
        # aquired, this piece of info is propogated to clones.
        if from_transport is not None:
            self._range_hint = from_transport._range_hint
        else:
            self._range_hint = 'multi'

    def abspath(self, relpath):
        """Return the full url to the given relative path.

        This can be supplied with a string or a list.

        The URL returned always has the protocol scheme originally used to 
        construct the transport, even if that includes an explicit
        implementation qualifier.
        """
        assert isinstance(relpath, basestring)
        if isinstance(relpath, unicode):
            raise errors.InvalidURL(relpath, 'paths must not be unicode.')
        if isinstance(relpath, basestring):
            relpath_parts = relpath.split('/')
        else:
            # TODO: Don't call this with an array - no magic interfaces
            relpath_parts = relpath[:]
        if relpath.startswith('/'):
            basepath = []
        else:
            # Except for the root, no trailing slashes are allowed
            if len(relpath_parts) > 1 and relpath_parts[-1] == '':
                raise ValueError(
                    "path %r within branch %r seems to be a directory"
                    % (relpath, self._path))
            basepath = self._path.split('/')
            if len(basepath) > 0 and basepath[-1] == '':
                basepath = basepath[:-1]

        for p in relpath_parts:
            if p == '..':
                if len(basepath) == 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                basepath.pop()
            elif p == '.' or p == '':
                continue # No-op
            else:
                basepath.append(p)
        # Possibly, we could use urlparse.urljoin() here, but
        # I'm concerned about when it chooses to strip the last
        # portion of the path, and when it doesn't.
        path = '/'.join(basepath)
        if path == '':
            path = '/'
        result = urlparse.urlunparse((self._qualified_proto,
                                    self._host, path, '', '', ''))
        return result

    def _real_abspath(self, relpath):
        """Produce absolute path, adjusting protocol if needed"""
        abspath = self.abspath(relpath)
        qp = self._qualified_proto
        rp = self._proto
        if self._qualified_proto != self._proto:
            abspath = rp + abspath[len(qp):]
        if not isinstance(abspath, str):
            # escaping must be done at a higher level
            abspath = abspath.encode('ascii')
        return abspath

    def has(self, relpath):
        raise NotImplementedError("has() is abstract on %r" % self)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        code, response_file = self._get(relpath, None)
        return response_file

    def _get(self, relpath, ranges):
        """Get a file, or part of a file.

        :param relpath: Path relative to transport base URL
        :param byte_range: None to get the whole file;
            or [(start,end)] to fetch parts of a file.

        :returns: (http_code, result_file)

        Note that the current http implementations can only fetch one range at
        a time through this call.
        """
        raise NotImplementedError(self._get)

    def get_request(self):
        return SmartClientHTTPMediumRequest(self)

    def get_smart_medium(self):
        """See Transport.get_smart_medium.

        HttpTransportBase directly implements the minimal interface of
        SmartMediumClient, so this returns self.
        """
        return self

    def _retry_get(self, relpath, ranges, exc_info):
        """A GET request have failed, let's retry with a simpler request."""

        try_again = False
        # The server does not gives us enough data or
        # bogus-looking result, let's try again with
        # a simpler request if possible.
        if self._range_hint == 'multi':
            self._range_hint = 'single'
            mutter('Retry %s with single range request' % relpath)
            try_again = True
        elif self._range_hint == 'single':
            self._range_hint = None
            mutter('Retry %s without ranges' % relpath)
            try_again = True
        if try_again:
            # Note that since the offsets and the ranges may not
            # be in the same order we dont't try to calculate a
            # restricted single range encompassing unprocessed
            # offsets.
            code, f = self._get(relpath, ranges)
            return try_again, code, f
        else:
            # We tried all the tricks, nothing worked
            raise exc_info[0], exc_info[1], exc_info[2]

    def readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param offsets: A list of (offset, size) tuples.
        :param return: A list or generator of (offset, data) tuples
        """
        ranges = self.offsets_to_ranges(offsets)
        mutter('http readv of %s collapsed %s offsets => %s',
                relpath, len(offsets), ranges)

        try_again = True
        while try_again:
            try_again = False
            try:
                code, f = self._get(relpath, ranges)
            except (errors.InvalidRange, errors.ShortReadvError), e:
                try_again, code, f = self._retry_get(relpath, ranges,
                                                     sys.exc_info())

        for start, size in offsets:
            try_again = True
            while try_again:
                try_again = False
                f.seek(start, (start < 0) and 2 or 0)
                start = f.tell()
                try:
                    data = f.read(size)
                    if len(data) != size:
                        raise errors.ShortReadvError(relpath, start, size,
                                                     actual=len(data))
                except (errors.InvalidRange, errors.ShortReadvError), e:
                    # Note that we replace 'f' here and that it
                    # may need cleaning one day before being
                    # thrown that way.
                    try_again, code, f = self._retry_get(relpath, ranges,
                                                         sys.exc_info())
            # After one or more tries, we get the data.
            yield start, data

    @staticmethod
    def offsets_to_ranges(offsets):
        """Turn a list of offsets and sizes into a list of byte ranges.

        :param offsets: A list of tuples of (start, size).  An empty list
            is not accepted.
        :return: a list of inclusive byte ranges (start, end) 
            Adjacent ranges will be combined.
        """
        # Make sure we process sorted offsets
        offsets = sorted(offsets)

        prev_end = None
        combined = []

        for start, size in offsets:
            end = start + size - 1
            if prev_end is None:
                combined.append([start, end])
            elif start <= prev_end + 1:
                combined[-1][1] = end
            else:
                combined.append([start, end])
            prev_end = end

        return combined

    def _post(self, body_bytes):
        """POST body_bytes to .bzr/smart on this transport.
        
        :returns: (response code, response body file-like object).
        """
        # TODO: Requiring all the body_bytes to be available at the beginning of
        # the POST may require large client buffers.  It would be nice to have
        # an interface that allows streaming via POST when possible (and
        # degrades to a local buffer when not).
        raise NotImplementedError(self._post)

    def put_file(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        """
        raise errors.TransportNotPossible('http PUT not supported')

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise errors.TransportNotPossible('http does not support mkdir()')

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        raise errors.TransportNotPossible('http does not support rmdir()')

    def append_file(self, relpath, f, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        raise errors.TransportNotPossible('http does not support append()')

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise errors.TransportNotPossible('http does not support copy()')

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.

        TODO: if other is LocalTransport, is it possible to
              do better than put(get())?
        """
        # At this point HttpTransport might be able to check and see if
        # the remote location is the same, and rather than download, and
        # then upload, it could just issue a remote copy_this command.
        if isinstance(other, HttpTransportBase):
            raise errors.TransportNotPossible(
                'http cannot be the target of copy_to()')
        else:
            return super(HttpTransportBase, self).\
                    copy_to(relpaths, other, mode=mode, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise errors.TransportNotPossible('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise errors.TransportNotPossible('http does not support delete()')

    def is_readonly(self):
        """See Transport.is_readonly."""
        return True

    def listable(self):
        """See Transport.listable."""
        return False

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        raise errors.TransportNotPossible('http does not support stat()')

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # The old RemoteBranch ignore lock for reading, so we will
        # continue that tradition and return a bogus lock object.
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        raise errors.TransportNotPossible('http does not support lock_write()')

    def clone(self, offset=None):
        """Return a new HttpTransportBase with root at self.base + offset

        We leave the daughter classes take advantage of the hint
        that it's a cloning not a raw creation.
        """
        if offset is None:
            return self.__class__(self.base, self)
        else:
            return self.__class__(self.abspath(offset), self)

    def attempted_range_header(self, ranges, tail_amount):
        """Prepare a HTTP Range header at a level the server should accept"""

        if self._range_hint == 'multi':
            # Nothing to do here
            return self.range_header(ranges, tail_amount)
        elif self._range_hint == 'single':
            # Combine all the requested ranges into a single
            # encompassing one
            if len(ranges) > 0:
                start, ignored = ranges[0]
                ignored, end = ranges[-1]
                if tail_amount not in (0, None):
                    # Nothing we can do here to combine ranges
                    # with tail_amount, just returns None. The
                    # whole file should be downloaded.
                    return None
                else:
                    return self.range_header([(start, end)], 0)
            else:
                # Only tail_amount, requested, leave range_header
                # do its work
                return self.range_header(ranges, tail_amount)
        else:
            return None

    @staticmethod
    def range_header(ranges, tail_amount):
        """Turn a list of bytes ranges into a HTTP Range header value.

        :param ranges: A list of byte ranges, (start, end).
        :param tail_amount: The amount to get from the end of the file.

        :return: HTTP range header string.

        At least a non-empty ranges *or* a tail_amount must be
        provided.
        """
        strings = []
        for start, end in ranges:
            strings.append('%d-%d' % (start, end))

        if tail_amount:
            strings.append('-%d' % tail_amount)

        return ','.join(strings)

    def send_http_smart_request(self, bytes):
        code, body_filelike = self._post(bytes)
        assert code == 200, 'unexpected HTTP response code %r' % (code,)
        return body_filelike


class SmartClientHTTPMediumRequest(smart.SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an HTTP medium."""

    def __init__(self, medium):
        smart.SmartClientMediumRequest.__init__(self, medium)
        self._buffer = ''

    def _accept_bytes(self, bytes):
        self._buffer += bytes

    def _finished_writing(self):
        data = self._medium.send_http_smart_request(self._buffer)
        self._response_body = data

    def _read_bytes(self, count):
        return self._response_body.read(count)

    def _finished_reading(self):
        """See SmartClientMediumRequest._finished_reading."""
        pass

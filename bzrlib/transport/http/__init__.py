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
import sys

from bzrlib import (
    errors,
    ui,
    urlutils,
    )
from bzrlib.smart import medium
from bzrlib.symbol_versioning import (
        deprecated_method,
        zero_seventeen,
        )
from bzrlib.trace import mutter
from bzrlib.transport import (
    ConnectedTransport,
    _CoalescedOffset,
    Transport,
    )

# FIXME: There are two known cases where we open a new connection during the
# lifetime of the transport:
# - when an error is received from the server,
# - when the keep-alive header reach zero.
# This should be taken into account for the connection sharing by either
# failing without reconnecting or inform the clones that a new connection have
# been established.

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


class HttpTransportBase(ConnectedTransport, medium.SmartClientMedium):
    """Base class for http implementations.

    Does URL parsing, etc, but not any network IO.

    The protocol can be given as e.g. http+urllib://host/ to use a particular
    implementation.
    """

    # _unqualified_scheme: "http" or "https"
    # _scheme: may have "+pycurl", etc

    def __init__(self, base, from_transport=None):
        """Set the base path where files will be stored."""
        proto_match = re.match(r'^(https?)(\+\w+)?://', base)
        if not proto_match:
            raise AssertionError("not a http url: %r" % base)
        self._unqualified_scheme = proto_match.group(1)
        impl_name = proto_match.group(2)
        if impl_name:
            impl_name = impl_name[1:]
        self._impl_name = impl_name
        super(HttpTransportBase, self).__init__(base, from_transport)
        # range hint is handled dynamically throughout the life
        # of the transport object. We start by trying multi-range
        # requests and if the server returns bogus results, we
        # retry with single range requests and, finally, we
        # forget about range if the server really can't
        # understand. Once acquired, this piece of info is
        # propagated to clones.
        if from_transport is not None:
            self._range_hint = from_transport._range_hint
        else:
            self._range_hint = 'multi'

    def _remote_path(self, relpath):
        """Produce absolute path, adjusting protocol."""
        relative = urlutils.unescape(relpath).encode('utf-8')
        path = self._combine_paths(self._path, relative)
        return self._unsplit_url(self._unqualified_scheme,
                                 self._user, self._password,
                                 self._host, self._port,
                                 path)

    def has(self, relpath):
        raise NotImplementedError("has() is abstract on %r" % self)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        code, response_file = self._get(relpath, None)
        return response_file

    def _get(self, relpath, ranges, tail_amount=0):
        """Get a file, or part of a file.

        :param relpath: Path relative to transport base URL
        :param ranges: None to get the whole file;
            or  a list of _CoalescedOffset to fetch parts of a file.
        :param tail_amount: The amount to get from the end of the file.

        :returns: (http_code, result_file)
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

    def _degrade_range_hint(self, relpath, ranges, exc_info):
        if self._range_hint == 'multi':
            self._range_hint = 'single'
            mutter('Retry "%s" with single range request' % relpath)
        elif self._range_hint == 'single':
            self._range_hint = None
            mutter('Retry "%s" without ranges' % relpath)
        else:
            # We tried all the tricks, but nothing worked. We re-raise original
            # exception; the 'mutter' calls above will indicate that further
            # tries were unsuccessful
            raise exc_info[0], exc_info[1], exc_info[2]

    def _get_ranges_hinted(self, relpath, ranges):
        """Issue a ranged GET request taking server capabilities into account.

        Depending of the errors returned by the server, we try several GET
        requests, trying to minimize the data transferred.

        :param relpath: Path relative to transport base URL
        :param ranges: None to get the whole file;
            or  a list of _CoalescedOffset to fetch parts of a file.
        :returns: A file handle containing at least the requested ranges.
        """
        exc_info = None
        try_again = True
        while try_again:
            try_again = False
            try:
                code, f = self._get(relpath, ranges)
            except errors.InvalidRange, e:
                if exc_info is None:
                    exc_info = sys.exc_info()
                self._degrade_range_hint(relpath, ranges, exc_info)
                try_again = True
        return f

    # _coalesce_offsets is a helper for readv, it try to combine ranges without
    # degrading readv performances. _bytes_to_read_before_seek is the value
    # used for the limit parameter and has been tuned for other transports. For
    # HTTP, the name is inappropriate but the parameter is still useful and
    # helps reduce the number of chunks in the response. The overhead for a
    # chunk (headers, length, footer around the data itself is variable but
    # around 50 bytes. We use 128 to reduce the range specifiers that appear in
    # the header, some servers (notably Apache) enforce a maximum length for a
    # header and issue a '400: Bad request' error when too much ranges are
    # specified.
    _bytes_to_read_before_seek = 128
    # No limit on the offset number that get combined into one, we are trying
    # to avoid downloading the whole file.
    _max_readv_combined = 0

    def readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param offsets: A list of (offset, size) tuples.
        :param return: A list or generator of (offset, data) tuples
        """
        sorted_offsets = sorted(list(offsets))
        fudge = self._bytes_to_read_before_seek
        coalesced = self._coalesce_offsets(sorted_offsets,
                                           limit=self._max_readv_combine,
                                           fudge_factor=fudge)
        coalesced = list(coalesced)
        mutter('http readv of %s  offsets => %s collapsed %s',
                relpath, len(offsets), len(coalesced))

        f = self._get_ranges_hinted(relpath, coalesced)
        for start, size in offsets:
            try_again = True
            while try_again:
                try_again = False
                f.seek(start, ((start < 0) and 2) or 0)
                start = f.tell()
                try:
                    data = f.read(size)
                    if len(data) != size:
                        raise errors.ShortReadvError(relpath, start, size,
                                                     actual=len(data))
                except errors.ShortReadvError, e:
                    self._degrade_range_hint(relpath, coalesced, sys.exc_info())

                    # Since the offsets and the ranges may not be in the same
                    # order, we don't try to calculate a restricted single
                    # range encompassing unprocessed offsets.

                    # Note: we replace 'f' here, it may need cleaning one day
                    # before being thrown that way.
                    f = self._get_ranges_hinted(relpath, coalesced)
                    try_again = True

            # After one or more tries, we get the data.
            yield start, data

    @staticmethod
    @deprecated_method(zero_seventeen)
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

    def external_url(self):
        """See bzrlib.transport.Transport.external_url."""
        # HTTP URL's are externally usable.
        return self.base

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

    def _attempted_range_header(self, offsets, tail_amount):
        """Prepare a HTTP Range header at a level the server should accept"""

        if self._range_hint == 'multi':
            # Nothing to do here
            return self._range_header(offsets, tail_amount)
        elif self._range_hint == 'single':
            # Combine all the requested ranges into a single
            # encompassing one
            if len(offsets) > 0:
                if tail_amount not in (0, None):
                    # Nothing we can do here to combine ranges with tail_amount
                    # in a single range, just returns None. The whole file
                    # should be downloaded.
                    return None
                else:
                    start = offsets[0].start
                    last = offsets[-1]
                    end = last.start + last.length - 1
                    whole = self._coalesce_offsets([(start, end - start + 1)],
                                                   limit=0, fudge_factor=0)
                    return self._range_header(list(whole), 0)
            else:
                # Only tail_amount, requested, leave range_header
                # do its work
                return self._range_header(offsets, tail_amount)
        else:
            return None

    @staticmethod
    def _range_header(ranges, tail_amount):
        """Turn a list of bytes ranges into a HTTP Range header value.

        :param ranges: A list of _CoalescedOffset
        :param tail_amount: The amount to get from the end of the file.

        :return: HTTP range header string.

        At least a non-empty ranges *or* a tail_amount must be
        provided.
        """
        strings = []
        for offset in ranges:
            strings.append('%d-%d' % (offset.start,
                                      offset.start + offset.length - 1))

        if tail_amount:
            strings.append('-%d' % tail_amount)

        return ','.join(strings)

    def send_http_smart_request(self, bytes):
        code, body_filelike = self._post(bytes)
        assert code == 200, 'unexpected HTTP response code %r' % (code,)
        return body_filelike


class SmartClientHTTPMediumRequest(medium.SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an HTTP medium."""

    def __init__(self, client_medium):
        medium.SmartClientMediumRequest.__init__(self, client_medium)
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

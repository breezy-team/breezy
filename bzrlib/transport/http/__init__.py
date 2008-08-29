# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
        )
from bzrlib.trace import mutter
from bzrlib.transport import (
    ConnectedTransport,
    _CoalescedOffset,
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
    if not re.match(r'^(https?)(\+\w+)?://', url):
        raise ValueError(
            'invalid absolute url %r' % (url,))
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


class HttpTransportBase(ConnectedTransport, medium.SmartClientMedium):
    """Base class for http implementations.

    Does URL parsing, etc, but not any network IO.

    The protocol can be given as e.g. http+urllib://host/ to use a particular
    implementation.
    """

    # _unqualified_scheme: "http" or "https"
    # _scheme: may have "+pycurl", etc

    def __init__(self, base, _from_transport=None):
        """Set the base path where files will be stored."""
        proto_match = re.match(r'^(https?)(\+\w+)?://', base)
        if not proto_match:
            raise AssertionError("not a http url: %r" % base)
        self._unqualified_scheme = proto_match.group(1)
        impl_name = proto_match.group(2)
        if impl_name:
            impl_name = impl_name[1:]
        self._impl_name = impl_name
        super(HttpTransportBase, self).__init__(base,
                                                _from_transport=_from_transport)
        # range hint is handled dynamically throughout the life
        # of the transport object. We start by trying multi-range
        # requests and if the server returns bogus results, we
        # retry with single range requests and, finally, we
        # forget about range if the server really can't
        # understand. Once acquired, this piece of info is
        # propagated to clones.
        if _from_transport is not None:
            self._range_hint = _from_transport._range_hint
        else:
            self._range_hint = 'multi'

    def has(self, relpath):
        raise NotImplementedError("has() is abstract on %r" % self)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        code, response_file = self._get(relpath, None)
        # FIXME: some callers want an iterable... One step forward, three steps
        # backwards :-/ And not only an iterable, but an iterable that can be
        # seeked backwards, so we will never be able to do that.  One such
        # known client is bzrlib.bundle.serializer.v4.get_bundle_reader. At the
        # time of this writing it's even the only known client -- vila20071203
        return StringIO(response_file.read())

    def _get(self, relpath, ranges, tail_amount=0):
        """Get a file, or part of a file.

        :param relpath: Path relative to transport base URL
        :param ranges: None to get the whole file;
            or  a list of _CoalescedOffset to fetch parts of a file.
        :param tail_amount: The amount to get from the end of the file.

        :returns: (http_code, result_file)
        """
        raise NotImplementedError(self._get)

    def _remote_path(self, relpath):
        """See ConnectedTransport._remote_path.

        user and passwords are not embedded in the path provided to the server.
        """
        relative = urlutils.unescape(relpath).encode('utf-8')
        path = self._combine_paths(self._path, relative)
        return self._unsplit_url(self._unqualified_scheme,
                                 None, None, self._host, self._port, path)

    def _create_auth(self):
        """Returns a dict returning the credentials provided at build time."""
        auth = dict(host=self._host, port=self._port,
                    user=self._user, password=self._password,
                    protocol=self._unqualified_scheme,
                    path=self._path)
        return auth

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
            # We tried all the tricks, but nothing worked. We re-raise the
            # original exception; the 'mutter' calls above will indicate that
            # further tries were unsuccessful
            raise exc_info[0], exc_info[1], exc_info[2]

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
    _max_readv_combine = 0
    # By default Apache has a limit of ~400 ranges before replying with a 400
    # Bad Request. So we go underneath that amount to be safe.
    _max_get_ranges = 200
    # We impose no limit on the range size. But see _pycurl.py for a different
    # use.
    _get_max_size = 0

    def _readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param offsets: A list of (offset, size) tuples.
        :param return: A list or generator of (offset, data) tuples
        """

        # offsets may be a generator, we will iterate it several times, so
        # build a list
        offsets = list(offsets)

        try_again = True
        retried_offset = None
        while try_again:
            try_again = False

            # Coalesce the offsets to minimize the GET requests issued
            sorted_offsets = sorted(offsets)
            coalesced = self._coalesce_offsets(
                sorted_offsets, limit=self._max_readv_combine,
                fudge_factor=self._bytes_to_read_before_seek,
                max_size=self._get_max_size)

            # Turn it into a list, we will iterate it several times
            coalesced = list(coalesced)
            mutter('http readv of %s  offsets => %s collapsed %s',
                    relpath, len(offsets), len(coalesced))

            # Cache the data read, but only until it's been used
            data_map = {}
            # We will iterate on the data received from the GET requests and
            # serve the corresponding offsets respecting the initial order. We
            # need an offset iterator for that.
            iter_offsets = iter(offsets)
            cur_offset_and_size = iter_offsets.next()

            try:
                for cur_coal, rfile in self._coalesce_readv(relpath, coalesced):
                    # Split the received chunk
                    for offset, size in cur_coal.ranges:
                        start = cur_coal.start + offset
                        rfile.seek(start, 0)
                        data = rfile.read(size)
                        data_len = len(data)
                        if data_len != size:
                            raise errors.ShortReadvError(relpath, start, size,
                                                         actual=data_len)
                        if (start, size) == cur_offset_and_size:
                            # The offset requested are sorted as the coalesced
                            # ones, no need to cache. Win !
                            yield cur_offset_and_size[0], data
                            cur_offset_and_size = iter_offsets.next()
                        else:
                            # Different sorting. We need to cache.
                            data_map[(start, size)] = data

                    # Yield everything we can
                    while cur_offset_and_size in data_map:
                        # Clean the cached data since we use it
                        # XXX: will break if offsets contains duplicates --
                        # vila20071129
                        this_data = data_map.pop(cur_offset_and_size)
                        yield cur_offset_and_size[0], this_data
                        cur_offset_and_size = iter_offsets.next()

            except (errors.ShortReadvError, errors.InvalidRange,
                    errors.InvalidHttpRange), e:
                mutter('Exception %r: %s during http._readv',e, e)
                if (not isinstance(e, errors.ShortReadvError)
                    or retried_offset == cur_offset_and_size):
                    # We don't degrade the range hint for ShortReadvError since
                    # they do not indicate a problem with the server ability to
                    # handle ranges. Except when we fail to get back a required
                    # offset twice in a row. In that case, falling back to
                    # single range or whole file should help or end up in a
                    # fatal exception.
                    self._degrade_range_hint(relpath, coalesced, sys.exc_info())
                # Some offsets may have been already processed, so we retry
                # only the unsuccessful ones.
                offsets = [cur_offset_and_size] + [o for o in iter_offsets]
                retried_offset = cur_offset_and_size
                try_again = True

    def _coalesce_readv(self, relpath, coalesced):
        """Issue several GET requests to satisfy the coalesced offsets"""

        def get_and_yield(relpath, coalesced):
            if coalesced:
                # Note that the _get below may raise
                # errors.InvalidHttpRange. It's the caller's responsibility to
                # decide how to retry since it may provide different coalesced
                # offsets.
                code, rfile = self._get(relpath, coalesced)
                for coal in coalesced:
                    yield coal, rfile

        if self._range_hint is None:
            # Download whole file
            for c, rfile in get_and_yield(relpath, coalesced):
                yield c, rfile
        else:
            total = len(coalesced)
            if self._range_hint == 'multi':
                max_ranges = self._max_get_ranges
            elif self._range_hint == 'single':
                max_ranges = total
            else:
                raise AssertionError("Unknown _range_hint %r"
                                     % (self._range_hint,))
            # TODO: Some web servers may ignore the range requests and return
            # the whole file, we may want to detect that and avoid further
            # requests.
            # Hint: test_readv_multiple_get_requests will fail once we do that
            cumul = 0
            ranges = []
            for coal in coalesced:
                if ((self._get_max_size > 0
                     and cumul + coal.length > self._get_max_size)
                    or len(ranges) >= max_ranges):
                    # Get that much and yield
                    for c, rfile in get_and_yield(relpath, ranges):
                        yield c, rfile
                    # Restart with the current offset
                    ranges = [coal]
                    cumul = coal.length
                else:
                    ranges.append(coal)
                    cumul += coal.length
            # Get the rest and yield
            for c, rfile in get_and_yield(relpath, ranges):
                yield c, rfile

    def recommended_page_size(self):
        """See Transport.recommended_page_size().

        For HTTP we suggest a large page size to reduce the overhead
        introduced by latency.
        """
        return 64 * 1024

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
        """Prepare a HTTP Range header at a level the server should accept.

        :return: the range header representing offsets/tail_amount or None if
            no header can be built.
        """

        if self._range_hint == 'multi':
            # Generate the header describing all offsets
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
        try:
            code, body_filelike = self._post(bytes)
            if code != 200:
                raise InvalidHttpResponse(
                    self._remote_path('.bzr/smart'),
                    'Expected 200 response code, got %r' % (code,))
        except errors.InvalidHttpResponse, e:
            raise errors.SmartProtocolError(str(e))
        return body_filelike

    def should_probe(self):
        return True

    def remote_path_from_transport(self, transport):
        # Strip the optional 'bzr+' prefix from transport so it will have the
        # same scheme as self.
        transport_base = transport.base
        if transport_base.startswith('bzr+'):
            transport_base = transport_base[4:]
        rel_url = urlutils.relative_url(self.base, transport_base)
        return urllib.unquote(rel_url)


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
        """See SmartClientMediumRequest._read_bytes."""
        return self._response_body.read(count)

    def _read_line(self):
        line, excess = medium._get_line(self._response_body.read)
        if excess != '':
            raise AssertionError(
                '_get_line returned excess bytes, but this mediumrequest '
                'cannot handle excess. (%r)' % (excess,))
        return line

    def _finished_reading(self):
        """See SmartClientMediumRequest._finished_reading."""
        pass

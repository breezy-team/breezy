# Copyright (C) 2005-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Base implementation of Transport over http.

There are separate implementation modules for each http client implementation.
"""

from __future__ import absolute_import

import os
import re
import sys
import weakref

from ... import (
    debug,
    errors,
    transport,
    ui,
    urlutils,
    )
from ...bzr.smart import medium
from ...trace import mutter
from ...transport import (
    ConnectedTransport,
    )

# TODO: handle_response should be integrated into the http/__init__.py
from .response import handle_response
from ._urllib2_wrappers import (
    Opener,
    Request,
    )


class HttpTransport(ConnectedTransport):
    """HTTP Client implementations.

    The protocol can be given as e.g. http+urllib://host/ to use a particular
    implementation.
    """

    # _unqualified_scheme: "http" or "https"
    # _scheme: may have "+pycurl", etc

    # In order to debug we have to issue our traces in sync with
    # httplib, which use print :(
    _debuglevel = 0

    _opener_class = Opener

    def __init__(self, base, _from_transport=None, ca_certs=None):
        """Set the base path where files will be stored."""
        proto_match = re.match(r'^(https?)(\+\w+)?://', base)
        if not proto_match:
            raise AssertionError("not a http url: %r" % base)
        self._unqualified_scheme = proto_match.group(1)
        super(HttpTransport, self).__init__(
            base, _from_transport=_from_transport)
        self._medium = None
        # range hint is handled dynamically throughout the life
        # of the transport object. We start by trying multi-range
        # requests and if the server returns bogus results, we
        # retry with single range requests and, finally, we
        # forget about range if the server really can't
        # understand. Once acquired, this piece of info is
        # propagated to clones.
        if _from_transport is not None:
            self._range_hint = _from_transport._range_hint
            self._opener = _from_transport._opener
        else:
            self._range_hint = 'multi'
            self._opener = self._opener_class(
                report_activity=self._report_activity, ca_certs=ca_certs)

    def _perform(self, request):
        """Send the request to the server and handles common errors.

        :returns: urllib2 Response object
        """
        connection = self._get_connection()
        if connection is not None:
            # Give back shared info
            request.connection = connection
            (auth, proxy_auth) = self._get_credentials()
            # Clean the httplib.HTTPConnection pipeline in case the previous
            # request couldn't do it
            connection.cleanup_pipe()
        else:
            # First request, initialize credentials.
            # scheme and realm will be set by the _urllib2_wrappers.AuthHandler
            auth = self._create_auth()
            # Proxy initialization will be done by the first proxied request
            proxy_auth = dict()
        # Ensure authentication info is provided
        request.auth = auth
        request.proxy_auth = proxy_auth

        if self._debuglevel > 0:
            print('perform: %s base: %s, url: %s' % (request.method, self.base,
                                                     request.get_full_url()))
        response = self._opener.open(request)
        if self._get_connection() is not request.connection:
            # First connection or reconnection
            self._set_connection(request.connection,
                                 (request.auth, request.proxy_auth))
        else:
            # http may change the credentials while keeping the
            # connection opened
            self._update_credentials((request.auth, request.proxy_auth))

        code = response.code
        if (request.follow_redirections is False
                and code in (301, 302, 303, 307)):
            raise errors.RedirectRequested(request.get_full_url(),
                                           request.redirected_to,
                                           is_permanent=(code == 301))

        if request.redirected_to is not None:
            trace.mutter('redirected from: %s to: %s' % (request.get_full_url(),
                                                         request.redirected_to))

        return response

    def disconnect(self):
        connection = self._get_connection()
        if connection is not None:
            connection.close()

    def has(self, relpath):
        """Does the target location exist?
        """
        response = self._head(relpath)

        code = response.code
        if code == 200:  # "ok",
            return True
        else:
            return False

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        code, response_file = self._get(relpath, None)
        return response_file

    def _get(self, relpath, offsets, tail_amount=0):
        """Get a file, or part of a file.

        :param relpath: Path relative to transport base URL
        :param offsets: None to get the whole file;
            or  a list of _CoalescedOffset to fetch parts of a file.
        :param tail_amount: The amount to get from the end of the file.

        :returns: (http_code, result_file)
        """
        abspath = self._remote_path(relpath)
        headers = {}
        accepted_errors = [200, 404]
        if offsets or tail_amount:
            range_header = self._attempted_range_header(offsets, tail_amount)
            if range_header is not None:
                accepted_errors.append(206)
                accepted_errors.append(400)
                accepted_errors.append(416)
                bytes = 'bytes=' + range_header
                headers = {'Range': bytes}

        request = Request('GET', abspath, None, headers,
                          accepted_errors=accepted_errors)
        response = self._perform(request)

        code = response.code
        if code == 404:  # not found
            raise errors.NoSuchFile(abspath)
        elif code in (400, 416):
            # We don't know which, but one of the ranges we specified was
            # wrong.
            raise errors.InvalidHttpRange(abspath, range_header,
                                          'Server return code %d' % code)

        data = handle_response(abspath, code, response.info(), response)
        return code, data

    def _remote_path(self, relpath):
        """See ConnectedTransport._remote_path.

        user and passwords are not embedded in the path provided to the server.
        """
        url = self._parsed_url.clone(relpath)
        url.user = url.quoted_user = None
        url.password = url.quoted_password = None
        url.scheme = self._unqualified_scheme
        return str(url)

    def _create_auth(self):
        """Returns a dict containing the credentials provided at build time."""
        auth = dict(host=self._parsed_url.host, port=self._parsed_url.port,
                    user=self._parsed_url.user, password=self._parsed_url.password,
                    protocol=self._unqualified_scheme,
                    path=self._parsed_url.path)
        return auth

    def get_smart_medium(self):
        """See Transport.get_smart_medium."""
        if self._medium is None:
            # Since medium holds some state (smart server probing at least), we
            # need to keep it around. Note that this is needed because medium
            # has the same 'base' attribute as the transport so it can't be
            # shared between transports having different bases.
            self._medium = SmartClientHTTPMedium(self)
        return self._medium

    def _degrade_range_hint(self, relpath, ranges):
        if self._range_hint == 'multi':
            self._range_hint = 'single'
            mutter('Retry "%s" with single range request' % relpath)
        elif self._range_hint == 'single':
            self._range_hint = None
            mutter('Retry "%s" without ranges' % relpath)
        else:
            # We tried all the tricks, but nothing worked, caller must reraise.
            return False
        return True

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
            if 'http' in debug.debug_flags:
                mutter('http readv of %s  offsets => %s collapsed %s',
                       relpath, len(offsets), len(coalesced))

            # Cache the data read, but only until it's been used
            data_map = {}
            # We will iterate on the data received from the GET requests and
            # serve the corresponding offsets respecting the initial order. We
            # need an offset iterator for that.
            iter_offsets = iter(offsets)
            try:
                cur_offset_and_size = next(iter_offsets)
            except StopIteration:
                return

            try:
                for cur_coal, rfile in self._coalesce_readv(relpath, coalesced):
                    # Split the received chunk
                    for offset, size in cur_coal.ranges:
                        start = cur_coal.start + offset
                        rfile.seek(start, os.SEEK_SET)
                        data = rfile.read(size)
                        data_len = len(data)
                        if data_len != size:
                            raise errors.ShortReadvError(relpath, start, size,
                                                         actual=data_len)
                        if (start, size) == cur_offset_and_size:
                            # The offset requested are sorted as the coalesced
                            # ones, no need to cache. Win !
                            yield cur_offset_and_size[0], data
                            try:
                                cur_offset_and_size = next(iter_offsets)
                            except StopIteration:
                                return
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
                        try:
                            cur_offset_and_size = next(iter_offsets)
                        except StopIteration:
                            return

            except (errors.ShortReadvError, errors.InvalidRange,
                    errors.InvalidHttpRange, errors.HttpBoundaryMissing) as e:
                mutter('Exception %r: %s during http._readv', e, e)
                if (not isinstance(e, errors.ShortReadvError)
                        or retried_offset == cur_offset_and_size):
                    # We don't degrade the range hint for ShortReadvError since
                    # they do not indicate a problem with the server ability to
                    # handle ranges. Except when we fail to get back a required
                    # offset twice in a row. In that case, falling back to
                    # single range or whole file should help.
                    if not self._degrade_range_hint(relpath, coalesced):
                        raise
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
                     and cumul + coal.length > self._get_max_size) or
                        len(ranges) >= max_ranges):
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
        abspath = self._remote_path('.bzr/smart')
        # We include 403 in accepted_errors so that send_http_smart_request can
        # handle a 403.  Otherwise a 403 causes an unhandled TransportError.
        response = self._perform(
            Request('POST', abspath, body_bytes,
                    {'Content-Type': 'application/octet-stream'},
                    accepted_errors=[200, 403]))
        code = response.code
        data = handle_response(abspath, code, response.info(), response)
        return code, data

    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._remote_path(relpath)
        request = Request('HEAD', abspath,
                          accepted_errors=[200, 404])
        response = self._perform(request)

        return response

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
        if isinstance(other, HttpTransport):
            raise errors.TransportNotPossible(
                'http cannot be the target of copy_to()')
        else:
            return super(HttpTransport, self).\
                copy_to(relpaths, other, mode=mode, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise errors.TransportNotPossible('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise errors.TransportNotPossible('http does not support delete()')

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        # HTTP URL's are externally usable as long as they don't mention their
        # implementation qualifier
        url = self._parsed_url.clone()
        url.scheme = self._unqualified_scheme
        return str(url)

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

    def _redirected_to(self, source, target):
        """Returns a transport suitable to re-issue a redirected request.

        :param source: The source url as returned by the server.
        :param target: The target url as returned by the server.

        The redirection can be handled only if the relpath involved is not
        renamed by the redirection.

        :returns: A transport or None.
        """
        parsed_source = self._split_url(source)
        parsed_target = self._split_url(target)
        pl = len(self._parsed_url.path)
        # determine the excess tail - the relative path that was in
        # the original request but not part of this transports' URL.
        excess_tail = parsed_source.path[pl:].strip("/")
        if not parsed_target.path.endswith(excess_tail):
            # The final part of the url has been renamed, we can't handle the
            # redirection.
            return None

        target_path = parsed_target.path
        if excess_tail:
            # Drop the tail that was in the redirect but not part of
            # the path of this transport.
            target_path = target_path[:-len(excess_tail)]

        if parsed_target.scheme in ('http', 'https'):
            # Same protocol family (i.e. http[s]), we will preserve the same
            # http client implementation when a redirection occurs from one to
            # the other (otherwise users may be surprised that bzr switches
            # from one implementation to the other, and devs may suffer
            # debugging it).
            if (parsed_target.scheme == self._unqualified_scheme
                and parsed_target.host == self._parsed_url.host
                and parsed_target.port == self._parsed_url.port
                and (parsed_target.user is None or
                     parsed_target.user == self._parsed_url.user)):
                # If a user is specified, it should match, we don't care about
                # passwords, wrong passwords will be rejected anyway.
                return self.clone(target_path)
            else:
                # Rebuild the url preserving the scheme qualification and the
                # credentials (if they don't apply, the redirected to server
                # will tell us, but if they do apply, we avoid prompting the
                # user)
                redir_scheme = parsed_target.scheme
                new_url = self._unsplit_url(redir_scheme,
                                            self._parsed_url.user,
                                            self._parsed_url.password,
                                            parsed_target.host, parsed_target.port,
                                            target_path)
                return transport.get_transport_from_url(new_url)
        else:
            # Redirected to a different protocol
            new_url = self._unsplit_url(parsed_target.scheme,
                                        parsed_target.user,
                                        parsed_target.password,
                                        parsed_target.host, parsed_target.port,
                                        target_path)
            return transport.get_transport_from_url(new_url)


# TODO: May be better located in smart/medium.py with the other
# SmartMedium classes
class SmartClientHTTPMedium(medium.SmartClientMedium):

    def __init__(self, http_transport):
        super(SmartClientHTTPMedium, self).__init__(http_transport.base)
        # We don't want to create a circular reference between the http
        # transport and its associated medium. Since the transport will live
        # longer than the medium, the medium keep only a weak reference to its
        # transport.
        self._http_transport_ref = weakref.ref(http_transport)

    def get_request(self):
        return SmartClientHTTPMediumRequest(self)

    def should_probe(self):
        return True

    def remote_path_from_transport(self, transport):
        # Strip the optional 'bzr+' prefix from transport so it will have the
        # same scheme as self.
        transport_base = transport.base
        if transport_base.startswith('bzr+'):
            transport_base = transport_base[4:]
        rel_url = urlutils.relative_url(self.base, transport_base)
        return urlutils.unquote(rel_url)

    def send_http_smart_request(self, bytes):
        try:
            # Get back the http_transport hold by the weak reference
            t = self._http_transport_ref()
            code, body_filelike = t._post(bytes)
            if code != 200:
                raise errors.InvalidHttpResponse(
                    t._remote_path('.bzr/smart'),
                    'Expected 200 response code, got %r' % (code,))
        except (errors.InvalidHttpResponse, errors.ConnectionReset) as e:
            raise errors.SmartProtocolError(str(e))
        return body_filelike

    def _report_activity(self, bytes, direction):
        """See SmartMedium._report_activity.

        Does nothing; the underlying plain HTTP transport will report the
        activity that this medium would report.
        """
        pass

    def disconnect(self):
        """See SmartClientMedium.disconnect()."""
        t = self._http_transport_ref()
        t.disconnect()


# TODO: May be better located in smart/medium.py with the other
# SmartMediumRequest classes
class SmartClientHTTPMediumRequest(medium.SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an HTTP medium."""

    def __init__(self, client_medium):
        medium.SmartClientMediumRequest.__init__(self, client_medium)
        self._buffer = b''

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
        if excess != b'':
            raise AssertionError(
                '_get_line returned excess bytes, but this mediumrequest '
                'cannot handle excess. (%r)' % (excess,))
        return line

    def _finished_reading(self):
        """See SmartClientMediumRequest._finished_reading."""
        pass


def unhtml_roughly(maybe_html, length_limit=1000):
    """Very approximate html->text translation, for presenting error bodies.

    :param length_limit: Truncate the result to this many characters.

    >>> unhtml_roughly("<b>bad</b> things happened\\n")
    ' bad  things happened '
    """
    return re.subn(r"(<[^>]*>|\n|&nbsp;)", " ", maybe_html)[0][:length_limit]


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import (
        features,
        http_server,
        )
    permutations = [(HttpTransport, http_server.HttpServer), ]
    if features.HTTPSServerFeature.available():
        from breezy.tests import (
            https_server,
            ssl_certs,
            )

        class HTTPS_transport(HttpTransport):

            def __init__(self, base, _from_transport=None):
                super(HTTPS_transport, self).__init__(
                    base, _from_transport=_from_transport,
                    ca_certs=ssl_certs.build_path('ca.crt'))

        permutations.append((HTTPS_transport,
                             https_server.HTTPSServer))
    return permutations

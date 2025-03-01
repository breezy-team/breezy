# Copyright (C) 2006-2011 Canonical Ltd
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

"""Handlers for HTTP Responses.

The purpose of these classes is to provide a uniform interface for clients
to standard HTTP responses, single range responses and multipart range
responses.
"""

import email.utils as email_utils
import http.client as http_client
import os
from io import BytesIO

from ... import errors, osutils


class ResponseFile:
    """A wrapper around the http socket containing the result of a GET request.

    Only read() and seek() (forward) are supported.

    """

    def __init__(self, path, infile):
        """Constructor.

        :param path: File url, for error reports.

        :param infile: File-like socket set at body start.
        """
        self._path = path
        self._file = infile
        self._pos = 0

    def close(self):
        """Close this file.

        Dummy implementation for consistency with the 'file' API.
        """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False  # propogate exceptions.

    def read(self, size=None):
        """Read size bytes from the current position in the file.

        :param size:  The number of bytes to read.  Leave unspecified or pass
            -1 to read to EOF.
        """
        data = self._file.read(size)
        self._pos += len(data)
        return data

    def readline(self):
        data = self._file.readline()
        self._pos += len(data)
        return data

    def readlines(self, size=None):
        data = self._file.readlines()
        self._pos += sum(map(len, data))
        return data

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                return
            yield line

    def tell(self):
        return self._pos

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            if offset < self._pos:
                raise AssertionError(
                    "Can't seek backwards, pos: {}, offset: {}".format(self._pos, offset)
                )
            to_discard = offset - self._pos
        elif whence == os.SEEK_CUR:
            to_discard = offset
        else:
            raise AssertionError("Can't seek backwards")
        if to_discard:
            # Just discard the unwanted bytes
            self.read(to_discard)


# A RangeFile expects the following grammar (simplified to outline the
# assumptions we rely upon).

# file: single_range
#     | multiple_range

# single_range: content_range_header data

# multiple_range: boundary_header boundary (content_range_header data boundary)+


class RangeFile(ResponseFile):
    """File-like object that allow access to partial available data.

    All accesses should happen sequentially since the acquisition occurs during
    an http response reception (as sockets can't be seeked, we simulate the
    seek by just reading and discarding the data).

    The access pattern is defined by a set of ranges discovered as reading
    progress. Only one range is available at a given time, so all accesses
    should happen with monotonically increasing offsets.
    """

    # in _checked_read() below, we may have to discard several MB in the worst
    # case. To avoid buffering that much, we read and discard by chunks
    # instead. The underlying file is either a socket or a BytesIO, so reading
    # 8k chunks should be fine.
    _discarded_buf_size = 8192

    # maximum size of read requests -- used to avoid MemoryError issues in recv
    _max_read_size = 512 * 1024

    def __init__(self, path, infile):
        """Constructor.

        :param path: File url, for error reports.

        :param infile: File-like socket set at body start.
        """
        super().__init__(path, infile)
        self._boundary = None
        # When using multi parts response, this will be set with the headers
        # associated with the range currently read.
        self._headers = None
        # Default to the whole file of unspecified size
        self.set_range(0, -1)

    def set_range(self, start, size):
        """Change the range mapping."""
        self._start = start
        self._size = size
        # Set the new _pos since that's what we want to expose
        self._pos = self._start

    def set_boundary(self, boundary):
        """Define the boundary used in a multi parts message.

        The file should be at the beginning of the body, the first range
        definition is read and taken into account.
        """
        if not isinstance(boundary, bytes):
            raise TypeError(boundary)
        self._boundary = boundary
        # Decode the headers and setup the first range
        self.read_boundary()
        self.read_range_definition()

    def read_boundary(self):
        """Read the boundary headers defining a new range."""
        boundary_line = b"\r\n"
        while boundary_line == b"\r\n":
            # RFC2616 19.2 Additional CRLFs may precede the first boundary
            # string entity.
            # To be on the safe side we allow it before any boundary line
            boundary_line = self._file.readline()

        if boundary_line == b"":
            # A timeout in the proxy server caused the response to end early.
            # See launchpad bug 198646.
            raise errors.HttpBoundaryMissing(self._path, self._boundary)

        if boundary_line != b"--" + self._boundary + b"\r\n":
            # email_utils.unquote() incorrectly unquotes strings enclosed in <>
            # IIS 6 and 7 incorrectly wrap boundary strings in <>
            # together they make a beautiful bug, which we will be gracious
            # about here
            if (
                self._unquote_boundary(boundary_line)
                != b"--" + self._boundary + b"\r\n"
            ):
                raise errors.InvalidHttpResponse(
                    self._path,
                    "Expected a boundary ({}) line, got '{}'".format(self._boundary, boundary_line),
                )

    def _unquote_boundary(self, b):
        return (
            b[:2]
            + email_utils.unquote(b[2:-2].decode("ascii")).encode("ascii")
            + b[-2:]
        )

    def read_range_definition(self):
        """Read a new range definition in a multi parts message.

        Parse the headers including the empty line following them so that we
        are ready to read the data itself.
        """
        self._headers = http_client.parse_headers(self._file)
        # Extract the range definition
        content_range = self._headers.get("content-range", None)
        if content_range is None:
            raise errors.InvalidHttpResponse(
                self._path,
                "Content-Range header missing in a multi-part response",
                headers=self._headers,
            )
        self.set_range_from_header(content_range)

    def set_range_from_header(self, content_range):
        """Helper to set the new range from its description in the headers."""
        try:
            rtype, values = content_range.split()
        except ValueError:
            raise errors.InvalidHttpRange(self._path, content_range, "Malformed header")
        if rtype != "bytes":
            raise errors.InvalidHttpRange(
                self._path, content_range, "Unsupported range type '{}'".format(rtype)
            )
        try:
            # We don't need total, but note that it may be either the file size
            # or '*' if the server can't or doesn't want to return the file
            # size.
            start_end, total = values.split("/")
            start, end = start_end.split("-")
            start = int(start)
            end = int(end)
        except ValueError:
            raise errors.InvalidHttpRange(
                self._path, content_range, "Invalid range values"
            )
        size = end - start + 1
        if size <= 0:
            raise errors.InvalidHttpRange(
                self._path, content_range, "Invalid range, size <= 0"
            )
        self.set_range(start, size)

    def _checked_read(self, size):
        """Read the file checking for short reads.

        The data read is discarded along the way.
        """
        pos = self._pos
        remaining = size
        while remaining > 0:
            data = self._file.read(min(remaining, self._discarded_buf_size))
            remaining -= len(data)
            if not data:
                raise errors.ShortReadvError(self._path, pos, size, size - remaining)
        self._pos += size

    def _seek_to_next_range(self):
        # We will cross range boundaries
        if self._boundary is None:
            # If we don't have a boundary, we can't find another range
            raise errors.InvalidRange(
                self._path,
                self._pos,
                "Range ({}, {}) exhausted".format(self._start, self._size),
            )
        self.read_boundary()
        self.read_range_definition()

    def read(self, size=-1):
        """Read size bytes from the current position in the file.

        Reading across ranges is not supported. We rely on the underlying http
        client to clean the socket if we leave bytes unread. This may occur for
        the final boundary line of a multipart response or for any range
        request not entirely consumed by the client (due to offset coalescing)

        :param size:  The number of bytes to read.  Leave unspecified or pass
            -1 to read to EOF.
        """
        if self._size > 0 and self._pos == self._start + self._size:
            if size == 0:
                return b""
            else:
                self._seek_to_next_range()
        elif self._pos < self._start:
            raise errors.InvalidRange(
                self._path,
                self._pos,
                "Can't read {} bytes before range ({}, {})".format(size, self._start, self._size),
            )
        if self._size > 0:
            if size > 0 and self._pos + size > self._start + self._size:
                raise errors.InvalidRange(
                    self._path,
                    self._pos,
                    "Can't read {} bytes across range ({}, {})".format(size, self._start, self._size),
                )

        # read data from file
        buf = BytesIO()
        limited = size
        if self._size > 0:
            # Don't read past the range definition
            limited = self._start + self._size - self._pos
            if size >= 0:
                limited = min(limited, size)
        osutils.pumpfile(self._file, buf, limited, self._max_read_size)
        data = buf.getvalue()

        # Update _pos respecting the data effectively read
        self._pos += len(data)
        return data

    def seek(self, offset, whence=0):
        start_pos = self._pos
        if whence == 0:
            final_pos = offset
        elif whence == 1:
            final_pos = start_pos + offset
        elif whence == 2:
            if self._size > 0:
                final_pos = self._start + self._size + offset  # offset < 0
            else:
                raise errors.InvalidRange(
                    self._path,
                    self._pos,
                    "RangeFile: can't seek from end while size is unknown",
                )
        else:
            raise ValueError("Invalid value {} for whence.".format(whence))

        if final_pos < self._pos:
            # Can't seek backwards
            raise errors.InvalidRange(
                self._path,
                self._pos,
                "RangeFile: trying to seek backwards to {}".format(final_pos),
            )

        if self._size > 0:
            cur_limit = self._start + self._size
            while final_pos > cur_limit:
                # We will cross range boundaries
                remain = cur_limit - self._pos
                if remain > 0:
                    # Finish reading the current range
                    self._checked_read(remain)
                self._seek_to_next_range()
                cur_limit = self._start + self._size

        size = final_pos - self._pos
        if size > 0:  # size can be < 0 if we crossed a range boundary
            # We don't need the data, just read it and throw it away
            self._checked_read(size)

    def tell(self):
        return self._pos


def handle_response(url, code, getheader, data):
    """Interpret the code & headers and wrap the provided data in a RangeFile.

    This is a factory method which returns an appropriate RangeFile based on
    the code & headers it's given.

    :param url: The url being processed. Mostly for error reporting
    :param code: The integer HTTP response code
    :param getheader: Function for retrieving header
    :param data: A file-like object that can be read() to get the
                 requested data
    :return: A file-like object that can seek()+read() the
             ranges indicated by the headers.
    """
    if code == 200:
        # A whole file
        rfile = ResponseFile(url, data)
    elif code == 206:
        rfile = RangeFile(url, data)
        # When there is no content-type header we treat the response as
        # being of type 'application/octet-stream' as per RFC2616 section
        # 7.2.1.
        # Therefore it is obviously not multipart
        content_type = getheader("content-type", "application/octet-stream")
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["content-type"] = content_type
        params = msg["content-type"].params
        mimetype = msg.get_content_type()
        if mimetype == "multipart/byteranges":
            rfile.set_boundary(params["boundary"].encode("ascii"))
        else:
            # A response to a range request, but not multipart
            content_range = getheader("content-range", None)
            if content_range is None:
                raise errors.InvalidHttpResponse(
                    url, "Missing the Content-Range header in a 206 range response"
                )
            rfile.set_range_from_header(content_range)
    else:
        raise errors.UnexpectedHttpStatus(url, code)

    return rfile

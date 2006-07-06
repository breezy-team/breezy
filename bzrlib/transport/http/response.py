# Copyright (C) 2006 Michael Ellerman
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

"""Handlers for HTTP Responses.

The purpose of these classes is to provide a uniform interface for clients
to standard HTTP responses, single range responses and multipart range
responses.
"""


from bisect import bisect
import re

from bzrlib import errors
from bzrlib.trace import mutter


class ResponseRange(object):
    """A range in a RangeFile-object."""

    __slots__ = ['_ent_start', '_ent_end', '_data_start']

    def __init__(self, ent_start, ent_end, data_start):
        self._ent_start = ent_start
        self._ent_end = ent_end
        self._data_start = data_start

    def __cmp__(self, other):
        """Compare this to other.

        We need this both for sorting, and so that we can
        bisect the list of ranges.
        """
        if isinstance(other, int):
            # Later on we bisect for a starting point
            # so we allow comparing against a single integer
            return cmp(self._ent_start, other)
        else:
            return cmp((self._ent_start, self._ent_end, self._data_start),
                       (other._ent_start, other._ent_end, other._data_start))

    def __str__(self):
        return "%s(%s-%s,%s)" % (self.__class__.__name__,
                                 self._ent_start, self._ent_end,
                                 self._data_start)


class RangeFile(object):
    """File-like object that allow access to partial available data.

    Specified by a set of ranges.
    """

    def __init__(self, path, input_file):
        self._path = path
        self._pos = 0
        self._len = 0
        self._ranges = []
        self._data = input_file.read()

    def _add_range(self, ent_start, ent_end, data_start):
        """Add an entity range.

        :param ent_start: Start offset of entity
        :param ent_end: End offset of entity (inclusive)
        :param data_start: Start offset of data in data stream.
        """
        self._ranges.append(ResponseRange(ent_start, ent_end, data_start))
        self._len = max(self._len, ent_end)

    def _finish_ranges(self):
        self._ranges.sort()

    def read(self, size):
        """Read size bytes from the current position in the file.

        Reading across ranges is not supported.
        """
        # find the last range which has a start <= pos
        i = bisect(self._ranges, self._pos) - 1

        if i < 0 or self._pos > self._ranges[i]._ent_end:
            raise errors.InvalidRange(self._path, self._pos)

        r = self._ranges[i]

        mutter('found range %s %s for pos %s', i, self._ranges[i], self._pos)

        if (self._pos + size - 1) > r._ent_end:
            raise errors.InvalidRange(self._path, self._pos)

        start = r._data_start + (self._pos - r._ent_start)
        end   = start + size
        mutter("range read %d bytes at %d == %d-%d", size, self._pos,
                start, end)
        self._pos += (end-start)
        return self._data[start:end]

    def seek(self, offset, whence=0):
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            self._pos = self._len + offset
        else:
            raise ValueError("Invalid value %s for whence." % whence)

        if self._pos < 0:
            self._pos = 0

    def tell(self):
        return self._pos


class HttpRangeResponse(RangeFile):
    """A single-range HTTP response."""

    CONTENT_RANGE_RE = re.compile(
        '\s*([^\s]+)\s+([0-9]+)-([0-9]+)/([0-9]+)\s*$')

    def __init__(self, path, content_range, input_file):
        mutter("parsing 206 non-multipart response for %s", path)
        RangeFile.__init__(self, path, input_file)
        start, end = self._parse_range(content_range)
        self._add_range(start, end, 0)
        self._finish_ranges()

    def _parse_range(self, range):
        """Parse an http Content-range header and return start + end"""
        match = self.CONTENT_RANGE_RE.match(range)
        if not match:
            raise errors.InvalidHttpRange(self._path, range,
                                          "Invalid Content-range")

        rtype, start, end, total = match.groups()

        if rtype != 'bytes':
            raise errors.InvalidHttpRange(self._path, range,
                    "Unsupported range type '%s'" % (rtype,))

        try:
            start = int(start)
            end = int(end)
        except ValueError, e:
            raise errors.InvalidHttpRange(self._path, range, str(e))

        return start, end


class HttpMultipartRangeResponse(HttpRangeResponse):
    """A multi-range HTTP response."""

    CONTENT_TYPE_RE = re.compile(
        '^\s*multipart/byteranges\s*;\s*boundary\s*=\s*(.*)\s*$')

    BOUNDARY_PATT = \
        "^--%s(?:\r\n(?:(?:content-range:([^\r]+))|[^\r]+))+\r\n\r\n"

    def __init__(self, path, content_type, input_file):
        mutter("parsing 206 multipart response for %s", path)
        RangeFile.__init__(self, path, input_file)

        self._parse_boundary(content_type)

        for match in self.BOUNDARY_RE.finditer(self._data):
            ent_start, ent_end = self._parse_range(match.group(1))
            self._add_range(ent_start, ent_end, match.end())

        self._finish_ranges()

    def _parse_boundary(self, ctype):
        match = self.CONTENT_TYPE_RE.match(ctype)
        if not match:
            raise TransportError("Invalid Content-type (%s) in HTTP multipart"
                                 "response for %s!" % (ctype, self._path))

        boundary = match.group(1)
        mutter('multipart boundary is %s', boundary)
        self.BOUNDARY_RE = re.compile(self.BOUNDARY_PATT % re.escape(boundary),
                                      re.IGNORECASE | re.MULTILINE)

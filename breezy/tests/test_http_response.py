# Copyright (C) 2006-2010, 2012, 2013, 2016 Canonical Ltd
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

"""Tests from HTTP response parsing.

The handle_response method read the response body of a GET request an returns
the corresponding RangeFile.

There are four different kinds of RangeFile:
- a whole file whose size is unknown, seen as a simple byte stream,
- a whole file whose size is known, we can't read past its end,
- a single range file, a part of a file with a start and a size,
- a multiple range file, several consecutive parts with known start offset
  and size.

Some properties are common to all kinds:
- seek can only be forward (its really a socket underneath),
- read can't cross ranges,
- successive ranges are taken into account transparently,

- the expected pattern of use is either seek(offset)+read(size) or a single
  read with no size specified. For multiple range files, multiple read() will
  return the corresponding ranges, trying to read further will raise
  InvalidHttpResponse.
"""

import http.client as http_client
from io import BytesIO

parse_headers = http_client.parse_headers

from .. import errors, tests
from ..transport.http import response, urllib
from .file_utils import FakeReadFile


class ReadSocket:
    """A socket-like object that can be given a predefined content."""

    def __init__(self, data):
        self.readfile = BytesIO(data)

    def makefile(self, mode="r", bufsize=None):
        return self.readfile


class FakeHTTPConnection(urllib.HTTPConnection):
    def __init__(self, sock):
        urllib.HTTPConnection.__init__(self, "localhost")
        # Set the socket to bypass the connection
        self.sock = sock

    def send(self, str):
        """Ignores the writes on the socket."""
        pass


class TestResponseFileIter(tests.TestCase):
    def test_iter_empty(self):
        f = response.ResponseFile("empty", BytesIO())
        self.assertEqual([], list(f))

    def test_iter_many(self):
        f = response.ResponseFile("many", BytesIO(b"0\n1\nboo!\n"))
        self.assertEqual([b"0\n", b"1\n", b"boo!\n"], list(f))

    def test_readlines(self):
        f = response.ResponseFile("many", BytesIO(b"0\n1\nboo!\n"))
        self.assertEqual([b"0\n", b"1\n", b"boo!\n"], f.readlines())


class TestHTTPConnection(tests.TestCase):
    def test_cleanup_pipe(self):
        sock = ReadSocket(b"""HTTP/1.1 200 OK\r
Content-Type: text/plain; charset=UTF-8\r
Content-Length: 18
\r
0123456789
garbage""")
        conn = FakeHTTPConnection(sock)
        # Simulate the request sending so that the connection will be able to
        # read the response.
        conn.putrequest("GET", "http://localhost/fictious")
        conn.endheaders()
        # Now, get the response
        resp = conn.getresponse()
        # Read part of the response
        self.assertEqual(b"0123456789\n", resp.read(11))
        # Override the thresold to force the warning emission
        conn._range_warning_thresold = 6  # There are 7 bytes pending
        conn.cleanup_pipe()
        self.assertContainsRe(self.get_log(), "Got a 200 response when asking")


class TestRangeFileMixin:
    """Tests for accessing the first range in a RangeFile."""

    # A simple string used to represent a file part (also called a range), in
    # which offsets are easy to calculate for test writers. It's used as a
    # building block with slight variations but basically 'a' is the first char
    # of the range and 'z' is the last.
    alpha = b"abcdefghijklmnopqrstuvwxyz"

    def test_can_read_at_first_access(self):
        """Test that the just created file can be read."""
        self.assertEqual(self.alpha, self._file.read())

    def test_seek_read(self):
        """Test seek/read inside the range."""
        f = self._file
        start = self.first_range_start
        # Before any use, tell() should be at the range start
        self.assertEqual(start, f.tell())
        cur = start  # For an overall offset assertion
        f.seek(start + 3)
        cur += 3
        self.assertEqual(b"def", f.read(3))
        cur += len("def")
        f.seek(4, 1)
        cur += 4
        self.assertEqual(b"klmn", f.read(4))
        cur += len("klmn")
        # read(0) in the middle of a range
        self.assertEqual(b"", f.read(0))
        # seek in place
        here = f.tell()
        f.seek(0, 1)
        self.assertEqual(here, f.tell())
        self.assertEqual(cur, f.tell())

    def test_read_zero(self):
        f = self._file
        self.assertEqual(b"", f.read(0))
        f.seek(10, 1)
        self.assertEqual(b"", f.read(0))

    def test_seek_at_range_end(self):
        f = self._file
        f.seek(26, 1)

    def test_read_at_range_end(self):
        """Test read behaviour at range end."""
        f = self._file
        self.assertEqual(self.alpha, f.read())
        self.assertEqual(b"", f.read(0))
        self.assertRaises(errors.InvalidRange, f.read, 1)

    def test_unbounded_read_after_seek(self):
        f = self._file
        f.seek(24, 1)
        # Should not cross ranges
        self.assertEqual(b"yz", f.read())

    def test_seek_backwards(self):
        f = self._file
        start = self.first_range_start
        f.seek(start)
        f.read(12)
        self.assertRaises(errors.InvalidRange, f.seek, start + 5)

    def test_seek_outside_single_range(self):
        f = self._file
        if f._size == -1 or f._boundary is not None:
            raise tests.TestNotApplicable("Needs a fully defined range")
        # Will seek past the range and then errors out
        self.assertRaises(errors.InvalidRange, f.seek, self.first_range_start + 27)

    def test_read_past_end_of_range(self):
        f = self._file
        if f._size == -1:
            raise tests.TestNotApplicable("Can't check an unknown size")
        start = self.first_range_start
        f.seek(start + 20)
        self.assertRaises(errors.InvalidRange, f.read, 10)

    def test_seek_from_end(self):
        """Test seeking from the end of the file.

        The semantic is unclear in case of multiple ranges. Seeking from end
        exists only for the http transports, cannot be used if the file size is
        unknown and is not used in breezy itself. This test must be (and is)
        overridden by daughter classes.

        Reading from end makes sense only when a range has been requested from
        the end of the file (see HttpTransportBase._get() when using the
        'tail_amount' parameter). The HTTP response can only be a whole file or
        a single range.
        """
        f = self._file
        f.seek(-2, 2)
        self.assertEqual(b"yz", f.read())


class TestRangeFileSizeUnknown(tests.TestCase, TestRangeFileMixin):
    """Test a RangeFile for a whole file whose size is not known."""

    def setUp(self):
        super().setUp()
        self._file = response.RangeFile("Whole_file_size_known", BytesIO(self.alpha))
        # We define no range, relying on RangeFile to provide default values
        self.first_range_start = 0  # It's the whole file

    def test_seek_from_end(self):
        """See TestRangeFileMixin.test_seek_from_end.

        The end of the file can't be determined since the size is unknown.
        """
        self.assertRaises(errors.InvalidRange, self._file.seek, -1, 2)

    def test_read_at_range_end(self):
        """Test read behaviour at range end."""
        f = self._file
        self.assertEqual(self.alpha, f.read())
        self.assertEqual(b"", f.read(0))
        self.assertEqual(b"", f.read(1))


class TestRangeFileSizeKnown(tests.TestCase, TestRangeFileMixin):
    """Test a RangeFile for a whole file whose size is known."""

    def setUp(self):
        super().setUp()
        self._file = response.RangeFile("Whole_file_size_known", BytesIO(self.alpha))
        self._file.set_range(0, len(self.alpha))
        self.first_range_start = 0  # It's the whole file


class TestRangeFileSingleRange(tests.TestCase, TestRangeFileMixin):
    """Test a RangeFile for a single range."""

    def setUp(self):
        super().setUp()
        self._file = response.RangeFile("Single_range_file", BytesIO(self.alpha))
        self.first_range_start = 15
        self._file.set_range(self.first_range_start, len(self.alpha))

    def test_read_before_range(self):
        # This can't occur under normal circumstances, we have to force it
        f = self._file
        f._pos = 0  # Force an invalid pos
        self.assertRaises(errors.InvalidRange, f.read, 2)


class TestRangeFileMultipleRanges(tests.TestCase, TestRangeFileMixin):
    """Test a RangeFile for multiple ranges.

    The RangeFile used for the tests contains three ranges:

    - at offset 25: alpha
    - at offset 100: alpha
    - at offset 126: alpha.upper()

    The two last ranges are contiguous. This only rarely occurs (should not in
    fact) in real uses but may lead to hard to track bugs.
    """

    # The following is used to represent the boundary paramter defined
    # in HTTP response headers and the boundary lines that separate
    # multipart content.

    boundary = b"separation"

    def setUp(self):
        super().setUp()

        boundary = self.boundary

        content = b""
        self.first_range_start = 25
        file_size = 200  # big enough to encompass all ranges
        for start, part in [
            (self.first_range_start, self.alpha),
            # Two contiguous ranges
            (100, self.alpha),
            (126, self.alpha.upper()),
        ]:
            content += self._multipart_byterange(part, start, boundary, file_size)
        # Final boundary
        content += self._boundary_line()

        self._file = response.RangeFile("Multiple_ranges_file", BytesIO(content))
        self.set_file_boundary()

    def _boundary_line(self):
        """Helper to build the formatted boundary line."""
        return b"--" + self.boundary + b"\r\n"

    def set_file_boundary(self):
        # Ranges are set by decoding the range headers, the RangeFile user is
        # supposed to call the following before using seek or read since it
        # requires knowing the *response* headers (in that case the boundary
        # which is part of the Content-Type header).
        self._file.set_boundary(self.boundary)

    def _multipart_byterange(self, data, offset, boundary, file_size=b"*"):
        """Encode a part of a file as a multipart/byterange MIME type.

        When a range request is issued, the HTTP response body can be
        decomposed in parts, each one representing a range (start, size) in a
        file.

        :param data: The payload.
        :param offset: where data starts in the file
        :param boundary: used to separate the parts
        :param file_size: the size of the file containing the range (default to
            '*' meaning unknown)

        :return: a string containing the data encoded as it will appear in the
            HTTP response body.
        """
        bline = self._boundary_line()
        # Each range begins with a boundary line
        range = bline
        # A range is described by a set of headers, but only 'Content-Range' is
        # required for our implementation (TestHandleResponse below will
        # exercise ranges with multiple or missing headers')
        if isinstance(file_size, int):
            file_size = b"%d" % file_size
        range += b"Content-Range: bytes %d-%d/%s\r\n" % (
            offset,
            offset + len(data) - 1,
            file_size,
        )
        range += b"\r\n"
        # Finally the raw bytes
        range += data
        return range

    def test_read_all_ranges(self):
        f = self._file
        self.assertEqual(self.alpha, f.read())  # Read first range
        f.seek(100)  # Trigger the second range recognition
        self.assertEqual(self.alpha, f.read())  # Read second range
        self.assertEqual(126, f.tell())
        f.seek(126)  # Start of third range which is also the current pos !
        self.assertEqual(b"A", f.read(1))
        f.seek(10, 1)
        self.assertEqual(b"LMN", f.read(3))

    def test_seek_from_end(self):
        """See TestRangeFileMixin.test_seek_from_end."""
        # The actual implementation will seek from end for the first range only
        # and then fail. Since seeking from end is intended to be used for a
        # single range only anyway, this test just document the actual
        # behaviour.
        f = self._file
        f.seek(-2, 2)
        self.assertEqual(b"yz", f.read())
        self.assertRaises(errors.InvalidRange, f.seek, -2, 2)

    def test_seek_into_void(self):
        f = self._file
        start = self.first_range_start
        f.seek(start)
        # Seeking to a point between two ranges is possible (only once) but
        # reading there is forbidden
        f.seek(start + 40)
        # We crossed a range boundary, so now the file is positioned at the
        # start of the new range (i.e. trying to seek below 100 will error out)
        f.seek(100)
        f.seek(125)

    def test_seek_across_ranges(self):
        f = self._file
        f.seek(126)  # skip the two first ranges
        self.assertEqual(b"AB", f.read(2))

    def test_checked_read_dont_overflow_buffers(self):
        f = self._file
        # We force a very low value to exercise all code paths in _checked_read
        f._discarded_buf_size = 8
        f.seek(126)  # skip the two first ranges
        self.assertEqual(b"AB", f.read(2))

    def test_seek_twice_between_ranges(self):
        f = self._file
        start = self.first_range_start
        f.seek(start + 40)  # Past the first range but before the second
        # Now the file is positioned at the second range start (100)
        self.assertRaises(errors.InvalidRange, f.seek, start + 41)

    def test_seek_at_range_end(self):
        """Test seek behavior at range end."""
        f = self._file
        f.seek(25 + 25)
        f.seek(100 + 25)
        f.seek(126 + 25)

    def test_read_at_range_end(self):
        f = self._file
        self.assertEqual(self.alpha, f.read())
        self.assertEqual(self.alpha, f.read())
        self.assertEqual(self.alpha.upper(), f.read())
        self.assertRaises(errors.InvalidHttpResponse, f.read, 1)


class TestRangeFileMultipleRangesQuotedBoundaries(TestRangeFileMultipleRanges):
    """Perform the same tests as TestRangeFileMultipleRanges, but uses
    an angle-bracket quoted boundary string like IIS 6.0 and 7.0
    (but not IIS 5, which breaks the RFC in a different way
    by using square brackets, not angle brackets)

    This reveals a bug caused by

    - The bad implementation of RFC 822 unquoting in Python (angles are not
      quotes), coupled with

    - The bad implementation of RFC 2046 in IIS (angles are not permitted chars
      in boundary lines).

    """

    # The boundary as it appears in boundary lines
    # IIS 6 and 7 use this value
    _boundary_trimmed = b"q1w2e3r4t5y6u7i8o9p0zaxscdvfbgnhmjklkl"
    boundary = b"<" + _boundary_trimmed + b">"

    def set_file_boundary(self):
        # Emulate broken rfc822.unquote() here by removing angles
        self._file.set_boundary(self._boundary_trimmed)


class TestRangeFileVarious(tests.TestCase):
    """Tests RangeFile aspects not covered elsewhere."""

    def test_seek_whence(self):
        """Test the seek whence parameter values."""
        f = response.RangeFile("foo", BytesIO(b"abc"))
        f.set_range(0, 3)
        f.seek(0)
        f.seek(1, 1)
        f.seek(-1, 2)
        self.assertRaises(ValueError, f.seek, 0, 14)

    def test_range_syntax(self):
        """Test the Content-Range scanning."""
        f = response.RangeFile("foo", BytesIO())

        def ok(expected, header_value):
            f.set_range_from_header(header_value)
            # Slightly peek under the covers to get the size
            self.assertEqual(expected, (f.tell(), f._size))

        ok((1, 10), "bytes 1-10/11")
        ok((1, 10), "bytes 1-10/*")
        ok((12, 2), "\tbytes 12-13/*")
        ok((28, 1), "  bytes 28-28/*")
        ok((2123, 2120), "bytes  2123-4242/12310")
        ok((1, 10), "bytes 1-10/ttt")  # We don't check total (ttt)

        def nok(header_value):
            self.assertRaises(
                errors.InvalidHttpRange, f.set_range_from_header, header_value
            )

        nok("bytes 10-2/3")
        nok("chars 1-2/3")
        nok("bytes xx-yyy/zzz")
        nok("bytes xx-12/zzz")
        nok("bytes 11-yy/zzz")
        nok("bytes10-2/3")


# Taken from real request responses
_full_text_response = (
    200,
    b"""HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: 35\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
""",
    b"""Bazaar-NG meta directory, format 1
""",
)


_single_range_response = (
    206,
    b"""HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:45:22 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 100\r
Content-Range: bytes 100-199/93890\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
""",
    b"""mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e762""",
)


_single_range_no_content_type = (
    206,
    b"""HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:45:22 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 100\r
Content-Range: bytes 100-199/93890\r
Connection: close\r
\r
""",
    b"""mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e762""",
)


_multipart_range_response = (
    206,
    b"""HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:49:48 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 1534\r
Connection: close\r
Content-Type: multipart/byteranges; boundary=418470f848b63279b\r
\r
\r""",
    b"""--418470f848b63279b\r
Content-type: text/plain; charset=UTF-8\r
Content-range: bytes 0-254/93890\r
\r
mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e7627
mbp@sourcefrog.net-20050309040957-6cad07f466bb0bb8
mbp@sourcefrog.net-20050309041501-c840e09071de3b67
mbp@sourcefrog.net-20050309044615-c24a3250be83220a
\r
--418470f848b63279b\r
Content-type: text/plain; charset=UTF-8\r
Content-range: bytes 1000-2049/93890\r
\r
40-fd4ec249b6b139ab
mbp@sourcefrog.net-20050311063625-07858525021f270b
mbp@sourcefrog.net-20050311231934-aa3776aff5200bb9
mbp@sourcefrog.net-20050311231953-73aeb3a131c3699a
mbp@sourcefrog.net-20050311232353-f5e33da490872c6a
mbp@sourcefrog.net-20050312071639-0a8f59a34a024ff0
mbp@sourcefrog.net-20050312073432-b2c16a55e0d6e9fb
mbp@sourcefrog.net-20050312073831-a47c3335ece1920f
mbp@sourcefrog.net-20050312085412-13373aa129ccbad3
mbp@sourcefrog.net-20050313052251-2bf004cb96b39933
mbp@sourcefrog.net-20050313052856-3edd84094687cb11
mbp@sourcefrog.net-20050313053233-e30a4f28aef48f9d
mbp@sourcefrog.net-20050313053853-7c64085594ff3072
mbp@sourcefrog.net-20050313054757-a86c3f5871069e22
mbp@sourcefrog.net-20050313061422-418f1f73b94879b9
mbp@sourcefrog.net-20050313120651-497bd231b19df600
mbp@sourcefrog.net-20050314024931-eae0170ef25a5d1a
mbp@sourcefrog.net-20050314025438-d52099f915fe65fc
mbp@sourcefrog.net-20050314025539-637a636692c055cf
mbp@sourcefrog.net-20050314025737-55eb441f430ab4ba
mbp@sourcefrog.net-20050314025901-d74aa93bb7ee8f62
mbp@source\r
--418470f848b63279b--\r
""",
)


_multipart_squid_range_response = (
    206,
    b"""HTTP/1.0 206 Partial Content\r
Date: Thu, 31 Aug 2006 21:16:22 GMT\r
Server: Apache/2.2.2 (Unix) DAV/2\r
Last-Modified: Thu, 31 Aug 2006 17:57:06 GMT\r
Accept-Ranges: bytes\r
Content-Type: multipart/byteranges; boundary="squid/2.5.STABLE12:C99323425AD4FE26F726261FA6C24196"\r
Content-Length: 598\r
X-Cache: MISS from localhost.localdomain\r
X-Cache-Lookup: HIT from localhost.localdomain:3128\r
Proxy-Connection: keep-alive\r
\r
""",
    b"""\r
--squid/2.5.STABLE12:C99323425AD4FE26F726261FA6C24196\r
Content-Type: text/plain\r
Content-Range: bytes 0-99/18672\r
\r
# bzr knit index 8

scott@netsplit.com-20050708230047-47c7868f276b939f fulltext 0 863  :
scott@netsp\r
--squid/2.5.STABLE12:C99323425AD4FE26F726261FA6C24196\r
Content-Type: text/plain\r
Content-Range: bytes 300-499/18672\r
\r
com-20050708231537-2b124b835395399a :
scott@netsplit.com-20050820234126-551311dbb7435b51 line-delta 1803 479 .scott@netsplit.com-20050820232911-dc4322a084eadf7e :
scott@netsplit.com-20050821213706-c86\r
--squid/2.5.STABLE12:C99323425AD4FE26F726261FA6C24196--\r
""",
)


# This is made up
_full_text_response_no_content_type = (
    200,
    b"""HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: 35\r
Connection: close\r
\r
""",
    b"""Bazaar-NG meta directory, format 1
""",
)


_full_text_response_no_content_length = (
    200,
    b"""HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
""",
    b"""Bazaar-NG meta directory, format 1
""",
)


_single_range_no_content_range = (
    206,
    b"""HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:45:22 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 100\r
Connection: close\r
\r
""",
    b"""mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e762""",
)


_single_range_response_truncated = (
    206,
    b"""HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:45:22 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 100\r
Content-Range: bytes 100-199/93890\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
""",
    b"""mbp@sourcefrog.net-20050309040815-13242001617e4a06""",
)


_invalid_response = (
    444,
    b"""HTTP/1.1 444 Bad Response\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Connection: close\r
Content-Type: text/html; charset=iso-8859-1\r
\r
""",
    b"""<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>404 Not Found</title>
</head><body>
<h1>Not Found</h1>
<p>I don't know what I'm doing</p>
<hr>
</body></html>
""",
)


_multipart_no_content_range = (
    206,
    b"""HTTP/1.0 206 Partial Content\r
Content-Type: multipart/byteranges; boundary=THIS_SEPARATES\r
Content-Length: 598\r
\r
""",
    b"""\r
--THIS_SEPARATES\r
Content-Type: text/plain\r
\r
# bzr knit index 8
--THIS_SEPARATES\r
""",
)


_multipart_no_boundary = (
    206,
    b"""HTTP/1.0 206 Partial Content\r
Content-Type: multipart/byteranges; boundary=THIS_SEPARATES\r
Content-Length: 598\r
\r
""",
    b"""\r
--THIS_SEPARATES\r
Content-Type: text/plain\r
Content-Range: bytes 0-18/18672\r
\r
# bzr knit index 8

The range ended at the line above, this text is garbage instead of a boundary
line
""",
)


class TestHandleResponse(tests.TestCase):
    def _build_HTTPMessage(self, raw_headers):
        status_and_headers = BytesIO(raw_headers)
        # Get rid of the status line
        status_and_headers.readline()
        msg = parse_headers(status_and_headers)
        return msg.get

    def get_response(self, a_response):
        """Process a supplied response, and return the result."""
        code, raw_headers, body = a_response
        getheader = self._build_HTTPMessage(raw_headers)
        return response.handle_response(
            "http://foo", code, getheader, BytesIO(a_response[2])
        )

    def test_full_text(self):
        out = self.get_response(_full_text_response)
        # It is a BytesIO from the original data
        self.assertEqual(_full_text_response[2], out.read())

    def test_single_range(self):
        out = self.get_response(_single_range_response)

        out.seek(100)
        self.assertEqual(_single_range_response[2], out.read(100))

    def test_single_range_no_content(self):
        out = self.get_response(_single_range_no_content_type)

        out.seek(100)
        self.assertEqual(_single_range_no_content_type[2], out.read(100))

    def test_single_range_truncated(self):
        out = self.get_response(_single_range_response_truncated)
        # Content-Range declares 100 but only 51 present
        self.assertRaises(errors.ShortReadvError, out.seek, out.tell() + 51)

    def test_multi_range(self):
        out = self.get_response(_multipart_range_response)

        # Just make sure we can read the right contents
        out.seek(0)
        out.read(255)

        out.seek(1000)
        out.read(1050)

    def test_multi_squid_range(self):
        out = self.get_response(_multipart_squid_range_response)

        # Just make sure we can read the right contents
        out.seek(0)
        out.read(100)

        out.seek(300)
        out.read(200)

    def test_invalid_response(self):
        self.assertRaises(
            errors.InvalidHttpResponse, self.get_response, _invalid_response
        )

    def test_full_text_no_content_type(self):
        # We should not require Content-Type for a full response
        code, raw_headers, body = _full_text_response_no_content_type
        getheader = self._build_HTTPMessage(raw_headers)
        out = response.handle_response("http://foo", code, getheader, BytesIO(body))
        self.assertEqual(body, out.read())

    def test_full_text_no_content_length(self):
        code, raw_headers, body = _full_text_response_no_content_length
        getheader = self._build_HTTPMessage(raw_headers)
        out = response.handle_response("http://foo", code, getheader, BytesIO(body))
        self.assertEqual(body, out.read())

    def test_missing_content_range(self):
        code, raw_headers, body = _single_range_no_content_range
        getheader = self._build_HTTPMessage(raw_headers)
        self.assertRaises(
            errors.InvalidHttpResponse,
            response.handle_response,
            "http://bogus",
            code,
            getheader,
            BytesIO(body),
        )

    def test_multipart_no_content_range(self):
        code, raw_headers, body = _multipart_no_content_range
        getheader = self._build_HTTPMessage(raw_headers)
        self.assertRaises(
            errors.InvalidHttpResponse,
            response.handle_response,
            "http://bogus",
            code,
            getheader,
            BytesIO(body),
        )

    def test_multipart_no_boundary(self):
        out = self.get_response(_multipart_no_boundary)
        out.read()  # Read the whole range
        # Fail to find the boundary line
        self.assertRaises(errors.InvalidHttpResponse, out.seek, 1, 1)


class TestRangeFileSizeReadLimited(tests.TestCase):
    """Test RangeFile _max_read_size functionality which limits the size of
    read blocks to prevent MemoryError messages in socket.recv.
    """

    def setUp(self):
        super().setUp()
        # create a test datablock larger than _max_read_size.
        chunk_size = response.RangeFile._max_read_size
        test_pattern = b"0123456789ABCDEF"
        self.test_data = test_pattern * (3 * chunk_size // len(test_pattern))
        self.test_data_len = len(self.test_data)

    def test_max_read_size(self):
        """Read data in blocks and verify that the reads are not larger than
        the maximum read size.
        """
        # retrieve data in large blocks from response.RangeFile object
        mock_read_file = FakeReadFile(self.test_data)
        range_file = response.RangeFile("test_max_read_size", mock_read_file)
        response_data = range_file.read(self.test_data_len)

        # verify read size was equal to the maximum read size
        self.assertTrue(mock_read_file.get_max_read_size() > 0)
        self.assertEqual(
            mock_read_file.get_max_read_size(), response.RangeFile._max_read_size
        )
        self.assertEqual(mock_read_file.get_read_count(), 3)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

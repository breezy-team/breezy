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

"""Tests from HTTP response parsing."""

from cStringIO import StringIO
import httplib

from bzrlib import errors
from bzrlib.transport import http
from bzrlib.transport.http import response
from bzrlib.tests import TestCase


class TestRangeFileAccess(TestCase):
    """Test RangeFile."""

    def setUp(self):
        self.alpha = 'abcdefghijklmnopqrstuvwxyz'
        # Each file is defined as a tuple (builder, start), 'builder' is a
        # callable returning a RangeFile and 'start' the start of the first (or
        # unique) range.
        self.files = [(self._file_size_unknown, 0),
                      (self._file_size_known, 0),
                      (self._file_single_range, 10),
                      (self._file_multi_ranges, 10),]


    def _file_size_unknown(self):
        return response.RangeFile('Whole_file_size_unknown',
                                  StringIO(self.alpha))

    def _file_size_known(self):
        alpha = self.alpha
        f = response.RangeFile('Whole_file_size_known', StringIO(alpha))
        f.set_range(0, len(alpha))
        return f

    def _file_single_range(self):
        alpha = self.alpha
        f = response.RangeFile('Single_range_file', StringIO(alpha))
        f.set_range(10, len(alpha))
        return f

    def _file_multi_ranges(self):
        alpha = self.alpha

        boundary = 'separation'
        bline = '--' + boundary + '\r\n'
        content = []
        content += bline
        file_size = 200
        for (start, part) in [(10, alpha), (100, alpha)]:
            plen = len(part)
            content += 'Content-Range: bytes %d-%d/%d\r\n' % (start,
                                                              start+plen-1,
                                                              file_size)
            content += '\r\n'
            content += part
            content += bline

        data = ''.join(content)
        f = response.RangeFile('Multiple_ranges_file', StringIO(data))
        # Ranges are set by decoding the headers
        f.set_boundary(boundary)
        return f

    def _check_accesses_inside_range(self, f, start=0):
        self.assertEquals(start, f.tell())
        self.assertEquals('abc', f.read(3))
        self.assertEquals('def', f.read(3))
        self.assertEquals(start + 6, f.tell())
        f.seek(start + 10)
        self.assertEquals('klm', f.read(3))
        self.assertEquals('no', f.read(2))
        self.assertEquals(start + 15, f.tell())
        # Unbounded read, should not cross range
        self.assertEquals('pqrstuvwxyz', f.read())

    def test_valid_accesses(self):
        """Test valid accesses: inside one or more ranges"""
        alpha = 'abcdefghijklmnopqrstuvwxyz'

        for builder, start in self.files[:3]:
            self._check_accesses_inside_range(builder(), start)

        f =  self._file_multi_ranges()
        self._check_accesses_inside_range(f, start=10)
        f.seek(100) # Will trigger the decoding and setting of the second range
        self._check_accesses_inside_range(f, 100)

        f =  self._file_multi_ranges()
        f.seek(10)
        # Seeking to a point between two ranges is possible (only once) but
        # reading there is forbidden
        f.seek(40)
        # We crossed a range boundary, so now the file is positioned at the
        # start of the new range (i.e. trying to seek below 100 will error out)
        f.seek(100)
        f.seek(126)

    def _check_file_boundaries(self, f, start=0):
        f.seek(start)
        self.assertRaises(errors.InvalidRange, f.read, 27)
        # Will seek past the range and then errors out
        self.assertRaises(errors.InvalidRange, f.seek, start + 27)

    def _check_beyond_range(self, builder, start):
        f = builder()
        f.seek(start + 20)
        # Will try to read past the end of the range
        self.assertRaises(errors.InvalidRange, f.read, 10)

    def _check_seek_backwards(self, f, start=0):
        f.read(start + 12)
        # Can't seek backwards
        self.assertRaises(errors.InvalidRange, f.seek, start + 5)

    def test_invalid_accesses(self):
        """Test errors triggered by invalid accesses."""

        f =  self._file_size_unknown()
        self.assertRaises(errors.InvalidRange, f.seek, -1, 2)

        for builder, start in self.files:
            self._check_seek_backwards(builder(), start)

        for builder, start in self.files[1:3]:
            self._check_file_boundaries(builder(), start)

        f =  self._file_multi_ranges()
        self._check_accesses_inside_range(f, start=10)
        f.seek(40) # Will trigger the decoding and setting of the second range
        self.assertEquals(100, f.tell())
        self._check_accesses_inside_range(f, 100)


        self._check_beyond_range(self._file_single_range, start=10)
        self._check_beyond_range(self._file_multi_ranges, start=10)

        f =  self._file_multi_ranges()
        f.seek(40) # Past the first range but before the second
        # Now the file is positioned at the second range start (100)
        self.assertRaises(errors.InvalidRange, f.seek, 41)

        f =  self._file_multi_ranges()
        # We can seek across ranges but not beyond
        self.assertRaises(errors.InvalidRange, f.read, 127)


class TestRanges(TestCase):

    def test_range_syntax(self):

        rf = response.RangeFile('foo', None)

        def ok(expected, header_value):
            rf.set_range_from_header(header_value)
            # Slightly peek under the covers to get the size
            self.assertEquals(expected, (rf.tell(), rf._size))

        ok((1, 10), 'bytes 1-10/11')
        ok((1, 10), 'bytes 1-10/*')
        ok((12, 2), '\tbytes 12-13/*')
        ok((28, 1), '  bytes 28-28/*')
        ok((2123, 2120), 'bytes  2123-4242/12310')
        ok((1, 10), 'bytes 1-10/xxx') # We don't check total (xxx)

        def nok(header_value):
            self.assertRaises(errors.InvalidHttpRange,
                              rf.set_range_from_header, header_value)

        nok('chars 1-2/3')
        nok('bytes xx-yyy/zzz')
        nok('bytes xx-12/zzz')
        nok('bytes 11-yy/zzz')

# Taken from real request responses
_full_text_response = (200, """HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: 35\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
""", """Bazaar-NG meta directory, format 1
""")


_single_range_response = (206, """HTTP/1.1 206 Partial Content\r
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
""", """mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e762""")


_single_range_no_content_type = (206, """HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:45:22 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 100\r
Content-Range: bytes 100-199/93890\r
Connection: close\r
\r
""", """mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e762""")


_multipart_range_response = (206, """HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:49:48 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 1534\r
Connection: close\r
Content-Type: multipart/byteranges; boundary=418470f848b63279b\r
\r
\r""", """--418470f848b63279b\r
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
""")

_multipart_squid_range_response = (206, """HTTP/1.0 206 Partial Content\r
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
"""\r
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
""")


# This is made up
_full_text_response_no_content_type = (200, """HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: 35\r
Connection: close\r
\r
""", """Bazaar-NG meta directory, format 1
""")


_single_range_no_content_range = (206, """HTTP/1.1 206 Partial Content\r
Date: Tue, 11 Jul 2006 04:45:22 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Thu, 06 Jul 2006 20:22:05 GMT\r
ETag: "238a3c-16ec2-805c5540"\r
Accept-Ranges: bytes\r
Content-Length: 100\r
Connection: close\r
\r
""", """mbp@sourcefrog.net-20050309040815-13242001617e4a06
mbp@sourcefrog.net-20050309040929-eee0eb3e6d1e762""")


_invalid_response = (444, """HTTP/1.1 444 Bad Response\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Connection: close\r
Content-Type: text/html; charset=iso-8859-1\r
\r
""", """<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>404 Not Found</title>
</head><body>
<h1>Not Found</h1>
<p>I don't know what I'm doing</p>
<hr>
</body></html>
""")


class TestHandleResponse(TestCase):

    def _build_HTTPMessage(self, raw_headers):
        status_and_headers = StringIO(raw_headers)
        # Get read of the status line
        status_and_headers.readline()
        msg = httplib.HTTPMessage(status_and_headers)
        return msg

    def get_response(self, a_response):
        """Process a supplied response, and return the result."""
        code, raw_headers, body = a_response
        msg = self._build_HTTPMessage(raw_headers)
        return response.handle_response('http://foo', code, msg,
                                        StringIO(a_response[2]))

    def test_full_text(self):
        out = self.get_response(_full_text_response)
        # It is a StringIO from the original data
        self.assertEqual(_full_text_response[2], out.read())

    def test_single_range(self):
        out = self.get_response(_single_range_response)

        out.seek(100)
        self.assertEqual(_single_range_response[2], out.read(100))

    def test_single_range_no_content(self):
        out = self.get_response(_single_range_no_content_type)

        out.seek(100)
        self.assertEqual(_single_range_no_content_type[2], out.read(100))

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
        self.assertRaises(errors.InvalidHttpResponse,
                          self.get_response, _invalid_response)

    def test_full_text_no_content_type(self):
        # We should not require Content-Type for a full response
        code, raw_headers, body = _full_text_response_no_content_type
        msg = self._build_HTTPMessage(raw_headers)
        out = response.handle_response('http://foo', code, msg, StringIO(body))
        self.assertEqual(body, out.read())

    def test_missing_content_range(self):
        code, raw_headers, body = _single_range_no_content_range
        msg = self._build_HTTPMessage(raw_headers)
        self.assertRaises(errors.InvalidHttpResponse,
                          response.handle_response,
                          'http://nocontent', code, msg, StringIO(body))

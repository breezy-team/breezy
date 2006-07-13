# Copyright (C) 2005, 2006 by Canonical Ltd
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
import mimetools

from bzrlib import errors
from bzrlib.transport import http
from bzrlib.transport.http import response
from bzrlib.tests import TestCase


class TestResponseRange(TestCase):
    """Test the ResponseRange class."""

    def test_cmp(self):
        RR = response.ResponseRange
        r1 = RR(0, 10, 0)
        r2 = RR(15, 20, 10)
        self.assertTrue(r1 < r2)
        self.assertFalse(r1 > r2)
        self.assertTrue(r1 < 5)
        self.assertFalse(r2 < 5)

        self.assertEqual(RR(0, 10, 5), RR(0, 10, 5))
        self.assertNotEqual(RR(0, 10, 5), RR(0, 8, 5))
        self.assertNotEqual(RR(0, 10, 5), RR(0, 10, 6))

    def test_sort_list(self):
        """Ensure longer ranges are sorted after shorter ones"""
        RR = response.ResponseRange
        lst = [RR(3, 8, 0), 5, RR(3, 7, 0), 6]
        lst.sort()
        self.assertEqual([RR(3,7,0), RR(3,8,0), 5, 6], lst)


class TestRangeFile(TestCase):
    """Test RangeFile."""

    def setUp(self):
        content = "abcdefghijklmnopqrstuvwxyz"
        self.fp = response.RangeFile('foo', StringIO(content))
        self.fp._add_range(0,  9,   0)
        self.fp._add_range(20, 29, 10)
        self.fp._add_range(30, 39, 15)

    def test_valid_accesses(self):
        """Test so that valid accesses work to the file."""
        self.fp.seek(0, 0)
        self.assertEquals(self.fp.read(3), 'abc')
        self.assertEquals(self.fp.read(3), 'def')
        self.assertEquals(self.fp.tell(), 6)
        self.fp.seek(20, 0)
        self.assertEquals(self.fp.read(3), 'klm')
        self.assertEquals(self.fp.read(2), 'no')
        self.assertEquals(self.fp.tell(), 25)
        # should wrap over to 30-39 entity
        self.assertEquals(self.fp.read(3), 'pqr')
        self.fp.seek(3)
        self.assertEquals(self.fp.read(3), 'def')
        self.assertEquals(self.fp.tell(), 6)

    def test_invalid_accesses(self):
        """Test so that invalid accesses trigger errors."""
        self.fp.seek(9)
        self.assertRaises(errors.InvalidRange, self.fp.read, 2)
        self.fp.seek(39)
        self.assertRaises(errors.InvalidRange, self.fp.read, 2)
        self.fp.seek(19)
        self.assertRaises(errors.InvalidRange, self.fp.read, 2)

    def test__finish_ranges(self):
        """Test that after RangeFile._finish_ranges the list is sorted."""
        self.fp._add_range(1, 2, 3)
        self.fp._add_range(8, 9, 10)
        self.fp._add_range(3, 4, 5)

        # TODO: jam 20060706 If we switch to inserting
        #       in sorted order, remove this test
        self.assertNotEqual(self.fp._ranges, sorted(self.fp._ranges))

        self.fp._finish_ranges()
        self.assertEqual(self.fp._ranges, sorted(self.fp._ranges))

    def test_seek_and_tell(self):
        # Check for seeking before start
        self.fp.seek(-2, 0)
        self.assertEqual(0, self.fp.tell())

        self.fp.seek(5, 0)
        self.assertEqual(5, self.fp.tell())

        self.fp.seek(-2, 1)
        self.assertEqual(3, self.fp.tell())

        # TODO: jam 20060706 following tests will fail if this 
        #       is not true, and would be difficult to debug
        #       but it is a layering violation
        self.assertEqual(39, self.fp._len)

        self.fp.seek(0, 2)
        self.assertEqual(39, self.fp.tell())

        self.fp.seek(-10, 2)
        self.assertEqual(29, self.fp.tell())

        self.assertRaises(ValueError, self.fp.seek, 0, 4)
        self.assertRaises(ValueError, self.fp.seek, 0, -1)


class TestRegexes(TestCase):

    def assertRegexMatches(self, groups, text):
        """Check that the regex matches and returns the right values"""
        m = self.regex.match(text)
        self.assertNotEqual(None, m, "text %s did not match regex" % (text,))

        self.assertEqual(groups, m.groups())

    def test_range_re(self):
        """Test that we match valid ranges."""
        self.regex = response.HttpRangeResponse._CONTENT_RANGE_RE
        self.assertRegexMatches(('bytes', '1', '10', '11'),
                           'bytes 1-10/11')
        self.assertRegexMatches(('bytes', '1', '10', '11'),
                           '\tbytes  1-10/11   ')
        self.assertRegexMatches(('bytes', '2123', '4242', '1231'),
                           '\tbytes  2123-4242/1231   ')
        self.assertRegexMatches(('chars', '1', '2', '3'),
                           ' chars 1-2/3')

    def test_content_type_re(self):
        self.regex = response.HttpMultipartRangeResponse._CONTENT_TYPE_RE
        self.assertRegexMatches(('xxyyzz',),
                                'multipart/byteranges; boundary = xxyyzz')
        self.assertRegexMatches(('xxyyzz',),
                                'multipart/byteranges;boundary=xxyyzz')
        self.assertRegexMatches(('xx yy zz',),
                                ' multipart/byteranges ; boundary= xx yy zz ')
        self.assertEqual(None,
                self.regex.match('multipart byteranges;boundary=xx'))


simple_data = """
--xxyyzz\r
foo\r
Content-range: bytes 1-10/20\r
\r
1234567890
--xxyyzz\r
Content-Range: bytes 21-30/20\r
bar\r
\r
abcdefghij
--xxyyzz\r
content-range: bytes 41-50/20\r
\r
zyxwvutsrq
--xxyyzz\r
content-range: bytes 51-60/20\r
\r
xxyyzz fbd
"""


class TestHelpers(TestCase):
    """Test the helper functions"""

    def test__parse_range(self):
        """Test that _parse_range acts reasonably."""
        content = StringIO('')
        parse_range = response.HttpRangeResponse._parse_range
        self.assertEqual((1,2), parse_range('bytes 1-2/3'))
        self.assertEqual((10,20), parse_range('bytes 10-20/2'))

        self.assertRaises(errors.InvalidHttpRange, parse_range, 'char 1-3/2')
        self.assertRaises(errors.InvalidHttpRange, parse_range, 'bytes a-3/2')

        try:
            parse_range('bytes x-10/3', path='http://foo/bar')
        except errors.InvalidHttpRange, e:
            self.assertContainsRe(str(e), 'http://foo/bar')
            self.assertContainsRe(str(e), 'bytes x-10/3')
        else:
            self.fail('Did not raise InvalidHttpRange')

    def test__parse_boundary_simple(self):
        """Test that _parse_boundary handles Content-type properly"""
        parse_boundary = response.HttpMultipartRangeResponse._parse_boundary
        m = parse_boundary(' multipart/byteranges; boundary=xxyyzz')
        self.assertNotEqual(None, m)
        # Check that the returned regex is capable of splitting simple_data
        matches = list(m.finditer(simple_data))
        self.assertEqual(4, len(matches))

        # match.group() should be the content-range entry
        # and match.end() should be the start of the content
        self.assertEqual(' bytes 1-10/20', matches[0].group(1))
        self.assertEqual(simple_data.find('1234567890'), matches[0].end())
        self.assertEqual(' bytes 21-30/20', matches[1].group(1))
        self.assertEqual(simple_data.find('abcdefghij'), matches[1].end())
        self.assertEqual(' bytes 41-50/20', matches[2].group(1))
        self.assertEqual(simple_data.find('zyxwvutsrq'), matches[2].end())
        self.assertEqual(' bytes 51-60/20', matches[3].group(1))
        self.assertEqual(simple_data.find('xxyyzz fbd'), matches[3].end())

    def test__parse_boundary_invalid(self):
        parse_boundary = response.HttpMultipartRangeResponse._parse_boundary
        try:
            parse_boundary(' multipart/bytes;boundary=xxyyzz',
                           path='http://foo/bar')
        except errors.InvalidHttpContentType, e:
            self.assertContainsRe(str(e), 'http://foo/bar')
            self.assertContainsRe(str(e), 'multipart/bytes;boundary=xxyyzz')
        else:
            self.fail('Did not raise InvalidHttpContentType')


class TestHttpRangeResponse(TestCase):

    def test_smoketest(self):
        """A basic test that HttpRangeResponse is reasonable."""
        content = StringIO('0123456789')
        f = response.HttpRangeResponse('http://foo', 'bytes 1-10/9', content)
        self.assertEqual([response.ResponseRange(1,10,0)], f._ranges)

        f.seek(0)
        self.assertRaises(errors.InvalidRange, f.read, 2)
        f.seek(1)
        self.assertEqual('012345', f.read(6))

    def test_invalid(self):
        try:
            f = response.HttpRangeResponse('http://foo', 'bytes x-10/9',
                                           StringIO('0123456789'))
        except errors.InvalidHttpRange, e:
            self.assertContainsRe(str(e), 'http://foo')
            self.assertContainsRe(str(e), 'bytes x-10/9')
        else:
            self.fail('Failed to raise InvalidHttpRange')


class TestHttpMultipartRangeResponse(TestCase):
    """Test the handling of multipart range responses"""

    def test_simple(self):
        content = StringIO(simple_data)
        multi = response.HttpMultipartRangeResponse('http://foo',
                    'multipart/byteranges; boundary = xxyyzz', content)

        self.assertEqual(4, len(multi._ranges))

        multi.seek(1)
        self.assertEqual('1234567890', multi.read(10))
        multi.seek(21)
        self.assertEqual('abcdefghij', multi.read(10))
        multi.seek(41)
        self.assertEqual('zyxwvutsrq', multi.read(10))
        multi.seek(51)
        self.assertEqual('xxyyzz fbd', multi.read(10))
        # TODO: jam 20060706 Currently RangeFile does not support
        #       reading across ranges. Consider adding it.
        multi.seek(41)
        # self.assertEqual('zyxwvutsrqxxyyzz fbd', multi.read(20))
        self.assertRaises(errors.InvalidRange, multi.read, 20)

        multi.seek(21)
        self.assertRaises(errors.InvalidRange, multi.read, 11)
        multi.seek(31)
        self.assertRaises(errors.InvalidRange, multi.read, 10)

    def test_invalid(self):
        content = StringIO('')
        try:
            response.HttpMultipartRangeResponse('http://foo',
                        'multipart/byte;boundary=invalid', content)
        except errors.InvalidHttpContentType, e:
            self.assertContainsRe(str(e), 'http://foo')
            self.assertContainsRe(str(e), 'multipart/byte;')


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


_missing_response = (404, """HTTP/1.1 404 Not Found\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Content-Length: 336\r
Connection: close\r
Content-Type: text/html; charset=iso-8859-1\r
\r
""", """<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>404 Not Found</title>
</head><body>
<h1>Not Found</h1>
<p>The requested URL /branches/bzr/jam-integration/.bzr/repository/format was not found on this server.</p>
<hr>
<address>Apache/2.0.54 (Fedora) Server at bzr.arbash-meinel.com Port 80</address>
</body></html>
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
--418470f848b63279b--\r\n'
""")


# This is made up
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


# This should be in test_http.py, but the headers we
# want to parse are here
class TestExtractHeader(TestCase):
    
    def use_response(self, response):
        self.headers = http._extract_headers(StringIO(response[1]))

    def check_header(self, header, value):
        self.assertEqual(value, self.headers[header])
        
    def test_full_text(self):
        self.use_response(_full_text_response)

        self.check_header('Date', 'Tue, 11 Jul 2006 04:32:56 GMT')
        self.check_header('date', 'Tue, 11 Jul 2006 04:32:56 GMT')
        self.check_header('Content-Length', '35')
        self.check_header('Content-Type', 'text/plain; charset=UTF-8')
        self.check_header('content-type', 'text/plain; charset=UTF-8')

    def test_missing_response(self):
        self.use_response(_missing_response)

        self.check_header('Content-Length', '336')
        self.check_header('Content-Type', 'text/html; charset=iso-8859-1')

    def test_single_range(self):
        self.use_response(_single_range_response)

        self.check_header('Content-Length', '100')
        self.check_header('Content-Range', 'bytes 100-199/93890')
        self.check_header('Content-Type', 'text/plain; charset=UTF-8')

    def test_multi_range(self):
        self.use_response(_multipart_range_response)

        self.check_header('Content-Length', '1534')
        self.check_header('Content-Type',
                          'multipart/byteranges; boundary=418470f848b63279b')



def parse_response(response):
    """Turn one of the static HTTP responses into an in-flight response."""
    resp = StringIO(response)
    http_response = resp.readline()
    assert http_response.startswith('HTTP/1.1 ')

class TestHandleResponse(TestCase):
    
    def get_response(self, a_response):
        """Process a supplied response, and return the result."""
        headers = http._extract_headers(StringIO(a_response[1]))
        return response.handle_response('http://foo', a_response[0], headers,
                                        StringIO(a_response[2]))

    def test_full_text(self):
        out = self.get_response(_full_text_response)
        # It is a StringIO from the original data
        self.assertEqual(_full_text_response[2], out.read())

    def test_missing_response(self):
        self.assertRaises(errors.NoSuchFile,
            self.get_response, _missing_response)

    def test_single_range(self):
        out = self.get_response(_single_range_response)
        self.assertIsInstance(out, response.HttpRangeResponse)

        self.assertRaises(errors.InvalidRange, out.read, 20)

        out.seek(100)
        self.assertEqual(_single_range_response[2], out.read(100))

    def test_multi_range(self):
        out = self.get_response(_multipart_range_response)
        self.assertIsInstance(out, response.HttpMultipartRangeResponse)

        # Just make sure we can read the right contents
        out.seek(0)
        out.read(255)

        out.seek(1000)
        out.read(1050)

    def test_invalid_response(self):
        self.assertRaises(errors.InvalidHttpResponse,
            self.get_response, _invalid_response)

    def test_full_text_no_content_type(self):
        # We should not require Content-Type for a full response
        a_response = _full_text_response
        headers = http._extract_headers(StringIO(a_response[1]))
        del headers['Content-Type']
        out = response.handle_response('http://foo', a_response[0], headers,
                                        StringIO(a_response[2]))
        self.assertEqual(_full_text_response[2], out.read())

    def test_missing_no_content_type(self):
        # Without Content-Type we should still raise NoSuchFile on a 404
        a_response = _missing_response
        headers = http._extract_headers(StringIO(a_response[1]))
        del headers['Content-Type']
        self.assertRaises(errors.NoSuchFile,
            response.handle_response, 'http://missing', a_response[0], headers,
                                      StringIO(a_response[2]))

    def test_missing_content_type(self):
        a_response = _single_range_response
        headers = http._extract_headers(StringIO(a_response[1]))
        del headers['Content-Type']
        self.assertRaises(errors.InvalidHttpContentType,
            response.handle_response, 'http://nocontent', a_response[0],
                                      headers, StringIO(a_response[2]))

    def test_missing_content_range(self):
        a_response = _single_range_response
        headers = http._extract_headers(StringIO(a_response[1]))
        del headers['Content-Range']
        self.assertRaises(errors.InvalidHttpResponse,
            response.handle_response, 'http://nocontent', a_response[0],
                                      headers, StringIO(a_response[2]))

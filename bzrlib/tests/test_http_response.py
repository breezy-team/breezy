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

from bzrlib import errors
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
        self.regex = response._CONTENT_RANGE_RE
        self.assertRegexMatches(('bytes', '1', '10', '11'),
                           'bytes 1-10/11')
        self.assertRegexMatches(('bytes', '1', '10', '11'),
                           '\tbytes  1-10/11   ')
        self.assertRegexMatches(('bytes', '2123', '4242', '1231'),
                           '\tbytes  2123-4242/1231   ')
        self.assertRegexMatches(('chars', '1', '2', '3'),
                           ' chars 1-2/3')

    def test_content_type_re(self):
        self.regex = response._CONTENT_TYPE_RE
        self.assertRegexMatches(('xxyyzz',),
                                'multipart/byteranges; boundary = xxyyzz')
        self.assertRegexMatches(('xxyyzz',),
                                'multipart/byteranges;boundary=xxyyzz')
        self.assertRegexMatches(('xx yy zz',),
                                ' multipart/byteranges ; boundary= xx yy zz ')
        self.assertEqual(None, 
                self.regex.match('multipart byteranges;boundary=xx'))


class TestHttpRangeResponse(TestCase):

    def test__parse_range(self):
        """Test that _parse_range acts reasonably."""
        content = StringIO('')
        parse_range = response._parse_range
        self.assertEqual((1,2), parse_range('bytes 1-2/3'))
        self.assertEqual((10,20), parse_range('bytes 10-20/2'))

        self.assertRaises(errors.InvalidHttpRange, parse_range, 'char 1-3/2')
        self.assertRaises(errors.InvalidHttpRange, parse_range, 'bytes a-3/2')

        try:
            parse_range('bytes x-10/3', path='http://foo/bar')
        except errors.InvalidHttpRange, e:
            self.assertContainsRe(str(e), 'http://foo/bar')
        else:
            self.fail('Did not raise InvalidHttpRange')

    def test_smoketest(self):
        """A basic test that HttpRangeResponse is reasonable."""
        content = StringIO('0123456789')
        f = response.HttpRangeResponse('http://foo', 'bytes 1-10/9', content)
        self.assertEqual([response.ResponseRange(1,10,0)], f._ranges)

        f.seek(0)
        self.assertRaises(errors.InvalidRange, f.read, 2)
        f.seek(1)
        self.assertEqual('012345', f.read(6))


class TestHttpMultipartRangeResponse(TestCase):
    pass

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

from bzrlib.tests import TestCase
from bzrlib.transport.http.response import RangeFile, ResponseRange
from bzrlib.errors import InvalidRange


class TestResponseRange(TestCase):
    """Test the ResponseRange class."""

    def test_cmp(self):
        r1 = ResponseRange(0, 10, 0)
        r2 = ResponseRange(15, 20, 10)
        self.assertTrue(r1 < r2)
        self.assertFalse(r1 > r2)
        self.assertTrue(r1 < 5)
        self.assertFalse(r2 < 5)

        self.assertEqual(ResponseRange(0, 10, 5), ResponseRange(0, 10, 5))
        self.assertNotEqual(ResponseRange(0, 10, 5), ResponseRange(0, 8, 5))
        self.assertNotEqual(ResponseRange(0, 10, 5), ResponseRange(0, 10, 6))

    def test_sort_list(self):
        lst = [ResponseRange(3, 8, 0), 5, ResponseRange(3, 7, 0), 6]
        lst.sort()
        self.assertEqual([ResponseRange(3,7,0), ResponseRange(3,8,0), 5, 6],
                         lst)


class TestRangeFile(TestCase):
    """Test RangeFile."""

    def setUp(self):
        content = "abcdefghijklmnopqrstuvwxyz"
        self.fp = RangeFile('foo', StringIO(content))
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
        self.assertRaises(InvalidRange, self.fp.read, 2)
        self.fp.seek(39)
        self.assertRaises(InvalidRange, self.fp.read, 2)
        self.fp.seek(19)
        self.assertRaises(InvalidRange, self.fp.read, 2)

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

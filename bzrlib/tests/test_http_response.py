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
from bzrlib.transport.http.response import RangeFile
from bzrlib.errors import InvalidRange


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
        


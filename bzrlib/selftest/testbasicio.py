# Copyright (C) 2005 by Canonical Ltd
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

"""Tests for basic_io serialization

A simple, reproducible structured IO format.

basic_io itself works in Unicode strings.  It is typically encoded to UTF-8,
but this depends on the transport.
"""

import os
import sys
from tempfile import TemporaryFile

from bzrlib.selftest import TestCaseInTempDir, TestCase
from bzrlib.basicio import BasicWriter, Stanza


class TestBasicIO(TestCase):

    def test_stanza(self):
        """Construct basic_io stanza in memory"""
        s = Stanza(number=42, name="fred")
        self.assertTrue('number' in s)
        self.assertFalse('color' in s)
        self.assertFalse(42 in s)
        self.assertEquals(list(s),
                [('name', 'fred'), ('number', 42)])
        # TODO: how to get back particular fields?  what if it's repeated?

    def test_value_checks(self):
        """basic_io checks types on construction"""
        self.assertRaises(ValueError,
                Stanza, complex=42 + 3j)
        self.assertRaises(ValueError, 
                Stanza, several=range(10))

    def test_to_lines(self):
        """Write simple basic_io stanza to string"""
        s = Stanza(number=42, name='fred')
        self.assertEquals(list(s.to_lines()),
                ['  name "fred"\n',
                 'number 42\n'])

    def test_to_file(self):
        """Write basic_io to file"""
        tmpf = TemporaryFile()
        s = Stanza(a_thing='something with "quotes like \\"this\\""', number=42, name='fred')
        s.write(tmpf)
        tmpf.seek(0)
        self.assertEqualDiff(tmpf.read(), r'''
a_thing "something with \"quotes like \\\"this\\\"\""
   name "fred"
 number 42
'''[1:])

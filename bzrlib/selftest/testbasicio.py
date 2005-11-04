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
from bzrlib.basicio import BasicWriter, Stanza, read_stanza, read_stanzas


class TestBasicIO(TestCase):

    def test_stanza(self):
        """Construct basic_io stanza in memory"""
        s = Stanza(number=42, name="fred")
        self.assertTrue('number' in s)
        self.assertFalse('color' in s)
        self.assertFalse(42 in s)
        self.assertEquals(list(s.iter_pairs()),
                [('name', 'fred'), ('number', 42)])
        self.assertEquals(s.get('number'), 42)
        self.assertEquals(s.get('name'), 'fred')

    def test_value_checks(self):
        """basic_io checks types on construction"""
        # these aren't enforced at construction time
        ## self.assertRaises(ValueError,
        ##        Stanza, complex=42 + 3j)
        ## self.assertRaises(ValueError, 
        ##        Stanza, several=range(10))

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

    def test_multiline_string(self):
        """Write basic_io with multiline string"""
        tmpf = TemporaryFile()
        s = Stanza(a=123, motto="war is peace\nfreedom is slavery\nignorance is strength\n",
                   charlie_horse=456)
        s.write(tmpf)
        tmp.seek(0)
        self.assertEqualDiff(tmpf.read(), r'''\
            a 123
        motto "war is peace
freedom is slavery
ignorance is strength
"
charlie_horse 456
''')

    def test_multiline_string(self):
        tmpf = TemporaryFile()
        s = Stanza(motto="war is peace\nfreedom is slavery\nignorance is strength")
        s.write(tmpf)
        tmpf.seek(0)
        self.assertEqualDiff(tmpf.read(), '''\
motto "war is peace
freedom is slavery
ignorance is strength"
''')
        tmpf.seek(0)
        s2 = read_stanza(tmpf)
        self.assertEquals(s, s2)

    def test_read_stanza(self):
        """Load stanza from string"""
        lines = """\
 revision "mbp@sourcefrog.net-123-abc"
timestamp 1130653962
 timezone 36000
committer "Martin Pool <mbp@test.sourcefrog.net>"
""".splitlines(True)
        s = read_stanza(lines)
        self.assertTrue('revision' in s)
        self.assertEqualDiff(s.get('revision'), 'mbp@sourcefrog.net-123-abc')
        self.assertEquals(list(s.iter_pairs()),
                [('revision', 'mbp@sourcefrog.net-123-abc'),
                 ('timestamp', 1130653962),
                 ('timezone', 36000),
                 ('committer', "Martin Pool <mbp@test.sourcefrog.net>")])
        self.assertEquals(len(s), 4)

    def test_repeated_field(self):
        """Repeated field in basic_io"""
        s = Stanza()
        for k, v in [('a', 10), ('b', 20), ('a', 100), ('b', 200), ('a', 1000), ('b', 2000)]:
            s.add(k, v)
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)
        self.assertEquals(s.get_all('a'), [10, 100, 1000])
        self.assertEquals(s.get_all('b'), [20, 200, 2000])

    def test_longint(self):
        """basic_io packing long integers"""
        s = Stanza(x=-12345678901234567890,
                   y=1<<100)
        lines = s.to_lines()
        s2 = read_stanza(lines)
        self.assertEquals(s, s2)

    def test_quoted_0(self):
        """Backslash quoted cases"""
        s = Stanza(q='\\')
        t = s.to_string()
        self.assertEqualDiff(t, 'q "\\\\"\n')
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_quoted_1(self):
        """Backslash quoted cases"""
        s = Stanza(q=r'\"\"')
        self.assertEqualDiff(s.to_string(), r'q "\\\"\\\""' + '\n')

    def test_quoted_4(self):
        s = Stanza(q=r'""""')
        t = s.to_string()
        self.assertEqualDiff(t, r'q "\"\"\"\""' + '\n')
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_quoted_5(self):
        s = Stanza(q=r'\\\\\"')
        t = s.to_string()
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_quoted_6(self):
        qval = r'''
                "
                \"
'''
        s = Stanza(q=qval)
        t = s.to_string()
        self.log(t)
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s2['q'], qval)
        
    def test_quoted_7(self):
        qval = r'''
                "
                \\"
trailing stuff'''
        s = Stanza(q=qval)
        t = s.to_string()
        self.log(t)
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s2['q'], qval)
        
    def test_quoted(self):
        """basic_io quoted string cases"""
        s = Stanza(q1='"hello"', 
                   q2=' "for', 
                   q3='\n\n"for"\n',
                   q4='for\n"\nfor',
                   q5='\n',
                   q6='"', 
                   q7='""',
                   q8='\\',
                   q9='\\"\\"',
                   )
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_read_empty(self):
        """Detect end of basic_io file"""
        s = read_stanza([])
        self.assertEqual(s, None)
        self.assertTrue(s is None)
        
    def test_read_iter(self):
        """Read several stanzas from file"""
        tmpf = TemporaryFile()
        tmpf.write("""\
version_header 1

name "foo"
val 123

name "bar"
val 129319
""")
        tmpf.seek(0)
        reader = read_stanzas(tmpf)
        read_iter = iter(reader)
        stuff = list(reader)
        self.assertEqual(stuff, 
                [ Stanza(version_header=1),
                  Stanza(name="foo", val=123),
                  Stanza(name="bar", val=129319), ])

    def test_read_several(self):
        """Read several stanzas from file"""
        tmpf = TemporaryFile()
        tmpf.write("""\
version_header 1

name "foo"
val 123

name "bar"
val 129319
""")
        tmpf.seek(0)
        s = read_stanza(tmpf)
        self.assertEquals(s, Stanza(version_header=1))
        s = read_stanza(tmpf)
        self.assertEquals(s, Stanza(name="foo", val=123))
        s = read_stanza(tmpf)
        self.assertEquals(s, Stanza(name="bar", val=129319))
        s = read_stanza(tmpf)
        self.assertEquals(s, None)

    def test_write_bool(self):
        """Write bool to basic_io"""
        l = list(Stanza(my_bool=True).to_lines())
        self.assertEquals(l, ['my_bool 1\n'])

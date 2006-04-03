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

"""Tests for rio serialization

A simple, reproducible structured IO format.

rio itself works in Unicode strings.  It is typically encoded to UTF-8,
but this depends on the transport.
"""

import cStringIO
import os
import sys
from tempfile import TemporaryFile

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.rio import RioWriter, Stanza, read_stanza, read_stanzas


class TestRio(TestCase):

    def test_stanza(self):
        """Construct rio stanza in memory"""
        s = Stanza(number='42', name="fred")
        self.assertTrue('number' in s)
        self.assertFalse('color' in s)
        self.assertFalse('42' in s)
        self.assertEquals(list(s.iter_pairs()),
                [('name', 'fred'), ('number', '42')])
        self.assertEquals(s.get('number'), '42')
        self.assertEquals(s.get('name'), 'fred')

    def test_value_checks(self):
        """rio checks types on construction"""
        # these aren't enforced at construction time
        ## self.assertRaises(ValueError,
        ##        Stanza, complex=42 + 3j)
        ## self.assertRaises(ValueError, 
        ##        Stanza, several=range(10))

    def test_empty_value(self):
        """Serialize stanza with empty field"""
        s = Stanza(empty='')
        self.assertEqualDiff(s.to_string(),
                "empty: \n")

    def test_to_lines(self):
        """Write simple rio stanza to string"""
        s = Stanza(number='42', name='fred')
        self.assertEquals(list(s.to_lines()),
                ['name: fred\n',
                 'number: 42\n'])

    def test_as_dict(self):
        """Convert rio Stanza to dictionary"""
        s = Stanza(number='42', name='fred')
        sd = s.as_dict()
        self.assertEquals(sd, dict(number='42', name='fred'))

    def test_to_file(self):
        """Write rio to file"""
        tmpf = TemporaryFile()
        s = Stanza(a_thing='something with "quotes like \\"this\\""', number='42', name='fred')
        s.write(tmpf)
        tmpf.seek(0)
        self.assertEqualDiff(tmpf.read(), r'''
a_thing: something with "quotes like \"this\""
name: fred
number: 42
'''[1:])

    def test_multiline_string(self):
        tmpf = TemporaryFile()
        s = Stanza(motto="war is peace\nfreedom is slavery\nignorance is strength")
        s.write(tmpf)
        tmpf.seek(0)
        self.assertEqualDiff(tmpf.read(), '''\
motto: war is peace
\tfreedom is slavery
\tignorance is strength
''')
        tmpf.seek(0)
        s2 = read_stanza(tmpf)
        self.assertEquals(s, s2)

    def test_read_stanza(self):
        """Load stanza from string"""
        lines = """\
revision: mbp@sourcefrog.net-123-abc
timestamp: 1130653962
timezone: 36000
committer: Martin Pool <mbp@test.sourcefrog.net>
""".splitlines(True)
        s = read_stanza(lines)
        self.assertTrue('revision' in s)
        self.assertEqualDiff(s.get('revision'), 'mbp@sourcefrog.net-123-abc')
        self.assertEquals(list(s.iter_pairs()),
                [('revision', 'mbp@sourcefrog.net-123-abc'),
                 ('timestamp', '1130653962'),
                 ('timezone', '36000'),
                 ('committer', "Martin Pool <mbp@test.sourcefrog.net>")])
        self.assertEquals(len(s), 4)

    def test_repeated_field(self):
        """Repeated field in rio"""
        s = Stanza()
        for k, v in [('a', '10'), ('b', '20'), ('a', '100'), ('b', '200'), 
                     ('a', '1000'), ('b', '2000')]:
            s.add(k, v)
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)
        self.assertEquals(s.get_all('a'), map(str, [10, 100, 1000]))
        self.assertEquals(s.get_all('b'), map(str, [20, 200, 2000]))

    def test_backslash(self):
        s = Stanza(q='\\')
        t = s.to_string()
        self.assertEqualDiff(t, 'q: \\\n')
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_blank_line(self):
        s = Stanza(none='', one='\n', two='\n\n')
        self.assertEqualDiff(s.to_string(), """\
none: 
one: 
\t
two: 
\t
\t
""")
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_whitespace_value(self):
        s = Stanza(space=' ', tabs='\t\t\t', combo='\n\t\t\n')
        self.assertEqualDiff(s.to_string(), """\
combo: 
\t\t\t
\t
space:  
tabs: \t\t\t
""")
        s2 = read_stanza(s.to_lines())
        self.assertEquals(s, s2)

    def test_quoted(self):
        """rio quoted string cases"""
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
        """Detect end of rio file"""
        s = read_stanza([])
        self.assertEqual(s, None)
        self.assertTrue(s is None)
        
    def test_read_iter(self):
        """Read several stanzas from file"""
        tmpf = TemporaryFile()
        tmpf.write("""\
version_header: 1

name: foo
val: 123

name: bar
val: 129319
""")
        tmpf.seek(0)
        reader = read_stanzas(tmpf)
        read_iter = iter(reader)
        stuff = list(reader)
        self.assertEqual(stuff, 
                [ Stanza(version_header='1'),
                  Stanza(name="foo", val='123'),
                  Stanza(name="bar", val='129319'), ])

    def test_read_several(self):
        """Read several stanzas from file"""
        tmpf = TemporaryFile()
        tmpf.write("""\
version_header: 1

name: foo
val: 123

name: quoted
address:   "Willowglen"
\t  42 Wallaby Way
\t  Sydney

name: bar
val: 129319
""")
        tmpf.seek(0)
        s = read_stanza(tmpf)
        self.assertEquals(s, Stanza(version_header='1'))
        s = read_stanza(tmpf)
        self.assertEquals(s, Stanza(name="foo", val='123'))
        s = read_stanza(tmpf)
        self.assertEqualDiff(s.get('name'), 'quoted')
        self.assertEqualDiff(s.get('address'), '  "Willowglen"\n  42 Wallaby Way\n  Sydney')
        s = read_stanza(tmpf)
        self.assertEquals(s, Stanza(name="bar", val='129319'))
        s = read_stanza(tmpf)
        self.assertEquals(s, None)

    def test_tricky_quoted(self):
        tmpf = TemporaryFile()
        tmpf.write('''\
s: "one"

s: 
\t"one"
\t

s: "

s: ""

s: """

s: 
\t

s: \\

s: 
\t\\
\t\\\\
\t

s: word\\

s: quote"

s: backslashes\\\\\\

s: both\\\"

''')
        tmpf.seek(0)
        expected_vals = ['"one"',
            '\n"one"\n',
            '"',
            '""',
            '"""',
            '\n',
            '\\',
            '\n\\\n\\\\\n',
            'word\\',
            'quote\"',
            'backslashes\\\\\\',
            'both\\\"',
            ]
        for expected in expected_vals:
            stanza = read_stanza(tmpf)
            self.assertEquals(len(stanza), 1)
            self.assertEqualDiff(stanza.get('s'), expected)

    def test_write_empty_stanza(self):
        """Write empty stanza"""
        l = list(Stanza().to_lines())
        self.assertEquals(l, [])

    def test_rio_raises_type_error(self):
        """TypeError on adding invalid type to Stanza"""
        s = Stanza()
        self.assertRaises(TypeError, s.add, 'foo', {})

    def test_rio_raises_type_error_key(self):
        """TypeError on adding invalid type to Stanza"""
        s = Stanza()
        self.assertRaises(TypeError, s.add, 10, {})

    def test_rio_unicode(self):
        # intentionally use cStringIO which doesn't accomodate unencoded unicode objects
        sio = cStringIO.StringIO()
        uni_data = u'\N{KATAKANA LETTER O}'
        s = Stanza(foo=uni_data)
        self.assertEquals(s.get('foo'), uni_data)
        raw_lines = s.to_lines()
        self.assertEquals(raw_lines,
                ['foo: ' + uni_data.encode('utf-8') + '\n'])
        new_s = read_stanza(raw_lines)
        self.assertEquals(new_s.get('foo'), uni_data)


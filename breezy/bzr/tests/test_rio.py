# Copyright (C) 2005, 2006, 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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

"""Tests for rio serialization

A simple, reproducible structured IO format.

rio itself works in Unicode strings.  It is typically encoded to UTF-8,
but this depends on the transport.
"""

import re
from tempfile import TemporaryFile

from breezy.tests import TestCase
from .. import (
    rio,
    )
from ..rio import (
    RioReader,
    Stanza,
    read_stanza,
    read_stanzas,
    rio_file,
    )


class TestRio(TestCase):

    def test_stanza(self):
        """Construct rio stanza in memory"""
        s = Stanza(number='42', name="fred")
        self.assertTrue('number' in s)
        self.assertFalse('color' in s)
        self.assertFalse('42' in s)
        self.assertEqual(list(s.iter_pairs()),
                         [('name', 'fred'), ('number', '42')])
        self.assertEqual(s.get('number'), '42')
        self.assertEqual(s.get('name'), 'fred')

    def test_empty_value(self):
        """Serialize stanza with empty field"""
        s = Stanza(empty='')
        self.assertEquals(s.to_string(),
                          b"empty: \n")

    def test_to_lines(self):
        """Write simple rio stanza to string"""
        s = Stanza(number='42', name='fred')
        self.assertEqual(list(s.to_lines()),
                         [b'name: fred\n',
                          b'number: 42\n'])

    def test_as_dict(self):
        """Convert rio Stanza to dictionary"""
        s = Stanza(number='42', name='fred')
        sd = s.as_dict()
        self.assertEqual(sd, dict(number='42', name='fred'))

    def test_to_file(self):
        """Write rio to file"""
        tmpf = TemporaryFile()
        s = Stanza(a_thing='something with "quotes like \\"this\\""',
                   number='42', name='fred')
        s.write(tmpf)
        tmpf.seek(0)
        self.assertEqual(tmpf.read(), b'''\
a_thing: something with "quotes like \\"this\\""
name: fred
number: 42
''')

    def test_multiline_string(self):
        tmpf = TemporaryFile()
        s = Stanza(
            motto="war is peace\nfreedom is slavery\nignorance is strength")
        s.write(tmpf)
        tmpf.seek(0)
        self.assertEqual(tmpf.read(), b'''\
motto: war is peace
\tfreedom is slavery
\tignorance is strength
''')
        tmpf.seek(0)
        s2 = read_stanza(tmpf)
        self.assertEqual(s, s2)

    def test_read_stanza(self):
        """Load stanza from string"""
        lines = b"""\
revision: mbp@sourcefrog.net-123-abc
timestamp: 1130653962
timezone: 36000
committer: Martin Pool <mbp@test.sourcefrog.net>
""".splitlines(True)
        s = read_stanza(lines)
        self.assertTrue('revision' in s)
        self.assertEqual(s.get('revision'), 'mbp@sourcefrog.net-123-abc')
        self.assertEqual(list(s.iter_pairs()),
                         [('revision', 'mbp@sourcefrog.net-123-abc'),
                          ('timestamp', '1130653962'),
                          ('timezone', '36000'),
                          ('committer', "Martin Pool <mbp@test.sourcefrog.net>")])
        self.assertEqual(len(s), 4)

    def test_repeated_field(self):
        """Repeated field in rio"""
        s = Stanza()
        for k, v in [('a', '10'), ('b', '20'), ('a', '100'), ('b', '200'),
                     ('a', '1000'), ('b', '2000')]:
            s.add(k, v)
        s2 = read_stanza(s.to_lines())
        self.assertEqual(s, s2)
        self.assertEqual(s.get_all('a'), ['10', '100', '1000'])
        self.assertEqual(s.get_all('b'), ['20', '200', '2000'])

    def test_backslash(self):
        s = Stanza(q='\\')
        t = s.to_string()
        self.assertEqual(t, b'q: \\\n')
        s2 = read_stanza(s.to_lines())
        self.assertEqual(s, s2)

    def test_blank_line(self):
        s = Stanza(none='', one='\n', two='\n\n')
        self.assertEqual(s.to_string(), b"""\
none:\x20
one:\x20
\t
two:\x20
\t
\t
""")
        s2 = read_stanza(s.to_lines())
        self.assertEqual(s, s2)

    def test_whitespace_value(self):
        s = Stanza(space=' ', tabs='\t\t\t', combo='\n\t\t\n')
        self.assertEqual(s.to_string(), b"""\
combo:\x20
\t\t\t
\t
space:\x20\x20
tabs: \t\t\t
""")
        s2 = read_stanza(s.to_lines())
        self.assertEqual(s, s2)
        self.rio_file_stanzas([s])

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
        self.assertEqual(s, s2)
        # apparent bug in read_stanza
        # s3 = read_stanza(self.stanzas_to_str([s]))
        # self.assertEqual(s, s3)

    def test_read_empty(self):
        """Detect end of rio file"""
        s = read_stanza([])
        self.assertEqual(s, None)
        self.assertTrue(s is None)

    def test_read_nul_byte(self):
        """File consisting of a nul byte causes an error."""
        self.assertRaises(ValueError, read_stanza, [b'\0'])

    def test_read_nul_bytes(self):
        """File consisting of many nul bytes causes an error."""
        self.assertRaises(ValueError, read_stanza, [b'\0' * 100])

    def test_read_iter(self):
        """Read several stanzas from file"""
        tmpf = TemporaryFile()
        tmpf.write(b"""\
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
                         [Stanza(version_header='1'),
                          Stanza(name="foo", val='123'),
                             Stanza(name="bar", val='129319'), ])

    def test_read_several(self):
        """Read several stanzas from file"""
        tmpf = TemporaryFile()
        tmpf.write(b"""\
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
        self.assertEqual(s, Stanza(version_header='1'))
        s = read_stanza(tmpf)
        self.assertEqual(s, Stanza(name="foo", val='123'))
        s = read_stanza(tmpf)
        self.assertEqual(s.get('name'), 'quoted')
        self.assertEqual(
            s.get('address'), '  "Willowglen"\n  42 Wallaby Way\n  Sydney')
        s = read_stanza(tmpf)
        self.assertEqual(s, Stanza(name="bar", val='129319'))
        s = read_stanza(tmpf)
        self.assertEqual(s, None)
        self.check_rio_file(tmpf)

    def check_rio_file(self, real_file):
        real_file.seek(0)
        read_write = rio_file(RioReader(real_file)).read()
        real_file.seek(0)
        self.assertEqual(read_write, real_file.read())

    @staticmethod
    def stanzas_to_str(stanzas):
        return rio_file(stanzas).read()

    def rio_file_stanzas(self, stanzas):
        new_stanzas = list(RioReader(rio_file(stanzas)))
        self.assertEqual(new_stanzas, stanzas)

    def test_tricky_quoted(self):
        tmpf = TemporaryFile()
        tmpf.write(b'''\
s: "one"

s:\x20
\t"one"
\t

s: "

s: ""

s: """

s:\x20
\t

s: \\

s:\x20
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
            self.rio_file_stanzas([stanza])
            self.assertEqual(len(stanza), 1)
            self.assertEqual(stanza.get('s'), expected)

    def test_write_empty_stanza(self):
        """Write empty stanza"""
        l = list(Stanza().to_lines())
        self.assertEqual(l, [])

    def test_rio_raises_type_error(self):
        """TypeError on adding invalid type to Stanza"""
        s = Stanza()
        self.assertRaises(TypeError, s.add, 'foo', {})

    def test_rio_raises_type_error_key(self):
        """TypeError on adding invalid type to Stanza"""
        s = Stanza()
        self.assertRaises(TypeError, s.add, 10, {})

    def test_rio_surrogateescape(self):
        raw_bytes = b'\xcb'
        self.assertRaises(UnicodeDecodeError, raw_bytes.decode, 'utf-8')
        try:
            uni_data = raw_bytes.decode('utf-8', 'surrogateescape')
        except LookupError:
            self.skipTest('surrogateescape is not available on Python < 3')
        s = Stanza(foo=uni_data)
        self.assertEqual(s.get('foo'), uni_data)
        raw_lines = s.to_lines()
        self.assertEqual(raw_lines,
                         [b'foo: ' + uni_data.encode('utf-8', 'surrogateescape') + b'\n'])
        new_s = read_stanza(raw_lines)
        self.assertEqual(new_s.get('foo'), uni_data)

    def test_rio_unicode(self):
        uni_data = u'\N{KATAKANA LETTER O}'
        s = Stanza(foo=uni_data)
        self.assertEqual(s.get('foo'), uni_data)
        raw_lines = s.to_lines()
        self.assertEqual(raw_lines,
                         [b'foo: ' + uni_data.encode('utf-8') + b'\n'])
        new_s = read_stanza(raw_lines)
        self.assertEqual(new_s.get('foo'), uni_data)

    def mail_munge(self, lines, dos_nl=True):
        new_lines = []
        for line in lines:
            line = re.sub(b' *\n', b'\n', line)
            if dos_nl:
                line = re.sub(b'([^\r])\n', b'\\1\r\n', line)
            new_lines.append(line)
        return new_lines

    def test_patch_rio(self):
        stanza = Stanza(data='#\n\r\\r ', space=' ' * 255, hash='#' * 255)
        lines = rio.to_patch_lines(stanza)
        for line in lines:
            self.assertContainsRe(line, b'^# ')
            self.assertTrue(72 >= len(line))
        for line in rio.to_patch_lines(stanza, max_width=12):
            self.assertTrue(12 >= len(line))
        new_stanza = rio.read_patch_stanza(self.mail_munge(lines,
                                                           dos_nl=False))
        lines = self.mail_munge(lines)
        new_stanza = rio.read_patch_stanza(lines)
        self.assertEqual('#\n\r\\r ', new_stanza.get('data'))
        self.assertEqual(' ' * 255, new_stanza.get('space'))
        self.assertEqual('#' * 255, new_stanza.get('hash'))

    def test_patch_rio_linebreaks(self):
        stanza = Stanza(breaktest='linebreak -/' * 30)
        self.assertContainsRe(rio.to_patch_lines(stanza, 71)[0],
                              b'linebreak\\\\\n')
        stanza = Stanza(breaktest='linebreak-/' * 30)
        self.assertContainsRe(rio.to_patch_lines(stanza, 70)[0],
                              b'linebreak-\\\\\n')
        stanza = Stanza(breaktest='linebreak/' * 30)
        self.assertContainsRe(rio.to_patch_lines(stanza, 70)[0],
                              b'linebreak\\\\\n')

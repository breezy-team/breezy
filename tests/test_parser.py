# Copyright (C) 2008 Canonical Ltd
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

"""Test the Import parsing"""

import StringIO

from bzrlib import tests

from bzrlib.plugins.fastimport import (
    errors,
    parser,
    )


class TestLineBasedParser(tests.TestCase):

    def test_push_line(self):
        s = StringIO.StringIO("foo\nbar\nbaz\n")
        p = parser.LineBasedParser(s)
        self.assertEqual('foo', p.next_line())
        self.assertEqual('bar', p.next_line())
        p.push_line('bar')
        self.assertEqual('bar', p.next_line())
        self.assertEqual('baz', p.next_line())
        self.assertEqual(None, p.next_line())

    def test_read_bytes(self):
        s = StringIO.StringIO("foo\nbar\nbaz\n")
        p = parser.LineBasedParser(s)
        self.assertEqual('fo', p.read_bytes(2))
        self.assertEqual('o\nb', p.read_bytes(3))
        self.assertEqual('ar', p.next_line())
        # Test that the line buffer is ignored
        p.push_line('bar')
        self.assertEqual('baz', p.read_bytes(3))
        # Test missing bytes
        self.assertRaises(errors.MissingBytes, p.read_bytes, 10)

    def test_read_until(self):
        # TODO
        return
        s = StringIO.StringIO("foo\nbar\nbaz\nabc\ndef\nghi\n")
        p = parser.LineBasedParser(s)
        self.assertEqual('foo\nbar', p.read_until('baz'))
        self.assertEqual('abc', p.next_line())
        # Test that the line buffer is ignored
        p.push_line('abc')
        self.assertEqual('def', p.read_until('ghi'))
        # Test missing terminator
        self.assertRaises(errors.MissingTerminator, p.read_until('>>>'))


# Sample text
_sample_import_text = """
progress completed
# Test blob formats
blob
mark :1
data 4
aaaa
blob
data 5
bbbbb
# Commit formats
commit 
committer bugs <bugs@bunny.org> now
data 14
initial import
from :1
M 644 inline README
data 18
Welcome from bugs
# Miscellaneous
checkpoint
progress completed
"""


class TestImportParser(tests.TestCase):

    def test_iter_commands(self):
        s = StringIO.StringIO(_sample_import_text)
        p = parser.ImportParser(s)
        result = []
        for cmd in p.iter_commands():
            result.append(cmd)
            if cmd.name == 'commit':
                for fc in cmd.file_iter():
                    result.append(fc)
        cmd1 = result[0]
        self.assertEqual('progress', cmd1.name)


class TestStringParsing(tests.TestCase):

    def test_unquote(self):
        s = r'hello \"sweet\" wo\\r\tld'
        self.assertEquals(r'hello "sweet" wo\r' + "\tld",
            parser._unquote_c_string(s))

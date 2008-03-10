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
aaaablob
data 5
bbbbb
# Commit formats
commit refs/heads/master
mark :2
committer bugs bunny <bugs@bunny.org> now
data 14
initial import
M 644 inline README
data 18
Welcome from bugs
commit refs/heads/master
committer <bugs@bunny.org> now
data 13
second commit
from :2
M 644 inline README
data 23
Welcome from bugs, etc.
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
        self.assertEqual(len(result), 9)
        cmd1 = result[0]
        self.assertEqual('progress', cmd1.name)
        self.assertEqual('completed', cmd1.message)
        cmd2 = result[1]
        self.assertEqual('blob', cmd2.name)
        self.assertEqual('1', cmd2.mark)
        self.assertEqual(':1', cmd2.id)
        self.assertEqual('aaaa', cmd2.data)
        self.assertEqual(4, cmd2.lineno)
        cmd3 = result[2]
        self.assertEqual('blob', cmd3.name)
        self.assertEqual('@7', cmd3.id)
        self.assertEqual(None, cmd3.mark)
        self.assertEqual('bbbbb', cmd3.data)
        self.assertEqual(7, cmd3.lineno)
        cmd4 = result[3]
        self.assertEqual('commit', cmd4.name)
        self.assertEqual('2', cmd4.mark)
        self.assertEqual(':2', cmd4.id)
        self.assertEqual('initial import', cmd4.message)
        self.assertEqual('bugs bunny', cmd4.committer[0])
        self.assertEqual('bugs@bunny.org', cmd4.committer[1])
        # FIXME: check timestamp and timezone as well
        self.assertEqual(None, cmd4.author)
        self.assertEqual(11, cmd4.lineno)
        self.assertEqual('refs/heads/master', cmd4.ref)
        self.assertEqual([], cmd4.parents)
        file_cmd1 = result[4]
        self.assertEqual('filemodify', file_cmd1.name)
        self.assertEqual('README', file_cmd1.path)
        self.assertEqual('file', file_cmd1.kind)
        self.assertEqual(False, file_cmd1.is_executable)
        self.assertEqual('Welcome from bugs\n', file_cmd1.data)
        cmd5 = result[5]
        self.assertEqual('commit', cmd5.name)
        self.assertEqual(None, cmd5.mark)
        self.assertEqual('@19', cmd5.id)
        self.assertEqual('second commit', cmd5.message)
        self.assertEqual('', cmd5.committer[0])
        self.assertEqual('bugs@bunny.org', cmd5.committer[1])
        # FIXME: check timestamp and timezone as well
        self.assertEqual(None, cmd5.author)
        self.assertEqual(19, cmd5.lineno)
        self.assertEqual('refs/heads/master', cmd5.ref)
        self.assertEqual([':2'], cmd5.parents)
        file_cmd2 = result[6]
        self.assertEqual('filemodify', file_cmd2.name)
        self.assertEqual('README', file_cmd2.path)
        self.assertEqual('file', file_cmd2.kind)
        self.assertEqual(False, file_cmd2.is_executable)
        self.assertEqual('Welcome from bugs, etc.', file_cmd2.data)
        cmd6 = result[7]
        self.assertEqual(cmd6.name, 'checkpoint')
        cmd7 = result[8]
        self.assertEqual('progress', cmd7.name)
        self.assertEqual('completed', cmd7.message)


class TestStringParsing(tests.TestCase):

    def test_unquote(self):
        s = r'hello \"sweet\" wo\\r\tld'
        self.assertEquals(r'hello "sweet" wo\r' + "\tld",
            parser._unquote_c_string(s))

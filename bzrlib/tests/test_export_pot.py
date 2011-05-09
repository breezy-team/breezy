# Copyright (C) 2011 Canonical Ltd
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

from cStringIO import StringIO

from bzrlib import (
    export_pot,
    tests,
    )

class TestEscape(tests.TestCase):

    def test_simple_escape(self):
        self.assertEqual(
                export_pot._escape('foobar'),
                'foobar')

        s = '''foo\nbar\r\tbaz\\"spam"'''
        e = '''foo\\nbar\\r\\tbaz\\\\\\"spam\\"'''
        self.assertEqual(export_pot._escape(s), e)

    def test_complex_escape(self):
        s = '''\\r \\\n'''
        e = '''\\\\r \\\\\\n'''
        self.assertEqual(export_pot._escape(s), e)


class TestNormalize(tests.TestCase):

    def test_single_line(self):
        s = 'foobar'
        e = '"foobar"'
        self.assertEqual(export_pot._normalize(s), e)

        s = 'foo"bar'
        e = '"foo\\"bar"'
        self.assertEqual(export_pot._normalize(s), e)

    def test_multi_lines(self):
        s = 'foo\nbar\n'
        e = '""\n"foo\\n"\n"bar\\n"'
        self.assertEqual(export_pot._normalize(s), e)

        s = '\nfoo\nbar\n'
        e = ('""\n'
             '"\\n"\n'
             '"foo\\n"\n'
             '"bar\\n"')
        self.assertEqual(export_pot._normalize(s), e)


class TestPoEntry(tests.TestCase):

    def setUp(self):
        self.overrideAttr(export_pot, '_FOUND_MSGID', set())
        self._outf = StringIO()
        super(TestPoEntry, self).setUp()

    def test_simple(self):
        export_pot._poentry( self._outf, 'dummy', 1, "spam")
        export_pot._poentry( self._outf, 'dummy', 2, "ham", 'EGG')
        self.assertEqual(
                self._outf.getvalue(),
                '''#: dummy:1\n'''
                '''msgid "spam"\n'''
                '''msgstr ""\n'''
                '''\n'''
                '''#: dummy:2\n'''
                '''# EGG\n'''
                '''msgid "ham"\n'''
                '''msgstr ""\n'''
                '''\n'''
                )

    def test_duplicate(self):
        export_pot._poentry(self._outf, 'dummy', 1, "spam")
        # This should be ignored.
        export_pot._poentry(self._outf, 'dummy', 2, "spam", 'EGG')

        self.assertEqual(
                self._outf.getvalue(),
                '''#: dummy:1\n'''
                '''msgid "spam"\n'''
                '''msgstr ""\n'''
                '''\n'''
                )


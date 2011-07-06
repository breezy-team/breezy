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
import textwrap

from bzrlib import (
    commands,
    export_pot,
    tests,
    )

import re


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


class PoEntryTestCase(tests.TestCase):

    def setUp(self):
        self.overrideAttr(export_pot, '_FOUND_MSGID', set())
        self._outf = StringIO()
        super(PoEntryTestCase, self).setUp()

    def check_output(self, expected):
        self.assertEqual(
                self._outf.getvalue(),
                textwrap.dedent(expected)
                )

class TestPoEntry(PoEntryTestCase):

    def test_simple(self):
        export_pot._poentry(self._outf, 'dummy', 1, "spam")
        export_pot._poentry(self._outf, 'dummy', 2, "ham", 'EGG')
        self.check_output('''\
                #: dummy:1
                msgid "spam"
                msgstr ""

                #: dummy:2
                # EGG
                msgid "ham"
                msgstr ""

                ''')

    def test_duplicate(self):
        export_pot._poentry(self._outf, 'dummy', 1, "spam")
        # This should be ignored.
        export_pot._poentry(self._outf, 'dummy', 2, "spam", 'EGG')

        self.check_output('''\
                #: dummy:1
                msgid "spam"
                msgstr ""\n
                ''')


class TestPoentryPerPergraph(PoEntryTestCase):

    def test_single(self):
        export_pot._poentry_per_paragraph(
                self._outf,
                'dummy',
                10,
                '''foo\nbar\nbaz\n'''
                )
        self.check_output('''\
                #: dummy:10
                msgid ""
                "foo\\n"
                "bar\\n"
                "baz\\n"
                msgstr ""\n
                ''')

    def test_multi(self):
        export_pot._poentry_per_paragraph(
                self._outf,
                'dummy',
                10,
                '''spam\nham\negg\n\nSPAM\nHAM\nEGG\n'''
                )
        self.check_output('''\
                #: dummy:10
                msgid ""
                "spam\\n"
                "ham\\n"
                "egg"
                msgstr ""

                #: dummy:14
                msgid ""
                "SPAM\\n"
                "HAM\\n"
                "EGG\\n"
                msgstr ""\n
                ''')


class TestExportCommandHelp(PoEntryTestCase):

    def test_command_help(self):

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            :Usage:
                bzr demo

            :Examples:
                Example 1::

                    cmd arg1

            Blah Blah Blah
            """

        export_pot._write_command_help(self._outf, cmd_Demo())
        result = self._outf.getvalue()
        # We don't care about filename and lineno here.
        result = re.sub(r'(?m)^#: [^\n]+\n', '', result)

        self.assertEqualDiff(
                'msgid "A sample command."\n'
                'msgstr ""\n'
                '\n'                # :Usage: should not be translated.
                'msgid ""\n'
                '":Examples:\\n"\n'
                '"    Example 1::"\n'
                'msgstr ""\n'
                '\n'
                'msgid "        cmd arg1"\n'
                'msgstr ""\n'
                '\n'
                'msgid "Blah Blah Blah"\n'
                'msgstr ""\n'
                '\n',
                result
                )

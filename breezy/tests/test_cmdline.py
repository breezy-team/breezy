# Copyright (C) 2010 Canonical Ltd
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


from .. import (
    cmdline,
    tests,
    )
from .features import backslashdir_feature


class TestSplitter(tests.TestCase):

    def assertAsTokens(self, expected, line, single_quotes_allowed=False):
        s = cmdline.Splitter(line, single_quotes_allowed=single_quotes_allowed)
        self.assertEqual(expected, list(s))

    def test_simple(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar'), (False, u'baz')],
                            u'foo bar baz')

    def test_ignore_multiple_spaces(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar')], u'foo  bar')

    def test_ignore_leading_space(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar')], u'  foo bar')

    def test_ignore_trailing_space(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar')], u'foo bar  ')

    def test_posix_quotations(self):
        self.assertAsTokens([(True, u'foo bar')], u"'foo bar'",
                            single_quotes_allowed=True)
        self.assertAsTokens([(True, u'foo bar')], u"'fo''o b''ar'",
                            single_quotes_allowed=True)
        self.assertAsTokens([(True, u'foo bar')], u'"fo""o b""ar"',
                            single_quotes_allowed=True)
        self.assertAsTokens([(True, u'foo bar')], u'"fo"\'o b\'"ar"',
                            single_quotes_allowed=True)

    def test_nested_quotations(self):
        self.assertAsTokens([(True, u'foo"" bar')], u"\"foo\\\"\\\" bar\"")
        self.assertAsTokens([(True, u'foo\'\' bar')], u"\"foo'' bar\"")
        self.assertAsTokens([(True, u'foo\'\' bar')], u"\"foo'' bar\"",
                            single_quotes_allowed=True)
        self.assertAsTokens([(True, u'foo"" bar')], u"'foo\"\" bar'",
                            single_quotes_allowed=True)

    def test_empty_result(self):
        self.assertAsTokens([], u'')
        self.assertAsTokens([], u'    ')

    def test_quoted_empty(self):
        self.assertAsTokens([(True, '')], u'""')
        self.assertAsTokens([(False, u"''")], u"''")
        self.assertAsTokens([(True, '')], u"''", single_quotes_allowed=True)
        self.assertAsTokens([(False, u'a'), (True, u''), (False, u'c')],
                            u'a "" c')
        self.assertAsTokens([(False, u'a'), (True, u''), (False, u'c')],
                            u"a '' c", single_quotes_allowed=True)

    def test_unicode_chars(self):
        self.assertAsTokens([(False, u'f\xb5\xee'), (False, u'\u1234\u3456')],
                            u'f\xb5\xee \u1234\u3456')

    def test_newline_in_quoted_section(self):
        self.assertAsTokens([(True, u'foo\nbar\nbaz\n')], u'"foo\nbar\nbaz\n"')
        self.assertAsTokens([(True, u'foo\nbar\nbaz\n')], u"'foo\nbar\nbaz\n'",
                            single_quotes_allowed=True)

    def test_escape_chars(self):
        self.assertAsTokens([(False, u'foo\\bar')], u'foo\\bar')

    def test_escape_quote(self):
        self.assertAsTokens([(True, u'foo"bar')], u'"foo\\"bar"')
        self.assertAsTokens([(True, u'foo\\"bar')], u'"foo\\\\\\"bar"')
        self.assertAsTokens([(True, u'foo\\bar')], u'"foo\\\\"bar"')

    def test_double_escape(self):
        self.assertAsTokens([(True, u'foo\\\\bar')], u'"foo\\\\bar"')
        self.assertAsTokens([(False, u'foo\\\\bar')], u"foo\\\\bar")

    def test_multiple_quoted_args(self):
        self.assertAsTokens([(True, u'x x'), (True, u'y y')],
                            u'"x x" "y y"')
        self.assertAsTokens([(True, u'x x'), (True, u'y y')],
                            u'"x x" \'y y\'', single_quotes_allowed=True)

    def test_n_backslashes_handling(self):
        # https://bugs.launchpad.net/bzr/+bug/528944
        # actually we care about the doubled backslashes when they're
        # represents UNC paths.
        # But in fact there is too much weird corner cases
        # (see https://bugs.launchpad.net/tortoisebzr/+bug/569050)
        # so to reproduce every bit of windows command-line handling
        # could be not worth of efforts?
        self.requireFeature(backslashdir_feature)
        self.assertAsTokens([(True, r'\\host\path')], r'"\\host\path"')
        self.assertAsTokens([(False, r'\\host\path')], r'\\host\path')
        # handling of " after the 2n and 2n+1 backslashes
        # inside and outside the quoted string
        self.assertAsTokens([(True, r'\\'), (False, r'*.py')], r'"\\\\" *.py')
        self.assertAsTokens([(True, r'\\" *.py')], r'"\\\\\" *.py"')
        self.assertAsTokens([(True, r'\\ *.py')], r'\\\\" *.py"')
        self.assertAsTokens([(False, r'\\"'), (False, r'*.py')],
                            r'\\\\\" *.py')
        self.assertAsTokens([(True, u'\\\\')], u'"\\\\')

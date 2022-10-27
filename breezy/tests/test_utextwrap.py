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
#

"""Tests of the breezy.utextwrap."""

from .. import (
    tests,
    utextwrap,
    )


# Japanese "Good morning".
# Each character have double width. So total 8 width on console.
_str_D = u'\u304a\u306f\u3088\u3046'

_str_S = u"hello"

# Combine single width characters and double width characters.
_str_SD = _str_S + _str_D
_str_DS = _str_D + _str_S


class TestUTextWrap(tests.TestCase):

    def check_width(self, text, expected_width):
        w = utextwrap.UTextWrapper()
        self.assertEqual(
            w._width(text),
            expected_width,
            "Width of %r should be %d" % (text, expected_width))

    def test_width(self):
        self.check_width(_str_D, 8)
        self.check_width(_str_SD, 13)

    def check_cut(self, text, width, pos):
        w = utextwrap.UTextWrapper()
        self.assertEqual((text[:pos], text[pos:]), w._cut(text, width))

    def test_cut(self):
        s = _str_SD
        self.check_cut(s, 0, 0)
        self.check_cut(s, 1, 1)
        self.check_cut(s, 5, 5)
        self.check_cut(s, 6, 5)
        self.check_cut(s, 7, 6)
        self.check_cut(s, 12, 8)
        self.check_cut(s, 13, 9)
        self.check_cut(s, 14, 9)
        self.check_cut(u'A' * 5, 3, 3)

    def test_split(self):
        w = utextwrap.UTextWrapper()
        self.assertEqual(list(_str_D), w._split(_str_D))
        self.assertEqual([_str_S] + list(_str_D), w._split(_str_SD))
        self.assertEqual(list(_str_D) + [_str_S], w._split(_str_DS))

    def test_wrap(self):
        self.assertEqual(list(_str_D), utextwrap.wrap(_str_D, 1))
        self.assertEqual(list(_str_D), utextwrap.wrap(_str_D, 2))
        self.assertEqual(list(_str_D), utextwrap.wrap(_str_D, 3))
        self.assertEqual(list(_str_D),
                         utextwrap.wrap(_str_D, 3, break_long_words=False))


class TestUTextFill(tests.TestCase):

    def test_fill_simple(self):
        # Test only can call fill() because it's just '\n'.join(wrap(text)).
        self.assertEqual("%s\n%s" % (_str_D[:2], _str_D[2:]),
                         utextwrap.fill(_str_D, 4))

    def test_fill_with_breaks(self):
        # Demonstrate complicated case.
        text = u"spam ham egg spamhamegg" + _str_D + u" spam" + _str_D * 2
        self.assertEqual(u'\n'.join(["spam ham",
                                     "egg spam",
                                     "hamegg" + _str_D[0],
                                     _str_D[1:],
                                     "spam" + _str_D[:2],
                                     _str_D[2:] + _str_D[:2],
                                     _str_D[2:]]),
                         utextwrap.fill(text, 8))

    def test_fill_without_breaks(self):
        text = u"spam ham egg spamhamegg" + _str_D + u" spam" + _str_D * 2
        self.assertEqual(u'\n'.join(["spam ham",
                                     "egg",
                                     "spamhamegg",
                                     # border between single width and double
                                     # width.
                                     _str_D,
                                     "spam" + _str_D[:2],
                                     _str_D[2:] + _str_D[:2],
                                     _str_D[2:]]),
                         utextwrap.fill(text, 8, break_long_words=False))

    def test_fill_indent_with_breaks(self):
        w = utextwrap.UTextWrapper(8, initial_indent=' ' * 4,
                                   subsequent_indent=' ' * 4)
        self.assertEqual(u'\n'.join(["    hell",
                                     "    o" + _str_D[0],
                                     "    " + _str_D[1:3],
                                     "    " + _str_D[3]
                                     ]),
                         w.fill(_str_SD))

    def test_fill_indent_without_breaks(self):
        w = utextwrap.UTextWrapper(8, initial_indent=' ' * 4,
                                   subsequent_indent=' ' * 4)
        w.break_long_words = False
        self.assertEqual(u'\n'.join(["    hello",
                                     "    " + _str_D[:2],
                                     "    " + _str_D[2:],
                                     ]),
                         w.fill(_str_SD))

    def test_fill_indent_without_breaks_with_fixed_width(self):
        w = utextwrap.UTextWrapper(8, initial_indent=' ' * 4,
                                   subsequent_indent=' ' * 4)
        w.break_long_words = False
        w.width = 3
        self.assertEqual(u'\n'.join(["    hello",
                                     "    " + _str_D[0],
                                     "    " + _str_D[1],
                                     "    " + _str_D[2],
                                     "    " + _str_D[3],
                                     ]),
                         w.fill(_str_SD))


class TestUTextWrapAmbiWidth(tests.TestCase):
    _cyrill_char = u"\u0410"  # east_asian_width() == 'A'

    def test_ambiwidth1(self):
        w = utextwrap.UTextWrapper(4, ambiguous_width=1)
        s = self._cyrill_char * 8
        self.assertEqual([self._cyrill_char * 4] * 2, w.wrap(s))

    def test_ambiwidth2(self):
        w = utextwrap.UTextWrapper(4, ambiguous_width=2)
        s = self._cyrill_char * 8
        self.assertEqual([self._cyrill_char * 2] * 4, w.wrap(s))


# Regression test with Python's test_textwrap
# Note that some distribution including Ubuntu doesn't install
# Python's test suite.
try:
    from test import test_textwrap

    def override_textwrap_symbols(testcase):
        # Override the symbols imported by test_textwrap so it uses our own
        # replacements.
        testcase.overrideAttr(test_textwrap, 'TextWrapper',
                              utextwrap.UTextWrapper)
        testcase.overrideAttr(test_textwrap, 'wrap', utextwrap.wrap)
        testcase.overrideAttr(test_textwrap, 'fill', utextwrap.fill)

    def setup_both(testcase, base_class, reused_class):
        super(base_class, testcase).setUp()
        override_textwrap_symbols(testcase)
        reused_class.setUp(testcase)

    class TestWrap(tests.TestCase, test_textwrap.WrapTestCase):

        def setUp(self):
            setup_both(self, TestWrap, test_textwrap.WrapTestCase)

    class TestLongWord(tests.TestCase, test_textwrap.LongWordTestCase):

        def setUp(self):
            setup_both(self, TestLongWord, test_textwrap.LongWordTestCase)

    class TestIndent(tests.TestCase, test_textwrap.IndentTestCases):

        def setUp(self):
            setup_both(self, TestIndent, test_textwrap.IndentTestCases)


except ImportError:

    class TestWrap(tests.TestCase):

        def test_wrap(self):
            raise tests.TestSkipped("test.test_textwrap is not available.")

    class TestLongWord(tests.TestCase):

        def test_longword(self):
            raise tests.TestSkipped("test.test_textwrap is not available.")

    class TestIndent(tests.TestCase):

        def test_indent(self):
            raise tests.TestSkipped("test.test_textwrap is not available.")

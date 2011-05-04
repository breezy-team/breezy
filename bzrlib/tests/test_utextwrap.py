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

"""Tests of the bzrlib.utextwrap."""

from bzrlib import tests, utextwrap

# Japanese "Good morning".
# Each character have double width. So total 8 width on console.
_str_D = u'\u304a\u306f\u3088\u3046'

_str_S = u"hello"

# Combine single width characters and double width characters.
_str_SD = _str_S + _str_D
_str_DS = _str_D + _str_S

class TestUTextWrap(tests.TestCase):

    def assertWidth(self, text, expected_width):
        self.assertEqual(
                utextwrap._width(text),
                expected_width,
                "Width of %r should be %d" % (text, expected_width))

    def test__width(self):
        self.assertWidth(_str_D, 8)
        self.assertWidth(_str_SD, 13)

    def test__break_cjkword(self):
        self.assertEqual(utextwrap._break_cjkword(u"hello", 3), ('', _str_S))
        self.assertEqual(utextwrap._break_cjkword(_str_D, 1), ('', _str_D))

        half = _str_D[:2], _str_D[2:]
        self.assertEqual(utextwrap._break_cjkword(_str_D, 4), half)
        self.assertEqual(utextwrap._break_cjkword(_str_D, 5), half)

        # word should be split between double width character and single
        # width character.
        self.assertEqual(utextwrap._break_cjkword(_str_DS, 10),
                         (_str_D, _str_S))

        self.assertEqual(utextwrap._break_cjkword(_str_D, 8), (_str_D, ''))

    def test_wrap(self):
        self.assertEqual(utextwrap.wrap(_str_D, 1), list(_str_D))
        self.assertEqual(utextwrap.wrap(_str_D, 2), list(_str_D))
        self.assertEqual(utextwrap.wrap(_str_D, 3), list(_str_D))
        self.assertEqual(utextwrap.wrap(_str_D, 3, break_long_words=False),
                list(_str_D))

    def test_fill(self):
        # Test only can call fill() because it's just '\n'.join(wrap(text)).
        self.assertEqual(utextwrap.fill(_str_D, 4),
                "%s\n%s" % (_str_D[:2], _str_D[2:]))

# Regression test with Python's test_textwrap
# Note that some distribution including Ubuntu doesn't install
# Python's test suite.
try:
    import test.test_textwrap as _test_textwrap

    # replace test_textwrap's TextWrapper with UTextWrapper
    _test_textwrap.TextWrapper = utextwrap.UTextWrapper
    _test_textwrap.wrap = utextwrap.wrap
    _test_textwrap.fill = utextwrap.fill

    class TestWrap(_test_textwrap.WrapTestCase):
        pass
    class TestLongWord(_test_textwrap.LongWordTestCase):
        pass
    class TestIndent(_test_textwrap.IndentTestCases):
        pass
except ImportError:
    pass


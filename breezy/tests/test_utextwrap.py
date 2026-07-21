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

from .. import tests, utextwrap

# Japanese "Good morning".
# Each character has double width. So total 8 width on console.
_str_d = "おはよう"

_str_s = "hello"

# Combine single width characters and double width characters.
_str_sd = _str_s + _str_d


class TestUTextWrap(tests.TestCase):
    def test_wrap_double_width(self):
        # A run of double width characters breaks between any two of them.
        self.assertEqual(list(_str_d), utextwrap.wrap(_str_d, 1))
        self.assertEqual(list(_str_d), utextwrap.wrap(_str_d, 2))
        self.assertEqual(list(_str_d), utextwrap.wrap(_str_d, 3))
        self.assertEqual(
            list(_str_d), utextwrap.wrap(_str_d, 3, break_long_words=False)
        )

    def test_wrap_mixed_width(self):
        # "hello" fills a width-5 line, then the double-width run packs two
        # characters per line.
        self.assertEqual([_str_s, _str_d[:2], _str_d[2:]], utextwrap.wrap(_str_sd, 5))


class TestUTextFill(tests.TestCase):
    def test_fill_simple(self):
        self.assertEqual(f"{_str_d[:2]}\n{_str_d[2:]}", utextwrap.fill(_str_d, 4))

    def test_fill_with_breaks(self):
        # Demonstrate a complicated case where double-width characters are
        # split across lines while single-width words wrap normally.
        text = "spam ham egg spamhamegg" + _str_d + " spam" + _str_d * 2
        self.assertEqual(
            "\n".join(
                [
                    "spam ham",
                    "egg spam",
                    "hamegg" + _str_d[0],
                    _str_d[1:],
                    "spam" + _str_d[:2],
                    _str_d[2:] + _str_d[:2],
                    _str_d[2:],
                ]
            ),
            utextwrap.fill(text, 8),
        )

    def test_fill_without_breaks(self):
        text = "spam ham egg spamhamegg" + _str_d + " spam" + _str_d * 2
        self.assertEqual(
            "\n".join(
                [
                    "spam ham",
                    "egg",
                    "spamhamegg",
                    # border between single width and double width.
                    _str_d,
                    "spam" + _str_d[:2],
                    _str_d[2:] + _str_d[:2],
                    _str_d[2:],
                ]
            ),
            utextwrap.fill(text, 8, break_long_words=False),
        )

    def test_fill_indent_with_breaks(self):
        self.assertEqual(
            "\n".join(
                [
                    "    hell",
                    "    o" + _str_d[0],
                    "    " + _str_d[1:3],
                    "    " + _str_d[3],
                ]
            ),
            utextwrap.fill(
                _str_sd, 8, initial_indent=" " * 4, subsequent_indent=" " * 4
            ),
        )

    def test_fill_indent_without_breaks(self):
        self.assertEqual(
            "\n".join(
                [
                    "    hello",
                    "    " + _str_d[:2],
                    "    " + _str_d[2:],
                ]
            ),
            utextwrap.fill(
                _str_sd,
                8,
                initial_indent=" " * 4,
                subsequent_indent=" " * 4,
                break_long_words=False,
            ),
        )


class TestUTextWrapAmbiWidth(tests.TestCase):
    _cyrill_char = "\u0410"  # east_asian_width() == 'A'

    def test_ambiwidth1(self):
        s = self._cyrill_char * 8
        self.assertEqual(
            [self._cyrill_char * 4] * 2, utextwrap.wrap(s, 4, ambiguous_width=1)
        )

    def test_ambiwidth2(self):
        s = self._cyrill_char * 8
        self.assertEqual(
            [self._cyrill_char * 2] * 4, utextwrap.wrap(s, 4, ambiguous_width=2)
        )


class TestUTextWrapErrors(tests.TestCase):
    def test_invalid_width(self):
        self.assertRaises(ValueError, utextwrap.wrap, "hello", 0)
        self.assertRaises(ValueError, utextwrap.wrap, "hello", -1)

    def test_invalid_ambiguous_width(self):
        self.assertRaises(ValueError, utextwrap.wrap, "hello", 4, ambiguous_width=3)

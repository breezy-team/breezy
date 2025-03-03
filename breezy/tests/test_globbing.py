# Copyright (C) 2006-2011 Canonical Ltd
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

import re

from .. import lazy_regex
from ..globbing import ExceptionGlobster, Globster, _OrderedGlobster, normalize_pattern
from . import TestCase


class TestGlobster(TestCase):
    def assertMatch(self, matchset, glob_prefix=None):
        for glob, positive, negative in matchset:
            if glob_prefix:
                glob = glob_prefix + glob
            globster = Globster([glob])
            for name in positive:
                self.assertTrue(
                    globster.match(name),
                    repr(
                        'name "{}" does not match glob "{}" (re={})'.format(
                            name, glob, globster._regex_patterns[0][0].pattern
                        )
                    ),
                )
            for name in negative:
                self.assertFalse(
                    globster.match(name),
                    repr(
                        'name "{}" does match glob "{}" (re={})'.format(
                            name, glob, globster._regex_patterns[0][0].pattern
                        )
                    ),
                )

    def assertMatchBasenameAndFullpath(self, matchset):
        # test basename matcher
        self.assertMatch(matchset)
        # test fullpath matcher
        self.assertMatch(matchset, glob_prefix="./")

    def test_char_group_digit(self):
        self.assertMatchBasenameAndFullpath(
            [
                # The definition of digit this uses includes arabic digits from
                # non-latin scripts (arabic, indic, etc.) but neither roman
                # numerals nor vulgar fractions. Some characters such as
                # subscript/superscript digits may or may not match depending on
                # the Python version used, see: <http://bugs.python.org/issue6561>
                (
                    "[[:digit:]]",
                    ["0", "5", "\u0663", "\u06f9", "\u0f21"],
                    ["T", "q", " ", "\u8336", "."],
                ),
                (
                    "[^[:digit:]]",
                    ["T", "q", " ", "\u8336", "."],
                    ["0", "5", "\u0663", "\u06f9", "\u0f21"],
                ),
            ]
        )

    def test_char_group_space(self):
        self.assertMatchBasenameAndFullpath(
            [
                (
                    "[[:space:]]",
                    [" ", "\t", "\n", "\xa0", "\u2000", "\u2002"],
                    ["a", "-", "\u8336", "."],
                ),
                (
                    "[^[:space:]]",
                    ["a", "-", "\u8336", "."],
                    [" ", "\t", "\n", "\xa0", "\u2000", "\u2002"],
                ),
            ]
        )

    def test_char_group_alnum(self):
        self.assertMatchBasenameAndFullpath(
            [
                (
                    "[[:alnum:]]",
                    ["a", "Z", "\u017e", "\u8336"],
                    [":", "-", "\u25cf", "."],
                ),
                ("[^[:alnum:]]", [":", "-", "\u25cf", "."], ["a"]),
            ]
        )

    def test_char_group_ascii(self):
        self.assertMatchBasenameAndFullpath(
            [
                ("[[:ascii:]]", ["a", "Q", "^", "."], ["\xcc", "\u8336"]),
                ("[^[:ascii:]]", ["\xcc", "\u8336"], ["a", "Q", "^", "."]),
            ]
        )

    def test_char_group_blank(self):
        self.assertMatchBasenameAndFullpath(
            [
                ("[[:blank:]]", ["\t"], ["x", "y", "z", "."]),
                ("[^[:blank:]]", ["x", "y", "z", "."], ["\t"]),
            ]
        )

    def test_char_group_cntrl(self):
        self.assertMatchBasenameAndFullpath(
            [
                ("[[:cntrl:]]", ["\b", "\t", "\x7f"], ["a", "Q", "\u8336", "."]),
                ("[^[:cntrl:]]", ["a", "Q", "\u8336", "."], ["\b", "\t", "\x7f"]),
            ]
        )

    def test_char_group_range(self):
        self.assertMatchBasenameAndFullpath(
            [
                ("[a-z]", ["a", "q", "f"], ["A", "Q", "F"]),
                ("[^a-z]", ["A", "Q", "F"], ["a", "q", "f"]),
                ("[!a-z]foo", ["Afoo", ".foo"], ["afoo", "ABfoo"]),
                ("foo[!a-z]bar", ["fooAbar", "foo.bar"], ["foojbar"]),
                ("[\x20-\x30\u8336]", ["\040", "\044", "\u8336"], ["\x1f"]),
                ("[^\x20-\x30\u8336]", ["\x1f"], ["\040", "\044", "\u8336"]),
            ]
        )

    def test_regex(self):
        self.assertMatch(
            [
                ("RE:(a|b|c+)", ["a", "b", "ccc"], ["d", "aa", "c+", "-a"]),
                ("RE:(?:a|b|c+)", ["a", "b", "ccc"], ["d", "aa", "c+", "-a"]),
                ("RE:(?P<a>.)(?P=a)", ["a"], ["ab", "aa", "aaa"]),
                # test we can handle odd numbers of trailing backslashes
                ("RE:a\\\\\\", ["a\\"], ["a", "ab", "aa", "aaa"]),
            ]
        )

    def test_question_mark(self):
        self.assertMatch(
            [
                (
                    "?foo",
                    ["xfoo", "bar/xfoo", "bar/\u8336foo", ".foo", "bar/.foo"],
                    ["bar/foo", "foo"],
                ),
                (
                    "foo?bar",
                    ["fooxbar", "foo.bar", "foo\u8336bar", "qyzzy/foo.bar"],
                    ["foo/bar"],
                ),
                (
                    "foo/?bar",
                    ["foo/xbar", "foo/\u8336bar", "foo/.bar"],
                    ["foo/bar", "bar/foo/xbar"],
                ),
            ]
        )

    def test_asterisk(self):
        self.assertMatch(
            [
                (
                    "x*x",
                    ["xx", "x.x", "x\u8336..x", "\u8336/x.x", "x.y.x"],
                    ["x/x", "bar/x/bar/x", "bax/abaxab"],
                ),
                (
                    "foo/*x",
                    ["foo/x", "foo/bax", "foo/a.x", "foo/.x", "foo/.q.x"],
                    ["foo/bar/bax"],
                ),
                (
                    "*/*x",
                    [
                        "\u8336/x",
                        "foo/x",
                        "foo/bax",
                        "x/a.x",
                        ".foo/x",
                        "\u8336/.x",
                        "foo/.q.x",
                    ],
                    ["foo/bar/bax"],
                ),
                ("f*", ["foo", "foo.bar"], [".foo", "foo/bar", "foo/.bar"]),
                (
                    "*bar",
                    [
                        "bar",
                        "foobar",
                        "foo\\nbar",
                        "foo.bar",
                        "foo/bar",
                        "foo/foobar",
                        "foo/f.bar",
                        ".bar",
                        "foo/.bar",
                    ],
                    [],
                ),
            ]
        )

    def test_double_asterisk(self):
        self.assertMatch(
            [
                # expected uses of double asterisk
                (
                    "foo/**/x",
                    ["foo/x", "foo/bar/x"],
                    ["foox", "foo/bax", "foo/.x", "foo/bar/bax"],
                ),
                (
                    "**/bar",
                    ["bar", "foo/bar"],
                    [
                        "foobar",
                        "foo.bar",
                        "foo/foobar",
                        "foo/f.bar",
                        ".bar",
                        "foo/.bar",
                    ],
                ),
                # check that we ignore extra *s, so *** is treated like ** not *.
                (
                    "foo/***/x",
                    ["foo/x", "foo/bar/x"],
                    ["foox", "foo/bax", "foo/.x", "foo/bar/bax"],
                ),
                (
                    "***/bar",
                    ["bar", "foo/bar"],
                    [
                        "foobar",
                        "foo.bar",
                        "foo/foobar",
                        "foo/f.bar",
                        ".bar",
                        "foo/.bar",
                    ],
                ),
                # the remaining tests check that ** is interpreted as *
                # unless it is a whole path component
                (
                    "x**/x",
                    ["x\u8336/x", "x/x"],
                    ["xx", "x.x", "bar/x/bar/x", "x.y.x", "x/y/x"],
                ),
                (
                    "x**x",
                    ["xx", "x.x", "x\u8336..x", "foo/x.x", "x.y.x"],
                    ["bar/x/bar/x", "xfoo/bar/x", "x/x", "bax/abaxab"],
                ),
                (
                    "foo/**x",
                    ["foo/x", "foo/bax", "foo/a.x", "foo/.x", "foo/.q.x"],
                    ["foo/bar/bax"],
                ),
                ("f**", ["foo", "foo.bar"], [".foo", "foo/bar", "foo/.bar"]),
                (
                    "**bar",
                    [
                        "bar",
                        "foobar",
                        "foo\\nbar",
                        "foo.bar",
                        "foo/bar",
                        "foo/foobar",
                        "foo/f.bar",
                        ".bar",
                        "foo/.bar",
                    ],
                    [],
                ),
            ]
        )

    def test_leading_dot_slash(self):
        self.assertMatch(
            [
                ("./foo", ["foo"], ["\u8336/foo", "barfoo", "x/y/foo"]),
                ("./f*", ["foo"], ["foo/bar", "foo/.bar", "x/foo/y"]),
            ]
        )

    def test_backslash(self):
        self.assertMatch(
            [
                (".\\foo", ["foo"], ["\u8336/foo", "barfoo", "x/y/foo"]),
                (".\\f*", ["foo"], ["foo/bar", "foo/.bar", "x/foo/y"]),
                (
                    "foo\\**\\x",
                    ["foo/x", "foo/bar/x"],
                    ["foox", "foo/bax", "foo/.x", "foo/bar/bax"],
                ),
            ]
        )

    def test_trailing_slash(self):
        self.assertMatch(
            [
                ("./foo/", ["foo"], ["\u8336/foo", "barfoo", "x/y/foo"]),
                (".\\foo\\", ["foo"], ["foo/", "\u8336/foo", "barfoo", "x/y/foo"]),
            ]
        )

    def test_leading_asterisk_dot(self):
        self.assertMatch(
            [
                (
                    "*.x",
                    [
                        "foo/bar/baz.x",
                        "\u8336/Q.x",
                        "foo.y.x",
                        ".foo.x",
                        "bar/.foo.x",
                        ".x",
                    ],
                    ["foo.x.y"],
                ),
                ("foo/*.bar", ["foo/b.bar", "foo/a.b.bar", "foo/.bar"], ["foo/bar"]),
                ("*.~*", ["foo.py.~1~", ".foo.py.~1~"], []),
            ]
        )

    def test_end_anchor(self):
        self.assertMatch(
            [
                ("*.333", ["foo.333"], ["foo.3"]),
                ("*.3", ["foo.3"], ["foo.333"]),
            ]
        )

    def test_mixed_globs(self):
        """Tests handling of combinations of path type matches.

        The types being extension, basename and full path.
        """
        patterns = ["*.foo", ".*.swp", "./*.png"]
        globster = Globster(patterns)
        self.assertEqual("*.foo", globster.match("bar.foo"))
        self.assertEqual("./*.png", globster.match("foo.png"))
        self.assertEqual(None, globster.match("foo/bar.png"))
        self.assertEqual(".*.swp", globster.match("foo/.bar.py.swp"))

    def test_large_globset(self):
        """Tests that the globster can handle a large set of patterns.

        Large is defined as more than supported by python regex groups,
        i.e. 99.
        This test assumes the globs are broken into regexs containing 99
        groups.
        """
        patterns = ["*.%03d" % i for i in range(300)]
        globster = Globster(patterns)
        # test the fence posts
        for x in (0, 98, 99, 197, 198, 296, 297, 299):
            filename = "foo.%03d" % x
            self.assertEqual(patterns[x], globster.match(filename))
        self.assertEqual(None, globster.match("foobar.300"))

    def test_bad_pattern(self):
        """Ensure that globster handles bad patterns cleanly."""
        patterns = ["RE:[", "/home/foo", "RE:*.cpp"]
        g = Globster(patterns)
        e = self.assertRaises(lazy_regex.InvalidPattern, g.match, "filename")
        self.assertContainsRe(
            e.msg, r"File.*ignore.*contains error.*RE:\[.*RE:\*\.cpp", flags=re.DOTALL
        )


class TestExceptionGlobster(TestCase):
    def test_exclusion_patterns(self):
        """Test that exception patterns are not matched."""
        patterns = ["*", "!./local", "!./local/**/*", "!RE:\\.z.*", "!!./.zcompdump"]
        globster = ExceptionGlobster(patterns)
        self.assertEqual("*", globster.match("tmp/foo.txt"))
        self.assertEqual(None, globster.match("local"))
        self.assertEqual(None, globster.match("local/bin/wombat"))
        self.assertEqual(None, globster.match(".zshrc"))
        self.assertEqual(None, globster.match(".zfunctions/fiddle/flam"))
        self.assertEqual("!!./.zcompdump", globster.match(".zcompdump"))

    def test_exclusion_order(self):
        """Test that ordering of exclusion patterns does not matter."""
        patterns = ["static/**/*.html", "!static/**/versionable.html"]
        globster = ExceptionGlobster(patterns)
        self.assertEqual("static/**/*.html", globster.match("static/foo.html"))
        self.assertEqual(None, globster.match("static/versionable.html"))
        self.assertEqual(None, globster.match("static/bar/versionable.html"))
        globster = ExceptionGlobster(reversed(patterns))
        self.assertEqual("static/**/*.html", globster.match("static/foo.html"))
        self.assertEqual(None, globster.match("static/versionable.html"))
        self.assertEqual(None, globster.match("static/bar/versionable.html"))


class TestOrderedGlobster(TestCase):
    def test_ordered_globs(self):
        """Test that the first match in a list is the one found."""
        patterns = ["*.foo", "bar.*"]
        globster = _OrderedGlobster(patterns)
        self.assertEqual("*.foo", globster.match("bar.foo"))
        self.assertEqual(None, globster.match("foo.bar"))
        globster = _OrderedGlobster(reversed(patterns))
        self.assertEqual("bar.*", globster.match("bar.foo"))
        self.assertEqual(None, globster.match("foo.bar"))


class TestNormalizePattern(TestCase):
    def test_backslashes(self):
        """Tests that backslashes are converted to forward slashes, multiple
        backslashes are collapsed to single forward slashes and trailing
        backslashes are removed.
        """
        self.assertEqual("/", normalize_pattern("\\"))
        self.assertEqual("/", normalize_pattern("\\\\"))
        self.assertEqual("/foo/bar", normalize_pattern("\\foo\\bar"))
        self.assertEqual("foo/bar", normalize_pattern("foo\\bar\\"))
        self.assertEqual("/foo/bar", normalize_pattern("\\\\foo\\\\bar\\\\"))

    def test_forward_slashes(self):
        """Tests that multiple foward slashes are collapsed to single forward
        slashes and trailing forward slashes are removed.
        """
        self.assertEqual("/", normalize_pattern("/"))
        self.assertEqual("/", normalize_pattern("//"))
        self.assertEqual("/foo/bar", normalize_pattern("/foo/bar"))
        self.assertEqual("foo/bar", normalize_pattern("foo/bar/"))
        self.assertEqual("/foo/bar", normalize_pattern("//foo//bar//"))

    def test_mixed_slashes(self):
        """Tests that multiple mixed slashes are collapsed to single forward
        slashes and trailing mixed slashes are removed.
        """
        self.assertEqual("/foo/bar", normalize_pattern("\\/\\foo//\\///bar/\\\\/"))

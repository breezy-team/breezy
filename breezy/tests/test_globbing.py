# Copyright (C) 2006-2011 Canonical Ltd
# -*- coding: utf-8 -*-
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

from .. import errors, lazy_regex
from ..globbing import (
    Globster,
    ExceptionGlobster,
    _OrderedGlobster,
    normalize_pattern
    )
from . import (
    TestCase,
    )


class TestGlobster(TestCase):

    def assertMatch(self, matchset, glob_prefix=None):
        for glob, positive, negative in matchset:
            if glob_prefix:
                glob = glob_prefix + glob
            globster = Globster([glob])
            for name in positive:
                self.assertTrue(globster.match(name), repr(
                    u'name "%s" does not match glob "%s" (re=%s)' %
                    (name, glob, globster._regex_patterns[0][0].pattern)))
            for name in negative:
                self.assertFalse(globster.match(name), repr(
                    u'name "%s" does match glob "%s" (re=%s)' %
                    (name, glob, globster._regex_patterns[0][0].pattern)))

    def assertMatchBasenameAndFullpath(self, matchset):
        # test basename matcher
        self.assertMatch(matchset)
        # test fullpath matcher
        self.assertMatch(matchset, glob_prefix='./')

    def test_char_group_digit(self):
        self.assertMatchBasenameAndFullpath([
            # The definition of digit this uses includes arabic digits from
            # non-latin scripts (arabic, indic, etc.) but neither roman
            # numerals nor vulgar fractions. Some characters such as
            # subscript/superscript digits may or may not match depending on
            # the Python version used, see: <http://bugs.python.org/issue6561>
            (u'[[:digit:]]',
             [u'0', u'5', u'\u0663', u'\u06f9', u'\u0f21'],
             [u'T', u'q', u' ', u'\u8336', u'.']),
            (u'[^[:digit:]]',
             [u'T', u'q', u' ', u'\u8336', u'.'],
             [u'0', u'5', u'\u0663', u'\u06f9', u'\u0f21']),
            ])

    def test_char_group_space(self):
        self.assertMatchBasenameAndFullpath([
            (u'[[:space:]]',
             [u' ', u'\t', u'\n', u'\xa0', u'\u2000', u'\u2002'],
             [u'a', u'-', u'\u8336', u'.']),
            (u'[^[:space:]]',
             [u'a', u'-', u'\u8336', u'.'],
             [u' ', u'\t', u'\n', u'\xa0', u'\u2000', u'\u2002']),
            ])

    def test_char_group_alnum(self):
        self.assertMatchBasenameAndFullpath([
            (u'[[:alnum:]]',
             [u'a', u'Z', u'\u017e', u'\u8336'],
             [u':', u'-', u'\u25cf', u'.']),
            (u'[^[:alnum:]]',
             [u':', u'-', u'\u25cf', u'.'],
             [u'a']),
            ])

    def test_char_group_ascii(self):
        self.assertMatchBasenameAndFullpath([
            (u'[[:ascii:]]',
             [u'a', u'Q', u'^', u'.'],
             [u'\xcc', u'\u8336']),
            (u'[^[:ascii:]]',
             [u'\xcc', u'\u8336'],
             [u'a', u'Q', u'^', u'.']),
            ])

    def test_char_group_blank(self):
        self.assertMatchBasenameAndFullpath([
            (u'[[:blank:]]',
             [u'\t'],
             [u'x', u'y', u'z', u'.']),
            (u'[^[:blank:]]',
             [u'x', u'y', u'z', u'.'],
             [u'\t']),
            ])

    def test_char_group_cntrl(self):
        self.assertMatchBasenameAndFullpath([
            (u'[[:cntrl:]]',
             [u'\b', u'\t', '\x7f'],
             [u'a', u'Q', u'\u8336', u'.']),
            (u'[^[:cntrl:]]',
             [u'a', u'Q', u'\u8336', u'.'],
             [u'\b', u'\t', '\x7f']),
            ])

    def test_char_group_range(self):
        self.assertMatchBasenameAndFullpath([
            (u'[a-z]',
             [u'a', u'q', u'f'],
             [u'A', u'Q', u'F']),
            (u'[^a-z]',
             [u'A', u'Q', u'F'],
             [u'a', u'q', u'f']),
            (u'[!a-z]foo',
             [u'Afoo', u'.foo'],
             [u'afoo', u'ABfoo']),
            (u'foo[!a-z]bar',
             [u'fooAbar', u'foo.bar'],
             [u'foojbar']),
            (u'[\x20-\x30\u8336]',
             [u'\040', u'\044', u'\u8336'],
             [u'\x1f']),
            (u'[^\x20-\x30\u8336]',
             [u'\x1f'],
             [u'\040', u'\044', u'\u8336']),
            ])

    def test_regex(self):
        self.assertMatch([
            (u'RE:(a|b|c+)',
             [u'a', u'b', u'ccc'],
             [u'd', u'aa', u'c+', u'-a']),
            (u'RE:(?:a|b|c+)',
             [u'a', u'b', u'ccc'],
             [u'd', u'aa', u'c+', u'-a']),
            (u'RE:(?P<a>.)(?P=a)',
             [u'a'],
             [u'ab', u'aa', u'aaa']),
            # test we can handle odd numbers of trailing backslashes
            (u'RE:a\\\\\\',
             [u'a\\'],
             [u'a', u'ab', u'aa', u'aaa']),
            ])

    def test_question_mark(self):
        self.assertMatch([
            (u'?foo',
             [u'xfoo', u'bar/xfoo', u'bar/\u8336foo', u'.foo', u'bar/.foo'],
             [u'bar/foo', u'foo']),
            (u'foo?bar',
             [u'fooxbar', u'foo.bar', u'foo\u8336bar', u'qyzzy/foo.bar'],
             [u'foo/bar']),
            (u'foo/?bar',
             [u'foo/xbar', u'foo/\u8336bar', u'foo/.bar'],
             [u'foo/bar', u'bar/foo/xbar']),
            ])

    def test_asterisk(self):
        self.assertMatch([
            (u'x*x',
             [u'xx', u'x.x', u'x\u8336..x', u'\u8336/x.x', u'x.y.x'],
             [u'x/x', u'bar/x/bar/x', u'bax/abaxab']),
            (u'foo/*x',
             [u'foo/x', u'foo/bax', u'foo/a.x', u'foo/.x', u'foo/.q.x'],
             [u'foo/bar/bax']),
            (u'*/*x',
             [u'\u8336/x', u'foo/x', u'foo/bax', u'x/a.x', u'.foo/x',
              u'\u8336/.x', u'foo/.q.x'],
             [u'foo/bar/bax']),
            (u'f*',
             [u'foo', u'foo.bar'],
             [u'.foo', u'foo/bar', u'foo/.bar']),
            (u'*bar',
             [u'bar', u'foobar', u'foo\\nbar', u'foo.bar', u'foo/bar',
              u'foo/foobar', u'foo/f.bar', u'.bar', u'foo/.bar'],
             []),
            ])

    def test_double_asterisk(self):
        self.assertMatch([
            # expected uses of double asterisk
            (u'foo/**/x',
             [u'foo/x', u'foo/bar/x'],
             [u'foox', u'foo/bax', u'foo/.x', u'foo/bar/bax']),
            (u'**/bar',
             [u'bar', u'foo/bar'],
             [u'foobar', u'foo.bar', u'foo/foobar', u'foo/f.bar',
              u'.bar', u'foo/.bar']),
            # check that we ignore extra *s, so *** is treated like ** not *.
            (u'foo/***/x',
             [u'foo/x', u'foo/bar/x'],
             [u'foox', u'foo/bax', u'foo/.x', u'foo/bar/bax']),
            (u'***/bar',
             [u'bar', u'foo/bar'],
             [u'foobar', u'foo.bar', u'foo/foobar', u'foo/f.bar',
              u'.bar', u'foo/.bar']),
            # the remaining tests check that ** is interpreted as *
            # unless it is a whole path component
            (u'x**/x',
             [u'x\u8336/x', u'x/x'],
             [u'xx', u'x.x', u'bar/x/bar/x', u'x.y.x', u'x/y/x']),
            (u'x**x',
             [u'xx', u'x.x', u'x\u8336..x', u'foo/x.x', u'x.y.x'],
             [u'bar/x/bar/x', u'xfoo/bar/x', u'x/x', u'bax/abaxab']),
            (u'foo/**x',
             [u'foo/x', u'foo/bax', u'foo/a.x', u'foo/.x', u'foo/.q.x'],
             [u'foo/bar/bax']),
            (u'f**',
             [u'foo', u'foo.bar'],
             [u'.foo', u'foo/bar', u'foo/.bar']),
            (u'**bar',
             [u'bar', u'foobar', u'foo\\nbar', u'foo.bar', u'foo/bar',
              u'foo/foobar', u'foo/f.bar', u'.bar', u'foo/.bar'],
             []),
            ])

    def test_leading_dot_slash(self):
        self.assertMatch([
            (u'./foo',
             [u'foo'],
             [u'\u8336/foo', u'barfoo', u'x/y/foo']),
            (u'./f*',
             [u'foo'],
             [u'foo/bar', u'foo/.bar', u'x/foo/y']),
            ])

    def test_backslash(self):
        self.assertMatch([
            (u'.\\foo',
             [u'foo'],
             [u'\u8336/foo', u'barfoo', u'x/y/foo']),
            (u'.\\f*',
             [u'foo'],
             [u'foo/bar', u'foo/.bar', u'x/foo/y']),
            (u'foo\\**\\x',
             [u'foo/x', u'foo/bar/x'],
             [u'foox', u'foo/bax', u'foo/.x', u'foo/bar/bax']),
            ])

    def test_trailing_slash(self):
        self.assertMatch([
            (u'./foo/',
             [u'foo'],
             [u'\u8336/foo', u'barfoo', u'x/y/foo']),
            (u'.\\foo\\',
             [u'foo'],
             [u'foo/', u'\u8336/foo', u'barfoo', u'x/y/foo']),
            ])

    def test_leading_asterisk_dot(self):
        self.assertMatch([
            (u'*.x',
             [u'foo/bar/baz.x', u'\u8336/Q.x', u'foo.y.x', u'.foo.x',
              u'bar/.foo.x', u'.x', ],
             [u'foo.x.y']),
            (u'foo/*.bar',
             [u'foo/b.bar', u'foo/a.b.bar', u'foo/.bar'],
             [u'foo/bar']),
            (u'*.~*',
             [u'foo.py.~1~', u'.foo.py.~1~'],
             []),
            ])

    def test_end_anchor(self):
        self.assertMatch([
            (u'*.333',
             [u'foo.333'],
             [u'foo.3']),
            (u'*.3',
             [u'foo.3'],
             [u'foo.333']),
            ])

    def test_mixed_globs(self):
        """tests handling of combinations of path type matches.

        The types being extension, basename and full path.
        """
        patterns = [u'*.foo', u'.*.swp', u'./*.png']
        globster = Globster(patterns)
        self.assertEqual(u'*.foo', globster.match('bar.foo'))
        self.assertEqual(u'./*.png', globster.match('foo.png'))
        self.assertEqual(None, globster.match('foo/bar.png'))
        self.assertEqual(u'.*.swp', globster.match('foo/.bar.py.swp'))

    def test_large_globset(self):
        """tests that the globster can handle a large set of patterns.

        Large is defined as more than supported by python regex groups,
        i.e. 99.
        This test assumes the globs are broken into regexs containing 99
        groups.
        """
        patterns = [u'*.%03d' % i for i in range(300)]
        globster = Globster(patterns)
        # test the fence posts
        for x in (0, 98, 99, 197, 198, 296, 297, 299):
            filename = u'foo.%03d' % x
            self.assertEqual(patterns[x], globster.match(filename))
        self.assertEqual(None, globster.match('foobar.300'))

    def test_bad_pattern(self):
        """Ensure that globster handles bad patterns cleanly."""
        patterns = [u'RE:[', u'/home/foo', u'RE:*.cpp']
        g = Globster(patterns)
        e = self.assertRaises(lazy_regex.InvalidPattern, g.match, 'filename')
        self.assertContainsRe(e.msg,
                              r"File.*ignore.*contains error.*RE:\[.*RE:\*\.cpp", flags=re.DOTALL)


class TestExceptionGlobster(TestCase):

    def test_exclusion_patterns(self):
        """test that exception patterns are not matched"""
        patterns = [u'*', u'!./local', u'!./local/**/*',
                    u'!RE:\\.z.*', u'!!./.zcompdump']
        globster = ExceptionGlobster(patterns)
        self.assertEqual(u'*', globster.match('tmp/foo.txt'))
        self.assertEqual(None, globster.match('local'))
        self.assertEqual(None, globster.match('local/bin/wombat'))
        self.assertEqual(None, globster.match('.zshrc'))
        self.assertEqual(None, globster.match('.zfunctions/fiddle/flam'))
        self.assertEqual(u'!!./.zcompdump', globster.match('.zcompdump'))

    def test_exclusion_order(self):
        """test that ordering of exclusion patterns does not matter"""
        patterns = [u'static/**/*.html', u'!static/**/versionable.html']
        globster = ExceptionGlobster(patterns)
        self.assertEqual(u'static/**/*.html',
                         globster.match('static/foo.html'))
        self.assertEqual(None, globster.match('static/versionable.html'))
        self.assertEqual(None, globster.match('static/bar/versionable.html'))
        globster = ExceptionGlobster(reversed(patterns))
        self.assertEqual(u'static/**/*.html',
                         globster.match('static/foo.html'))
        self.assertEqual(None, globster.match('static/versionable.html'))
        self.assertEqual(None, globster.match('static/bar/versionable.html'))


class TestOrderedGlobster(TestCase):

    def test_ordered_globs(self):
        """test that the first match in a list is the one found"""
        patterns = [u'*.foo', u'bar.*']
        globster = _OrderedGlobster(patterns)
        self.assertEqual(u'*.foo', globster.match('bar.foo'))
        self.assertEqual(None, globster.match('foo.bar'))
        globster = _OrderedGlobster(reversed(patterns))
        self.assertEqual(u'bar.*', globster.match('bar.foo'))
        self.assertEqual(None, globster.match('foo.bar'))


class TestNormalizePattern(TestCase):

    def test_backslashes(self):
        """tests that backslashes are converted to forward slashes, multiple
        backslashes are collapsed to single forward slashes and trailing
        backslashes are removed"""
        self.assertEqual(u'/', normalize_pattern(u'\\'))
        self.assertEqual(u'/', normalize_pattern(u'\\\\'))
        self.assertEqual(u'/foo/bar', normalize_pattern(u'\\foo\\bar'))
        self.assertEqual(u'foo/bar', normalize_pattern(u'foo\\bar\\'))
        self.assertEqual(u'/foo/bar', normalize_pattern(u'\\\\foo\\\\bar\\\\'))

    def test_forward_slashes(self):
        """tests that multiple foward slashes are collapsed to single forward
        slashes and trailing forward slashes are removed"""
        self.assertEqual(u'/', normalize_pattern(u'/'))
        self.assertEqual(u'/', normalize_pattern(u'//'))
        self.assertEqual(u'/foo/bar', normalize_pattern(u'/foo/bar'))
        self.assertEqual(u'foo/bar', normalize_pattern(u'foo/bar/'))
        self.assertEqual(u'/foo/bar', normalize_pattern(u'//foo//bar//'))

    def test_mixed_slashes(self):
        """tests that multiple mixed slashes are collapsed to single forward
        slashes and trailing mixed slashes are removed"""
        self.assertEqual(
            u'/foo/bar', normalize_pattern(u'\\/\\foo//\\///bar/\\\\/'))

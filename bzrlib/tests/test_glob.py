# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.tests import TestCase, TestCaseInTempDir

from bzrlib.glob import (
        Globster
        )


class TestGlobster(TestCase):

    def assertMatch(self, matchset, glob_prefix=None):
        for glob, positive, negative in matchset:
            if glob_prefix:
                glob = glob_prefix + glob
            globster = Globster([glob])
            for name in positive:
                self.failUnless(globster.match(name), repr(
                    u'name "%s" does not match glob "%s" (re=%s)' %
                    (name, glob, globster._regex_patterns[0][0].pattern)))
            for name in negative:
                self.failIf(globster.match(name), repr(
                    u'name "%s" does match glob "%s" (re=%s)' %
                    (name, glob, globster._regex_patterns[0][0].pattern)))

    def test_char_groups(self):
        # The definition of digit this uses includes arabic digits from
        # non-latin scripts (arabic, indic, etc.) and subscript/superscript
        # digits, but neither roman numerals nor vulgar fractions.
        matchset = [
            (u'[[:digit:]]',
             [u'0', u'5', u'\u0663', u'\u06f9', u'\u0f21', u'\xb9'],
             [u'T', u'q', u' ', u'\u8336', u'.']),
            (u'[[:space:]]',
             [u' ', u'\t', u'\n', u'\xa0', u'\u2000', u'\u2002'],
             [u'a', u'-', u'\u8336', u'.']),
            (u'[^[:space:]]',
             [u'a', u'-', u'\u8336'],
             [u' ', u'\t', u'\n', u'\xa0', u'\u2000', u'\u2002', u'.']),
            (u'[[:alnum:]]',
             [u'a', u'Z', u'\u017e', u'\u8336'],
             [u':', u'-', u'\u25cf', u'.']),
            (u'[^[:alnum:]]',
             [u':', u'-', u'\u25cf'],
             [u'a', u'.']),
            (u'[[:ascii:]]',
             [u'a', u'Q', u'^'],
             [u'\xcc', u'\u8336', u'.']),
            (u'[^[:ascii:]]',
             [u'\xcc', u'\u8336'],
             [u'a', u'Q', u'^', u'.']),
            (u'[[:blank:]]',
             [u'\t'],
             [u'x', u'y', u'z', u'.']),
            (u'[^[:blank:]]',
             [u'x', u'y', u'z'],
             [u'\t', u'.']),
            (u'[[:cntrl:]]',
             [u'\b', u'\t', '\x7f'],
             [u'a', u'Q', u'\u8336', u'.']),
            (u'[a-z]',
             [u'a', u'q', u'f'],
             [u'A', u'Q', u'F']),
            (ur'[^a-z]',
             [u'A', u'Q', u'F'],
             [u'a', u'q', u'f']),
            (u'[!a-z]foo',
             [u'Afoo'],
             [u'.foo']),
            (ur'foo[!a-z]bar',
             [u'fooAbar', u'foo.bar'],
             [u'foojbar']),
            (ur'[\x20-\x30\u8336]',
             [u'\040', u'\044', u'\u8336'],
             []),
            (ur'[^\x20-\x30\u8336]',
             [],
             [u'\040', u'\044', u'\u8336']),
            ]
        self.assertMatch(matchset)
        self.assertMatch(matchset,glob_prefix='./')

    def test_regex(self):
        self.assertMatch([
            (ur'RE:(a|b|c+)',
             [u'a', u'b', u'ccc'],
             [u'd', u'aa', u'c+', u'-a']),
            (ur'RE:(?:a|b|c+)',
             [u'a', u'b', u'ccc'],
             [u'd', u'aa', u'c+', u'-a']),
            (ur'RE:(?P<a>.)(?P=a)',
             [u'a'],
             [u'ab', u'aa', u'aaa']),
            ])

    def test_question_mark(self):
        self.assertMatch([
            (u'?foo',
             [u'xfoo', u'bar/xfoo', u'bar/\u8336foo'],
             [u'.foo', u'bar/.foo', u'bar/foo', u'foo']),
            (u'foo?bar',
             [u'fooxbar', u'foo.bar', u'foo\u8336bar', u'qyzzy/foo.bar'],
             [u'foo/bar']),
            (u'foo/?bar',
             [u'foo/xbar', u'foo/\u8336bar'],
             [u'foo/.bar', u'foo/bar', u'bar/foo/xbar']),
            ])

    def test_asterisk(self):
        self.assertMatch([
            (u'x*x',
             [u'xx', u'x.x', u'x\u8336..x', u'\u8336/x.x', u'x.y.x'],
             [u'x/x', u'bar/x/bar/x', u'bax/abaxab']),
            (u'foo/*x',
             [u'foo/x', u'foo/bax', u'foo/a.x'],
             [u'foo/.x', u'foo/.q.x', u'foo/bar/bax']),
            (u'*/*x',
             [u'\u8336/x', u'foo/x', u'foo/bax', u'x/a.x'],
             [u'.foo/x', u'\u8336/.x', u'foo/.q.x', u'foo/bar/bax']),
            (u'f*',
             [u'foo', u'foo.bar'],
             [u'.foo', u'foo/bar', u'foo/.bar']),
            (u'*bar',
             [u'bar', u'foobar', ur'foo\nbar', u'foo.bar', u'foo/bar', 
              u'foo/foobar', u'foo/f.bar'],
             [u'.bar', u'foo/.bar']),
            ])

    def test_leading_dotslash(self):
        self.assertMatch([
            (u'./foo',
             [u'foo'],
             [u'\u8336/foo', u'barfoo', u'x/y/foo']),
            (u'./f*',
             [u'foo'],
             [u'foo/bar', u'foo/.bar', u'x/foo/y']),
            ])

    def test_leading_stardot(self):
        self.assertMatch([
            (u'*.x',
             [u'foo/bar/baz.x', u'\u8336/Q.x', u'foo.y.x'],
             [ u'.foo.x', u'bar/.foo.x', u'.x']),
            (u'foo/*.bar',
             [u'foo/b.bar', u'foo/a.b.bar'],
             [u'foo/.bar', u'foo/bar']),
            (u'*.~*',
             [u'foo.py.~1~'],
             [u'.foo.py.~1~']),
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
        patterns = [ u'*.foo', u'.*.swp', u'./*.png']
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
        patterns = [ u'*.%03d' % i for i in xrange(0,300) ]
        globster = Globster(patterns)
        # test the fence posts
        for x in (0,98,99,197,198,296,297,299):
            filename = u'foo.%03d' % x
            self.assertEqual(patterns[x],globster.match(filename))
        self.assertEqual(None,globster.match('foobar.300'))


# Copyright (C) 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""\
Test new style globs.

fnmatch is not a very good pattern matcher.
It doesn't handle unicode patterns, nor special
patterns like **.
"""

import re

import bzrlib
from bzrlib.tests import TestCase
from bzrlib.glob_matcher import (glob_to_re, glob_to_matcher,
                                 globs_to_re, globs_to_matcher)


class GlobToRe(TestCase):
    """This tests the direct conversion."""

    def test_no_globs(self):
        self.assertEqual('a$', glob_to_re('a'))
        # fnmatch thinks that an unmatched [ should just
        # be escaped
        self.assertEqual('foo\\[$', glob_to_re('foo['))

    def test_star(self):
        self.assertEqual('a[^/\\\\]*$', glob_to_re('a*'))
        self.assertEqual('[^/\\\\]*a$', glob_to_re('*a'))

    def test_starstar(self):
        self.assertEqual('a.*$', glob_to_re('a**'))
        self.assertEqual('.*a$', glob_to_re('**a'))
        self.assertEqual(r'.*\/a\/[^/\\]*b$', glob_to_re('**/a/*b'))

    def test_sequence(self):
        self.assertEqual('a[abcd]$', glob_to_re('a[abcd]'))
        self.assertEqual('a[^abcd/\\\\]$', glob_to_re('a[!abcd]'))
        self.assertEqual('a[\\^b]$' , glob_to_re('a[^b]'))
        self.assertEqual('a[^^/\\\\]$', glob_to_re('a[!^]'))

    def test_unicode(self):
        self.assertEqual(u'a\\\xb5$', glob_to_re(u'a\xb5'))


class GlobMatching(TestCase):
    """More of a functional test, making sure globs match what we want."""

    def assertMatching(self, glob, matching, not_matching):
        """Make sure glob matches matching, but not not_matching.

        :param glob: A filename glob
        :param matching: List of matching filenames
        :param not_matching: List on non-matching filenames
        """
        matcher = glob_to_matcher(glob)
        for fname in matching:
            self.failUnless(matcher(fname), 'glob %s did not match %s' % (glob, fname))
        for fname in not_matching:
            self.failIf(matcher(fname), 'glob %s should not match %s' % (glob, fname))

    def test_no_globs(self):
        check = self.assertMatching
        check('a', ['a'], ['b', 'a ', ' a', 'ba'])
        check('foo[', ['foo['], ['[', 'foo', '[foo'])
        check('a(b)', ['a(b)'], ['ab', 'ba', 'a(b'])

    def test_star(self):
        check = self.assertMatching
        check('a*', ['a', 'ab', 'abc', 'a.txt'],
                    ['a/', 'a/a', 'foo/a', 'a\\'])
        # TODO jam 20060107 Some would say '*a' should not match .a
        check('*a', ['a', 'ba', 'bca', '.a', 'c.a'],
                    ['/a', 'a/a', 'foo/a', '\\a', 'a\\a'])

    def test_starstar(self):
        check = self.assertMatching
        check('a**', ['a', 'ab', 'abc', 'a/', 'a/a', 'a\\'],
                     ['foo/a', 'b/a'])
        check('**a', ['a', 'ba', 'bca', '/a', '.a', './.a', '(foo)/a'],
                     ['booty/ab', 'bca/b'])
        #check('**/a/*b'

    def test_sequence(self):
        check = self.assertMatching
        check('a[abcd]', ['aa', 'ab', 'ac', 'ad'],
                         ['a', 'ba', 'baa', 'ae', 'a/', 'abc', 'aab'])
        check('a[!abcd]', ['ae', 'af', 'aq'],
                          ['a', 'a/', 'ab', 'ac', 'ad', 'abc'])
        check('a[^b]', ['ab', 'a^'], ['a', 'ac'])
        check('a[!^]', ['ab', 'ac'], ['a', 'a^', 'a/'])

    def test_unicode(self):
        check = self.assertMatching
        check(u'a\xb5', [u'a\xb5'], ['a', 'au', 'a/'])
        check(u'a\xb5*.txt', [u'a\xb5.txt', u'a\xb5txt.txt', u'a\xb5\xb5.txt'],
                             [u'a.txt', u'a/a\xb5.txt'])
        check('a*', ['a', u'a\xb5\xb5'], [u'a/\xb5'])
        check('**a', ['a', u'\xb5/a', u'\xb5/\xb5a'],
                     ['ab', u'\xb5/ab'])

        check(u'a[\xb5b]', ['ab', u'a\xb5'], ['a/', 'a\\', u'ba\xb5'])


class GlobsToRe(TestCase):
    """Test that we can use multiple patterns at once"""

    def test_basic(self):
        self.assertEqual('(a)$', globs_to_re(['a']))
        self.assertEqual('(a|b)$', globs_to_re(['a', 'b']))


class GlobsMatching(TestCase):
    """Functional test that multiple patterns match correctly"""

    def assertMatching(self, globs, matching, not_matching):
        """Make sure globs match matching, but not not_matching.

        :param globs: A list of filename globs
        :param matching: List of matching filenames
        :param not_matching: List on non-matching filenames
        """
        matcher = globs_to_matcher(globs)
        for fname in matching:
            self.failUnless(matcher(fname), 'globs %s did not match %s' % (globs, fname))
        for fname in not_matching:
            self.failIf(matcher(fname), 'globs %s should not match %s' % (globs, fname))

    def test_basic(self):
        check = self.assertMatching
        check(['a'], ['a'], ['ab', 'b'])
        check(['a', 'b'], ['a', 'b'], ['ab', 'ba'])

    def test_star(self):
        check = self.assertMatching
        check(['a*', 'b*'], ['a', 'b', 'ab', 'ba', 'a(b)'],
                            ['ca', 'cb', 'a/', 'b/'])

        check(['a', 'b', 'ab*'], ['a', 'b', 'ab', 'abc'],
                                 ['ac', 'acb', 'a/', 'ab/'])

    def test_starstar(self):
        check = self.assertMatching
        check(['a*', 'b**'], ['a', 'ab', 'abc', 'b/a', 'baa', 'b/ab'],
                             ['a/', 'a/b'])

    def test_bzrignore(self):
        matches = ['.foo.swp', 'test.pyc']
        not_matches = ['foo.py', 'test/foo.py', 'foo/test.pyc']
        self.assertMatching(bzrlib.DEFAULT_IGNORE, matches, not_matches)



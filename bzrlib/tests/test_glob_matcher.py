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

from bzrlib.tests import TestCase
from bzrlib.glob_matcher import (glob_to_re, glob_to_matcher,
                                 globs_to_re, globs_to_matcher)


class GlobToRe(TestCase):

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

    def test_sequence(self):
        self.assertEqual('a[abcd]$', glob_to_re('a[abcd]'))
        self.assertEqual('a[^abcd]$', glob_to_re('a[!abcd]'))
        self.assertEqual('a[\\^b]$' , glob_to_re('a[^b]'))
        self.assertEqual('a[^^]$', glob_to_re('a[!^]'))


class GlobMatching(TestCase):

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
        self.assertMatching('a', ['a'], ['b', 'a ', ' a'])
        self.assertMatching('foo[', ['foo['], ['[', 'foo', '[foo'])

    def test_star(self):
        self.assertMatching('a*', ['a', 'ab', 'abc', 'a.txt'],
                                  ['a/', 'a/a', 'foo/a', 'a\\'])
        # TODO jam 20060107 Some would say '*a' should not match .a
        self.assertMatching('*a', ['a', 'ba', 'bca', '.a', 'c.a'],
                                  ['/a', 'a/a', 'foo/a', '\\a', 'a\\a'])

    def test_starstar(self):
        self.assertMatching('a**', ['a', 'ab', 'abc', 'a/', 'a/a', 'a\\'],
                                   ['foo/a', 'b/a'])
        self.assertMatching('**a', ['a', 'ba', 'bca', '/a', '.a', './.a'],
                                   ['booty/ab', 'bca/b'])


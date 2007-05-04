# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the compiled dirstate helpers."""


from bzrlib import (
    tests,
    )
try:
    from bzrlib.compiled import dirstate_helpers
except ImportError:
    have_dirstate_helpers = False
else:
    have_dirstate_helpers = True


class _CompiledDirstateHelpersFeature(tests.Feature):
    def _probe(self):
        return have_dirstate_helpers

    def feature_name(self):
        return 'bzrlib.compiled.dirstate_helpers'

CompiledDirstateHelpersFeature = _CompiledDirstateHelpersFeature()


class TestCMPDirblockStrings(tests.TestCase):

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def assertPositive(self, val):
        """Assert that val is greater than 0."""
        self.assertTrue(val > 0, 'expected a positive value, but got %s' % val)

    def assertNegative(self, val):
        """Assert that val is less than 0."""
        self.assertTrue(val < 0, 'expected a negative value, but got %s' % val)

    def assertStrCmp(self, expected, str1, str2):
        """Compare the two strings, in both directions.

        :param expected: The expected comparison value. -1 means str1 comes
            first, 0 means they are equal, 1 means str2 comes first
        :param str1: string to compare
        :param str2: string to compare
        """
        cmp_dirblock_strings = dirstate_helpers.cmp_dirblock_strings
        if expected == 0:
            self.assertEqual(0, cmp(str1.split('/'), str2.split('/')))
            self.assertEqual(0, cmp_dirblock_strings(str1, str2))
            self.assertEqual(0, cmp_dirblock_strings(str2, str1))
        elif expected > 0:
            self.assertPositive(cmp(str1.split('/'), str2.split('/')))
            self.assertPositive(cmp_dirblock_strings(str1, str2))
            self.assertNegative(cmp_dirblock_strings(str2, str1))
        else:
            self.assertNegative(cmp(str1.split('/'), str2.split('/')))
            self.assertNegative(cmp_dirblock_strings(str1, str2))
            self.assertPositive(cmp_dirblock_strings(str2, str1))

    def test_cmp_empty(self):
        """Compare against the empty string."""
        self.assertStrCmp(0, '', '')
        self.assertStrCmp(1, 'a', '')
        self.assertStrCmp(1, 'b', '')
        self.assertStrCmp(1, 'testing', '')
        self.assertStrCmp(1, 'test/ing/a/path/', '')

    def test_cmp_same_str(self):
        """Compare the same string"""
        self.assertStrCmp(0, 'a', 'a')
        self.assertStrCmp(0, 'b', 'b')
        self.assertStrCmp(0, 'testing a long string', 'testing a long string')
        self.assertStrCmp(0, 'x'*10000, 'x'*10000)
        self.assertStrCmp(0, 'x y', 'x' + ' ' + 'y')
        self.assertStrCmp(0, 'a/b/c/d', 'a/b/c/d')

    def test_simple_paths(self):
        """Compare strings that act like normal string comparison"""
        self.assertStrCmp(-1, 'a', 'b')
        self.assertStrCmp(-1, 'b', 'c')
        self.assertStrCmp(1, 'd', 'c')
        self.assertStrCmp(-1, 'testing a long string', 'testing b long string')
        self.assertStrCmp(-1, 'a/b/c/d', 'a/c/c/d')

    def test_tricky_paths(self):
        self.assertStrCmp(1, 'ab/cd/ef', 'ab/cc/ef')
        self.assertStrCmp(1, 'ab/cd/ef', 'ab/c/ef')
        self.assertStrCmp(-1, 'ab/cd/ef', 'ab/cd-ef')
        self.assertStrCmp(-1, 'ab/cd', 'ab/cd-')
        self.assertStrCmp(-1, 'ab/cd', 'ab-cd')

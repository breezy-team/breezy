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

import bisect

from bzrlib import (
    tests,
    )


class _CompiledDirstateHelpersFeature(tests.Feature):
    def _probe(self):
        try:
            import bzrlib._dirstate_helpers_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._dirstate_helpers_c'

CompiledDirstateHelpersFeature = _CompiledDirstateHelpersFeature()


class TestCmpByDirs(tests.TestCase):

    def get_cmp_by_dirs(self):
        """Get a specific implementation of cmp_by_dirs."""
        from bzrlib._dirstate_helpers_py import cmp_by_dirs_py
        return cmp_by_dirs_py

    def assertPositive(self, val):
        """Assert that val is greater than 0."""
        self.assertTrue(val > 0, 'expected a positive value, but got %s' % val)

    def assertNegative(self, val):
        """Assert that val is less than 0."""
        self.assertTrue(val < 0, 'expected a negative value, but got %s' % val)

    def assertCmpByDirs(self, expected, str1, str2):
        """Compare the two strings, in both directions.

        :param expected: The expected comparison value. -1 means str1 comes
            first, 0 means they are equal, 1 means str2 comes first
        :param str1: string to compare
        :param str2: string to compare
        """
        cmp_by_dirs = self.get_cmp_by_dirs()
        if expected == 0:
            self.assertEqual(str1, str2)
            self.assertEqual(0, cmp_by_dirs(str1, str2))
            self.assertEqual(0, cmp_by_dirs(str2, str1))
        elif expected > 0:
            self.assertPositive(cmp_by_dirs(str1, str2))
            self.assertNegative(cmp_by_dirs(str2, str1))
        else:
            self.assertNegative(cmp_by_dirs(str1, str2))
            self.assertPositive(cmp_by_dirs(str2, str1))

    def test_cmp_empty(self):
        """Compare against the empty string."""
        self.assertCmpByDirs(0, '', '')
        self.assertCmpByDirs(1, 'a', '')
        self.assertCmpByDirs(1, 'ab', '')
        self.assertCmpByDirs(1, 'abc', '')
        self.assertCmpByDirs(1, 'abcd', '')
        self.assertCmpByDirs(1, 'abcde', '')
        self.assertCmpByDirs(1, 'abcdef', '')
        self.assertCmpByDirs(1, 'abcdefg', '')
        self.assertCmpByDirs(1, 'abcdefgh', '')
        self.assertCmpByDirs(1, 'abcdefghi', '')
        self.assertCmpByDirs(1, 'test/ing/a/path/', '')

    def test_cmp_same_str(self):
        """Compare the same string"""
        self.assertCmpByDirs(0, 'a', 'a')
        self.assertCmpByDirs(0, 'ab', 'ab')
        self.assertCmpByDirs(0, 'abc', 'abc')
        self.assertCmpByDirs(0, 'abcd', 'abcd')
        self.assertCmpByDirs(0, 'abcde', 'abcde')
        self.assertCmpByDirs(0, 'abcdef', 'abcdef')
        self.assertCmpByDirs(0, 'abcdefg', 'abcdefg')
        self.assertCmpByDirs(0, 'abcdefgh', 'abcdefgh')
        self.assertCmpByDirs(0, 'abcdefghi', 'abcdefghi')
        self.assertCmpByDirs(0, 'testing a long string', 'testing a long string')
        self.assertCmpByDirs(0, 'x'*10000, 'x'*10000)
        self.assertCmpByDirs(0, 'a/b', 'a/b')
        self.assertCmpByDirs(0, 'a/b/c', 'a/b/c')
        self.assertCmpByDirs(0, 'a/b/c/d', 'a/b/c/d')
        self.assertCmpByDirs(0, 'a/b/c/d/e', 'a/b/c/d/e')

    def test_simple_paths(self):
        """Compare strings that act like normal string comparison"""
        self.assertCmpByDirs(-1, 'a', 'b')
        self.assertCmpByDirs(-1, 'aa', 'ab')
        self.assertCmpByDirs(-1, 'ab', 'bb')
        self.assertCmpByDirs(-1, 'aaa', 'aab')
        self.assertCmpByDirs(-1, 'aab', 'abb')
        self.assertCmpByDirs(-1, 'abb', 'bbb')
        self.assertCmpByDirs(-1, 'aaaa', 'aaab')
        self.assertCmpByDirs(-1, 'aaab', 'aabb')
        self.assertCmpByDirs(-1, 'aabb', 'abbb')
        self.assertCmpByDirs(-1, 'abbb', 'bbbb')
        self.assertCmpByDirs(-1, 'aaaaa', 'aaaab')
        self.assertCmpByDirs(-1, 'a/a', 'a/b')
        self.assertCmpByDirs(-1, 'a/b', 'b/b')
        self.assertCmpByDirs(-1, 'a/a/a', 'a/a/b')
        self.assertCmpByDirs(-1, 'a/a/b', 'a/b/b')
        self.assertCmpByDirs(-1, 'a/b/b', 'b/b/b')
        self.assertCmpByDirs(-1, 'a/a/a/a', 'a/a/a/b')
        self.assertCmpByDirs(-1, 'a/a/a/b', 'a/a/b/b')
        self.assertCmpByDirs(-1, 'a/a/b/b', 'a/b/b/b')
        self.assertCmpByDirs(-1, 'a/b/b/b', 'b/b/b/b')
        self.assertCmpByDirs(-1, 'a/a/a/a/a', 'a/a/a/a/b')

    def test_tricky_paths(self):
        self.assertCmpByDirs(1, 'ab/cd/ef', 'ab/cc/ef')
        self.assertCmpByDirs(1, 'ab/cd/ef', 'ab/c/ef')
        self.assertCmpByDirs(-1, 'ab/cd/ef', 'ab/cd-ef')
        self.assertCmpByDirs(-1, 'ab/cd', 'ab/cd-')
        self.assertCmpByDirs(-1, 'ab/cd', 'ab-cd')


class TestCCmpByDirs(TestCmpByDirs):
    """Test the C implementation of cmp_by_dirs"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_c import cmp_by_dirs_c
        return cmp_by_dirs_c


class TestBisectDirblock(tests.TestCase):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.
    """

    def get_bisect_dirblock(self):
        """Return an implementation of bisect_dirblock"""
        from bzrlib._dirstate_helpers_py import bisect_dirblock_py
        return bisect_dirblock_py

    def assertBisect(self, dirblocks, split_dirblocks, path, *args, **kwargs):
        """Assert that bisect_split works like bisect_left on the split paths.

        :param dirblocks: A list of (path, [info]) pairs.
        :param split_dirblocks: A list of ((split, path), [info]) pairs.
        :param path: The path we are indexing.

        All other arguments will be passed along.
        """
        bisect_dirblock = self.get_bisect_dirblock()
        self.assertIsInstance(dirblocks, list)
        bisect_split_idx = bisect_dirblock(dirblocks, path, *args, **kwargs)
        split_dirblock = (path.split('/'), [])
        bisect_left_idx = bisect.bisect_left(split_dirblocks, split_dirblock,
                                             *args)
        self.assertEqual(bisect_left_idx, bisect_split_idx,
                         'bisect_split disagreed. %s != %s'
                         ' for key %s'
                         % (bisect_left_idx, bisect_split_idx, path)
                         )

    def paths_to_dirblocks(self, paths):
        """Convert a list of paths into dirblock form.

        Also, ensure that the paths are in proper sorted order.
        """
        dirblocks = [(path, []) for path in paths]
        split_dirblocks = [(path.split('/'), []) for path in paths]
        self.assertEqual(sorted(split_dirblocks), split_dirblocks)
        return dirblocks, split_dirblocks

    def test_simple(self):
        """In the simple case it works just like bisect_left"""
        paths = ['', 'a', 'b', 'c', 'd']
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path)
        self.assertBisect(dirblocks, split_dirblocks, '_')
        self.assertBisect(dirblocks, split_dirblocks, 'aa')
        self.assertBisect(dirblocks, split_dirblocks, 'bb')
        self.assertBisect(dirblocks, split_dirblocks, 'cc')
        self.assertBisect(dirblocks, split_dirblocks, 'dd')
        self.assertBisect(dirblocks, split_dirblocks, 'a/a')
        self.assertBisect(dirblocks, split_dirblocks, 'b/b')
        self.assertBisect(dirblocks, split_dirblocks, 'c/c')
        self.assertBisect(dirblocks, split_dirblocks, 'd/d')

    def test_involved(self):
        """This is where bisect_left diverges slightly."""
        paths = ['', 'a',
                 'a/a', 'a/a/a', 'a/a/z', 'a/a-a', 'a/a-z',
                 'a/z', 'a/z/a', 'a/z/z', 'a/z-a', 'a/z-z',
                 'a-a', 'a-z',
                 'z', 'z/a/a', 'z/a/z', 'z/a-a', 'z/a-z',
                 'z/z', 'z/z/a', 'z/z/z', 'z/z-a', 'z/z-z',
                 'z-a', 'z-z',
                ]
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path)

    def test_involved_cached(self):
        """This is where bisect_left diverges slightly."""
        paths = ['', 'a',
                 'a/a', 'a/a/a', 'a/a/z', 'a/a-a', 'a/a-z',
                 'a/z', 'a/z/a', 'a/z/z', 'a/z-a', 'a/z-z',
                 'a-a', 'a-z',
                 'z', 'z/a/a', 'z/a/z', 'z/a-a', 'z/a-z',
                 'z/z', 'z/z/a', 'z/z/z', 'z/z-a', 'z/z-z',
                 'z-a', 'z-z',
                ]
        cache = {}
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path, cache=cache)


class TestCompiledBisectDirblock(TestBisectDirblock):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.

    This runs all the normal tests that TestBisectDirblock did, but uses the
    compiled version.
    """

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_dirblock(self):
        from bzrlib._dirstate_helpers_c import bisect_dirblock_c
        return bisect_dirblock_c

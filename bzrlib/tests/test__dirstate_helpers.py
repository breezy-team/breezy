# Copyright (C) 2007, 2008 Canonical Ltd
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
import os

from bzrlib import (
    dirstate,
    errors,
    tests,
    )
from bzrlib.tests import (
        SymlinkFeature,
        )
from bzrlib.tests import test_dirstate


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


class TestBisectPathMixin(object):
    """Test that _bisect_path_*() returns the expected values.

    _bisect_path_* is intended to work like bisect.bisect_*() except it
    knows it is working on paths that are sorted by ('path', 'to', 'foo')
    chunks rather than by raw 'path/to/foo'.

    Test Cases should inherit from this and override ``get_bisect_path`` return
    their implementation, and ``get_bisect`` to return the matching
    bisect.bisect_* function.
    """

    def get_bisect_path(self):
        """Return an implementation of _bisect_path_*"""
        raise NotImplementedError

    def get_bisect(self):
        """Return a version of bisect.bisect_*.

        Also, for the 'exists' check, return the offset to the real values.
        For example bisect_left returns the index of an entry, while
        bisect_right returns the index *after* an entry

        :return: (bisect_func, offset)
        """
        raise NotImplementedError

    def assertBisect(self, paths, split_paths, path, exists=True):
        """Assert that bisect_split works like bisect_left on the split paths.

        :param paths: A list of path names
        :param split_paths: A list of path names that are already split up by directory
            ('path/to/foo' => ('path', 'to', 'foo'))
        :param path: The path we are indexing.
        :param exists: The path should be present, so make sure the
            final location actually points to the right value.

        All other arguments will be passed along.
        """
        bisect_path = self.get_bisect_path()
        self.assertIsInstance(paths, list)
        bisect_path_idx = bisect_path(paths, path)
        split_path = self.split_for_dirblocks([path])[0]
        bisect_func, offset = self.get_bisect()
        bisect_split_idx = bisect_func(split_paths, split_path)
        self.assertEqual(bisect_split_idx, bisect_path_idx,
                         '%s disagreed. %s != %s'
                         ' for key %r'
                         % (bisect_path.__name__,
                            bisect_split_idx, bisect_path_idx, path)
                         )
        if exists:
            self.assertEqual(path, paths[bisect_path_idx+offset])

    def split_for_dirblocks(self, paths):
        dir_split_paths = []
        for path in paths:
            dirname, basename = os.path.split(path)
            dir_split_paths.append((dirname.split('/'), basename))
        dir_split_paths.sort()
        return dir_split_paths

    def test_simple(self):
        """In the simple case it works just like bisect_left"""
        paths = ['', 'a', 'b', 'c', 'd']
        split_paths = self.split_for_dirblocks(paths)
        for path in paths:
            self.assertBisect(paths, split_paths, path, exists=True)
        self.assertBisect(paths, split_paths, '_', exists=False)
        self.assertBisect(paths, split_paths, 'aa', exists=False)
        self.assertBisect(paths, split_paths, 'bb', exists=False)
        self.assertBisect(paths, split_paths, 'cc', exists=False)
        self.assertBisect(paths, split_paths, 'dd', exists=False)
        self.assertBisect(paths, split_paths, 'a/a', exists=False)
        self.assertBisect(paths, split_paths, 'b/b', exists=False)
        self.assertBisect(paths, split_paths, 'c/c', exists=False)
        self.assertBisect(paths, split_paths, 'd/d', exists=False)

    def test_involved(self):
        """This is where bisect_path_* diverges slightly."""
        # This is the list of paths and their contents
        # a/
        #   a/
        #     a
        #     z
        #   a-a/
        #     a
        #   a-z/
        #     z
        #   a=a/
        #     a
        #   a=z/
        #     z
        #   z/
        #     a
        #     z
        #   z-a
        #   z-z
        #   z=a
        #   z=z
        # a-a/
        #   a
        # a-z/
        #   z
        # a=a/
        #   a
        # a=z/
        #   z
        # This is the exact order that is stored by dirstate
        # All children in a directory are mentioned before an children of
        # children are mentioned.
        # So all the root-directory paths, then all the
        # first sub directory, etc.
        paths = [# content of '/'
                 '', 'a', 'a-a', 'a-z', 'a=a', 'a=z',
                 # content of 'a/'
                 'a/a', 'a/a-a', 'a/a-z',
                 'a/a=a', 'a/a=z',
                 'a/z', 'a/z-a', 'a/z-z',
                 'a/z=a', 'a/z=z',
                 # content of 'a/a/'
                 'a/a/a', 'a/a/z',
                 # content of 'a/a-a'
                 'a/a-a/a',
                 # content of 'a/a-z'
                 'a/a-z/z',
                 # content of 'a/a=a'
                 'a/a=a/a',
                 # content of 'a/a=z'
                 'a/a=z/z',
                 # content of 'a/z/'
                 'a/z/a', 'a/z/z',
                 # content of 'a-a'
                 'a-a/a',
                 # content of 'a-z'
                 'a-z/z',
                 # content of 'a=a'
                 'a=a/a',
                 # content of 'a=z'
                 'a=z/z',
                ]
        split_paths = self.split_for_dirblocks(paths)
        sorted_paths = []
        for dir_parts, basename in split_paths:
            if dir_parts == ['']:
                sorted_paths.append(basename)
            else:
                sorted_paths.append('/'.join(dir_parts + [basename]))

        self.assertEqual(sorted_paths, paths)

        for path in paths:
            self.assertBisect(paths, split_paths, path, exists=True)


class TestBisectPathLeft(tests.TestCase, TestBisectPathMixin):
    """Run all Bisect Path tests against _bisect_path_left_py."""

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_py import _bisect_path_left_py
        return _bisect_path_left_py

    def get_bisect(self):
        return bisect.bisect_left, 0


class TestCompiledBisectPathLeft(TestBisectPathLeft):
    """Run all Bisect Path tests against _bisect_path_right_c"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_c import _bisect_path_left_c
        return _bisect_path_left_c


class TestBisectPathRight(tests.TestCase, TestBisectPathMixin):
    """Run all Bisect Path tests against _bisect_path_right_py"""

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_py import _bisect_path_right_py
        return _bisect_path_right_py

    def get_bisect(self):
        return bisect.bisect_right, -1


class TestCompiledBisectPathRight(TestBisectPathRight):
    """Run all Bisect Path tests against _bisect_path_right_c"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_c import _bisect_path_right_c
        return _bisect_path_right_c


class TestBisectDirblock(tests.TestCase):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.

    This test is parameterized by calling get_bisect_dirblock(). Child test
    cases can override this function to test against a different
    implementation.
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
                         ' for key %r'
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


class TestCmpByDirs(tests.TestCase):
    """Test an implementation of cmp_by_dirs()

    cmp_by_dirs() compares 2 paths by their directory sections, rather than as
    plain strings.

    Child test cases can override ``get_cmp_by_dirs`` to test a specific
    implementation.
    """

    def get_cmp_by_dirs(self):
        """Get a specific implementation of cmp_by_dirs."""
        from bzrlib._dirstate_helpers_py import cmp_by_dirs_py
        return cmp_by_dirs_py

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

    def test_cmp_unicode_not_allowed(self):
        cmp_by_dirs = self.get_cmp_by_dirs()
        self.assertRaises(TypeError, cmp_by_dirs, u'Unicode', 'str')
        self.assertRaises(TypeError, cmp_by_dirs, 'str', u'Unicode')
        self.assertRaises(TypeError, cmp_by_dirs, u'Unicode', u'Unicode')

    def test_cmp_non_ascii(self):
        self.assertCmpByDirs(-1, '\xc2\xb5', '\xc3\xa5') # u'\xb5', u'\xe5'
        self.assertCmpByDirs(-1, 'a', '\xc3\xa5') # u'a', u'\xe5'
        self.assertCmpByDirs(-1, 'b', '\xc2\xb5') # u'b', u'\xb5'
        self.assertCmpByDirs(-1, 'a/b', 'a/\xc3\xa5') # u'a/b', u'a/\xe5'
        self.assertCmpByDirs(-1, 'b/a', 'b/\xc2\xb5') # u'b/a', u'b/\xb5'


class TestCompiledCmpByDirs(TestCmpByDirs):
    """Test the pyrex implementation of cmp_by_dirs"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_c import cmp_by_dirs_c
        return cmp_by_dirs_c


class TestCmpPathByDirblock(tests.TestCase):
    """Test an implementation of _cmp_path_by_dirblock()

    _cmp_path_by_dirblock() compares two paths using the sort order used by
    DirState. All paths in the same directory are sorted together.

    Child test cases can override ``get_cmp_path_by_dirblock`` to test a specific
    implementation.
    """

    def get_cmp_path_by_dirblock(self):
        """Get a specific implementation of _cmp_path_by_dirblock."""
        from bzrlib._dirstate_helpers_py import _cmp_path_by_dirblock_py
        return _cmp_path_by_dirblock_py

    def assertCmpPathByDirblock(self, paths):
        """Compare all paths and make sure they evaluate to the correct order.

        This does N^2 comparisons. It is assumed that ``paths`` is properly
        sorted list.

        :param paths: a sorted list of paths to compare
        """
        # First, make sure the paths being passed in are correct
        def _key(p):
            dirname, basename = os.path.split(p)
            return dirname.split('/'), basename
        self.assertEqual(sorted(paths, key=_key), paths)

        cmp_path_by_dirblock = self.get_cmp_path_by_dirblock()
        for idx1, path1 in enumerate(paths):
            for idx2, path2 in enumerate(paths):
                cmp_val = cmp_path_by_dirblock(path1, path2)
                if idx1 < idx2:
                    self.assertTrue(cmp_val < 0,
                        '%s did not state that %r came before %r, cmp=%s'
                        % (cmp_path_by_dirblock.__name__,
                           path1, path2, cmp_val))
                elif idx1 > idx2:
                    self.assertTrue(cmp_val > 0,
                        '%s did not state that %r came after %r, cmp=%s'
                        % (cmp_path_by_dirblock.__name__,
                           path1, path2, cmp_val))
                else: # idx1 == idx2
                    self.assertTrue(cmp_val == 0,
                        '%s did not state that %r == %r, cmp=%s'
                        % (cmp_path_by_dirblock.__name__,
                           path1, path2, cmp_val))

    def test_cmp_simple_paths(self):
        """Compare against the empty string."""
        self.assertCmpPathByDirblock(['', 'a', 'ab', 'abc', 'a/b/c', 'b/d/e'])
        self.assertCmpPathByDirblock(['kl', 'ab/cd', 'ab/ef', 'gh/ij'])

    def test_tricky_paths(self):
        self.assertCmpPathByDirblock([
            # Contents of ''
            '', 'a', 'a-a', 'a=a', 'b',
            # Contents of 'a'
            'a/a', 'a/a-a', 'a/a=a', 'a/b',
            # Contents of 'a/a'
            'a/a/a', 'a/a/a-a', 'a/a/a=a',
            # Contents of 'a/a/a'
            'a/a/a/a', 'a/a/a/b',
            # Contents of 'a/a/a-a',
            'a/a/a-a/a', 'a/a/a-a/b',
            # Contents of 'a/a/a=a',
            'a/a/a=a/a', 'a/a/a=a/b',
            # Contents of 'a/a-a'
            'a/a-a/a',
            # Contents of 'a/a-a/a'
            'a/a-a/a/a', 'a/a-a/a/b',
            # Contents of 'a/a=a'
            'a/a=a/a',
            # Contents of 'a/b'
            'a/b/a', 'a/b/b',
            # Contents of 'a-a',
            'a-a/a', 'a-a/b',
            # Contents of 'a=a',
            'a=a/a', 'a=a/b',
            # Contents of 'b',
            'b/a', 'b/b',
            ])
        self.assertCmpPathByDirblock([
                 # content of '/'
                 '', 'a', 'a-a', 'a-z', 'a=a', 'a=z',
                 # content of 'a/'
                 'a/a', 'a/a-a', 'a/a-z',
                 'a/a=a', 'a/a=z',
                 'a/z', 'a/z-a', 'a/z-z',
                 'a/z=a', 'a/z=z',
                 # content of 'a/a/'
                 'a/a/a', 'a/a/z',
                 # content of 'a/a-a'
                 'a/a-a/a',
                 # content of 'a/a-z'
                 'a/a-z/z',
                 # content of 'a/a=a'
                 'a/a=a/a',
                 # content of 'a/a=z'
                 'a/a=z/z',
                 # content of 'a/z/'
                 'a/z/a', 'a/z/z',
                 # content of 'a-a'
                 'a-a/a',
                 # content of 'a-z'
                 'a-z/z',
                 # content of 'a=a'
                 'a=a/a',
                 # content of 'a=z'
                 'a=z/z',
                ])

    def test_unicode_not_allowed(self):
        cmp_path_by_dirblock = self.get_cmp_path_by_dirblock()
        self.assertRaises(TypeError, cmp_path_by_dirblock, u'Uni', 'str')
        self.assertRaises(TypeError, cmp_path_by_dirblock, 'str', u'Uni')
        self.assertRaises(TypeError, cmp_path_by_dirblock, u'Uni', u'Uni')
        self.assertRaises(TypeError, cmp_path_by_dirblock, u'x/Uni', 'x/str')
        self.assertRaises(TypeError, cmp_path_by_dirblock, 'x/str', u'x/Uni')
        self.assertRaises(TypeError, cmp_path_by_dirblock, u'x/Uni', u'x/Uni')

    def test_nonascii(self):
        self.assertCmpPathByDirblock([
            # content of '/'
            '', 'a', '\xc2\xb5', '\xc3\xa5',
            # content of 'a'
            'a/a', 'a/\xc2\xb5', 'a/\xc3\xa5',
            # content of 'a/a'
            'a/a/a', 'a/a/\xc2\xb5', 'a/a/\xc3\xa5',
            # content of 'a/\xc2\xb5'
            'a/\xc2\xb5/a', 'a/\xc2\xb5/\xc2\xb5', 'a/\xc2\xb5/\xc3\xa5',
            # content of 'a/\xc3\xa5'
            'a/\xc3\xa5/a', 'a/\xc3\xa5/\xc2\xb5', 'a/\xc3\xa5/\xc3\xa5',
            # content of '\xc2\xb5'
            '\xc2\xb5/a', '\xc2\xb5/\xc2\xb5', '\xc2\xb5/\xc3\xa5',
            # content of '\xc2\xe5'
            '\xc3\xa5/a', '\xc3\xa5/\xc2\xb5', '\xc3\xa5/\xc3\xa5',
            ])


class TestCompiledCmpPathByDirblock(TestCmpPathByDirblock):
    """Test the pyrex implementation of _cmp_path_by_dirblock"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_c import _cmp_path_by_dirblock_c
        return _cmp_path_by_dirblock_c


class TestMemRChr(tests.TestCase):
    """Test memrchr functionality"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def assertMemRChr(self, expected, s, c):
        from bzrlib._dirstate_helpers_c import _py_memrchr
        self.assertEqual(expected, _py_memrchr(s, c))

    def test_missing(self):
        self.assertMemRChr(None, '', 'a')
        self.assertMemRChr(None, '', 'c')
        self.assertMemRChr(None, 'abcdefghijklm', 'q')
        self.assertMemRChr(None, 'aaaaaaaaaaaaaaaaaaaaaaa', 'b')

    def test_single_entry(self):
        self.assertMemRChr(0, 'abcdefghijklm', 'a')
        self.assertMemRChr(1, 'abcdefghijklm', 'b')
        self.assertMemRChr(2, 'abcdefghijklm', 'c')
        self.assertMemRChr(10, 'abcdefghijklm', 'k')
        self.assertMemRChr(11, 'abcdefghijklm', 'l')
        self.assertMemRChr(12, 'abcdefghijklm', 'm')

    def test_multiple(self):
        self.assertMemRChr(10, 'abcdefjklmabcdefghijklm', 'a')
        self.assertMemRChr(11, 'abcdefjklmabcdefghijklm', 'b')
        self.assertMemRChr(12, 'abcdefjklmabcdefghijklm', 'c')
        self.assertMemRChr(20, 'abcdefjklmabcdefghijklm', 'k')
        self.assertMemRChr(21, 'abcdefjklmabcdefghijklm', 'l')
        self.assertMemRChr(22, 'abcdefjklmabcdefghijklm', 'm')
        self.assertMemRChr(22, 'aaaaaaaaaaaaaaaaaaaaaaa', 'a')

    def test_with_nulls(self):
        self.assertMemRChr(10, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'a')
        self.assertMemRChr(11, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'b')
        self.assertMemRChr(12, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'c')
        self.assertMemRChr(20, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'k')
        self.assertMemRChr(21, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'l')
        self.assertMemRChr(22, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'm')
        self.assertMemRChr(22, 'aaa\0\0\0aaaaaaa\0\0\0aaaaaaa', 'a')
        self.assertMemRChr(9, '\0\0\0\0\0\0\0\0\0\0', '\0')


class TestReadDirblocks(test_dirstate.TestCaseWithDirState):
    """Test an implementation of _read_dirblocks()

    _read_dirblocks() reads in all of the dirblock information from the disk
    file.

    Child test cases can override ``get_read_dirblocks`` to test a specific
    implementation.
    """

    def get_read_dirblocks(self):
        from bzrlib._dirstate_helpers_py import _read_dirblocks_py
        return _read_dirblocks_py

    def test_smoketest(self):
        """Make sure that we can create and read back a simple file."""
        tree, state, expected = self.create_basic_dirstate()
        del tree
        state._read_header_if_needed()
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                         state._dirblock_state)
        read_dirblocks = self.get_read_dirblocks()
        read_dirblocks(state)
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

    def test_trailing_garbage(self):
        tree, state, expected = self.create_basic_dirstate()
        # We can modify the file as long as it hasn't been read yet.
        f = open('dirstate', 'ab')
        try:
            # Add bogus trailing garbage
            f.write('bogus\n')
        finally:
            f.close()
        e = self.assertRaises(errors.DirstateCorrupt,
                              state._read_dirblocks_if_needed)
        # Make sure we mention the bogus characters in the error
        self.assertContainsRe(str(e), 'bogus')


class TestCompiledReadDirblocks(TestReadDirblocks):
    """Test the pyrex implementation of _read_dirblocks"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_read_dirblocks(self):
        from bzrlib._dirstate_helpers_c import _read_dirblocks_c
        return _read_dirblocks_c


class TestUsingCompiledIfAvailable(tests.TestCase):
    """Check that any compiled functions that are available are the default.

    It is possible to have typos, etc in the import line, such that
    _dirstate_helpers_c is actually available, but the compiled functions are
    not being used.
    """

    def test_bisect_dirblock(self):
        if CompiledDirstateHelpersFeature.available():
            from bzrlib._dirstate_helpers_c import bisect_dirblock_c
            self.assertIs(bisect_dirblock_c, dirstate.bisect_dirblock)
        else:
            from bzrlib._dirstate_helpers_py import bisect_dirblock_py
            self.assertIs(bisect_dirblock_py, dirstate.bisect_dirblock)

    def test__bisect_path_left(self):
        if CompiledDirstateHelpersFeature.available():
            from bzrlib._dirstate_helpers_c import _bisect_path_left_c
            self.assertIs(_bisect_path_left_c, dirstate._bisect_path_left)
        else:
            from bzrlib._dirstate_helpers_py import _bisect_path_left_py
            self.assertIs(_bisect_path_left_py, dirstate._bisect_path_left)

    def test__bisect_path_right(self):
        if CompiledDirstateHelpersFeature.available():
            from bzrlib._dirstate_helpers_c import _bisect_path_right_c
            self.assertIs(_bisect_path_right_c, dirstate._bisect_path_right)
        else:
            from bzrlib._dirstate_helpers_py import _bisect_path_right_py
            self.assertIs(_bisect_path_right_py, dirstate._bisect_path_right)

    def test_cmp_by_dirs(self):
        if CompiledDirstateHelpersFeature.available():
            from bzrlib._dirstate_helpers_c import cmp_by_dirs_c
            self.assertIs(cmp_by_dirs_c, dirstate.cmp_by_dirs)
        else:
            from bzrlib._dirstate_helpers_py import cmp_by_dirs_py
            self.assertIs(cmp_by_dirs_py, dirstate.cmp_by_dirs)

    def test__read_dirblocks(self):
        if CompiledDirstateHelpersFeature.available():
            from bzrlib._dirstate_helpers_c import _read_dirblocks_c
            self.assertIs(_read_dirblocks_c, dirstate._read_dirblocks)
        else:
            from bzrlib._dirstate_helpers_py import _read_dirblocks_py
            self.assertIs(_read_dirblocks_py, dirstate._read_dirblocks)

    def test_update_entry(self):
        if CompiledDirstateHelpersFeature.available():
            from bzrlib._dirstate_helpers_c import update_entry
            self.assertIs(update_entry, dirstate.update_entry)
        else:
            from bzrlib.dirstate import py_update_entry
            self.assertIs(py_update_entry, dirstate.py_update_entry)


class TestUpdateEntry(test_dirstate.TestCaseWithDirState):
    """Test the DirState.update_entry functions"""

    def get_state_with_a(self):
        """Create a DirState tracking a single object named 'a'"""
        state = test_dirstate.InstrumentedDirState.initialize('dirstate')
        self.addCleanup(state.unlock)
        state.add('a', 'a-id', 'file', None, '')
        entry = state._get_entry(0, path_utf8='a')
        self.set_update_entry()
        return state, entry

    def set_update_entry(self):
        self.update_entry = dirstate.py_update_entry

    def test_update_entry(self):
        state, entry = self.get_state_with_a()
        self.build_tree(['a'])
        # Add one where we don't provide the stat or sha already
        self.assertEqual(('', 'a', 'a-id'), entry[0])
        self.assertEqual([('f', '', 0, False, dirstate.DirState.NULLSTAT)],
                         entry[1])
        # Flush the buffers to disk
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)

        # The dirblock entry should not cache the file's sha1
        self.assertEqual([('f', '', 14, False, dirstate.DirState.NULLSTAT)],
                         entry[1])
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                         state._dirblock_state)
        mode = stat_value.st_mode
        self.assertEqual([('sha1', 'a'), ('is_exec', mode, False)], state._log)

        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

        # If we do it again right away, we don't know if the file has changed
        # so we will re-read the file. Roll the clock back so the file is
        # guaranteed to look too new.
        state.adjust_time(-10)

        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual([('sha1', 'a'), ('is_exec', mode, False),
                          ('sha1', 'a'), ('is_exec', mode, False),
                         ], state._log)
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                         state._dirblock_state)
        self.assertEqual([('f', '', 14, False, dirstate.DirState.NULLSTAT)],
                         entry[1])
        state.save()

        # However, if we move the clock forward so the file is considered
        # "stable", it should just cache the value.
        state.adjust_time(+20)
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)
        self.assertEqual([('sha1', 'a'), ('is_exec', mode, False),
                          ('sha1', 'a'), ('is_exec', mode, False),
                          ('sha1', 'a'), ('is_exec', mode, False),
                         ], state._log)
        self.assertEqual([('f', link_or_sha1, 14, False, packed_stat)],
                         entry[1])

        # Subsequent calls will just return the cached value
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)
        self.assertEqual([('sha1', 'a'), ('is_exec', mode, False),
                          ('sha1', 'a'), ('is_exec', mode, False),
                          ('sha1', 'a'), ('is_exec', mode, False),
                         ], state._log)
        self.assertEqual([('f', link_or_sha1, 14, False, packed_stat)],
                         entry[1])

    def test_update_entry_symlink(self):
        """Update entry should read symlinks."""
        self.requireFeature(SymlinkFeature)
        state, entry = self.get_state_with_a()
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        os.symlink('target', 'a')

        state.adjust_time(-10) # Make the symlink look new
        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('target', link_or_sha1)
        self.assertEqual([('read_link', 'a', '')], state._log)
        # Dirblock is not updated (the link is too new)
        self.assertEqual([('l', '', 6, False, dirstate.DirState.NULLSTAT)],
                         entry[1])
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                         state._dirblock_state)

        # Because the stat_value looks new, we should re-read the target
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('target', link_or_sha1)
        self.assertEqual([('read_link', 'a', ''),
                          ('read_link', 'a', ''),
                         ], state._log)
        self.assertEqual([('l', '', 6, False, dirstate.DirState.NULLSTAT)],
                         entry[1])
        state.adjust_time(+20) # Skip into the future, all files look old
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('target', link_or_sha1)
        # We need to re-read the link because only now can we cache it
        self.assertEqual([('read_link', 'a', ''),
                          ('read_link', 'a', ''),
                          ('read_link', 'a', ''),
                         ], state._log)
        self.assertEqual([('l', 'target', 6, False, packed_stat)],
                         entry[1])

        # Another call won't re-read the link
        self.assertEqual([('read_link', 'a', ''),
                          ('read_link', 'a', ''),
                          ('read_link', 'a', ''),
                         ], state._log)
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('target', link_or_sha1)
        self.assertEqual([('l', 'target', 6, False, packed_stat)],
                         entry[1])

    def do_update_entry(self, state, entry, abspath):
        stat_value = os.lstat(abspath)
        return self.update_entry(state, entry, abspath, stat_value)

    def test_update_entry_dir(self):
        state, entry = self.get_state_with_a()
        self.build_tree(['a/'])
        self.assertIs(None, self.do_update_entry(state, entry, 'a'))

    def test_update_entry_dir_unchanged(self):
        state, entry = self.get_state_with_a()
        self.build_tree(['a/'])
        state.adjust_time(+20)
        self.assertIs(None, self.do_update_entry(state, entry, 'a'))
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                         state._dirblock_state)
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        self.assertIs(None, self.do_update_entry(state, entry, 'a'))
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

    def test_update_entry_file_unchanged(self):
        state, entry = self.get_state_with_a()
        self.build_tree(['a'])
        sha1sum = 'b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6'
        state.adjust_time(+20)
        self.assertEqual(sha1sum, self.do_update_entry(state, entry, 'a'))
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                         state._dirblock_state)
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        self.assertEqual(sha1sum, self.do_update_entry(state, entry, 'a'))
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

    def create_and_test_file(self, state, entry):
        """Create a file at 'a' and verify the state finds it.

        The state should already be versioning *something* at 'a'. This makes
        sure that state.update_entry recognizes it as a file.
        """
        self.build_tree(['a'])
        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath='a')
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)
        self.assertEqual([('f', link_or_sha1, 14, False, packed_stat)],
                         entry[1])
        return packed_stat

    def create_and_test_dir(self, state, entry):
        """Create a directory at 'a' and verify the state finds it.

        The state should already be versioning *something* at 'a'. This makes
        sure that state.update_entry recognizes it as a directory.
        """
        self.build_tree(['a/'])
        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath='a')
        self.assertIs(None, link_or_sha1)
        self.assertEqual([('d', '', 0, False, packed_stat)], entry[1])

        return packed_stat

    def create_and_test_symlink(self, state, entry):
        """Create a symlink at 'a' and verify the state finds it.

        The state should already be versioning *something* at 'a'. This makes
        sure that state.update_entry recognizes it as a symlink.

        This should not be called if this platform does not have symlink
        support.
        """
        # caller should care about skipping test on platforms without symlinks
        os.symlink('path/to/foo', 'a')

        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath='a')
        self.assertEqual('path/to/foo', link_or_sha1)
        self.assertEqual([('l', 'path/to/foo', 11, False, packed_stat)],
                         entry[1])
        return packed_stat

    def test_update_file_to_dir(self):
        """If a file changes to a directory we return None for the sha.
        We also update the inventory record.
        """
        state, entry = self.get_state_with_a()
        # The file sha1 won't be cached unless the file is old
        state.adjust_time(+10)
        self.create_and_test_file(state, entry)
        os.remove('a')
        self.create_and_test_dir(state, entry)

    def test_update_file_to_symlink(self):
        """File becomes a symlink"""
        self.requireFeature(SymlinkFeature)
        state, entry = self.get_state_with_a()
        # The file sha1 won't be cached unless the file is old
        state.adjust_time(+10)
        self.create_and_test_file(state, entry)
        os.remove('a')
        self.create_and_test_symlink(state, entry)

    def test_update_dir_to_file(self):
        """Directory becoming a file updates the entry."""
        state, entry = self.get_state_with_a()
        # The file sha1 won't be cached unless the file is old
        state.adjust_time(+10)
        self.create_and_test_dir(state, entry)
        os.rmdir('a')
        self.create_and_test_file(state, entry)

    def test_update_dir_to_symlink(self):
        """Directory becomes a symlink"""
        self.requireFeature(SymlinkFeature)
        state, entry = self.get_state_with_a()
        # The symlink target won't be cached if it isn't old
        state.adjust_time(+10)
        self.create_and_test_dir(state, entry)
        os.rmdir('a')
        self.create_and_test_symlink(state, entry)

    def test_update_symlink_to_file(self):
        """Symlink becomes a file"""
        self.requireFeature(SymlinkFeature)
        state, entry = self.get_state_with_a()
        # The symlink and file info won't be cached unless old
        state.adjust_time(+10)
        self.create_and_test_symlink(state, entry)
        os.remove('a')
        self.create_and_test_file(state, entry)

    def test_update_symlink_to_dir(self):
        """Symlink becomes a directory"""
        self.requireFeature(SymlinkFeature)
        state, entry = self.get_state_with_a()
        # The symlink target won't be cached if it isn't old
        state.adjust_time(+10)
        self.create_and_test_symlink(state, entry)
        os.remove('a')
        self.create_and_test_dir(state, entry)

    def test__is_executable_win32(self):
        state, entry = self.get_state_with_a()
        self.build_tree(['a'])

        # Make sure we are using the win32 implementation of _is_executable
        state._is_executable = state._is_executable_win32

        # The file on disk is not executable, but we are marking it as though
        # it is. With _is_executable_win32 we ignore what is on disk.
        entry[1][0] = ('f', '', 0, True, dirstate.DirState.NULLSTAT)

        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)

        state.adjust_time(-10) # Make sure everything is new
        self.update_entry(state, entry, abspath='a', stat_value=stat_value)

        # The row is updated, but the executable bit stays set.
        self.assertEqual([('f', '', 14, True, dirstate.DirState.NULLSTAT)],
                         entry[1])

        # Make the disk object look old enough to cache
        state.adjust_time(+20)
        digest = 'b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6'
        self.update_entry(state, entry, abspath='a', stat_value=stat_value)
        self.assertEqual([('f', digest, 14, True, packed_stat)], entry[1])


class TestCompiledUpdateEntry(TestUpdateEntry):
    """Test the pyrex implementation of _read_dirblocks"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def set_update_entry(self):
        from bzrlib._dirstate_helpers_c import update_entry
        self.update_entry = update_entry

# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for the compiled dirstate helpers."""

import bisect
import os
import time

from bzrlib import (
    dirstate,
    errors,
    osutils,
    tests,
    _dirstate_helpers_py,
    )
from bzrlib.tests import (
    test_dirstate,
    )
from bzrlib.tests.test_osutils import dir_reader_scenarios
from bzrlib.tests.scenarios import (
    load_tests_apply_scenarios,
    multiply_scenarios,
    )
from bzrlib.tests import (
    features,
    )


load_tests = load_tests_apply_scenarios


compiled_dirstate_helpers_feature = features.ModuleAvailableFeature(
    'bzrlib._dirstate_helpers_pyx')


# FIXME: we should also parametrize against SHA1Provider !

ue_scenarios = [('dirstate_Python',
    {'update_entry': dirstate.py_update_entry})]
if compiled_dirstate_helpers_feature.available():
    update_entry = compiled_dirstate_helpers_feature.module.update_entry
    ue_scenarios.append(('dirstate_Pyrex', {'update_entry': update_entry}))

pe_scenarios = [('dirstate_Python',
    {'_process_entry': dirstate.ProcessEntryPython})]
if compiled_dirstate_helpers_feature.available():
    process_entry = compiled_dirstate_helpers_feature.module.ProcessEntryC
    pe_scenarios.append(('dirstate_Pyrex', {'_process_entry': process_entry}))

helper_scenarios = [('dirstate_Python', {'helpers': _dirstate_helpers_py})]
if compiled_dirstate_helpers_feature.available():
    helper_scenarios.append(('dirstate_Pyrex',
        {'helpers': compiled_dirstate_helpers_feature.module}))


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
    """Run all Bisect Path tests against _bisect_path_left."""

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_py import _bisect_path_left
        return _bisect_path_left

    def get_bisect(self):
        return bisect.bisect_left, 0


class TestCompiledBisectPathLeft(TestBisectPathLeft):
    """Run all Bisect Path tests against _bisect_path_lect"""

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_pyx import _bisect_path_left
        return _bisect_path_left


class TestBisectPathRight(tests.TestCase, TestBisectPathMixin):
    """Run all Bisect Path tests against _bisect_path_right"""

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_py import _bisect_path_right
        return _bisect_path_right

    def get_bisect(self):
        return bisect.bisect_right, -1


class TestCompiledBisectPathRight(TestBisectPathRight):
    """Run all Bisect Path tests against _bisect_path_right"""

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_pyx import _bisect_path_right
        return _bisect_path_right


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
        from bzrlib._dirstate_helpers_py import bisect_dirblock
        return bisect_dirblock

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

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_bisect_dirblock(self):
        from bzrlib._dirstate_helpers_pyx import bisect_dirblock
        return bisect_dirblock


class TestCmpByDirs(tests.TestCase):
    """Test an implementation of cmp_by_dirs()

    cmp_by_dirs() compares 2 paths by their directory sections, rather than as
    plain strings.

    Child test cases can override ``get_cmp_by_dirs`` to test a specific
    implementation.
    """

    def get_cmp_by_dirs(self):
        """Get a specific implementation of cmp_by_dirs."""
        from bzrlib._dirstate_helpers_py import cmp_by_dirs
        return cmp_by_dirs

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

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_pyx import cmp_by_dirs
        return cmp_by_dirs


class TestCmpPathByDirblock(tests.TestCase):
    """Test an implementation of _cmp_path_by_dirblock()

    _cmp_path_by_dirblock() compares two paths using the sort order used by
    DirState. All paths in the same directory are sorted together.

    Child test cases can override ``get_cmp_path_by_dirblock`` to test a specific
    implementation.
    """

    def get_cmp_path_by_dirblock(self):
        """Get a specific implementation of _cmp_path_by_dirblock."""
        from bzrlib._dirstate_helpers_py import _cmp_path_by_dirblock
        return _cmp_path_by_dirblock

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

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_pyx import _cmp_path_by_dirblock
        return _cmp_path_by_dirblock


class TestMemRChr(tests.TestCase):
    """Test memrchr functionality"""

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def assertMemRChr(self, expected, s, c):
        from bzrlib._dirstate_helpers_pyx import _py_memrchr
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

    # inherits scenarios from test_dirstate

    def get_read_dirblocks(self):
        from bzrlib._dirstate_helpers_py import _read_dirblocks
        return _read_dirblocks

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
        # On Unix, we can write extra data as long as we haven't read yet, but
        # on Win32, if you've opened the file with FILE_SHARE_READ, trying to
        # open it in append mode will fail.
        state.unlock()
        f = open('dirstate', 'ab')
        try:
            # Add bogus trailing garbage
            f.write('bogus\n')
        finally:
            f.close()
            state.lock_read()
        e = self.assertRaises(errors.DirstateCorrupt,
                              state._read_dirblocks_if_needed)
        # Make sure we mention the bogus characters in the error
        self.assertContainsRe(str(e), 'bogus')


class TestCompiledReadDirblocks(TestReadDirblocks):
    """Test the pyrex implementation of _read_dirblocks"""

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_read_dirblocks(self):
        from bzrlib._dirstate_helpers_pyx import _read_dirblocks
        return _read_dirblocks


class TestUsingCompiledIfAvailable(tests.TestCase):
    """Check that any compiled functions that are available are the default.

    It is possible to have typos, etc in the import line, such that
    _dirstate_helpers_pyx is actually available, but the compiled functions are
    not being used.
    """

    def test_bisect_dirblock(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import bisect_dirblock
        else:
            from bzrlib._dirstate_helpers_py import bisect_dirblock
        self.assertIs(bisect_dirblock, dirstate.bisect_dirblock)

    def test__bisect_path_left(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import _bisect_path_left
        else:
            from bzrlib._dirstate_helpers_py import _bisect_path_left
        self.assertIs(_bisect_path_left, dirstate._bisect_path_left)

    def test__bisect_path_right(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import _bisect_path_right
        else:
            from bzrlib._dirstate_helpers_py import _bisect_path_right
        self.assertIs(_bisect_path_right, dirstate._bisect_path_right)

    def test_cmp_by_dirs(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import cmp_by_dirs
        else:
            from bzrlib._dirstate_helpers_py import cmp_by_dirs
        self.assertIs(cmp_by_dirs, dirstate.cmp_by_dirs)

    def test__read_dirblocks(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import _read_dirblocks
        else:
            from bzrlib._dirstate_helpers_py import _read_dirblocks
        self.assertIs(_read_dirblocks, dirstate._read_dirblocks)

    def test_update_entry(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import update_entry
        else:
            from bzrlib.dirstate import update_entry
        self.assertIs(update_entry, dirstate.update_entry)

    def test_process_entry(self):
        if compiled_dirstate_helpers_feature.available():
            from bzrlib._dirstate_helpers_pyx import ProcessEntryC
            self.assertIs(ProcessEntryC, dirstate._process_entry)
        else:
            from bzrlib.dirstate import ProcessEntryPython
            self.assertIs(ProcessEntryPython, dirstate._process_entry)


class TestUpdateEntry(test_dirstate.TestCaseWithDirState):
    """Test the DirState.update_entry functions"""

    scenarios = multiply_scenarios(
        dir_reader_scenarios(), ue_scenarios)

    # Set by load_tests
    update_entry = None

    def setUp(self):
        super(TestUpdateEntry, self).setUp()
        self.overrideAttr(dirstate, 'update_entry', self.update_entry)

    def get_state_with_a(self):
        """Create a DirState tracking a single object named 'a'"""
        state = test_dirstate.InstrumentedDirState.initialize('dirstate')
        self.addCleanup(state.unlock)
        state.add('a', 'a-id', 'file', None, '')
        entry = state._get_entry(0, path_utf8='a')
        return state, entry

    def test_observed_sha1_cachable(self):
        state, entry = self.get_state_with_a()
        state.save()
        atime = time.time() - 10
        self.build_tree(['a'])
        statvalue = test_dirstate._FakeStat.from_stat(os.lstat('a'))
        statvalue.st_mtime = statvalue.st_ctime = atime
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        state._observed_sha1(entry, "foo", statvalue)
        self.assertEqual('foo', entry[1][0][1])
        packed_stat = dirstate.pack_stat(statvalue)
        self.assertEqual(packed_stat, entry[1][0][4])
        self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                         state._dirblock_state)

    def test_observed_sha1_not_cachable(self):
        state, entry = self.get_state_with_a()
        state.save()
        oldval = entry[1][0][1]
        oldstat = entry[1][0][4]
        self.build_tree(['a'])
        statvalue = os.lstat('a')
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        state._observed_sha1(entry, "foo", statvalue)
        self.assertEqual(oldval, entry[1][0][1])
        self.assertEqual(oldstat, entry[1][0][4])
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

    def test_update_entry(self):
        state, _ = self.get_state_with_a()
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        empty_revid = tree.commit('empty')
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a-id'])
        with_a_id = tree.commit('with_a')
        self.addCleanup(tree.unlock)
        state.set_parent_trees(
            [(empty_revid, tree.branch.repository.revision_tree(empty_revid))],
            [])
        entry = state._get_entry(0, path_utf8='a')
        self.build_tree(['a'])
        # Add one where we don't provide the stat or sha already
        self.assertEqual(('', 'a', 'a-id'), entry[0])
        self.assertEqual(('f', '', 0, False, dirstate.DirState.NULLSTAT),
                         entry[1][0])
        # Flush the buffers to disk
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual(None, link_or_sha1)

        # The dirblock entry should not have computed or cached the file's
        # sha1, but it did update the files' st_size. However, this is not
        # worth writing a dirstate file for, so we leave the state UNMODIFIED
        self.assertEqual(('f', '', 14, False, dirstate.DirState.NULLSTAT),
                         entry[1][0])
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        mode = stat_value.st_mode
        self.assertEqual([('is_exec', mode, False)], state._log)

        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

        # Roll the clock back so the file is guaranteed to look too new. We
        # should still not compute the sha1.
        state.adjust_time(-10)
        del state._log[:]

        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual([('is_exec', mode, False)], state._log)
        self.assertEqual(None, link_or_sha1)
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        self.assertEqual(('f', '', 14, False, dirstate.DirState.NULLSTAT),
                         entry[1][0])
        state.save()

        # If it is cachable (the clock has moved forward) but new it still
        # won't calculate the sha or cache it.
        state.adjust_time(+20)
        del state._log[:]
        link_or_sha1 = dirstate.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual(None, link_or_sha1)
        self.assertEqual([('is_exec', mode, False)], state._log)
        self.assertEqual(('f', '', 14, False, dirstate.DirState.NULLSTAT),
                         entry[1][0])
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

        # If the file is no longer new, and the clock has been moved forward
        # sufficiently, it will cache the sha.
        del state._log[:]
        state.set_parent_trees(
            [(with_a_id, tree.branch.repository.revision_tree(with_a_id))],
            [])
        entry = state._get_entry(0, path_utf8='a')

        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)
        self.assertEqual([('is_exec', mode, False), ('sha1', 'a')],
                          state._log)
        self.assertEqual(('f', link_or_sha1, 14, False, packed_stat),
                         entry[1][0])

        # Subsequent calls will just return the cached value
        del state._log[:]
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6',
                         link_or_sha1)
        self.assertEqual([], state._log)
        self.assertEqual(('f', link_or_sha1, 14, False, packed_stat),
                         entry[1][0])

    def test_update_entry_symlink(self):
        """Update entry should read symlinks."""
        self.requireFeature(features.SymlinkFeature)
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
        # The file entry turned into a symlink, that is considered
        # HASH modified worthy.
        self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                         state._dirblock_state)

        # Because the stat_value looks new, we should re-read the target
        del state._log[:]
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        self.assertEqual('target', link_or_sha1)
        self.assertEqual([('read_link', 'a', '')], state._log)
        self.assertEqual([('l', '', 6, False, dirstate.DirState.NULLSTAT)],
                         entry[1])
        state.save()
        state.adjust_time(+20) # Skip into the future, all files look old
        del state._log[:]
        link_or_sha1 = self.update_entry(state, entry, abspath='a',
                                          stat_value=stat_value)
        # The symlink stayed a symlink. So while it is new enough to cache, we
        # don't bother setting the flag, because it is not really worth saving
        # (when we stat the symlink, we'll have paged in the target.)
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        self.assertEqual('target', link_or_sha1)
        # We need to re-read the link because only now can we cache it
        self.assertEqual([('read_link', 'a', '')], state._log)
        self.assertEqual([('l', 'target', 6, False, packed_stat)],
                         entry[1])

        del state._log[:]
        # Another call won't re-read the link
        self.assertEqual([], state._log)
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
        # a/ used to be a file, but is now a directory, worth saving
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                         state._dirblock_state)
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        # No changes to a/ means not worth saving.
        self.assertIs(None, self.do_update_entry(state, entry, 'a'))
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        # Change the last-modified time for the directory
        t = time.time() - 100.0
        try:
            os.utime('a', (t, t))
        except OSError:
            # It looks like Win32 + FAT doesn't allow to change times on a dir.
            raise tests.TestSkipped("can't update mtime of a dir on FAT")
        saved_packed_stat = entry[1][0][-1]
        self.assertIs(None, self.do_update_entry(state, entry, 'a'))
        # We *do* go ahead and update the information in the dirblocks, but we
        # don't bother setting IN_MEMORY_MODIFIED because it is trivial to
        # recompute.
        self.assertNotEqual(saved_packed_stat, entry[1][0][-1])
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)

    def test_update_entry_file_unchanged(self):
        state, _ = self.get_state_with_a()
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a-id'])
        with_a_id = tree.commit('witha')
        self.addCleanup(tree.unlock)
        state.set_parent_trees(
            [(with_a_id, tree.branch.repository.revision_tree(with_a_id))],
            [])
        entry = state._get_entry(0, path_utf8='a')
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

    def test_update_entry_tree_reference(self):
        state = test_dirstate.InstrumentedDirState.initialize('dirstate')
        self.addCleanup(state.unlock)
        state.add('r', 'r-id', 'tree-reference', None, '')
        self.build_tree(['r/'])
        entry = state._get_entry(0, path_utf8='r')
        self.do_update_entry(state, entry, 'r')
        entry = state._get_entry(0, path_utf8='r')
        self.assertEqual('t', entry[1][0][0])

    def create_and_test_file(self, state, entry):
        """Create a file at 'a' and verify the state finds it during update.

        The state should already be versioning *something* at 'a'. This makes
        sure that state.update_entry recognizes it as a file.
        """
        self.build_tree(['a'])
        stat_value = os.lstat('a')
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath='a')
        self.assertEqual(None, link_or_sha1)
        self.assertEqual([('f', '', 14, False, dirstate.DirState.NULLSTAT)],
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

    # FIXME: Add unicode version
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
        self.requireFeature(features.SymlinkFeature)
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
        self.requireFeature(features.SymlinkFeature)
        state, entry = self.get_state_with_a()
        # The symlink target won't be cached if it isn't old
        state.adjust_time(+10)
        self.create_and_test_dir(state, entry)
        os.rmdir('a')
        self.create_and_test_symlink(state, entry)

    def test_update_symlink_to_file(self):
        """Symlink becomes a file"""
        self.requireFeature(features.SymlinkFeature)
        state, entry = self.get_state_with_a()
        # The symlink and file info won't be cached unless old
        state.adjust_time(+10)
        self.create_and_test_symlink(state, entry)
        os.remove('a')
        self.create_and_test_file(state, entry)

    def test_update_symlink_to_dir(self):
        """Symlink becomes a directory"""
        self.requireFeature(features.SymlinkFeature)
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

        # Make the disk object look old enough to cache (but it won't cache the
        # sha as it is a new file).
        state.adjust_time(+20)
        digest = 'b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6'
        self.update_entry(state, entry, abspath='a', stat_value=stat_value)
        self.assertEqual([('f', '', 14, True, dirstate.DirState.NULLSTAT)],
            entry[1])

    def _prepare_tree(self):
        # Create a tree
        text = 'Hello World\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a file', text)])
        tree.add('a file', 'a-file-id')
        # Note: dirstate does not sha prior to the first commit
        # so commit now in order for the test to work
        tree.commit('first')
        return tree, text

    def test_sha1provider_sha1_used(self):
        tree, text = self._prepare_tree()
        state = dirstate.DirState.from_tree(tree, 'dirstate',
            UppercaseSHA1Provider())
        self.addCleanup(state.unlock)
        expected_sha = osutils.sha_string(text.upper() + "foo")
        entry = state._get_entry(0, path_utf8='a file')
        state._sha_cutoff_time()
        state._cutoff_time += 10
        sha1 = self.update_entry(state, entry, 'tree/a file',
                                 os.lstat('tree/a file'))
        self.assertEqual(expected_sha, sha1)

    def test_sha1provider_stat_and_sha1_used(self):
        tree, text = self._prepare_tree()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        state = tree._current_dirstate()
        state._sha1_provider = UppercaseSHA1Provider()
        # If we used the standard provider, it would look like nothing has
        # changed
        file_ids_changed = [change[0] for change
                            in tree.iter_changes(tree.basis_tree())]
        self.assertEqual(['a-file-id'], file_ids_changed)


class UppercaseSHA1Provider(dirstate.SHA1Provider):
    """A custom SHA1Provider."""

    def sha1(self, abspath):
        return self.stat_and_sha1(abspath)[1]

    def stat_and_sha1(self, abspath):
        file_obj = file(abspath, 'rb')
        try:
            statvalue = os.fstat(file_obj.fileno())
            text = ''.join(file_obj.readlines())
            sha1 = osutils.sha_string(text.upper() + "foo")
        finally:
            file_obj.close()
        return statvalue, sha1


class TestProcessEntry(test_dirstate.TestCaseWithDirState):

    scenarios = multiply_scenarios(dir_reader_scenarios(), pe_scenarios)

    # Set by load_tests
    _process_entry = None

    def setUp(self):
        super(TestProcessEntry, self).setUp()
        self.overrideAttr(dirstate, '_process_entry', self._process_entry)

    def assertChangedFileIds(self, expected, tree):
        tree.lock_read()
        try:
            file_ids = [info[0] for info
                        in tree.iter_changes(tree.basis_tree())]
        finally:
            tree.unlock()
        self.assertEqual(sorted(expected), sorted(file_ids))

    def test_exceptions_raised(self):
        # This is a direct test of bug #495023, it relies on osutils.is_inside
        # getting called in an inner function. Which makes it a bit brittle,
        # but at least it does reproduce the bug.
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file', 'tree/dir/', 'tree/dir/sub',
                         'tree/dir2/', 'tree/dir2/sub2'])
        tree.add(['file', 'dir', 'dir/sub', 'dir2', 'dir2/sub2'])
        tree.commit('first commit')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis_tree = tree.basis_tree()
        def is_inside_raises(*args, **kwargs):
            raise RuntimeError('stop this')
        self.overrideAttr(osutils, 'is_inside', is_inside_raises)
        self.assertListRaises(RuntimeError, tree.iter_changes, basis_tree)

    def test_simple_changes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add(['file'], ['file-id'])
        self.assertChangedFileIds([tree.get_root_id(), 'file-id'], tree)
        tree.commit('one')
        self.assertChangedFileIds([], tree)

    def test_sha1provider_stat_and_sha1_used(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add(['file'], ['file-id'])
        tree.commit('one')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        state = tree._current_dirstate()
        state._sha1_provider = UppercaseSHA1Provider()
        self.assertChangedFileIds(['file-id'], tree)


class TestPackStat(tests.TestCase):
    """Check packed representaton of stat values is robust on all inputs"""

    scenarios = helper_scenarios

    def pack(self, statlike_tuple):
        return self.helpers.pack_stat(os.stat_result(statlike_tuple))

    @staticmethod
    def unpack_field(packed_string, stat_field):
        return _dirstate_helpers_py._unpack_stat(packed_string)[stat_field]

    def test_result(self):
        self.assertEqual("AAAQAAAAABAAAAARAAAAAgAAAAEAAIHk",
            self.pack((33252, 1, 2, 0, 0, 0, 4096, 15.5, 16.5, 17.5)))

    def test_giant_inode(self):
        packed = self.pack((33252, 0xF80000ABC, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(0x80000ABC, self.unpack_field(packed, "st_ino"))

    def test_giant_size(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, (1 << 33) + 4096, 0, 0, 0))
        self.assertEqual(4096, self.unpack_field(packed, "st_size"))

    def test_fractional_mtime(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, 0, 0, 16.9375, 0))
        self.assertEqual(16, self.unpack_field(packed, "st_mtime"))

    def test_ancient_mtime(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, 0, 0, -11644473600.0, 0))
        self.assertEqual(1240428288, self.unpack_field(packed, "st_mtime"))

    def test_distant_mtime(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, 0, 0, 64060588800.0, 0))
        self.assertEqual(3931046656, self.unpack_field(packed, "st_mtime"))

    def test_fractional_ctime(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, 0, 0, 0, 17.5625))
        self.assertEqual(17, self.unpack_field(packed, "st_ctime"))

    def test_ancient_ctime(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, 0, 0, 0, -11644473600.0))
        self.assertEqual(1240428288, self.unpack_field(packed, "st_ctime"))

    def test_distant_ctime(self):
        packed = self.pack((33252, 0, 0, 0, 0, 0, 0, 0, 0, 64060588800.0))
        self.assertEqual(3931046656, self.unpack_field(packed, "st_ctime"))

    def test_negative_dev(self):
        packed = self.pack((33252, 0, -0xFFFFFCDE, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(0x322, self.unpack_field(packed, "st_dev"))

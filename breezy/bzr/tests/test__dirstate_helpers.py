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

from ... import osutils, tests
from ...tests import features
from ...tests.scenarios import load_tests_apply_scenarios, multiply_scenarios
from ...tests.test_osutils import dir_reader_scenarios
from .. import _dirstate_helpers_py, dirstate
from . import test_dirstate

load_tests = load_tests_apply_scenarios


compiled_dirstate_helpers_feature = features.ModuleAvailableFeature(
    "breezy.bzr._dirstate_helpers_pyx"
)


# FIXME: we should also parametrize against SHA1Provider !

ue_scenarios = [("dirstate_Python", {"update_entry": dirstate.py_update_entry})]
if compiled_dirstate_helpers_feature.available():
    update_entry = compiled_dirstate_helpers_feature.module.update_entry
    ue_scenarios.append(("dirstate_Pyrex", {"update_entry": update_entry}))

pe_scenarios = [("dirstate_Python", {"_process_entry": dirstate.ProcessEntryPython})]
if compiled_dirstate_helpers_feature.available():
    process_entry = compiled_dirstate_helpers_feature.module.ProcessEntryC
    pe_scenarios.append(("dirstate_Pyrex", {"_process_entry": process_entry}))

helper_scenarios = [("dirstate_Python", {"helpers": _dirstate_helpers_py})]
if compiled_dirstate_helpers_feature.available():
    helper_scenarios.append(
        ("dirstate_Pyrex", {"helpers": compiled_dirstate_helpers_feature.module})
    )


class TestBisectPathMixin:
    """Test that _bisect_path_*() returns the expected values.

    _bisect_path_* is intended to work like bisect.bisect_*() except it
    knows it is working on paths that are sorted by ('path', 'to', 'foo')
    chunks rather than by raw 'path/to/foo'.

    Test Cases should inherit from this and override ``get_bisect_path`` return
    their implementation, and ``get_bisect`` to return the matching
    bisect.bisect_* function.
    """

    def get_bisect_path(self):
        """Return an implementation of _bisect_path_*."""
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
        self.assertEqual(
            bisect_split_idx,
            bisect_path_idx,
            "{} disagreed. {} != {} for key {!r}".format(
                bisect_path.__name__, bisect_split_idx, bisect_path_idx, path
            ),
        )
        if exists:
            self.assertEqual(path, paths[bisect_path_idx + offset])

    def split_for_dirblocks(self, paths):
        dir_split_paths = []
        for path in paths:
            dirname, basename = os.path.split(path)
            dir_split_paths.append((dirname.split(b"/"), basename))
        dir_split_paths.sort()
        return dir_split_paths

    def test_simple(self):
        """In the simple case it works just like bisect_left."""
        paths = [b"", b"a", b"b", b"c", b"d"]
        split_paths = self.split_for_dirblocks(paths)
        for path in paths:
            self.assertBisect(paths, split_paths, path, exists=True)
        self.assertBisect(paths, split_paths, b"_", exists=False)
        self.assertBisect(paths, split_paths, b"aa", exists=False)
        self.assertBisect(paths, split_paths, b"bb", exists=False)
        self.assertBisect(paths, split_paths, b"cc", exists=False)
        self.assertBisect(paths, split_paths, b"dd", exists=False)
        self.assertBisect(paths, split_paths, b"a/a", exists=False)
        self.assertBisect(paths, split_paths, b"b/b", exists=False)
        self.assertBisect(paths, split_paths, b"c/c", exists=False)
        self.assertBisect(paths, split_paths, b"d/d", exists=False)

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
        paths = [  # content of '/'
            b"",
            b"a",
            b"a-a",
            b"a-z",
            b"a=a",
            b"a=z",
            # content of 'a/'
            b"a/a",
            b"a/a-a",
            b"a/a-z",
            b"a/a=a",
            b"a/a=z",
            b"a/z",
            b"a/z-a",
            b"a/z-z",
            b"a/z=a",
            b"a/z=z",
            # content of 'a/a/'
            b"a/a/a",
            b"a/a/z",
            # content of 'a/a-a'
            b"a/a-a/a",
            # content of 'a/a-z'
            b"a/a-z/z",
            # content of 'a/a=a'
            b"a/a=a/a",
            # content of 'a/a=z'
            b"a/a=z/z",
            # content of 'a/z/'
            b"a/z/a",
            b"a/z/z",
            # content of 'a-a'
            b"a-a/a",
            # content of 'a-z'
            b"a-z/z",
            # content of 'a=a'
            b"a=a/a",
            # content of 'a=z'
            b"a=z/z",
        ]
        split_paths = self.split_for_dirblocks(paths)
        sorted_paths = []
        for dir_parts, basename in split_paths:
            if dir_parts == [b""]:
                sorted_paths.append(basename)
            else:
                sorted_paths.append(b"/".join(dir_parts + [basename]))

        self.assertEqual(sorted_paths, paths)

        for path in paths:
            self.assertBisect(paths, split_paths, path, exists=True)


class TestBisectPathLeft(tests.TestCase, TestBisectPathMixin):
    """Run all Bisect Path tests against bisect_path_left."""

    def get_bisect_path(self):
        from ..dirstate import bisect_path_left

        return bisect_path_left

    def get_bisect(self):
        return bisect.bisect_left, 0


class TestBisectPathRight(tests.TestCase, TestBisectPathMixin):
    """Run all Bisect Path tests against bisect_path_right."""

    def get_bisect_path(self):
        from ..dirstate import bisect_path_right

        return bisect_path_right

    def get_bisect(self):
        return bisect.bisect_right, -1


class TestLtByDirs(tests.TestCase):
    """Test an implementation of lt_by_dirs().

    lt_by_dirs() compares 2 paths by their directory sections, rather than as
    plain strings.
    """

    def assertCmpByDirs(self, expected, str1, str2):
        """Compare the two strings, in both directions.

        :param expected: The expected comparison value. -1 means str1 comes
            first, 0 means they are equal, 1 means str2 comes first
        :param str1: string to compare
        :param str2: string to compare
        """
        if expected == 0:
            self.assertEqual(str1, str2)
            self.assertFalse(dirstate.lt_by_dirs(str1, str2))
            self.assertFalse(dirstate.lt_by_dirs(str2, str1))
        elif expected > 0:
            self.assertFalse(dirstate.lt_by_dirs(str1, str2))
            self.assertTrue(dirstate.lt_by_dirs(str2, str1))
        else:
            self.assertTrue(dirstate.lt_by_dirs(str1, str2))
            self.assertFalse(dirstate.lt_by_dirs(str2, str1))

    def test_cmp_empty(self):
        """Compare against the empty string."""
        self.assertCmpByDirs(0, b"", b"")
        self.assertCmpByDirs(1, b"a", b"")
        self.assertCmpByDirs(1, b"ab", b"")
        self.assertCmpByDirs(1, b"abc", b"")
        self.assertCmpByDirs(1, b"abcd", b"")
        self.assertCmpByDirs(1, b"abcde", b"")
        self.assertCmpByDirs(1, b"abcdef", b"")
        self.assertCmpByDirs(1, b"abcdefg", b"")
        self.assertCmpByDirs(1, b"abcdefgh", b"")
        self.assertCmpByDirs(1, b"abcdefghi", b"")
        self.assertCmpByDirs(1, b"test/ing/a/path/", b"")

    def test_cmp_same_str(self):
        """Compare the same string."""
        self.assertCmpByDirs(0, b"a", b"a")
        self.assertCmpByDirs(0, b"ab", b"ab")
        self.assertCmpByDirs(0, b"abc", b"abc")
        self.assertCmpByDirs(0, b"abcd", b"abcd")
        self.assertCmpByDirs(0, b"abcde", b"abcde")
        self.assertCmpByDirs(0, b"abcdef", b"abcdef")
        self.assertCmpByDirs(0, b"abcdefg", b"abcdefg")
        self.assertCmpByDirs(0, b"abcdefgh", b"abcdefgh")
        self.assertCmpByDirs(0, b"abcdefghi", b"abcdefghi")
        self.assertCmpByDirs(0, b"testing a long string", b"testing a long string")
        self.assertCmpByDirs(0, b"x" * 10000, b"x" * 10000)
        self.assertCmpByDirs(0, b"a/b", b"a/b")
        self.assertCmpByDirs(0, b"a/b/c", b"a/b/c")
        self.assertCmpByDirs(0, b"a/b/c/d", b"a/b/c/d")
        self.assertCmpByDirs(0, b"a/b/c/d/e", b"a/b/c/d/e")

    def test_simple_paths(self):
        """Compare strings that act like normal string comparison."""
        self.assertCmpByDirs(-1, b"a", b"b")
        self.assertCmpByDirs(-1, b"aa", b"ab")
        self.assertCmpByDirs(-1, b"ab", b"bb")
        self.assertCmpByDirs(-1, b"aaa", b"aab")
        self.assertCmpByDirs(-1, b"aab", b"abb")
        self.assertCmpByDirs(-1, b"abb", b"bbb")
        self.assertCmpByDirs(-1, b"aaaa", b"aaab")
        self.assertCmpByDirs(-1, b"aaab", b"aabb")
        self.assertCmpByDirs(-1, b"aabb", b"abbb")
        self.assertCmpByDirs(-1, b"abbb", b"bbbb")
        self.assertCmpByDirs(-1, b"aaaaa", b"aaaab")
        self.assertCmpByDirs(-1, b"a/a", b"a/b")
        self.assertCmpByDirs(-1, b"a/b", b"b/b")
        self.assertCmpByDirs(-1, b"a/a/a", b"a/a/b")
        self.assertCmpByDirs(-1, b"a/a/b", b"a/b/b")
        self.assertCmpByDirs(-1, b"a/b/b", b"b/b/b")
        self.assertCmpByDirs(-1, b"a/a/a/a", b"a/a/a/b")
        self.assertCmpByDirs(-1, b"a/a/a/b", b"a/a/b/b")
        self.assertCmpByDirs(-1, b"a/a/b/b", b"a/b/b/b")
        self.assertCmpByDirs(-1, b"a/b/b/b", b"b/b/b/b")
        self.assertCmpByDirs(-1, b"a/a/a/a/a", b"a/a/a/a/b")

    def test_tricky_paths(self):
        self.assertCmpByDirs(1, b"ab/cd/ef", b"ab/cc/ef")
        self.assertCmpByDirs(1, b"ab/cd/ef", b"ab/c/ef")
        self.assertCmpByDirs(-1, b"ab/cd/ef", b"ab/cd-ef")
        self.assertCmpByDirs(-1, b"ab/cd", b"ab/cd-")
        self.assertCmpByDirs(-1, b"ab/cd", b"ab-cd")

    def test_cmp_non_ascii(self):
        self.assertCmpByDirs(-1, b"\xc2\xb5", b"\xc3\xa5")  # u'\xb5', u'\xe5'
        self.assertCmpByDirs(-1, b"a", b"\xc3\xa5")  # u'a', u'\xe5'
        self.assertCmpByDirs(-1, b"b", b"\xc2\xb5")  # u'b', u'\xb5'
        self.assertCmpByDirs(-1, b"a/b", b"a/\xc3\xa5")  # u'a/b', u'a/\xe5'
        self.assertCmpByDirs(-1, b"b/a", b"b/\xc2\xb5")  # u'b/a', u'b/\xb5'


class TestLtPathByDirblock(tests.TestCase):
    """Test an implementation of lt_path_by_dirblock().

    lt_path_by_dirblock() compares two paths using the sort order used by
    DirState. All paths in the same directory are sorted together.

    Child test cases can override ``get_lt_path_by_dirblock`` to test a specific
    implementation.
    """

    def get_lt_path_by_dirblock(self):
        """Get a specific implementation of lt_path_by_dirblock."""
        from ..dirstate import lt_path_by_dirblock

        return lt_path_by_dirblock

    def assertLtPathByDirblock(self, paths):
        """Compare all paths and make sure they evaluate to the correct order.

        This does N^2 comparisons. It is assumed that ``paths`` is properly
        sorted list.

        :param paths: a sorted list of paths to compare
        """

        # First, make sure the paths being passed in are correct
        def _key(p):
            dirname, basename = os.path.split(p)
            return dirname.split(b"/"), basename

        self.assertEqual(sorted(paths, key=_key), paths)

        lt_path_by_dirblock = self.get_lt_path_by_dirblock()
        for idx1, path1 in enumerate(paths):
            for idx2, path2 in enumerate(paths):
                lt_result = lt_path_by_dirblock(path1, path2)
                self.assertEqual(
                    idx1 < idx2,
                    lt_result,
                    "{} did not state that {!r} < {!r}, lt={}".format(
                        lt_path_by_dirblock.__name__, path1, path2, lt_result
                    ),
                )

    def test_cmp_simple_paths(self):
        """Compare against the empty string."""
        self.assertLtPathByDirblock([b"", b"a", b"ab", b"abc", b"a/b/c", b"b/d/e"])
        self.assertLtPathByDirblock([b"kl", b"ab/cd", b"ab/ef", b"gh/ij"])

    def test_tricky_paths(self):
        self.assertLtPathByDirblock(
            [
                # Contents of ''
                b"",
                b"a",
                b"a-a",
                b"a=a",
                b"b",
                # Contents of 'a'
                b"a/a",
                b"a/a-a",
                b"a/a=a",
                b"a/b",
                # Contents of 'a/a'
                b"a/a/a",
                b"a/a/a-a",
                b"a/a/a=a",
                # Contents of 'a/a/a'
                b"a/a/a/a",
                b"a/a/a/b",
                # Contents of 'a/a/a-a',
                b"a/a/a-a/a",
                b"a/a/a-a/b",
                # Contents of 'a/a/a=a',
                b"a/a/a=a/a",
                b"a/a/a=a/b",
                # Contents of 'a/a-a'
                b"a/a-a/a",
                # Contents of 'a/a-a/a'
                b"a/a-a/a/a",
                b"a/a-a/a/b",
                # Contents of 'a/a=a'
                b"a/a=a/a",
                # Contents of 'a/b'
                b"a/b/a",
                b"a/b/b",
                # Contents of 'a-a',
                b"a-a/a",
                b"a-a/b",
                # Contents of 'a=a',
                b"a=a/a",
                b"a=a/b",
                # Contents of 'b',
                b"b/a",
                b"b/b",
            ]
        )
        self.assertLtPathByDirblock(
            [
                # content of '/'
                b"",
                b"a",
                b"a-a",
                b"a-z",
                b"a=a",
                b"a=z",
                # content of 'a/'
                b"a/a",
                b"a/a-a",
                b"a/a-z",
                b"a/a=a",
                b"a/a=z",
                b"a/z",
                b"a/z-a",
                b"a/z-z",
                b"a/z=a",
                b"a/z=z",
                # content of 'a/a/'
                b"a/a/a",
                b"a/a/z",
                # content of 'a/a-a'
                b"a/a-a/a",
                # content of 'a/a-z'
                b"a/a-z/z",
                # content of 'a/a=a'
                b"a/a=a/a",
                # content of 'a/a=z'
                b"a/a=z/z",
                # content of 'a/z/'
                b"a/z/a",
                b"a/z/z",
                # content of 'a-a'
                b"a-a/a",
                # content of 'a-z'
                b"a-z/z",
                # content of 'a=a'
                b"a=a/a",
                # content of 'a=z'
                b"a=z/z",
            ]
        )

    def test_nonascii(self):
        self.assertLtPathByDirblock(
            [
                # content of '/'
                b"",
                b"a",
                b"\xc2\xb5",
                b"\xc3\xa5",
                # content of 'a'
                b"a/a",
                b"a/\xc2\xb5",
                b"a/\xc3\xa5",
                # content of 'a/a'
                b"a/a/a",
                b"a/a/\xc2\xb5",
                b"a/a/\xc3\xa5",
                # content of 'a/\xc2\xb5'
                b"a/\xc2\xb5/a",
                b"a/\xc2\xb5/\xc2\xb5",
                b"a/\xc2\xb5/\xc3\xa5",
                # content of 'a/\xc3\xa5'
                b"a/\xc3\xa5/a",
                b"a/\xc3\xa5/\xc2\xb5",
                b"a/\xc3\xa5/\xc3\xa5",
                # content of '\xc2\xb5'
                b"\xc2\xb5/a",
                b"\xc2\xb5/\xc2\xb5",
                b"\xc2\xb5/\xc3\xa5",
                # content of '\xc2\xe5'
                b"\xc3\xa5/a",
                b"\xc3\xa5/\xc2\xb5",
                b"\xc3\xa5/\xc3\xa5",
            ]
        )


class TestReadDirblocks(test_dirstate.TestCaseWithDirState):
    """Test an implementation of _read_dirblocks().

    _read_dirblocks() reads in all of the dirblock information from the disk
    file.

    Child test cases can override ``get_read_dirblocks`` to test a specific
    implementation.
    """

    # inherits scenarios from test_dirstate

    def get_read_dirblocks(self):
        from .._dirstate_helpers_py import _read_dirblocks

        return _read_dirblocks

    def test_smoketest(self):
        """Make sure that we can create and read back a simple file."""
        tree, state, expected = self.create_basic_dirstate()
        del tree
        state._read_header_if_needed()
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY, state._dirblock_state)
        read_dirblocks = self.get_read_dirblocks()
        read_dirblocks(state)
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

    def test_trailing_garbage(self):
        tree, state, expected = self.create_basic_dirstate()
        # On Unix, we can write extra data as long as we haven't read yet, but
        # on Win32, if you've opened the file with FILE_SHARE_READ, trying to
        # open it in append mode will fail.
        state.unlock()
        f = open("dirstate", "ab")
        try:
            # Add bogus trailing garbage
            f.write(b"bogus\n")
        finally:
            f.close()
            state.lock_read()
        e = self.assertRaises(dirstate.DirstateCorrupt, state._read_dirblocks_if_needed)
        # Make sure we mention the bogus characters in the error
        self.assertContainsRe(str(e), "bogus")


class TestCompiledReadDirblocks(TestReadDirblocks):
    """Test the pyrex implementation of _read_dirblocks."""

    _test_needs_features = [compiled_dirstate_helpers_feature]

    def get_read_dirblocks(self):
        from .._dirstate_helpers_pyx import _read_dirblocks

        return _read_dirblocks


class TestUsingCompiledIfAvailable(tests.TestCase):
    """Check that any compiled functions that are available are the default.

    It is possible to have typos, etc in the import line, such that
    _dirstate_helpers_pyx is actually available, but the compiled functions are
    not being used.
    """

    def test__read_dirblocks(self):
        if compiled_dirstate_helpers_feature.available():
            from .._dirstate_helpers_pyx import _read_dirblocks
        else:
            from .._dirstate_helpers_py import _read_dirblocks
        self.assertIs(_read_dirblocks, dirstate._read_dirblocks)

    def test_update_entry(self):
        if compiled_dirstate_helpers_feature.available():
            from .._dirstate_helpers_pyx import update_entry
        else:
            from ..dirstate import update_entry
        self.assertIs(update_entry, dirstate.update_entry)

    def test_process_entry(self):
        if compiled_dirstate_helpers_feature.available():
            from .._dirstate_helpers_pyx import ProcessEntryC

            self.assertIs(ProcessEntryC, dirstate._process_entry)
        else:
            from ..dirstate import ProcessEntryPython

            self.assertIs(ProcessEntryPython, dirstate._process_entry)


class TestUpdateEntry(test_dirstate.TestCaseWithDirState):
    """Test the DirState.update_entry functions."""

    scenarios = multiply_scenarios(dir_reader_scenarios(), ue_scenarios)

    # Set by load_tests
    update_entry = None

    def setUp(self):
        super().setUp()
        self.overrideAttr(dirstate, "update_entry", self.update_entry)

    def get_state_with_a(self):
        """Create a DirState tracking a single object named 'a'."""
        state = test_dirstate.InstrumentedDirState.initialize("dirstate")
        self.addCleanup(state.unlock)
        state.add("a", b"a-id", "file", None, b"")
        entry = state._get_entry(0, path_utf8=b"a")
        return state, entry

    def test_observed_sha1_cachable(self):
        state, entry = self.get_state_with_a()
        state.save()
        atime = time.time() - 10
        self.build_tree(["a"])
        statvalue = test_dirstate._FakeStat.from_stat(os.lstat("a"))
        statvalue.st_mtime = statvalue.st_ctime = atime
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        state._observed_sha1(entry, b"foo", statvalue)
        self.assertEqual(b"foo", entry[1][0][1])
        packed_stat = dirstate.pack_stat(statvalue)
        self.assertEqual(packed_stat, entry[1][0][4])
        self.assertEqual(
            dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
        )

    def test_observed_sha1_not_cachable(self):
        state, entry = self.get_state_with_a()
        state.save()
        oldval = entry[1][0][1]
        oldstat = entry[1][0][4]
        self.build_tree(["a"])
        statvalue = os.lstat("a")
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        state._observed_sha1(entry, "foo", statvalue)
        self.assertEqual(oldval, entry[1][0][1])
        self.assertEqual(oldstat, entry[1][0][4])
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

    def test_update_entry(self):
        state, _ = self.get_state_with_a()
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        empty_revid = tree.commit("empty")
        self.build_tree(["tree/a"])
        tree.add(["a"], ids=[b"a-id"])
        with_a_id = tree.commit("with_a")
        self.addCleanup(tree.unlock)
        state.set_parent_trees(
            [(empty_revid, tree.branch.repository.revision_tree(empty_revid))], []
        )
        entry = state._get_entry(0, path_utf8=b"a")
        self.build_tree(["a"])
        # Add one where we don't provide the stat or sha already
        self.assertEqual((b"", b"a", b"a-id"), entry[0])
        self.assertEqual((b"f", b"", 0, False, dirstate.DirState.NULLSTAT), entry[1][0])
        # Flush the buffers to disk
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

        stat_value = os.lstat("a")
        packed_stat = dirstate.pack_stat(stat_value)
        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(None, link_or_sha1)

        # The dirblock entry should not have computed or cached the file's
        # sha1, but it did update the files' st_size. However, this is not
        # worth writing a dirstate file for, so we leave the state UNMODIFIED
        self.assertEqual(
            (b"f", b"", 14, False, dirstate.DirState.NULLSTAT), entry[1][0]
        )
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        mode = stat_value.st_mode
        self.assertEqual([("is_exec", mode, False)], state._log)

        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

        # Roll the clock back so the file is guaranteed to look too new. We
        # should still not compute the sha1.
        state.adjust_time(-10)
        del state._log[:]

        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual([("is_exec", mode, False)], state._log)
        self.assertEqual(None, link_or_sha1)
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        self.assertEqual(
            (b"f", b"", 14, False, dirstate.DirState.NULLSTAT), entry[1][0]
        )
        state.save()

        # If it is cachable (the clock has moved forward) but new it still
        # won't calculate the sha or cache it.
        state.adjust_time(+20)
        del state._log[:]
        link_or_sha1 = dirstate.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(None, link_or_sha1)
        self.assertEqual([("is_exec", mode, False)], state._log)
        self.assertEqual(
            (b"f", b"", 14, False, dirstate.DirState.NULLSTAT), entry[1][0]
        )
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

        # If the file is no longer new, and the clock has been moved forward
        # sufficiently, it will cache the sha.
        del state._log[:]
        state.set_parent_trees(
            [(with_a_id, tree.branch.repository.revision_tree(with_a_id))], []
        )
        entry = state._get_entry(0, path_utf8=b"a")

        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(b"b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6", link_or_sha1)
        self.assertEqual([("is_exec", mode, False), ("sha1", b"a")], state._log)
        self.assertEqual((b"f", link_or_sha1, 14, False, packed_stat), entry[1][0])

        # Subsequent calls will just return the cached value
        del state._log[:]
        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(b"b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6", link_or_sha1)
        self.assertEqual([], state._log)
        self.assertEqual((b"f", link_or_sha1, 14, False, packed_stat), entry[1][0])

    def test_update_entry_symlink(self):
        """Update entry should read symlinks."""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        state, entry = self.get_state_with_a()
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        os.symlink("target", "a")

        state.adjust_time(-10)  # Make the symlink look new
        stat_value = os.lstat("a")
        packed_stat = dirstate.pack_stat(stat_value)
        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(b"target", link_or_sha1)
        self.assertEqual([("read_link", b"a", b"")], state._log)
        # Dirblock is not updated (the link is too new)
        self.assertEqual([(b"l", b"", 6, False, dirstate.DirState.NULLSTAT)], entry[1])
        # The file entry turned into a symlink, that is considered
        # HASH modified worthy.
        self.assertEqual(
            dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
        )

        # Because the stat_value looks new, we should re-read the target
        del state._log[:]
        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(b"target", link_or_sha1)
        self.assertEqual([("read_link", b"a", b"")], state._log)
        self.assertEqual([(b"l", b"", 6, False, dirstate.DirState.NULLSTAT)], entry[1])
        state.save()
        state.adjust_time(+20)  # Skip into the future, all files look old
        del state._log[:]
        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        # The symlink stayed a symlink. So while it is new enough to cache, we
        # don't bother setting the flag, because it is not really worth saving
        # (when we stat the symlink, we'll have paged in the target.)
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        self.assertEqual(b"target", link_or_sha1)
        # We need to re-read the link because only now can we cache it
        self.assertEqual([("read_link", b"a", b"")], state._log)
        self.assertEqual([(b"l", b"target", 6, False, packed_stat)], entry[1])

        del state._log[:]
        # Another call won't re-read the link
        self.assertEqual([], state._log)
        link_or_sha1 = self.update_entry(
            state, entry, abspath=b"a", stat_value=stat_value
        )
        self.assertEqual(b"target", link_or_sha1)
        self.assertEqual([(b"l", b"target", 6, False, packed_stat)], entry[1])

    def do_update_entry(self, state, entry, abspath):
        stat_value = os.lstat(abspath)
        return self.update_entry(state, entry, abspath, stat_value)

    def test_update_entry_dir(self):
        state, entry = self.get_state_with_a()
        self.build_tree(["a/"])
        self.assertIs(None, self.do_update_entry(state, entry, b"a"))

    def test_update_entry_dir_unchanged(self):
        state, entry = self.get_state_with_a()
        self.build_tree(["a/"])
        state.adjust_time(+20)
        self.assertIs(None, self.do_update_entry(state, entry, b"a"))
        # a/ used to be a file, but is now a directory, worth saving
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED, state._dirblock_state)
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        # No changes to a/ means not worth saving.
        self.assertIs(None, self.do_update_entry(state, entry, b"a"))
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        # Change the last-modified time for the directory
        t = time.time() - 100.0
        try:
            os.utime("a", (t, t))
        except OSError as e:
            # It looks like Win32 + FAT doesn't allow to change times on a dir.
            raise tests.TestSkipped("can't update mtime of a dir on FAT") from e
        saved_packed_stat = entry[1][0][-1]
        self.assertIs(None, self.do_update_entry(state, entry, b"a"))
        # We *do* go ahead and update the information in the dirblocks, but we
        # don't bother setting IN_MEMORY_MODIFIED because it is trivial to
        # recompute.
        self.assertNotEqual(saved_packed_stat, entry[1][0][-1])
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

    def test_update_entry_file_unchanged(self):
        state, _ = self.get_state_with_a()
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.build_tree(["tree/a"])
        tree.add(["a"], ids=[b"a-id"])
        with_a_id = tree.commit("witha")
        self.addCleanup(tree.unlock)
        state.set_parent_trees(
            [(with_a_id, tree.branch.repository.revision_tree(with_a_id))], []
        )
        entry = state._get_entry(0, path_utf8=b"a")
        self.build_tree(["a"])
        sha1sum = b"b50e5406bb5e153ebbeb20268fcf37c87e1ecfb6"
        state.adjust_time(+20)
        self.assertEqual(sha1sum, self.do_update_entry(state, entry, b"a"))
        self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED, state._dirblock_state)
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        self.assertEqual(sha1sum, self.do_update_entry(state, entry, b"a"))
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)

    def test_update_entry_tree_reference(self):
        state = test_dirstate.InstrumentedDirState.initialize("dirstate")
        self.addCleanup(state.unlock)
        state.add("r", b"r-id", "tree-reference", None, b"")
        self.build_tree(["r/"])
        entry = state._get_entry(0, path_utf8=b"r")
        self.do_update_entry(state, entry, "r")
        entry = state._get_entry(0, path_utf8=b"r")
        self.assertEqual(b"t", entry[1][0][0])

    def create_and_test_file(self, state, entry):
        """Create a file at 'a' and verify the state finds it during update.

        The state should already be versioning *something* at 'a'. This makes
        sure that state.update_entry recognizes it as a file.
        """
        self.build_tree(["a"])
        stat_value = os.lstat("a")
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath="a")
        self.assertEqual(None, link_or_sha1)
        self.assertEqual([(b"f", b"", 14, False, dirstate.DirState.NULLSTAT)], entry[1])
        return packed_stat

    def create_and_test_dir(self, state, entry):
        """Create a directory at 'a' and verify the state finds it.

        The state should already be versioning *something* at 'a'. This makes
        sure that state.update_entry recognizes it as a directory.
        """
        self.build_tree(["a/"])
        stat_value = os.lstat("a")
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath=b"a")
        self.assertIs(None, link_or_sha1)
        self.assertEqual([(b"d", b"", 0, False, packed_stat)], entry[1])

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
        os.symlink("path/to/foo", "a")

        stat_value = os.lstat("a")
        packed_stat = dirstate.pack_stat(stat_value)

        link_or_sha1 = self.do_update_entry(state, entry, abspath=b"a")
        self.assertEqual(b"path/to/foo", link_or_sha1)
        self.assertEqual([(b"l", b"path/to/foo", 11, False, packed_stat)], entry[1])
        return packed_stat

    def test_update_file_to_dir(self):
        """If a file changes to a directory we return None for the sha.
        We also update the inventory record.
        """
        state, entry = self.get_state_with_a()
        # The file sha1 won't be cached unless the file is old
        state.adjust_time(+10)
        self.create_and_test_file(state, entry)
        os.remove("a")
        self.create_and_test_dir(state, entry)

    def test_update_file_to_symlink(self):
        """File becomes a symlink."""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        state, entry = self.get_state_with_a()
        # The file sha1 won't be cached unless the file is old
        state.adjust_time(+10)
        self.create_and_test_file(state, entry)
        os.remove("a")
        self.create_and_test_symlink(state, entry)

    def test_update_dir_to_file(self):
        """Directory becoming a file updates the entry."""
        state, entry = self.get_state_with_a()
        # The file sha1 won't be cached unless the file is old
        state.adjust_time(+10)
        self.create_and_test_dir(state, entry)
        os.rmdir("a")
        self.create_and_test_file(state, entry)

    def test_update_dir_to_symlink(self):
        """Directory becomes a symlink."""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        state, entry = self.get_state_with_a()
        # The symlink target won't be cached if it isn't old
        state.adjust_time(+10)
        self.create_and_test_dir(state, entry)
        os.rmdir("a")
        self.create_and_test_symlink(state, entry)

    def test_update_symlink_to_file(self):
        """Symlink becomes a file."""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        state, entry = self.get_state_with_a()
        # The symlink and file info won't be cached unless old
        state.adjust_time(+10)
        self.create_and_test_symlink(state, entry)
        os.remove("a")
        self.create_and_test_file(state, entry)

    def test_update_symlink_to_dir(self):
        """Symlink becomes a directory."""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        state, entry = self.get_state_with_a()
        # The symlink target won't be cached if it isn't old
        state.adjust_time(+10)
        self.create_and_test_symlink(state, entry)
        os.remove("a")
        self.create_and_test_dir(state, entry)

    def test__is_executable_win32(self):
        state, entry = self.get_state_with_a()
        self.build_tree(["a"])

        # Make sure we are using the version of _is_executable that doesn't
        # check the filesystem mode.
        state._use_filesystem_for_exec = False

        # The file on disk is not executable, but we are marking it as though
        # it is. With _use_filesystem_for_exec disabled we ignore what is on
        # disk.
        entry[1][0] = (b"f", b"", 0, True, dirstate.DirState.NULLSTAT)

        stat_value = os.lstat("a")
        dirstate.pack_stat(stat_value)

        state.adjust_time(-10)  # Make sure everything is new
        self.update_entry(state, entry, abspath=b"a", stat_value=stat_value)

        # The row is updated, but the executable bit stays set.
        self.assertEqual([(b"f", b"", 14, True, dirstate.DirState.NULLSTAT)], entry[1])

        # Make the disk object look old enough to cache (but it won't cache the
        # sha as it is a new file).
        state.adjust_time(+20)
        self.update_entry(state, entry, abspath=b"a", stat_value=stat_value)
        self.assertEqual([(b"f", b"", 14, True, dirstate.DirState.NULLSTAT)], entry[1])

    def _prepare_tree(self):
        # Create a tree
        text = b"Hello World\n"
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/a file", text)])
        tree.add("a file", ids=b"a-file-id")
        # Note: dirstate does not sha prior to the first commit
        # so commit now in order for the test to work
        tree.commit("first")
        return tree, text

    def test_sha1provider_sha1_used(self):
        tree, text = self._prepare_tree()
        state = dirstate.DirState.from_tree(tree, "dirstate", UppercaseSHA1Provider())
        self.addCleanup(state.unlock)
        expected_sha = osutils.sha_string(text.upper() + b"foo")
        entry = state._get_entry(0, path_utf8=b"a file")
        self.assertNotEqual((None, None), entry)
        state._sha_cutoff_time()
        state._cutoff_time += 10
        sha1 = self.update_entry(state, entry, "tree/a file", os.lstat("tree/a file"))
        self.assertEqual(expected_sha, sha1)

    def test_sha1provider_stat_and_sha1_used(self):
        tree, text = self._prepare_tree()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        state = tree._current_dirstate()
        state._sha1_provider = UppercaseSHA1Provider()
        # If we used the standard provider, it would look like nothing has
        # changed
        file_ids_changed = [
            change.file_id for change in tree.iter_changes(tree.basis_tree())
        ]
        self.assertEqual([b"a-file-id"], file_ids_changed)


class UppercaseSHA1Provider(dirstate.SHA1Provider):
    """A custom SHA1Provider."""

    def sha1(self, abspath):
        return self.stat_and_sha1(abspath)[1]

    def stat_and_sha1(self, abspath):
        with open(abspath, "rb") as file_obj:
            statvalue = os.fstat(file_obj.fileno())
            text = b"".join(file_obj.readlines())
            sha1 = osutils.sha_string(text.upper() + b"foo")
        return statvalue, sha1


class TestProcessEntry(test_dirstate.TestCaseWithDirState):
    scenarios = multiply_scenarios(dir_reader_scenarios(), pe_scenarios)

    # Set by load_tests
    _process_entry = None

    def setUp(self):
        super().setUp()
        self.overrideAttr(dirstate, "_process_entry", self._process_entry)

    def assertChangedFileIds(self, expected, tree):
        with tree.lock_read():
            file_ids = [info.file_id for info in tree.iter_changes(tree.basis_tree())]
        self.assertEqual(sorted(expected), sorted(file_ids))

    def test_exceptions_raised(self):
        # This is a direct test of bug #495023, it relies on osutils.is_inside
        # getting called in an inner function. Which makes it a bit brittle,
        # but at least it does reproduce the bug.
        tree = self.make_branch_and_tree("tree")
        self.build_tree(
            ["tree/file", "tree/dir/", "tree/dir/sub", "tree/dir2/", "tree/dir2/sub2"]
        )
        tree.add(["file", "dir", "dir/sub", "dir2", "dir2/sub2"])
        tree.commit("first commit")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis_tree = tree.basis_tree()

        def is_inside_raises(*args, **kwargs):
            raise RuntimeError("stop this")

        self.overrideAttr(dirstate, "is_inside", is_inside_raises)
        try:
            from .. import _dirstate_helpers_pyx
        except ModuleNotFoundError:
            pass
        else:
            self.overrideAttr(_dirstate_helpers_pyx, "is_inside", is_inside_raises)
        self.overrideAttr(osutils, "is_inside", is_inside_raises)
        self.assertListRaises(RuntimeError, tree.iter_changes, basis_tree)

    def test_simple_changes(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file"])
        tree.add(["file"], ids=[b"file-id"])
        self.assertChangedFileIds([tree.path2id(""), b"file-id"], tree)
        tree.commit("one")
        self.assertChangedFileIds([], tree)

    def test_sha1provider_stat_and_sha1_used(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file"])
        tree.add(["file"], ids=[b"file-id"])
        tree.commit("one")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        state = tree._current_dirstate()
        state._sha1_provider = UppercaseSHA1Provider()
        self.assertChangedFileIds([b"file-id"], tree)

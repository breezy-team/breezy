# Copyright (C) 2005-2016 Canonical Ltd
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

"""Tests for the osutils wrapper."""

import errno
import os
import socket
import sys
import tempfile
from io import BytesIO

from .. import errors, osutils, tests, trace, win32utils
from . import features, file_utils
from .scenarios import load_tests_apply_scenarios


class _UTF8DirReaderFeature(features.ModuleAvailableFeature):
    def _probe(self):
        try:
            from .. import _readdir_pyx

            self._module = _readdir_pyx
            self.reader = _readdir_pyx.UTF8DirReader
            return True
        except ImportError:
            return False


UTF8DirReaderFeature = _UTF8DirReaderFeature("breezy._readdir_pyx")

term_ios_feature = features.ModuleAvailableFeature("termios")


def _already_unicode(s):
    return s


def _utf8_to_unicode(s):
    return s.decode("UTF-8")


def dir_reader_scenarios():
    # For each dir reader we define:

    # - native_to_unicode: a function converting the native_abspath as returned
    #   by DirReader.read_dir to its unicode representation

    # UnicodeDirReader is the fallback, it should be tested on all platforms.
    scenarios = [
        (
            "unicode",
            {
                "_dir_reader_class": osutils.UnicodeDirReader,
                "_native_to_unicode": _already_unicode,
            },
        )
    ]
    # Some DirReaders are platform specific and even there they may not be
    # available.
    if UTF8DirReaderFeature.available():
        from .. import _readdir_pyx

        scenarios.append(
            (
                "utf8",
                {
                    "_dir_reader_class": _readdir_pyx.UTF8DirReader,
                    "_native_to_unicode": _utf8_to_unicode,
                },
            )
        )

    return scenarios


load_tests = load_tests_apply_scenarios


class TestContainsWhitespace(tests.TestCase):
    def test_contains_whitespace(self):
        self.assertTrue(osutils.contains_whitespace(" "))
        self.assertTrue(osutils.contains_whitespace("hello there"))
        self.assertTrue(osutils.contains_whitespace("hellothere\n"))
        self.assertTrue(osutils.contains_whitespace("hello\nthere"))
        self.assertTrue(osutils.contains_whitespace("hello\rthere"))
        self.assertTrue(osutils.contains_whitespace("hello\tthere"))

        # \xa0 is "Non-breaking-space" which on some python locales thinks it
        # is whitespace, but we do not.
        self.assertFalse(osutils.contains_whitespace(""))
        self.assertFalse(osutils.contains_whitespace("hellothere"))
        self.assertFalse(osutils.contains_whitespace("hello\xa0there"))


class TestRename(tests.TestCaseInTempDir):
    def create_file(self, filename, content):
        f = open(filename, "wb")
        try:
            f.write(content)
        finally:
            f.close()

    def _fancy_rename(self, a, b):
        osutils.fancy_rename(a, b, rename_func=os.rename, unlink_func=os.unlink)

    def test_fancy_rename(self):
        # This should work everywhere
        self.create_file("a", b"something in a\n")
        self._fancy_rename("a", "b")
        self.assertPathDoesNotExist("a")
        self.assertPathExists("b")
        self.check_file_contents("b", b"something in a\n")

        self.create_file("a", b"new something in a\n")
        self._fancy_rename("b", "a")

        self.check_file_contents("a", b"something in a\n")

    def test_fancy_rename_fails_source_missing(self):
        # An exception should be raised, and the target should be left in place
        self.create_file("target", b"data in target\n")
        self.assertRaises(
            (IOError, OSError), self._fancy_rename, "missingsource", "target"
        )
        self.assertPathExists("target")
        self.check_file_contents("target", b"data in target\n")

    def test_fancy_rename_fails_if_source_and_target_missing(self):
        self.assertRaises(
            (IOError, OSError), self._fancy_rename, "missingsource", "missingtarget"
        )

    def test_rename(self):
        # Rename should be semi-atomic on all platforms
        self.create_file("a", b"something in a\n")
        osutils.rename("a", "b")
        self.assertPathDoesNotExist("a")
        self.assertPathExists("b")
        self.check_file_contents("b", b"something in a\n")

        self.create_file("a", b"new something in a\n")
        osutils.rename("b", "a")

        self.check_file_contents("a", b"something in a\n")

    # TODO: test fancy_rename using a MemoryTransport

    def test_rename_change_case(self):
        # on Windows we should be able to change filename case by rename
        self.build_tree(["a", "b/"])
        osutils.rename("a", "A")
        osutils.rename("b", "B")
        # we can't use failUnlessExists on case-insensitive filesystem
        # so try to check shape of the tree
        shape = sorted(os.listdir("."))
        self.assertEqual(["A", "B"], shape)

    def test_rename_exception(self):
        try:
            osutils.rename("nonexistent_path", "different_nonexistent_path")
        except OSError as e:
            self.assertEqual(e.old_filename, "nonexistent_path")
            self.assertEqual(e.new_filename, "different_nonexistent_path")
            self.assertTrue("nonexistent_path" in e.strerror)
            self.assertTrue("different_nonexistent_path" in e.strerror)


class TestRandChars(tests.TestCase):
    def test_01_rand_chars_empty(self):
        result = osutils.rand_chars(0)
        self.assertEqual(result, "")

    def test_02_rand_chars_100(self):
        result = osutils.rand_chars(100)
        self.assertEqual(len(result), 100)
        self.assertEqual(type(result), str)
        self.assertContainsRe(result, r"^[a-z0-9]{100}$")


class TestIsInside(tests.TestCase):
    def test_is_inside(self):
        is_inside = osutils.is_inside
        self.assertTrue(is_inside("src", "src/foo.c"))
        self.assertFalse(is_inside("src", "srccontrol"))
        self.assertTrue(is_inside("src", "src/a/a/a/foo.c"))
        self.assertTrue(is_inside("foo.c", "foo.c"))
        self.assertFalse(is_inside("foo.c", ""))
        self.assertTrue(is_inside("", "foo.c"))

    def test_is_inside_any(self):
        SRC_FOO_C = osutils.pathjoin("src", "foo.c")
        for dirs, fn in [
            (["src", "doc"], SRC_FOO_C),
            (["src"], SRC_FOO_C),
            (["src"], "src"),
        ]:
            self.assertTrue(osutils.is_inside_any(dirs, fn))
        for dirs, fn in [(["src"], "srccontrol"), (["src"], "srccontrol/foo")]:
            self.assertFalse(osutils.is_inside_any(dirs, fn))

    def test_is_inside_or_parent_of_any(self):
        for dirs, fn in [
            (["src", "doc"], "src/foo.c"),
            (["src"], "src/foo.c"),
            (["src/bar.c"], "src"),
            (["src/bar.c", "bla/foo.c"], "src"),
            (["src"], "src"),
        ]:
            self.assertTrue(osutils.is_inside_or_parent_of_any(dirs, fn))

        for dirs, fn in [
            (["src"], "srccontrol"),
            (["srccontrol/foo.c"], "src"),
            (["src"], "srccontrol/foo"),
        ]:
            self.assertFalse(osutils.is_inside_or_parent_of_any(dirs, fn))


class TestLstat(tests.TestCaseInTempDir):
    def test_lstat_matches_fstat(self):
        # On Windows, lstat and fstat don't always agree, primarily in the
        # 'st_ino' and 'st_dev' fields. So we force them to be '0' in our
        # custom implementation.
        if sys.platform == "win32":
            self.skipTest("lstat and fstat do not match on Windows")
        with open("test-file.txt", "wb") as f:
            f.write(b"some content\n")
            f.flush()
            self.assertEqualStat(
                osutils.fstat(f.fileno()), osutils.lstat("test-file.txt")
            )


class TestRmTree(tests.TestCaseInTempDir):
    def test_rmtree(self):
        # Check to remove tree with read-only files/dirs
        os.mkdir("dir")
        with open("dir/file", "w") as f:
            f.write("spam")
        # would like to also try making the directory readonly, but at the
        # moment python shutil.rmtree doesn't handle that properly - it would
        # need to chmod the directory before removing things inside it - deferred
        # for now -- mbp 20060505
        # osutils.make_readonly('dir')
        osutils.make_readonly("dir/file")

        osutils.rmtree("dir")

        self.assertPathDoesNotExist("dir/file")
        self.assertPathDoesNotExist("dir")


class TestDeleteAny(tests.TestCaseInTempDir):
    def test_delete_any_readonly(self):
        # from <https://bugs.launchpad.net/bzr/+bug/218206>
        self.build_tree(["d/", "f"])
        osutils.make_readonly("d")
        osutils.make_readonly("f")

        osutils.delete_any("f")
        osutils.delete_any("d")


class TestKind(tests.TestCaseInTempDir):
    def test_file_kind(self):
        self.build_tree(["file", "dir/"])
        self.assertEqual("file", osutils.file_kind("file"))
        self.assertEqual("directory", osutils.file_kind("dir/"))
        if osutils.supports_symlinks(self.test_dir):
            os.symlink("symlink", "symlink")
            self.assertEqual("symlink", osutils.file_kind("symlink"))

        # TODO: jam 20060529 Test a block device
        try:
            os.lstat("/dev/null")
        except OSError as e:
            if e.errno not in (errno.ENOENT,):
                raise
        else:
            self.assertEqual(
                "chardev", osutils.file_kind(os.path.realpath("/dev/null"))
            )

        mkfifo = getattr(os, "mkfifo", None)
        if mkfifo:
            mkfifo("fifo")
            try:
                self.assertEqual("fifo", osutils.file_kind("fifo"))
            finally:
                os.remove("fifo")

        AF_UNIX = getattr(socket, "AF_UNIX", None)
        if AF_UNIX:
            s = socket.socket(AF_UNIX)
            s.bind("socket")
            try:
                self.assertEqual("socket", osutils.file_kind("socket"))
            finally:
                os.remove("socket")

    def test_kind_marker(self):
        self.assertEqual("", osutils.kind_marker("file"))
        self.assertEqual("/", osutils.kind_marker("directory"))
        self.assertEqual("/", osutils.kind_marker(osutils._directory_kind))
        self.assertEqual("@", osutils.kind_marker("symlink"))
        self.assertEqual("+", osutils.kind_marker("tree-reference"))
        self.assertEqual("", osutils.kind_marker("fifo"))
        self.assertEqual("", osutils.kind_marker("socket"))
        self.assertEqual("", osutils.kind_marker("unknown"))


class TestUmask(tests.TestCaseInTempDir):
    def test_get_umask(self):
        if sys.platform == "win32":
            # umask always returns '0', no way to set it
            self.assertEqual(0, osutils.get_umask())
            return

        orig_umask = osutils.get_umask()
        self.addCleanup(os.umask, orig_umask)
        os.umask(0o222)
        self.assertEqual(0o222, osutils.get_umask())
        os.umask(0o022)
        self.assertEqual(0o022, osutils.get_umask())
        os.umask(0o002)
        self.assertEqual(0o002, osutils.get_umask())
        os.umask(0o027)
        self.assertEqual(0o027, osutils.get_umask())


class TestDateTime(tests.TestCase):
    def assertFormatedDelta(self, expected, seconds):
        """Assert osutils.format_delta formats as expected."""
        actual = osutils.format_delta(seconds)
        self.assertEqual(expected, actual)

    def test_format_delta(self):
        self.assertFormatedDelta("0 seconds ago", 0)
        self.assertFormatedDelta("1 second ago", 1)
        self.assertFormatedDelta("10 seconds ago", 10)
        self.assertFormatedDelta("59 seconds ago", 59)
        self.assertFormatedDelta("89 seconds ago", 89)
        self.assertFormatedDelta("1 minute, 30 seconds ago", 90)
        self.assertFormatedDelta("3 minutes, 0 seconds ago", 180)
        self.assertFormatedDelta("3 minutes, 1 second ago", 181)
        self.assertFormatedDelta("10 minutes, 15 seconds ago", 615)
        self.assertFormatedDelta("30 minutes, 59 seconds ago", 1859)
        self.assertFormatedDelta("31 minutes, 0 seconds ago", 1860)
        self.assertFormatedDelta("60 minutes, 0 seconds ago", 3600)
        self.assertFormatedDelta("89 minutes, 59 seconds ago", 5399)
        self.assertFormatedDelta("1 hour, 30 minutes ago", 5400)
        self.assertFormatedDelta("2 hours, 30 minutes ago", 9017)
        self.assertFormatedDelta("10 hours, 0 minutes ago", 36000)
        self.assertFormatedDelta("24 hours, 0 minutes ago", 86400)
        self.assertFormatedDelta("35 hours, 59 minutes ago", 129599)
        self.assertFormatedDelta("36 hours, 0 minutes ago", 129600)
        self.assertFormatedDelta("36 hours, 0 minutes ago", 129601)
        self.assertFormatedDelta("36 hours, 1 minute ago", 129660)
        self.assertFormatedDelta("36 hours, 1 minute ago", 129661)
        self.assertFormatedDelta("84 hours, 10 minutes ago", 303002)

        # We handle when time steps the wrong direction because computers
        # don't have synchronized clocks.
        self.assertFormatedDelta("84 hours, 10 minutes in the future", -303002)
        self.assertFormatedDelta("1 second in the future", -1)
        self.assertFormatedDelta("2 seconds in the future", -2)

    def test_format_date(self):
        self.assertRaises(
            osutils.UnsupportedTimezoneFormat, osutils.format_date, 0, timezone="foo"
        )
        self.assertIsInstance(osutils.format_date(0), str)
        self.assertIsInstance(osutils.format_local_date(0), str)
        # Testing for the actual value of the local weekday without
        # duplicating the code from format_date is difficult.
        # Instead blackbox.test_locale should check for localized
        # dates once they do occur in output strings.

    def test_format_date_with_offset_in_original_timezone(self):
        self.assertEqual(
            "Thu 1970-01-01 00:00:00 +0000",
            osutils.format_date_with_offset_in_original_timezone(0),
        )
        self.assertEqual(
            "Fri 1970-01-02 03:46:40 +0000",
            osutils.format_date_with_offset_in_original_timezone(100000),
        )
        self.assertEqual(
            "Fri 1970-01-02 05:46:40 +0200",
            osutils.format_date_with_offset_in_original_timezone(100000, 7200),
        )

    def test_local_time_offset(self):
        """Test that local_time_offset() returns a sane value."""
        offset = osutils.local_time_offset()
        self.assertTrue(isinstance(offset, int))
        # Test that the offset is no more than a eighteen hours in
        # either direction.
        # Time zone handling is system specific, so it is difficult to
        # do more specific tests, but a value outside of this range is
        # probably wrong.
        eighteen_hours = 18 * 3600
        self.assertTrue(-eighteen_hours < offset < eighteen_hours)

    def test_local_time_offset_with_timestamp(self):
        """Test that local_time_offset() works with a timestamp."""
        offset = osutils.local_time_offset(1000000000.1234567)
        self.assertTrue(isinstance(offset, int))
        eighteen_hours = 18 * 3600
        self.assertTrue(-eighteen_hours < offset < eighteen_hours)


class TestFdatasync(tests.TestCaseInTempDir):
    def do_fdatasync(self):
        f = tempfile.NamedTemporaryFile()
        osutils.fdatasync(f.fileno())
        f.close()

    @staticmethod
    def raise_eopnotsupp(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, os.strerror(errno.EOPNOTSUPP))

    @staticmethod
    def raise_enotsup(*args, **kwargs):
        raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP))

    def test_fdatasync_handles_system_function(self):
        self.overrideAttr(os, "fdatasync")
        self.do_fdatasync()

    def test_fdatasync_handles_no_fdatasync_no_fsync(self):
        self.overrideAttr(os, "fdatasync")
        self.overrideAttr(os, "fsync")
        self.do_fdatasync()

    def test_fdatasync_handles_no_EOPNOTSUPP(self):
        self.overrideAttr(errno, "EOPNOTSUPP")
        self.do_fdatasync()

    def test_fdatasync_catches_ENOTSUP(self):
        enotsup = getattr(errno, "ENOTSUP", None)
        if enotsup is None:
            raise tests.TestNotApplicable("No ENOTSUP on this platform")
        self.overrideAttr(os, "fdatasync", self.raise_enotsup)
        self.do_fdatasync()

    def test_fdatasync_catches_EOPNOTSUPP(self):
        enotsup = getattr(errno, "EOPNOTSUPP", None)
        if enotsup is None:
            raise tests.TestNotApplicable("No EOPNOTSUPP on this platform")
        self.overrideAttr(os, "fdatasync", self.raise_eopnotsupp)
        self.do_fdatasync()


class TestLinks(tests.TestCaseInTempDir):
    def test_dereference_path(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        cwd = osutils.realpath(".")
        os.mkdir("bar")
        bar_path = osutils.pathjoin(cwd, "bar")
        # Using './' to avoid bug #1213894 (first path component not
        # dereferenced) in Python 2.4.1 and earlier
        self.assertEqual(bar_path, osutils.realpath("./bar"))
        os.symlink("bar", "foo")
        self.assertEqual(bar_path, osutils.realpath("./foo"))

        # Does not dereference terminal symlinks
        foo_path = osutils.pathjoin(cwd, "foo")
        self.assertEqual(foo_path, osutils.dereference_path("./foo"))

        # Dereferences parent symlinks
        os.mkdir("bar/baz")
        baz_path = osutils.pathjoin(bar_path, "baz")
        self.assertEqual(baz_path, osutils.dereference_path("./foo/baz"))

        # Dereferences parent symlinks that are the first path element
        self.assertEqual(baz_path, osutils.dereference_path("foo/baz"))

        # Dereferences parent symlinks in absolute paths
        foo_baz_path = osutils.pathjoin(foo_path, "baz")
        self.assertEqual(baz_path, osutils.dereference_path(foo_baz_path))

    def test_changing_access(self):
        with open("file", "w") as f:
            f.write("monkey")

        # Make a file readonly
        osutils.make_readonly("file")
        mode = os.lstat("file").st_mode
        self.assertEqual(mode, mode & 0o777555)

        # Make a file writable
        osutils.make_writable("file")
        mode = os.lstat("file").st_mode
        self.assertEqual(mode, mode | 0o200)

        if osutils.supports_symlinks(self.test_dir):
            # should not error when handed a symlink
            os.symlink("nonexistent", "dangling")
            osutils.make_readonly("dangling")
            osutils.make_writable("dangling")


class TestCanonicalRelPath(tests.TestCaseInTempDir):
    _test_needs_features = [features.CaseInsCasePresFilenameFeature]

    def test_canonical_relpath_simple(self):
        f = open("MixedCaseName", "w")
        f.close()
        actual = osutils.canonical_relpath(self.test_base_dir, "mixedcasename")
        self.assertEqual("work/MixedCaseName", actual)

    def test_canonical_relpath_missing_tail(self):
        os.mkdir("MixedCaseParent")
        actual = osutils.canonical_relpath(
            self.test_base_dir, "mixedcaseparent/nochild"
        )
        self.assertEqual("work/MixedCaseParent/nochild", actual)


class Test_CICPCanonicalRelpath(tests.TestCaseWithTransport):
    def assertRelpath(self, expected, base, path):
        actual = osutils._cicp_canonical_relpath(base, path)
        self.assertEqual(expected, actual)

    def test_simple(self):
        self.build_tree(["MixedCaseName"])
        base = osutils.realpath(self.get_transport(".").local_abspath("."))
        self.assertRelpath("MixedCaseName", base, "mixedcAsename")

    def test_subdir_missing_tail(self):
        self.build_tree(["MixedCaseParent/", "MixedCaseParent/a_child"])
        base = osutils.realpath(self.get_transport(".").local_abspath("."))
        self.assertRelpath("MixedCaseParent/a_child", base, "MixedCaseParent/a_child")
        self.assertRelpath("MixedCaseParent/a_child", base, "MixedCaseParent/A_Child")
        self.assertRelpath(
            "MixedCaseParent/not_child", base, "MixedCaseParent/not_child"
        )

    def test_at_root_slash(self):
        # We can't test this on Windows, because it has a 'MIN_ABS_PATHLENGTH'
        # check...
        if osutils.MIN_ABS_PATHLENGTH > 1:
            raise tests.TestSkipped(
                "relpath requires %d chars" % osutils.MIN_ABS_PATHLENGTH
            )
        self.assertRelpath("foo", "/", "/foo")

    def test_at_root_drive(self):
        if sys.platform != "win32":
            raise tests.TestNotApplicable(
                "we can only test drive-letter relative"
                " paths on Windows where we have drive"
                " letters."
            )
        # see bug #322807
        # The specific issue is that when at the root of a drive, 'abspath'
        # returns "C:/" or just "/". However, the code assumes that abspath
        # always returns something like "C:/foo" or "/foo" (no trailing slash).
        self.assertRelpath("foo", "C:/", "C:/foo")
        self.assertRelpath("foo", "X:/", "X:/foo")
        self.assertRelpath("foo", "X:/", "X://foo")


class TestPumpFile(tests.TestCase):
    """Test pumpfile method."""

    def setUp(self):
        super().setUp()
        # create a test datablock
        self.block_size = 512
        pattern = b"0123456789ABCDEF"
        self.test_data = pattern * (3 * self.block_size // len(pattern))
        self.test_data_len = len(self.test_data)

    def test_bracket_block_size(self):
        """Read data in blocks with the requested read size bracketing the
        block size.
        """
        # make sure test data is larger than max read size
        self.assertTrue(self.test_data_len > self.block_size)

        from_file = file_utils.FakeReadFile(self.test_data)
        to_file = BytesIO()

        # read (max // 2) bytes and verify read size wasn't affected
        num_bytes_to_read = self.block_size // 2
        osutils.pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)
        self.assertEqual(from_file.get_max_read_size(), num_bytes_to_read)
        self.assertEqual(from_file.get_read_count(), 1)

        # read (max) bytes and verify read size wasn't affected
        num_bytes_to_read = self.block_size
        from_file.reset_read_count()
        osutils.pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)
        self.assertEqual(from_file.get_max_read_size(), num_bytes_to_read)
        self.assertEqual(from_file.get_read_count(), 1)

        # read (max + 1) bytes and verify read size was limited
        num_bytes_to_read = self.block_size + 1
        from_file.reset_read_count()
        osutils.pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)
        self.assertEqual(from_file.get_max_read_size(), self.block_size)
        self.assertEqual(from_file.get_read_count(), 2)

        # finish reading the rest of the data
        num_bytes_to_read = self.test_data_len - to_file.tell()
        osutils.pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_specified_size(self):
        """Request a transfer larger than the maximum block size and verify
        that the maximum read doesn't exceed the block_size.
        """
        # make sure test data is larger than max read size
        self.assertTrue(self.test_data_len > self.block_size)

        # retrieve data in blocks
        from_file = file_utils.FakeReadFile(self.test_data)
        to_file = BytesIO()
        osutils.pumpfile(from_file, to_file, self.test_data_len, self.block_size)

        # verify read size was equal to the maximum read size
        self.assertTrue(from_file.get_max_read_size() > 0)
        self.assertEqual(from_file.get_max_read_size(), self.block_size)
        self.assertEqual(from_file.get_read_count(), 3)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_to_eof(self):
        """Read to end-of-file and verify that the reads are not larger than
        the maximum read size.
        """
        # make sure test data is larger than max read size
        self.assertTrue(self.test_data_len > self.block_size)

        # retrieve data to EOF
        from_file = file_utils.FakeReadFile(self.test_data)
        to_file = BytesIO()
        osutils.pumpfile(from_file, to_file, -1, self.block_size)

        # verify read size was equal to the maximum read size
        self.assertEqual(from_file.get_max_read_size(), self.block_size)
        self.assertEqual(from_file.get_read_count(), 4)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_defaults(self):
        """Verifies that the default arguments will read to EOF -- this
        test verifies that any existing usages of pumpfile will not be broken
        with this new version.
        """
        # retrieve data using default (old) pumpfile method
        from_file = file_utils.FakeReadFile(self.test_data)
        to_file = BytesIO()
        osutils.pumpfile(from_file, to_file)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_report_activity(self):
        activity = []

        def log_activity(length, direction):
            activity.append((length, direction))

        from_file = BytesIO(self.test_data)
        to_file = BytesIO()
        osutils.pumpfile(
            from_file,
            to_file,
            buff_size=500,
            report_activity=log_activity,
            direction="read",
        )
        self.assertEqual(
            [(500, "read"), (500, "read"), (500, "read"), (36, "read")], activity
        )

        from_file = BytesIO(self.test_data)
        to_file = BytesIO()
        del activity[:]
        osutils.pumpfile(
            from_file,
            to_file,
            buff_size=500,
            report_activity=log_activity,
            direction="write",
        )
        self.assertEqual(
            [(500, "write"), (500, "write"), (500, "write"), (36, "write")], activity
        )

        # And with a limited amount of data
        from_file = BytesIO(self.test_data)
        to_file = BytesIO()
        del activity[:]
        osutils.pumpfile(
            from_file,
            to_file,
            buff_size=500,
            read_length=1028,
            report_activity=log_activity,
            direction="read",
        )
        self.assertEqual([(500, "read"), (500, "read"), (28, "read")], activity)


class TestPumpStringFile(tests.TestCase):
    def test_empty(self):
        output = BytesIO()
        osutils.pump_string_file(b"", output)
        self.assertEqual(b"", output.getvalue())

    def test_more_than_segment_size(self):
        output = BytesIO()
        osutils.pump_string_file(b"123456789", output, 2)
        self.assertEqual(b"123456789", output.getvalue())

    def test_segment_size(self):
        output = BytesIO()
        osutils.pump_string_file(b"12", output, 2)
        self.assertEqual(b"12", output.getvalue())

    def test_segment_size_multiple(self):
        output = BytesIO()
        osutils.pump_string_file(b"1234", output, 2)
        self.assertEqual(b"1234", output.getvalue())


class TestRelpath(tests.TestCase):
    def test_simple_relpath(self):
        cwd = osutils.getcwd()
        subdir = cwd + "/subdir"
        self.assertEqual("subdir", osutils.relpath(cwd, subdir))

    def test_deep_relpath(self):
        cwd = osutils.getcwd()
        subdir = cwd + "/sub/subsubdir"
        self.assertEqual("sub/subsubdir", osutils.relpath(cwd, subdir))

    def test_not_relative(self):
        self.assertRaises(errors.PathNotChild, osutils.relpath, "C:/path", "H:/path")
        self.assertRaises(errors.PathNotChild, osutils.relpath, "C:/", "H:/path")


class TestSafeUnicode(tests.TestCase):
    def test_from_ascii_string(self):
        self.assertEqual("foobar", osutils.safe_unicode(b"foobar"))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual("bargam", osutils.safe_unicode("bargam"))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual("bargam\xae", osutils.safe_unicode("bargam\xae"))

    def test_from_utf8_string(self):
        self.assertEqual("foo\xae", osutils.safe_unicode(b"foo\xc2\xae"))

    def test_bad_utf8_string(self):
        self.assertRaises(
            errors.BzrBadParameterNotUnicode, osutils.safe_unicode, b"\xbb\xbb"
        )


class TestSafeUtf8(tests.TestCase):
    def test_from_ascii_string(self):
        f = b"foobar"
        self.assertEqual(b"foobar", osutils.safe_utf8(f))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual(b"bargam", osutils.safe_utf8("bargam"))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual(b"bargam\xc2\xae", osutils.safe_utf8("bargam\xae"))

    def test_from_utf8_string(self):
        self.assertEqual(b"foo\xc2\xae", osutils.safe_utf8(b"foo\xc2\xae"))

    def test_bad_utf8_string(self):
        self.assertRaises(
            errors.BzrBadParameterNotUnicode, osutils.safe_utf8, b"\xbb\xbb"
        )


class TestSendAll(tests.TestCase):
    def test_send_with_disconnected_socket(self):
        class DisconnectedSocket:
            def __init__(self, err):
                self.err = err

            def send(self, content):
                raise self.err

            def close(self):
                pass

        # All of these should be treated as ConnectionReset
        errs = []
        for err_cls in (IOError, socket.error):
            for errnum in osutils._end_of_stream_errors:
                errs.append(err_cls(errnum))
        for err in errs:
            sock = DisconnectedSocket(err)
            self.assertRaises(
                errors.ConnectionReset, osutils.send_all, sock, b"some more content"
            )

    def test_send_with_no_progress(self):
        # See https://bugs.launchpad.net/bzr/+bug/1047309
        # It seems that paramiko can get into a state where it doesn't error,
        # but it returns 0 bytes sent for requests over and over again.
        class NoSendingSocket:
            def __init__(self):
                self.call_count = 0

            def send(self, bytes):
                self.call_count += 1
                if self.call_count > 100:
                    # Prevent the test suite from hanging
                    raise RuntimeError("too many calls")
                return 0

        sock = NoSendingSocket()
        self.assertRaises(errors.ConnectionReset, osutils.send_all, sock, b"content")
        self.assertEqual(1, sock.call_count)


class TestPosixFuncs(tests.TestCase):
    """Test that the posix version of normpath returns an appropriate path
    when used with 2 leading slashes.
    """

    def test_normpath(self):
        self.assertEqual("/etc/shadow", osutils._posix_normpath("/etc/shadow"))
        self.assertEqual("/etc/shadow", osutils._posix_normpath("//etc/shadow"))
        self.assertEqual("/etc/shadow", osutils._posix_normpath("///etc/shadow"))


class TestWin32Funcs(tests.TestCase):
    """Test that _win32 versions of os utilities return appropriate paths."""

    def test_abspath(self):
        self.requireFeature(features.win32_feature)
        self.assertEqual("C:/foo", osutils._win32_abspath("C:\\foo"))
        self.assertEqual("C:/foo", osutils._win32_abspath("C:/foo"))
        self.assertEqual("//HOST/path", osutils._win32_abspath(r"\\HOST\path"))
        self.assertEqual("//HOST/path", osutils._win32_abspath("//HOST/path"))

    def test_realpath(self):
        self.assertEqual("C:/foo", osutils._win32_realpath("C:\\foo"))
        self.assertEqual("C:/foo", osutils._win32_realpath("C:/foo"))

    def test_pathjoin(self):
        self.assertEqual("path/to/foo", osutils._win32_pathjoin("path", "to", "foo"))
        self.assertEqual("C:/foo", osutils._win32_pathjoin("path\\to", "C:\\foo"))
        self.assertEqual("C:/foo", osutils._win32_pathjoin("path/to", "C:/foo"))
        self.assertEqual("path/to/foo", osutils._win32_pathjoin("path/to/", "foo"))

    def test_pathjoin_late_bugfix(self):
        expected = "C:/foo"
        self.assertEqual(expected, osutils._win32_pathjoin("C:/path/to/", "/foo"))
        self.assertEqual(expected, osutils._win32_pathjoin("C:\\path\\to\\", "\\foo"))

    def test_normpath(self):
        self.assertEqual(
            "path/to/foo", osutils._win32_normpath(r"path\\from\..\to\.\foo")
        )
        self.assertEqual(
            "path/to/foo", osutils._win32_normpath("path//from/../to/./foo")
        )

    def test_getcwd(self):
        cwd = osutils._win32_getcwd()
        os_cwd = os.getcwd()
        self.assertEqual(os_cwd[1:].replace("\\", "/"), cwd[1:])
        # win32 is inconsistent whether it returns lower or upper case
        # and even if it was consistent the user might type the other
        # so we force it to uppercase
        # running python.exe under cmd.exe return capital C:\\
        # running win32 python inside a cygwin shell returns lowercase
        self.assertEqual(os_cwd[0].upper(), cwd[0])

    def test_fixdrive(self):
        self.assertEqual("H:/foo", osutils._win32_fixdrive("h:/foo"))
        self.assertEqual("H:/foo", osutils._win32_fixdrive("H:/foo"))
        self.assertEqual("C:\\foo", osutils._win32_fixdrive("c:\\foo"))


class TestWin32FuncsDirs(tests.TestCaseInTempDir):
    """Test win32 functions that create files."""

    def test_getcwd(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        os.mkdir("mu-\xb5")
        os.chdir("mu-\xb5")
        # TODO: jam 20060427 This will probably fail on Mac OSX because
        #       it will change the normalization of B\xe5gfors
        #       Consider using a different unicode character, or make
        #       osutils.getcwd() renormalize the path.
        self.assertEndsWith(osutils._win32_getcwd(), "mu-\xb5")

    def test_minimum_path_selection(self):
        self.assertEqual(set(), osutils.minimum_path_selection([]))
        self.assertEqual({"a"}, osutils.minimum_path_selection(["a"]))
        self.assertEqual({"a", "b"}, osutils.minimum_path_selection(["a", "b"]))
        self.assertEqual({"a/", "b"}, osutils.minimum_path_selection(["a/", "b"]))
        self.assertEqual(
            {"a/", "b"}, osutils.minimum_path_selection(["a/c", "a/", "b"])
        )
        self.assertEqual(
            {"a-b", "a", "a0b"},
            osutils.minimum_path_selection(["a-b", "a/b", "a0b", "a"]),
        )

    def test_rename(self):
        with open("a", "wb") as a:
            a.write(b"foo\n")
        with open("b", "wb") as b:
            b.write(b"baz\n")

        osutils._win32_rename("b", "a")
        self.assertPathExists("a")
        self.assertPathDoesNotExist("b")
        self.assertFileEqual(b"baz\n", "a")

    def test_rename_missing_file(self):
        with open("a", "wb") as a:
            a.write(b"foo\n")

        try:
            osutils._win32_rename("b", "a")
        except OSError as e:
            self.assertEqual(errno.ENOENT, e.errno)
        self.assertFileEqual(b"foo\n", "a")

    def test_rename_missing_dir(self):
        os.mkdir("a")
        try:
            osutils._win32_rename("b", "a")
        except OSError as e:
            self.assertEqual(errno.ENOENT, e.errno)

    def test_rename_current_dir(self):
        os.mkdir("a")
        os.chdir("a")
        # You can't rename the working directory
        # doing rename non-existant . usually
        # just raises ENOENT, since non-existant
        # doesn't exist.
        try:
            osutils._win32_rename("b", ".")
        except OSError as e:
            self.assertEqual(errno.ENOENT, e.errno)

    def test_splitpath(self):
        def check(expected, path):
            self.assertEqual(expected, osutils.splitpath(path))

        check(["a"], "a")
        check(["a", "b"], "a/b")
        check(["a", "b"], "a/./b")
        check(["a", ".b"], "a/.b")
        if os.path.sep == "\\":
            check(["a", ".b"], "a\\.b")
        else:
            check(["a\\.b"], "a\\.b")

        self.assertRaises(errors.BzrError, osutils.splitpath, "a/../b")


class TestParentDirectories(tests.TestCaseInTempDir):
    """Test osutils.parent_directories()."""

    def test_parent_directories(self):
        self.assertEqual([], osutils.parent_directories("a"))
        self.assertEqual(["a"], osutils.parent_directories("a/b"))
        self.assertEqual(["a/b", "a"], osutils.parent_directories("a/b/c"))


class TestMacFuncsDirs(tests.TestCaseInTempDir):
    """Test mac special functions that require directories."""

    def test_getcwd(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        os.mkdir("B\xe5gfors")
        os.chdir("B\xe5gfors")
        self.assertEndsWith(osutils._mac_getcwd(), "B\xe5gfors")

    def test_getcwd_nonnorm(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        # Test that _mac_getcwd() will normalize this path
        os.mkdir("Ba\u030agfors")
        os.chdir("Ba\u030agfors")
        self.assertEndsWith(osutils._mac_getcwd(), "B\xe5gfors")


class TestChunksToLines(tests.TestCase):
    def test_smoketest(self):
        self.assertEqual(
            [b"foo\n", b"bar\n", b"baz\n"],
            osutils.chunks_to_lines([b"foo\nbar", b"\nbaz\n"]),
        )
        self.assertEqual(
            [b"foo\n", b"bar\n", b"baz\n"],
            osutils.chunks_to_lines([b"foo\n", b"bar\n", b"baz\n"]),
        )

    def test_osutils_binding(self):
        from . import test__chunks_to_lines

        if test__chunks_to_lines.compiled_chunkstolines_feature.available():
            from .._chunks_to_lines_pyx import chunks_to_lines
        else:
            from .._chunks_to_lines_py import chunks_to_lines
        self.assertIs(chunks_to_lines, osutils.chunks_to_lines)


class TestSplitLines(tests.TestCase):
    def test_split_unicode(self):
        self.assertEqual(["foo\n", "bar\xae"], osutils.split_lines("foo\nbar\xae"))
        self.assertEqual(["foo\n", "bar\xae\n"], osutils.split_lines("foo\nbar\xae\n"))

    def test_split_with_carriage_returns(self):
        self.assertEqual([b"foo\rbar\n"], osutils.split_lines(b"foo\rbar\n"))


class TestWalkDirs(tests.TestCaseInTempDir):
    def assertExpectedBlocks(self, expected, result):
        self.assertEqual(
            expected,
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result],
        )

    def test_walkdirs(self):
        tree = [".bzr", "0file", "1dir/", "1dir/0file", "1dir/1dir/", "2file"]
        self.build_tree(tree)
        expected_dirblocks = [
            (
                ("", "."),
                [
                    ("0file", "0file", "file"),
                    ("1dir", "1dir", "directory"),
                    ("2file", "2file", "file"),
                ],
            ),
            (
                ("1dir", "./1dir"),
                [
                    ("1dir/0file", "0file", "file"),
                    ("1dir/1dir", "1dir", "directory"),
                ],
            ),
            (("1dir/1dir", "./1dir/1dir"), []),
        ]
        result = []
        found_bzrdir = False
        for dirdetail, dirblock in osutils.walkdirs("."):
            if len(dirblock) and dirblock[0][1] == ".bzr":
                # this tests the filtering of selected paths
                found_bzrdir = True
                del dirblock[0]
            result.append((dirdetail, dirblock))

        self.assertTrue(found_bzrdir)
        self.assertExpectedBlocks(expected_dirblocks, result)
        # you can search a subdir only, with a supplied prefix.
        result = []
        for dirblock in osutils.walkdirs("./1dir", "1dir"):
            result.append(dirblock)
        self.assertExpectedBlocks(expected_dirblocks[1:], result)

    def test_walkdirs_os_error(self):
        # <https://bugs.launchpad.net/bzr/+bug/338653>
        # Pyrex readdir didn't raise useful messages if it had an error
        # reading the directory
        if sys.platform == "win32":
            raise tests.TestNotApplicable("readdir IOError not tested on win32")
        self.requireFeature(features.not_running_as_root)
        os.mkdir("test-unreadable")
        os.chmod("test-unreadable", 0000)
        # must chmod it back so that it can be removed
        self.addCleanup(os.chmod, "test-unreadable", 0o700)
        # The error is not raised until the generator is actually evaluated.
        # (It would be ok if it happened earlier but at the moment it
        # doesn't.)
        e = self.assertRaises(OSError, list, osutils._walkdirs_utf8("."))
        self.assertEqual("./test-unreadable", osutils.safe_unicode(e.filename))
        self.assertEqual(errno.EACCES, e.errno)
        # Ensure the message contains the file name
        self.assertContainsRe(str(e), "\\./test-unreadable")

    def test_walkdirs_encoding_error(self):
        # <https://bugs.launchpad.net/bzr/+bug/488519>
        # walkdirs didn't raise a useful message when the filenames
        # are not using the filesystem's encoding

        # require a bytestring based filesystem
        self.requireFeature(features.ByteStringNamedFilesystem)

        tree = [".bzr", "0file", "1dir/", "1dir/0file", "1dir/1dir/", "1file"]

        self.build_tree(tree)

        # rename the 1file to a latin-1 filename
        os.rename(b"./1file", b"\xe8file")
        if b"\xe8file" not in os.listdir("."):
            self.skipTest("Lack filesystem that preserves arbitrary bytes")

        self._save_platform_info()

        # this should raise on error
        def attempt():
            for _dirdetail, _dirblock in osutils.walkdirs(b".", codecs.utf_8_decode):
                pass

        self.assertRaises(UnicodeDecodeError, attempt)

    def test__walkdirs_utf8(self):
        tree = [".bzr", "0file", "1dir/", "1dir/0file", "1dir/1dir/", "2file"]
        self.build_tree(tree)
        expected_dirblocks = [
            (
                ("", "."),
                [
                    ("0file", "0file", "file"),
                    ("1dir", "1dir", "directory"),
                    ("2file", "2file", "file"),
                ],
            ),
            (
                ("1dir", "./1dir"),
                [
                    ("1dir/0file", "0file", "file"),
                    ("1dir/1dir", "1dir", "directory"),
                ],
            ),
            (("1dir/1dir", "./1dir/1dir"), []),
        ]
        result = []
        found_bzrdir = False
        for dirdetail, dirblock in osutils._walkdirs_utf8(b"."):
            if len(dirblock) and dirblock[0][1] == b".bzr":
                # this tests the filtering of selected paths
                found_bzrdir = True
                del dirblock[0]
            dirdetail = (
                dirdetail[0].decode("utf-8"),
                osutils.safe_unicode(dirdetail[1]),
            )
            dirblock = [
                (entry[0].decode("utf-8"), entry[1].decode("utf-8"), entry[2])
                for entry in dirblock
            ]
            result.append((dirdetail, dirblock))

        self.assertTrue(found_bzrdir)
        self.assertExpectedBlocks(expected_dirblocks, result)

        # you can search a subdir only, with a supplied prefix.
        result = []
        for dirblock in osutils.walkdirs("./1dir", "1dir"):
            result.append(dirblock)
        self.assertExpectedBlocks(expected_dirblocks[1:], result)

    def _filter_out_stat(self, result):
        """Filter out the stat value from the walkdirs result."""
        for _dirdetail, dirblock in result:
            new_dirblock = []
            for info in dirblock:
                # Ignore info[3] which is the stat
                new_dirblock.append((info[0], info[1], info[2], info[4]))
            dirblock[:] = new_dirblock

    def _save_platform_info(self):
        self.overrideAttr(osutils, "_selected_dir_reader")

    def assertDirReaderIs(self, expected, top, fs_enc=None):
        """Assert the right implementation for _walkdirs_utf8 is chosen."""
        # Force it to redetect
        osutils._selected_dir_reader = None
        # Nothing to list, but should still trigger the selection logic
        self.assertEqual(
            [((b"", top), [])], list(osutils._walkdirs_utf8(".", fs_enc=fs_enc))
        )
        self.assertIsInstance(osutils._selected_dir_reader, expected)

    def test_force_walkdirs_utf8_fs_utf8(self):
        self.requireFeature(UTF8DirReaderFeature)
        self._save_platform_info()
        self.assertDirReaderIs(
            UTF8DirReaderFeature.module.UTF8DirReader, b".", fs_enc="utf-8"
        )

    def test_force_walkdirs_utf8_fs_ascii(self):
        self.requireFeature(UTF8DirReaderFeature)
        self._save_platform_info()
        self.assertDirReaderIs(
            UTF8DirReaderFeature.module.UTF8DirReader, b".", fs_enc="ascii"
        )

    def test_force_walkdirs_utf8_fs_latin1(self):
        self._save_platform_info()
        self.assertDirReaderIs(osutils.UnicodeDirReader, ".", fs_enc="iso-8859-1")

    def test_unicode_walkdirs(self):
        """Walkdirs should always return unicode paths."""
        self.requireFeature(features.UnicodeFilenameFeature)
        name0 = "0file-\xb6"
        name1 = "1dir-\u062c\u0648"
        name2 = "2file-\u0633"
        tree = [
            name0,
            name1 + "/",
            name1 + "/" + name0,
            name1 + "/" + name1 + "/",
            name2,
        ]
        self.build_tree(tree)
        expected_dirblocks = [
            (
                ("", "."),
                [
                    (name0, name0, "file", "./" + name0),
                    (name1, name1, "directory", "./" + name1),
                    (name2, name2, "file", "./" + name2),
                ],
            ),
            (
                (name1, "./" + name1),
                [
                    (name1 + "/" + name0, name0, "file", "./" + name1 + "/" + name0),
                    (
                        name1 + "/" + name1,
                        name1,
                        "directory",
                        "./" + name1 + "/" + name1,
                    ),
                ],
            ),
            ((name1 + "/" + name1, "./" + name1 + "/" + name1), []),
        ]
        result = list(osutils.walkdirs("."))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks, result)
        result = list(osutils.walkdirs("./" + name1, name1))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks[1:], result)

    def test_unicode__walkdirs_utf8(self):
        """Walkdirs_utf8 should always return utf8 paths.

        The abspath portion might be in unicode or utf-8
        """
        self.requireFeature(features.UnicodeFilenameFeature)
        name0 = "0file-\xb6"
        name1 = "1dir-\u062c\u0648"
        name2 = "2file-\u0633"
        tree = [
            name0,
            name1 + "/",
            name1 + "/" + name0,
            name1 + "/" + name1 + "/",
            name2,
        ]
        self.build_tree(tree)
        name0 = name0.encode("utf8")
        name1 = name1.encode("utf8")
        name2 = name2.encode("utf8")

        expected_dirblocks = [
            (
                (b"", b"."),
                [
                    (name0, name0, "file", b"./" + name0),
                    (name1, name1, "directory", b"./" + name1),
                    (name2, name2, "file", b"./" + name2),
                ],
            ),
            (
                (name1, b"./" + name1),
                [
                    (name1 + b"/" + name0, name0, "file", b"./" + name1 + b"/" + name0),
                    (
                        name1 + b"/" + name1,
                        name1,
                        "directory",
                        b"./" + name1 + b"/" + name1,
                    ),
                ],
            ),
            ((name1 + b"/" + name1, b"./" + name1 + b"/" + name1), []),
        ]
        result = []
        # For ease in testing, if walkdirs_utf8 returns Unicode, assert that
        # all abspaths are Unicode, and encode them back into utf8.
        for dirdetail, dirblock in osutils._walkdirs_utf8("."):
            self.assertIsInstance(dirdetail[0], bytes)
            if isinstance(dirdetail[1], str):
                dirdetail = (dirdetail[0], dirdetail[1].encode("utf8"))
                dirblock = [list(info) for info in dirblock]
                for info in dirblock:
                    self.assertIsInstance(info[4], str)
                    info[4] = info[4].encode("utf8")
            new_dirblock = []
            for info in dirblock:
                self.assertIsInstance(info[0], bytes)
                self.assertIsInstance(info[1], bytes)
                self.assertIsInstance(info[4], bytes)
                # Remove the stat information
                new_dirblock.append((info[0], info[1], info[2], info[4]))
            result.append((dirdetail, new_dirblock))
        self.assertEqual(expected_dirblocks, result)

    def test__walkdirs_utf8_with_unicode_fs(self):
        """UnicodeDirReader should be a safe fallback everywhere.

        The abspath portion should be in unicode
        """
        self.requireFeature(features.UnicodeFilenameFeature)
        # Use the unicode reader. TODO: split into driver-and-driven unit
        # tests.
        self._save_platform_info()
        osutils._selected_dir_reader = osutils.UnicodeDirReader()
        name0u = "0file-\xb6"
        name1u = "1dir-\u062c\u0648"
        name2u = "2file-\u0633"
        tree = [
            name0u,
            name1u + "/",
            name1u + "/" + name0u,
            name1u + "/" + name1u + "/",
            name2u,
        ]
        self.build_tree(tree)
        name0 = name0u.encode("utf8")
        name1 = name1u.encode("utf8")
        name2 = name2u.encode("utf8")

        # All of the abspaths should be in unicode, all of the relative paths
        # should be in utf8
        expected_dirblocks = [
            (
                (b"", "."),
                [
                    (name0, name0, "file", "./" + name0u),
                    (name1, name1, "directory", "./" + name1u),
                    (name2, name2, "file", "./" + name2u),
                ],
            ),
            (
                (name1, "./" + name1u),
                [
                    (name1 + b"/" + name0, name0, "file", "./" + name1u + "/" + name0u),
                    (
                        name1 + b"/" + name1,
                        name1,
                        "directory",
                        "./" + name1u + "/" + name1u,
                    ),
                ],
            ),
            ((name1 + b"/" + name1, "./" + name1u + "/" + name1u), []),
        ]
        result = list(osutils._walkdirs_utf8("."))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks, result)

    def assertStatIsCorrect(self, path, win32stat):
        os_stat = os.stat(path)
        self.assertEqual(os_stat.st_size, win32stat.st_size)
        self.assertAlmostEqual(os_stat.st_mtime, win32stat.st_mtime, places=4)
        self.assertAlmostEqual(os_stat.st_ctime, win32stat.st_ctime, places=4)
        self.assertAlmostEqual(os_stat.st_atime, win32stat.st_atime, places=4)
        self.assertEqual(os_stat.st_dev, win32stat.st_dev)
        self.assertEqual(os_stat.st_ino, win32stat.st_ino)
        self.assertEqual(os_stat.st_mode, win32stat.st_mode)

    def assertPathCompare(self, path_less, path_greater):
        """Check that path_less and path_greater compare correctly."""
        self.assertEqual(0, osutils.compare_paths_prefix_order(path_less, path_less))
        self.assertEqual(
            0, osutils.compare_paths_prefix_order(path_greater, path_greater)
        )
        self.assertEqual(
            -1, osutils.compare_paths_prefix_order(path_less, path_greater)
        )
        self.assertEqual(1, osutils.compare_paths_prefix_order(path_greater, path_less))

    def test_compare_paths_prefix_order(self):
        # root before all else
        self.assertPathCompare("/", "/a")
        # alpha within a dir
        self.assertPathCompare("/a", "/b")
        self.assertPathCompare("/b", "/z")
        # high dirs before lower.
        self.assertPathCompare("/z", "/a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("/a/b/c", "/d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("/a/z", "/z/z")
        self.assertPathCompare("/a/c/z", "/a/d/e")

        # this should also be consistent for no leading / paths
        # root before all else
        self.assertPathCompare("", "a")
        # alpha within a dir
        self.assertPathCompare("a", "b")
        self.assertPathCompare("b", "z")
        # high dirs before lower.
        self.assertPathCompare("z", "a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("a/b/c", "d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("a/z", "z/z")
        self.assertPathCompare("a/c/z", "a/d/e")

    def test_path_prefix_sorting(self):
        """Doing a sort on path prefix should match our sample data."""
        original_paths = [
            "a",
            "a/b",
            "a/b/c",
            "b",
            "b/c",
            "d",
            "d/e",
            "d/e/f",
            "d/f",
            "d/g",
            "g",
        ]

        dir_sorted_paths = [
            "a",
            "b",
            "d",
            "g",
            "a/b",
            "a/b/c",
            "b/c",
            "d/e",
            "d/f",
            "d/g",
            "d/e/f",
        ]

        self.assertEqual(
            dir_sorted_paths, sorted(original_paths, key=osutils.path_prefix_key)
        )
        # using the comparison routine shoudl work too:
        self.assertEqual(
            dir_sorted_paths, sorted(original_paths, key=osutils.path_prefix_key)
        )


class TestCopyTree(tests.TestCaseInTempDir):
    def test_copy_basic_tree(self):
        self.build_tree(["source/", "source/a", "source/b/", "source/b/c"])
        osutils.copy_tree("source", "target")
        self.assertEqual(["a", "b"], sorted(os.listdir("target")))
        self.assertEqual(["c"], os.listdir("target/b"))

    def test_copy_tree_target_exists(self):
        self.build_tree(["source/", "source/a", "source/b/", "source/b/c", "target/"])
        osutils.copy_tree("source", "target")
        self.assertEqual(["a", "b"], sorted(os.listdir("target")))
        self.assertEqual(["c"], os.listdir("target/b"))

    def test_copy_tree_symlinks(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        self.build_tree(["source/"])
        os.symlink("a/generic/path", "source/lnk")
        osutils.copy_tree("source", "target")
        self.assertEqual(["lnk"], os.listdir("target"))
        self.assertEqual("a/generic/path", os.readlink("target/lnk"))

    def test_copy_tree_handlers(self):
        processed_files = []
        processed_links = []

        def file_handler(from_path, to_path):
            processed_files.append(("f", from_path, to_path))

        def dir_handler(from_path, to_path):
            processed_files.append(("d", from_path, to_path))

        def link_handler(from_path, to_path):
            processed_links.append((from_path, to_path))

        handlers = {
            "file": file_handler,
            "directory": dir_handler,
            "symlink": link_handler,
        }

        self.build_tree(["source/", "source/a", "source/b/", "source/b/c"])
        if osutils.supports_symlinks(self.test_dir):
            os.symlink("a/generic/path", "source/lnk")
        osutils.copy_tree("source", "target", handlers=handlers)

        self.assertEqual(
            [
                ("d", "source", "target"),
                ("f", "source/a", "target/a"),
                ("d", "source/b", "target/b"),
                ("f", "source/b/c", "target/b/c"),
            ],
            processed_files,
        )
        self.assertPathDoesNotExist("target")
        if osutils.supports_symlinks(self.test_dir):
            self.assertEqual([("source/lnk", "target/lnk")], processed_links)


class TestSetUnsetEnv(tests.TestCase):
    """Test updating the environment."""

    def setUp(self):
        super().setUp()

        self.assertEqual(
            None,
            os.environ.get("BRZ_TEST_ENV_VAR"),
            "Environment was not cleaned up properly."
            " Variable BRZ_TEST_ENV_VAR should not exist.",
        )

        def cleanup():
            if "BRZ_TEST_ENV_VAR" in os.environ:
                del os.environ["BRZ_TEST_ENV_VAR"]

        self.addCleanup(cleanup)

    def test_set(self):
        """Test that we can set an env variable."""
        old = osutils.set_or_unset_env("BRZ_TEST_ENV_VAR", "foo")
        self.assertEqual(None, old)
        self.assertEqual("foo", os.environ.get("BRZ_TEST_ENV_VAR"))

    def test_double_set(self):
        """Test that we get the old value out."""
        osutils.set_or_unset_env("BRZ_TEST_ENV_VAR", "foo")
        old = osutils.set_or_unset_env("BRZ_TEST_ENV_VAR", "bar")
        self.assertEqual("foo", old)
        self.assertEqual("bar", os.environ.get("BRZ_TEST_ENV_VAR"))

    def test_unicode(self):
        """Environment can only contain plain strings.

        So Unicode strings must be encoded.
        """
        uni_val, env_val = tests.probe_unicode_in_user_encoding()
        if uni_val is None:
            raise tests.TestSkipped(
                "Cannot find a unicode character that works in encoding {}".format(
                    osutils.get_user_encoding()
                )
            )

        osutils.set_or_unset_env("BRZ_TEST_ENV_VAR", uni_val)
        self.assertEqual(uni_val, os.environ.get("BRZ_TEST_ENV_VAR"))

    def test_unset(self):
        """Test that passing None will remove the env var."""
        osutils.set_or_unset_env("BRZ_TEST_ENV_VAR", "foo")
        old = osutils.set_or_unset_env("BRZ_TEST_ENV_VAR", None)
        self.assertEqual("foo", old)
        self.assertEqual(None, os.environ.get("BRZ_TEST_ENV_VAR"))
        self.assertNotIn("BRZ_TEST_ENV_VAR", os.environ)


class TestSizeShaFile(tests.TestCaseInTempDir):
    def test_sha_empty(self):
        self.build_tree_contents([("foo", b"")])
        expected_sha = osutils.sha_string(b"")
        f = open("foo")
        self.addCleanup(f.close)
        size, sha = osutils.size_sha_file(f)
        self.assertEqual(0, size)
        self.assertEqual(expected_sha, sha)

    def test_sha_mixed_endings(self):
        text = b"test\r\nwith\nall\rpossible line endings\r\n"
        self.build_tree_contents([("foo", text)])
        expected_sha = osutils.sha_string(text)
        f = open("foo", "rb")
        self.addCleanup(f.close)
        size, sha = osutils.size_sha_file(f)
        self.assertEqual(38, size)
        self.assertEqual(expected_sha, sha)


class TestShaFileByName(tests.TestCaseInTempDir):
    def test_sha_empty(self):
        self.build_tree_contents([("foo", b"")])
        expected_sha = osutils.sha_string(b"")
        self.assertEqual(expected_sha, osutils.sha_file_by_name("foo"))

    def test_sha_mixed_endings(self):
        text = b"test\r\nwith\nall\rpossible line endings\r\n"
        self.build_tree_contents([("foo", text)])
        expected_sha = osutils.sha_string(text)
        self.assertEqual(expected_sha, osutils.sha_file_by_name("foo"))


class TestResourceLoading(tests.TestCaseInTempDir):
    def test_resource_string(self):
        # test resource in breezy
        text = osutils.resource_string("breezy", "debug.py")
        self.assertContainsRe(text, "debug_flags = set()")
        # test resource under breezy
        text = osutils.resource_string("breezy.ui", "text.py")
        self.assertContainsRe(text, "class TextUIFactory")
        # test unsupported package
        self.assertRaises(errors.BzrError, osutils.resource_string, "zzzz", "yyy.xx")
        # test unknown resource
        self.assertRaises(IOError, osutils.resource_string, "breezy", "yyy.xx")


class TestDirReader(tests.TestCaseInTempDir):
    scenarios = dir_reader_scenarios()

    # Set by load_tests
    _dir_reader_class = None
    _native_to_unicode = None

    def setUp(self):
        super().setUp()
        self.overrideAttr(osutils, "_selected_dir_reader", self._dir_reader_class())

    def _get_ascii_tree(self):
        tree = ["0file", "1dir/", "1dir/0file", "1dir/1dir/", "2file"]
        expected_dirblocks = [
            (
                (b"", "."),
                [
                    (b"0file", b"0file", "file", "./0file"),
                    (b"1dir", b"1dir", "directory", "./1dir"),
                    (b"2file", b"2file", "file", "./2file"),
                ],
            ),
            (
                (b"1dir", "./1dir"),
                [
                    (b"1dir/0file", b"0file", "file", "./1dir/0file"),
                    (b"1dir/1dir", b"1dir", "directory", "./1dir/1dir"),
                ],
            ),
            ((b"1dir/1dir", "./1dir/1dir"), []),
        ]
        return tree, expected_dirblocks

    def test_walk_cur_dir(self):
        tree, expected_dirblocks = self._get_ascii_tree()
        self.build_tree(tree)
        result = list(osutils._walkdirs_utf8("."))
        # Filter out stat and abspath
        self.assertEqual(expected_dirblocks, self._filter_out(result))

    def test_walk_sub_dir(self):
        tree, expected_dirblocks = self._get_ascii_tree()
        self.build_tree(tree)
        # you can search a subdir only, with a supplied prefix.
        result = list(osutils._walkdirs_utf8(b"./1dir", b"1dir"))
        # Filter out stat and abspath
        self.assertEqual(expected_dirblocks[1:], self._filter_out(result))

    def _get_unicode_tree(self):
        name0u = "0file-\xb6"
        name1u = "1dir-\u062c\u0648"
        name2u = "2file-\u0633"
        tree = [
            name0u,
            name1u + "/",
            name1u + "/" + name0u,
            name1u + "/" + name1u + "/",
            name2u,
        ]
        name0 = name0u.encode("UTF-8")
        name1 = name1u.encode("UTF-8")
        name2 = name2u.encode("UTF-8")
        expected_dirblocks = [
            (
                (b"", "."),
                [
                    (name0, name0, "file", "./" + name0u),
                    (name1, name1, "directory", "./" + name1u),
                    (name2, name2, "file", "./" + name2u),
                ],
            ),
            (
                (name1, "./" + name1u),
                [
                    (name1 + b"/" + name0, name0, "file", "./" + name1u + "/" + name0u),
                    (
                        name1 + b"/" + name1,
                        name1,
                        "directory",
                        "./" + name1u + "/" + name1u,
                    ),
                ],
            ),
            ((name1 + b"/" + name1, "./" + name1u + "/" + name1u), []),
        ]
        return tree, expected_dirblocks

    def _filter_out(self, raw_dirblocks):
        """Filter out a walkdirs_utf8 result.

        stat field is removed, all native paths are converted to unicode
        """
        filtered_dirblocks = []
        for dirinfo, block in raw_dirblocks:
            dirinfo = (dirinfo[0], self._native_to_unicode(dirinfo[1]))
            details = []
            for line in block:
                details.append(line[0:3] + (self._native_to_unicode(line[4]),))
            filtered_dirblocks.append((dirinfo, details))
        return filtered_dirblocks

    def test_walk_unicode_tree(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        tree, expected_dirblocks = self._get_unicode_tree()
        self.build_tree(tree)
        result = list(osutils._walkdirs_utf8("."))
        self.assertEqual(expected_dirblocks, self._filter_out(result))

    def test_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        self.requireFeature(features.UnicodeFilenameFeature)
        target = "target\N{EURO SIGN}"
        link_name = "l\N{EURO SIGN}nk"
        os.symlink(target, link_name)
        link_name_utf8 = link_name.encode("UTF-8")
        expected_dirblocks = [
            (
                (b"", "."),
                [
                    (link_name_utf8, link_name_utf8, "symlink", "./" + link_name),
                ],
            )
        ]
        result = list(osutils._walkdirs_utf8("."))
        self.assertEqual(expected_dirblocks, self._filter_out(result))


class TestReadLink(tests.TestCaseInTempDir):
    """Exposes os.readlink() problems and the osutils solution.

    The only guarantee offered by os.readlink(), starting with 2.6, is that a
    unicode string will be returned if a unicode string is passed.

    But prior python versions failed to properly encode the passed unicode
    string.
    """

    _test_needs_features = [features.UnicodeFilenameFeature]

    def setUp(self):
        super(tests.TestCaseInTempDir, self).setUp()
        self._test_needs_features.append(features.SymlinkFeature(self.test_dir))
        self.link = "l\N{EURO SIGN}ink"
        self.target = "targe\N{EURO SIGN}t"
        os.symlink(self.target, self.link)

    def test_os_readlink_link_encoding(self):
        self.assertEqual(self.target, os.readlink(self.link))

    def test_os_readlink_link_decoding(self):
        self.assertEqual(os.fsencode(self.target), os.readlink(os.fsencode(self.link)))


class TestConcurrency(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(osutils, "_cached_local_concurrency")

    def test_local_concurrency(self):
        concurrency = osutils.local_concurrency()
        self.assertIsInstance(concurrency, int)

    def test_local_concurrency_environment_variable(self):
        self.overrideEnv("BRZ_CONCURRENCY", "2")
        self.assertEqual(2, osutils.local_concurrency(use_cache=False))
        self.overrideEnv("BRZ_CONCURRENCY", "3")
        self.assertEqual(3, osutils.local_concurrency(use_cache=False))
        self.overrideEnv("BRZ_CONCURRENCY", "foo")
        self.assertEqual(1, osutils.local_concurrency(use_cache=False))

    def test_option_concurrency(self):
        self.overrideEnv("BRZ_CONCURRENCY", "1")
        self.run_bzr("rocks --concurrency 42")
        # Command line overrides environment variable
        self.assertEqual("42", os.environ["BRZ_CONCURRENCY"])
        self.assertEqual(42, osutils.local_concurrency(use_cache=False))


class TestFailedToLoadExtension(tests.TestCase):
    def _try_loading(self):
        try:
            import breezy._fictional_extension_py  # noqa: F401
        except ImportError as e:
            osutils.failed_to_load_extension(e)
            return True

    def setUp(self):
        super().setUp()
        self.overrideAttr(osutils, "_extension_load_failures", [])

    def test_failure_to_load(self):
        self._try_loading()
        self.assertLength(1, osutils._extension_load_failures)
        self.assertEqual(
            osutils._extension_load_failures[0],
            "No module named 'breezy._fictional_extension_py'",
        )

    def test_report_extension_load_failures_no_warning(self):
        self.assertTrue(self._try_loading())
        warnings, result = self.callCatchWarnings(
            osutils.report_extension_load_failures
        )
        # it used to give a Python warning; it no longer does
        self.assertLength(0, warnings)

    def test_report_extension_load_failures_message(self):
        log = BytesIO()
        trace.push_log_file(log)
        self.assertTrue(self._try_loading())
        osutils.report_extension_load_failures()
        self.assertContainsRe(
            log.getvalue(),
            rb"brz: warning: some compiled extensions could not be loaded; "
            b"see ``brz help missing-extensions``\n",
        )


class TestTerminalWidth(tests.TestCase):
    def setUp(self):
        super().setUp()
        self._orig_terminal_size_state = osutils._terminal_size_state
        self._orig_first_terminal_size = osutils._first_terminal_size
        self.addCleanup(self.restore_osutils_globals)
        osutils._terminal_size_state = "no_data"
        osutils._first_terminal_size = None

    def restore_osutils_globals(self):
        osutils._terminal_size_state = self._orig_terminal_size_state
        osutils._first_terminal_size = self._orig_first_terminal_size

    def replace_stdout(self, new):
        self.overrideAttr(sys, "stdout", new)

    def replace__terminal_size(self, new):
        self.overrideAttr(osutils, "_terminal_size", new)

    def set_fake_tty(self):
        class I_am_a_tty:
            def isatty(self):
                return True

        self.replace_stdout(I_am_a_tty())

    def test_default_values(self):
        self.assertEqual(80, osutils.default_terminal_width)

    def test_defaults_to_BRZ_COLUMNS(self):
        # BRZ_COLUMNS is set by the test framework
        self.assertNotEqual("12", os.environ["BRZ_COLUMNS"])
        self.overrideEnv("BRZ_COLUMNS", "12")
        self.assertEqual(12, osutils.terminal_width())

    def test_BRZ_COLUMNS_0_no_limit(self):
        self.overrideEnv("BRZ_COLUMNS", "0")
        self.assertEqual(None, osutils.terminal_width())

    def test_falls_back_to_COLUMNS(self):
        self.overrideEnv("BRZ_COLUMNS", None)
        self.assertNotEqual("42", os.environ["COLUMNS"])
        self.set_fake_tty()
        self.overrideEnv("COLUMNS", "42")
        self.assertEqual(42, osutils.terminal_width())

    def test_tty_default_without_columns(self):
        self.overrideEnv("BRZ_COLUMNS", None)
        self.overrideEnv("COLUMNS", None)

        def terminal_size(w, h):
            return 42, 42

        self.set_fake_tty()
        # We need to override the osutils definition as it depends on the
        # running environment that we can't control (PQM running without a
        # controlling terminal is one example).
        self.replace__terminal_size(terminal_size)
        self.assertEqual(42, osutils.terminal_width())

    def test_non_tty_default_without_columns(self):
        self.overrideEnv("BRZ_COLUMNS", None)
        self.overrideEnv("COLUMNS", None)
        self.replace_stdout(None)
        self.assertEqual(None, osutils.terminal_width())

    def test_no_TIOCGWINSZ(self):
        self.requireFeature(term_ios_feature)
        termios = term_ios_feature.module
        # bug 63539 is about a termios without TIOCGWINSZ attribute
        try:
            termios.TIOCGWINSZ  # noqa: B018
        except AttributeError:
            # We won't remove TIOCGWINSZ, because it doesn't exist anyway :)
            pass
        else:
            self.overrideAttr(termios, "TIOCGWINSZ")
            del termios.TIOCGWINSZ
        self.overrideEnv("BRZ_COLUMNS", None)
        self.overrideEnv("COLUMNS", None)
        # Whatever the result is, if we don't raise an exception, it's ok.
        osutils.terminal_width()


class TestCreationOps(tests.TestCaseInTempDir):
    _test_needs_features = [features.chown_feature]

    def setUp(self):
        super().setUp()
        self.overrideAttr(os, "chown", self._dummy_chown)

        # params set by call to _dummy_chown
        self.path = self.uid = self.gid = None

    def _dummy_chown(self, path, uid, gid):
        self.path, self.uid, self.gid = path, uid, gid

    def test_copy_ownership_from_path(self):
        """copy_ownership_from_path test with specified src."""
        ownsrc = "/"
        open("test_file", "w").close()
        osutils.copy_ownership_from_path("test_file", ownsrc)

        s = os.stat(ownsrc)
        self.assertEqual(self.path, "test_file")
        self.assertEqual(self.uid, s.st_uid)
        self.assertEqual(self.gid, s.st_gid)

    def test_copy_ownership_nonesrc(self):
        """copy_ownership_from_path test with src=None."""
        open("test_file", "w").close()
        # should use parent dir for permissions
        osutils.copy_ownership_from_path("test_file")

        s = os.stat("..")
        self.assertEqual(self.path, "test_file")
        self.assertEqual(self.uid, s.st_uid)
        self.assertEqual(self.gid, s.st_gid)


class TestGetuserUnicode(tests.TestCase):
    def test_is_unicode(self):
        user = osutils.getuser_unicode()
        self.assertIsInstance(user, str)

    def envvar_to_override(self):
        if sys.platform == "win32":
            # Disable use of platform calls on windows so envvar is used
            self.overrideAttr(win32utils.ctypes, "windll", None)
            return "USERNAME"  # only variable used on windows
        return "LOGNAME"  # first variable checked by getpass.getuser()

    def test_ascii_user(self):
        self.overrideEnv(self.envvar_to_override(), "jrandom")
        self.assertEqual("jrandom", osutils.getuser_unicode())

    def test_unicode_user(self):
        ue = osutils.get_user_encoding()
        uni_val, env_val = tests.probe_unicode_in_user_encoding()
        if uni_val is None:
            raise tests.TestSkipped(
                "Cannot find a unicode character that works in encoding {}".format(
                    osutils.get_user_encoding()
                )
            )
        uni_username = "jrandom" + uni_val
        uni_username.encode(ue)
        self.overrideEnv(self.envvar_to_override(), uni_username)
        self.assertEqual(uni_username, osutils.getuser_unicode())


class TestBackupNames(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.backups = []

    def backup_exists(self, name):
        return name in self.backups

    def available_backup_name(self, name):
        backup_name = osutils.available_backup_name(name, self.backup_exists)
        self.backups.append(backup_name)
        return backup_name

    def assertBackupName(self, expected, name):
        self.assertEqual(expected, self.available_backup_name(name))

    def test_empty(self):
        self.assertBackupName("file.~1~", "file")

    def test_existing(self):
        self.available_backup_name("file")
        self.available_backup_name("file")
        self.assertBackupName("file.~3~", "file")
        # Empty slots are found, this is not a strict requirement and may be
        # revisited if we test against all implementations.
        self.backups.remove("file.~2~")
        self.assertBackupName("file.~2~", "file")


class TestFindExecutableInPath(tests.TestCase):
    def test_windows(self):
        if sys.platform != "win32":
            raise tests.TestSkipped("test requires win32")
        self.assertTrue(osutils.find_executable_on_path("explorer") is not None)
        self.assertTrue(osutils.find_executable_on_path("explorer.exe") is not None)
        self.assertTrue(osutils.find_executable_on_path("EXPLORER.EXE") is not None)
        self.assertTrue(
            osutils.find_executable_on_path("THIS SHOULD NOT EXIST") is None
        )
        self.assertTrue(osutils.find_executable_on_path("file.txt") is None)

    def test_windows_app_path(self):
        if sys.platform != "win32":
            raise tests.TestSkipped("test requires win32")
        # Override PATH env var so that exe can only be found on App Path
        self.overrideEnv("PATH", "")
        # Internt Explorer is always registered in the App Path
        self.assertTrue(osutils.find_executable_on_path("iexplore") is not None)

    def test_other(self):
        if sys.platform == "win32":
            raise tests.TestSkipped("test requires non-win32")
        self.assertTrue(osutils.find_executable_on_path("sh") is not None)
        self.assertTrue(
            osutils.find_executable_on_path("THIS SHOULD NOT EXIST") is None
        )


class SupportsExecutableTests(tests.TestCaseInTempDir):
    def test_returns_bool(self):
        self.assertIsInstance(osutils.supports_executable(self.test_dir), bool)


class SupportsSymlinksTests(tests.TestCaseInTempDir):
    def setUp(self):
        super().setUp()
        self.overrideAttr(
            osutils,
            "_FILESYSTEM_FINDER",
            osutils.MtabFilesystemFinder(
                [
                    (b"/usr", "ext4"),
                    (b"/home", "vfat"),
                    (b"/home/jelmer/smb", "ntfs"),
                    (b"/home/jelmer", "ext2"),
                ]
            ),
        )

    def test_returns_bool(self):
        self.assertIsInstance(osutils.supports_symlinks(self.test_dir), bool)

    def test_known(self):
        self.assertTrue(osutils.supports_symlinks("/usr"))
        self.assertFalse(osutils.supports_symlinks("/home/bogus"))
        self.assertTrue(osutils.supports_symlinks("/home/jelmer/osx"))
        self.assertFalse(osutils.supports_symlinks("/home/jelmer/smb"))

    def test_unknown(self):
        have_symlinks = sys.platform != "win32"
        self.assertIs(osutils.supports_symlinks("/var"), have_symlinks)

    def test_error(self):
        have_symlinks = sys.platform != "win32"

        def raise_error(path):
            raise errors.DependencyNotPresent("FS", "TEST")

        self.overrideAttr(osutils, "get_fs_type", raise_error)
        self.assertIs(osutils.supports_symlinks("/var"), have_symlinks)


class MtabReader(tests.TestCaseInTempDir):
    def test_read_mtab(self):
        self.build_tree_contents(
            [
                (
                    "mtab",
                    """\
/dev/mapper/blah--vg-root / ext4 rw,relatime,errors=remount-ro 0 0
/dev/mapper/blah--vg-home /home vfat rw,relatime 0 0
# comment

iminvalid
""",
                )
            ]
        )
        self.assertEqual(
            list(osutils.read_mtab("mtab")), [(b"/", "ext4"), (b"/home", "vfat")]
        )


class GetFsTypeTests(tests.TestCaseInTempDir):
    def test_returns_string_or_none(self):
        ret = osutils.get_fs_type(self.test_dir)
        self.assertTrue(isinstance(ret, str) or ret is None)

    def test_returns_most_specific(self):
        self.overrideAttr(
            osutils,
            "_FILESYSTEM_FINDER",
            osutils.MtabFilesystemFinder(
                [(b"/", "ext4"), (b"/home", "vfat"), (b"/home/jelmer", "ext2")]
            ),
        )
        self.assertEqual(osutils.get_fs_type(b"/home/jelmer/blah"), "ext2")
        self.assertEqual(osutils.get_fs_type("/home/jelmer/blah"), "ext2")
        self.assertEqual(osutils.get_fs_type(b"/home/jelmer"), "ext2")
        self.assertEqual(osutils.get_fs_type(b"/home/martin"), "vfat")
        self.assertEqual(osutils.get_fs_type(b"/home"), "vfat")
        self.assertEqual(osutils.get_fs_type(b"/other"), "ext4")

    def test_returns_none(self):
        self.overrideAttr(
            osutils, "_FILESYSTEM_FINDER", osutils.MtabFilesystemFinder([])
        )
        self.assertIs(osutils.get_fs_type("/home/jelmer/blah"), None)
        self.assertIs(osutils.get_fs_type(b"/home/jelmer/blah"), None)
        self.assertIs(osutils.get_fs_type("/home/jelmer"), None)

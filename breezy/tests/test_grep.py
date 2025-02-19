# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

import os
import re
import unicodedata as ud

from .. import osutils, tests
from .._termcolor import FG, color_string
from ..tests.features import UnicodeFilenameFeature

# NOTE: As bzr-grep optimizes PATTERN search to -F/--fixed-string
# for patterns that are not alphanumeric+whitespace, we test grep
# specfically with patterns that have special characters so that
# regex path is tested. alphanumeric patterns test the -F path.


class GrepTestBase(tests.TestCaseWithTransport):
    """Base class for testing grep.

    Provides support methods for creating directory and file revisions.
    """

    _reflags = re.MULTILINE | re.DOTALL

    def _mk_file(self, path, line_prefix, total_lines, versioned):
        text = ""
        for i in range(total_lines):
            text += line_prefix + str(i + 1) + "\n"

        with open(path, "w") as f:
            f.write(text)
        if versioned:
            self.run_bzr(["add", path])
            self.run_bzr(["ci", "-m", '"' + path + '"'])

    def _update_file(self, path, text, checkin=True):
        """Append text to file 'path' and check it in"""
        with open(path, "a") as f:
            f.write(text)
        if checkin:
            self.run_bzr(["ci", path, "-m", '"' + path + '"'])

    def _mk_unknown_file(self, path, line_prefix="line", total_lines=10):
        self._mk_file(path, line_prefix, total_lines, versioned=False)

    def _mk_versioned_file(self, path, line_prefix="line", total_lines=10):
        self._mk_file(path, line_prefix, total_lines, versioned=True)

    def _mk_dir(self, path, versioned):
        os.mkdir(path)
        if versioned:
            self.run_bzr(["add", path])
            self.run_bzr(["ci", "-m", '"' + path + '"'])

    def _mk_unknown_dir(self, path):
        self._mk_dir(path, versioned=False)

    def _mk_versioned_dir(self, path):
        self._mk_dir(path, versioned=True)


class TestGrep(GrepTestBase):
    """Core functional tests for grep."""

    def test_basic_unknown_file(self):
        """Search for pattern in specfic file.

        If specified file is unknown, grep it anyway.
        """
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_unknown_file("file0.txt")

        out, err = self.run_bzr(["grep", "line1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)  # finds line1 and line10

        out, err = self.run_bzr(["grep", "line\\d+", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 10)

        # unknown file is not grepped unless explicitely specified
        out, err = self.run_bzr(["grep", "line1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

        # unknown file is not grepped unless explicitely specified
        out, err = self.run_bzr(["grep", "line1$"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

    def test_ver_basic_file(self):
        """(versioned) Search for pattern in specfic file."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(["grep", "-r", "1", "line1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt~1:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)  # finds line1 and line10

        out, err = self.run_bzr(["grep", "-r", "1", "line[0-9]$", "file0.txt"])
        self.assertContainsRe(out, "file0.txt~1:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 9)

        # finds all the lines
        out, err = self.run_bzr(["grep", "-r", "1", "line[0-9]", "file0.txt"])
        self.assertContainsRe(out, "file0.txt~1:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 10)

    def test_wtree_basic_file(self):
        """(wtree) Search for pattern in specfic file."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")
        self._update_file("file0.txt", "ABC\n", checkin=False)

        out, err = self.run_bzr(["grep", "ABC", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:ABC", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "[A-Z]{3}", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:ABC", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-r", "last:1", "ABC", "file0.txt"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

        out, err = self.run_bzr(["grep", "-r", "last:1", "[A-Z]{3}", "file0.txt"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

    def test_ver_basic_include(self):
        """(versioned) Ensure that -I flag is respected."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.aa")
        self._mk_versioned_file("file0.bb")
        self._mk_versioned_file("file0.cc")

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--include", "*.aa", "--include", "*.bb", "line1"]
        )
        self.assertContainsRe(out, "file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # two lines each (line1, line10) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--include", "*.aa", "--include", "*.bb", "line1$"]
        )
        self.assertContainsRe(out, "file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # one lines each (line1) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "-I", "*.aa", "-I", "*.bb", "line1"]
        )
        self.assertContainsRe(out, "file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # two lines each (line1, line10) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "-I", "*.aa", "-I", "*.bb", "line1$"]
        )
        self.assertContainsRe(out, "file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # one lines each (line1) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 2)

    def test_wtree_basic_include(self):
        """(wtree) Ensure that --include flag is respected."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.aa")
        self._mk_versioned_file("file0.bb")
        self._mk_versioned_file("file0.cc")

        out, err = self.run_bzr(
            ["grep", "--include", "*.aa", "--include", "*.bb", "line1"]
        )
        self.assertContainsRe(out, "file0.aa:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # two lines each (line1, line10) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(
            ["grep", "--include", "*.aa", "--include", "*.bb", "line1$"]
        )
        self.assertContainsRe(out, "file0.aa:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # one line each (line1) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 2)

    def test_ver_basic_exclude(self):
        """(versioned) Ensure that --exclude flag is respected."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.aa")
        self._mk_versioned_file("file0.bb")
        self._mk_versioned_file("file0.cc")

        out, err = self.run_bzr(["grep", "-r", "last:1", "--exclude", "*.cc", "line1"])
        self.assertContainsRe(out, "file0.aa~.:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.aa~.:line10", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line10", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # two lines each (line1, line10) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--exclude", "*.cc", "line1$"])
        self.assertContainsRe(out, "file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # one line each (line1) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "-r", "last:1", "-X", "*.cc", "line1"])
        self.assertContainsRe(out, "file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # two lines each (line1, line10) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 4)

    def test_wtree_basic_exclude(self):
        """(wtree) Ensure that --exclude flag is respected."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.aa")
        self._mk_versioned_file("file0.bb")
        self._mk_versioned_file("file0.cc")

        out, err = self.run_bzr(["grep", "--exclude", "*.cc", "line1"])
        self.assertContainsRe(out, "file0.aa:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # two lines each (line1, line10) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "--exclude", "*.cc", "lin.1$"])
        self.assertContainsRe(out, "file0.aa:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.bb:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.cc", flags=TestGrep._reflags)
        # one line each (line1) from file0.aa and file0.bb
        self.assertEqual(len(out.splitlines()), 2)

    def test_ver_multiple_files(self):
        """(versioned) Search for pattern in multiple files."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt", total_lines=2)
        self._mk_versioned_file("file1.txt", total_lines=2)
        self._mk_versioned_file("file2.txt", total_lines=2)

        out, err = self.run_bzr(["grep", "-r", "last:1", "line[1-2]$"])
        self.assertContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~.:line2", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~.:line2", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file2.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file2.txt~.:line2", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 6)

        out, err = self.run_bzr(["grep", "-r", "last:1", "line"])
        self.assertContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~.:line2", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~.:line2", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file2.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file2.txt~.:line2", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 6)

    def test_multiple_wtree_files(self):
        """(wtree) Search for pattern in multiple files in working tree."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt", total_lines=2)
        self._mk_versioned_file("file1.txt", total_lines=2)
        self._mk_versioned_file("file2.txt", total_lines=2)
        self._update_file("file0.txt", "HELLO\n", checkin=False)
        self._update_file("file1.txt", "HELLO\n", checkin=True)
        self._update_file("file2.txt", "HELLO\n", checkin=False)

        out, err = self.run_bzr(
            ["grep", "HELLO", "file0.txt", "file1.txt", "file2.txt"]
        )

        self.assertContainsRe(out, "file0.txt:HELLO", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt:HELLO", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file2.txt:HELLO", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        out, err = self.run_bzr(
            ["grep", "HELLO", "-r", "last:1", "file0.txt", "file1.txt", "file2.txt"]
        )

        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~.:HELLO", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file2.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(
            ["grep", "HE..O", "file0.txt", "file1.txt", "file2.txt"]
        )

        self.assertContainsRe(out, "file0.txt:HELLO", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt:HELLO", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file2.txt:HELLO", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        out, err = self.run_bzr(
            ["grep", "HE..O", "-r", "last:1", "file0.txt", "file1.txt", "file2.txt"]
        )

        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~.:HELLO", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file2.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

    def test_ver_null_option(self):
        """(versioned) --null option should use NUL instead of newline."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt", total_lines=3)

        nref = ud.normalize(
            "NFC", "file0.txt~1:line1\0file0.txt~1:line2\0file0.txt~1:line3\0"
        )

        out, err = self.run_bzr(["grep", "-r", "last:1", "--null", "line[1-3]"])
        nout = ud.normalize("NFC", out)
        self.assertEqual(nout, nref)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-r", "last:1", "-Z", "line[1-3]"])
        nout = ud.normalize("NFC", out)
        self.assertEqual(nout, nref)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--null", "line"])
        nout = ud.normalize("NFC", out)
        self.assertEqual(nout, nref)
        self.assertEqual(len(out.splitlines()), 1)

    def test_wtree_null_option(self):
        """(wtree) --null option should use NUL instead of newline."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt", total_lines=3)

        out, err = self.run_bzr(["grep", "--null", "line[1-3]"])
        self.assertEqual(out, "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-Z", "line[1-3]"])
        self.assertEqual(out, "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-Z", "line"])
        self.assertEqual(out, "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")
        self.assertEqual(len(out.splitlines()), 1)

    def test_versioned_file_in_dir_no_recursive(self):
        """(versioned) Should not recurse with --no-recursive"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("fileX.txt", line_prefix="lin")
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        out, err = self.run_bzr(["grep", "-r", "last:1", "--no-recursive", "line1"])
        self.assertNotContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--no-recursive", "line1$"])
        self.assertNotContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

    def test_wtree_file_in_dir_no_recursive(self):
        """(wtree) Should not recurse with --no-recursive"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("fileX.txt", line_prefix="lin")
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        out, err = self.run_bzr(["grep", "--no-recursive", "line1"])
        self.assertNotContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

        out, err = self.run_bzr(["grep", "--no-recursive", "lin.1"])
        self.assertNotContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

    def test_versioned_file_in_dir_recurse(self):
        """(versioned) Should recurse by default."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        out, err = self.run_bzr(["grep", "-r", "-1", ".i.e1"])
        self.assertContainsRe(out, "^dir0/file0.txt~.:line1", flags=TestGrep._reflags)
        # find line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "-r", "-1", "line1"])
        self.assertContainsRe(out, "^dir0/file0.txt~.:line1", flags=TestGrep._reflags)
        # find line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_wtree_file_in_dir_recurse(self):
        """(wtree) Should recurse by default."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        out, err = self.run_bzr(["grep", "line1"])
        self.assertContainsRe(out, "^dir0/file0.txt:line1", flags=TestGrep._reflags)
        # find line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "lin.1"])
        self.assertContainsRe(out, "^dir0/file0.txt:line1", flags=TestGrep._reflags)
        # find line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_versioned_file_within_dir(self):
        """(versioned) Search for pattern while in nested dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "-r", "last:1", "line1"])
        self.assertContainsRe(out, "^file0.txt~.:line1", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "-r", "last:1", ".i.e1"])
        self.assertContainsRe(out, "^file0.txt~.:line1", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_versioned_include_file_within_dir(self):
        """(versioned) Ensure --include is respected with file within dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")  # revno 1
        self._mk_versioned_file("dir0/file0.txt")  # revno 2
        self._mk_versioned_file("dir0/file1.aa")  # revno 3
        self._update_file("dir0/file1.aa", "hello\n")  # revno 4
        self._update_file("dir0/file0.txt", "hello\n")  # revno 5
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "-r", "last:1", "--include", "*.aa", "line1"])
        self.assertContainsRe(out, "^file1.aa~5:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~5:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(
            ["grep", "-r", "last:2..last:1", "--include", "*.aa", "line1"]
        )
        self.assertContainsRe(out, "^file1.aa~4:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~4:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~5:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~5:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10 over two revisions
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--include", "*.aa", "lin.1"])
        self.assertContainsRe(out, "^file1.aa~5:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~5:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(
            ["grep", "-r", "last:3..last:1", "--include", "*.aa", "lin.1"]
        )
        self.assertContainsRe(out, "^file1.aa~3:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~4:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~5:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~3:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~4:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa~5:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10 over 3 revisions
        self.assertEqual(len(out.splitlines()), 6)

    def test_versioned_exclude_file_within_dir(self):
        """(versioned) Ensure --exclude is respected with file within dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")
        self._mk_versioned_file("dir0/file1.aa")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "-r", "last:1", "--exclude", "*.txt", "line1"])
        self.assertContainsRe(out, "^file1.aa~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--exclude", "*.txt", "l[a-z]ne1"]
        )
        self.assertContainsRe(out, "^file1.aa~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_wtree_file_within_dir(self):
        """(wtree) Search for pattern while in nested dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "line1"])
        self.assertContainsRe(out, "^file0.txt:line1", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "l[aeiou]ne1"])
        self.assertContainsRe(out, "^file0.txt:line1", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_wtree_include_file_within_dir(self):
        """(wtree) Ensure --include is respected with file within dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")
        self._mk_versioned_file("dir0/file1.aa")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "--include", "*.aa", "line1"])
        self.assertContainsRe(out, "^file1.aa:line1", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "--include", "*.aa", "l[ixn]ne1"])
        self.assertContainsRe(out, "^file1.aa:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_wtree_exclude_file_within_dir(self):
        """(wtree) Ensure --exclude is respected with file within dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")
        self._mk_versioned_file("dir0/file1.aa")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "--exclude", "*.txt", "li.e1"])
        self.assertContainsRe(out, "^file1.aa:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

        out, err = self.run_bzr(["grep", "--exclude", "*.txt", "line1"])
        self.assertContainsRe(out, "^file1.aa:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.aa:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 2)

    def test_versioned_include_from_outside_dir(self):
        """(versioned) Ensure --include is respected during recursive search."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.aa")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.bb")

        self._mk_versioned_dir("dir2")
        self._mk_versioned_file("dir2/file2.cc")

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--include", "*.aa", "--include", "*.bb", "l..e1"]
        )
        self.assertContainsRe(out, "^dir0/file0.aa~.:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb~.:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.aa~.:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb~.:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--include", "*.aa", "--include", "*.bb", "line1"]
        )
        self.assertContainsRe(out, "^dir0/file0.aa~.:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb~.:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.aa~.:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb~.:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 4)

    def test_wtree_include_from_outside_dir(self):
        """(wtree) Ensure --include is respected during recursive search."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.aa")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.bb")

        self._mk_versioned_dir("dir2")
        self._mk_versioned_file("dir2/file2.cc")

        out, err = self.run_bzr(
            ["grep", "--include", "*.aa", "--include", "*.bb", "l.n.1"]
        )
        self.assertContainsRe(out, "^dir0/file0.aa:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.aa:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(
            ["grep", "--include", "*.aa", "--include", "*.bb", "line1"]
        )
        self.assertContainsRe(out, "^dir0/file0.aa:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.aa:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb:line10$", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)
        # finds line1 and line10
        self.assertEqual(len(out.splitlines()), 4)

    def test_versioned_exclude_from_outside_dir(self):
        """(versioned) Ensure --exclude is respected during recursive search."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.aa")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.bb")

        self._mk_versioned_dir("dir2")
        self._mk_versioned_file("dir2/file2.cc")

        out, err = self.run_bzr(["grep", "-r", "last:1", "--exclude", "*.cc", "l..e1"])
        self.assertContainsRe(out, "^dir0/file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--exclude", "*.cc", "line1"])
        self.assertContainsRe(out, "^dir0/file0.aa~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb~.:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)

    def test_wtree_exclude_from_outside_dir(self):
        """(wtree) Ensure --exclude is respected during recursive search."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.aa")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.bb")

        self._mk_versioned_dir("dir2")
        self._mk_versioned_file("dir2/file2.cc")

        out, err = self.run_bzr(["grep", "--exclude", "*.cc", "l[hijk]ne1"])
        self.assertContainsRe(out, "^dir0/file0.aa:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "--exclude", "*.cc", "line1"])
        self.assertContainsRe(out, "^dir0/file0.aa:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.bb:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file1.cc", flags=TestGrep._reflags)

    def test_workingtree_files_from_outside_dir(self):
        """(wtree) Grep for pattern with dirs passed as argument."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.txt")

        out, err = self.run_bzr(["grep", "l[aeiou]ne1", "dir0", "dir1"])
        self.assertContainsRe(out, "^dir0/file0.txt:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "line1", "dir0", "dir1"])
        self.assertContainsRe(out, "^dir0/file0.txt:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.txt:line1", flags=TestGrep._reflags)

    def test_versioned_files_from_outside_dir(self):
        """(versioned) Grep for pattern with dirs passed as argument."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.txt")

        out, err = self.run_bzr(["grep", "-r", "last:1", ".ine1", "dir0", "dir1"])
        self.assertContainsRe(out, "^dir0/file0.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "line1", "dir0", "dir1"])
        self.assertContainsRe(out, "^dir0/file0.txt~.:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.txt~.:line1", flags=TestGrep._reflags)

    def test_wtree_files_from_outside_dir(self):
        """(wtree) Grep for pattern with dirs passed as argument."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.txt")

        out, err = self.run_bzr(["grep", "li.e1", "dir0", "dir1"])
        self.assertContainsRe(out, "^dir0/file0.txt:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "line1", "dir0", "dir1"])
        self.assertContainsRe(out, "^dir0/file0.txt:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir1/file1.txt:line1", flags=TestGrep._reflags)

    def test_versioned_files_from_outside_two_dirs(self):
        """(versioned) Grep for pattern with two levels of nested dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.txt")

        self._mk_versioned_dir("dir0/dir00")
        self._mk_versioned_file("dir0/dir00/file0.txt")

        out, err = self.run_bzr(["grep", "-r", "last:1", "l.ne1", "dir0/dir00"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt~.:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "-r", "last:1", "l.ne1"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt~.:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "-r", "last:1", "line1", "dir0/dir00"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt~.:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "-r", "last:1", "line1"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt~.:line1", flags=TestGrep._reflags
        )

    def test_wtree_files_from_outside_two_dirs(self):
        """(wtree) Grep for pattern with two levels of nested dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file0.txt")

        self._mk_versioned_dir("dir1")
        self._mk_versioned_file("dir1/file1.txt")

        self._mk_versioned_dir("dir0/dir00")
        self._mk_versioned_file("dir0/dir00/file0.txt")

        out, err = self.run_bzr(["grep", "lin.1", "dir0/dir00"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "li.e1"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "line1", "dir0/dir00"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "line1"])
        self.assertContainsRe(
            out, "^dir0/dir00/file0.txt:line1", flags=TestGrep._reflags
        )

    def test_versioned_file_within_dir_two_levels(self):
        """(versioned) Search for pattern while in nested dir (two levels)."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_dir("dir0/dir1")
        self._mk_versioned_file("dir0/dir1/file0.txt")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "-r", "last:1", ".ine1"])
        self.assertContainsRe(out, "^dir1/file0.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--from-root", "l.ne1"])
        self.assertContainsRe(
            out, "^dir0/dir1/file0.txt~.:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "-r", "last:1", "--no-recursive", "line1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "lin.1"])
        self.assertContainsRe(out, "^dir1/file0.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--from-root", "line1"])
        self.assertContainsRe(
            out, "^dir0/dir1/file0.txt~.:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "-r", "last:1", "--no-recursive", "line1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

    def test_wtree_file_within_dir_two_levels(self):
        """(wtree) Search for pattern while in nested dir (two levels)."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_dir("dir0/dir1")
        self._mk_versioned_file("dir0/dir1/file0.txt")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "l[hij]ne1"])
        self.assertContainsRe(out, "^dir1/file0.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "--from-root", "l.ne1"])
        self.assertContainsRe(
            out, "^dir0/dir1/file0.txt:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "--no-recursive", "lin.1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "line1"])
        self.assertContainsRe(out, "^dir1/file0.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "--from-root", "line1"])
        self.assertContainsRe(
            out, "^dir0/dir1/file0.txt:line1", flags=TestGrep._reflags
        )

        out, err = self.run_bzr(["grep", "--no-recursive", "line1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

    def test_versioned_ignore_case_no_match(self):
        """(versioned) Match fails without --ignore-case."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(["grep", "-r", "last:1", "LinE1", "file0.txt"])
        self.assertNotContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "Li.E1", "file0.txt"])
        self.assertNotContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)

    def test_wtree_ignore_case_no_match(self):
        """(wtree) Match fails without --ignore-case."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(["grep", "LinE1", "file0.txt"])
        self.assertNotContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", ".inE1", "file0.txt"])
        self.assertNotContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)

    def test_versioned_ignore_case_match(self):
        """(versioned) Match fails without --ignore-case."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(["grep", "-r", "last:1", "-i", "Li.E1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "-i", "LinE1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--ignore-case", "LinE1", "file0.txt"]
        )
        self.assertContainsRe(out, "^file0.txt~.:line1", flags=TestGrep._reflags)

    def test_wtree_ignore_case_match(self):
        """(wtree) Match fails without --ignore-case."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(["grep", "-i", "LinE1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "--ignore-case", "LinE1", "file0.txt"])
        self.assertContainsRe(out, "^file0.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "--ignore-case", "Li.E1", "file0.txt"])
        self.assertContainsRe(out, "^file0.txt:line1", flags=TestGrep._reflags)

    def test_versioned_from_root_fail(self):
        """(versioned) Match should fail without --from-root."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")
        self._mk_versioned_dir("dir0")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "-r", "last:1", "li.e1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "line1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

    def test_wtree_from_root_fail(self):
        """(wtree) Match should fail without --from-root."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")
        self._mk_versioned_dir("dir0")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "line1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "li.e1"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

    def test_versioned_from_root_pass(self):
        """(versioned) Match pass with --from-root."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")
        self._mk_versioned_dir("dir0")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "-r", "last:1", "--from-root", "l.ne1"])
        self.assertContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "--from-root", "line1"])
        self.assertContainsRe(out, "file0.txt~.:line1", flags=TestGrep._reflags)

    def test_wtree_from_root_pass(self):
        """(wtree) Match pass with --from-root."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")
        self._mk_versioned_dir("dir0")
        os.chdir("dir0")

        out, err = self.run_bzr(["grep", "--from-root", "lin.1"])
        self.assertContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "--from-root", "line1"])
        self.assertContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)

    def test_versioned_with_line_number(self):
        """(versioned) Search for pattern with --line-number."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--line-number", "li.e3", "file0.txt"]
        )
        self.assertContainsRe(out, "file0.txt~.:3:line3", flags=TestGrep._reflags)

        out, err = self.run_bzr(
            ["grep", "-r", "last:1", "--line-number", "line3", "file0.txt"]
        )
        self.assertContainsRe(out, "file0.txt~.:3:line3", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "last:1", "-n", "line1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt~.:1:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-n", "line[0-9]", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:3:line3", flags=TestGrep._reflags)

    def test_wtree_with_line_number(self):
        """(wtree) Search for pattern with --line-number."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.txt")

        out, err = self.run_bzr(["grep", "--line-number", "line3", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:3:line3", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-n", "line1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:1:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-n", "[hjkl]ine1", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:1:line1", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-n", "line[0-9]", "file0.txt"])
        self.assertContainsRe(out, "file0.txt:3:line3", flags=TestGrep._reflags)

    def test_revno_basic_history_grep_file(self):
        """Search for pattern in specific revision number in a file."""
        wd = "foobar0"
        fname = "file0.txt"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file(fname, total_lines=0)
        self._update_file(fname, text="v2 text\n")
        self._update_file(fname, text="v3 text\n")
        self._update_file(fname, text="v4 text\n")

        # rev 2 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "2", "v3", fname])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "3", "v3", fname])
        self.assertContainsRe(out, "file0.txt~3:v3.*", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3' with line number
        out, err = self.run_bzr(["grep", "-r", "3", "-n", "v3", fname])
        self.assertContainsRe(out, "file0.txt~3:2:v3.*", flags=TestGrep._reflags)

        # rev 2 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "2", "[tuv]3", fname])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "3", "[tuv]3", fname])
        self.assertContainsRe(out, "file0.txt~3:v3.*", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3' with line number
        out, err = self.run_bzr(["grep", "-r", "3", "-n", "[tuv]3", fname])
        self.assertContainsRe(out, "file0.txt~3:2:v3.*", flags=TestGrep._reflags)

    def test_revno_basic_history_grep_full(self):
        """Search for pattern in specific revision number in a file."""
        wd = "foobar0"
        fname = "file0.txt"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file(fname, total_lines=0)  # rev1
        self._mk_versioned_file("file1.txt")  # rev2
        self._update_file(fname, text="v3 text\n")  # rev3
        self._update_file(fname, text="v4 text\n")  # rev4
        self._update_file(fname, text="v5 text\n")  # rev5

        # rev 2 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "2", "v3"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "3", "v3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3' with line number
        out, err = self.run_bzr(["grep", "-r", "3", "-n", "v3"])
        self.assertContainsRe(out, "file0.txt~3:1:v3", flags=TestGrep._reflags)

        # rev 2 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "2", "[tuv]3"])
        self.assertNotContainsRe(out, "file0.txt", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3'
        out, err = self.run_bzr(["grep", "-r", "3", "[tuv]3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)

        # rev 3 should not have text 'v3' with line number
        out, err = self.run_bzr(["grep", "-r", "3", "-n", "[tuv]3"])
        self.assertContainsRe(out, "file0.txt~3:1:v3", flags=TestGrep._reflags)

    def test_revno_versioned_file_in_dir(self):
        """Grep specific version of file withing dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")  # rev1
        self._mk_versioned_file("dir0/file0.txt")  # rev2
        self._update_file("dir0/file0.txt", "v3 text\n")  # rev3
        self._update_file("dir0/file0.txt", "v4 text\n")  # rev4
        self._update_file("dir0/file0.txt", "v5 text\n")  # rev5

        # v4 should not be present in revno 3
        out, err = self.run_bzr(["grep", "-r", "last:3", "v4"])
        self.assertNotContainsRe(out, "^dir0/file0.txt", flags=TestGrep._reflags)

        # v4 should be present in revno 4
        out, err = self.run_bzr(["grep", "-r", "last:2", "v4"])
        self.assertContainsRe(out, "^dir0/file0.txt~4:v4", flags=TestGrep._reflags)

        # v4 should not be present in revno 3
        out, err = self.run_bzr(["grep", "-r", "last:3", "[tuv]4"])
        self.assertNotContainsRe(out, "^dir0/file0.txt", flags=TestGrep._reflags)

        # v4 should be present in revno 4
        out, err = self.run_bzr(["grep", "-r", "last:2", "[tuv]4"])
        self.assertContainsRe(out, "^dir0/file0.txt~4:v4", flags=TestGrep._reflags)

    def test_revno_range_basic_history_grep(self):
        """Search for pattern in revision range for file."""
        wd = "foobar0"
        fname = "file0.txt"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file(fname, total_lines=0)  # rev1
        self._mk_versioned_file("file1.txt")  # rev2
        self._update_file(fname, text="v3 text\n")  # rev3
        self._update_file(fname, text="v4 text\n")  # rev4
        self._update_file(fname, text="v5 text\n")  # rev5
        self._update_file(fname, text="v6 text\n")  # rev6

        out, err = self.run_bzr(["grep", "-r", "1..", "v3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "..1", "v3"])
        # searching only rev1 gives nothing
        self.assertEqual(len(out.splitlines()), 0)

        out, err = self.run_bzr(["grep", "-r", "..6", "v3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "..", "v3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "1..5", "v3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        out, err = self.run_bzr(["grep", "-r", "5..1", "v3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        out, err = self.run_bzr(["grep", "-r", "1..", "[tuv]3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "1..5", "[tuv]3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        out, err = self.run_bzr(["grep", "-r", "5..1", "[tuv]3"])
        self.assertContainsRe(out, "file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

    def test_revno_range_versioned_file_in_dir(self):
        """Grep rev-range for pattern for file withing a dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")  # rev1
        self._mk_versioned_file("dir0/file0.txt")  # rev2
        self._update_file("dir0/file0.txt", "v3 text\n")  # rev3
        self._update_file("dir0/file0.txt", "v4 text\n")  # rev4
        self._update_file("dir0/file0.txt", "v5 text\n")  # rev5
        self._update_file("dir0/file0.txt", "v6 text\n")  # rev6

        out, err = self.run_bzr(["grep", "-r", "2..5", "v3"])
        self.assertContainsRe(out, "^dir0/file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "^dir0/file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        out, err = self.run_bzr(["grep", "-r", "2..5", "[tuv]3"])
        self.assertContainsRe(out, "^dir0/file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "^dir0/file0.txt~6:v3", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

    def test_revno_range_versioned_file_from_outside_dir(self):
        """Grep rev-range for pattern from outside dir."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")  # rev1
        self._mk_versioned_file("dir0/file0.txt")  # rev2
        self._update_file("dir0/file0.txt", "v3 text\n")  # rev3
        self._update_file("dir0/file0.txt", "v4 text\n")  # rev4
        self._update_file("dir0/file0.txt", "v5 text\n")  # rev5
        self._update_file("dir0/file0.txt", "v6 text\n")  # rev6

        out, err = self.run_bzr(["grep", "-r", "2..5", "v3", "dir0"])
        self.assertContainsRe(out, "^dir0/file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "^dir0/file0.txt~6:v3", flags=TestGrep._reflags)

        out, err = self.run_bzr(["grep", "-r", "2..5", "[tuv]3", "dir0"])
        self.assertContainsRe(out, "^dir0/file0.txt~3:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~4:v3", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file0.txt~5:v3", flags=TestGrep._reflags)
        self.assertNotContainsRe(out, "^dir0/file0.txt~6:v3", flags=TestGrep._reflags)

    def test_levels(self):
        """--levels=0 should show findings from merged revision."""
        wd0 = "foobar0"
        wd1 = "foobar1"

        self.make_branch_and_tree(wd0)
        os.chdir(wd0)
        self._mk_versioned_file("file0.txt")
        os.chdir("..")

        out, err = self.run_bzr(["branch", wd0, wd1])
        os.chdir(wd1)
        self._mk_versioned_file("file1.txt")
        os.chdir(osutils.pathjoin("..", wd0))

        out, err = self.run_bzr(["merge", osutils.pathjoin("..", wd1)])
        out, err = self.run_bzr(["ci", "-m", "merged"])

        out, err = self.run_bzr(["grep", "line1"])
        self.assertContainsRe(out, "file0.txt:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt:line1", flags=TestGrep._reflags)

        # levels should be ignored by wtree grep
        out, err = self.run_bzr(["grep", "--levels=0", "line1"])
        self.assertContainsRe(out, "^file0.txt:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt:line10$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "last:1..", "--levels=0", "line1"])
        self.assertContainsRe(out, "^file0.txt~2:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~2:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~1.1.1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~1.1.1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~2:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~2:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~1.1.1:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~1.1.1:line10$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 8)

        out, err = self.run_bzr(["grep", "-r", "-1..", "-n", "--levels=0", "line1"])
        self.assertContainsRe(out, "^file0.txt~2:1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~2:1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~1.1.1:1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~1.1.1:1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~2:10:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~2:10:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(
            out, "^file0.txt~1.1.1:10:line10$", flags=TestGrep._reflags
        )
        self.assertContainsRe(
            out, "^file1.txt~1.1.1:10:line10$", flags=TestGrep._reflags
        )
        self.assertEqual(len(out.splitlines()), 8)

        # levels should be ignored by wtree grep
        out, err = self.run_bzr(["grep", "--levels=0", "l.ne1"])
        self.assertContainsRe(out, "^file0.txt:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt:line10$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 4)

        out, err = self.run_bzr(["grep", "-r", "last:1..", "--levels=0", "lin.1"])
        self.assertContainsRe(out, "^file0.txt~2:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~2:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~1.1.1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~1.1.1:line1$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~2:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~2:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~1.1.1:line10$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~1.1.1:line10$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 8)

        out, err = self.run_bzr(["grep", "-r", "-1..", "-n", "--levels=0", ".ine1"])
        self.assertContainsRe(out, "file0.txt~2:1:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~2:1:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file0.txt~1.1.1:1:line1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~1.1.1:1:line1", flags=TestGrep._reflags)

    def test_dotted_rev_grep(self):
        """Grep in dotted revs"""
        wd0 = "foobar0"
        wd1 = "foobar1"

        self.make_branch_and_tree(wd0)
        os.chdir(wd0)
        self._mk_versioned_file("file0.txt")
        os.chdir("..")

        out, err = self.run_bzr(["branch", wd0, wd1])
        os.chdir(wd1)
        self._mk_versioned_file("file1.txt")  # revno 1.1.1
        self._update_file("file1.txt", "text 0\n")  # revno 1.1.2
        self._update_file("file1.txt", "text 1\n")  # revno 1.1.3
        self._update_file("file1.txt", "text 2\n")  # revno 1.1.4
        os.chdir(osutils.pathjoin("..", wd0))

        out, err = self.run_bzr(["merge", osutils.pathjoin("..", wd1)])
        out, err = self.run_bzr(["ci", "-m", "merged"])

        out, err = self.run_bzr(["grep", "-r", "1.1.1..1.1.4", "text"])
        self.assertContainsRe(out, "file1.txt~1.1.2:text 0", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~1.1.3:text 1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~1.1.3:text 1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~1.1.4:text 0", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~1.1.4:text 1", flags=TestGrep._reflags)
        self.assertContainsRe(out, "file1.txt~1.1.4:text 2", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 6)

    def test_versioned_binary_file_grep(self):
        """(versioned) Grep for pattern in binary file."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file.txt")
        self._mk_versioned_file("file0.bin")
        self._update_file("file0.bin", "\x00lineNN\x00\n")

        # note: set --verbose/-v flag to get the skip message.
        out, err = self.run_bzr(["grep", "-v", "-r", "last:1", "lineNN", "file0.bin"])
        self.assertNotContainsRe(out, "file0.bin", flags=TestGrep._reflags)
        self.assertContainsRe(
            err, "Binary file.*file0.bin.*skipped", flags=TestGrep._reflags
        )
        self.assertEqual(len(out.splitlines()), 0)
        self.assertEqual(len(err.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-v", "-r", "last:1", "line.N", "file0.bin"])
        self.assertNotContainsRe(out, "file0.bin", flags=TestGrep._reflags)
        self.assertContainsRe(
            err, "Binary file.*file0.bin.*skipped", flags=TestGrep._reflags
        )
        self.assertEqual(len(out.splitlines()), 0)
        self.assertEqual(len(err.splitlines()), 1)

    def test_wtree_binary_file_grep(self):
        """(wtree) Grep for pattern in binary file."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file("file0.bin")
        self._update_file("file0.bin", "\x00lineNN\x00\n")

        # note: set --verbose/-v flag to get the skip message.
        out, err = self.run_bzr(["grep", "-v", "lineNN", "file0.bin"])
        self.assertNotContainsRe(out, "file0.bin:line1", flags=TestGrep._reflags)
        self.assertContainsRe(
            err, "Binary file.*file0.bin.*skipped", flags=TestGrep._reflags
        )

        # binary warning should not be shown without --verbose
        out, err = self.run_bzr(["grep", "lineNN", "file0.bin"])
        self.assertNotContainsRe(out, "file0.bin:line1", flags=TestGrep._reflags)
        self.assertNotContainsRe(err, "Binary file", flags=TestGrep._reflags)

    def test_revspec(self):
        """Ensure various revspecs work"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir("dir0")  # rev1
        self._mk_versioned_file("dir0/file0.txt")  # rev2
        self._update_file("dir0/file0.txt", "v3 text\n")  # rev3
        self._update_file("dir0/file0.txt", "v4 text\n")  # rev4
        self._update_file("dir0/file0.txt", "v5 text\n")  # rev5

        out, err = self.run_bzr(["grep", "-r", "revno:1..2", "v3"])
        self.assertNotContainsRe(out, "file0", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

        out, err = self.run_bzr(["grep", "-r", "revno:4..", "v4"])
        self.assertContainsRe(out, "^dir0/file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)  # find v4 in rev4 and rev5

        out, err = self.run_bzr(["grep", "-r", "..revno:3", "v4"])
        self.assertNotContainsRe(out, "file0", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 0)

        out, err = self.run_bzr(["grep", "-r", "..revno:3", "v3"])
        self.assertContainsRe(out, "^dir0/file0.txt", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

    def test_wtree_files_with_matches(self):
        """(wtree) Ensure --files-with-matches, -l works"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_file("file0.txt", total_lines=2)
        self._mk_versioned_file("file1.txt", total_lines=2)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file00.txt", total_lines=2)
        self._mk_versioned_file("dir0/file01.txt", total_lines=2)

        self._update_file("file0.txt", "HELLO\n", checkin=False)
        self._update_file("dir0/file00.txt", "HELLO\n", checkin=False)

        # fixed-string
        out, err = self.run_bzr(["grep", "--files-with-matches", "HELLO"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "--files-with-matches", "HE.LO"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-l", "HELLO"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-l", "HE.LO"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-l", "HELLO", "dir0", "file1.txt"])

        self.assertContainsRe(out, "^dir0/file00.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "-l", ".ELLO", "dir0", "file1.txt"])

        self.assertContainsRe(out, "^dir0/file00.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # fixed-string
        out, err = self.run_bzr(["grep", "-l", "HELLO", "file0.txt"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "-l", ".ELLO", "file0.txt"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # fixed-string
        out, err = self.run_bzr(["grep", "--no-recursive", "-l", "HELLO"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "--no-recursive", "-l", ".ELLO"])

        self.assertContainsRe(out, "^file0.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

    def test_ver_files_with_matches(self):
        """(ver) Ensure --files-with-matches, -l works"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_file("file0.txt", total_lines=2)  # rev 1
        self._mk_versioned_file("file1.txt", total_lines=2)  # rev 2
        self._mk_versioned_dir("dir0")  # rev 3
        self._mk_versioned_file("dir0/file00.txt", total_lines=2)  # rev 4
        self._mk_versioned_file("dir0/file01.txt", total_lines=2)  # rev 5

        self._update_file("file0.txt", "HELLO\n")  # rev 6
        self._update_file("dir0/file00.txt", "HELLO\n")  # rev 7

        # fixed-string
        out, err = self.run_bzr(["grep", "-r", "-1", "--files-with-matches", "HELLO"])

        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-r", "-1", "--files-with-matches", "H.LLO"])

        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-r", "6..7", "--files-with-matches", "HELLO"])

        self.assertContainsRe(out, "^file0.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        # regex
        out, err = self.run_bzr(["grep", "-r", "6..7", "--files-with-matches", "H.LLO"])

        self.assertContainsRe(out, "^file0.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 3)

        # fixed-string
        out, err = self.run_bzr(["grep", "-r", "-1", "-l", "HELLO"])

        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-r", "-1", "-l", "H.LLO"])

        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(
            ["grep", "-l", "HELLO", "-r", "-1", "dir0", "file1.txt"]
        )

        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(
            ["grep", "-l", "H.LLO", "-r", "-1", "dir0", "file1.txt"]
        )

        self.assertContainsRe(out, "^dir0/file00.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # fixed-string
        out, err = self.run_bzr(["grep", "-l", "HELLO", "-r", "-2", "file0.txt"])

        self.assertContainsRe(out, "^file0.txt~6$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "-l", "HE.LO", "-r", "-2", "file0.txt"])

        self.assertContainsRe(out, "^file0.txt~6$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # fixed-string
        out, err = self.run_bzr(["grep", "--no-recursive", "-r", "-1", "-l", "HELLO"])

        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "--no-recursive", "-r", "-1", "-l", ".ELLO"])

        self.assertContainsRe(out, "^file0.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

    def test_wtree_files_without_matches(self):
        """(wtree) Ensure --files-without-match, -L works"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_file("file0.txt", total_lines=2)
        self._mk_versioned_file("file1.txt", total_lines=2)
        self._mk_versioned_dir("dir0")
        self._mk_versioned_file("dir0/file00.txt", total_lines=2)
        self._mk_versioned_file("dir0/file01.txt", total_lines=2)

        self._update_file("file0.txt", "HELLO\n", checkin=False)
        self._update_file("dir0/file00.txt", "HELLO\n", checkin=False)

        # fixed-string
        out, err = self.run_bzr(["grep", "--files-without-match", "HELLO"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "--files-without-match", "HE.LO"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-L", "HELLO"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-L", "HE.LO"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-L", "HELLO", "dir0", "file1.txt"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-L", ".ELLO", "dir0", "file1.txt"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-L", "HELLO", "file1.txt"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "-L", ".ELLO", "file1.txt"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # fixed-string
        out, err = self.run_bzr(["grep", "--no-recursive", "-L", "HELLO"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "--no-recursive", "-L", ".ELLO"])

        self.assertContainsRe(out, "^file1.txt$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

    def test_ver_files_without_matches(self):
        """(ver) Ensure --files-without-match, -L works"""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_file("file0.txt", total_lines=2)  # rev 1
        self._mk_versioned_file("file1.txt", total_lines=2)  # rev 2
        self._mk_versioned_dir("dir0")  # rev 3
        self._mk_versioned_file("dir0/file00.txt", total_lines=2)  # rev 4
        self._mk_versioned_file("dir0/file01.txt", total_lines=2)  # rev 5

        self._update_file("file0.txt", "HELLO\n")  # rev 6
        self._update_file("dir0/file00.txt", "HELLO\n")  # rev 7

        # fixed-string
        out, err = self.run_bzr(["grep", "-r", "-1", "--files-without-match", "HELLO"])

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-r", "-1", "--files-without-match", "H.LLO"])

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(
            ["grep", "-r", "6..7", "--files-without-match", "HELLO"]
        )

        self.assertContainsRe(out, "^file1.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 5)

        # regex
        out, err = self.run_bzr(
            ["grep", "-r", "6..7", "--files-without-match", "H.LLO"]
        )

        self.assertContainsRe(out, "^file1.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file00.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~6$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 5)

        # fixed-string
        out, err = self.run_bzr(["grep", "-r", "-1", "-L", "HELLO"])

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(["grep", "-r", "-1", "-L", "H.LLO"])

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(
            ["grep", "-L", "HELLO", "-r", "-1", "dir0", "file1.txt"]
        )

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # regex
        out, err = self.run_bzr(
            ["grep", "-L", "H.LLO", "-r", "-1", "dir0", "file1.txt"]
        )

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertContainsRe(out, "^dir0/file01.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)

        # fixed-string
        out, err = self.run_bzr(["grep", "-L", "HELLO", "-r", "-2", "file1.txt"])

        self.assertContainsRe(out, "^file1.txt~6$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "-L", "HE.LO", "-r", "-2", "file1.txt"])

        self.assertContainsRe(out, "^file1.txt~6$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # fixed-string
        out, err = self.run_bzr(["grep", "--no-recursive", "-r", "-1", "-L", "HELLO"])

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

        # regex
        out, err = self.run_bzr(["grep", "--no-recursive", "-r", "-1", "-L", ".ELLO"])

        self.assertContainsRe(out, "^file1.txt~7$", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 1)

    def test_no_tree(self):
        """Ensure grep works without working tree."""
        wd0 = "foobar0"
        wd1 = "foobar1"
        self.make_branch_and_tree(wd0)
        os.chdir(wd0)
        self._mk_versioned_file("file0.txt")
        os.chdir("..")
        out, err = self.run_bzr(["branch", "--no-tree", wd0, wd1])
        os.chdir(wd1)

        out, err = self.run_bzr(["grep", "line1"], 3)
        self.assertContainsRe(
            err, "Cannot search working tree", flags=TestGrep._reflags
        )
        self.assertEqual(out, "")

        out, err = self.run_bzr(["grep", "-r", "1", "line1"])
        self.assertContainsRe(out, "file0.txt~1:line1", flags=TestGrep._reflags)
        self.assertEqual(len(out.splitlines()), 2)  # finds line1 and line10


class TestNonAscii(GrepTestBase):
    """Tests for non-ascii filenames and file contents"""

    _test_needs_features = [UnicodeFilenameFeature]

    def test_unicode_only_file(self):
        """Test filename and contents that requires a unicode encoding"""
        tree = self.make_branch_and_tree(".")
        contents = ["\u1234"]
        self.build_tree(contents)
        tree.add(contents)
        tree.commit("Initial commit")
        as_utf8 = "\u1234"

        # GZ 2010-06-07: Note we can't actually grep for \u1234 as the pattern
        #                is mangled according to the user encoding.
        streams = self.run_bzr_raw(
            ["grep", "--files-with-matches", "contents"], encoding="UTF-8"
        )
        as_utf8 = as_utf8.encode("UTF-8")
        self.assertEqual(streams, (as_utf8 + b"\n", b""))

        streams = self.run_bzr_raw(
            ["grep", "-r", "1", "--files-with-matches", "contents"], encoding="UTF-8"
        )
        self.assertEqual(streams, (as_utf8 + b"~1\n", b""))

        fileencoding = osutils.get_user_encoding()
        as_mangled = as_utf8.decode(fileencoding, "replace").encode("UTF-8")

        streams = self.run_bzr_raw(["grep", "-n", "contents"], encoding="UTF-8")
        self.assertEqual(
            streams, (b"%s:1:contents of %s\n" % (as_utf8, as_mangled), b"")
        )

        streams = self.run_bzr_raw(
            ["grep", "-n", "-r", "1", "contents"], encoding="UTF-8"
        )
        self.assertEqual(
            streams, (b"%s~1:1:contents of %s\n" % (as_utf8, as_mangled), b"")
        )


class TestColorGrep(GrepTestBase):
    """Tests for the --color option."""

    _rev_sep = color_string("~", fg=FG.BOLD_YELLOW)
    _sep = color_string(":", fg=FG.BOLD_CYAN)

    def test_color_option(self):
        """Ensure options for color are valid."""
        out, err = self.run_bzr(["grep", "--color", "foo", "bar"], 3)
        self.assertEqual(out, "")
        self.assertContainsRe(
            err, "Valid values for --color are", flags=TestGrep._reflags
        )

    def test_ver_matching_files(self):
        """(versioned) Search for matches or no matches only"""
        tree = self.make_branch_and_tree(".")
        contents = ["d/", "d/aaa", "bbb"]
        self.build_tree(contents)
        tree.add(contents)
        tree.commit("Initial commit")

        # GZ 2010-06-05: Maybe modify the working tree here

        streams = self.run_bzr(
            ["grep", "--color", "always", "-r", "1", "--files-with-matches", "aaa"]
        )
        self.assertEqual(
            streams, ("".join([FG.MAGENTA, "d/aaa", self._rev_sep, "1", "\n"]), "")
        )

        streams = self.run_bzr(
            ["grep", "--color", "always", "-r", "1", "--files-without-match", "aaa"]
        )
        self.assertEqual(
            streams, ("".join([FG.MAGENTA, "bbb", self._rev_sep, "1", "\n"]), "")
        )

    def test_wtree_matching_files(self):
        """(wtree) Search for matches or no matches only"""
        tree = self.make_branch_and_tree(".")
        contents = ["d/", "d/aaa", "bbb"]
        self.build_tree(contents)
        tree.add(contents)
        tree.commit("Initial commit")

        # GZ 2010-06-05: Maybe modify the working tree here

        streams = self.run_bzr(
            ["grep", "--color", "always", "--files-with-matches", "aaa"]
        )
        self.assertEqual(streams, ("".join([FG.MAGENTA, "d/aaa", FG.NONE, "\n"]), ""))

        streams = self.run_bzr(
            ["grep", "--color", "always", "--files-without-match", "aaa"]
        )
        self.assertEqual(streams, ("".join([FG.MAGENTA, "bbb", FG.NONE, "\n"]), ""))

    def test_ver_basic_file(self):
        """(versioned) Search for pattern in specfic file."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        lp = "foo is foobar"
        self._mk_versioned_file("file0.txt", line_prefix=lp, total_lines=1)

        # prepare colored result
        foo = color_string("foo", fg=FG.BOLD_RED)
        res = (
            FG.MAGENTA
            + "file0.txt"
            + self._rev_sep
            + "1"
            + self._sep
            + foo
            + " is "
            + foo
            + "bar1"
            + "\n"
        )
        txt_res = "file0.txt~1:foo is foobar1\n"

        nres = (
            FG.MAGENTA
            + "file0.txt"
            + self._rev_sep
            + "1"
            + self._sep
            + "1"
            + self._sep
            + foo
            + " is "
            + foo
            + "bar1"
            + "\n"
        )

        out, err = self.run_bzr(["grep", "--color", "always", "-r", "1", "foo"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        # auto should produce plain text result
        # as stdout is redireched here.
        out, err = self.run_bzr(["grep", "--color", "auto", "-r", "1", "foo"])
        self.assertEqual(out, txt_res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-i", "--color", "always", "-r", "1", "FOO"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "--color", "always", "-r", "1", "f.o"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-i", "--color", "always", "-r", "1", "F.O"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-n", "--color", "always", "-r", "1", "foo"])
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(
            ["grep", "-n", "-i", "--color", "always", "-r", "1", "FOO"]
        )
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-n", "--color", "always", "-r", "1", "f.o"])
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(
            ["grep", "-n", "-i", "--color", "always", "-r", "1", "F.O"]
        )
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

    def test_wtree_basic_file(self):
        """(wtree) Search for pattern in specfic file."""
        wd = "foobar0"
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        lp = "foo is foobar"
        self._mk_versioned_file("file0.txt", line_prefix=lp, total_lines=1)

        # prepare colored result
        foo = color_string("foo", fg=FG.BOLD_RED)
        res = FG.MAGENTA + "file0.txt" + self._sep + foo + " is " + foo + "bar1" + "\n"

        nres = (
            FG.MAGENTA
            + "file0.txt"
            + self._sep
            + "1"
            + self._sep
            + foo
            + " is "
            + foo
            + "bar1"
            + "\n"
        )

        out, err = self.run_bzr(["grep", "--color", "always", "foo"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-i", "--color", "always", "FOO"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "--color", "always", "f.o"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-i", "--color", "always", "F.O"])
        self.assertEqual(out, res)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-n", "--color", "always", "foo"])
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-n", "-i", "--color", "always", "FOO"])
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-n", "--color", "always", "f.o"])
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)

        out, err = self.run_bzr(["grep", "-n", "-i", "--color", "always", "F.O"])
        self.assertEqual(out, nres)
        self.assertEqual(len(out.splitlines()), 1)


# copied from breezy.tests.blackbox.test_diff
def subst_dates(string):
    """Replace date strings with constant values."""
    return re.sub(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [-\+]\d{4}",
        "YYYY-MM-DD HH:MM:SS +ZZZZ",
        string,
    )


class TestGrepDiff(tests.TestCaseWithTransport):
    def make_example_branch(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("hello", b"foo\n"), ("goodbye", b"baz\n")])
        tree.add(["hello"])
        tree.commit("setup")
        tree.add(["goodbye"])
        tree.commit("setup")
        return tree

    def test_grep_diff_basic(self):
        """Grep -p basic test."""
        tree = self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        tree.commit("updated hello")
        out, err = self.run_bzr(["grep", "-p", "hello"])
        self.assertEqual(err, "")
        self.assertEqualDiff(
            subst_dates(out),
            """\
=== revno:3 ===
  === modified file 'hello'
    --- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +hello world!
=== revno:1 ===
  === added file 'hello'
    --- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
""",
        )

    def test_grep_diff_revision(self):
        """Grep -p specific revision."""
        tree = self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        tree.commit("updated hello")
        out, err = self.run_bzr(["grep", "-p", "-r", "3", "hello"])
        self.assertEqual(err, "")
        self.assertEqualDiff(
            subst_dates(out),
            """\
=== revno:3 ===
  === modified file 'hello'
    --- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +hello world!
""",
        )

    def test_grep_diff_revision_range(self):
        """Grep -p revision range."""
        tree = self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!1\n")])  # rev 3
        tree.commit("rev3")
        self.build_tree_contents([("blah", b"hello world!2\n")])  # rev 4
        tree.add("blah")
        tree.commit("rev4")
        with open("hello", "a") as f:
            f.write("hello world!3\n")
        # self.build_tree_contents([('hello', 'hello world!3\n')]) # rev 5
        tree.commit("rev5")
        out, err = self.run_bzr(["grep", "-p", "-r", "2..5", "hello"])
        self.assertEqual(err, "")
        self.assertEqualDiff(
            subst_dates(out),
            """\
=== revno:5 ===
  === modified file 'hello'
    --- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +hello world!3
=== revno:4 ===
  === added file 'blah'
    +hello world!2
=== revno:3 ===
  === modified file 'hello'
    --- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +hello world!1
""",
        )

    def test_grep_diff_color(self):
        """Grep -p color test."""
        tree = self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        tree.commit("updated hello")
        out, err = self.run_bzr(
            ["grep", "--diff", "-r", "3", "--color", "always", "hello"]
        )
        self.assertEqual(err, "")
        revno = color_string("=== revno:3 ===", fg=FG.BOLD_BLUE) + "\n"
        filename = (
            color_string("  === modified file 'hello'", fg=FG.BOLD_MAGENTA) + "\n"
        )
        redhello = color_string("hello", fg=FG.BOLD_RED)
        diffstr = """\
    --- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
    +hello world!
"""
        diffstr = diffstr.replace("hello", redhello)
        self.assertEqualDiff(subst_dates(out), revno + filename + diffstr)

    def test_grep_norevs(self):
        """Grep -p with zero revisions."""
        out, err = self.run_bzr(["init"])
        out, err = self.run_bzr(["grep", "--diff", "foo"], 3)
        self.assertEqual(out, "")
        self.assertContainsRe(err, "ERROR:.*revision.* does not exist in branch")

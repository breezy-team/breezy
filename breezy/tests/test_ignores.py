# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for handling of ignore files."""

import os
from io import BytesIO

from .. import bedding, ignores
from . import TestCase, TestCaseInTempDir, TestCaseWithTransport


class TestParseIgnoreFile(TestCase):
    def test_parse_fancy(self):
        ignored = ignores.parse_ignore_file(
            BytesIO(
                b"./rootdir\n"
                b"randomfile*\n"
                b"path/from/ro?t\n"
                b"unicode\xc2\xb5\n"  # u'\xb5'.encode('utf8')
                b"dos\r\n"
                b"\n"  # empty line
                b"#comment\n"
                b" xx \n"  # whitespace
                b"!RE:^\\.z.*\n"
                b"!!./.zcompdump\n"
            )
        )
        self.assertEqual(
            {
                "./rootdir",
                "randomfile*",
                "path/from/ro?t",
                "unicode\xb5",
                "dos",
                " xx ",
                "!RE:^\\.z.*",
                "!!./.zcompdump",
            },
            ignored,
        )

    def test_parse_empty(self):
        ignored = ignores.parse_ignore_file(BytesIO(b""))
        self.assertEqual(set(), ignored)

    def test_parse_non_utf8(self):
        """Lines with non utf 8 characters should be discarded."""
        ignored = ignores.parse_ignore_file(
            BytesIO(b"utf8filename_a\ninvalid utf8\x80\nutf8filename_b\n")
        )
        self.assertEqual(
            {
                "utf8filename_a",
                "utf8filename_b",
            },
            ignored,
        )


class TestUserIgnores(TestCaseInTempDir):
    def test_create_if_missing(self):
        # $HOME should be set to '.'
        ignore_path = bedding.user_ignore_config_path()
        self.assertPathDoesNotExist(ignore_path)
        user_ignores = ignores.get_user_ignores()
        self.assertEqual(set(ignores.USER_DEFAULTS), user_ignores)

        self.assertPathExists(ignore_path)
        with open(ignore_path, "rb") as f:
            entries = ignores.parse_ignore_file(f)
        self.assertEqual(set(ignores.USER_DEFAULTS), entries)

    def test_create_with_intermediate_missing(self):
        # $HOME should be set to '.'
        ignore_path = bedding.user_ignore_config_path()
        self.assertPathDoesNotExist(ignore_path)
        os.mkdir("empty-home")

        config_path = os.path.join(self.test_dir, "empty-home", "foo", ".config")
        self.overrideEnv("BRZ_HOME", config_path)
        self.assertPathDoesNotExist(config_path)

        user_ignores = ignores.get_user_ignores()
        self.assertEqual(set(ignores.USER_DEFAULTS), user_ignores)

        ignore_path = bedding.user_ignore_config_path()
        self.assertPathDoesNotExist(ignore_path)

    def test_use_existing(self):
        patterns = ["*.o", "*.py[co]", "\xe5*"]
        ignores._set_user_ignores(patterns)

        user_ignores = ignores.get_user_ignores()
        self.assertEqual(set(patterns), user_ignores)

    def test_use_empty(self):
        ignores._set_user_ignores([])
        ignore_path = bedding.user_ignore_config_path()
        self.check_file_contents(ignore_path, b"")

        self.assertEqual(set(), ignores.get_user_ignores())

    def test_set(self):
        patterns = ["*.py[co]", "*.py[oc]"]
        ignores._set_user_ignores(patterns)

        self.assertEqual(set(patterns), ignores.get_user_ignores())

        patterns = ["vim", "*.swp"]
        ignores._set_user_ignores(patterns)
        self.assertEqual(set(patterns), ignores.get_user_ignores())

    def test_add(self):
        """Test that adding will not duplicate ignores."""
        # Create an empty file
        ignores._set_user_ignores([])

        patterns = ["foo", "./bar", "b\xe5z"]
        added = ignores.add_unique_user_ignores(patterns)
        self.assertEqual(patterns, added)
        self.assertEqual(set(patterns), ignores.get_user_ignores())

    def test_add_directory(self):
        """Test that adding a directory will strip any trailing slash."""
        # Create an empty file
        ignores._set_user_ignores([])

        in_patterns = ["foo/", "bar/", "baz\\"]
        added = ignores.add_unique_user_ignores(in_patterns)
        out_patterns = [x.rstrip("/\\") for x in in_patterns]
        self.assertEqual(out_patterns, added)
        self.assertEqual(set(out_patterns), ignores.get_user_ignores())

    def test_add_unique(self):
        """Test that adding will not duplicate ignores."""
        ignores._set_user_ignores(["foo", "./bar", "b\xe5z", "dir1/", "dir3\\"])

        added = ignores.add_unique_user_ignores(
            ["xxx", "./bar", "xxx", "dir1/", "dir2/", "dir3\\"]
        )
        self.assertEqual(["xxx", "dir2"], added)
        self.assertEqual(
            {"foo", "./bar", "b\xe5z", "xxx", "dir1", "dir2", "dir3"},
            ignores.get_user_ignores(),
        )


class TestRuntimeIgnores(TestCase):
    def setUp(self):
        super().setUp()

        # For the purposes of these tests, we must have no
        # runtime ignores
        self.overrideAttr(ignores, "_runtime_ignores", set())

    def test_add(self):
        """Test that we can add an entry to the list."""
        self.assertEqual(set(), ignores.get_runtime_ignores())

        ignores.add_runtime_ignores(["foo"])
        self.assertEqual({"foo"}, ignores.get_runtime_ignores())

    def test_add_duplicate(self):
        """Adding the same ignore twice shouldn't add a new entry."""
        ignores.add_runtime_ignores(["foo", "bar"])
        self.assertEqual({"foo", "bar"}, ignores.get_runtime_ignores())

        ignores.add_runtime_ignores(["bar"])
        self.assertEqual({"foo", "bar"}, ignores.get_runtime_ignores())


class TestTreeIgnores(TestCaseWithTransport):
    def assertPatternsEquals(self, patterns):
        with open(".bzrignore", "rb") as f:
            contents = f.read().decode("utf-8").splitlines()
        self.assertEqual(sorted(patterns), sorted(contents))

    def test_new_file(self):
        tree = self.make_branch_and_tree(".")
        ignores.tree_ignores_add_patterns(tree, ["myentry"])
        self.assertTrue(tree.has_filename(".bzrignore"))
        self.assertPatternsEquals(["myentry"])

    def test_add_to_existing(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([(".bzrignore", b"myentry1\n")])
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry2", "foo"])
        self.assertPatternsEquals(["myentry1", "myentry2", "foo"])

    def test_adds_ending_newline(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([(".bzrignore", b"myentry1")])
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry2"])
        self.assertPatternsEquals(["myentry1", "myentry2"])
        with open(".bzrignore") as f:
            text = f.read()
        self.assertTrue(text.endswith(("\r\n", "\n", "\r")))

    def test_does_not_add_dupe(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([(".bzrignore", b"myentry\n")])
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry"])
        self.assertPatternsEquals(["myentry"])

    def test_non_ascii(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([(".bzrignore", "myentry\u1234\n".encode())])
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry\u5678"])
        self.assertPatternsEquals(["myentry\u1234", "myentry\u5678"])

    def test_crlf(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([(".bzrignore", b"myentry1\r\n")])
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry2", "foo"])
        with open(".bzrignore", "rb") as f:
            self.assertEqual(f.read(), b"myentry1\r\nmyentry2\r\nfoo\r\n")
        self.assertPatternsEquals(["myentry1", "myentry2", "foo"])

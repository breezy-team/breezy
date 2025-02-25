# Copyright (C) 2006-2010, 2016 Canonical Ltd
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

"""UI tests for brz ignore."""

import os
import re

from breezy import ignores
from breezy.tests import TestCaseWithTransport


class TestCommands(TestCaseWithTransport):
    def test_ignore_absolutes(self):
        """'ignore' with an absolute path returns an error."""
        self.make_branch_and_tree(".")
        self.run_bzr_error(
            ("brz: ERROR: NAME_PATTERN should not be an absolute path\n",),
            "ignore /crud",
        )

    def test_ignore_directories(self):
        """Ignoring a directory should ignore directory tree.

        Also check that trailing slashes on directories are stripped.
        """
        self.run_bzr("init")
        self.build_tree(["dir1/", "dir1/foo", "dir2/", "dir2/bar", "dir3/", "dir3/baz"])
        self.run_bzr(["ignore", "dir1", "dir2/", "dir4\\"])
        self.check_file_contents(".bzrignore", b"dir1\ndir2\ndir4\n")
        self.assertEqual(self.run_bzr("unknowns")[0], "dir3\n")

    def test_ignore_patterns(self):
        tree = self.make_branch_and_tree(".")

        self.assertEqual(list(tree.unknowns()), [])

        # is_ignored() will now create the user global ignore file
        # if it doesn't exist, so make sure we ignore it in our tests
        ignores._set_user_ignores(["*.tmp"])

        self.build_tree_contents([("foo.tmp", b".tmp files are ignored by default")])
        self.assertEqual(list(tree.unknowns()), [])

        self.build_tree_contents([("foo.c", b"int main() {}")])
        self.assertEqual(list(tree.unknowns()), ["foo.c"])

        tree.add("foo.c")
        self.assertEqual(list(tree.unknowns()), [])

        # 'ignore' works when creating the .bzrignore file
        self.build_tree_contents([("foo.blah", b"blah")])
        self.assertEqual(list(tree.unknowns()), ["foo.blah"])
        self.run_bzr("ignore *.blah")
        self.assertEqual(list(tree.unknowns()), [])
        self.check_file_contents(".bzrignore", b"*.blah\n")

        # 'ignore' works when then .bzrignore file already exists
        self.build_tree_contents([("garh", b"garh")])
        self.assertEqual(list(tree.unknowns()), ["garh"])
        self.run_bzr("ignore garh")
        self.assertEqual(list(tree.unknowns()), [])
        self.check_file_contents(".bzrignore", b"*.blah\ngarh\n")

    def test_ignore_multiple_arguments(self):
        """'ignore' works with multiple arguments."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b", "c", "d"])
        self.assertEqual(list(tree.unknowns()), ["a", "b", "c", "d"])
        self.run_bzr("ignore a b c")
        self.assertEqual(list(tree.unknowns()), ["d"])
        self.check_file_contents(".bzrignore", b"a\nb\nc\n")

    def test_ignore_no_arguments(self):
        """'ignore' with no arguments returns an error."""
        self.make_branch_and_tree(".")
        self.run_bzr_error(
            (
                "brz: ERROR: ignore requires at least one "
                "NAME_PATTERN or --default-rules.\n",
            ),
            "ignore",
        )

    def test_ignore_default_rules(self):
        out, err = self.run_bzr(["ignore", "--default-rules"])
        reference_set = set(ignores.USER_DEFAULTS)
        output_set = set(out.rstrip().split("\n"))
        self.assertEqual(reference_set, output_set)
        self.assertEqual("", err)

    def test_ignore_versioned_file(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b"])
        tree.add("a")

        # test a single versioned file
        out, err = self.run_bzr("ignore a")
        self.assertEqual(
            out,
            "Warning: the following files are version controlled"
            " and match your ignore pattern:\na\n"
            "These files will continue to be version controlled"
            " unless you 'brz remove' them.\n",
        )

        # test a single unversioned file
        out, err = self.run_bzr("ignore b")
        self.assertEqual(out, "")

        # test wildcards
        tree.add("b")
        out, err = self.run_bzr("ignore *")
        self.assertEqual(
            out,
            "Warning: the following files are version controlled"
            " and match your ignore pattern:\n.bzrignore\na\nb\n"
            "These files will continue to be version controlled"
            " unless you 'brz remove' them.\n",
        )

    def test_ignored_versioned_file_matching_new_pattern(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b"])
        tree.add(["a", "b"])
        self.run_bzr("ignore *")

        # If only the given pattern is used then only 'b' should match in
        # this case.
        out, err = self.run_bzr("ignore b")
        self.assertEqual(
            out,
            "Warning: the following files are version controlled"
            " and match your ignore pattern:\nb\n"
            "These files will continue to be version controlled"
            " unless you 'brz remove' them.\n",
        )

    def test_ignore_directory(self):
        """Test --directory option."""
        self.make_branch_and_tree("a")
        self.run_bzr(["ignore", "--directory=a", "README"])
        self.check_file_contents("a/.bzrignore", b"README\n")

    def test_ignored_invalid_pattern(self):
        """Ensure graceful handling for invalid ignore pattern.

        Test case for #300062.
        Invalid pattern should show clear error message.
        Invalid pattern should not be added to .bzrignore file.
        """
        self.make_branch_and_tree(".")
        out, err = self.run_bzr(["ignore", "RE:*.cpp", "foo", "RE:["], 3)
        self.assertEqual(out, "")
        self.assertContainsRe(
            err, r"Invalid ignore pattern.*RE:\*\.cpp.*RE:\[", re.DOTALL
        )
        self.assertNotContainsRe(err, "foo", re.DOTALL)
        self.assertFalse(os.path.isfile(".bzrignore"))

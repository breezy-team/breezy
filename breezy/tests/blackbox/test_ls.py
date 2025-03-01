# Copyright (C) 2006-2012 Canonical Ltd
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

"""External tests of 'brz ls'."""

from breezy import ignores, tests


class TestLS(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()

        # Create a simple branch that can be used in testing
        ignores._set_user_ignores(["user-ignore"])

        self.wt = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                (".bzrignore", b"*.pyo\n"),
                ("a", b"hello\n"),
            ]
        )

    def ls_equals(self, value, args=None, recursive=True, working_dir=None):
        command = "ls"
        if args is not None:
            command += " " + args
        if recursive:
            command += " -R"
        out, err = self.run_bzr(command, working_dir=working_dir)
        self.assertEqual("", err)
        self.assertEqualDiff(value, out)

    def test_ls_null_verbose(self):
        # Can't supply both
        self.run_bzr_error(
            ["Cannot set both --verbose and --null"], "ls --verbose --null"
        )

    def test_ls_basic(self):
        """Test the abilities of 'brz ls'."""
        self.ls_equals(".bzrignore\na\n")
        self.ls_equals(".bzrignore\na\n", "./")
        self.ls_equals("?        .bzrignore\n?        a\n", "--verbose")
        self.ls_equals(".bzrignore\na\n", "--unknown")
        self.ls_equals("", "--ignored")
        self.ls_equals("", "--versioned")
        self.ls_equals("", "-V")
        self.ls_equals(".bzrignore\na\n", "--unknown --ignored --versioned")
        self.ls_equals(".bzrignore\na\n", "--unknown --ignored -V")
        self.ls_equals("", "--ignored --versioned")
        self.ls_equals("", "--ignored -V")
        self.ls_equals(".bzrignore\0a\0", "--null")

    def test_ls_added(self):
        self.wt.add(["a"])
        self.ls_equals("?        .bzrignore\nV        a\n", "--verbose")
        self.wt.commit("add")

        self.build_tree(["subdir/"])
        self.ls_equals(
            "?        .bzrignore\nV        a\n?        subdir/\n", "--verbose"
        )
        self.build_tree(["subdir/b"])
        self.wt.add(["subdir/", "subdir/b", ".bzrignore"])
        self.ls_equals(
            "V        .bzrignore\nV        a\nV        subdir/\nV        subdir/b\n",
            "--verbose",
        )

    def test_show_ids(self):
        self.build_tree(["subdir/"])
        self.wt.add(["a", "subdir"], ids=[b"a-id", b"subdir-id"])
        self.ls_equals(
            ".bzrignore                                         \n"
            "a                                                  a-id\n"
            "subdir/                                            subdir-id\n",
            "--show-ids",
        )
        self.ls_equals(
            "?        .bzrignore\n"
            "V        a                                         a-id\n"
            "V        subdir/                                   subdir-id\n",
            "--show-ids --verbose",
        )
        self.ls_equals(
            ".bzrignore\0\0a\0a-id\0subdir\0subdir-id\0", "--show-ids --null"
        )

    def test_ls_no_recursive(self):
        self.build_tree(["subdir/", "subdir/b"])
        self.wt.add(["a", "subdir/", "subdir/b", ".bzrignore"])

        self.ls_equals(".bzrignore\na\nsubdir/\n", recursive=False)

        self.ls_equals(
            "V        .bzrignore\nV        a\nV        subdir/\n",
            "--verbose",
            recursive=False,
        )

        # Check what happens in a sub-directory
        self.ls_equals("b\n", working_dir="subdir")
        self.ls_equals("b\0", "--null", working_dir="subdir")
        self.ls_equals("subdir/b\n", "--from-root", working_dir="subdir")
        self.ls_equals("subdir/b\0", "--from-root --null", working_dir="subdir")
        self.ls_equals(
            "subdir/b\n", "--from-root", recursive=False, working_dir="subdir"
        )

    def test_ls_path(self):
        """If a path is specified, files are listed with that prefix."""
        self.build_tree(["subdir/", "subdir/b"])
        self.wt.add(["subdir", "subdir/b"])
        self.ls_equals("subdir/b\n", "subdir")
        self.ls_equals(
            "../.bzrignore\n../a\n../subdir/\n../subdir/b\n",
            "..",
            working_dir="subdir",
        )
        self.ls_equals(
            "../.bzrignore\0../a\0../subdir\0../subdir/b\0",
            ".. --null",
            working_dir="subdir",
        )
        self.ls_equals(
            "?        ../.bzrignore\n"
            "?        ../a\n"
            "V        ../subdir/\n"
            "V        ../subdir/b\n",
            ".. --verbose",
            working_dir="subdir",
        )
        self.run_bzr_error(
            ["cannot specify both --from-root and PATH"],
            "ls --from-root ..",
            working_dir="subdir",
        )

    def test_ls_revision(self):
        self.wt.add(["a"])
        self.wt.commit("add")

        self.build_tree(["subdir/"])

        # Check what happens when we supply a specific revision
        self.ls_equals("a\n", "--revision 1")
        self.ls_equals("V        a\n", "--verbose --revision 1")

        self.ls_equals("", "--revision 1", working_dir="subdir")

    def test_ls_branch(self):
        """If a branch is specified, files are listed from it."""
        self.build_tree(["subdir/", "subdir/b"])
        self.wt.add(["subdir", "subdir/b"])
        self.wt.commit("committing")
        branch = self.make_branch("branchdir")
        branch.pull(self.wt.branch)
        self.ls_equals("branchdir/subdir/\nbranchdir/subdir/b\n", "branchdir")
        self.ls_equals(
            "branchdir/subdir/\nbranchdir/subdir/b\n", "branchdir --revision 1"
        )

    def test_ls_ignored(self):
        # Now try to do ignored files.
        self.wt.add(["a", ".bzrignore"])

        self.build_tree(["blah.py", "blah.pyo", "user-ignore"])
        self.ls_equals(".bzrignore\na\nblah.py\nblah.pyo\nuser-ignore\n")
        self.ls_equals(
            "V        .bzrignore\n"
            "V        a\n"
            "?        blah.py\n"
            "I        blah.pyo\n"
            "I        user-ignore\n",
            "--verbose",
        )
        self.ls_equals("blah.pyo\nuser-ignore\n", "--ignored")
        self.ls_equals("blah.py\n", "--unknown")
        self.ls_equals(".bzrignore\na\n", "--versioned")
        self.ls_equals(".bzrignore\na\n", "-V")

    def test_kinds(self):
        self.build_tree(["subdir/"])
        self.ls_equals(".bzrignore\na\n", "--kind=file")
        self.ls_equals("subdir/\n", "--kind=directory")
        self.ls_equals("", "--kind=symlink")
        self.run_bzr_error(["invalid kind specified"], "ls --kind=pile")

    def test_ls_path_nonrecursive(self):
        self.ls_equals(
            "{}/.bzrignore\n{}/a\n".format(self.test_dir, self.test_dir),
            self.test_dir,
            recursive=False,
        )

    def test_ls_directory(self):
        """Test --directory option."""
        self.wt = self.make_branch_and_tree("dir")
        self.build_tree(["dir/sub/", "dir/sub/file"])
        self.wt.add(["sub", "sub/file"])
        self.wt.commit("commit")
        self.ls_equals("sub/\nsub/file\n", "--directory=dir")
        self.ls_equals("sub/file\n", "-d dir sub")

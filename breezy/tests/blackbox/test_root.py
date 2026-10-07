# Copyright (C) 2026 Breezy Developers
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

"""Black-box tests for 'brz root', which shows the tree root directory."""

from breezy.tests import TestCaseWithTransport


class TestRoot(TestCaseWithTransport):
    def test_root(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/dir/"])
        out, err = self.run_bzr("root", working_dir="tree/dir")
        self.assertEqual(tree.basedir + "\n", out)
        self.assertEqual("", err)

    def test_root_git(self):
        tree = self.make_branch_and_tree("tree", format="git")
        self.build_tree(["tree/dir/"])
        out, err = self.run_bzr("root", working_dir="tree/dir")
        self.assertEqual(tree.basedir + "\n", out)
        self.assertEqual("", err)

    def test_root_filename(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/dir/", "tree/dir/file"])
        out, err = self.run_bzr(["root", "tree/dir/file"])
        self.assertEqual(tree.basedir + "\n", out)
        self.assertEqual("", err)

    def test_root_not_a_branch(self):
        self.run_bzr_error(["Not a branch"], ["root", "nonexistent"], working_dir="/")

    def test_root_help(self):
        out = self.run_bzr("help root")[0]
        self.assertEqual(
            "Purpose: Show the tree root directory.\n"
            "Usage:   brz root [FILENAME]\n"
            "\n"
            "Options:\n"
            "  -h, --help     Show help message.\n"
            "  -q, --quiet    Only display errors and warnings.\n"
            "  --usage        Show usage message and options.\n"
            "  -v, --verbose  Display more information.\n"
            "\n"
            "Description:\n"
            "  The root is the nearest enclosing directory with a control\n"
            "  directory.\n"
            "\n",
            out,
        )

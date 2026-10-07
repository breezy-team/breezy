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

"""Black-box tests for 'brz relpath', which shows a path relative to the tree root."""

from breezy.tests import TestCaseWithTransport


class TestRelpath(TestCaseWithTransport):
    def test_relpath(self):
        self.make_branch_and_tree("tree")
        self.build_tree(["tree/dir/", "tree/dir/file"])
        out, err = self.run_bzr(["relpath", "tree/dir/file"])
        self.assertEqual("dir/file\n", out)
        self.assertEqual("", err)

    def test_relpath_from_subdir(self):
        self.make_branch_and_tree("tree")
        self.build_tree(["tree/dir/", "tree/dir/file"])
        out, err = self.run_bzr(["relpath", "file"], working_dir="tree/dir")
        self.assertEqual("dir/file\n", out)
        self.assertEqual("", err)

    def test_relpath_git(self):
        self.make_branch_and_tree("tree", format="git")
        self.build_tree(["tree/dir/", "tree/dir/file"])
        out, err = self.run_bzr(["relpath", "tree/dir/file"])
        self.assertEqual("dir/file\n", out)
        self.assertEqual("", err)

    def test_relpath_of_root(self):
        self.make_branch_and_tree("tree")
        out, err = self.run_bzr(["relpath", "tree"])
        self.assertEqual("\n", out)
        self.assertEqual("", err)

    def test_relpath_requires_filename(self):
        self.run_bzr_error(["command 'relpath' requires argument FILENAME"], "relpath")

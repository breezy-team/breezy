# Copyright (C) 2010 Canonical Ltd
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


"""Black-box tests for brz rmbranch."""

from breezy import controldir
from breezy.tests import TestCaseWithTransport


class TestRemoveBranch(TestCaseWithTransport):
    def example_tree(self, path=".", format=None):
        tree = self.make_branch_and_tree(path, format=format)
        self.build_tree_contents([(path + "/hello", b"foo")])
        tree.add("hello")
        tree.commit(message="setup")
        self.build_tree_contents([(path + "/goodbye", b"baz")])
        tree.add("goodbye")
        tree.commit(message="setup")
        return tree

    def test_remove_local(self):
        # Remove a local branch.
        self.example_tree("a")
        self.run_bzr_error(
            ["Branch is active. Use --force to remove it.\n"], "rmbranch a"
        )
        self.run_bzr("rmbranch --force a")
        dir = controldir.ControlDir.open("a")
        self.assertFalse(dir.has_branch())
        self.assertPathExists("a/hello")
        self.assertPathExists("a/goodbye")

    def test_no_branch(self):
        # No branch in the current directory.
        self.make_repository("a")
        self.run_bzr_error(["Not a branch"], "rmbranch a")

    def test_no_tree(self):
        # removing the active branch is possible if there is no tree
        tree = self.example_tree("a")
        tree.controldir.destroy_workingtree()
        self.run_bzr("rmbranch", working_dir="a")
        dir = controldir.ControlDir.open("a")
        self.assertFalse(dir.has_branch())

    def test_no_arg(self):
        # location argument defaults to current directory
        self.example_tree("a")
        self.run_bzr_error(
            ["Branch is active. Use --force to remove it.\n"], "rmbranch a"
        )
        self.run_bzr("rmbranch --force", working_dir="a")
        dir = controldir.ControlDir.open("a")
        self.assertFalse(dir.has_branch())

    def test_remove_colo(self):
        # Remove a colocated branch.
        tree = self.example_tree("a")
        tree.controldir.create_branch(name="otherbranch")
        self.assertTrue(tree.controldir.has_branch("otherbranch"))
        self.run_bzr("rmbranch {},branch=otherbranch".format(tree.controldir.user_url))
        dir = controldir.ControlDir.open("a")
        self.assertFalse(dir.has_branch("otherbranch"))
        self.assertTrue(dir.has_branch())

    def test_remove_colo_directory(self):
        # Remove a colocated branch.
        tree = self.example_tree("a")
        tree.controldir.create_branch(name="otherbranch")
        self.assertTrue(tree.controldir.has_branch("otherbranch"))
        self.run_bzr("rmbranch otherbranch -d {}".format(tree.controldir.user_url))
        dir = controldir.ControlDir.open("a")
        self.assertFalse(dir.has_branch("otherbranch"))
        self.assertTrue(dir.has_branch())

    def test_remove_active_colo_branch(self):
        # Remove a colocated branch.
        dir = self.make_repository("a").controldir
        branch = dir.create_branch("otherbranch")
        branch.create_checkout("a")
        self.run_bzr_error(
            ["Branch is active. Use --force to remove it.\n"],
            "rmbranch otherbranch -d {}".format(branch.controldir.user_url),
        )
        self.assertTrue(dir.has_branch("otherbranch"))
        self.run_bzr("rmbranch --force otherbranch -d {}".format(branch.controldir.user_url))
        self.assertFalse(dir.has_branch("otherbranch"))

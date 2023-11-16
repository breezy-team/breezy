# Copyright (C) 2009 Canonical Ltd
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


from breezy import controldir
from breezy.tests import TestCaseWithTransport


class TestReference(TestCaseWithTransport):
    def get_default_format(self):
        return controldir.format_registry.make_controldir("2a")

    def test_no_args_lists(self):
        tree = self.make_branch_and_tree("branch")
        tree.add_reference(self.make_branch_and_tree("branch/path"))
        tree.add_reference(self.make_branch_and_tree("branch/lath"))
        tree.set_reference_info("path", "http://example.org")
        tree.set_reference_info("lath", "http://example.org/2")
        out, err = self.run_bzr("reference", working_dir="branch")
        lines = out.splitlines()
        self.assertEqual("lath http://example.org/2", lines[0])
        self.assertEqual("path http://example.org", lines[1])

    def make_tree_with_reference(self):
        tree = self.make_branch_and_tree("tree")
        subtree = self.make_branch_and_tree("tree/newpath")
        tree.add_reference(subtree)
        tree.set_reference_info("newpath", "http://example.org")
        tree.commit("add reference")
        return tree

    def test_uses_working_tree_location(self):
        self.make_tree_with_reference()
        out, err = self.run_bzr("reference", working_dir="tree")
        self.assertContainsRe(out, "newpath http://example.org\n")

    def test_uses_basis_tree_location(self):
        tree = self.make_tree_with_reference()
        tree.controldir.destroy_workingtree()
        out, err = self.run_bzr("reference", working_dir="tree")
        self.assertContainsRe(out, "newpath http://example.org\n")

    def test_one_arg_displays(self):
        self.make_tree_with_reference()
        out, err = self.run_bzr("reference newpath", working_dir="tree")
        self.assertEqual("newpath http://example.org\n", out)

    def test_one_arg_uses_containing_tree(self):
        self.make_tree_with_reference()
        out, err = self.run_bzr("reference -d tree newpath")
        self.assertEqual("newpath http://example.org\n", out)

    def test_two_args_sets(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file"])
        tree.add("file")
        out, err = self.run_bzr("reference -d tree file http://example.org")
        location = tree.get_reference_info("file")
        self.assertEqual("http://example.org", location)
        self.assertEqual("", out)
        self.assertEqual("", err)

    def test_missing_file(self):
        self.make_branch_and_tree("tree")
        out, err = self.run_bzr(
            "reference file http://example.org", working_dir="tree", retcode=3
        )
        self.assertEqual("brz: ERROR: file is not versioned.\n", err)

    def test_missing_file_forced(self):
        tree = self.make_branch_and_tree("tree")
        tree.add_reference(self.make_branch_and_tree("tree/file"))
        out, err = self.run_bzr(
            "reference --force-unversioned file http://example.org", working_dir="tree"
        )
        location = tree.get_reference_info("file")
        self.assertEqual("http://example.org", location)
        self.assertEqual("", out)
        self.assertEqual("", err)

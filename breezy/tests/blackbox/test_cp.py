# Copyright (C) 2017 The Breezy Developers
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

"""Test for 'brz mv'"""


from breezy.tests import TestCaseWithTransport


class TestCopy(TestCaseWithTransport):
    def test_cp_unversioned(self):
        self.build_tree(["unversioned.txt"])
        self.run_bzr_error(
            [
                "^brz: ERROR: Could not copy .*unversioned.txt => .*elsewhere."
                " .*unversioned.txt is not versioned\\.$"
            ],
            "cp unversioned.txt elsewhere",
        )

    def test_cp_nonexisting(self):
        self.run_bzr_error(
            [
                "^brz: ERROR: Could not copy .*doesnotexist => .*somewhereelse."
                " .*doesnotexist is not versioned\\.$"
            ],
            "cp doesnotexist somewhereelse",
        )

    def test_cp_unqualified(self):
        self.run_bzr_error(["^brz: ERROR: missing file argument$"], "cp")

    def test_cp_invalid(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["test.txt", "sub1/"])
        tree.add(["test.txt"])

        self.run_bzr_error(
            [
                "^brz: ERROR: Could not copy test.txt => sub1/test.txt: "
                "sub1 is not versioned\\.$"
            ],
            "cp test.txt sub1",
        )

        self.run_bzr_error(
            [
                "^brz: ERROR: Could not copy test.txt => .*hello.txt: "
                "sub1 is not versioned\\.$"
            ],
            "cp test.txt sub1/hello.txt",
        )

    def test_cp_dir(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["hello.txt", "sub1/"])
        tree.add(["hello.txt", "sub1"])

        self.run_bzr_error(
            ["^brz: ERROR: Could not copy sub1 => sub2 . sub1 is a directory\\.$"],
            "cp sub1 sub2",
        )

    def test_cp_file_into(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["sub1/", "sub1/hello.txt", "sub2/"])
        tree.add(["sub1", "sub1/hello.txt", "sub2"])

        self.run_bzr("cp sub1/hello.txt sub2")
        self.assertInWorkingTree("sub1")
        self.assertInWorkingTree("sub1/hello.txt")
        self.assertInWorkingTree("sub2")
        self.assertInWorkingTree("sub2/hello.txt")

    def test_cp_file(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["hello.txt"])
        tree.add(["hello.txt"])

        self.run_bzr("cp hello.txt hallo.txt")
        self.assertInWorkingTree("hello.txt")
        self.assertInWorkingTree("hallo.txt")

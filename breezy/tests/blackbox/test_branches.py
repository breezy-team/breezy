# Copyright (C) 2011, 2012, 2016 Canonical Ltd
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


"""Black-box tests for brz branches."""

from breezy.tests import TestCaseWithTransport

from ...controldir import ControlDir


class TestBranches(TestCaseWithTransport):
    def test_no_colocated_support(self):
        # Listing the branches in a control directory without colocated branch
        # support.
        self.run_bzr("init a")
        out, _err = self.run_bzr("branches a")
        self.assertEqual(out, "* (default)\n")

    def test_no_branch(self):
        # Listing the branches in a control directory without branches.
        self.run_bzr("init-shared-repo a")
        out, _err = self.run_bzr("branches a")
        self.assertEqual(out, "")

    def test_default_current_dir(self):
        # "brz branches" list the branches in the current directory
        # if no location was specified.
        self.run_bzr("init-shared-repo a")
        out, _err = self.run_bzr("branches", working_dir="a")
        self.assertEqual(out, "")

    def test_recursive_current(self):
        self.run_bzr("init .")
        self.assertEqual(".\n", self.run_bzr("branches --recursive")[0])

    def test_recursive(self):
        self.run_bzr("init source")
        self.run_bzr("init source/subsource")
        self.run_bzr("checkout --lightweight source checkout")
        self.run_bzr("init checkout/subcheckout")
        self.run_bzr("init checkout/.bzr/subcheckout")
        out = self.run_bzr("branches --recursive")[0]
        lines = out.split("\n")
        self.assertIs(True, "source" in lines, lines)
        self.assertIs(True, "source/subsource" in lines, lines)
        self.assertIs(True, "checkout/subcheckout" in lines, lines)
        self.assertIs(True, "checkout" not in lines, lines)

    def test_indicates_non_branch(self):
        t = self.make_branch_and_tree("a", format="development-colo")
        t.controldir.create_branch(name="another")
        t.controldir.create_branch(name="colocated")
        out, _err = self.run_bzr("branches a")
        self.assertEqual(out, "* (default)\n  another\n  colocated\n")

    def test_indicates_branch(self):
        t = self.make_repository("a", format="development-colo")
        t.controldir.create_branch(name="another")
        branch = t.controldir.create_branch(name="colocated")
        t.controldir.set_branch_reference(target_branch=branch)
        out, _err = self.run_bzr("branches a")
        self.assertEqual(out, "  another\n* colocated\n")

    def test_shared_repos(self):
        self.make_repository("a", shared=True)
        ControlDir.create_branch_convenience("a/branch1")
        b = ControlDir.create_branch_convenience("a/branch2")
        b.create_checkout(lightweight=True, to_location="b")
        out, _err = self.run_bzr("branches b")
        self.assertEqual(out, "  branch1\n* branch2\n")

    def test_standalone_branch(self):
        self.make_branch("a")
        out, _err = self.run_bzr("branches a")
        self.assertEqual(out, "* (default)\n")

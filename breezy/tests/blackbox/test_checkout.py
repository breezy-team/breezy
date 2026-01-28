# Copyright (C) 2006, 2007, 2009-2012, 2016 Canonical Ltd
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

"""Tests for the 'checkout' CLI command."""

import os

from breezy import branch as _mod_branch
from breezy import controldir, errors, workingtree
from breezy.bzr import bzrdir
from breezy.tests import TestCaseWithTransport
from breezy.tests.features import HardlinkFeature


class TestCheckout(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        tree = controldir.ControlDir.create_standalone_workingtree("branch")
        self.rev1 = tree.commit("1", allow_pointless=True)
        self.build_tree(["branch/added_in_2"])
        tree.add("added_in_2")
        self.rev2 = tree.commit("2")

    def test_checkout_makes_bound_branch(self):
        self.run_bzr("checkout branch checkout")
        # if we have a checkout, the branch base should be 'branch'
        source = controldir.ControlDir.open("branch")
        result = controldir.ControlDir.open("checkout")
        self.assertEqual(
            source.open_branch().controldir.root_transport.base,
            result.open_branch().get_bound_location(),
        )

    def test_checkout_light_makes_checkout(self):
        self.run_bzr("checkout --lightweight branch checkout")
        # if we have a checkout, the branch base should be 'branch'
        source = controldir.ControlDir.open("branch")
        result = controldir.ControlDir.open("checkout")
        self.assertEqual(
            source.open_branch().controldir.root_transport.base,
            result.open_branch().controldir.root_transport.base,
        )

    def test_checkout_dash_r(self):
        _out, _err = self.run_bzr(["checkout", "-r", "-2", "branch", "checkout"])
        # the working tree should now be at revision '1' with the content
        # from 1.
        result = controldir.ControlDir.open("checkout")
        self.assertEqual([self.rev1], result.open_workingtree().get_parent_ids())
        self.assertPathDoesNotExist("checkout/added_in_2")

    def test_checkout_light_dash_r(self):
        _out, _err = self.run_bzr(
            ["checkout", "--lightweight", "-r", "-2", "branch", "checkout"]
        )
        # the working tree should now be at revision '1' with the content
        # from 1.
        result = controldir.ControlDir.open("checkout")
        self.assertEqual([self.rev1], result.open_workingtree().get_parent_ids())
        self.assertPathDoesNotExist("checkout/added_in_2")

    def test_checkout_into_empty_dir(self):
        self.make_controldir("checkout")
        _out, _err = self.run_bzr(["checkout", "branch", "checkout"])
        result = controldir.ControlDir.open("checkout")
        result.open_workingtree()
        result.open_branch()

    def test_checkout_reconstitutes_working_trees(self):
        # doing a 'brz checkout' in the directory of a branch with no tree
        # or a 'brz checkout path' with path the name of a directory with
        # a branch with no tree will reconsistute the tree.
        os.mkdir("treeless-branch")
        branch = controldir.ControlDir.create_branch_convenience(
            "treeless-branch", force_new_tree=False, format=bzrdir.BzrDirMetaFormat1()
        )
        # check no tree was created
        self.assertRaises(errors.NoWorkingTree, branch.controldir.open_workingtree)
        out, err = self.run_bzr("checkout treeless-branch")
        # we should have a tree now
        branch.controldir.open_workingtree()
        # with no diff
        out, err = self.run_bzr("diff treeless-branch")

        # now test with no parameters
        branch = controldir.ControlDir.create_branch_convenience(
            ".", force_new_tree=False, format=bzrdir.BzrDirMetaFormat1()
        )
        # check no tree was created
        self.assertRaises(errors.NoWorkingTree, branch.controldir.open_workingtree)
        out, err = self.run_bzr("checkout")
        # we should have a tree now
        branch.controldir.open_workingtree()
        # with no diff
        _out, _err = self.run_bzr("diff")

    def _test_checkout_existing_dir(self, lightweight):
        source = self.make_branch_and_tree("source")
        self.build_tree_contents(
            [
                ("source/file1", b"content1"),
                ("source/file2", b"content2"),
            ]
        )
        source.add(["file1", "file2"])
        source.commit("added files")
        self.build_tree_contents(
            [
                ("target/", b""),
                ("target/file1", b"content1"),
                ("target/file2", b"content3"),
            ]
        )
        cmd = ["checkout", "source", "target"]
        if lightweight:
            cmd.append("--lightweight")
        self.run_bzr("checkout source target")
        # files with unique content should be moved
        self.assertPathExists("target/file2.moved")
        # files with content matching tree should not be moved
        self.assertPathDoesNotExist("target/file1.moved")

    def test_checkout_existing_dir_heavy(self):
        self._test_checkout_existing_dir(False)

    def test_checkout_existing_dir_lightweight(self):
        self._test_checkout_existing_dir(True)

    def test_checkout_in_branch_with_r(self):
        branch = _mod_branch.Branch.open("branch")
        branch.controldir.destroy_workingtree()
        self.run_bzr("checkout -r 1", working_dir="branch")
        tree = workingtree.WorkingTree.open("branch")
        self.assertEqual(self.rev1, tree.last_revision())
        branch.controldir.destroy_workingtree()
        self.run_bzr("checkout -r 0", working_dir="branch")
        self.assertEqual(b"null:", tree.last_revision())

    def test_checkout_files_from(self):
        _mod_branch.Branch.open("branch")
        self.run_bzr(["checkout", "branch", "branch2", "--files-from", "branch"])

    def test_checkout_hardlink(self):
        self.requireFeature(HardlinkFeature(self.test_dir))
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/file1"])
        source.add("file1")
        source.commit("added file")
        _out, _err = self.run_bzr("checkout source target --hardlink")
        source_stat = os.stat("source/file1")
        target_stat = os.stat("target/file1")
        self.assertEqual(source_stat, target_stat)

    def test_checkout_hardlink_files_from(self):
        self.requireFeature(HardlinkFeature(self.test_dir))
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/file1"])
        source.add("file1")
        source.commit("added file")
        source.controldir.sprout("second")
        _out, _err = self.run_bzr(
            "checkout source target --hardlink --files-from second"
        )
        second_stat = os.stat("second/file1")
        target_stat = os.stat("target/file1")
        self.assertEqual(second_stat, target_stat)

    def test_colo_checkout(self):
        source = self.make_branch_and_tree("source", format="development-colo")
        self.build_tree(["source/file1"])
        source.add("file1")
        source.commit("added file")
        target = source.controldir.sprout(
            "file:second,branch=somebranch", create_tree_if_local=False
        )
        _out, _err = self.run_bzr(
            "checkout file:,branch=somebranch .", working_dir="second"
        )
        # We should always be creating a lighweight checkout for colocated
        # branches.
        self.assertEqual(
            target.open_branch(name="somebranch").user_url,
            target.get_branch_reference(name=""),
        )

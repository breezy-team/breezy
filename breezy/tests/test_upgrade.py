# Copyright (C) 2005-2011 Canonical Ltd
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

"""Tests for upgrade of old trees.

This file contains canned versions of some old trees, which are instantiated
and then upgraded to the new format.
"""

# TODO queue for upgrade:
# test the error message when upgrading an unknown BzrDir format.

from .. import branch, controldir, tests, upgrade
from ..bzr import branch as bzrbranch
from ..bzr import workingtree, workingtree_4


class TestUpgrade(tests.TestCaseWithTransport):
    def test_upgrade_rich_root(self):
        tree = self.make_branch_and_tree("tree", format="rich-root")
        tree.commit("first post")
        upgrade.upgrade("tree")

    def test_convert_branch5_branch6(self):
        b = self.make_branch("branch", format="knit")
        b._set_revision_history([b"CD"])
        b.set_parent("file:///EF")
        b.set_bound_location("file:///GH")
        b.set_push_location("file:///IJ")
        target = controldir.format_registry.make_controldir("dirstate-with-subtree")
        converter = b.controldir._format.get_converter(target)
        converter.convert(b.controldir, None)
        new_branch = branch.Branch.open(self.get_url("branch"))
        self.assertIs(new_branch.__class__, bzrbranch.BzrBranch6)
        self.assertEqual(b"CD", new_branch.last_revision())
        self.assertEqual("file:///EF", new_branch.get_parent())
        self.assertEqual("file:///GH", new_branch.get_bound_location())
        branch_config = new_branch.get_config_stack()
        self.assertEqual("file:///IJ", branch_config.get("push_location"))

        b2 = self.make_branch("branch2", format="knit")
        converter = b2.controldir._format.get_converter(target)
        converter.convert(b2.controldir, None)
        b2 = branch.Branch.open(self.get_url("branch"))
        self.assertIs(b2.__class__, bzrbranch.BzrBranch6)

    def test_convert_branch7_branch8(self):
        b = self.make_branch("branch", format="1.9")
        target = controldir.format_registry.make_controldir("1.9")
        target.set_branch_format(bzrbranch.BzrBranchFormat8())
        converter = b.controldir._format.get_converter(target)
        converter.convert(b.controldir, None)
        b = branch.Branch.open(self.get_url("branch"))
        self.assertIs(b.__class__, bzrbranch.BzrBranch8)
        self.assertEqual({}, b._get_all_reference_info())

    def test_convert_knit_dirstate_empty(self):
        # test that asking for an upgrade from knit to dirstate works.
        tree = self.make_branch_and_tree("tree", format="knit")
        target = controldir.format_registry.make_controldir("dirstate")
        converter = tree.controldir._format.get_converter(target)
        converter.convert(tree.controldir, None)
        new_tree = workingtree.WorkingTree.open("tree")
        self.assertIs(new_tree.__class__, workingtree_4.WorkingTree4)
        self.assertEqual(b"null:", new_tree.last_revision())

    def test_convert_knit_dirstate_content(self):
        # smoke test for dirstate conversion: we call dirstate primitives,
        # and its there that the core logic is tested.
        tree = self.make_branch_and_tree("tree", format="knit")
        self.build_tree(["tree/file"])
        tree.add(["file"])
        target = controldir.format_registry.make_controldir("dirstate")
        converter = tree.controldir._format.get_converter(target)
        converter.convert(tree.controldir, None)
        new_tree = workingtree.WorkingTree.open("tree")
        self.assertIs(new_tree.__class__, workingtree_4.WorkingTree4)
        self.assertEqual(b"null:", new_tree.last_revision())

    def test_convert_knit_one_parent_dirstate(self):
        # test that asking for an upgrade from knit to dirstate works.
        tree = self.make_branch_and_tree("tree", format="knit")
        rev_id = tree.commit("first post")
        target = controldir.format_registry.make_controldir("dirstate")
        converter = tree.controldir._format.get_converter(target)
        converter.convert(tree.controldir, None)
        new_tree = workingtree.WorkingTree.open("tree")
        self.assertIs(new_tree.__class__, workingtree_4.WorkingTree4)
        self.assertEqual(rev_id, new_tree.last_revision())
        for path in [
            "basis-inventory-cache",
            "inventory",
            "last-revision",
            "pending-merges",
            "stat-cache",
        ]:
            self.assertPathDoesNotExist("tree/.bzr/checkout/" + path)

    def test_convert_knit_merges_dirstate(self):
        tree = self.make_branch_and_tree("tree", format="knit")
        tree.commit("first post")
        merge_tree = tree.controldir.sprout("tree2").open_workingtree()
        rev_id2 = tree.commit("second post")
        rev_id3 = merge_tree.commit("second merge post")
        tree.merge_from_branch(merge_tree.branch)
        target = controldir.format_registry.make_controldir("dirstate")
        converter = tree.controldir._format.get_converter(target)
        converter.convert(tree.controldir, None)
        new_tree = workingtree.WorkingTree.open("tree")
        self.assertIs(new_tree.__class__, workingtree_4.WorkingTree4)
        self.assertEqual(rev_id2, new_tree.last_revision())
        self.assertEqual([rev_id2, rev_id3], new_tree.get_parent_ids())
        for path in [
            "basis-inventory-cache",
            "inventory",
            "last-revision",
            "pending-merges",
            "stat-cache",
        ]:
            self.assertPathDoesNotExist("tree/.bzr/checkout/" + path)


class TestSmartUpgrade(tests.TestCaseWithTransport):
    from_format = controldir.format_registry.make_controldir("pack-0.92")
    to_format = controldir.format_registry.make_controldir("2a")

    def make_standalone_branch(self):
        wt = self.make_branch_and_tree("branch1", format=self.from_format)
        return wt.controldir

    def test_upgrade_standalone_branch(self):
        control = self.make_standalone_branch()
        tried, worked, issues = upgrade.smart_upgrade([control], format=self.to_format)
        self.assertLength(1, tried)
        self.assertEqual(tried[0], control)
        self.assertLength(1, worked)
        self.assertEqual(worked[0], control)
        self.assertLength(0, issues)
        self.assertPathExists("branch1/backup.bzr.~1~")
        self.assertEqual(
            control.open_repository()._format, self.to_format._repository_format
        )

    def test_upgrade_standalone_branch_cleanup(self):
        control = self.make_standalone_branch()
        tried, worked, issues = upgrade.smart_upgrade(
            [control], format=self.to_format, clean_up=True
        )
        self.assertLength(1, tried)
        self.assertEqual(tried[0], control)
        self.assertLength(1, worked)
        self.assertEqual(worked[0], control)
        self.assertLength(0, issues)
        self.assertPathExists("branch1")
        self.assertPathExists("branch1/.bzr")
        self.assertPathDoesNotExist("branch1/backup.bzr.~1~")
        self.assertEqual(
            control.open_repository()._format, self.to_format._repository_format
        )

    def make_repo_with_branches(self):
        repo = self.make_repository("repo", shared=True, format=self.from_format)
        # Note: self.make_branch() always creates a new repo at the location
        # so we need to avoid using that here ...
        controldir.ControlDir.create_branch_convenience(
            "repo/branch1", format=self.from_format
        )
        b2 = controldir.ControlDir.create_branch_convenience(
            "repo/branch2", format=self.from_format
        )
        return repo.controldir

    def test_upgrade_repo_with_branches(self):
        control = self.make_repo_with_branches()
        tried, worked, issues = upgrade.smart_upgrade([control], format=self.to_format)
        self.assertLength(3, tried)
        self.assertEqual(tried[0], control)
        self.assertLength(3, worked)
        self.assertEqual(worked[0], control)
        self.assertLength(0, issues)
        self.assertPathExists("repo/backup.bzr.~1~")
        self.assertPathExists("repo/branch1/backup.bzr.~1~")
        self.assertPathExists("repo/branch2/backup.bzr.~1~")
        self.assertEqual(
            control.open_repository()._format, self.to_format._repository_format
        )
        b1 = branch.Branch.open("repo/branch1")
        self.assertEqual(b1._format, self.to_format._branch_format)

    def test_upgrade_repo_with_branches_cleanup(self):
        control = self.make_repo_with_branches()
        tried, worked, issues = upgrade.smart_upgrade(
            [control], format=self.to_format, clean_up=True
        )
        self.assertLength(3, tried)
        self.assertEqual(tried[0], control)
        self.assertLength(3, worked)
        self.assertEqual(worked[0], control)
        self.assertLength(0, issues)
        self.assertPathExists("repo")
        self.assertPathExists("repo/.bzr")
        self.assertPathDoesNotExist("repo/backup.bzr.~1~")
        self.assertPathDoesNotExist("repo/branch1/backup.bzr.~1~")
        self.assertPathDoesNotExist("repo/branch2/backup.bzr.~1~")
        self.assertEqual(
            control.open_repository()._format, self.to_format._repository_format
        )
        b1 = branch.Branch.open("repo/branch1")
        self.assertEqual(b1._format, self.to_format._branch_format)

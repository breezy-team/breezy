# Copyright (C) 2007-2012, 2016 Canonical Ltd
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


"""Tests for the switch command of bzr."""

import os

from breezy import branch, osutils, urlutils
from breezy.controldir import ControlDir
from breezy.directory_service import directories
from breezy.tests import TestCaseWithTransport, script
from breezy.tests.features import UnicodeFilenameFeature
from breezy.workingtree import WorkingTree


class TestSwitch(TestCaseWithTransport):
    def _create_sample_tree(self):
        tree = self.make_branch_and_tree("branch-1")
        self.build_tree(["branch-1/file-1", "branch-1/file-2"])
        tree.add("file-1")
        tree.commit("rev1")
        tree.add("file-2")
        tree.commit("rev2")
        return tree

    def test_switch_up_to_date_light_checkout(self):
        self.make_branch_and_tree("branch")
        self.run_bzr("branch branch branch2")
        self.run_bzr("checkout --lightweight branch checkout")
        os.chdir("checkout")
        out, err = self.run_bzr("switch ../branch2")
        self.assertContainsRe(err, "Tree is up to date at revision 0.\n")
        self.assertContainsRe(err, "Switched to branch at .*/branch2.\n")
        self.assertEqual("", out)

    def test_switch_out_of_date_light_checkout(self):
        self.make_branch_and_tree("branch")
        self.run_bzr("branch branch branch2")
        self.build_tree(["branch2/file"])
        self.run_bzr("add branch2/file")
        self.run_bzr("commit -m add-file branch2")
        self.run_bzr("checkout --lightweight branch checkout")
        os.chdir("checkout")
        out, err = self.run_bzr("switch ../branch2")
        # self.assertContainsRe(err, '\+N  file')
        self.assertContainsRe(err, "Updated to revision 1.\n")
        self.assertContainsRe(err, "Switched to branch at .*/branch2.\n")
        self.assertEqual("", out)

    def _test_switch_nick(self, lightweight):
        """Check that the nick gets switched too."""
        tree1 = self.make_branch_and_tree("branch1")
        tree2 = self.make_branch_and_tree("branch2")
        tree2.pull(tree1.branch)
        checkout = tree1.branch.create_checkout("checkout", lightweight=lightweight)
        self.assertEqual(checkout.branch.nick, tree1.branch.nick)
        self.assertEqual(checkout.branch.get_config().has_explicit_nickname(), False)
        self.run_bzr("switch branch2", working_dir="checkout")

        # we need to get the tree again, otherwise we don't get the new branch
        checkout = WorkingTree.open("checkout")
        self.assertEqual(checkout.branch.nick, tree2.branch.nick)
        self.assertEqual(checkout.branch.get_config().has_explicit_nickname(), False)

    def test_switch_nick(self):
        self._test_switch_nick(lightweight=False)

    def test_switch_nick_lightweight(self):
        self._test_switch_nick(lightweight=True)

    def _test_switch_explicit_nick(self, lightweight):
        """Check that the nick gets switched too."""
        tree1 = self.make_branch_and_tree("branch1")
        tree2 = self.make_branch_and_tree("branch2")
        tree2.pull(tree1.branch)
        checkout = tree1.branch.create_checkout("checkout", lightweight=lightweight)
        self.assertEqual(checkout.branch.nick, tree1.branch.nick)
        checkout.branch.nick = "explicit_nick"
        self.assertEqual(checkout.branch.nick, "explicit_nick")
        self.assertEqual(
            checkout.branch.get_config()._get_explicit_nickname(), "explicit_nick"
        )
        self.run_bzr("switch branch2", working_dir="checkout")

        # we need to get the tree again, otherwise we don't get the new branch
        checkout = WorkingTree.open("checkout")
        self.assertEqual(checkout.branch.nick, tree2.branch.nick)
        self.assertEqual(
            checkout.branch.get_config()._get_explicit_nickname(), tree2.branch.nick
        )

    def test_switch_explicit_nick(self):
        self._test_switch_explicit_nick(lightweight=False)

    def test_switch_explicit_nick_lightweight(self):
        self._test_switch_explicit_nick(lightweight=True)

    def test_switch_finds_relative_branch(self):
        """Switch will find 'foo' relative to the branch the checkout is of."""
        self.build_tree(["repo/"])
        tree1 = self.make_branch_and_tree("repo/brancha")
        tree1.commit("foo")
        tree2 = self.make_branch_and_tree("repo/branchb")
        tree2.pull(tree1.branch)
        branchb_id = tree2.commit("bar")
        checkout = tree1.branch.create_checkout("checkout", lightweight=True)
        self.run_bzr(["switch", "branchb"], working_dir="checkout")
        self.assertEqual(branchb_id, checkout.last_revision())
        checkout = checkout.controldir.open_workingtree()
        self.assertEqual(tree2.branch.base, checkout.branch.base)

    def test_switch_finds_relative_bound_branch(self):
        """Using switch on a heavy checkout should find master sibling.

        The behaviour of lighweight and heavy checkouts should be
        consistent when using the convenient "switch to sibling" feature
        Both should switch to a sibling of the branch
        they are bound to, and not a sibling of themself
        """
        self.build_tree(["repo/", "heavyco/"])
        tree1 = self.make_branch_and_tree("repo/brancha")
        tree1.commit("foo")
        tree2 = self.make_branch_and_tree("repo/branchb")
        tree2.pull(tree1.branch)
        branchb_id = tree2.commit("bar")
        checkout = tree1.branch.create_checkout("heavyco/a", lightweight=False)
        self.run_bzr(["switch", "branchb"], working_dir="heavyco/a")
        # Refresh checkout as 'switch' modified it
        checkout = checkout.controldir.open_workingtree()
        self.assertEqual(branchb_id, checkout.last_revision())
        self.assertEqual(tree2.branch.base, checkout.branch.get_bound_location())

    def test_switch_finds_relative_unicode_branch(self):
        """Switch will find 'foo' relative to the branch the checkout is of."""
        self.requireFeature(UnicodeFilenameFeature)
        self.build_tree(["repo/"])
        tree1 = self.make_branch_and_tree("repo/brancha")
        tree1.commit("foo")
        tree2 = self.make_branch_and_tree("repo/branch\xe9")
        tree2.pull(tree1.branch)
        branchb_id = tree2.commit("bar")
        checkout = tree1.branch.create_checkout("checkout", lightweight=True)
        self.run_bzr(["switch", "branch\xe9"], working_dir="checkout")
        self.assertEqual(branchb_id, checkout.last_revision())
        checkout = checkout.controldir.open_workingtree()
        self.assertEqual(tree2.branch.base, checkout.branch.base)

    def test_switch_revision(self):
        tree = self._create_sample_tree()
        tree.branch.create_checkout("checkout", lightweight=True)
        self.run_bzr(["switch", "branch-1", "-r1"], working_dir="checkout")
        self.assertPathExists("checkout/file-1")
        self.assertPathDoesNotExist("checkout/file-2")

    def test_switch_into_colocated(self):
        # Create a new colocated branch from an existing non-colocated branch.
        tree = self.make_branch_and_tree(".", format="development-colo")
        self.build_tree(["file-1", "file-2"])
        tree.add("file-1")
        tree.commit("rev1")
        tree.add("file-2")
        tree.commit("rev2")
        self.run_bzr(["switch", "-b", "anotherbranch"])
        self.assertEqual(
            {"", "anotherbranch"}, set(tree.branch.controldir.branch_names())
        )

    def test_switch_into_unrelated_colocated(self):
        # Create a new colocated branch from an existing non-colocated branch.
        tree = self.make_branch_and_tree(".", format="development-colo")
        self.build_tree(["file-1", "file-2"])
        tree.add("file-1")
        tree.commit("rev1")
        tree.add("file-2")
        tree.commit("rev2")
        tree.controldir.create_branch(name="foo")
        self.run_bzr_error(["Cannot switch a branch, only a checkout."], "switch foo")
        self.run_bzr(["switch", "--force", "foo"])

    def test_switch_existing_colocated(self):
        # Create a branch branch-1 that initially is a checkout of 'foo'
        # Use switch to change it to 'anotherbranch'
        repo = self.make_repository("branch-1", format="development-colo")
        target_branch = repo.controldir.create_branch(name="foo")
        repo.controldir.set_branch_reference(target_branch)
        tree = repo.controldir.create_workingtree()
        self.build_tree(["branch-1/file-1", "branch-1/file-2"])
        tree.add("file-1")
        revid1 = tree.commit("rev1")
        tree.add("file-2")
        tree.commit("rev2")
        otherbranch = tree.controldir.create_branch(name="anotherbranch")
        otherbranch.generate_revision_history(revid1)
        self.run_bzr(["switch", "anotherbranch"], working_dir="branch-1")
        tree = WorkingTree.open("branch-1")
        self.assertEqual(tree.last_revision(), revid1)
        self.assertEqual(tree.branch.control_url, otherbranch.control_url)

    def test_switch_new_colocated(self):
        # Create a branch branch-1 that initially is a checkout of 'foo'
        # Use switch to create 'anotherbranch' which derives from that
        repo = self.make_repository("branch-1", format="development-colo")
        target_branch = repo.controldir.create_branch(name="foo")
        repo.controldir.set_branch_reference(target_branch)
        tree = repo.controldir.create_workingtree()
        self.build_tree(["branch-1/file-1", "branch-1/file-2"])
        tree.add("file-1")
        revid1 = tree.commit("rev1")
        self.run_bzr(["switch", "-b", "anotherbranch"], working_dir="branch-1")
        bzrdir = ControlDir.open("branch-1")
        self.assertEqual(
            {b.name for b in bzrdir.list_branches()}, {"foo", "anotherbranch"}
        )
        self.assertEqual(bzrdir.open_branch().name, "anotherbranch")
        self.assertEqual(bzrdir.open_branch().last_revision(), revid1)

    def test_switch_new_colocated_unicode(self):
        # Create a branch branch-1 that initially is a checkout of 'foo'
        # Use switch to create 'branch\xe9' which derives from that
        self.requireFeature(UnicodeFilenameFeature)
        repo = self.make_repository("branch-1", format="development-colo")
        target_branch = repo.controldir.create_branch(name="foo")
        repo.controldir.set_branch_reference(target_branch)
        tree = repo.controldir.create_workingtree()
        self.build_tree(["branch-1/file-1", "branch-1/file-2"])
        tree.add("file-1")
        revid1 = tree.commit("rev1")
        self.run_bzr(["switch", "-b", "branch\xe9"], working_dir="branch-1")
        bzrdir = ControlDir.open("branch-1")
        self.assertEqual(
            {b.name for b in bzrdir.list_branches()}, {"foo", "branch\xe9"}
        )
        self.assertEqual(bzrdir.open_branch().name, "branch\xe9")
        self.assertEqual(bzrdir.open_branch().last_revision(), revid1)

    def test_switch_only_revision(self):
        tree = self._create_sample_tree()
        tree.branch.create_checkout("checkout", lightweight=True)
        self.assertPathExists("checkout/file-1")
        self.assertPathExists("checkout/file-2")
        self.run_bzr(["switch", "-r1"], working_dir="checkout")
        self.assertPathExists("checkout/file-1")
        self.assertPathDoesNotExist("checkout/file-2")
        # Check that we don't accept a range
        self.run_bzr_error(
            ["brz switch --revision takes exactly one revision identifier"],
            ["switch", "-r0..2"],
            working_dir="checkout",
        )

    def prepare_lightweight_switch(self):
        branch = self.make_branch("branch")
        branch.create_checkout("tree", lightweight=True)
        osutils.rename("branch", "branch1")

    def test_switch_lightweight_after_branch_moved(self):
        self.prepare_lightweight_switch()
        self.run_bzr("switch --force ../branch1", working_dir="tree")
        branch_location = WorkingTree.open("tree").branch.base
        self.assertEndsWith(branch_location, "branch1/")

    def test_switch_lightweight_after_branch_moved_relative(self):
        self.prepare_lightweight_switch()
        self.run_bzr("switch --force branch1", working_dir="tree")
        branch_location = WorkingTree.open("tree").branch.base
        self.assertEndsWith(branch_location, "branch1/")

    def test_create_branch_no_branch(self):
        self.prepare_lightweight_switch()
        self.run_bzr_error(
            ["cannot create branch without source branch"],
            "switch --create-branch ../branch2",
            working_dir="tree",
        )

    def test_create_branch(self):
        branch = self.make_branch("branch")
        tree = branch.create_checkout("tree", lightweight=True)
        tree.commit("one", rev_id=b"rev-1")
        self.run_bzr("switch --create-branch ../branch2", working_dir="tree")
        tree = WorkingTree.open("tree")
        self.assertEndsWith(tree.branch.base, "/branch2/")

    def test_create_branch_local(self):
        branch = self.make_branch("branch")
        tree = branch.create_checkout("tree", lightweight=True)
        tree.commit("one", rev_id=b"rev-1")
        self.run_bzr("switch --create-branch branch2", working_dir="tree")
        tree = WorkingTree.open("tree")
        # The new branch should have been created at the same level as
        # 'branch', because we did not have a '/' segment
        self.assertEqual(branch.base[:-1] + "2/", tree.branch.base)

    def test_create_branch_short_name(self):
        branch = self.make_branch("branch")
        tree = branch.create_checkout("tree", lightweight=True)
        tree.commit("one", rev_id=b"rev-1")
        self.run_bzr("switch -b branch2", working_dir="tree")
        tree = WorkingTree.open("tree")
        # The new branch should have been created at the same level as
        # 'branch', because we did not have a '/' segment
        self.assertEqual(branch.base[:-1] + "2/", tree.branch.base)

    def test_create_branch_directory_services(self):
        branch = self.make_branch("branch")
        tree = branch.create_checkout("tree", lightweight=True)

        class FooLookup:
            def look_up(self, name, url, purpose=None):
                return "foo-" + name

        directories.register("foo:", FooLookup, "Create branches named foo-")
        self.addCleanup(directories.remove, "foo:")
        self.run_bzr("switch -b foo:branch2", working_dir="tree")
        tree = WorkingTree.open("tree")
        self.assertEndsWith(tree.branch.base, "foo-branch2/")

    def test_switch_with_post_switch_hook(self):
        from breezy import branch as _mod_branch

        calls = []
        _mod_branch.Branch.hooks.install_named_hook("post_switch", calls.append, None)
        self.make_branch_and_tree("branch")
        self.run_bzr("branch branch branch2")
        self.run_bzr("checkout branch checkout")
        os.chdir("checkout")
        self.assertLength(0, calls)
        out, err = self.run_bzr("switch ../branch2")
        self.assertLength(1, calls)

    def test_switch_lightweight_co_with_post_switch_hook(self):
        from breezy import branch as _mod_branch

        calls = []
        _mod_branch.Branch.hooks.install_named_hook("post_switch", calls.append, None)
        self.make_branch_and_tree("branch")
        self.run_bzr("branch branch branch2")
        self.run_bzr("checkout --lightweight branch checkout")
        os.chdir("checkout")
        self.assertLength(0, calls)
        out, err = self.run_bzr("switch ../branch2")
        self.assertLength(1, calls)

    def test_switch_lightweight_directory(self):
        """Test --directory option."""
        # create a source branch
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/a", b"initial\n")])
        a_tree.add("a")
        a_tree.commit(message="initial")

        # clone and add a differing revision
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("b/a", b"initial\nmore\n")])
        b_tree.commit(message="more")

        self.run_bzr("checkout --lightweight a checkout")
        self.run_bzr("switch --directory checkout b")
        self.assertFileEqual(b"initial\nmore\n", "checkout/a")


class TestSwitchParentLocationBase(TestCaseWithTransport):
    def setUp(self):
        """Set up a repository and branch ready for testing."""
        super().setUp()
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(
            self,
            """
                $ brz init-shared-repo --no-trees repo
                Shared repository...
                Location:
                  shared repository: repo
                $ brz init repo/trunk
                Created a repository branch...
                Using shared repository: ...
                """,
        )

    def assertParent(self, expected_parent, branch):
        """Verify that the parent is not None and is set correctly."""
        branch.get_parent()
        self.assertIsSameRealPath(
            urlutils.local_path_to_url(expected_parent), branch.get_parent()
        )


class TestSwitchParentLocation(TestSwitchParentLocationBase):
    def _checkout_and_switch(self, option=""):
        self.script_runner.run_script(
            self,
            """
                $ brz checkout {option} repo/trunk checkout
                $ cd checkout
                $ brz switch --create-branch switched
                2>Tree is up to date at revision 0.
                2>Switched to branch at .../switched/
                $ cd ..
                """.format(**locals()),
        )
        bound_branch = branch.Branch.open_containing("checkout")[0]
        master_branch = branch.Branch.open_containing("repo/switched")[0]
        return (bound_branch, master_branch)

    def test_switch_parent_lightweight(self):
        """Lightweight checkout using brz switch."""
        bb, mb = self._checkout_and_switch(option="--lightweight")
        self.assertParent("repo/trunk", bb)
        self.assertParent("repo/trunk", mb)

    def test_switch_parent_heavyweight(self):
        """Heavyweight checkout using brz switch."""
        bb, mb = self._checkout_and_switch()
        self.assertParent("repo/trunk", bb)
        self.assertParent("repo/trunk", mb)


class TestSwitchDoesntOpenMasterBranch(TestCaseWithTransport):
    # See https://bugs.launchpad.net/bzr/+bug/812285
    # "brz switch --create-branch" can point the new branch's parent to the
    # master branch, but it doesn't have to open it to do so.

    def test_switch_create_doesnt_open_master_branch(self):
        master = self.make_branch_and_tree("master")
        master.commit("one")
        # Note: not a lightweight checkout
        master.branch.create_checkout("checkout")
        opened = []

        def open_hook(branch):
            # Just append the final directory of the branch
            name = branch.base.rstrip("/").rsplit("/", 1)[1]
            opened.append(name)

        branch.Branch.hooks.install_named_hook("open", open_hook, "open_hook_logger")
        self.run_bzr("switch --create-branch -d checkout feature")
        # We only open the master branch 1 time.
        # This test should be cleaner to write, but see bug:
        #  https://bugs.launchpad.net/bzr/+bug/812295
        self.assertEqual(1, opened.count("master"))


class TestSwitchUncommitted(TestCaseWithTransport):
    def prepare(self):
        tree = self.make_branch_and_tree("orig")
        tree.commit("")
        tree.branch.controldir.sprout("new")
        checkout = tree.branch.create_checkout("checkout", lightweight=True)
        self.build_tree(["checkout/a"])
        self.assertPathExists("checkout/a")
        checkout.add("a")
        return checkout

    def test_store_and_restore_uncommitted(self):
        checkout = self.prepare()
        self.run_bzr(["switch", "--store", "-d", "checkout", "new"])
        self.build_tree(["checkout/b"])
        checkout.add("b")
        self.assertPathDoesNotExist("checkout/a")
        self.assertPathExists("checkout/b")
        self.run_bzr(["switch", "--store", "-d", "checkout", "orig"])
        self.assertPathExists("checkout/a")
        self.assertPathDoesNotExist("checkout/b")

    def test_does_not_store(self):
        self.prepare()
        self.run_bzr(["switch", "-d", "checkout", "new"])
        self.assertPathExists("checkout/a")

    def test_does_not_restore_changes(self):
        self.prepare()
        self.run_bzr(["switch", "--store", "-d", "checkout", "new"])
        self.assertPathDoesNotExist("checkout/a")
        self.run_bzr(["switch", "-d", "checkout", "orig"])
        self.assertPathDoesNotExist("checkout/a")


class TestSwitchStandAloneCorruption(TestCaseWithTransport):
    def test_empty_tree_switch(self):
        """Switch . on an empty tree gets infinite recursion.

        Inspired by: https://bugs.launchpad.net/bzr/+bug/1018628
        """
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(
            self,
            """
            $ brz init
            Created a standalone tree (format: 2a)
            $ brz switch .
            2>brz: ERROR: switching would create a branch reference loop. Use the "bzr up" command to switch to a different revision.
            """,
        )

    def test_switch_on_previous_rev(self):
        """Switch to previous rev in a standalone directory.

        Inspired by: https://bugs.launchpad.net/brz/+bug/1018628
        """
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(
            self,
            """
           $ brz init
           Created a standalone tree (format: 2a)
           $ brz commit -m 1 --unchanged
           $ brz commit -m 2 --unchanged
           $ brz switch -r 1
           2>brz: ERROR: switching would create a branch reference loop. Use the "bzr up" command to switch to a different revision.""",
            null_output_matches_anything=True,
        )

    def test_switch_create_colo_locks_repo_path(self):
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(
            self,
            """
            $ mkdir mywork
            $ cd mywork
            $ brz init
            Created a standalone tree (format: 2a)
            $ echo A > a && brz add a && brz commit -m A
            $ brz switch -b br1
            $ cd ..
            $ mv mywork mywork1
            $ cd mywork1
            $ brz branches
              br1
            """,
            null_output_matches_anything=True,
        )

    def test_switch_to_new_branch_on_old_rev(self):
        """Switch to previous rev in a standalone directory.

        Inspired by: https://bugs.launchpad.net/brz/+bug/933362
        """
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(
            self,
            """
           $ brz init
           Created a standalone tree (format: 2a)
           $ brz switch -b trunk
           2>Tree is up to date at revision 0.
           2>Switched to branch trunk
           $ brz commit -m 1 --unchanged
           2>Committing to: ...
           2>Committed revision 1.
           $ brz commit -m 2 --unchanged
           2>Committing to: ...
           2>Committed revision 2.
           $ brz switch -b blah -r1
           2>Updated to revision 1.
           2>Switched to branch blah
           $ brz branches
           * blah
             trunk
           $ brz st
           """,
        )

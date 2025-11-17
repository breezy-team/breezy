# Copyright (C) 2006-2012, 2016 Canonical Ltd
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


"""Black-box tests for brz branch."""

import os

from breezy import branch, controldir, errors, tests
from breezy import revision as _mod_revision
from breezy.bzr import bzrdir
from breezy.bzr.knitrepo import RepositoryFormatKnit1
from breezy.tests import fixtures, test_server
from breezy.tests.blackbox import test_switch
from breezy.tests.features import HardlinkFeature
from breezy.tests.test_sftp_transport import TestCaseWithSFTPServer
from breezy.urlutils import local_path_to_url, strip_trailing_slash
from breezy.workingtree import WorkingTree


class TestBranch(tests.TestCaseWithTransport):
    def example_branch(self, path=".", format=None):
        tree = self.make_branch_and_tree(path, format=format)
        self.build_tree_contents([(path + "/hello", b"foo")])
        tree.add("hello")
        tree.commit(message="setup")
        self.build_tree_contents([(path + "/goodbye", b"baz")])
        tree.add("goodbye")
        tree.commit(message="setup")
        return tree

    def test_branch(self):
        """Branch from one branch to another."""
        self.example_branch("a")
        self.run_bzr("branch a b")
        b = branch.Branch.open("b")
        self.run_bzr("branch a c -r 1")
        # previously was erroneously created by branching
        self.assertFalse(b._transport.has("branch-name"))
        b.controldir.open_workingtree().commit(message="foo", allow_pointless=True)

    def test_branch_no_to_location(self):
        """The to_location is derived from the source branch name."""
        os.mkdir("something")
        a = self.example_branch("something/a").branch
        self.run_bzr("branch something/a")
        b = branch.Branch.open("a")
        self.assertEqual(b.last_revision_info(), a.last_revision_info())

    def test_into_colocated(self):
        """Branch from a branch into a colocated branch."""
        self.example_branch("a")
        out, err = self.run_bzr("init --format=development-colo file:b,branch=orig")
        self.assertEqual(
            """Created a standalone tree (format: development-colo)\n""", out
        )
        self.assertEqual("", err)
        out, err = self.run_bzr("branch a file:b,branch=thiswasa")
        self.assertEqual("", out)
        self.assertEqual("Branched 2 revisions.\n", err)
        out, err = self.run_bzr("branches b")
        self.assertEqual("  orig\n  thiswasa\n", out)
        self.assertEqual("", err)
        out, err = self.run_bzr("branch a file:b,branch=orig", retcode=3)
        self.assertEqual("", out)
        self.assertEqual('brz: ERROR: Already a branch: "file:b,branch=orig".\n', err)

    def test_from_colocated(self):
        """Branch from a colocated branch into a regular branch."""
        os.mkdir("b")
        tree = self.example_branch("b/a", format="development-colo")
        tree.controldir.create_branch(name="somecolo")
        out, err = self.run_bzr(
            "branch {},branch=somecolo".format(local_path_to_url("b/a"))
        )
        self.assertEqual("", out)
        self.assertEqual("Branched 0 revisions.\n", err)
        self.assertPathExists("a")

    def test_from_name(self):
        """Branch from a colocated branch into a regular branch."""
        os.mkdir("b")
        tree = self.example_branch("b/a", format="development-colo")
        tree.controldir.create_branch(name="somecolo")
        out, err = self.run_bzr(
            "branch -b somecolo {}".format(local_path_to_url("b/a"))
        )
        self.assertEqual("", out)
        self.assertEqual("Branched 0 revisions.\n", err)
        self.assertPathExists("a")

    def test_branch_broken_pack(self):
        """Branching with a corrupted pack file."""
        self.example_branch("a")
        # add some corruption
        packs_dir = "a/.bzr/repository/packs/"
        fname = packs_dir + os.listdir(packs_dir)[0]
        with open(fname, "rb+") as f:
            # Start from the end of the file to avoid choosing a place bigger
            # than the file itself.
            f.seek(-5, os.SEEK_END)
            c = f.read(1)
            f.seek(-5, os.SEEK_END)
            # Make sure we inject a value different than the one we just read
            if c == b"\xff":
                corrupt = b"\x00"
            else:
                corrupt = b"\xff"
            f.write(corrupt)  # make sure we corrupt something
        self.run_bzr_error(
            ["Corruption while decompressing repository file"], "branch a b", retcode=3
        )

    def test_branch_switch_no_branch(self):
        # No branch in the current directory:
        #  => new branch will be created, but switch fails
        self.example_branch("a")
        self.make_repository("current")
        self.run_bzr_error(
            ["No WorkingTree exists for"],
            "branch --switch ../a ../b",
            working_dir="current",
        )
        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.last_revision(), b.last_revision())

    def test_branch_switch_no_wt(self):
        # No working tree in the current directory:
        #  => new branch will be created, but switch fails and the current
        #     branch is unmodified
        self.example_branch("a")
        self.make_branch("current")
        self.run_bzr_error(
            ["No WorkingTree exists for"],
            "branch --switch ../a ../b",
            working_dir="current",
        )
        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.last_revision(), b.last_revision())
        work = branch.Branch.open("current")
        self.assertEqual(work.last_revision(), _mod_revision.NULL_REVISION)

    def test_branch_switch_no_checkout(self):
        # Standalone branch in the current directory:
        #  => new branch will be created, but switch fails and the current
        #     branch is unmodified
        self.example_branch("a")
        tree = self.make_branch_and_tree("current")
        c1 = tree.commit("some diverged change")
        self.run_bzr_error(
            ["Cannot switch a branch, only a checkout"],
            "branch --switch ../a ../b",
            working_dir="current",
        )
        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.last_revision(), b.last_revision())
        work = branch.Branch.open("current")
        self.assertEqual(work.last_revision(), c1)

    def test_branch_into_empty_dir(self):
        t = self.example_branch("source")
        self.make_controldir("target")
        self.run_bzr("branch source target")
        self.assertEqual(2, len(t.branch.repository.all_revision_ids()))

    def test_branch_switch_checkout(self):
        # Checkout in the current directory:
        #  => new branch will be created and checkout bound to the new branch
        self.example_branch("a")
        self.run_bzr("checkout a current")
        _out, err = self.run_bzr("branch --switch ../a ../b", working_dir="current")
        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.last_revision(), b.last_revision())
        work = WorkingTree.open("current")
        self.assertEndsWith(work.branch.get_bound_location(), "/b/")
        self.assertContainsRe(err, "Switched to branch: .*/b/")

    def test_branch_switch_lightweight_checkout(self):
        # Lightweight checkout in the current directory:
        #  => new branch will be created and lightweight checkout pointed to
        #     the new branch
        self.example_branch("a")
        self.run_bzr("checkout --lightweight a current")
        _out, err = self.run_bzr("branch --switch ../a ../b", working_dir="current")
        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.last_revision(), b.last_revision())
        work = WorkingTree.open("current")
        self.assertEndsWith(work.branch.base, "/b/")
        self.assertContainsRe(err, "Switched to branch: .*/b/")

    def test_branch_only_copies_history(self):
        # Knit branches should only push the history for the current revision.
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = RepositoryFormatKnit1()
        shared_repo = self.make_repository("repo", format=format, shared=True)
        shared_repo.set_make_working_trees(True)

        def make_shared_tree(path):
            shared_repo.controldir.root_transport.mkdir(path)
            controldir.ControlDir.create_branch_convenience("repo/" + path)
            return WorkingTree.open("repo/" + path)

        tree_a = make_shared_tree("a")
        self.build_tree(["repo/a/file"])
        tree_a.add("file")
        a1 = tree_a.commit("commit a-1")
        with open("repo/a/file", "ab") as f:
            f.write(b"more stuff\n")
        a2 = tree_a.commit("commit a-2")

        tree_b = make_shared_tree("b")
        self.build_tree(["repo/b/file"])
        tree_b.add("file")
        b1 = tree_b.commit("commit b-1")

        self.assertTrue(shared_repo.has_revision(a1))
        self.assertTrue(shared_repo.has_revision(a2))
        self.assertTrue(shared_repo.has_revision(b1))

        # Now that we have a repository with shared files, make sure
        # that things aren't copied out by a 'branch'
        self.run_bzr("branch repo/b branch-b")
        pushed_tree = WorkingTree.open("branch-b")
        pushed_repo = pushed_tree.branch.repository
        self.assertFalse(pushed_repo.has_revision(a1))
        self.assertFalse(pushed_repo.has_revision(a2))
        self.assertTrue(pushed_repo.has_revision(b1))

    def test_branch_hardlink(self):
        self.requireFeature(HardlinkFeature(self.test_dir))
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/file1"])
        source.add("file1")
        source.commit("added file")
        _out, _err = self.run_bzr(["branch", "source", "target", "--hardlink"])
        source_stat = os.stat("source/file1")
        target_stat = os.stat("target/file1")
        self.assertEqual(source_stat, target_stat)

    def test_branch_files_from(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/file1"])
        source.add("file1")
        source.commit("added file")
        _out, _err = self.run_bzr("branch source target --files-from source")
        self.assertPathExists("target/file1")

    def test_branch_files_from_hardlink(self):
        self.requireFeature(HardlinkFeature(self.test_dir))
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/file1"])
        source.add("file1")
        source.commit("added file")
        source.controldir.sprout("second")
        _out, _err = self.run_bzr("branch source target --files-from second --hardlink")
        source_stat = os.stat("source/file1")
        second_stat = os.stat("second/file1")
        target_stat = os.stat("target/file1")
        self.assertNotEqual(source_stat, target_stat)
        self.assertEqual(second_stat, target_stat)

    def test_branch_standalone(self):
        self.make_repository("repo", shared=True)
        self.example_branch("source")
        self.run_bzr("branch --standalone source repo/target")
        b = branch.Branch.open("repo/target")
        expected_repo_path = os.path.abspath("repo/target/.bzr/repository")
        self.assertEqual(
            strip_trailing_slash(b.repository.base),
            strip_trailing_slash(local_path_to_url(expected_repo_path)),
        )

    def test_branch_no_tree(self):
        self.example_branch("source")
        self.run_bzr("branch --no-tree source target")
        self.assertPathDoesNotExist("target/hello")
        self.assertPathDoesNotExist("target/goodbye")

    def test_branch_into_existing_dir(self):
        self.example_branch("a")
        # existing dir with similar files but no .brz dir
        self.build_tree_contents([("b/",)])
        self.build_tree_contents([("b/hello", b"bar")])  # different content
        self.build_tree_contents([("b/goodbye", b"baz")])  # same content
        # fails without --use-existing-dir
        out, err = self.run_bzr("branch a b", retcode=3)
        self.assertEqual("", out)
        self.assertEqual('brz: ERROR: Target directory "b" already exists.\n', err)
        # force operation
        self.run_bzr("branch a b --use-existing-dir")
        # check conflicts
        self.assertPathExists("b/hello.moved")
        self.assertPathDoesNotExist("b/godbye.moved")
        # we can't branch into branch
        out, err = self.run_bzr("branch a b --use-existing-dir", retcode=3)
        self.assertEqual("", out)
        self.assertEqual('brz: ERROR: Already a branch: "b".\n', err)

    def test_branch_bind(self):
        self.example_branch("a")
        _out, err = self.run_bzr("branch a b --bind")
        self.assertEndsWith(err, "New branch bound to a\n")
        b = branch.Branch.open("b")
        self.assertEndsWith(b.get_bound_location(), "/a/")

    def test_branch_with_post_branch_init_hook(self):
        calls = []
        branch.Branch.hooks.install_named_hook("post_branch_init", calls.append, None)
        self.assertLength(0, calls)
        self.example_branch("a")
        self.assertLength(1, calls)
        self.run_bzr("branch a b")
        self.assertLength(2, calls)

    def test_checkout_with_post_branch_init_hook(self):
        calls = []
        branch.Branch.hooks.install_named_hook("post_branch_init", calls.append, None)
        self.assertLength(0, calls)
        self.example_branch("a")
        self.assertLength(1, calls)
        self.run_bzr("checkout a b")
        self.assertLength(2, calls)

    def test_lightweight_checkout_with_post_branch_init_hook(self):
        calls = []
        branch.Branch.hooks.install_named_hook("post_branch_init", calls.append, None)
        self.assertLength(0, calls)
        self.example_branch("a")
        self.assertLength(1, calls)
        self.run_bzr("checkout --lightweight a b")
        self.assertLength(2, calls)

    def test_branch_fetches_all_tags(self):
        builder = self.make_branch_builder("source")
        source, _rev1, rev2 = fixtures.build_branch_with_non_ancestral_rev(builder)
        source.tags.set_tag("tag-a", rev2)
        source.get_config_stack().set("branch.fetch_tags", True)
        # Now source has a tag not in its ancestry.  Make a branch from it.
        self.run_bzr("branch source new-branch")
        new_branch = branch.Branch.open("new-branch")
        # The tag is present, and so is its revision.
        self.assertEqual(rev2, new_branch.tags.lookup_tag("tag-a"))
        new_branch.repository.get_revision(rev2)

    def test_branch_with_nested_trees(self):
        orig = self.make_branch_and_tree("source", format="development-subtree")
        subtree = self.make_branch_and_tree("source/subtree")
        self.build_tree(["source/subtree/a"])
        subtree.add(["a"])
        subtree.commit("add subtree contents")
        orig.add_reference(subtree)
        orig.set_reference_info("subtree", subtree.branch.user_url)
        orig.commit("add subtree")

        self.run_bzr("branch source target")

        target = WorkingTree.open("target")
        target_subtree = WorkingTree.open("target/subtree")
        self.assertTreesEqual(orig, target)
        self.assertTreesEqual(subtree, target_subtree)

    def test_branch_with_nested_trees_reference_unset(self):
        orig = self.make_branch_and_tree("source", format="development-subtree")
        subtree = self.make_branch_and_tree("source/subtree")
        self.build_tree(["source/subtree/a"])
        subtree.add(["a"])
        subtree.commit("add subtree contents")
        orig.add_reference(subtree)
        orig.commit("add subtree")

        self.run_bzr("branch source target")

        WorkingTree.open("target")
        self.assertRaises(errors.NotBranchError, WorkingTree.open, "target/subtree")

    def test_branch_with_nested_trees_no_recurse(self):
        orig = self.make_branch_and_tree("source", format="development-subtree")
        subtree = self.make_branch_and_tree("source/subtree")
        self.build_tree(["source/subtree/a"])
        subtree.add(["a"])
        subtree.commit("add subtree contents")
        orig.add_reference(subtree)
        orig.commit("add subtree")

        self.run_bzr("branch --no-recurse-nested source target")

        WorkingTree.open("target")
        self.addCleanup(subtree.lock_read().unlock)
        basis = subtree.basis_tree()
        self.addCleanup(basis.lock_read().unlock)
        self.assertRaises(errors.NotBranchError, WorkingTree.open, "target/subtree")


class TestBranchStacked(tests.TestCaseWithTransport):
    """Tests for branch --stacked."""

    def assertRevisionInRepository(self, repo_path, revid):
        """Check that a revision is in a repo, disregarding stacking."""
        repo = controldir.ControlDir.open(repo_path).open_repository()
        self.assertTrue(repo.has_revision(revid))

    def assertRevisionNotInRepository(self, repo_path, revid):
        """Check that a revision is not in a repo, disregarding stacking."""
        repo = controldir.ControlDir.open(repo_path).open_repository()
        self.assertFalse(repo.has_revision(revid))

    def assertRevisionsInBranchRepository(self, revid_list, branch_path):
        repo = branch.Branch.open(branch_path).repository
        self.assertEqual(set(revid_list), repo.has_revisions(revid_list))

    def test_branch_stacked_branch_not_stacked(self):
        """Branching a stacked branch is not stacked by default."""
        # We have a mainline
        trunk_tree = self.make_branch_and_tree("target", format="1.9")
        trunk_tree.commit("mainline")
        # and a branch from it which is stacked
        branch_tree = self.make_branch_and_tree("branch", format="1.9")
        branch_tree.branch.set_stacked_on_url(trunk_tree.branch.base)
        # with some work on it
        work_tree = trunk_tree.branch.controldir.sprout("local").open_workingtree()
        work_tree.commit("moar work plz")
        work_tree.branch.push(branch_tree.branch)
        # branching our local branch gives us a new stacked branch pointing at
        # mainline.
        out, err = self.run_bzr(["branch", "branch", "newbranch"])
        self.assertEqual("", out)
        self.assertEqual("Branched 2 revisions.\n", err)
        # it should have preserved the branch format, and so it should be
        # capable of supporting stacking, but not actually have a stacked_on
        # branch configured
        self.assertRaises(
            errors.NotStacked,
            controldir.ControlDir.open("newbranch").open_branch().get_stacked_on_url,
        )

    def test_branch_stacked_branch_stacked(self):
        """Asking to stack on a stacked branch does work."""
        # We have a mainline
        trunk_tree = self.make_branch_and_tree("target", format="1.9")
        trunk_revid = trunk_tree.commit("mainline")
        # and a branch from it which is stacked
        branch_tree = self.make_branch_and_tree("branch", format="1.9")
        branch_tree.branch.set_stacked_on_url(trunk_tree.branch.base)
        # with some work on it
        work_tree = trunk_tree.branch.controldir.sprout("local").open_workingtree()
        branch_revid = work_tree.commit("moar work plz")
        work_tree.branch.push(branch_tree.branch)
        # you can chain branches on from there
        out, err = self.run_bzr(["branch", "branch", "--stacked", "branch2"])
        self.assertEqual("", out)
        self.assertEqual(
            "Created new stacked branch referring to {}.\n".format(
                branch_tree.branch.base
            ),
            err,
        )
        self.assertEqual(
            branch_tree.branch.base, branch.Branch.open("branch2").get_stacked_on_url()
        )
        branch2_tree = WorkingTree.open("branch2")
        branch2_revid = work_tree.commit("work on second stacked branch")
        work_tree.branch.push(branch2_tree.branch)
        self.assertRevisionInRepository("branch2", branch2_revid)
        self.assertRevisionsInBranchRepository(
            [trunk_revid, branch_revid, branch2_revid], "branch2"
        )

    def test_branch_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree("mainline")
        original_revid = trunk_tree.commit("mainline")
        self.assertRevisionInRepository("mainline", original_revid)
        # and a branch from it which is stacked
        out, err = self.run_bzr(["branch", "--stacked", "mainline", "newbranch"])
        self.assertEqual("", out)
        self.assertEqual(
            "Created new stacked branch referring to {}.\n".format(
                trunk_tree.branch.base
            ),
            err,
        )
        self.assertRevisionNotInRepository("newbranch", original_revid)
        new_branch = branch.Branch.open("newbranch")
        self.assertEqual(trunk_tree.branch.base, new_branch.get_stacked_on_url())

    def test_branch_stacked_from_smart_server(self):
        # We can branch stacking on a smart server
        self.transport_server = test_server.SmartTCPServer_for_testing
        self.make_branch("mainline", format="1.9")
        _out, _err = self.run_bzr(
            ["branch", "--stacked", self.get_url("mainline"), "shallow"]
        )

    def test_branch_stacked_from_non_stacked_format(self):
        """The origin format doesn't support stacking."""
        trunk = self.make_branch("trunk", format="pack-0.92")
        _out, err = self.run_bzr(["branch", "--stacked", "trunk", "shallow"])
        # We should notify the user that we upgraded their format
        self.assertEqualDiff(
            "Source repository format does not support stacking, using format:\n"
            "  Packs 5 (adds stacking support, requires bzr 1.6)\n"
            "Source branch format does not support stacking, using format:\n"
            "  Branch format 7\n"
            "Doing on-the-fly conversion from RepositoryFormatKnitPack1() to RepositoryFormatKnitPack5().\n"
            "This may take some time. Upgrade the repositories to the same format for better performance.\n"
            "Created new stacked branch referring to {}.\n".format(trunk.base),
            err,
        )

    def test_branch_stacked_from_rich_root_non_stackable(self):
        trunk = self.make_branch("trunk", format="rich-root-pack")
        _out, err = self.run_bzr(["branch", "--stacked", "trunk", "shallow"])
        # We should notify the user that we upgraded their format
        self.assertEqualDiff(
            "Source repository format does not support stacking, using format:\n"
            "  Packs 5 rich-root (adds stacking support, requires bzr 1.6.1)\n"
            "Source branch format does not support stacking, using format:\n"
            "  Branch format 7\n"
            "Doing on-the-fly conversion from RepositoryFormatKnitPack4() to RepositoryFormatKnitPack5RichRoot().\n"
            "This may take some time. Upgrade the repositories to the same format for better performance.\n"
            "Created new stacked branch referring to {}.\n".format(trunk.base),
            err,
        )


class TestRemoteBranch(TestCaseWithSFTPServer):
    def setUp(self):
        super().setUp()
        self.skipTest("tests often hang - see pad.lv/1997033")
        tree = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/file", b"file content\n")])
        tree.add("file")
        tree.commit("file created")

    def test_branch_local_remote(self):
        self.run_bzr(["branch", "branch", self.get_url("remote")])
        t = self.get_transport()
        # Ensure that no working tree what created remotely
        self.assertFalse(t.has("remote/file"))

    def test_branch_remote_remote(self):
        # Light cheat: we access the branch remotely
        self.run_bzr(["branch", self.get_url("branch"), self.get_url("remote")])
        t = self.get_transport()
        # Ensure that no working tree what created remotely
        self.assertFalse(t.has("remote/file"))


class TestBranchParentLocation(test_switch.TestSwitchParentLocationBase):
    def _checkout_and_branch(self, option=""):
        self.script_runner.run_script(
            self,
            """
                $ brz checkout {option} repo/trunk checkout
                $ cd checkout
                $ brz branch --switch ../repo/trunk ../repo/branched
                2>Branched 0 revisions.
                2>Tree is up to date at revision 0.
                2>Switched to branch:...branched...
                $ cd ..
                """.format(**locals()),
        )
        bound_branch = branch.Branch.open_containing("checkout")[0]
        master_branch = branch.Branch.open_containing("repo/branched")[0]
        return (bound_branch, master_branch)

    def test_branch_switch_parent_lightweight(self):
        """Lightweight checkout using brz branch --switch."""
        bb, mb = self._checkout_and_branch(option="--lightweight")
        self.assertParent("repo/trunk", bb)
        self.assertParent("repo/trunk", mb)

    def test_branch_switch_parent_heavyweight(self):
        """Heavyweight checkout using brz branch --switch."""
        bb, mb = self._checkout_and_branch()
        self.assertParent("repo/trunk", bb)
        self.assertParent("repo/trunk", mb)

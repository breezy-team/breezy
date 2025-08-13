# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2007 Canonical Ltd
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


"""Tests for interfacing with a Git Branch."""

import os

import dulwich
from dulwich.objects import Commit, Tag
from dulwich.repo import Repo as GitRepo

from ... import errors, revision, urlutils
from ...branch import Branch, InterBranch, UnstackableBranchFormat
from ...controldir import ControlDir
from ...repository import Repository
from .. import branch, tests
from ..dir import LocalGitControlDirFormat
from ..mapping import default_mapping


class TestGitBranch(tests.TestCaseInTempDir):
    def test_open_by_ref(self):
        GitRepo.init(".")
        url = "{},ref={}".format(
            urlutils.local_path_to_url(self.test_dir),
            urlutils.quote("refs/remotes/origin/unstable", safe=""),
        )
        d = ControlDir.open(url)
        b = d.create_branch()
        self.assertEqual(b.ref, b"refs/remotes/origin/unstable")

    def test_open_existing(self):
        GitRepo.init(".")
        d = ControlDir.open(".")
        thebranch = d.create_branch()
        self.assertIsInstance(thebranch, branch.GitBranch)

    def test_repr(self):
        GitRepo.init(".")
        d = ControlDir.open(".")
        thebranch = d.create_branch()
        self.assertEqual(
            f"<LocalGitBranch('{urlutils.local_path_to_url(self.test_dir)}/', 'master')>",
            repr(thebranch),
        )

    def test_last_revision_is_null(self):
        GitRepo.init(".")
        thedir = ControlDir.open(".")
        thebranch = thedir.create_branch()
        self.assertEqual(revision.NULL_REVISION, thebranch.last_revision())
        self.assertEqual((0, revision.NULL_REVISION), thebranch.last_revision_info())

    def simple_commit_a(self):
        r = GitRepo.init(".")
        self.build_tree(["a"])
        worktree = r.get_worktree()
        worktree.stage(["a"])
        return worktree.do_commit(b"a", committer=b"Somebody <foo@example.com>")

    def test_last_revision_is_valid(self):
        head = self.simple_commit_a()
        thebranch = Branch.open(".")
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(head), thebranch.last_revision()
        )

    def test_last_revision_info(self):
        self.simple_commit_a()
        self.build_tree(["b"])
        r = GitRepo(".")
        self.addCleanup(r.close)
        worktree = r.get_worktree()
        worktree.stage("b")
        revb = worktree.do_commit(b"b", committer=b"Somebody <foo@example.com>")

        thebranch = Branch.open(".")
        self.assertEqual(
            (2, default_mapping.revision_id_foreign_to_bzr(revb)),
            thebranch.last_revision_info(),
        )

    def test_tag_annotated(self):
        reva = self.simple_commit_a()
        o = Tag()
        o.name = b"foo"
        o.tagger = b"Jelmer <foo@example.com>"
        o.message = b"add tag"
        o.object = (Commit, reva)
        o.tag_timezone = 0
        o.tag_time = 42
        r = GitRepo(".")
        self.addCleanup(r.close)
        r.object_store.add_object(o)
        r[b"refs/tags/foo"] = o.id
        thebranch = Branch.open(".")
        self.assertEqual(
            {"foo": default_mapping.revision_id_foreign_to_bzr(reva)},
            thebranch.tags.get_tag_dict(),
        )

    def test_tag(self):
        reva = self.simple_commit_a()
        r = GitRepo(".")
        self.addCleanup(r.close)
        r.refs[b"refs/tags/foo"] = reva
        thebranch = Branch.open(".")
        self.assertEqual(
            {"foo": default_mapping.revision_id_foreign_to_bzr(reva)},
            thebranch.tags.get_tag_dict(),
        )


class TestWithGitBranch(tests.TestCaseWithTransport):
    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        dulwich.repo.Repo.create(self.test_dir)
        d = ControlDir.open(self.test_dir)
        self.git_branch = d.create_branch()

    def test_get_parent(self):
        self.assertIs(None, self.git_branch.get_parent())

    def test_get_stacked_on_url(self):
        self.assertRaises(UnstackableBranchFormat, self.git_branch.get_stacked_on_url)

    def test_get_physical_lock_status(self):
        self.assertFalse(self.git_branch.get_physical_lock_status())


class TestLocalGitBranchFormat(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.format = branch.LocalGitBranchFormat()

    def test_get_format_description(self):
        self.assertEqual("Local Git Branch", self.format.get_format_description())

    def test_get_network_name(self):
        self.assertEqual(b"git", self.format.network_name())

    def test_supports_tags(self):
        self.assertTrue(self.format.supports_tags())


class BranchTests(tests.TestCaseInTempDir):
    def make_onerev_branch(self):
        os.mkdir("d")
        os.chdir("d")
        GitRepo.init(".")
        bb = tests.GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", False)
        mark = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        return os.path.abspath("d"), gitsha

    def make_tworev_branch(self):
        os.mkdir("d")
        os.chdir("d")
        GitRepo.init(".")
        bb = tests.GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", False)
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        marks = bb.finish()
        os.chdir("..")
        return "d", (marks[mark1], marks[mark2])

    def clone_git_branch(self, from_url, to_url):
        from_dir = ControlDir.open(from_url)
        to_dir = from_dir.sprout(to_url)
        return to_dir.open_branch()

    def test_single_rev(self):
        path, gitsha = self.make_onerev_branch()
        oldrepo = Repository.open(path)
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        self.assertEqual(gitsha, oldrepo._git.get_refs()[b"refs/heads/master"])
        newbranch = self.clone_git_branch(path, "f")
        self.assertEqual([revid], newbranch.repository.all_revision_ids())

    def test_sprouted_tags(self):
        path, gitsha = self.make_onerev_branch()
        r = GitRepo(path)
        self.addCleanup(r.close)
        r.refs[b"refs/tags/lala"] = r.head()
        oldrepo = Repository.open(path)
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        newbranch = self.clone_git_branch(path, "f")
        self.assertEqual({"lala": revid}, newbranch.tags.get_tag_dict())
        self.assertEqual([revid], newbranch.repository.all_revision_ids())

    def test_sprouted_ghost_tags(self):
        path, gitsha = self.make_onerev_branch()
        r = GitRepo(path)
        self.addCleanup(r.close)
        r.refs[b"refs/tags/lala"] = b"aa" * 20
        oldrepo = Repository.open(path)
        oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        warnings, newbranch = self.callCatchWarnings(self.clone_git_branch, path, "f")
        self.assertEqual({}, newbranch.tags.get_tag_dict())
        # Dulwich raises a UserWarning for tags with invalid target
        self.assertIn(
            ("ref refs/tags/lala points at non-present sha " + ("aa" * 20),),
            [w.args for w in warnings],
        )

    def test_interbranch_pull_submodule(self):
        path = "d"
        os.mkdir(path)
        os.chdir(path)
        GitRepo.init(".")
        bb = tests.GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", False)
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        bb.set_submodule("core", b"102ee7206ebc4227bec8ac02450972e6738f4a33")
        bb.set_file(
            ".gitmodules",
            b"""\
[submodule "core"]
  path = core
  url = https://github.com/phhusson/QuasselC.git
""",
            False,
        )
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        marks = bb.finish()
        os.chdir("..")
        marks[mark1]
        gitsha2 = marks[mark2]
        oldrepo = Repository.open(path)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch("g")
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull()
        self.assertEqual(revid2, newbranch.last_revision())
        self.assertEqual(
            ("https://github.com/phhusson/QuasselC.git", "core"),
            newbranch.get_reference_info(newbranch.basis_tree().path2id("core")),
        )

    def test_interbranch_pull(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch("g")
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull()
        self.assertEqual(revid2, newbranch.last_revision())

    def test_interbranch_pull_noop(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch("g")
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull()
        # This is basically "assertNotRaises"
        inter_branch.pull()
        self.assertEqual(revid2, newbranch.last_revision())

    def test_interbranch_pull_stop_revision(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        newbranch = self.make_branch("g")
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull(stop_revision=revid1)
        self.assertEqual(revid1, newbranch.last_revision())

    def test_interbranch_pull_with_tags(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        gitrepo = GitRepo(path)
        self.addCleanup(gitrepo.close)
        gitrepo.refs[b"refs/tags/sometag"] = gitsha2
        oldrepo = Repository.open(path)
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch("g")
        source_branch = Branch.open(path)
        source_branch.get_config().set_user_option("branch.fetch_tags", True)
        inter_branch = InterBranch.get(source_branch, newbranch)
        inter_branch.pull(stop_revision=revid1)
        self.assertEqual(revid1, newbranch.last_revision())
        self.assertTrue(newbranch.repository.has_revision(revid2))

    def test_bzr_branch_bound_to_git(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        wt = Branch.open(path).create_checkout("co")
        self.build_tree_contents([("co/foobar", b"blah")])
        self.assertRaises(
            errors.NoRoundtrippingSupport, wt.commit, "commit from bound branch."
        )
        revid = wt.commit("commit from bound branch.", lossy=True)
        self.assertEqual(revid, wt.branch.last_revision())
        self.assertEqual(revid, wt.branch.get_master_branch().last_revision())

    def test_interbranch_pull_older(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch("g")
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull(stop_revision=revid2)
        inter_branch.pull(stop_revision=revid1)
        self.assertEqual(revid2, newbranch.last_revision())


class ForeignTestsBranchFactory:
    def make_empty_branch(self, transport):
        d = LocalGitControlDirFormat().initialize_on_transport(transport)
        return d.create_branch()

    make_branch = make_empty_branch

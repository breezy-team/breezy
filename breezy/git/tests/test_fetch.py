# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests from fetching from git into bzr."""

import os
import stat
import time

from dulwich.objects import S_IFGITLINK, Blob, Tag, Tree
from dulwich.repo import Repo as GitRepo

from ... import osutils
from ...branch import Branch
from ...bzr import knit, versionedfile
from ...bzr.inventory import Inventory
from ...controldir import ControlDir
from ...repository import Repository
from ...tests import TestCaseWithTransport
from ..fetch import import_git_blob, import_git_submodule, import_git_tree
from ..mapping import DEFAULT_FILE_MODE, BzrGitMappingv1
from . import GitBranchBuilder


class RepositoryFetchTests:
    def make_git_repo(self, path):
        os.mkdir(path)
        return GitRepo.init(os.path.abspath(path))

    def clone_git_repo(self, from_url, to_url, revision_id=None):
        oldrepos = self.open_git_repo(from_url)
        dir = ControlDir.create(to_url)
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos, revision_id=revision_id)
        return newrepos

    def test_empty(self):
        self.make_git_repo("d")
        newrepos = self.clone_git_repo("d", "f")
        self.assertEqual([], newrepos.all_revision_ids())

    def make_onerev_branch(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", False)
        mark = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        return "d", gitsha

    def test_single_rev(self):
        path, gitsha = self.make_onerev_branch()
        oldrepo = self.open_git_repo(path)
        newrepo = self.clone_git_repo(path, "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        self.assertEqual([revid], newrepo.all_revision_ids())

    def test_single_rev_specific(self):
        path, gitsha = self.make_onerev_branch()
        oldrepo = self.open_git_repo(path)
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        newrepo = self.clone_git_repo(path, "f", revision_id=revid)
        self.assertEqual([revid], newrepo.all_revision_ids())

    def test_incremental(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", False)
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        bb.set_file("foobar", b"fooll\nbar\n", False)
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"nextmsg")
        marks = bb.finish()
        gitsha1 = marks[mark1]
        gitsha2 = marks[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        newrepo = self.clone_git_repo("d", "f", revision_id=revid1)
        self.assertEqual([revid1], newrepo.all_revision_ids())
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newrepo.fetch(oldrepo, revision_id=revid2)
        self.assertEqual({revid1, revid2}, set(newrepo.all_revision_ids()))

    def test_dir_becomes_symlink(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("mylink/somefile", b"foo\nbar\n", False)
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg1")
        bb.delete_entry("mylink/somefile")
        bb.set_symlink("mylink", "target/")
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg2")
        marks = bb.finish()
        gitsha1 = marks[mark1]
        gitsha2 = marks[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        tree1 = newrepo.revision_tree(revid1)
        tree2 = newrepo.revision_tree(revid2)
        self.assertEqual(revid1, tree1.get_file_revision("mylink"))
        self.assertEqual("directory", tree1.kind("mylink"))
        self.assertEqual(None, tree1.get_symlink_target("mylink"))
        self.assertEqual(revid2, tree2.get_file_revision("mylink"))
        self.assertEqual("symlink", tree2.kind("mylink"))
        self.assertEqual("target/", tree2.get_symlink_target("mylink"))

    def test_symlink_becomes_dir(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_symlink("mylink", "target/")
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg1")
        bb.delete_entry("mylink")
        bb.set_file("mylink/somefile", b"foo\nbar\n", False)
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg2")
        marks = bb.finish()
        gitsha1 = marks[mark1]
        gitsha2 = marks[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        tree1 = newrepo.revision_tree(revid1)
        tree2 = newrepo.revision_tree(revid2)
        self.assertEqual(revid1, tree1.get_file_revision("mylink"))
        self.assertEqual("symlink", tree1.kind("mylink"))
        self.assertEqual("target/", tree1.get_symlink_target("mylink"))
        self.assertEqual(revid2, tree2.get_file_revision("mylink"))
        self.assertEqual("directory", tree2.kind("mylink"))
        self.assertEqual(None, tree2.get_symlink_target("mylink"))

    def test_changing_symlink(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_symlink("mylink", "target")
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg1")
        bb.set_symlink("mylink", "target/")
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg2")
        marks = bb.finish()
        gitsha1 = marks[mark1]
        gitsha2 = marks[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        tree1 = newrepo.revision_tree(revid1)
        tree2 = newrepo.revision_tree(revid2)
        self.assertEqual(revid1, tree1.get_file_revision("mylink"))
        self.assertEqual("target", tree1.get_symlink_target("mylink"))
        self.assertEqual(revid2, tree2.get_file_revision("mylink"))
        self.assertEqual("target/", tree2.get_symlink_target("mylink"))

    def test_executable(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", True)
        bb.set_file("notexec", b"foo\nbar\n", False)
        mark = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename("foobar"))
        self.assertEqual(True, tree.is_executable("foobar"))
        self.assertTrue(tree.has_filename("notexec"))
        self.assertEqual(False, tree.is_executable("notexec"))

    def test_becomes_executable(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", b"foo\nbar\n", False)
        bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        bb.set_file("foobar", b"foo\nbar\n", True)
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        gitsha2 = bb.finish()[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename("foobar"))
        self.assertEqual(True, tree.is_executable("foobar"))
        self.assertEqual(revid, tree.get_file_revision("foobar"))

    def test_into_stacked_on(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", b"foo\n", False)
        mark1 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg1")
        gitsha1 = bb.finish()[mark1]
        os.chdir("..")
        stacked_on = self.clone_git_repo("d", "stacked-on")
        oldrepo = Repository.open("d")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        self.assertEqual([revid1], stacked_on.all_revision_ids())
        b = stacked_on.controldir.create_branch()
        b.generate_revision_history(revid1)
        self.assertEqual(b.last_revision(), revid1)
        tree = self.make_branch_and_tree("stacked")
        tree.branch.set_stacked_on_url(b.user_url)
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("barbar", b"bar\n", False)
        bb.set_file("foo/blie/bla", b"bla\n", False)
        mark2 = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg2")
        gitsha2 = bb.finish()[mark2]
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        os.chdir("..")
        tree.branch.fetch(Branch.open("d"))
        tree.branch.repository.check()
        self.addCleanup(tree.lock_read().unlock)
        self.assertEqual(
            {(revid2,)}, tree.branch.repository.revisions.without_fallbacks().keys()
        )
        self.assertEqual(
            {revid1, revid2}, set(tree.branch.repository.all_revision_ids())
        )

    def test_non_ascii_characters(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foőbar", b"foo\nbar\n", False)
        mark = bb.commit(b"Somebody <somebody@someorg.org>", b"mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename("foőbar"))

    def test_tagged_tree(self):
        r = self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", b"fooll\nbar\n", False)
        mark = bb.commit(b"Somebody <somebody@someorg.org>", b"nextmsg")
        marks = bb.finish()
        gitsha = marks[mark]
        tag = Tag()
        tag.name = b"sometag"
        tag.tag_time = int(time.time())
        tag.tag_timezone = 0
        tag.tagger = b"Somebody <somebody@example.com>"
        tag.message = b"Created tag pointed at tree"
        tag.object = (Tree, r[gitsha].tree)
        r.object_store.add_object(tag)
        r[b"refs/tags/sometag"] = tag
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        newrepo = self.clone_git_repo("d", "f")
        self.assertEqual({revid}, set(newrepo.all_revision_ids()))


class LocalRepositoryFetchTests(RepositoryFetchTests, TestCaseWithTransport):
    def open_git_repo(self, path):
        return Repository.open(path)


class DummyStoreUpdater:
    def add_object(self, obj, ie, path):
        pass

    def finish(self):
        pass


class ImportObjects(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self._mapping = BzrGitMappingv1()
        factory = knit.make_file_factory(True, versionedfile.PrefixMapper())
        self._texts = factory(self.get_transport("texts"))

    def test_import_blob_missing_in_one_parent(self):
        builder = self.make_branch_builder("br")
        builder.start_series()
        rev_root = builder.build_snapshot(
            None, [("add", ("", b"rootid", "directory", ""))]
        )
        rev1 = builder.build_snapshot(
            [rev_root],
            [
                (
                    "add",
                    ("bla", self._mapping.generate_file_id("bla"), "file", b"content"),
                )
            ],
        )
        rev2 = builder.build_snapshot([rev_root], [])
        builder.finish_series()
        branch = builder.get_branch()

        blob = Blob.from_string(b"bar")
        objs = {"blobname": blob}
        import_git_blob(
            self._texts,
            self._mapping,
            b"bla",
            b"bla",
            (None, "blobname"),
            branch.repository.revision_tree(rev1),
            b"rootid",
            b"somerevid",
            [branch.repository.revision_tree(r) for r in [rev1, rev2]],
            objs.__getitem__,
            (None, DEFAULT_FILE_MODE),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual({(b"git:bla", b"somerevid")}, self._texts.keys())

    def test_import_blob_simple(self):
        blob = Blob.from_string(b"bar")
        objs = {"blobname": blob}
        ret = import_git_blob(
            self._texts,
            self._mapping,
            b"bla",
            b"bla",
            (None, "blobname"),
            None,
            None,
            b"somerevid",
            [],
            objs.__getitem__,
            (None, DEFAULT_FILE_MODE),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual({(b"git:bla", b"somerevid")}, self._texts.keys())
        self.assertEqual(
            next(
                self._texts.get_record_stream(
                    [(b"git:bla", b"somerevid")], "unordered", True
                )
            ).get_bytes_as("fulltext"),
            b"bar",
        )
        self.assertEqual(1, len(ret))
        self.assertEqual(None, ret[0][0])
        self.assertEqual("bla", ret[0][1])
        ie = ret[0][3]
        self.assertEqual(False, ie.executable)
        self.assertEqual("file", ie.kind)
        self.assertEqual(b"somerevid", ie.revision)
        self.assertEqual(osutils.sha_strings([b"bar"]), ie.text_sha1)

    def test_import_tree_empty_root(self):
        tree = Tree()
        ret, child_modes = import_git_tree(
            self._texts,
            self._mapping,
            b"",
            b"",
            (None, tree.id),
            None,
            None,
            b"somerevid",
            [],
            {tree.id: tree}.__getitem__,
            (None, stat.S_IFDIR),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual(child_modes, {})
        self.assertEqual({(b"TREE_ROOT", b"somerevid")}, self._texts.keys())
        self.assertEqual(1, len(ret))
        self.assertEqual(None, ret[0][0])
        self.assertEqual("", ret[0][1])
        ie = ret[0][3]
        self.assertEqual(False, ie.executable)
        self.assertEqual("directory", ie.kind)
        self.assertEqual({}, ie.children)
        self.assertEqual(b"somerevid", ie.revision)
        self.assertEqual(None, ie.text_sha1)

    def test_import_tree_empty(self):
        tree = Tree()
        ret, child_modes = import_git_tree(
            self._texts,
            self._mapping,
            b"bla",
            b"bla",
            (None, tree.id),
            None,
            None,
            b"somerevid",
            [],
            {tree.id: tree}.__getitem__,
            (None, stat.S_IFDIR),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual(child_modes, {})
        self.assertEqual({(b"git:bla", b"somerevid")}, self._texts.keys())
        self.assertEqual(1, len(ret))
        self.assertEqual(None, ret[0][0])
        self.assertEqual("bla", ret[0][1])
        ie = ret[0][3]
        self.assertEqual("directory", ie.kind)
        self.assertEqual(False, ie.executable)
        self.assertEqual({}, ie.children)
        self.assertEqual(b"somerevid", ie.revision)
        self.assertEqual(None, ie.text_sha1)

    def test_import_tree_with_file(self):
        blob = Blob.from_string(b"bar1")
        tree = Tree()
        tree.add(b"foo", stat.S_IFREG | 0o644, blob.id)
        objects = {blob.id: blob, tree.id: tree}
        ret, child_modes = import_git_tree(
            self._texts,
            self._mapping,
            b"bla",
            b"bla",
            (None, tree.id),
            None,
            None,
            b"somerevid",
            [],
            objects.__getitem__,
            (None, stat.S_IFDIR),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual(child_modes, {})
        self.assertEqual(2, len(ret))
        self.assertEqual(None, ret[0][0])
        self.assertEqual("bla", ret[0][1])
        self.assertEqual(None, ret[1][0])
        self.assertEqual("bla/foo", ret[1][1])
        ie = ret[0][3]
        self.assertEqual("directory", ie.kind)
        ie = ret[1][3]
        self.assertEqual("file", ie.kind)
        self.assertEqual(b"git:bla/foo", ie.file_id)
        self.assertEqual(b"somerevid", ie.revision)
        self.assertEqual(osutils.sha_strings([b"bar1"]), ie.text_sha1)
        self.assertEqual(False, ie.executable)

    def test_import_tree_with_unusual_mode_file(self):
        blob = Blob.from_string(b"bar1")
        tree = Tree()
        tree.add(b"foo", stat.S_IFREG | 0o664, blob.id)
        objects = {blob.id: blob, tree.id: tree}
        _ret, child_modes = import_git_tree(
            self._texts,
            self._mapping,
            b"bla",
            b"bla",
            (None, tree.id),
            None,
            None,
            b"somerevid",
            [],
            objects.__getitem__,
            (None, stat.S_IFDIR),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual(child_modes, {b"bla/foo": stat.S_IFREG | 0o664})

    def test_import_tree_with_file_exe(self):
        blob = Blob.from_string(b"bar")
        tree = Tree()
        tree.add(b"foo", 0o100755, blob.id)
        objects = {blob.id: blob, tree.id: tree}
        ret, child_modes = import_git_tree(
            self._texts,
            self._mapping,
            b"",
            b"",
            (None, tree.id),
            None,
            None,
            b"somerevid",
            [],
            objects.__getitem__,
            (None, stat.S_IFDIR),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual(child_modes, {})
        self.assertEqual(2, len(ret))
        self.assertEqual(None, ret[0][0])
        self.assertEqual("", ret[0][1])
        self.assertEqual(None, ret[1][0])
        self.assertEqual("foo", ret[1][1])
        ie = ret[0][3]
        self.assertEqual("directory", ie.kind)
        ie = ret[1][3]
        self.assertEqual("file", ie.kind)
        self.assertEqual(True, ie.executable)

    def test_directory_converted_to_submodule(self):
        base_inv = Inventory()
        base_inv.add_path("foo", "directory")
        base_inv.add_path("foo/bar", "file")
        othertree = Blob.from_string(b"someotherthing")
        blob = Blob.from_string(b"bar")
        tree = Tree()
        tree.add(b"bar", 0o160000, blob.id)
        objects = {tree.id: tree}
        ret, child_modes = import_git_submodule(
            self._texts,
            self._mapping,
            b"foo",
            b"foo",
            (tree.id, othertree.id),
            base_inv,
            base_inv.root.file_id,
            b"somerevid",
            [],
            objects.__getitem__,
            (stat.S_IFDIR | 0o755, S_IFGITLINK),
            DummyStoreUpdater(),
            self._mapping.generate_file_id,
        )
        self.assertEqual(child_modes, {})
        self.assertEqual(2, len(ret))
        self.assertEqual(ret[0], ("foo/bar", None, base_inv.path2id("foo/bar"), None))
        self.assertEqual(
            ret[1][:3], ("foo", "foo", self._mapping.generate_file_id("foo"))
        )
        ie = ret[1][3]
        self.assertEqual(ie.kind, "tree-reference")

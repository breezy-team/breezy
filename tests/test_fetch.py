# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
# -*- coding: utf-8 -*-
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from dulwich.objects import (
    Blob,
    Tag,
    Tree,
    S_IFGITLINK,
    )
from dulwich.repo import (
    Repo as GitRepo,
    )
import os
import stat
import time

from .... import (
    knit,
    osutils,
    versionedfile,
    )
from ....branch import (
    Branch,
    )
from ....bzrdir import (
    BzrDir,
    )
from ....inventory import (
    Inventory,
    )
from ....repository import (
    Repository,
    )
from ....tests import (
    TestCaseWithTransport,
    )

from ..fetch import (
    import_git_blob,
    import_git_tree,
    import_git_submodule,
    )
from ..mapping import (
    BzrGitMappingv1,
    DEFAULT_FILE_MODE,
    )
from . import (
    GitBranchBuilder,
    )


class RepositoryFetchTests(object):

    def make_git_repo(self, path):
        os.mkdir(path)
        return GitRepo.init(os.path.abspath(path))

    def clone_git_repo(self, from_url, to_url, revision_id=None):
        oldrepos = self.open_git_repo(from_url)
        dir = BzrDir.create(to_url)
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos, revision_id=revision_id)
        return newrepos

    def test_empty(self):
        self.make_git_repo("d")
        newrepos = self.clone_git_repo("d", "f")
        self.assertEquals([], newrepos.all_revision_ids())

    def make_onerev_branch(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        return "d", gitsha

    def test_single_rev(self):
        path, gitsha = self.make_onerev_branch()
        oldrepo = self.open_git_repo(path)
        newrepo = self.clone_git_repo(path, "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        self.assertEquals([revid], newrepo.all_revision_ids())

    def test_single_rev_specific(self):
        path, gitsha = self.make_onerev_branch()
        oldrepo = self.open_git_repo(path)
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        newrepo = self.clone_git_repo(path, "f", revision_id=revid)
        self.assertEquals([revid], newrepo.all_revision_ids())

    def test_incremental(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", False)
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        bb.set_file("foobar", "fooll\nbar\n", False)
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "nextmsg")
        marks = bb.finish()
        gitsha1 = marks[mark1]
        gitsha2 = marks[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        newrepo = self.clone_git_repo("d", "f", revision_id=revid1)
        self.assertEquals([revid1], newrepo.all_revision_ids())
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newrepo.fetch(oldrepo, revision_id=revid2)
        self.assertEquals(set([revid1, revid2]), set(newrepo.all_revision_ids()))

    def test_dir_becomes_symlink(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("mylink/somefile", "foo\nbar\n", False)
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg1")
        bb.set_symlink("mylink", "target/")
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "mymsg2")
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
        fileid = tree1.path2id("mylink")
        self.assertEquals(revid1, tree1.get_file_revision(fileid))
        self.assertEquals("directory", tree1.kind(fileid))
        self.assertEquals(None, tree1.get_symlink_target(fileid))
        self.assertEquals(revid2, tree2.get_file_revision(fileid))
        self.assertEquals("symlink", tree2.kind(fileid))
        self.assertEquals("target/", tree2.get_symlink_target(fileid))

    def test_symlink_becomes_dir(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_symlink("mylink", "target/")
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg1")
        bb.set_file("mylink/somefile", "foo\nbar\n", False)
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "mymsg2")
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
        fileid = tree1.path2id("mylink")
        self.assertEquals(revid1, tree1.get_file_revision(fileid))
        self.assertEquals("symlink", tree1.kind(fileid))
        self.assertEquals("target/", tree1.get_symlink_target(fileid))
        self.assertEquals(revid2, tree2.get_file_revision(fileid))
        self.assertEquals("directory", tree2.kind(fileid))
        self.assertEquals(None, tree2.get_symlink_target(fileid))

    def test_changing_symlink(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_symlink("mylink", "target")
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg1")
        bb.set_symlink("mylink", "target/")
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "mymsg2")
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
        fileid = tree1.path2id("mylink")
        self.assertEquals(revid1, tree1.get_file_revision(fileid))
        self.assertEquals("target", tree1.get_symlink_target(fileid))
        self.assertEquals(revid2, tree2.get_file_revision(fileid))
        self.assertEquals("target/", tree2.get_symlink_target(fileid))

    def test_executable(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", True)
        bb.set_file("notexec", "foo\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename("foobar"))
        self.assertEquals(True, tree.is_executable(tree.path2id("foobar")))
        self.assertTrue(tree.has_filename("notexec"))
        self.assertEquals(False, tree.is_executable(tree.path2id("notexec")))

    def test_becomes_executable(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", False)
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        bb.set_file("foobar", "foo\nbar\n", True)
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha2 = bb.finish()[mark2]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename("foobar"))
        fileid = tree.path2id("foobar")
        self.assertEquals(True, tree.is_executable(fileid))
        self.assertEquals(revid, tree.get_file_revision(fileid))

    def test_into_stacked_on(self):
        r = self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file(u"foobar", "foo\n", False)
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg1")
        gitsha1 = bb.finish()[mark1]
        os.chdir("..")
        stacked_on = self.clone_git_repo("d", "stacked-on")
        oldrepo = Repository.open("d")
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        self.assertEquals([revid1], stacked_on.all_revision_ids())
        b = stacked_on.bzrdir.create_branch()
        b.generate_revision_history(revid1)
        self.assertEquals(b.last_revision(), revid1)
        tree = self.make_branch_and_tree("stacked")
        tree.branch.set_stacked_on_url(b.user_url)
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file(u"barbar", "bar\n", False)
        bb.set_file(u"foo/blie/bla", "bla\n", False)
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "mymsg2")
        gitsha2 = bb.finish()[mark2]
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        os.chdir("..")
        tree.branch.fetch(Branch.open("d"))
        tree.branch.repository.check()
        self.addCleanup(tree.lock_read().unlock)
        self.assertEquals(
            set([(revid2,)]),
            tree.branch.repository.revisions.without_fallbacks().keys())
        self.assertEquals(
            set([revid1, revid2]),
            set(tree.branch.repository.all_revision_ids()))

    def test_non_ascii_characters(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file(u"foőbar", "foo\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename(u"foőbar"))

    def test_tagged_tree(self):
        r = self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "fooll\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "nextmsg")
        marks = bb.finish()
        gitsha = marks[mark]
        tag = Tag()
        tag.name = "sometag"
        tag.tag_time = int(time.time())
        tag.tag_timezone = 0
        tag.tagger = "Somebody <somebody@example.com>"
        tag.message = "Created tag pointed at tree"
        tag.object = (Tree, r[gitsha].tree)
        r.object_store.add_object(tag)
        r["refs/tags/sometag"] = tag
        os.chdir("..")
        oldrepo = self.open_git_repo("d")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        newrepo = self.clone_git_repo("d", "f")
        self.assertEquals(set([revid]), set(newrepo.all_revision_ids()))


class LocalRepositoryFetchTests(RepositoryFetchTests, TestCaseWithTransport):

    def open_git_repo(self, path):
        return Repository.open(path)


class DummyStoreUpdater(object):

    def add_object(self, obj, ie, path):
        pass

    def finish(self):
        pass


class ImportObjects(TestCaseWithTransport):

    def setUp(self):
        super(ImportObjects, self).setUp()
        self._mapping = BzrGitMappingv1()
        factory = knit.make_file_factory(True, versionedfile.PrefixMapper())
        self._texts = factory(self.get_transport('texts'))

    def test_import_blob_simple(self):
        blob = Blob.from_string("bar")
        base_inv = Inventory()
        objs = { "blobname": blob}
        ret = import_git_blob(self._texts, self._mapping, "bla", "bla",
            (None, "blobname"), 
            base_inv, None, "somerevid", [], objs.__getitem__, 
            (None, DEFAULT_FILE_MODE), DummyStoreUpdater(),
            self._mapping.generate_file_id)
        self.assertEquals(set([('bla', 'somerevid')]), self._texts.keys())
        self.assertEquals(self._texts.get_record_stream([('bla', 'somerevid')],
            "unordered", True).next().get_bytes_as("fulltext"), "bar")
        self.assertEquals(1, len(ret)) 
        self.assertEquals(None, ret[0][0])
        self.assertEquals("bla", ret[0][1])
        ie = ret[0][3]
        self.assertEquals(False, ie.executable)
        self.assertEquals("file", ie.kind)
        self.assertEquals("somerevid", ie.revision)
        self.assertEquals(osutils.sha_strings(["bar"]), ie.text_sha1)

    def test_import_tree_empty_root(self):
        base_inv = Inventory(root_id=None)
        tree = Tree()
        ret, child_modes = import_git_tree(self._texts, self._mapping, "", "",
               (None, tree.id), base_inv, 
               None, "somerevid", [], {tree.id: tree}.__getitem__,
               (None, stat.S_IFDIR), DummyStoreUpdater(),
               self._mapping.generate_file_id)
        self.assertEquals(child_modes, {})
        self.assertEquals(set([("TREE_ROOT", 'somerevid')]), self._texts.keys())
        self.assertEquals(1, len(ret))
        self.assertEquals(None, ret[0][0])
        self.assertEquals("", ret[0][1])
        ie = ret[0][3]
        self.assertEquals(False, ie.executable)
        self.assertEquals("directory", ie.kind)
        self.assertEquals({}, ie.children)
        self.assertEquals("somerevid", ie.revision)
        self.assertEquals(None, ie.text_sha1)

    def test_import_tree_empty(self):
        base_inv = Inventory()
        tree = Tree()
        ret, child_modes = import_git_tree(self._texts, self._mapping, "bla", "bla",
           (None, tree.id), base_inv, None, "somerevid", [], 
           { tree.id: tree }.__getitem__,
           (None, stat.S_IFDIR), DummyStoreUpdater(),
           self._mapping.generate_file_id)
        self.assertEquals(child_modes, {})
        self.assertEquals(set([("bla", 'somerevid')]), self._texts.keys())
        self.assertEquals(1, len(ret))
        self.assertEquals(None, ret[0][0])
        self.assertEquals("bla", ret[0][1])
        ie = ret[0][3]
        self.assertEquals("directory", ie.kind)
        self.assertEquals(False, ie.executable)
        self.assertEquals({}, ie.children)
        self.assertEquals("somerevid", ie.revision)
        self.assertEquals(None, ie.text_sha1)

    def test_import_tree_with_file(self):
        base_inv = Inventory()
        blob = Blob.from_string("bar1")
        tree = Tree()
        tree.add("foo", stat.S_IFREG | 0644, blob.id)
        objects = { blob.id: blob, tree.id: tree }
        ret, child_modes = import_git_tree(self._texts, self._mapping, "bla", "bla",
                (None, tree.id), base_inv, None, "somerevid", [],
            objects.__getitem__, (None, stat.S_IFDIR), DummyStoreUpdater(),
            self._mapping.generate_file_id)
        self.assertEquals(child_modes, {})
        self.assertEquals(2, len(ret))
        self.assertEquals(None, ret[0][0])
        self.assertEquals("bla", ret[0][1])
        self.assertEquals(None, ret[1][0])
        self.assertEquals("bla/foo", ret[1][1])
        ie = ret[0][3]
        self.assertEquals("directory", ie.kind)
        ie = ret[1][3]
        self.assertEquals("file", ie.kind)
        self.assertEquals("bla/foo", ie.file_id)
        self.assertEquals("somerevid", ie.revision)
        self.assertEquals(osutils.sha_strings(["bar1"]), ie.text_sha1)
        self.assertEquals(False, ie.executable)

    def test_import_tree_with_unusual_mode_file(self):
        base_inv = Inventory()
        blob = Blob.from_string("bar1")
        tree = Tree()
        tree.add("foo", stat.S_IFREG | 0664, blob.id)
        objects = { blob.id: blob, tree.id: tree }
        ret, child_modes = import_git_tree(self._texts, self._mapping,
            "bla", "bla", (None, tree.id), base_inv, None, "somerevid", [],
            objects.__getitem__, (None, stat.S_IFDIR), DummyStoreUpdater(),
            self._mapping.generate_file_id)
        self.assertEquals(child_modes, { "bla/foo": stat.S_IFREG | 0664 })

    def test_import_tree_with_file_exe(self):
        base_inv = Inventory(root_id=None)
        blob = Blob.from_string("bar")
        tree = Tree()
        tree.add("foo", 0100755, blob.id)
        objects = { blob.id: blob, tree.id: tree }
        ret, child_modes = import_git_tree(self._texts, self._mapping, "", "",
                (None, tree.id), base_inv, None, "somerevid", [],
            objects.__getitem__, (None, stat.S_IFDIR), DummyStoreUpdater(),
            self._mapping.generate_file_id)
        self.assertEquals(child_modes, {})
        self.assertEquals(2, len(ret))
        self.assertEquals(None, ret[0][0])
        self.assertEquals("", ret[0][1])
        self.assertEquals(None, ret[1][0])
        self.assertEquals("foo", ret[1][1])
        ie = ret[0][3]
        self.assertEquals("directory", ie.kind)
        ie = ret[1][3]
        self.assertEquals("file", ie.kind)
        self.assertEquals(True, ie.executable)

    def test_directory_converted_to_submodule(self):
        base_inv = Inventory()
        base_inv.add_path("foo", "directory")
        base_inv.add_path("foo/bar", "file")
        othertree = Blob.from_string("someotherthing")
        blob = Blob.from_string("bar")
        tree = Tree()
        tree.add("bar", 0160000, blob.id)
        objects = { tree.id: tree }
        ret, child_modes = import_git_submodule(self._texts, self._mapping, "foo", "foo",
                (tree.id, othertree.id), base_inv, base_inv.root.file_id, "somerevid", [],
                objects.__getitem__, (stat.S_IFDIR | 0755, S_IFGITLINK), DummyStoreUpdater(),
                self._mapping.generate_file_id)
        self.assertEquals(child_modes, {})
        self.assertEquals(2, len(ret))
        self.assertEquals(ret[0], ("foo/bar", None, base_inv.path2id("foo/bar"), None))
        self.assertEquals(ret[1][:3], ("foo", "foo", self._mapping.generate_file_id("foo")))
        ie = ret[1][3]
        self.assertEquals(ie.kind, "tree-reference")

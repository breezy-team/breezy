# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for bzr-git's object store."""

import os
import shutil
import stat

from dulwich.objects import Blob, Tree
from vcsgraph.graph import DictParentsProvider, Graph

from ...branchbuilder import BranchBuilder
from ...bzr.inventory import InventoryDirectory, InventoryFile
from ...errors import NoSuchRevision
from ...tests import TestCase, TestCaseWithTransport
from ...tests.features import SymlinkFeature
from ..cache import DictGitShaMap
from ..object_store import (
    BazaarObjectStore,
    LRUTreeCache,
    _check_expected_sha,
    _find_missing_bzr_revids,
    _tree_to_objects,
    directory_to_tree,
)


class ExpectedShaTests(TestCase):
    def setUp(self):
        super().setUp()
        self.obj = Blob()
        self.obj.data = b"foo"

    def test_none(self):
        _check_expected_sha(None, self.obj)

    def test_hex(self):
        _check_expected_sha(self.obj.sha().hexdigest().encode("ascii"), self.obj)
        self.assertRaises(AssertionError, _check_expected_sha, b"0" * 40, self.obj)

    def test_binary(self):
        _check_expected_sha(self.obj.sha().digest(), self.obj)
        self.assertRaises(AssertionError, _check_expected_sha, b"x" * 20, self.obj)


class FindMissingBzrRevidsTests(TestCase):
    def _find_missing(self, ancestry, want, have):
        return _find_missing_bzr_revids(
            Graph(DictParentsProvider(ancestry)), set(want), set(have)
        )

    def test_simple(self):
        self.assertEqual(set(), self._find_missing({}, [], []))

    def test_up_to_date(self):
        self.assertEqual(set(), self._find_missing({"a": ["b"]}, ["a"], ["a"]))

    def test_one_missing(self):
        self.assertEqual({"a"}, self._find_missing({"a": ["b"]}, ["a"], ["b"]))

    def test_two_missing(self):
        self.assertEqual(
            {"a", "b"}, self._find_missing({"a": ["b"], "b": ["c"]}, ["a"], ["c"])
        )

    def test_two_missing_history(self):
        self.assertEqual(
            {"a", "b"},
            self._find_missing({"a": ["b"], "b": ["c"], "c": ["d"]}, ["a"], ["c"]),
        )


class LRUTreeCacheTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.branch = self.make_branch(".")
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        self.cache = LRUTreeCache(self.branch.repository)

    def test_get_not_present(self):
        self.assertRaises(NoSuchRevision, self.cache.revision_tree, b"unknown")

    def test_revision_trees(self):
        self.assertRaises(
            NoSuchRevision, self.cache.revision_trees, [b"unknown", b"la"]
        )

    def test_iter_revision_trees(self):
        self.assertRaises(
            NoSuchRevision, self.cache.iter_revision_trees, [b"unknown", b"la"]
        )

    def test_get(self):
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        revid = bb.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\nd\ne\n")),
            ],
        )
        bb.finish_series()
        tree = self.cache.revision_tree(revid)
        self.assertEqual(revid, tree.get_revision_id())


class BazaarObjectStoreTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.branch = self.make_branch(".")
        self.store = BazaarObjectStore(self.branch.repository)

    def test_get_blob(self):
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        b = Blob()
        b.data = b"a\nb\nc\nd\ne\n"
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertRaises(KeyError, self.store.__getitem__, b.id)
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        bb.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\nd\ne\n")),
            ],
        )
        bb.finish_series()
        # read locks cache
        self.assertRaises(KeyError, self.store.__getitem__, b.id)
        self.store.unlock()
        self.store.lock_read()
        self.assertEqual(b, self.store[b.id])

    def test_directory_converted_to_symlink(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        b = Blob()
        b.data = b"trgt"
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertRaises(KeyError, self.store.__getitem__, b.id)
        tree = self.branch.controldir.create_workingtree()
        self.build_tree_contents([("foo/",), ("foo/bar", b"a\nb\nc\nd\ne\n")])
        tree.add(["foo", "foo/bar"])
        tree.commit("commit 1")
        shutil.rmtree("foo")
        os.symlink("trgt", "foo")
        tree.commit("commit 2")
        # read locks cache
        self.assertRaises(KeyError, self.store.__getitem__, b.id)
        self.store.unlock()
        self.store.lock_read()
        self.assertEqual(b, self.store[b.id])

    def test_get_raw(self):
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        b = Blob()
        b.data = b"a\nb\nc\nd\ne\n"
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertRaises(KeyError, self.store.get_raw, b.id)
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        bb.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\nd\ne\n")),
            ],
        )
        bb.finish_series()
        # read locks cache
        self.assertRaises(KeyError, self.store.get_raw, b.id)
        self.store.unlock()
        self.store.lock_read()
        self.assertEqual(b.as_raw_string(), self.store.get_raw(b.id)[1])

    def test_contains(self):
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        b = Blob()
        b.data = b"a\nb\nc\nd\ne\n"
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertNotIn(b.id, self.store)
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        bb.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\nd\ne\n")),
            ],
        )
        bb.finish_series()
        # read locks cache
        self.assertNotIn(b.id, self.store)
        self.store.unlock()
        self.store.lock_read()
        self.assertIn(b.id, self.store)


class TreeToObjectsTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.idmap = DictGitShaMap()

    def test_no_changes(self):
        tree = self.make_branch_and_tree(".")
        self.addCleanup(tree.lock_read().unlock)
        entries = list(_tree_to_objects(tree, [tree], self.idmap, {}))
        self.assertEqual([], entries)

    def test_with_gitdir(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree([".git", "foo"])
        tree.add([".git", "foo"])
        revid = tree.commit("commit")
        revtree = tree.branch.repository.revision_tree(revid)
        self.addCleanup(revtree.lock_read().unlock)
        entries = list(_tree_to_objects(revtree, [], self.idmap, {}))
        self.assertEqual(["foo", ""], [p[0] for p in entries])

    def test_merge(self):
        basis_tree = self.make_branch_and_tree("base")
        self.build_tree(["base/foo/"])
        basis_tree.add(["foo"])
        basis_rev = basis_tree.commit("foo")
        basis_revtree = basis_tree.branch.repository.revision_tree(basis_rev)

        tree_a = self.make_branch_and_tree("a")
        tree_a.pull(basis_tree.branch)

        self.build_tree(["a/foo/file1"])
        self.build_tree(["a/foo/subdir-a/"])
        os.symlink(".", "a/foo/subdir-a/symlink")
        tree_a.add(["foo/subdir-a", "foo/subdir-a/symlink"])

        tree_a.add(["foo/file1"])
        rev_a = tree_a.commit("commit a")
        revtree_a = tree_a.branch.repository.revision_tree(rev_a)

        with revtree_a.lock_read():
            entries = list(_tree_to_objects(revtree_a, [basis_revtree], self.idmap, {}))
            objects = {path: obj for (path, obj, key) in entries}
            subdir_a = objects["foo/subdir-a"]

        tree_b = self.make_branch_and_tree("b")
        tree_b.pull(basis_tree.branch)
        self.build_tree(["b/foo/subdir/"])
        os.symlink(".", "b/foo/subdir/symlink")
        tree_b.add(["foo/subdir", "foo/subdir/symlink"])
        rev_b = tree_b.commit("commit b")
        revtree_b = tree_b.branch.repository.revision_tree(rev_b)
        self.addCleanup(revtree_b.lock_read().unlock)

        with revtree_b.lock_read():
            list(_tree_to_objects(revtree_b, [basis_revtree], self.idmap, {}))

        with tree_a.lock_write():
            tree_a.merge_from_branch(tree_b.branch)
        tree_a.commit("merge")

        revtree_merge = tree_a.branch.basis_tree()
        self.addCleanup(revtree_merge.lock_read().unlock)

        entries = list(
            _tree_to_objects(
                revtree_merge,
                [
                    tree_a.branch.repository.revision_tree(r)
                    for r in revtree_merge.get_parent_ids()
                ],
                self.idmap,
                {},
            )
        )
        objects = {path: obj for (path, obj, key) in entries}
        self.assertEqual({"", "foo", "foo/subdir"}, set(objects))
        self.assertEqual((stat.S_IFDIR, subdir_a.id), objects["foo"][b"subdir-a"])


class DirectoryToTreeTests(TestCase):
    def test_empty(self):
        t = directory_to_tree("", [], None, {}, None, allow_empty=False)
        self.assertEqual(None, t)

    def test_empty_dir(self):
        child_ie = InventoryDirectory(b"bar", "bar", b"bar")
        t = directory_to_tree(
            "", [child_ie], lambda p, x: None, {}, None, allow_empty=False
        )
        self.assertEqual(None, t)

    def test_empty_dir_dummy_files(self):
        child_ie = InventoryDirectory(b"bar", "bar", b"bar")
        t = directory_to_tree(
            "", [child_ie], lambda p, x: None, {}, ".mydummy", allow_empty=False
        )
        self.assertIn(".mydummy", t)

    def test_empty_root(self):
        child_ie = InventoryDirectory(b"bar", "bar", b"bar")
        t = directory_to_tree(
            "", [child_ie], lambda p, x: None, {}, None, allow_empty=True
        )
        self.assertEqual(Tree(), t)

    def test_with_file(self):
        child_ie = InventoryFile(b"bar", "bar", b"bar")
        b = Blob.from_string(b"bla")
        t1 = directory_to_tree(
            "", [child_ie], lambda p, x: b.id, {}, None, allow_empty=False
        )
        t2 = Tree()
        t2.add(b"bar", 0o100644, b.id)
        self.assertEqual(t1, t2)

    def test_with_gitdir(self):
        child_ie = InventoryFile(b"bar", "bar", b"bar")
        git_file_ie = InventoryFile(b"gitid", ".git", b"bar")
        b = Blob.from_string(b"bla")
        t1 = directory_to_tree(
            "", [child_ie, git_file_ie], lambda p, x: b.id, {}, None, allow_empty=False
        )
        t2 = Tree()
        t2.add(b"bar", 0o100644, b.id)
        self.assertEqual(t1, t2)

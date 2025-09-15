# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2011 Canonical Ltd.
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

"""Tests for Git working trees."""

import os
import stat

from dulwich import __version__ as dulwich_version
from dulwich.diff_tree import RenameDetector, tree_changes
from dulwich.index import ConflictedIndexEntry, IndexEntry
from dulwich.object_store import OverlayObjectStore
from dulwich.objects import S_IFGITLINK, ZERO_SHA, Blob, Tree

from ... import conflicts as _mod_conflicts
from ... import workingtree as _mod_workingtree
from ...bzr.inventorytree import InventoryTreeChange as TreeChange
from ...delta import TreeDelta
from ...tests import TestCase, TestCaseWithTransport
from ..mapping import default_mapping
from ..tree import tree_delta_from_git_changes


def changes_between_git_tree_and_working_copy(
    source_store,
    from_tree_sha,
    target,
    want_unchanged=False,
    want_unversioned=False,
    rename_detector=None,
    include_trees=True,
):
    """Determine the changes between a git tree and a working tree with index."""
    to_tree_sha, extras = target.git_snapshot(want_unversioned=want_unversioned)
    store = OverlayObjectStore([source_store, target.store])
    return tree_changes(
        store,
        from_tree_sha,
        to_tree_sha,
        include_trees=include_trees,
        rename_detector=rename_detector,
        want_unchanged=want_unchanged,
        change_type_same=True,
    ), extras


class GitWorkingTreeTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree(".", format="git")

    def test_conflict_list(self):
        self.assertIsInstance(self.tree.conflicts(), _mod_conflicts.ConflictList)

    def test_add_conflict(self):
        self.build_tree(["conflicted"])
        self.tree.add(["conflicted"])
        with self.tree.lock_tree_write():
            self.tree.index[b"conflicted"] = ConflictedIndexEntry(
                this=self.tree.index[b"conflicted"]
            )
            self.tree._index_dirty = True
        conflicts = self.tree.conflicts()
        self.assertEqual(1, len(conflicts))

    def test_revert_empty(self):
        self.build_tree(["a"])
        self.tree.add(["a"])
        self.assertTrue(self.tree.is_versioned("a"))
        self.tree.revert(["a"])
        self.assertFalse(self.tree.is_versioned("a"))

    def test_is_ignored_directory(self):
        self.assertFalse(self.tree.is_ignored("a"))
        self.build_tree(["a/"])
        self.assertFalse(self.tree.is_ignored("a"))
        self.build_tree_contents([(".gitignore", "a\n")])
        self.tree._ignoremanager = None
        self.assertTrue(self.tree.is_ignored("a"))
        self.build_tree_contents([(".gitignore", "a/\n")])
        self.tree._ignoremanager = None
        self.assertTrue(self.tree.is_ignored("a"))

    def test_add_submodule_dir(self):
        subtree = self.make_branch_and_tree("asub", format="git")
        subtree.commit("Empty commit")
        self.tree.add(["asub"])
        with self.tree.lock_read():
            entry = self.tree.index[b"asub"]
            self.assertEqual(entry.mode, S_IFGITLINK)
        self.assertEqual([], list(subtree.unknowns()))

    def test_add_submodule_file(self):
        os.mkdir(".git/modules")
        self.make_branch(".git/modules/asub", format="git-bare")
        os.mkdir("asub")
        with open("asub/.git", "w") as f:
            f.write("gitdir: ../.git/modules/asub\n")
        subtree = _mod_workingtree.WorkingTree.open("asub")
        subtree.commit("Empty commit")
        self.tree.add(["asub"])
        with self.tree.lock_read():
            entry = self.tree.index[b"asub"]
            self.assertEqual(entry.mode, S_IFGITLINK)
        self.assertEqual([], list(subtree.unknowns()))


class GitWorkingTreeFileTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree("actual", format="git")
        self.build_tree_contents(
            [("linked/",), ("linked/.git", "gitdir: ../actual/.git")]
        )
        self.wt = _mod_workingtree.WorkingTree.open("linked")

    def test_add(self):
        self.build_tree(["linked/somefile"])
        self.wt.add(["somefile"])
        self.wt.commit("Add somefile")


class TreeDeltaFromGitChangesTests(TestCase):
    def test_empty(self):
        delta = TreeDelta()
        changes = []
        self.assertEqual(
            delta,
            tree_delta_from_git_changes(changes, (default_mapping, default_mapping)),
        )

    def test_missing(self):
        delta = TreeDelta()
        delta.removed.append(
            TreeChange(
                b"git:a",
                ("a", "a"),
                False,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "a"),
                ("file", None),
                (True, False),
            )
        )
        changes = [
            ("remove", (b"a", stat.S_IFREG | 0o755, b"a" * 40), (b"a", 0, b"a" * 40))
        ]
        self.assertEqual(
            delta,
            tree_delta_from_git_changes(changes, (default_mapping, default_mapping)),
        )


class ChangesBetweenGitTreeAndWorkingCopyTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.wt = self.make_branch_and_tree(".", format="git")
        self.store = self.wt.branch.repository._git.object_store

    def expectDelta(
        self,
        expected_changes,
        expected_extras=None,
        want_unversioned=False,
        tree_id=None,
        rename_detector=None,
    ):
        if tree_id is None:
            try:
                tree_id = self.store[self.wt.branch.repository._git.head()].tree
            except KeyError:
                tree_id = None
        with self.wt.lock_read():
            changes, extras = changes_between_git_tree_and_working_copy(
                self.store,
                tree_id,
                self.wt,
                want_unversioned=want_unversioned,
                rename_detector=rename_detector,
            )
            self.assertEqual(expected_changes, list(changes))
        if expected_extras is None:
            expected_extras = set()
        self.assertEqual(set(expected_extras), set(extras))

    def test_empty(self):
        self.expectDelta([("add", (None, None, None), (b"", stat.S_IFDIR, Tree().id))])

    def test_added_file(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        a = Blob.from_string(b"contents of a\n")
        t = Tree()
        t.add(b"a", stat.S_IFREG | 0o644, a.id)
        self.expectDelta(
            [
                ("add", (None, None, None), (b"", stat.S_IFDIR, t.id)),
                ("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, a.id)),
            ]
        )

    def test_renamed_file(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        self.wt.rename_one("a", "b")
        a = Blob.from_string(b"contents of a\n")
        self.store.add_object(a)
        oldt = Tree()
        oldt.add(b"a", stat.S_IFREG | 0o644, a.id)
        self.store.add_object(oldt)
        newt = Tree()
        newt.add(b"b", stat.S_IFREG | 0o644, a.id)
        self.store.add_object(newt)
        self.expectDelta(
            [
                ("modify", (b"", stat.S_IFDIR, oldt.id), (b"", stat.S_IFDIR, newt.id)),
                ("delete", (b"a", stat.S_IFREG | 0o644, a.id), (None, None, None)),
                ("add", (None, None, None), (b"b", stat.S_IFREG | 0o644, a.id)),
            ],
            tree_id=oldt.id,
        )
        if dulwich_version >= (0, 19, 15):
            self.expectDelta(
                [
                    (
                        "modify",
                        (b"", stat.S_IFDIR, oldt.id),
                        (b"", stat.S_IFDIR, newt.id),
                    ),
                    (
                        "rename",
                        (b"a", stat.S_IFREG | 0o644, a.id),
                        (b"b", stat.S_IFREG | 0o644, a.id),
                    ),
                ],
                tree_id=oldt.id,
                rename_detector=RenameDetector(self.store),
            )

    def test_copied_file(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        self.wt.copy_one("a", "b")
        a = Blob.from_string(b"contents of a\n")
        self.store.add_object(a)
        oldt = Tree()
        oldt.add(b"a", stat.S_IFREG | 0o644, a.id)
        self.store.add_object(oldt)
        newt = Tree()
        newt.add(b"a", stat.S_IFREG | 0o644, a.id)
        newt.add(b"b", stat.S_IFREG | 0o644, a.id)
        self.store.add_object(newt)
        self.expectDelta(
            [
                ("modify", (b"", stat.S_IFDIR, oldt.id), (b"", stat.S_IFDIR, newt.id)),
                ("add", (None, None, None), (b"b", stat.S_IFREG | 0o644, a.id)),
            ],
            tree_id=oldt.id,
        )

        if dulwich_version >= (0, 19, 15):
            self.expectDelta(
                [
                    (
                        "modify",
                        (b"", stat.S_IFDIR, oldt.id),
                        (b"", stat.S_IFDIR, newt.id),
                    ),
                    (
                        "copy",
                        (b"a", stat.S_IFREG | 0o644, a.id),
                        (b"b", stat.S_IFREG | 0o644, a.id),
                    ),
                ],
                tree_id=oldt.id,
                rename_detector=RenameDetector(self.store, find_copies_harder=True),
            )
            self.expectDelta(
                [
                    (
                        "modify",
                        (b"", stat.S_IFDIR, oldt.id),
                        (b"", stat.S_IFDIR, newt.id),
                    ),
                    ("add", (None, None, None), (b"b", stat.S_IFREG | 0o644, a.id)),
                ],
                tree_id=oldt.id,
                rename_detector=RenameDetector(self.store, find_copies_harder=False),
            )

    def test_added_unknown_file(self):
        self.build_tree(["a"])
        t = Tree()
        self.expectDelta([("add", (None, None, None), (b"", stat.S_IFDIR, t.id))])
        a = Blob.from_string(b"contents of a\n")
        t = Tree()
        t.add(b"a", stat.S_IFREG | 0o644, a.id)
        self.expectDelta(
            [
                ("add", (None, None, None), (b"", stat.S_IFDIR, t.id)),
                ("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, a.id)),
            ],
            [b"a"],
            want_unversioned=True,
        )

    def test_missing_added_file(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        os.unlink("a")
        Blob.from_string(b"contents of a\n")
        t = Tree()
        t.add(b"a", 0, ZERO_SHA)
        self.expectDelta(
            [
                ("add", (None, None, None), (b"", stat.S_IFDIR, t.id)),
                ("add", (None, None, None), (b"a", 0, ZERO_SHA)),
            ],
            [],
        )

    def test_missing_versioned_file(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        self.wt.commit("")
        os.unlink("a")
        a = Blob.from_string(b"contents of a\n")
        oldt = Tree()
        oldt.add(b"a", stat.S_IFREG | 0o644, a.id)
        newt = Tree()
        newt.add(b"a", 0, ZERO_SHA)
        self.expectDelta(
            [
                ("modify", (b"", stat.S_IFDIR, oldt.id), (b"", stat.S_IFDIR, newt.id)),
                ("modify", (b"a", stat.S_IFREG | 0o644, a.id), (b"a", 0, ZERO_SHA)),
            ]
        )

    def test_versioned_replace_by_dir(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        self.wt.commit("")
        os.unlink("a")
        os.mkdir("a")
        olda = Blob.from_string(b"contents of a\n")
        oldt = Tree()
        oldt.add(b"a", stat.S_IFREG | 0o644, olda.id)
        newt = Tree()
        newa = Tree()
        newt.add(b"a", stat.S_IFDIR, newa.id)
        self.expectDelta(
            [
                ("modify", (b"", stat.S_IFDIR, oldt.id), (b"", stat.S_IFDIR, newt.id)),
                (
                    "modify",
                    (b"a", stat.S_IFREG | 0o644, olda.id),
                    (b"a", stat.S_IFDIR, newa.id),
                ),
            ],
            want_unversioned=False,
        )
        self.expectDelta(
            [
                ("modify", (b"", stat.S_IFDIR, oldt.id), (b"", stat.S_IFDIR, newt.id)),
                (
                    "modify",
                    (b"a", stat.S_IFREG | 0o644, olda.id),
                    (b"a", stat.S_IFDIR, newa.id),
                ),
            ],
            want_unversioned=True,
        )

    def test_extra(self):
        self.build_tree(["a"])
        newa = Blob.from_string(b"contents of a\n")
        newt = Tree()
        newt.add(b"a", stat.S_IFREG | 0o644, newa.id)
        self.expectDelta(
            [
                ("add", (None, None, None), (b"", stat.S_IFDIR, newt.id)),
                ("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, newa.id)),
            ],
            [b"a"],
            want_unversioned=True,
        )

    def test_submodule(self):
        self.subtree = self.make_branch_and_tree("a", format="git")
        a = Blob.from_string(b"irrelevant\n")
        self.build_tree_contents([("a/.git/HEAD", a.id)])
        with self.wt.lock_tree_write():
            (index, _index_path) = self.wt._lookup_index(b"a")
            index[b"a"] = IndexEntry(0, 0, 0, 0, S_IFGITLINK, 0, 0, 0, a.id)
            self.wt._index_dirty = True
        t = Tree()
        t.add(b"a", S_IFGITLINK, a.id)
        self.store.add_object(t)
        self.expectDelta([], tree_id=t.id)

    def test_submodule_not_checked_out(self):
        a = Blob.from_string(b"irrelevant\n")
        with self.wt.lock_tree_write():
            (index, _index_path) = self.wt._lookup_index(b"a")
            index[b"a"] = IndexEntry(0, 0, 0, 0, S_IFGITLINK, 0, 0, 0, a.id)
            self.wt._index_dirty = True
        os.mkdir(self.wt.abspath("a"))
        t = Tree()
        t.add(b"a", S_IFGITLINK, a.id)
        self.store.add_object(t)
        self.expectDelta([], tree_id=t.id)

    def test_subsume(self):
        self.build_tree(["a", "b"])
        self.wt.add(["a", "b"])
        myrevid = self.wt.commit("")

        subwt = self.make_branch_and_tree("c", format="git")
        self.build_tree(["c/d"])
        subwt.add(["d"])
        subrevid = subwt.commit("")

        self.wt.subsume(subwt)
        self.assertEqual([myrevid, subrevid], self.wt.get_parent_ids())
        self.assertFalse(os.path.exists("c/.git"))
        self.assertTrue(os.path.exists("c/.git.retired.0"))
        changes = list(self.wt.iter_changes(self.wt.basis_tree()))
        self.assertEqual(2, len(changes))

# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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


"""Tests for breezy.git.tests."""

import stat

from dulwich.objects import Blob

from breezy.bzr.inventorytree import InventoryTreeChange as TreeChange
from breezy.delta import TreeDelta
from breezy.errors import PathsNotVersionedError
from breezy.git.mapping import default_mapping
from breezy.git.tree import changes_from_git_changes, tree_delta_from_git_changes
from breezy.tests import TestCase, TestCaseWithTransport
from breezy.workingtree import WorkingTree

REG_MODE = stat.S_IFREG | 0o644


class ChangesFromGitChangesTests(TestCase):
    def setUp(self):
        super().setUp()
        self.maxDiff = None
        self.mapping = default_mapping

    def transform(
        self,
        changes,
        specific_files=None,
        include_unchanged=False,
        source_extras=None,
        target_extras=None,
    ):
        return list(
            changes_from_git_changes(
                changes,
                self.mapping,
                specific_files=specific_files,
                include_unchanged=include_unchanged,
                source_extras=source_extras,
                target_extras=target_extras,
            )
        )

    def test_empty(self):
        self.assertEqual([], self.transform([]))

    def test_modified(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    ("a", "a"),
                    True,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("a", "a"),
                    ("file", "file"),
                    (False, False),
                    False,
                )
            ],
            self.transform(
                [
                    (
                        "modify",
                        (b"a", stat.S_IFREG | 0o644, a),
                        (b"a", stat.S_IFREG | 0o644, b),
                    )
                ]
            ),
        )

    def test_kind_changed(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"target")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    ("a", "a"),
                    True,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("a", "a"),
                    ("file", "symlink"),
                    (False, False),
                    False,
                )
            ],
            self.transform(
                [("modify", (b"a", stat.S_IFREG | 0o644, a), (b"a", stat.S_IFLNK, b))]
            ),
        )

    def test_rename_no_changes(self):
        a = Blob.from_string(b"a")
        self.assertEqual(
            [
                TreeChange(
                    b"git:old",
                    ("old", "a"),
                    False,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("old", "a"),
                    ("file", "file"),
                    (False, False),
                    False,
                )
            ],
            self.transform(
                [
                    (
                        "rename",
                        (b"old", stat.S_IFREG | 0o644, a),
                        (b"a", stat.S_IFREG | 0o644, a),
                    )
                ]
            ),
        )

    def test_rename_and_modify(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    ("a", "b"),
                    True,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("a", "b"),
                    ("file", "file"),
                    (False, False),
                    False,
                )
            ],
            self.transform(
                [
                    (
                        "rename",
                        (b"a", stat.S_IFREG | 0o644, a),
                        (b"b", stat.S_IFREG | 0o644, b),
                    )
                ]
            ),
        )

    def test_copy_no_changes(self):
        a = Blob.from_string(b"a")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    ("old", "a"),
                    False,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("old", "a"),
                    ("file", "file"),
                    (False, False),
                    True,
                )
            ],
            self.transform(
                [
                    (
                        "copy",
                        (b"old", stat.S_IFREG | 0o644, a),
                        (b"a", stat.S_IFREG | 0o644, a),
                    )
                ]
            ),
        )

    def test_copy_and_modify(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    b"git:b",
                    ("a", "b"),
                    True,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("a", "b"),
                    ("file", "file"),
                    (False, False),
                    True,
                )
            ],
            self.transform(
                [
                    (
                        "copy",
                        (b"a", stat.S_IFREG | 0o644, a),
                        (b"b", stat.S_IFREG | 0o644, b),
                    )
                ]
            ),
        )

    def test_add(self):
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    (None, "a"),
                    True,
                    (False, True),
                    (None, b"TREE_ROOT"),
                    (None, "a"),
                    (None, "file"),
                    (None, False),
                    False,
                )
            ],
            self.transform(
                [("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, b))]
            ),
        )

    def test_delete(self):
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    ("a", None),
                    True,
                    (True, False),
                    (b"TREE_ROOT", None),
                    ("a", None),
                    ("file", None),
                    (False, None),
                    False,
                )
            ],
            self.transform(
                [("remove", (b"a", stat.S_IFREG | 0o644, b), (None, None, None))]
            ),
        )

    def test_unchanged(self):
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    b"git:a",
                    ("a", "a"),
                    False,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("a", "a"),
                    ("file", "file"),
                    (False, False),
                    False,
                )
            ],
            self.transform(
                [
                    (
                        "unchanged",
                        (b"a", stat.S_IFREG | 0o644, b),
                        (b"a", stat.S_IFREG | 0o644, b),
                    )
                ],
                include_unchanged=True,
            ),
        )
        self.assertEqual(
            [],
            self.transform(
                [
                    (
                        "unchanged",
                        (b"a", stat.S_IFREG | 0o644, b),
                        (b"a", stat.S_IFREG | 0o644, b),
                    )
                ],
                include_unchanged=False,
            ),
        )

    def test_unversioned(self):
        b = Blob.from_string(b"b")
        self.assertEqual(
            [
                TreeChange(
                    None,
                    (None, "a"),
                    True,
                    (False, False),
                    (None, b"TREE_ROOT"),
                    (None, "a"),
                    (None, "file"),
                    (None, False),
                    False,
                )
            ],
            self.transform(
                [("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, b))],
                target_extras={b"a"},
            ),
        )
        self.assertEqual(
            [
                TreeChange(
                    None,
                    ("a", "a"),
                    False,
                    (False, False),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("a", "a"),
                    ("file", "file"),
                    (False, False),
                    False,
                )
            ],
            self.transform(
                [
                    (
                        "add",
                        (b"a", stat.S_IFREG | 0o644, b),
                        (b"a", stat.S_IFREG | 0o644, b),
                    )
                ],
                source_extras={b"a"},
                target_extras={b"a"},
            ),
        )


class DeltaFromGitChangesTests(TestCase):
    def setUp(self):
        super().setUp()
        self.maxDiff = None
        self.mapping = default_mapping

    def transform(
        self,
        changes,
        specific_files=None,
        require_versioned=False,
        include_root=False,
        source_extras=None,
        target_extras=None,
    ):
        return tree_delta_from_git_changes(
            changes,
            (self.mapping, self.mapping),
            specific_files=specific_files,
            require_versioned=require_versioned,
            include_root=include_root,
            source_extras=source_extras,
            target_extras=target_extras,
        )

    def test_empty(self):
        self.assertEqual(TreeDelta(), self.transform([]))

    def test_modified(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"b")
        delta = self.transform(
            [
                (
                    "modify",
                    (b"a", stat.S_IFREG | 0o644, a),
                    (b"a", stat.S_IFREG | 0o644, b),
                )
            ]
        )
        expected_delta = TreeDelta()
        expected_delta.modified.append(
            TreeChange(
                b"git:a",
                ("a", "a"),
                True,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "a"),
                ("file", "file"),
                (False, False),
                False,
            )
        )
        self.assertEqual(expected_delta, delta)

    def test_rename_no_changes(self):
        a = Blob.from_string(b"a")
        delta = self.transform(
            [
                (
                    "rename",
                    (b"old", stat.S_IFREG | 0o644, a),
                    (b"a", stat.S_IFREG | 0o644, a),
                )
            ]
        )
        expected_delta = TreeDelta()
        expected_delta.renamed.append(
            TreeChange(
                b"git:old",
                ("old", "a"),
                False,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("old", "a"),
                ("file", "file"),
                (False, False),
                False,
            )
        )
        self.assertEqual(expected_delta, delta)

    def test_rename_and_modify(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"b")
        delta = self.transform(
            [
                (
                    "rename",
                    (b"a", stat.S_IFREG | 0o644, a),
                    (b"b", stat.S_IFREG | 0o644, b),
                )
            ]
        )
        expected_delta = TreeDelta()
        expected_delta.renamed.append(
            TreeChange(
                b"git:a",
                ("a", "b"),
                True,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "b"),
                ("file", "file"),
                (False, False),
                False,
            )
        )
        self.assertEqual(delta, expected_delta)

    def test_copy_no_changes(self):
        a = Blob.from_string(b"a")
        delta = self.transform(
            [
                (
                    "copy",
                    (b"old", stat.S_IFREG | 0o644, a),
                    (b"a", stat.S_IFREG | 0o644, a),
                )
            ]
        )
        expected_delta = TreeDelta()
        expected_delta.copied.append(
            TreeChange(
                b"git:a",
                ("old", "a"),
                False,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("old", "a"),
                ("file", "file"),
                (False, False),
                True,
            )
        )
        self.assertEqual(expected_delta, delta)

    def test_copy_and_modify(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"b")
        delta = self.transform(
            [("copy", (b"a", stat.S_IFREG | 0o644, a), (b"b", stat.S_IFREG | 0o644, b))]
        )
        expected_delta = TreeDelta()
        expected_delta.copied.append(
            TreeChange(
                b"git:b",
                ("a", "b"),
                True,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "b"),
                ("file", "file"),
                (False, False),
                True,
            )
        )
        self.assertEqual(expected_delta, delta)

    def test_add(self):
        b = Blob.from_string(b"b")
        delta = self.transform(
            [("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, b))]
        )
        expected_delta = TreeDelta()
        expected_delta.added.append(
            TreeChange(
                b"git:a",
                (None, "a"),
                True,
                (False, True),
                (None, b"TREE_ROOT"),
                (None, "a"),
                (None, "file"),
                (None, False),
                False,
            )
        )
        self.assertEqual(delta, expected_delta)

    def test_delete(self):
        b = Blob.from_string(b"b")
        delta = self.transform(
            [("remove", (b"a", stat.S_IFREG | 0o644, b), (None, None, None))]
        )
        expected_delta = TreeDelta()
        expected_delta.removed.append(
            TreeChange(
                b"git:a",
                ("a", None),
                True,
                (True, False),
                (b"TREE_ROOT", None),
                ("a", None),
                ("file", None),
                (False, None),
                False,
            )
        )
        self.assertEqual(delta, expected_delta)

    def test_unchanged(self):
        b = Blob.from_string(b"b")
        self.transform(
            [
                (
                    "unchanged",
                    (b"a", stat.S_IFREG | 0o644, b),
                    (b"a", stat.S_IFREG | 0o644, b),
                )
            ]
        )
        expected_delta = TreeDelta()
        expected_delta.unchanged.append(
            TreeChange(
                b"git:a",
                ("a", "a"),
                False,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "a"),
                ("file", "file"),
                (False, False),
                False,
            )
        )

    def test_unversioned(self):
        b = Blob.from_string(b"b")
        delta = self.transform(
            [("add", (None, None, None), (b"a", stat.S_IFREG | 0o644, b))],
            target_extras={b"a"},
        )
        expected_delta = TreeDelta()
        expected_delta.unversioned.append(
            TreeChange(
                None,
                (None, "a"),
                True,
                (False, False),
                (None, b"TREE_ROOT"),
                (None, "a"),
                (None, "file"),
                (None, False),
                False,
            )
        )
        self.assertEqual(delta, expected_delta)
        delta = self.transform(
            [("add", (b"a", stat.S_IFREG | 0o644, b), (b"a", stat.S_IFREG | 0o644, b))],
            source_extras={b"a"},
            target_extras={b"a"},
        )
        expected_delta = TreeDelta()
        expected_delta.unversioned.append(
            TreeChange(
                None,
                ("a", "a"),
                False,
                (False, False),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "a"),
                ("file", "file"),
                (False, False),
                False,
            )
        )
        self.assertEqual(delta, expected_delta)

    def test_kind_change(self):
        a = Blob.from_string(b"a")
        b = Blob.from_string(b"target")
        delta = self.transform(
            [("modify", (b"a", stat.S_IFREG | 0o644, a), (b"a", stat.S_IFLNK, b))]
        )
        expected_delta = TreeDelta()
        expected_delta.kind_changed.append(
            TreeChange(
                b"git:a",
                ("a", "a"),
                True,
                (True, True),
                (b"TREE_ROOT", b"TREE_ROOT"),
                ("a", "a"),
                ("file", "symlink"),
                (False, False),
                False,
            )
        )
        self.assertEqual(expected_delta, delta)


class FindRelatedPathsAcrossTrees(TestCaseWithTransport):
    def test_none(self):
        self.make_branch_and_tree("t1", format="git")
        wt = WorkingTree.open("t1")
        self.assertIs(None, wt.find_related_paths_across_trees(None))

    def test_empty(self):
        self.make_branch_and_tree("t1", format="git")
        wt = WorkingTree.open("t1")
        self.assertEqual([], list(wt.find_related_paths_across_trees([])))

    def test_directory(self):
        self.make_branch_and_tree("t1", format="git")
        wt = WorkingTree.open("t1")
        self.build_tree(["t1/dir/", "t1/dir/file"])
        wt.add(["dir", "dir/file"])
        self.assertEqual(
            ["dir/file"], list(wt.find_related_paths_across_trees(["dir/file"]))
        )
        self.assertEqual(["dir"], list(wt.find_related_paths_across_trees(["dir"])))

    def test_empty_directory(self):
        self.make_branch_and_tree("t1", format="git")
        wt = WorkingTree.open("t1")
        self.build_tree(["t1/dir/"])
        wt.add(["dir"])
        self.assertEqual(["dir"], list(wt.find_related_paths_across_trees(["dir"])))
        self.assertRaises(
            PathsNotVersionedError, wt.find_related_paths_across_trees, ["dir/file"]
        )

    def test_missing(self):
        self.make_branch_and_tree("t1", format="git")
        wt = WorkingTree.open("t1")
        self.assertRaises(
            PathsNotVersionedError, wt.find_related_paths_across_trees, ["file"]
        )

    def test_not_versioned(self):
        self.make_branch_and_tree("t1", format="git")
        self.make_branch_and_tree("t2", format="git")
        wt1 = WorkingTree.open("t1")
        wt2 = WorkingTree.open("t2")
        self.build_tree(["t1/file"])
        self.build_tree(["t2/file"])
        self.assertRaises(
            PathsNotVersionedError, wt1.find_related_paths_across_trees, ["file"], [wt2]
        )

    def test_single(self):
        self.make_branch_and_tree("t1", format="git")
        wt = WorkingTree.open("t1")
        self.build_tree(["t1/file"])
        wt.add("file")
        self.assertEqual(["file"], list(wt.find_related_paths_across_trees(["file"])))

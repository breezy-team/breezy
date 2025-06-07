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

"""Tests for interface conformance of inventories of working trees."""

import os

from breezy import tests
from breezy.tests.per_workingtree import TestCaseWithWorkingTree
from bzrformats import inventory


class TestRevert(TestCaseWithWorkingTree):
    def test_dangling_id(self):
        wt = self.make_branch_and_tree("b1")
        wt.lock_tree_write()
        self.addCleanup(wt.unlock)
        self.assertEqual(len(list(wt.all_versioned_paths())), 1)
        with open("b1/a", "wb") as f:
            f.write(b"a test\n")
        wt.add("a")
        self.assertEqual(len(list(wt.all_versioned_paths())), 2)
        wt.flush()  # workaround revert doing wt._write_inventory for now.
        os.unlink("b1/a")
        wt.revert()
        self.assertEqual(len(list(wt.all_versioned_paths())), 1)


class TestApplyInventoryDelta(TestCaseWithWorkingTree):
    def setUp(self):
        super().setUp()
        if not self.bzrdir_format.repository_format.supports_full_versioned_files:
            raise tests.TestNotApplicable("format does not support inventory deltas")

    def test_add(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        root_id = wt.path2id("")
        wt.apply_inventory_delta(
            [
                (
                    None,
                    "bar/foo",
                    b"foo-id",
                    inventory.InventoryFile(b"foo-id", "foo", parent_id=b"bar-id"),
                ),
                (
                    None,
                    "bar",
                    b"bar-id",
                    inventory.InventoryDirectory(b"bar-id", "bar", parent_id=root_id),
                ),
            ]
        )
        self.assertEqual("bar/foo", wt.id2path(b"foo-id"))
        self.assertEqual("bar", wt.id2path(b"bar-id"))

    def test_remove(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["foo/", "foo/bar"])
        wt.add(["foo", "foo/bar"], ids=[b"foo-id", b"bar-id"])
        wt.apply_inventory_delta(
            [("foo", None, b"foo-id", None), ("foo/bar", None, b"bar-id", None)]
        )
        self.assertFalse(wt.is_versioned("foo"))

    def test_rename_dir_with_children(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        root_id = wt.path2id("")
        self.addCleanup(wt.unlock)
        self.build_tree(["foo/", "foo/bar"])
        wt.add(["foo", "foo/bar"], ids=[b"foo-id", b"bar-id"])
        wt.apply_inventory_delta(
            [
                (
                    "foo",
                    "baz",
                    b"foo-id",
                    inventory.InventoryDirectory(b"foo-id", "baz", root_id),
                )
            ]
        )
        # foo/bar should have been followed the rename of its parent to baz/bar
        self.assertEqual("baz", wt.id2path(b"foo-id"))
        self.assertEqual("baz/bar", wt.id2path(b"bar-id"))

    def test_rename_dir_with_children_with_children(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        root_id = wt.path2id("")
        self.addCleanup(wt.unlock)
        self.build_tree(["foo/", "foo/bar/", "foo/bar/baz"])
        wt.add(["foo", "foo/bar", "foo/bar/baz"], ids=[b"foo-id", b"bar-id", b"baz-id"])
        wt.apply_inventory_delta(
            [
                (
                    "foo",
                    "quux",
                    b"foo-id",
                    inventory.InventoryDirectory(b"foo-id", "quux", root_id),
                )
            ]
        )
        # foo/bar/baz should have been followed the rename of its parent's
        # parent to quux/bar/baz
        self.assertEqual("quux/bar/baz", wt.id2path(b"baz-id"))

    def test_rename_file(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["foo/", "foo/bar", "baz/"])
        wt.add(["foo", "foo/bar", "baz"], ids=[b"foo-id", b"bar-id", b"baz-id"])
        wt.apply_inventory_delta(
            [
                (
                    "foo/bar",
                    "baz/bar",
                    b"bar-id",
                    inventory.InventoryFile(b"bar-id", "bar", b"baz-id"),
                )
            ]
        )
        self.assertEqual("baz/bar", wt.id2path(b"bar-id"))

    def test_rename_swap(self):
        """Test the swap-names edge case.

        foo and bar should swap names, but retain their children.  If this
        works, any simpler rename ought to work.
        """
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        root_id = wt.path2id("")
        self.addCleanup(wt.unlock)
        self.build_tree(["foo/", "foo/bar", "baz/", "baz/qux"])
        wt.add(
            ["foo", "foo/bar", "baz", "baz/qux"],
            ids=[b"foo-id", b"bar-id", b"baz-id", b"qux-id"],
        )
        wt.apply_inventory_delta(
            [
                (
                    "foo",
                    "baz",
                    b"foo-id",
                    inventory.InventoryDirectory(b"foo-id", "baz", root_id),
                ),
                (
                    "baz",
                    "foo",
                    b"baz-id",
                    inventory.InventoryDirectory(b"baz-id", "foo", root_id),
                ),
            ]
        )
        self.assertEqual("baz/bar", wt.id2path(b"bar-id"))
        self.assertEqual("foo/qux", wt.id2path(b"qux-id"))

    def test_child_rename_ordering(self):
        """Test the rename-parent, move child edge case.

        (A naive implementation may move the parent first, and then be
         unable to find the child.)
        """
        wt = self.make_branch_and_tree(".")
        root_id = wt.path2id("")
        self.build_tree(["dir/", "dir/child", "other/"])
        wt.add(["dir", "dir/child", "other"], ids=[b"dir-id", b"child-id", b"other-id"])
        # this delta moves dir-id to dir2 and reparents
        # child-id to a parent of other-id
        wt.apply_inventory_delta(
            [
                (
                    "dir",
                    "dir2",
                    b"dir-id",
                    inventory.InventoryDirectory(b"dir-id", "dir2", root_id),
                ),
                (
                    "dir/child",
                    "other/child",
                    b"child-id",
                    inventory.InventoryFile(b"child-id", "child", b"other-id"),
                ),
            ]
        )
        self.assertEqual("dir2", wt.id2path(b"dir-id"))
        self.assertEqual("other/child", wt.id2path(b"child-id"))

    def test_replace_root(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)

        root_id = wt.path2id("")
        wt.apply_inventory_delta(
            [
                ("", None, root_id, None),
                (
                    None,
                    "",
                    b"root-id",
                    inventory.InventoryDirectory(b"root-id", "", None),
                ),
            ]
        )


class TestTreeReference(TestCaseWithWorkingTree):
    def test_tree_reference_matches_inv(self):
        base = self.make_branch_and_tree("base")
        if base.branch.repository._format.supports_full_versioned_files:
            raise tests.TestNotApplicable("format does not support inventory deltas")
        if not base.supports_tree_reference():
            raise tests.TestNotApplicable("wt doesn't support nested trees")
        if base.has_versioned_directories():
            # We add it as a directory, but it becomes a tree-reference
            base.add(["subdir"], ["directory"])
            subdir = self.make_branch_and_tree("base/subdir")
        else:
            subdir = self.make_branch_and_tree("base/subdir")
            subdir.commit("")
            # We add it as a directory, but it becomes a tree-reference
            base.add(["subdir"], ["tree-reference"])
        self.addCleanup(base.lock_read().unlock)
        # Note: we aren't strict about ie.kind being 'directory' here, what we
        # are strict about is that wt.inventory should match
        # wt.current_dirstate()'s idea about what files are where.
        path, ie = next(base.iter_entries_by_dir(specific_files=["subdir"]))
        self.assertEqual("subdir", path)
        self.assertEqual("tree-reference", ie.kind)

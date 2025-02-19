# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for different inventory implementations"""

# NOTE: Don't import Inventory here, to make sure that we don't accidentally
# hardcode that when we should be using self.make_inventory

from breezy import errors, osutils
from breezy.bzr import inventory
from breezy.bzr.inventory import (
    InventoryFile,
    InventoryLink,
)
from breezy.bzr.tests.per_inventory import TestCaseWithInventory


class TestInventory(TestCaseWithInventory):
    def make_init_inventory(self):
        inv = inventory.Inventory(b"tree-root")
        inv.revision = b"initial-rev"
        inv.root.revision = b"initial-rev"
        return self.inv_to_test_inv(inv)

    def make_file(
        self, file_id, name, parent_id, content=b"content\n", revision=b"new-test-rev"
    ):
        ie = InventoryFile(file_id, name, parent_id)
        ie.text_sha1 = osutils.sha_string(content)
        ie.text_size = len(content)
        ie.revision = revision
        return ie

    def make_link(self, file_id, name, parent_id, target="link-target\n"):
        ie = InventoryLink(file_id, name, parent_id)
        ie.symlink_target = target
        return ie

    def prepare_inv_with_nested_dirs(self):
        inv = inventory.Inventory(b"tree-root")
        inv.root.revision = b"revision"
        for args in [
            ("src", "directory", b"src-id"),
            ("doc", "directory", b"doc-id"),
            ("src/hello.c", "file", b"hello-id"),
            ("src/bye.c", "file", b"bye-id"),
            ("zz", "file", b"zz-id"),
            ("src/sub/", "directory", b"sub-id"),
            ("src/zz.c", "file", b"zzc-id"),
            ("src/sub/a", "file", b"a-id"),
            ("Makefile", "file", b"makefile-id"),
        ]:
            ie = inv.add_path(*args)
            ie.revision = b"revision"
            if args[1] == "file":
                ie.text_sha1 = osutils.sha_string(b"content\n")
                ie.text_size = len(b"content\n")
        return self.inv_to_test_inv(inv)


class TestInventoryCreateByApplyDelta(TestInventory):
    """A subset of the inventory delta application tests.

    See test_inv which has comprehensive delta application tests for
    inventories, dirstate, and repository based inventories.
    """

    def test_add(self):
        inv = self.make_init_inventory()
        inv = inv.create_by_apply_delta(
            [
                (None, "a", b"a-id", self.make_file(b"a-id", "a", b"tree-root")),
            ],
            b"new-test-rev",
        )
        self.assertEqual("a", inv.id2path(b"a-id"))

    def test_delete(self):
        inv = self.make_init_inventory()
        inv = inv.create_by_apply_delta(
            [
                (None, "a", b"a-id", self.make_file(b"a-id", "a", b"tree-root")),
            ],
            b"new-rev-1",
        )
        self.assertEqual("a", inv.id2path(b"a-id"))
        inv = inv.create_by_apply_delta(
            [
                ("a", None, b"a-id", None),
            ],
            b"new-rev-2",
        )
        self.assertRaises(errors.NoSuchId, inv.id2path, b"a-id")

    def test_rename(self):
        inv = self.make_init_inventory()
        inv = inv.create_by_apply_delta(
            [
                (None, "a", b"a-id", self.make_file(b"a-id", "a", b"tree-root")),
            ],
            b"new-rev-1",
        )
        self.assertEqual("a", inv.id2path(b"a-id"))
        a_ie = inv.get_entry(b"a-id")
        b_ie = self.make_file(a_ie.file_id, "b", a_ie.parent_id)
        inv = inv.create_by_apply_delta([("a", "b", b"a-id", b_ie)], b"new-rev-2")
        self.assertEqual("b", inv.id2path(b"a-id"))

    def test_illegal(self):
        # A file-id cannot appear in a delta more than once
        inv = self.make_init_inventory()
        self.assertRaises(
            errors.InconsistentDelta,
            inv.create_by_apply_delta,
            [
                (None, "a", b"id-1", self.make_file(b"id-1", "a", b"tree-root")),
                (None, "b", b"id-1", self.make_file(b"id-1", "b", b"tree-root")),
            ],
            b"new-rev-1",
        )


class TestInventoryReads(TestInventory):
    def test_is_root(self):
        """Ensure our root-checking code is accurate."""
        inv = self.make_init_inventory()
        self.assertTrue(inv.is_root(b"tree-root"))
        self.assertFalse(inv.is_root(b"booga"))
        ie = inv.get_entry(b"tree-root").copy()
        ie.file_id = b"booga"
        inv = inv.create_by_apply_delta(
            [("", None, b"tree-root", None), (None, "", b"booga", ie)], b"new-rev-2"
        )
        self.assertFalse(inv.is_root(b"TREE_ROOT"))
        self.assertTrue(inv.is_root(b"booga"))

    def test_ids(self):
        """Test detection of files within selected directories."""
        inv = inventory.Inventory(b"TREE_ROOT")
        inv.root.revision = b"revision"
        for args in [
            ("src", "directory", b"src-id"),
            ("doc", "directory", b"doc-id"),
            ("src/hello.c", "file"),
            ("src/bye.c", "file", b"bye-id"),
            ("Makefile", "file"),
        ]:
            ie = inv.add_path(*args)
            ie.revision = b"revision"
            if args[1] == "file":
                ie.text_sha1 = osutils.sha_string(b"content\n")
                ie.text_size = len(b"content\n")
        inv = self.inv_to_test_inv(inv)
        self.assertEqual(inv.path2id("src"), b"src-id")
        self.assertEqual(inv.path2id("src/bye.c"), b"bye-id")

    def test_get_entry_by_path_partial(self):
        inv = inventory.Inventory(b"TREE_ROOT")
        inv.root.revision = b"revision"
        for args in [
            ("src", "directory", b"src-id"),
            ("doc", "directory", b"doc-id"),
            ("src/hello.c", "file"),
            ("src/bye.c", "file", b"bye-id"),
            ("Makefile", "file"),
            ("external", "tree-reference", b"other-root"),
        ]:
            ie = inv.add_path(*args)
            ie.revision = b"revision"
            if args[1] == "file":
                ie.text_sha1 = osutils.sha_string(b"content\n")
                ie.text_size = len(b"content\n")
            if args[1] == "tree-reference":
                ie.reference_revision = b"reference"
        inv = self.inv_to_test_inv(inv)

        # Standard lookups
        ie, resolved, remaining = inv.get_entry_by_path_partial("")
        self.assertEqual((ie.file_id, resolved, remaining), (b"TREE_ROOT", [], []))
        ie, resolved, remaining = inv.get_entry_by_path_partial("src")
        self.assertEqual((ie.file_id, resolved, remaining), (b"src-id", ["src"], []))
        ie, resolved, remaining = inv.get_entry_by_path_partial("src/bye.c")
        self.assertEqual(
            (ie.file_id, resolved, remaining), (b"bye-id", ["src", "bye.c"], [])
        )

        # Paths in the external tree
        ie, resolved, remaining = inv.get_entry_by_path_partial("external")
        self.assertEqual(
            (ie.file_id, resolved, remaining), (b"other-root", ["external"], [])
        )
        ie, resolved, remaining = inv.get_entry_by_path_partial("external/blah")
        self.assertEqual(
            (ie.file_id, resolved, remaining), (b"other-root", ["external"], ["blah"])
        )

        # Nonexistant paths
        ie, resolved, remaining = inv.get_entry_by_path_partial("foo.c")
        self.assertEqual((ie, resolved, remaining), (None, None, None))

    def test_non_directory_children(self):
        """Test path2id when a parent directory has no children"""
        inv = inventory.Inventory(b"tree-root")
        inv.add(self.make_file(b"file-id", "file", b"tree-root"))
        inv.add(self.make_link(b"link-id", "link", b"tree-root"))
        self.assertIs(None, inv.path2id("file/subfile"))
        self.assertIs(None, inv.path2id("link/subfile"))

    def test_is_unmodified(self):
        f1 = self.make_file(b"file-id", "file", b"tree-root")
        f1.revision = b"rev"
        self.assertTrue(f1.is_unmodified(f1))
        f2 = self.make_file(b"file-id", "file", b"tree-root")
        f2.revision = b"rev"
        self.assertTrue(f1.is_unmodified(f2))
        f3 = self.make_file(b"file-id", "file", b"tree-root")
        self.assertFalse(f1.is_unmodified(f3))
        f4 = self.make_file(b"file-id", "file", b"tree-root")
        f4.revision = b"rev1"
        self.assertFalse(f1.is_unmodified(f4))

    def test_iter_entries(self):
        inv = self.prepare_inv_with_nested_dirs()

        # Test all entries
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("Makefile", b"makefile-id"),
                ("doc", b"doc-id"),
                ("src", b"src-id"),
                ("src/bye.c", b"bye-id"),
                ("src/hello.c", b"hello-id"),
                ("src/sub", b"sub-id"),
                ("src/sub/a", b"a-id"),
                ("src/zz.c", b"zzc-id"),
                ("zz", b"zz-id"),
            ],
            [(path, ie.file_id) for path, ie in inv.iter_entries()],
        )

        # Test a subdirectory
        self.assertEqual(
            [
                ("bye.c", b"bye-id"),
                ("hello.c", b"hello-id"),
                ("sub", b"sub-id"),
                ("sub/a", b"a-id"),
                ("zz.c", b"zzc-id"),
            ],
            [(path, ie.file_id) for path, ie in inv.iter_entries(from_dir=b"src-id")],
        )

        # Test not recursing at the root level
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("Makefile", b"makefile-id"),
                ("doc", b"doc-id"),
                ("src", b"src-id"),
                ("zz", b"zz-id"),
            ],
            [(path, ie.file_id) for path, ie in inv.iter_entries(recursive=False)],
        )

        # Test not recursing at a subdirectory level
        self.assertEqual(
            [
                ("bye.c", b"bye-id"),
                ("hello.c", b"hello-id"),
                ("sub", b"sub-id"),
                ("zz.c", b"zzc-id"),
            ],
            [
                (path, ie.file_id)
                for path, ie in inv.iter_entries(from_dir=b"src-id", recursive=False)
            ],
        )

    def test_iter_just_entries(self):
        inv = self.prepare_inv_with_nested_dirs()
        self.assertEqual(
            [
                b"a-id",
                b"bye-id",
                b"doc-id",
                b"hello-id",
                b"makefile-id",
                b"src-id",
                b"sub-id",
                b"tree-root",
                b"zz-id",
                b"zzc-id",
            ],
            sorted([ie.file_id for ie in inv.iter_just_entries()]),
        )

    def test_iter_entries_by_dir(self):
        inv = self.prepare_inv_with_nested_dirs()
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("Makefile", b"makefile-id"),
                ("doc", b"doc-id"),
                ("src", b"src-id"),
                ("zz", b"zz-id"),
                ("src/bye.c", b"bye-id"),
                ("src/hello.c", b"hello-id"),
                ("src/sub", b"sub-id"),
                ("src/zz.c", b"zzc-id"),
                ("src/sub/a", b"a-id"),
            ],
            [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir()],
        )
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("Makefile", b"makefile-id"),
                ("doc", b"doc-id"),
                ("src", b"src-id"),
                ("zz", b"zz-id"),
                ("src/bye.c", b"bye-id"),
                ("src/hello.c", b"hello-id"),
                ("src/sub", b"sub-id"),
                ("src/zz.c", b"zzc-id"),
                ("src/sub/a", b"a-id"),
            ],
            [
                (path, ie.file_id)
                for path, ie in inv.iter_entries_by_dir(
                    specific_file_ids=(
                        b"a-id",
                        b"zzc-id",
                        b"doc-id",
                        b"tree-root",
                        b"hello-id",
                        b"bye-id",
                        b"zz-id",
                        b"src-id",
                        b"makefile-id",
                        b"sub-id",
                    )
                )
            ],
        )

        self.assertEqual(
            [
                ("Makefile", b"makefile-id"),
                ("doc", b"doc-id"),
                ("zz", b"zz-id"),
                ("src/bye.c", b"bye-id"),
                ("src/hello.c", b"hello-id"),
                ("src/zz.c", b"zzc-id"),
                ("src/sub/a", b"a-id"),
            ],
            [
                (path, ie.file_id)
                for path, ie in inv.iter_entries_by_dir(
                    specific_file_ids=(
                        b"a-id",
                        b"zzc-id",
                        b"doc-id",
                        b"hello-id",
                        b"bye-id",
                        b"zz-id",
                        b"makefile-id",
                    )
                )
            ],
        )

        self.assertEqual(
            [
                ("Makefile", b"makefile-id"),
                ("src/bye.c", b"bye-id"),
            ],
            [
                (path, ie.file_id)
                for path, ie in inv.iter_entries_by_dir(
                    specific_file_ids=(b"bye-id", b"makefile-id")
                )
            ],
        )

        self.assertEqual(
            [
                ("Makefile", b"makefile-id"),
                ("src/bye.c", b"bye-id"),
            ],
            [
                (path, ie.file_id)
                for path, ie in inv.iter_entries_by_dir(
                    specific_file_ids=(b"bye-id", b"makefile-id")
                )
            ],
        )

        self.assertEqual(
            [
                ("src/bye.c", b"bye-id"),
            ],
            [
                (path, ie.file_id)
                for path, ie in inv.iter_entries_by_dir(specific_file_ids=(b"bye-id",))
            ],
        )


class TestInventoryFiltering(TestInventory):
    def test_inv_filter_empty(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter([])
        self.assertEqual(
            [
                ("", b"tree-root"),
            ],
            [(path, ie.file_id) for path, ie in new_inv.iter_entries()],
        )

    def test_inv_filter_files(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter([b"zz-id", b"hello-id", b"a-id"])
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("src", b"src-id"),
                ("src/hello.c", b"hello-id"),
                ("src/sub", b"sub-id"),
                ("src/sub/a", b"a-id"),
                ("zz", b"zz-id"),
            ],
            [(path, ie.file_id) for path, ie in new_inv.iter_entries()],
        )

    def test_inv_filter_dirs(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter([b"doc-id", b"sub-id"])
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("doc", b"doc-id"),
                ("src", b"src-id"),
                ("src/sub", b"sub-id"),
                ("src/sub/a", b"a-id"),
            ],
            [(path, ie.file_id) for path, ie in new_inv.iter_entries()],
        )

    def test_inv_filter_files_and_dirs(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter([b"makefile-id", b"src-id"])
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("Makefile", b"makefile-id"),
                ("src", b"src-id"),
                ("src/bye.c", b"bye-id"),
                ("src/hello.c", b"hello-id"),
                ("src/sub", b"sub-id"),
                ("src/sub/a", b"a-id"),
                ("src/zz.c", b"zzc-id"),
            ],
            [(path, ie.file_id) for path, ie in new_inv.iter_entries()],
        )

    def test_inv_filter_entry_not_present(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter([b"not-present-id"])
        self.assertEqual(
            [
                ("", b"tree-root"),
            ],
            [(path, ie.file_id) for path, ie in new_inv.iter_entries()],
        )

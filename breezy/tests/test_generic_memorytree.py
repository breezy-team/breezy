# Copyright (C) 2006 Canonical Ltd
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

"""Tests for the format-independent MemoryTree class."""

from .. import errors, transport
from ..memorytree import MemoryTree
from . import TestCaseWithTransport


class TestMemoryTree(TestCaseWithTransport):
    def _make_memory_tree(self):
        branch = self.make_branch("branch")
        return MemoryTree.create_on_branch(branch)

    def test_create_on_branch(self):
        """Creating a mutable tree on a trivial branch works."""
        branch = self.make_branch("branch")
        tree = MemoryTree.create_on_branch(branch)
        self.assertEqual(branch.controldir, tree.controldir)
        self.assertEqual(branch, tree.branch)
        self.assertEqual([], tree.get_parent_ids())

    def test_supports_file_ids(self):
        tree = self._make_memory_tree()
        self.assertFalse(tree.supports_file_ids)

    def test_supports_rename_tracking(self):
        tree = self._make_memory_tree()
        self.assertFalse(tree.supports_rename_tracking())

    def test_supports_tree_reference(self):
        tree = self._make_memory_tree()
        self.assertFalse(tree.supports_tree_reference())

    def test_lock_tree_write(self):
        """Check we can lock_tree_write and unlock MemoryTrees."""
        tree = self._make_memory_tree()
        tree.lock_tree_write()
        tree.unlock()

    def test_lock_tree_write_after_read_fails(self):
        """Check that we error when trying to upgrade a read lock to write."""
        tree = self._make_memory_tree()
        with tree.lock_read():
            self.assertRaises(errors.ReadOnlyError, tree.lock_tree_write)

    def test_lock_write(self):
        """Check we can lock_write and unlock MemoryTrees."""
        tree = self._make_memory_tree()
        tree.lock_write()
        tree.unlock()

    def test_lock_write_after_read_fails(self):
        """Check that we error when trying to upgrade a read lock to write."""
        tree = self._make_memory_tree()
        with tree.lock_read():
            self.assertRaises(errors.ReadOnlyError, tree.lock_write)

    def test_add_with_kind(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "afile", "adir"], ["directory", "file", "directory"])
            self.assertTrue(tree.is_versioned("afile"))
            self.assertTrue(tree.is_versioned("adir"))
            self.assertFalse(tree.has_filename("afile"))
            self.assertFalse(tree.has_filename("adir"))

    def test_put_new_file(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"barshoom")
            with tree.get_file("foo") as f:
                self.assertEqual(b"barshoom", f.read())

    def test_put_existing_file(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"first-content")
            tree.put_file_bytes_non_atomic("foo", b"barshoom")
            self.assertEqual(b"barshoom", tree.get_file("foo").read())

    def test_add_in_subdir(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], ["directory"])
            tree.mkdir("adir")
            tree.put_file_bytes_non_atomic("adir/afile", b"barshoom")
            tree.add(["adir/afile"], ["file"])
            self.assertTrue(tree.is_versioned("adir/afile"))
            self.assertTrue(tree.is_versioned("adir"))

    def test_add_symlink(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree._file_transport.symlink("bar", "foo")
            tree.add(["", "foo"])
            self.assertEqual("symlink", tree.kind("foo"))
            self.assertEqual("bar", tree.get_symlink_target("foo"))

    def test_unversion(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.unversion(["foo"])
            self.assertFalse(tree.is_versioned("foo"))

    def test_unversion_missing_raises(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            self.assertRaises(transport.NoSuchFile, tree.unversion, ["nonexistent"])

    def test_rename_file(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], ["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content\n")
            tree.rename_one("foo", "bar")
            self.assertTrue(tree.is_versioned("bar"))
            self.assertFalse(tree.is_versioned("foo"))
            self.assertEqual(b"content\n", tree._file_transport.get_bytes("bar"))
            self.assertRaises(
                transport.NoSuchFile, tree._file_transport.get_bytes, "foo"
            )

    def test_rename_file_to_subdir(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add("")
            tree.mkdir("subdir")
            tree.add("foo", "file")
            tree.put_file_bytes_non_atomic("foo", b"content\n")
            tree.rename_one("foo", "subdir/bar")
            self.assertTrue(tree.is_versioned("subdir/bar"))
            self.assertFalse(tree.is_versioned("foo"))
            self.assertEqual(b"content\n", tree._file_transport.get_bytes("subdir/bar"))

    def test_kind(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "afile", "adir"], ["directory", "file", "directory"])
            tree.put_file_bytes_non_atomic("afile", b"content")
            tree._file_transport.mkdir("adir")
            self.assertEqual("file", tree.kind("afile"))
            self.assertEqual("directory", tree.kind("adir"))

    def test_get_file_sha1(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            sha1 = tree.get_file_sha1("foo")
            self.assertIsNotNone(sha1)
            self.assertEqual(40, len(sha1))

    def test_get_file_size(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            self.assertEqual(7, tree.get_file_size("foo"))

    def test_is_versioned(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            self.assertFalse(tree.is_versioned("foo"))
            tree.add(["", "foo"], kinds=["directory", "file"])
            self.assertTrue(tree.is_versioned("foo"))
            self.assertTrue(tree.is_versioned(""))

    def test_all_versioned_paths(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo", "bar"], kinds=["directory", "file", "file"])
            paths = tree.all_versioned_paths()
            self.assertEqual({"", "foo", "bar"}, paths)

    def test_has_filename(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            self.assertFalse(tree.has_filename("foo"))
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            self.assertTrue(tree.has_filename("foo"))

    def test_path_content_summary_file(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            kind, size, executable, _sha1 = tree.path_content_summary("foo")
            self.assertEqual("file", kind)
            self.assertEqual(7, size)
            self.assertFalse(executable)

    def test_path_content_summary_directory(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            tree.mkdir("adir")
            kind, _size, _executable, _sha1 = tree.path_content_summary("adir")
            self.assertEqual("directory", kind)

    def test_path_content_summary_symlink(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            tree._file_transport.symlink("target", "link")
            tree.add(["link"], kinds=["symlink"])
            kind, _size, _executable, target = tree.path_content_summary("link")
            self.assertEqual("symlink", kind)
            self.assertEqual("target", target)

    def test_path_content_summary_missing(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            kind, _size, _executable, _sha1 = tree.path_content_summary("nonexistent")
            self.assertEqual("missing", kind)

    def test_iter_entries_by_dir(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo", "bar"], kinds=["directory", "file", "file"])
            tree.put_file_bytes_non_atomic("foo", b"foo content")
            tree.put_file_bytes_non_atomic("bar", b"bar content")
            entries = list(tree.iter_entries_by_dir())
            paths = [path for path, entry in entries]
            self.assertEqual(["", "bar", "foo"], paths)
            kinds = [entry.kind for path, entry in entries]
            self.assertEqual(["directory", "file", "file"], kinds)

    def test_iter_entries_by_dir_specific_files(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo", "bar"], kinds=["directory", "file", "file"])
            tree.put_file_bytes_non_atomic("foo", b"foo content")
            tree.put_file_bytes_non_atomic("bar", b"bar content")
            entries = list(tree.iter_entries_by_dir(specific_files=["foo"]))
            paths = [path for path, entry in entries]
            self.assertEqual(["foo"], paths)

    def test_list_files(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            files = list(tree.list_files())
            self.assertEqual(1, len(files))
            path, status, kind, _entry = files[0]
            self.assertEqual("foo", path)
            self.assertEqual("V", status)
            self.assertEqual("file", kind)

    def test_walkdirs(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            dirs = list(tree.walkdirs())
            self.assertEqual(1, len(dirs))
            dirpath, dirblock = dirs[0]
            self.assertEqual("", dirpath)
            self.assertEqual(1, len(dirblock))
            self.assertEqual("foo", dirblock[0][0])

    def test_has_changes_empty(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            # A fresh tree with nothing added has no changes
            self.assertFalse(tree.has_changes())

    def test_has_changes_with_new_file(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            self.assertTrue(tree.has_changes())

    def test_copy_one(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            tree.copy_one("foo", "bar")
            self.assertTrue(tree.is_versioned("bar"))
            self.assertEqual(b"content", tree.get_file("bar").read())
            # Original still exists
            self.assertTrue(tree.is_versioned("foo"))

    def test_mkdir(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            tree.mkdir("subdir")
            self.assertTrue(tree.is_versioned("subdir"))
            self.assertTrue(tree.has_filename("subdir"))
            self.assertEqual("directory", tree.kind("subdir"))

    def test_add_auto_versions_parents(self):
        """Adding a file in a subdir auto-versions the parent dirs."""
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            tree.mkdir("adir")
            tree.add(["adir/afile"], kinds=["file"])
            self.assertTrue(tree.is_versioned("adir"))
            self.assertTrue(tree.is_versioned("adir/afile"))

    def test_basis_tree(self):
        tree = self._make_memory_tree()
        with tree.lock_read():
            basis = tree.basis_tree()
            self.assertIsNotNone(basis)

    def test_annotate_iter(self):
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"line1\nline2\n")
            annotations = tree.annotate_iter("foo")
            self.assertEqual(2, len(annotations))

    def test_iter_changes_new_file(self):
        """iter_changes detects a new file vs the basis."""
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add(["", "foo"], kinds=["directory", "file"])
            tree.put_file_bytes_non_atomic("foo", b"content")
            changes = list(tree.iter_changes(tree.basis_tree()))
            # Should detect root and foo as new
            new_paths = [c.path[1] for c in changes if c.versioned[1]]
            self.assertIn("foo", new_paths)

    def test_iter_changes_unchanged(self):
        """iter_changes returns nothing when tree matches basis."""
        tree = self._make_memory_tree()
        with tree.lock_write():
            tree.add([""], kinds=["directory"])
            changes = list(tree.iter_changes(tree.basis_tree()))
            # Only the root, which is new
            non_root = [c for c in changes if c.path[1] != ""]
            self.assertEqual([], non_root)

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

from dulwich.diff_tree import RenameDetector, tree_changes
from dulwich.diff_tree import TreeChange as DulwichTreeChange
from dulwich.index import ConflictedIndexEntry, IndexEntry
from dulwich.object_store import OverlayObjectStore
from dulwich.objects import S_IFGITLINK, ZERO_SHA, Blob, Tree, TreeEntry

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
    changes = tree_changes(
        store,
        from_tree_sha,
        to_tree_sha,
        include_trees=include_trees,
        rename_detector=rename_detector,
        want_unchanged=want_unchanged,
        change_type_same=True,
    )
    return changes, extras


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
            DulwichTreeChange(
                type="remove",
                old=TreeEntry(b"a", stat.S_IFREG | 0o755, b"a" * 40),
                new=TreeEntry(b"a", 0, b"a" * 40),
            )
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
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"", stat.S_IFDIR, Tree().id)
                )
            ]
        )

    def test_added_file(self):
        self.build_tree(["a"])
        self.wt.add(["a"])
        a = Blob.from_string(b"contents of a\n")
        t = Tree()
        t.add(b"a", stat.S_IFREG | 0o644, a.id)
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"", stat.S_IFDIR, t.id)
                ),
                DulwichTreeChange(
                    type="add",
                    old=None,
                    new=TreeEntry(b"a", stat.S_IFREG | 0o644, a.id),
                ),
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
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="delete",
                    old=TreeEntry(b"a", stat.S_IFREG | 0o644, a.id),
                    new=None,
                ),
                DulwichTreeChange(
                    type="add",
                    old=None,
                    new=TreeEntry(b"b", stat.S_IFREG | 0o644, a.id),
                ),
            ],
            tree_id=oldt.id,
        )
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="rename",
                    old=TreeEntry(b"a", stat.S_IFREG | 0o644, a.id),
                    new=TreeEntry(b"b", stat.S_IFREG | 0o644, a.id),
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
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="add",
                    old=None,
                    new=TreeEntry(b"b", stat.S_IFREG | 0o644, a.id),
                ),
            ],
            tree_id=oldt.id,
        )

        self.expectDelta(
            [
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="copy",
                    old=TreeEntry(b"a", stat.S_IFREG | 0o644, a.id),
                    new=TreeEntry(b"b", stat.S_IFREG | 0o644, a.id),
                ),
            ],
            tree_id=oldt.id,
            rename_detector=RenameDetector(self.store, find_copies_harder=True),
        )
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="add",
                    old=None,
                    new=TreeEntry(b"b", stat.S_IFREG | 0o644, a.id),
                ),
            ],
            tree_id=oldt.id,
            rename_detector=RenameDetector(self.store, find_copies_harder=False),
        )

    def test_added_unknown_file(self):
        self.build_tree(["a"])
        t = Tree()
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"", stat.S_IFDIR, t.id)
                )
            ]
        )
        a = Blob.from_string(b"contents of a\n")
        t = Tree()
        t.add(b"a", stat.S_IFREG | 0o644, a.id)
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"", stat.S_IFDIR, t.id)
                ),
                DulwichTreeChange(
                    type="add",
                    old=None,
                    new=TreeEntry(b"a", stat.S_IFREG | 0o644, a.id),
                ),
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
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"", stat.S_IFDIR, t.id)
                ),
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"a", 0, ZERO_SHA)
                ),
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
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"a", stat.S_IFREG | 0o644, a.id),
                    new=TreeEntry(b"a", 0, ZERO_SHA),
                ),
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
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"a", stat.S_IFREG | 0o644, olda.id),
                    new=TreeEntry(b"a", stat.S_IFDIR, newa.id),
                ),
            ],
            want_unversioned=False,
        )
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"a", stat.S_IFREG | 0o644, olda.id),
                    new=TreeEntry(b"a", stat.S_IFDIR, newa.id),
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
                DulwichTreeChange(
                    type="add", old=None, new=TreeEntry(b"", stat.S_IFDIR, newt.id)
                ),
                DulwichTreeChange(
                    type="add",
                    old=None,
                    new=TreeEntry(b"a", stat.S_IFREG | 0o644, newa.id),
                ),
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

    def test_gitattributes_crlf_eol(self):
        """Working tree CRLF files should not show as changed when eol=crlf."""
        # Create .gitattributes specifying eol=crlf for .bat files
        self.build_tree_contents([(".gitattributes", "*.bat text eol=crlf\n")])
        self.wt.add([".gitattributes"])
        # Create a file with LF line endings (as git stores it)
        with open(self.wt.abspath("test.bat"), "wb") as f:
            f.write(b"line1\nline2\n")
        self.wt.add(["test.bat"])
        self.wt.commit("initial commit")
        # Now write the file with CRLF (as git checkout would produce
        # for eol=crlf)
        with open(self.wt.abspath("test.bat"), "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        # The LF-normalized blob is what git stores
        a_lf = Blob.from_string(b"line1\nline2\n")
        gitattrs = Blob.from_string(b"*.bat text eol=crlf\n")
        oldt = Tree()
        oldt.add(b".gitattributes", stat.S_IFREG | 0o644, gitattrs.id)
        oldt.add(b"test.bat", stat.S_IFREG | 0o644, a_lf.id)
        # After normalization, the CRLF working tree content should be
        # normalized to LF, matching the committed content - no changes.
        self.expectDelta([], tree_id=oldt.id)

    def test_gitattributes_crlf_actual_change(self):
        """Actual content changes should still be detected with eol=crlf."""
        self.build_tree_contents([(".gitattributes", "*.bat text eol=crlf\n")])
        self.wt.add([".gitattributes"])
        with open(self.wt.abspath("test.bat"), "wb") as f:
            f.write(b"line1\nline2\n")
        self.wt.add(["test.bat"])
        self.wt.commit("initial commit")
        # Write different content with CRLF
        with open(self.wt.abspath("test.bat"), "wb") as f:
            f.write(b"line1\r\nline2\r\nline3\r\n")
        a_old = Blob.from_string(b"line1\nline2\n")
        a_new = Blob.from_string(b"line1\nline2\nline3\n")
        gitattrs = Blob.from_string(b"*.bat text eol=crlf\n")
        oldt = Tree()
        oldt.add(b".gitattributes", stat.S_IFREG | 0o644, gitattrs.id)
        oldt.add(b"test.bat", stat.S_IFREG | 0o644, a_old.id)
        newt = Tree()
        newt.add(b".gitattributes", stat.S_IFREG | 0o644, gitattrs.id)
        newt.add(b"test.bat", stat.S_IFREG | 0o644, a_new.id)
        self.expectDelta(
            [
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"", stat.S_IFDIR, oldt.id),
                    new=TreeEntry(b"", stat.S_IFDIR, newt.id),
                ),
                DulwichTreeChange(
                    type="modify",
                    old=TreeEntry(b"test.bat", stat.S_IFREG | 0o644, a_old.id),
                    new=TreeEntry(b"test.bat", stat.S_IFREG | 0o644, a_new.id),
                ),
            ],
            tree_id=oldt.id,
        )

    def test_gitattributes_text_auto(self):
        """Files marked as text=auto should have LF normalized."""
        self.build_tree_contents([(".gitattributes", "* text=auto\n")])
        self.wt.add([".gitattributes"])
        # Create a file with CRLF line endings
        with open(self.wt.abspath("file.txt"), "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        self.wt.add(["file.txt"])
        self.wt.commit("initial commit")
        # The file should be stored with LF internally
        # Get the actual committed tree to verify normalization worked
        head_commit = self.store[self.wt.branch.repository._git.head()]
        committed_tree = self.store[head_commit.tree]
        # Verify file.txt was stored with LF
        file_entry = committed_tree[b"file.txt"]
        file_blob = self.store[file_entry[1]]
        self.assertEqual(
            file_blob.data, b"line1\nline2\n", "File should be stored with LF"
        )

        # Simulate checkout with CRLF (on Windows)
        with open(self.wt.abspath("file.txt"), "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        # Should not show as changed when compared to committed tree
        self.expectDelta([], tree_id=head_commit.tree)

    def test_gitattributes_binary(self):
        """Binary files marked with -text should not be normalized."""
        self.build_tree_contents(
            [
                (".gitattributes", "*.bin -text\n"),
                ("test.bin", b"binary\r\ndata\x00\r\n"),
            ]
        )
        self.wt.add([".gitattributes", "test.bin"])
        self.wt.commit("initial commit")

        # Verify file was stored without normalization (with CRLF)
        head_commit = self.store[self.wt.branch.repository._git.head()]
        committed_tree = self.store[head_commit.tree]
        file_entry = committed_tree[b"test.bin"]
        file_blob = self.store[file_entry[1]]
        self.assertEqual(
            file_blob.data,
            b"binary\r\ndata\x00\r\n",
            "Binary file should be stored as-is",
        )

    def test_gitattributes_info_attributes(self):
        """Test that .git/info/attributes is read."""
        import os

        # Create .git/info/attributes
        info_dir = os.path.join(self.wt.repository._git.controldir(), "info")
        os.makedirs(info_dir, exist_ok=True)
        info_attrs_path = os.path.join(info_dir, "attributes")
        with open(info_attrs_path, "w") as f:
            f.write("*.txt text eol=lf\n")

        # Create a file with CRLF
        with open(self.wt.abspath("file.txt"), "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        self.wt.add(["file.txt"])
        self.wt.commit("initial commit")

        # Verify file was normalized to LF
        head_commit = self.store[self.wt.branch.repository._git.head()]
        committed_tree = self.store[head_commit.tree]
        file_entry = committed_tree[b"file.txt"]
        file_blob = self.store[file_entry[1]]
        self.assertEqual(
            file_blob.data,
            b"line1\nline2\n",
            "File should be normalized according to info/attributes",
        )

    def test_gitattributes_get_file_filtered(self):
        """Test that get_file() applies content filters."""
        self.build_tree_contents(
            [
                (".gitattributes", "*.txt text eol=lf\n"),
                ("file.txt", b"line1\r\nline2\r\n"),
            ]
        )
        self.wt.add([".gitattributes", "file.txt"])

        # get_file() should return filtered (normalized) content
        with self.wt.get_file("file.txt") as f:
            content = f.read()
        self.assertEqual(content, b"line1\nline2\n", "get_file should apply filters")

        # get_file(filtered=False) should return raw content
        with self.wt.get_file("file.txt", filtered=False) as f:
            content = f.read()
        self.assertEqual(
            content,
            b"line1\r\nline2\r\n",
            "get_file(filtered=False) should return raw content",
        )

    def test_gitattributes_priority(self):
        """Test priority of gitattributes from different sources."""
        import os

        # Create .git/info/attributes with one rule
        info_dir = os.path.join(self.wt.repository._git.controldir(), "info")
        os.makedirs(info_dir, exist_ok=True)
        info_attrs_path = os.path.join(info_dir, "attributes")
        with open(info_attrs_path, "w") as f:
            f.write("*.txt text eol=crlf\n")

        # Create .gitattributes with conflicting rule (should take precedence)
        self.build_tree_contents(
            [
                (".gitattributes", "*.txt text eol=lf\n"),
                ("file.txt", b"line1\r\nline2\r\n"),
            ]
        )
        self.wt.add([".gitattributes", "file.txt"])
        self.wt.commit("initial commit")

        # Working tree .gitattributes should override info/attributes
        head_commit = self.store[self.wt.branch.repository._git.head()]
        committed_tree = self.store[head_commit.tree]
        file_entry = committed_tree[b"file.txt"]
        file_blob = self.store[file_entry[1]]
        self.assertEqual(
            file_blob.data,
            b"line1\nline2\n",
            "Working tree .gitattributes should override info/attributes",
        )

    def test_gitattributes_global_config(self):
        """Test that global gitattributes from core.attributesFile is read."""
        import os

        # Create a global gitattributes file in the test directory
        global_attrs_path = os.path.join(self.test_dir, "global.gitattributes")
        with open(global_attrs_path, "w") as f:
            f.write("*.global text eol=lf\n")

        # Set core.attributesFile config
        config_path = os.path.join(self.wt.repository._git.controldir(), "config")
        config = self.wt.repository._git.get_config()
        config.set(b"core", b"attributesFile", global_attrs_path.encode())
        config.write_to_path(config_path)

        # Create a file with CRLF
        with open(self.wt.abspath("file.global"), "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        self.wt.add(["file.global"])
        self.wt.commit("initial commit")

        # Verify file was normalized to LF
        head_commit = self.store[self.wt.branch.repository._git.head()]
        committed_tree = self.store[head_commit.tree]
        file_entry = committed_tree[b"file.global"]
        file_blob = self.store[file_entry[1]]
        self.assertEqual(
            file_blob.data,
            b"line1\nline2\n",
            "File should be normalized according to global gitattributes",
        )

    def test_gitattributes_custom_filter(self):
        """Test that custom filters from gitattributes are applied."""
        import os

        # Create filter scripts in test directory
        # Create clean filter (normalizes to LF)
        clean_script = os.path.join(self.test_dir, "clean.sh")
        with open(clean_script, "w") as f:
            f.write("#!/bin/sh\nsed 's/\\r$//'\n")
        os.chmod(clean_script, 0o755)  # noqa: S103

        # Create smudge filter (adds CRLF)
        smudge_script = os.path.join(self.test_dir, "smudge.sh")
        with open(smudge_script, "w") as f:
            f.write("#!/bin/sh\nsed 's/$/\\r/'\n")
        os.chmod(smudge_script, 0o755)  # noqa: S103

        # Configure the custom filter
        config_path = os.path.join(self.wt.repository._git.controldir(), "config")
        config = self.wt.repository._git.get_config()
        config.set((b"filter", b"myfilter"), b"clean", clean_script.encode())
        config.set((b"filter", b"myfilter"), b"smudge", smudge_script.encode())
        config.write_to_path(config_path)

        # Create .gitattributes using the custom filter
        self.build_tree_contents(
            [
                (".gitattributes", "*.custom filter=myfilter\n"),
            ]
        )
        self.wt.add([".gitattributes"])

        # Create a file with CRLF
        with open(self.wt.abspath("file.custom"), "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        self.wt.add(["file.custom"])
        self.wt.commit("initial commit")

        # The custom filter should normalize to LF via the clean filter
        head_commit = self.store[self.wt.branch.repository._git.head()]
        committed_tree = self.store[head_commit.tree]
        file_entry = committed_tree[b"file.custom"]
        file_blob = self.store[file_entry[1]]
        self.assertEqual(
            file_blob.data,
            b"line1\nline2\n",
            "File should be filtered through custom clean filter",
        )

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

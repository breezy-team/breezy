# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.remove'"""

from breezy import ignores, osutils
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestRemove(TestCaseWithWorkingTree):
    """Tests WorkingTree.remove"""

    files = ["a", "b/", "b/c", "d/"]
    rfiles = ["b/c", "b", "a", "d"]
    backup_files = ["a.~1~", "b.~1~/", "b.~1~/c.~1~", "d.~1~/"]
    backup_files_no_version_dirs = ["a.~1~", "b.~1~/", "b.~1~/c.~1~"]

    def get_tree(self, files):
        tree = self.make_branch_and_tree(".")
        self.build_tree(files)
        self.assertPathExists(files)
        return tree

    def get_committed_tree(self, files, message="Committing"):
        tree = self.get_tree(files)
        tree.add(files)
        tree.commit(message)
        if not tree.has_versioned_directories():
            self.assertInWorkingTree([f for f in files if not f.endswith("/")])
            self.assertPathExists(files)
        else:
            self.assertInWorkingTree(files)
        return tree

    def assertRemovedAndDeleted(self, files):
        self.assertNotInWorkingTree(files)
        self.assertPathDoesNotExist(files)

    def assertRemovedAndNotDeleted(self, files):
        self.assertNotInWorkingTree(files)
        self.assertPathExists(files)

    def test_remove_keep(self):
        """Check that files and directories are unversioned but not deleted."""
        tree = self.get_tree(TestRemove.files)
        tree.add(TestRemove.files)

        tree.remove(TestRemove.files)
        self.assertRemovedAndNotDeleted(TestRemove.files)

    def test_remove_keep_subtree(self):
        """Check that a directory is unversioned but not deleted."""
        tree = self.make_branch_and_tree(".")
        subtree = self.make_branch_and_tree("subtree")
        subtree.commit("")
        tree.add("subtree")

        tree.remove("subtree")
        self.assertRemovedAndNotDeleted("subtree")

    def test_remove_unchanged_files(self):
        """Check that unchanged files are removed and deleted."""
        tree = self.get_committed_tree(TestRemove.files)
        tree.remove(TestRemove.files, keep_files=False)
        self.assertRemovedAndDeleted(TestRemove.files)
        tree._validate()

    def test_remove_added_files(self):
        """Removal of newly added files must back them up."""
        tree = self.get_tree(TestRemove.files)
        tree.add(TestRemove.files)
        tree.remove(TestRemove.files, keep_files=False)
        self.assertNotInWorkingTree(TestRemove.files)
        if tree.has_versioned_directories():
            self.assertPathExists(TestRemove.backup_files)
        else:
            self.assertPathExists(TestRemove.backup_files_no_version_dirs)
        tree._validate()

    def test_remove_changed_file(self):
        """Removal of changed files must back it up."""
        tree = self.get_committed_tree(["a"])
        self.build_tree_contents([("a", b"some other new content!")])
        self.assertInWorkingTree("a")
        tree.remove("a", keep_files=False)
        self.assertNotInWorkingTree(TestRemove.files)
        self.assertPathExists("a.~1~")
        tree._validate()

    def test_remove_deleted_files(self):
        """Check that files are removed if they don't exist any more."""
        tree = self.get_committed_tree(TestRemove.files)
        for f in TestRemove.rfiles:
            osutils.delete_any(f)
        self.assertPathDoesNotExist(TestRemove.files)
        tree.remove(TestRemove.files, keep_files=False)
        self.assertRemovedAndDeleted(TestRemove.files)
        tree._validate()

    def test_remove_renamed_files(self):
        """Check that files are removed even if they are renamed."""
        tree = self.get_committed_tree(TestRemove.files)

        for f in TestRemove.rfiles:
            tree.rename_one(f, f + "x")
        rfilesx = ["bx/cx", "bx", "ax", "dx"]
        self.assertPathExists(rfilesx)

        tree.remove(rfilesx, keep_files=False)
        self.assertRemovedAndDeleted(rfilesx)
        tree._validate()

    def test_remove_renamed_changed_files(self):
        """Check that files that are renamed and changed are backed up."""
        tree = self.get_committed_tree(TestRemove.files)

        for f in TestRemove.rfiles:
            tree.rename_one(f, f + "x")
        rfilesx = ["bx/cx", "bx", "ax", "dx"]
        self.build_tree_contents(
            [("ax", b"changed and renamed!"), ("bx/cx", b"changed and renamed!")]
        )
        self.assertPathExists(rfilesx)

        tree.remove(rfilesx, keep_files=False)
        self.assertNotInWorkingTree(rfilesx)
        self.assertPathExists(["bx.~1~/cx.~1~", "bx.~1~", "ax.~1~"])
        if tree.supports_rename_tracking() or not tree.has_versioned_directories():
            self.assertPathDoesNotExist("dx.~1~")  # unchanged file
        else:
            self.assertPathExists("dx.~1~")  # renamed, so appears changed
        tree._validate()

    def test_force_remove_changed_files(self):
        """Check that changed files are removed and deleted when forced."""
        tree = self.get_tree(TestRemove.files)
        tree.add(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False, force=True)
        self.assertRemovedAndDeleted(TestRemove.files)
        self.assertPathDoesNotExist(["a.~1~", "b.~1~/", "b.~1~/c", "d.~1~/"])
        tree._validate()

    def test_remove_unknown_files(self):
        """Unknown files shuld be backed up"""
        tree = self.get_tree(TestRemove.files)
        tree.remove(TestRemove.files, keep_files=False)
        self.assertRemovedAndDeleted(TestRemove.files)
        if tree.has_versioned_directories():
            self.assertPathExists(TestRemove.backup_files)
        else:
            self.assertPathExists(TestRemove.backup_files_no_version_dirs)
        tree._validate()

    def test_remove_nonexisting_files(self):
        """Try to delete non-existing files."""
        tree = self.get_tree(TestRemove.files)
        tree.remove([""], keep_files=False)
        tree.remove(["xyz", "abc/def"], keep_files=False)
        tree._validate()

    def test_remove_unchanged_directory(self):
        """Unchanged directories should be deleted."""
        files = ["b/", "b/c", "b/sub_directory/", "b/sub_directory/with_file"]
        tree = self.get_committed_tree(files)
        tree.remove("b", keep_files=False)
        self.assertRemovedAndDeleted("b")
        tree._validate()

    def test_remove_absent_directory(self):
        """Removing a absent directory succeeds without corruption (#150438)."""
        paths = ["a/", "a/b"]
        tree = self.get_committed_tree(paths)
        tree.controldir.root_transport.delete_tree("a")
        tree.remove(["a"])
        self.assertRemovedAndDeleted("b")
        tree._validate()

    def test_remove_unknown_ignored_files(self):
        """Unknown ignored files should be deleted."""
        tree = self.get_committed_tree(["b/"])
        ignores.add_runtime_ignores(["*ignored*"])

        self.build_tree(["unknown_ignored_file"])
        self.assertNotEqual(None, tree.is_ignored("unknown_ignored_file"))
        tree.remove("unknown_ignored_file", keep_files=False)
        self.assertRemovedAndDeleted("unknown_ignored_file")

        self.build_tree(["b/unknown_ignored_file", "b/unknown_ignored_dir/"])
        self.assertNotEqual(None, tree.is_ignored("b/unknown_ignored_file"))
        self.assertNotEqual(None, tree.is_ignored("b/unknown_ignored_dir"))
        tree.remove("b", keep_files=False)
        self.assertRemovedAndDeleted("b")
        tree._validate()

    def test_remove_changed_ignored_files(self):
        """Changed ignored files should be backed up."""
        files = ["an_ignored_file"]
        tree = self.get_tree(files)
        tree.add(files)
        ignores.add_runtime_ignores(["*ignored*"])
        self.assertNotEqual(None, tree.is_ignored(files[0]))

        tree.remove(files, keep_files=False)
        self.assertNotInWorkingTree(files)
        self.assertPathExists("an_ignored_file.~1~")
        tree._validate()

    def test_dont_remove_directory_with_unknowns(self):
        """Directories with unknowns should be backed up."""
        directories = ["a/", "b/", "c/", "c/c/", "c/blah"]
        tree = self.get_committed_tree(directories)

        self.build_tree(["a/unknown_file"])
        tree.remove("a", keep_files=False)
        self.assertPathExists("a.~1~/unknown_file")

        self.build_tree(["b/unknown_directory"])
        tree.remove("b", keep_files=False)
        self.assertPathExists("b.~1~/unknown_directory")

        self.build_tree(["c/c/unknown_file"])
        tree.remove("c/c", keep_files=False)
        self.assertPathExists("c/c.~1~/unknown_file")

        tree.remove("c", keep_files=False)
        self.assertPathExists("c.~1~/")

        self.assertNotInWorkingTree(directories)
        tree._validate()

    def test_force_remove_directory_with_unknowns(self):
        """Unchanged non-empty directories should be deleted when forced."""
        files = ["b/", "b/c"]
        tree = self.get_committed_tree(files)

        other_files = [
            "b/unknown_file",
            "b/sub_directory/",
            "b/sub_directory/with_file",
            "b/sub_directory/sub_directory/",
        ]
        self.build_tree(other_files)

        self.assertInWorkingTree(files)
        self.assertPathExists(files)

        tree.remove("b", keep_files=False, force=True)

        self.assertRemovedAndDeleted(files)
        self.assertRemovedAndDeleted(other_files)
        tree._validate()

    def test_remove_directory_with_changed_file(self):
        """Backup directories with changed files."""
        files = ["b/", "b/c"]
        tree = self.get_committed_tree(files)
        self.build_tree_contents([("b/c", b"some other new content!")])

        tree.remove("b", keep_files=False)
        self.assertPathExists("b.~1~/c.~1~")
        self.assertNotInWorkingTree(files)

    def test_remove_force_directory_with_changed_file(self):
        """Delete directories with changed files when forced."""
        files = ["b/", "b/c"]
        tree = self.get_committed_tree(files)
        self.build_tree_contents([("b/c", b"some other new content!")])

        # see if we can force it now..
        tree.remove("b", keep_files=False, force=True)
        self.assertRemovedAndDeleted(files)
        tree._validate()

    def test_remove_directory_with_changed_emigrated_file(self):
        # As per bug #129880
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("somedir/",), (b"somedir/file", b"contents")])
        tree.add(["somedir", "somedir/file"])
        tree.commit(message="first")
        self.build_tree_contents([("somedir/file", b"changed")])
        tree.rename_one("somedir/file", "moved-file")
        tree.remove("somedir", keep_files=False)
        self.assertNotInWorkingTree("somedir")
        self.assertPathDoesNotExist("somedir")
        self.assertInWorkingTree("moved-file")
        self.assertPathExists("moved-file")

    def test_remove_directory_with_renames(self):
        """Delete directory with renames in or out."""
        files = ["a/", "a/file", "a/directory/", "a/directory/stuff", "b/"]
        files_to_move = ["a/file", "a/directory/"]

        tree = self.get_committed_tree(files)
        # move stuff from a=>b
        tree.move(["a/file", "a/directory"], to_dir="b")

        moved_files = ["b/file", "b/directory/"]
        self.assertRemovedAndDeleted(files_to_move)
        self.assertInWorkingTree(moved_files)
        self.assertPathExists(moved_files)

        # check if it works with renames out
        tree.remove("a", keep_files=False)
        self.assertRemovedAndDeleted(["a/"])

        # check if it works with renames in
        tree.remove("b", keep_files=False)
        self.assertRemovedAndDeleted(["b/"])
        tree._validate()

    def test_non_cwd(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/dir/", "tree/dir/file"])
        tree.add(["dir", "dir/file"])
        tree.commit("add file")
        tree.remove("dir/", keep_files=False)
        self.assertPathDoesNotExist("tree/dir/file")
        self.assertNotInWorkingTree("tree/dir/file", "tree")
        tree._validate()

    def test_remove_uncommitted_removed_file(self):
        # As per bug #152811
        tree = self.get_committed_tree(["a"])
        tree.remove("a", keep_files=False)
        tree.remove("a", keep_files=False)
        self.assertPathDoesNotExist("a")
        tree._validate()

    def test_remove_file_and_containing_dir(self):
        tree = self.get_committed_tree(["config/", "config/file"])
        tree.remove("config/file", keep_files=False)
        tree.remove("config", keep_files=False)
        self.assertPathDoesNotExist("config/file")
        self.assertPathDoesNotExist("config")
        tree._validate()

    def test_remove_dir_before_bzr(self):
        # As per bug #272648. Note that a file must be present in the directory
        # or the bug doesn't manifest itself.
        tree = self.get_committed_tree([".aaa/", ".aaa/file"])
        tree.remove(".aaa/", keep_files=False)
        self.assertPathDoesNotExist(".aaa/file")
        self.assertPathDoesNotExist(".aaa")
        tree._validate()

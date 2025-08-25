# Copyright (C) 2006-2010 Canonical Ltd
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


import os
import sys

from breezy import osutils
from breezy.tests import (
    TestCaseWithTransport,
    TestNotApplicable,
    TestSkipped,
    features,
    script,
)

from ...workingtree import WorkingTree

_id = b"-id"
a = "a"
b = "b/"
c = "b/c"
d = "d/"
files = (a, b, c, d)


class TestRemove(TestCaseWithTransport):
    def _make_tree_and_add(self, paths):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            self.build_tree(paths)
            for path in paths:
                file_id = path.replace("/", "_").encode("utf-8") + _id
                tree.add(path, ids=file_id)
        return tree

    def assertFilesDeleted(self, files):
        for f in files:
            f.encode("utf-8") + _id
            self.assertNotInWorkingTree(f)
            self.assertPathDoesNotExist(f)

    def assertFilesUnversioned(self, files):
        for f in files:
            self.assertNotInWorkingTree(f)
            self.assertPathExists(f)

    def changeFile(self, file_name):
        with open(file_name, "ab") as f:
            f.write(b"\nsome other new content!")

    def run_bzr_remove_changed_files(self, files_to_remove, working_dir=None):
        self.run_bzr(["remove"] + list(files_to_remove), working_dir=working_dir)

    def test_remove_new_no_files_specified(self):
        self.make_branch_and_tree(".")
        self.run_bzr_error(["brz: ERROR: No matching files."], "remove --new")
        self.run_bzr_error(["brz: ERROR: No matching files."], "remove --new .")

    def test_remove_no_files_specified(self):
        tree = self._make_tree_and_add(["foo"])
        out, err = self.run_bzr(["rm"])
        self.assertEqual("", err)
        self.assertEqual("", out)
        self.assertInWorkingTree("foo", tree=tree)
        self.assertPathExists("foo")

    def test_remove_no_files_specified_missing_dir_and_contents(self):
        tree = self._make_tree_and_add(
            ["foo", "dir/", "dir/missing/", "dir/missing/child"]
        )
        self.get_transport(".").delete_tree("dir/missing")
        out, err = self.run_bzr(["rm"])
        self.assertEqual("", out)
        self.assertEqual("removed dir/missing/child\nremoved dir/missing\n", err)
        # non-missing paths not touched:
        self.assertInWorkingTree("foo", tree=tree)
        self.assertPathExists("foo")
        self.assertInWorkingTree("dir", tree=tree)
        self.assertPathExists("dir")
        # missing files unversioned
        self.assertNotInWorkingTree("dir/missing", tree=tree)
        self.assertNotInWorkingTree("dir/missing/child", tree=tree)

    def test_remove_no_files_specified_already_deleted(self):
        tree = self._make_tree_and_add(["foo", "bar"])
        tree.commit("save foo and bar")
        os.unlink("bar")
        self.run_bzr(["rm"])
        self.assertFalse(tree.is_versioned("bar"))
        # Running rm with a deleted file does not error.
        out, err = self.run_bzr(["rm"])
        self.assertEqual("", out)
        self.assertEqual("", err)

    def test_remove_no_files_specified_missing_file(self):
        tree = self._make_tree_and_add(["foo", "bar"])
        os.unlink("bar")
        out, err = self.run_bzr(["rm"])
        self.assertEqual("", out)
        self.assertEqual("removed bar\n", err)
        # non-missing files not touched:
        self.assertInWorkingTree("foo", tree=tree)
        self.assertPathExists("foo")
        # missing files unversioned
        self.assertNotInWorkingTree("bar", tree=tree)

    def test_remove_no_files_specified_missing_link(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self._make_tree_and_add(["foo"])
        os.symlink("foo", "linkname")
        tree.add(["linkname"])
        os.unlink("linkname")
        out, err = self.run_bzr(["rm"])
        self.assertEqual("", out)
        self.assertEqual("removed linkname\n", err)
        # non-missing files not touched:
        self.assertInWorkingTree("foo", tree=tree)
        self.assertPathExists("foo")
        # missing files unversioned
        self.assertNotInWorkingTree("linkname", tree=tree)

    def test_rm_one_file(self):
        self._make_tree_and_add([a])
        self.run_bzr("commit -m 'added a'")
        self.run_bzr("rm a", error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_one_file(self):
        self._make_tree_and_add([a])
        self.run_bzr("commit -m 'added a'")
        self.run_bzr("remove a", error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_keep_one_file(self):
        self._make_tree_and_add([a])
        self.run_bzr("remove --keep a", error_regexes=["removed a"])
        self.assertFilesUnversioned([a])

    def test_remove_one_deleted_file(self):
        self._make_tree_and_add([a])
        self.run_bzr("commit -m 'added a'")
        os.unlink(a)
        self.assertInWorkingTree(a)
        self.run_bzr("remove a")
        self.assertNotInWorkingTree(a)

    def test_remove_invalid_files(self):
        self.build_tree(files)
        self.make_branch_and_tree(".")
        self.run_bzr(["remove", ".", "xyz", "abc/def"])

    def test_remove_unversioned_files(self):
        self.build_tree(files)
        self.make_branch_and_tree(".")
        self.run_bzr_remove_changed_files(files)

    def test_remove_changed_files(self):
        self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.changeFile(a)
        self.changeFile(c)
        self.run_bzr_remove_changed_files(files)

    def test_remove_changed_ignored_files(self):
        self._make_tree_and_add(["a"])
        self.run_bzr(["ignore", "a"])
        self.run_bzr_remove_changed_files(["a"])

    def test_remove_changed_files_from_child_dir(self):
        if sys.platform == "win32":
            raise TestSkipped("Windows unable to remove '.' directory")
        self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.changeFile(a)
        self.changeFile(c)
        self.run_bzr_remove_changed_files(["../a", "c", ".", "../d"], working_dir="b")
        self.assertNotInWorkingTree(files)
        self.assertPathDoesNotExist(files)

    def test_remove_keep_unversioned_files(self):
        self.build_tree(files)
        self.make_branch_and_tree(".")
        self.run_bzr("remove --keep a", error_regexes=["a is not versioned."])
        self.assertFilesUnversioned(files)

    def test_remove_no_backup_unversioned_files(self):
        self.build_tree(files)
        self.make_branch_and_tree(".")
        script.ScriptRunner().run_script(
            self,
            """
        $ brz remove --no-backup a b/ b/c d/
        2>deleted d
        2>removed b/c (but kept a copy: b/c.~1~)
        2>deleted b
        2>deleted a
        """,
        )
        self.assertFilesDeleted(files)

    def test_remove_deleted_files(self):
        self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        my_files = list(files)
        my_files.sort(reverse=True)
        for f in my_files:
            osutils.delete_any(f)
        self.assertInWorkingTree(files)
        self.assertPathDoesNotExist(files)
        self.run_bzr("remove " + " ".join(files))
        self.assertNotInWorkingTree(a)
        self.assertPathDoesNotExist(files)

    def test_remove_non_existing_files(self):
        self._make_tree_and_add([])
        self.run_bzr(["remove", "b"])

    def test_remove_keep_non_existing_files(self):
        self._make_tree_and_add([])
        self.run_bzr("remove --keep b", error_regexes=["b is not versioned."])

    def test_remove_files(self):
        self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.run_bzr(
            "remove a b b/c d",
            error_regexes=["deleted a", "deleted b", "deleted b/c", "deleted d"],
        )
        self.assertFilesDeleted(files)

    def test_remove_keep_files(self):
        self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.run_bzr(
            "remove --keep a b b/c d",
            error_regexes=["removed a", "removed b", "removed b/c", "removed d"],
        )
        self.assertFilesUnversioned(files)

    def test_remove_with_new(self):
        self._make_tree_and_add(files)
        self.run_bzr(
            "remove --new --keep",
            error_regexes=["removed a", "removed b", "removed b/c"],
        )
        self.assertFilesUnversioned(files)

    def test_remove_with_new_in_dir1(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr(
            "remove --new --keep b b/c", error_regexes=["removed b", "removed b/c"]
        )
        tree = WorkingTree.open(".")
        self.assertInWorkingTree(a)
        self.assertEqual(tree.path2id(a), a.encode("utf-8") + _id)
        self.assertFilesUnversioned([b, c])

    def test_remove_with_new_in_dir2(self):
        self._make_tree_and_add(files)
        self.run_bzr(
            "remove --new --keep .",
            error_regexes=["removed a", "removed b", "removed b/c"],
        )
        WorkingTree.open(".")
        self.assertFilesUnversioned(files)

    def test_remove_backslash(self):
        # pad.lv/176263
        if os.path.sep == "\\":
            raise TestNotApplicable(
                "unable to add filenames with backslashes where "
                " it is the path separator"
            )
        self.make_branch_and_tree(".")
        self.build_tree(["\\"])
        self.assertEqual("adding \\\n", self.run_bzr("add \\\\")[0])
        self.assertEqual("\\\n", self.run_bzr("ls --versioned")[0])
        self.assertEqual("", self.run_bzr("rm \\\\")[0])
        self.assertEqual("", self.run_bzr("ls --versioned")[0])

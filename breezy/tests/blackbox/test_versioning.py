# Copyright (C) 2005, 2006, 2007, 2009-2012, 2016 Canonical Ltd
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


"""Tests of simple versioning operations."""

# TODO: test trying to commit within a directory that is not yet added

import os

from breezy.osutils import pathjoin
from breezy.tests import TestCaseWithTransport
from breezy.trace import mutter
from breezy.workingtree import WorkingTree


class TestMkdir(TestCaseWithTransport):
    def test_mkdir_fails_cleanly(self):
        """'mkdir' fails cleanly when no working tree is available.
        https://bugs.launchpad.net/bzr/+bug/138600.
        """
        # Since there is a safety working tree above us, we create a bare repo
        # here locally.
        self.make_repository(".")
        self.run_bzr(["mkdir", "abc"], retcode=3)
        self.assertPathDoesNotExist("abc")

    def test_mkdir(self):
        """Basic 'brz mkdir' operation."""
        self.make_branch_and_tree(".")
        self.run_bzr(["mkdir", "foo"])
        self.assertTrue(os.path.isdir("foo"))

        self.run_bzr(["mkdir", "foo"], retcode=3)

        wt = WorkingTree.open(".")

        delta = wt.changes_from(wt.basis_tree())

        self.log("delta.added = {!r}".format(delta.added))

        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0].path[1], "foo")
        self.assertFalse(delta.modified)

    def test_mkdir_in_subdir(self):
        """'brz mkdir' operation in subdirectory."""
        self.make_branch_and_tree(".")
        self.run_bzr(["mkdir", "dir"])
        self.assertTrue(os.path.isdir("dir"))

        self.log("Run mkdir in subdir")
        self.run_bzr(["mkdir", "subdir"], working_dir="dir")
        self.assertTrue(os.path.isdir("dir/subdir"))

        wt = WorkingTree.open(".")

        delta = wt.changes_from(wt.basis_tree())

        self.log("delta.added = {!r}".format(delta.added))

        self.assertEqual(len(delta.added), 2)
        self.assertEqual(delta.added[0].path[1], "dir")
        self.assertEqual(delta.added[1].path[1], pathjoin("dir", "subdir"))
        self.assertFalse(delta.modified)

    def test_mkdir_w_nested_trees(self):
        """'brz mkdir' with nested trees."""
        self.make_branch_and_tree(".")
        self.make_branch_and_tree("a")
        self.make_branch_and_tree("a/b")

        self.run_bzr(["mkdir", "dir", "a/dir", "a/b/dir"])
        self.assertTrue(os.path.isdir("dir"))
        self.assertTrue(os.path.isdir("a/dir"))
        self.assertTrue(os.path.isdir("a/b/dir"))

        wt = WorkingTree.open(".")
        wt_a = WorkingTree.open("a")
        wt_b = WorkingTree.open("a/b")

        delta = wt.changes_from(wt.basis_tree())
        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0].path[1], "dir")
        self.assertFalse(delta.modified)

        delta = wt_a.changes_from(wt_a.basis_tree())
        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0].path[1], "dir")
        self.assertFalse(delta.modified)

        delta = wt_b.changes_from(wt_b.basis_tree())
        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0].path[1], "dir")
        self.assertFalse(delta.modified)

    def test_mkdir_quiet(self):
        """'brz mkdir --quiet' should not print a status message."""
        self.make_branch_and_tree(".")
        out, err = self.run_bzr(["mkdir", "--quiet", "foo"])
        self.assertEqual("", err)
        self.assertEqual("", out)


class SubdirCommit(TestCaseWithTransport):
    def test_subdir_commit(self):
        """Test committing a subdirectory, and committing a directory."""
        tree = self.make_branch_and_tree(".")
        b = tree.branch
        self.build_tree(["a/", "b/"])

        def set_contents(contents):
            self.build_tree_contents(
                [
                    ("a/one", contents),
                    ("b/two", contents),
                    ("top", contents),
                ]
            )

        set_contents(b"old contents")
        tree.smart_add(["."])
        tree.commit("first revision")
        set_contents(b"new contents")

        mutter("start selective subdir commit")
        self.run_bzr(["commit", "a", "-m", "commit a only"])

        new = b.repository.revision_tree(b.get_rev_id(2))
        new.lock_read()

        def get_text_by_path(tree, path):
            return tree.get_file_text(path)

        self.assertEqual(get_text_by_path(new, "b/two"), b"old contents")
        self.assertEqual(get_text_by_path(new, "top"), b"old contents")
        self.assertEqual(get_text_by_path(new, "a/one"), b"new contents")
        new.unlock()

        # commit from here should do nothing
        self.run_bzr(
            ["commit", ".", "-m", "commit subdir only", "--unchanged"], working_dir="a"
        )
        v3 = b.repository.revision_tree(b.get_rev_id(3))
        v3.lock_read()
        self.assertEqual(get_text_by_path(v3, "b/two"), b"old contents")
        self.assertEqual(get_text_by_path(v3, "top"), b"old contents")
        self.assertEqual(get_text_by_path(v3, "a/one"), b"new contents")
        v3.unlock()

        # commit in subdirectory commits whole tree
        self.run_bzr(["commit", "-m", "commit whole tree from subdir"], working_dir="a")
        v4 = b.repository.revision_tree(b.get_rev_id(4))
        v4.lock_read()
        self.assertEqual(get_text_by_path(v4, "b/two"), b"new contents")
        self.assertEqual(get_text_by_path(v4, "top"), b"new contents")
        v4.unlock()

        # TODO: factor out some kind of assert_tree_state() method

# Copyright (C) 2006-2010 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for the WorkingTree.merge_from_branch api."""

import os

from breezy import errors, merge
from breezy.tests import per_workingtree

from ...workingtree import PointlessMerge


class TestMergeFromBranch(per_workingtree.TestCaseWithWorkingTree):
    def create_two_trees_for_merging(self):
        """Create two trees that can be merged from.

        This sets self.tree_from, self.first_rev, self.tree_to, self.second_rev
        and self.to_second_rev.
        """
        self.tree_from = self.make_branch_and_tree("from")
        self.first_rev = self.tree_from.commit("first post")
        self.tree_to = self.tree_from.controldir.sprout("to").open_workingtree()
        self.second_rev = self.tree_from.commit(
            "second rev on from", allow_pointless=True
        )
        self.to_second_rev = self.tree_to.commit(
            "second rev on to", allow_pointless=True
        )

    def test_smoking_merge(self):
        """Smoke test of merge_from_branch."""
        self.create_two_trees_for_merging()
        self.tree_to.merge_from_branch(self.tree_from.branch)
        self.assertEqual(
            [self.to_second_rev, self.second_rev], self.tree_to.get_parent_ids()
        )

    def test_merge_to_revision(self):
        """Merge from a branch to a revision that is not the tip."""
        self.create_two_trees_for_merging()
        self.third_rev = self.tree_from.commit("real_tip")
        self.tree_to.merge_from_branch(
            self.tree_from.branch, to_revision=self.second_rev
        )
        self.assertEqual(
            [self.to_second_rev, self.second_rev], self.tree_to.get_parent_ids()
        )

    def test_compare_after_merge(self):
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"text-a")])
        tree_a.add("file")
        tree_a.commit("added file")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        os.unlink("tree_a/file")
        tree_a.commit("deleted file")
        self.build_tree_contents([("tree_b/file", b"text-b")])
        tree_b.commit("changed file")
        tree_a.merge_from_branch(tree_b.branch)
        tree_a.lock_read()
        self.addCleanup(tree_a.unlock)
        list(tree_a.iter_changes(tree_a.basis_tree()))

    def test_merge_empty(self):
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"text-a")])
        tree_a.add("file")
        tree_a.commit("added file")
        tree_b = self.make_branch_and_tree("treeb")
        self.assertRaises(errors.NoCommits, tree_a.merge_from_branch, tree_b.branch)
        tree_b.merge_from_branch(tree_a.branch)

    def test_merge_base(self):
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"text-a")])
        tree_a.add("file")
        rev1 = tree_a.commit("added file")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        os.unlink("tree_a/file")
        tree_a.commit("deleted file")
        self.build_tree_contents([("tree_b/file", b"text-b")])
        tree_b.commit("changed file")
        self.assertRaises(
            PointlessMerge,
            tree_a.merge_from_branch,
            tree_b.branch,
            from_revision=tree_b.branch.last_revision(),
        )
        tree_a.merge_from_branch(tree_b.branch, from_revision=rev1)
        tree_a.lock_read()
        self.addCleanup(tree_a.unlock)
        changes = list(tree_a.iter_changes(tree_a.basis_tree()))
        self.assertEqual(1, len(changes), changes)

    def test_merge_type(self):
        this = self.make_branch_and_tree("this")
        self.build_tree_contents([("this/foo", b"foo")])
        this.add("foo")
        this.commit("added foo")
        other = this.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("other/foo", b"bar")])
        other.commit("content -> bar")
        self.build_tree_contents([("this/foo", b"baz")])
        this.commit("content -> baz")

        class QuxMerge(merge.Merge3Merger):
            def text_merge(self, trans_id, paths):
                self.tt.create_file([b"qux"], trans_id)

        this.merge_from_branch(other.branch, merge_type=QuxMerge)
        self.assertEqual(b"qux", this.get_file_text("foo"))


class TestMergedBranch(per_workingtree.TestCaseWithWorkingTree):
    def make_inner_branch(self):
        bld_inner = self.make_branch_builder("inner")
        bld_inner.start_series()
        rev1 = bld_inner.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("dir", None, "directory", "")),
                ("add", ("dir/file1", None, "file", b"file1 content\n")),
                ("add", ("file3", None, "file", b"file3 content\n")),
            ],
        )
        rev4 = bld_inner.build_snapshot(
            [rev1], [("add", ("file4", None, "file", b"file4 content\n"))]
        )
        rev5 = bld_inner.build_snapshot([rev4], [("rename", ("file4", "dir/file4"))])
        rev3 = bld_inner.build_snapshot(
            [rev1],
            [
                ("modify", ("file3", b"new file3 contents\n")),
            ],
        )
        rev2 = bld_inner.build_snapshot(
            [rev1],
            [
                ("add", ("dir/file2", None, "file", b"file2 content\n")),
            ],
        )
        bld_inner.finish_series()
        br = bld_inner.get_branch()
        return br, [rev1, rev2, rev3, rev4, rev5]

    def assertTreeLayout(self, expected, tree):
        with tree.lock_read():
            actual = [e[0] for e in tree.list_files()]
            # list_files doesn't guarantee order
            actual = sorted(actual)
            self.assertEqual(expected, actual)

    def make_outer_tree(self):
        outer = self.make_branch_and_tree("outer")
        self.build_tree_contents([("outer/foo", b"foo")])
        outer.add("foo")
        outer.commit("added foo")
        inner, revs = self.make_inner_branch()
        outer.merge_from_branch(inner, to_revision=revs[0], from_revision=b"null:")
        # retain original root id.
        if outer.supports_setting_file_ids():
            outer.set_root_id(outer.basis_tree().path2id(""))
        outer.commit("merge inner branch")
        outer.mkdir("dir-outer")
        outer.move(["dir", "file3"], to_dir="dir-outer")
        outer.commit("rename imported dir and file3 to dir-outer")
        return outer, inner, revs

    def test_file1_deleted_in_dir(self):
        outer, inner, _revs = self.make_outer_tree()
        outer.remove(["dir-outer/dir/file1"], keep_files=False)
        outer.commit("delete file1")
        outer.merge_from_branch(inner)
        outer.commit("merge the rest")
        if outer.supports_rename_tracking():
            self.assertTreeLayout(
                [
                    "dir-outer",
                    "dir-outer/dir",
                    "dir-outer/dir/file2",
                    "dir-outer/file3",
                    "foo",
                ],
                outer,
            )
        else:
            self.assertTreeLayout(
                [
                    "dir",
                    "dir-outer",
                    "dir-outer/dir",
                    "dir-outer/file3",
                    "dir/file2",
                    "foo",
                ],
                outer,
            )

    def test_file3_deleted_in_root(self):
        # Reproduce bug #375898
        outer, inner, _revs = self.make_outer_tree()
        outer.remove(["dir-outer/file3"], keep_files=False)
        outer.commit("delete file3")
        outer.merge_from_branch(inner)
        outer.commit("merge the rest")
        if outer.supports_rename_tracking():
            self.assertTreeLayout(
                [
                    "dir-outer",
                    "dir-outer/dir",
                    "dir-outer/dir/file1",
                    "dir-outer/dir/file2",
                    "foo",
                ],
                outer,
            )
        else:
            self.assertTreeLayout(
                [
                    "dir",
                    "dir-outer",
                    "dir-outer/dir",
                    "dir-outer/dir/file1",
                    "dir/file2",
                    "foo",
                ],
                outer,
            )

    def test_file3_in_root_conflicted(self):
        outer, inner, revs = self.make_outer_tree()
        outer.remove(["dir-outer/file3"], keep_files=False)
        outer.commit("delete file3")
        nb_conflicts = outer.merge_from_branch(inner, to_revision=revs[2])
        if outer.supports_rename_tracking():
            self.assertEqual(4, len(nb_conflicts))
        else:
            self.assertEqual(1, len(nb_conflicts))
        self.assertTreeLayout(
            [
                "dir-outer",
                "dir-outer/dir",
                "dir-outer/dir/file1",
                # Ideally th conflict helpers should be in
                # dir-outer/dir but since we can't easily find
                # back the file3 -> outer-dir/dir rename, root
                # is good enough -- vila 20100401
                "file3.BASE",
                "file3.OTHER",
                "foo",
            ],
            outer,
        )

    def test_file4_added_in_root(self):
        outer, inner, revs = self.make_outer_tree()
        nb_conflicts = outer.merge_from_branch(inner, to_revision=revs[3])
        # file4 could not be added to its original root, so it gets added to
        # the new root with a conflict.
        if outer.supports_rename_tracking():
            self.assertEqual(1, len(nb_conflicts))
        else:
            self.assertEqual(0, len(nb_conflicts))
        self.assertTreeLayout(
            [
                "dir-outer",
                "dir-outer/dir",
                "dir-outer/dir/file1",
                "dir-outer/file3",
                "file4",
                "foo",
            ],
            outer,
        )

    def test_file4_added_then_renamed(self):
        outer, inner, revs = self.make_outer_tree()
        # 1 conflict, because file4 can't be put into the old root
        nb_conflicts = outer.merge_from_branch(inner, to_revision=revs[3])
        if outer.supports_rename_tracking():
            self.assertEqual(1, len(nb_conflicts))
        else:
            self.assertEqual(0, len(nb_conflicts))
        try:
            outer.set_conflicts([])
        except errors.UnsupportedOperation:
            # WT2 doesn't have a separate list of conflicts to clear. It
            # actually says there is a conflict, but happily forgets all about
            # it.
            pass
        outer.commit("added file4")
        # And now file4 gets renamed into an existing dir
        nb_conflicts = outer.merge_from_branch(inner, to_revision=revs[4])
        if outer.supports_rename_tracking():
            self.assertEqual(1, len(nb_conflicts))
            self.assertTreeLayout(
                [
                    "dir-outer",
                    "dir-outer/dir",
                    "dir-outer/dir/file1",
                    "dir-outer/dir/file4",
                    "dir-outer/file3",
                    "foo",
                ],
                outer,
            )
        else:
            if outer.has_versioned_directories():
                self.assertEqual(2, len(nb_conflicts))
            else:
                self.assertEqual(0, len(nb_conflicts))
            self.assertTreeLayout(
                [
                    "dir",
                    "dir-outer",
                    "dir-outer/dir",
                    "dir-outer/dir/file1",
                    "dir-outer/file3",
                    "dir/file4",
                    "foo",
                ],
                outer,
            )

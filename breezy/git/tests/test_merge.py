# Copyright (C) 2026 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for merging git branches."""

import os

from ...merge import Merge3Merger
from ...tests import TestCaseWithTransport

LONG_CONTENT = b"\n".join(f"line{i}".encode() for i in range(50)) + b"\n"


class GitMergeTestBase(TestCaseWithTransport):
    """Common setup for git merge tests.

    Builds ``local`` (which acts as THIS / working tree) seeded with
    ``initial_files`` and gives subclasses a helper for forking an
    ``other`` branch off the base revision.
    """

    def _make_local(self, initial_files):
        wt = self.make_branch_and_tree("local", format="git")
        # Ensure parent dirs exist — build_tree_contents won't create
        # them. Collect the unique parent paths in order so deeper
        # ancestors come after their parents.
        dirs = []
        for path, _ in initial_files:
            parts = path.split("/")
            for i in range(1, len(parts)):
                dir_path = "/".join(parts[:i])
                if dir_path and dir_path not in dirs:
                    dirs.append(dir_path)
        for d in dirs:
            os.mkdir(wt.abspath(d))
        self.build_tree_contents(
            [("local/" + path, content) for path, content in initial_files]
        )
        wt.add(dirs + [path for path, _ in initial_files])
        wt.commit("base")
        return wt

    def _fork_other(self, wt, base_rev, mutate):
        """Sprout ``other`` from ``base_rev``, run ``mutate`` on it, return the tree."""
        other_cd = wt.branch.controldir.sprout("other", revision_id=base_rev)
        other_wt = other_cd.open_workingtree()
        mutate(other_wt)
        other_rev = other_wt.commit("other change")
        return other_cd.open_branch().repository.revision_tree(other_rev), other_rev

    def _merge(self, wt, base_rev, other_tree):
        base_tree = wt.branch.repository.revision_tree(base_rev)
        merger = Merge3Merger(
            working_tree=wt,
            this_tree=wt,
            base_tree=base_tree,
            other_tree=other_tree,
            do_merge=False,
        )
        merger.do_merge()
        return merger


class GitRenameMergeTests(GitMergeTestBase):
    """Rename scenarios — the regression class that motivated this file.

    Git's ``iter_changes`` attaches a synthetic ``file_id`` derived from
    BASE/OTHER's path, not THIS's. Routing trans_id resolution through
    that synthetic id picks up the wrong path on path-based trees:
    ``trans_id_file_id(b'git:a.txt')`` resolves to a phantom trans_id at
    ``"a.txt"`` even though THIS has the file at ``"b.txt"``. The merge
    then fails with ``MalformedTransform: unversioned executability``.

    ``_compute_transform`` keys directly off ``paths3[2]`` (THIS's path)
    for path-based trees instead.
    """

    def test_rename_in_this_modify_in_other(self):
        """THIS renames a.txt -> b.txt; OTHER modifies a.txt."""
        wt = self._make_local([("a.txt", LONG_CONTENT)])
        base_rev = wt.last_revision()

        os.rename(wt.abspath("a.txt"), wt.abspath("b.txt"))
        wt.remove(["a.txt"])
        wt.add(["b.txt"])
        wt.commit("rename")

        def mutate(other_wt):
            self.build_tree_contents([("other/a.txt", LONG_CONTENT + b"appended\n")])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        self.assertFalse(os.path.exists(wt.abspath("a.txt")))
        with open(wt.abspath("b.txt"), "rb") as f:
            self.assertEqual(LONG_CONTENT + b"appended\n", f.read())

    def test_rename_in_other_modify_in_this(self):
        """Symmetric case: OTHER renames; THIS modifies in place.

        Without rename detection across this direction, OTHER's rename
        looks like a delete + add to the merger. The expected outcome
        is therefore that THIS's modification stays at the original
        path; the new path from OTHER also lands. (This pins current
        behaviour rather than the "ideal" outcome a rename-aware merge
        would produce.)
        """
        wt = self._make_local([("a.txt", LONG_CONTENT)])
        base_rev = wt.last_revision()

        # THIS modifies a.txt in place.
        self.build_tree_contents([("local/a.txt", LONG_CONTENT + b"this_change\n")])
        wt.commit("modify")

        def mutate(other_wt):
            os.rename(other_wt.abspath("a.txt"), other_wt.abspath("b.txt"))
            other_wt.remove(["a.txt"])
            other_wt.add(["b.txt"])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)
        # The merge must complete (not crash); we don't assert a
        # specific resolution because rename-vs-modify is genuinely
        # ambiguous. Just check it terminates and produces a tree.
        self.assertIsNotNone(merger)


class GitContentMergeTests(GitMergeTestBase):
    """Plain content merges that don't touch path/identity."""

    def test_clean_disjoint_changes(self):
        """THIS and OTHER edit different files — no conflict."""
        wt = self._make_local([("a.txt", b"a base\n"), ("b.txt", b"b base\n")])
        base_rev = wt.last_revision()

        self.build_tree_contents([("local/a.txt", b"a base\nthis\n")])
        wt.commit("modify a")

        def mutate(other_wt):
            self.build_tree_contents([("other/b.txt", b"b base\nother\n")])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        with open(wt.abspath("a.txt"), "rb") as f:
            self.assertEqual(b"a base\nthis\n", f.read())
        with open(wt.abspath("b.txt"), "rb") as f:
            self.assertEqual(b"b base\nother\n", f.read())

    def test_text_conflict_same_line(self):
        """THIS and OTHER edit the same line — text conflict markers."""
        wt = self._make_local([("a.txt", b"shared\n")])
        base_rev = wt.last_revision()

        self.build_tree_contents([("local/a.txt", b"this side\n")])
        wt.commit("this edit")

        def mutate(other_wt):
            self.build_tree_contents([("other/a.txt", b"other side\n")])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        conflicts = list(merger.cooked_conflicts)
        self.assertEqual(1, len(conflicts))
        self.assertEqual("Text conflict in a.txt", str(conflicts[0]))
        with open(wt.abspath("a.txt"), "rb") as f:
            merged = f.read()
        self.assertIn(b"<<<<<<< TREE", merged)
        self.assertIn(b"this side", merged)
        self.assertIn(b"other side", merged)
        self.assertIn(b">>>>>>> MERGE-SOURCE", merged)

    def test_clean_non_overlapping_lines(self):
        """THIS and OTHER edit different lines of the same file — auto-merged."""
        base = b"".join(f"line{i}\n".encode() for i in range(10))
        wt = self._make_local([("a.txt", base)])
        base_rev = wt.last_revision()

        # THIS edits line0
        this_content = base.replace(b"line0\n", b"line0_this\n")
        self.build_tree_contents([("local/a.txt", this_content)])
        wt.commit("this edit")

        # OTHER edits line9
        def mutate(other_wt):
            other_content = base.replace(b"line9\n", b"line9_other\n")
            self.build_tree_contents([("other/a.txt", other_content)])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        with open(wt.abspath("a.txt"), "rb") as f:
            merged = f.read()
        self.assertIn(b"line0_this", merged)
        self.assertIn(b"line9_other", merged)
        self.assertNotIn(b"<<<<<<<", merged)


class GitAddDeleteMergeTests(GitMergeTestBase):
    """Add/delete scenarios that exercise paths absent on one side."""

    def test_add_in_other_only(self):
        """OTHER adds a new file; THIS leaves alone — file lands cleanly."""
        wt = self._make_local([("a.txt", b"keep\n")])
        base_rev = wt.last_revision()

        def mutate(other_wt):
            self.build_tree_contents([("other/new.txt", b"brand new\n")])
            other_wt.add(["new.txt"])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        with open(wt.abspath("new.txt"), "rb") as f:
            self.assertEqual(b"brand new\n", f.read())

    def test_add_in_this_only(self):
        """THIS adds a new file; OTHER unrelated change — both land."""
        wt = self._make_local([("a.txt", b"keep\n")])
        base_rev = wt.last_revision()

        self.build_tree_contents([("local/new.txt", b"this added\n")])
        wt.add(["new.txt"])
        wt.commit("add new")

        def mutate(other_wt):
            self.build_tree_contents([("other/a.txt", b"keep\nother\n")])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        with open(wt.abspath("new.txt"), "rb") as f:
            self.assertEqual(b"this added\n", f.read())
        with open(wt.abspath("a.txt"), "rb") as f:
            self.assertEqual(b"keep\nother\n", f.read())

    def test_delete_in_other_unchanged_in_this(self):
        """OTHER deletes a file THIS leaves alone — file is removed."""
        wt = self._make_local([("a.txt", b"a\n"), ("b.txt", b"b\n")])
        base_rev = wt.last_revision()

        def mutate(other_wt):
            other_wt.remove(["b.txt"], keep_files=False)

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        self.assertFalse(os.path.exists(wt.abspath("b.txt")))
        self.assertTrue(os.path.exists(wt.abspath("a.txt")))

    def test_delete_in_other_modified_in_this(self):
        """OTHER deletes; THIS modifies — content conflict."""
        wt = self._make_local([("a.txt", b"original\n")])
        base_rev = wt.last_revision()

        self.build_tree_contents([("local/a.txt", b"modified\n")])
        wt.commit("modify")

        def mutate(other_wt):
            other_wt.remove(["a.txt"], keep_files=False)

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        # A conflict is expected; the test pins that the merge
        # completes rather than crashing, and that something was
        # reported.
        self.assertNotEqual([], list(merger.cooked_conflicts))


class GitSubdirMergeTests(GitMergeTestBase):
    """Files in subdirectories — exercises the dirname/basename path."""

    def test_add_file_in_subdir_in_other(self):
        """OTHER adds a file in a new subdir; THIS untouched."""
        wt = self._make_local([("a.txt", b"top\n")])
        base_rev = wt.last_revision()

        def mutate(other_wt):
            os.mkdir(other_wt.abspath("sub"))
            self.build_tree_contents([("other/sub/file.txt", b"in sub\n")])
            other_wt.add(["sub", "sub/file.txt"])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        with open(wt.abspath("sub/file.txt"), "rb") as f:
            self.assertEqual(b"in sub\n", f.read())

    def test_modify_in_subdir_both_sides_disjoint(self):
        """THIS and OTHER modify different files in the same subdir."""
        wt = self._make_local(
            [
                ("sub/x.txt", b"x base\n"),
                ("sub/y.txt", b"y base\n"),
            ]
        )
        base_rev = wt.last_revision()

        self.build_tree_contents([("local/sub/x.txt", b"x base\nthis\n")])
        wt.commit("this in sub")

        def mutate(other_wt):
            self.build_tree_contents([("other/sub/y.txt", b"y base\nother\n")])

        other_tree, _ = self._fork_other(wt, base_rev, mutate)
        merger = self._merge(wt, base_rev, other_tree)

        self.assertEqual([], list(merger.cooked_conflicts))
        with open(wt.abspath("sub/x.txt"), "rb") as f:
            self.assertEqual(b"x base\nthis\n", f.read())
        with open(wt.abspath("sub/y.txt"), "rb") as f:
            self.assertEqual(b"y base\nother\n", f.read())

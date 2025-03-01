# Copyright (C) 2006-2012, 2016 Canonical Ltd
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
from io import BytesIO

from breezy.tests.matchers import MatchesTreeChanges
from breezy.tests.per_tree import TestCaseWithTree

from ... import revision as _mod_revision
from ... import tests, trace
from ...diff import show_diff_trees
from ...merge import Merge3Merger, Merger
from ...transform import ROOT_PARENT, resolve_conflicts
from ...tree import TreeChange, find_previous_path
from ..features import SymlinkFeature, UnicodeFilenameFeature


class TestTransformPreview(TestCaseWithTree):
    def create_tree(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a", b"content 1")])
        tree.add("a")
        revid1 = tree.commit("rev1")
        return tree.branch.repository.revision_tree(revid1)

    def get_empty_preview(self):
        repository = self.make_repository("repo")
        tree = repository.revision_tree(_mod_revision.NULL_REVISION)
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        return preview

    def test_transform_preview(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)

    def test_transform_preview_tree(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.get_preview_tree()

    def test_transform_new_file(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("file2", preview.root, [b"content B\n"], b"file2-id")
        preview_tree = preview.get_preview_tree()
        self.assertEqual(preview_tree.kind("file2"), "file")
        with preview_tree.get_file("file2") as f:
            self.assertEqual(f.read(), b"content B\n")

    def test_diff_preview_tree(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("file2", preview.root, [b"content B\n"], b"file2-id")
        preview_tree = preview.get_preview_tree()
        out = BytesIO()
        show_diff_trees(revision_tree, preview_tree, out)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], b"=== added file 'file2'")
        # 3 lines of diff administrivia
        self.assertEqual(lines[4], b"+content B")

    def test_unsupported_symlink_diff(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a", "content 1")])
        tree.add("a")
        os.symlink("a", "foo")
        tree.add("foo")
        revid1 = tree.commit("rev1")
        revision_tree = tree.branch.repository.revision_tree(revid1)
        os_symlink = getattr(os, "symlink", None)
        os.symlink = None
        try:
            preview = revision_tree.preview_transform()
            self.addCleanup(preview.finalize)
            preview.delete_versioned(preview.trans_id_tree_path("foo"))
            preview_tree = preview.get_preview_tree()
            out = BytesIO()
            log = BytesIO()
            trace.push_log_file(log)
            show_diff_trees(revision_tree, preview_tree, out)
            out.getvalue().splitlines()
        finally:
            os.symlink = os_symlink
        self.assertContainsRe(
            log.getvalue(),
            b'Ignoring "foo" as symlinks are not supported on this filesystem',
        )

    def test_transform_conflicts(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("a", preview.root, [b"content 2"])
        resolve_conflicts(preview)
        trans_id = preview.trans_id_tree_path("a")
        self.assertEqual("a.moved", preview.final_name(trans_id))

    def get_tree_and_preview_tree(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)
        a_trans_id = preview.trans_id_tree_path("a")
        preview.delete_contents(a_trans_id)
        preview.create_file([b"b content"], a_trans_id)
        preview_tree = preview.get_preview_tree()
        return revision_tree, preview_tree

    def test_iter_changes(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        self.assertThat(
            preview_tree.iter_changes(revision_tree),
            MatchesTreeChanges(
                revision_tree,
                preview_tree,
                [
                    (
                        ("a", "a"),
                        True,
                        (True, True),
                        ("a", "a"),
                        ("file", "file"),
                        (False, False),
                        False,
                    )
                ],
            ),
        )

    def test_include_unchanged_succeeds(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        changes = preview_tree.iter_changes(revision_tree, include_unchanged=True)

        root_entry = TreeChange(
            ("", ""),
            False,
            (True, True),
            ("", ""),
            ("directory", "directory"),
            (False, False),
            False,
        )
        a_entry = TreeChange(
            ("a", "a"),
            True,
            (True, True),
            ("a", "a"),
            ("file", "file"),
            (False, False),
            False,
        )

        self.assertThat(
            changes,
            MatchesTreeChanges(revision_tree, preview_tree, [root_entry, a_entry]),
        )

    def test_specific_files(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        changes = preview_tree.iter_changes(revision_tree, specific_files=[""])
        a_entry = (
            ("a", "a"),
            True,
            (True, True),
            ("a", "a"),
            ("file", "file"),
            (False, False),
            False,
        )

        self.assertThat(
            changes, MatchesTreeChanges(revision_tree, preview_tree, [a_entry])
        )

    def test_want_unversioned(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        changes = preview_tree.iter_changes(revision_tree, want_unversioned=True)
        a_entry = TreeChange(
            ("a", "a"),
            True,
            (True, True),
            ("a", "a"),
            ("file", "file"),
            (False, False),
            False,
        )

        self.assertThat(
            changes, MatchesTreeChanges(revision_tree, preview_tree, [a_entry])
        )

    def test_ignore_extra_trees_no_specific_files(self):
        # extra_trees is harmless without specific_files, so we'll silently
        # accept it, even though we won't use it.
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        preview_tree.iter_changes(revision_tree, extra_trees=[preview_tree])

    def test_ignore_require_versioned_no_specific_files(self):
        # require_versioned is meaningless without specific_files.
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        preview_tree.iter_changes(revision_tree, require_versioned=False)

    def test_ignore_pb(self):
        # pb could be supported, but TT.iter_changes doesn't support it.
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        preview_tree.iter_changes(revision_tree)

    def test_kind(self):
        revision_tree = self.create_tree()
        preview = revision_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("file", preview.root, [b"contents"], b"file-id")
        preview.new_directory("directory", preview.root, b"dir-id")
        preview_tree = preview.get_preview_tree()
        self.assertEqual("file", preview_tree.kind("file"))
        self.assertEqual("directory", preview_tree.kind("directory"))

    def test_get_file_mtime(self):
        preview = self.get_empty_preview()
        file_trans_id = preview.new_file(
            "file", preview.root, [b"contents"], b"file-id"
        )
        limbo_path = preview._limbo_name(file_trans_id)
        preview_tree = preview.get_preview_tree()
        self.assertEqual(
            os.stat(limbo_path).st_mtime, preview_tree.get_file_mtime("file")
        )

    def test_get_file_mtime_renamed(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file"])
        work_tree.add("file")
        preview = work_tree.preview_transform()
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_tree_path("file")
        preview.adjust_path("renamed", preview.root, file_trans_id)
        preview_tree = preview.get_preview_tree()
        preview_tree.get_file_mtime("renamed")
        work_tree.get_file_mtime("file")

    def test_get_file_size(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/old", b"old")])
        work_tree.add("old")
        preview = work_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("name", preview.root, [b"contents"], b"new-id", "executable")
        tree = preview.get_preview_tree()
        self.assertEqual(len("old"), tree.get_file_size("old"))
        self.assertEqual(len("contents"), tree.get_file_size("name"))

    def test_get_file(self):
        preview = self.get_empty_preview()
        preview.new_file("file", preview.root, [b"contents"], b"file-id")
        preview_tree = preview.get_preview_tree()
        with preview_tree.get_file("file") as tree_file:
            self.assertEqual(b"contents", tree_file.read())

    def test_get_symlink_target(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        preview = self.get_empty_preview()
        preview.new_symlink("symlink", preview.root, "target", b"symlink-id")
        preview_tree = preview.get_preview_tree()
        self.assertEqual("target", preview_tree.get_symlink_target("symlink"))

    def test_all_file_ids(self):
        if not self.workingtree_format.supports_setting_file_ids:
            raise tests.TestNotApplicable("format does not support setting file ids")
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b", "tree/c"])
        tree.add(["a", "b", "c"], ids=[b"a-id", b"b-id", b"c-id"])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.unversion_file(preview.trans_id_file_id(b"b-id"))
        c_trans_id = preview.trans_id_file_id(b"c-id")
        preview.unversion_file(c_trans_id)
        preview.version_file(c_trans_id, file_id=b"c-id")
        preview_tree = preview.get_preview_tree()
        self.assertEqual(
            {b"a-id", b"c-id", tree.path2id("")}, preview_tree.all_file_ids()
        )

    def test_path2id_deleted_unchanged(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/unchanged", "tree/deleted"])
        tree.add(["unchanged", "deleted"])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.unversion_file(preview.trans_id_tree_path("deleted"))
        preview_tree = preview.get_preview_tree()
        self.assertEqual(
            "unchanged", find_previous_path(preview_tree, tree, "unchanged")
        )
        self.assertFalse(preview_tree.is_versioned("deleted"))

    def test_path2id_created(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/unchanged"])
        tree.add(["unchanged"])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file(
            "new", preview.trans_id_tree_path("unchanged"), [b"contents"], b"new-id"
        )
        preview_tree = preview.get_preview_tree()
        self.assertTrue(preview_tree.is_versioned("unchanged/new"))
        if self.workingtree_format.supports_setting_file_ids:
            self.assertEqual(b"new-id", preview_tree.path2id("unchanged/new"))

    def test_path2id_moved(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/old_parent/", "tree/old_parent/child"])
        tree.add(["old_parent", "old_parent/child"])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        new_parent = preview.new_directory("new_parent", preview.root, b"new_parent-id")
        preview.adjust_path(
            "child", new_parent, preview.trans_id_tree_path("old_parent/child")
        )
        preview_tree = preview.get_preview_tree()
        self.assertFalse(preview_tree.is_versioned("old_parent/child"))
        self.assertEqual(
            "new_parent/child",
            find_previous_path(tree, preview_tree, "old_parent/child"),
        )
        if self.workingtree_format.supports_setting_file_ids:
            self.assertEqual(
                tree.path2id("old_parent/child"),
                preview_tree.path2id("new_parent/child"),
            )

    def test_path2id_renamed_parent(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/old_name/", "tree/old_name/child"])
        tree.add(["old_name", "old_name/child"])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.adjust_path(
            "new_name", preview.root, preview.trans_id_tree_path("old_name")
        )
        preview_tree = preview.get_preview_tree()
        self.assertFalse(preview_tree.is_versioned("old_name/child"))
        self.assertEqual(
            "new_name/child", find_previous_path(tree, preview_tree, "old_name/child")
        )
        if tree.supports_setting_file_ids():
            self.assertEqual(
                tree.path2id("old_name/child"), preview_tree.path2id("new_name/child")
            )

    def assertMatchingIterEntries(self, tt, specific_files=None):
        preview_tree = tt.get_preview_tree()
        preview_result = list(
            preview_tree.iter_entries_by_dir(specific_files=specific_files)
        )
        tree = tt._tree
        tt.apply()
        actual_result = list(tree.iter_entries_by_dir(specific_files=specific_files))
        self.assertEqual(actual_result, preview_result)

    def test_iter_entries_by_dir_new(self):
        tree = self.make_branch_and_tree("tree")
        tt = tree.transform()
        tt.new_file("new", tt.root, [b"contents"], b"new-id")
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_deleted(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/deleted"])
        tree.add("deleted")
        tt = tree.transform()
        tt.delete_contents(tt.trans_id_tree_path("deleted"))
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_unversioned(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/removed"])
        tree.add("removed")
        tt = tree.transform()
        tt.unversion_file(tt.trans_id_tree_path("removed"))
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_moved(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/moved", "tree/new_parent/"])
        tree.add(["moved", "new_parent"])
        tt = tree.transform()
        tt.adjust_path(
            "moved", tt.trans_id_tree_path("new_parent"), tt.trans_id_tree_path("moved")
        )
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_specific_files(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/parent/", "tree/parent/child"])
        tree.add(["parent", "parent/child"])
        tt = tree.transform()
        self.assertMatchingIterEntries(tt, ["", "parent/child"])

    def test_symlink_content_summary(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        preview = self.get_empty_preview()
        preview.new_symlink("path", preview.root, "target", b"path-id")
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(("symlink", None, None, "target"), summary)

    def test_missing_content_summary(self):
        preview = self.get_empty_preview()
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(("missing", None, None, None), summary)

    def test_deleted_content_summary(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/path/"])
        tree.add("path")
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.delete_contents(preview.trans_id_tree_path("path"))
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(("missing", None, None, None), summary)

    def test_file_content_summary_executable(self):
        preview = self.get_empty_preview()
        path_id = preview.new_file("path", preview.root, [b"contents"], b"path-id")
        preview.set_executability(True, path_id)
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(4, len(summary))
        self.assertEqual("file", summary[0])
        # size must be known
        self.assertEqual(len("contents"), summary[1])
        # executable
        self.assertEqual(True, summary[2])
        # will not have hash (not cheap to determine)
        self.assertIs(None, summary[3])

    def test_change_executability(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/path"])
        tree.add("path")
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        path_id = preview.trans_id_tree_path("path")
        preview.set_executability(True, path_id)
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(True, summary[2])

    def test_file_content_summary_non_exec(self):
        preview = self.get_empty_preview()
        preview.new_file("path", preview.root, [b"contents"], b"path-id")
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(4, len(summary))
        self.assertEqual("file", summary[0])
        # size must be known
        self.assertEqual(len("contents"), summary[1])
        # not executable
        self.assertEqual(False, summary[2])
        # will not have hash (not cheap to determine)
        self.assertIs(None, summary[3])

    def test_dir_content_summary(self):
        preview = self.get_empty_preview()
        preview.new_directory("path", preview.root, b"path-id")
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(("directory", None, None, None), summary)

    def test_tree_content_summary(self):
        preview = self.get_empty_preview()
        path = preview.new_directory("path", preview.root, b"path-id")
        preview.set_tree_reference(b"rev-1", path)
        summary = preview.get_preview_tree().path_content_summary("path")
        self.assertEqual(4, len(summary))
        self.assertEqual("tree-reference", summary[0])

    def test_annotate(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"a\n")])
        tree.add("file")
        revid1 = tree.commit("a")
        self.build_tree_contents([("tree/file", b"a\nb\n")])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_tree_path("file")
        preview.delete_contents(file_trans_id)
        preview.create_file([b"a\nb\nc\n"], file_trans_id)
        preview_tree = preview.get_preview_tree()
        expected = [
            (revid1, b"a\n"),
            (b"me:", b"b\n"),
            (b"me:", b"c\n"),
        ]
        annotation = preview_tree.annotate_iter("file", default_revision=b"me:")
        self.assertEqual(expected, annotation)

    def test_annotate_missing(self):
        preview = self.get_empty_preview()
        preview.new_file("file", preview.root, [b"a\nb\nc\n"], b"file-id")
        preview_tree = preview.get_preview_tree()
        expected = [
            (b"me:", b"a\n"),
            (b"me:", b"b\n"),
            (b"me:", b"c\n"),
        ]
        annotation = preview_tree.annotate_iter("file", default_revision=b"me:")
        self.assertEqual(expected, annotation)

    def test_annotate_rename(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"a\n")])
        tree.add("file")
        revid1 = tree.commit("a")
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_tree_path("file")
        preview.adjust_path("newname", preview.root, file_trans_id)
        preview_tree = preview.get_preview_tree()
        expected = [
            (revid1, b"a\n"),
        ]
        annotation = preview_tree.annotate_iter("newname", default_revision=b"me:")
        self.assertEqual(expected, annotation)
        annotation = preview_tree.annotate_iter("file", default_revision=b"me:")
        self.assertIs(None, annotation)

    def test_annotate_deleted(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"a\n")])
        tree.add("file")
        tree.commit("a")
        self.build_tree_contents([("tree/file", b"a\nb\n")])
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_tree_path("file")
        preview.delete_contents(file_trans_id)
        preview_tree = preview.get_preview_tree()
        annotation = preview_tree.annotate_iter("file", default_revision=b"me:")
        self.assertIs(None, annotation)

    def test_stored_kind(self):
        preview = self.get_empty_preview()
        preview.new_file("file", preview.root, [b"a\nb\nc\n"], b"file-id")
        preview_tree = preview.get_preview_tree()
        self.assertEqual("file", preview_tree.stored_kind("file"))

    def test_is_executable(self):
        preview = self.get_empty_preview()
        trans_id = preview.new_file("file", preview.root, [b"a\nb\nc\n"], b"file-id")
        preview.set_executability(True, trans_id)
        preview_tree = preview.get_preview_tree()
        self.assertEqual(True, preview_tree.is_executable("file"))

    def test_get_set_parent_ids(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        self.assertEqual([], preview_tree.get_parent_ids())
        preview_tree.set_parent_ids([revision_tree.get_revision_id()])
        self.assertEqual(
            [revision_tree.get_revision_id()], preview_tree.get_parent_ids()
        )

    def test_plan_file_merge(self):
        work_a = self.make_branch_and_tree("wta")
        self.build_tree_contents([("wta/file", b"a\nb\nc\nd\n")])
        work_a.add("file")
        base_id = work_a.commit("base version")
        tree_b = work_a.controldir.sprout("wtb").open_workingtree()
        preview = work_a.preview_transform()
        self.addCleanup(preview.finalize)
        trans_id = preview.trans_id_tree_path("file")
        preview.delete_contents(trans_id)
        preview.create_file([b"b\nc\nd\ne\n"], trans_id)
        self.build_tree_contents([("wtb/file", b"a\nc\nd\nf\n")])
        tree_a = preview.get_preview_tree()
        if not getattr(tree_a, "plan_file_merge", None):
            self.skipTest("tree does not support file merge planning")
        tree_a.set_parent_ids([base_id])
        self.addCleanup(tree_b.lock_read().unlock)
        self.assertEqual(
            [
                ("killed-a", b"a\n"),
                ("killed-b", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("new-a", b"e\n"),
                ("new-b", b"f\n"),
            ],
            list(tree_a.plan_file_merge("file", tree_b)),
        )

    def test_plan_file_merge_revision_tree(self):
        work_a = self.make_branch_and_tree("wta")
        self.build_tree_contents([("wta/file", b"a\nb\nc\nd\n")])
        work_a.add("file")
        base_id = work_a.commit("base version")
        tree_b = work_a.controldir.sprout("wtb").open_workingtree()
        preview = work_a.basis_tree().preview_transform()
        self.addCleanup(preview.finalize)
        trans_id = preview.trans_id_tree_path("file")
        preview.delete_contents(trans_id)
        preview.create_file([b"b\nc\nd\ne\n"], trans_id)
        self.build_tree_contents([("wtb/file", b"a\nc\nd\nf\n")])
        tree_a = preview.get_preview_tree()
        if not getattr(tree_a, "plan_file_merge", None):
            self.skipTest("tree does not support file merge planning")
        tree_a.set_parent_ids([base_id])
        self.addCleanup(tree_b.lock_read().unlock)
        self.assertEqual(
            [
                ("killed-a", b"a\n"),
                ("killed-b", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("new-a", b"e\n"),
                ("new-b", b"f\n"),
            ],
            list(tree_a.plan_file_merge("file", tree_b)),
        )

    def test_walkdirs(self):
        preview = self.get_empty_preview()
        preview.new_directory("", ROOT_PARENT, b"tree-root")
        # FIXME: new_directory should mark root.
        preview.fixup_new_roots()
        preview_tree = preview.get_preview_tree()
        preview.new_file("a", preview.root, [b"contents"], b"a-id")
        expected = [("", [("a", "a", "file", None, "file")])]
        self.assertEqual(expected, list(preview_tree.walkdirs()))

    def test_extras(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree(
            ["tree/removed-file", "tree/existing-file", "tree/not-removed-file"]
        )
        work_tree.add(["removed-file", "not-removed-file"])
        preview = work_tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("new-file", preview.root, [b"contents"])
        preview.new_file(
            "new-versioned-file", preview.root, [b"contents"], b"new-versioned-id"
        )
        tree = preview.get_preview_tree()
        self.assertEqual({"existing-file"}, set(work_tree.extras()))
        preview.unversion_file(preview.trans_id_tree_path("removed-file"))
        self.assertEqual(
            {"new-file", "removed-file", "existing-file"}, set(tree.extras())
        )

    def test_merge_into_preview(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"b\n")])
        work_tree.add("file")
        work_tree.commit("first commit")
        child_tree = work_tree.controldir.sprout("child").open_workingtree()
        self.build_tree_contents([("child/file", b"b\nc\n")])
        child_tree.commit("child commit")
        child_tree.lock_write()
        self.addCleanup(child_tree.unlock)
        work_tree.lock_write()
        self.addCleanup(work_tree.unlock)
        preview = work_tree.preview_transform()
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_tree_path("file")
        preview.delete_contents(file_trans_id)
        preview.create_file([b"a\nb\n"], file_trans_id)
        preview_tree = preview.get_preview_tree()
        merger = Merger.from_revision_ids(
            preview_tree,
            child_tree.branch.last_revision(),
            other_branch=child_tree.branch,
            tree_branch=work_tree.branch,
        )
        merger.merge_type = Merge3Merger
        tt = merger.make_merger().make_preview_transform()
        self.addCleanup(tt.finalize)
        final_tree = tt.get_preview_tree()
        self.assertEqual(b"a\nb\nc\n", final_tree.get_file_text("file"))

    def test_merge_preview_into_workingtree(self):
        tree = self.make_branch_and_tree("tree")
        if tree.supports_setting_file_ids():
            tree.set_root_id(b"TREE_ROOT")
        tt = tree.preview_transform()
        self.addCleanup(tt.finalize)
        tt.new_file("name", tt.root, [b"content"], b"file-id")
        tree2 = self.make_branch_and_tree("tree2")
        if tree.supports_setting_file_ids():
            tree2.set_root_id(b"TREE_ROOT")
        merger = Merger.from_uncommitted(
            tree2, tt.get_preview_tree(), tree.basis_tree()
        )
        merger.merge_type = Merge3Merger
        merger.do_merge()

    def test_merge_preview_into_workingtree_handles_conflicts(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/foo", b"bar")])
        tree.add("foo")
        tree.commit("foo")
        tt = tree.preview_transform()
        self.addCleanup(tt.finalize)
        trans_id = tt.trans_id_tree_path("foo")
        tt.delete_contents(trans_id)
        tt.create_file([b"baz"], trans_id)
        tree2 = tree.controldir.sprout("tree2").open_workingtree()
        self.build_tree_contents([("tree2/foo", b"qux")])
        merger = Merger.from_uncommitted(
            tree2, tt.get_preview_tree(), tree.basis_tree()
        )
        merger.merge_type = Merge3Merger
        merger.do_merge()

    def test_has_filename(self):
        wt = self.make_branch_and_tree("tree")
        self.build_tree(["tree/unmodified", "tree/removed", "tree/modified"])
        tt = wt.preview_transform()
        removed_id = tt.trans_id_tree_path("removed")
        tt.delete_contents(removed_id)
        tt.new_file("new", tt.root, [b"contents"])
        modified_id = tt.trans_id_tree_path("modified")
        tt.delete_contents(modified_id)
        tt.create_file([b"modified-contents"], modified_id)
        self.addCleanup(tt.finalize)
        tree = tt.get_preview_tree()
        self.assertTrue(tree.has_filename("unmodified"))
        self.assertFalse(tree.has_filename("not-present"))
        self.assertFalse(tree.has_filename("removed"))
        self.assertTrue(tree.has_filename("new"))
        self.assertTrue(tree.has_filename("modified"))

    def test_is_executable2(self):
        tree = self.make_branch_and_tree("tree")
        preview = tree.preview_transform()
        self.addCleanup(preview.finalize)
        preview.new_file("foo", preview.root, [b"bar"], b"baz-id")
        preview_tree = preview.get_preview_tree()
        self.assertEqual(False, preview_tree.is_executable("tree/foo"))

    def test_commit_preview_tree(self):
        tree = self.make_branch_and_tree("tree")
        rev_id = tree.commit("rev1")
        tree.branch.lock_write()
        self.addCleanup(tree.branch.unlock)
        tt = tree.preview_transform()
        tt.new_file("file", tt.root, [b"contents"], b"file_id")
        self.addCleanup(tt.finalize)
        preview = tt.get_preview_tree()
        preview.set_parent_ids([rev_id])
        builder = tree.branch.get_commit_builder([rev_id])
        list(builder.record_iter_changes(preview, rev_id, tt.iter_changes()))
        builder.finish_inventory()
        rev2_id = builder.commit("rev2")
        rev2_tree = tree.branch.repository.revision_tree(rev2_id)
        self.assertEqual(b"contents", rev2_tree.get_file_text("file"))

    def test_ascii_limbo_paths(self):
        self.requireFeature(UnicodeFilenameFeature)
        branch = self.make_branch("any")
        tree = branch.repository.revision_tree(_mod_revision.NULL_REVISION)
        tt = tree.preview_transform()
        self.addCleanup(tt.finalize)
        foo_id = tt.new_directory("", ROOT_PARENT)
        bar_id = tt.new_file("\u1234bar", foo_id, [b"contents"])
        limbo_path = tt._limbo_name(bar_id)
        self.assertEqual(limbo_path, limbo_path)

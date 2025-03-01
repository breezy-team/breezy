# Copyright (C) 2006-2009, 2011, 2012, 2016 Canonical Ltd
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

from breezy import conflicts, errors, osutils, revisiontree, tests
from breezy import transport as _mod_transport
from breezy.bzr import workingtree_4
from breezy.tests.per_tree import TestCaseWithTree
from breezy.tree import MissingNestedTree


class TestAnnotate(TestCaseWithTree):
    def test_annotate(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree_revision = getattr(tree, "get_revision_id", lambda: b"current:")()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        for revision, line in tree.annotate_iter("a"):
            self.assertEqual(b"contents of a\n", line)
            self.assertEqual(tree_revision, revision)
        tree_revision = getattr(tree, "get_revision_id", lambda: b"random:")()
        for revision, line in tree.annotate_iter("a", default_revision=b"random:"):
            self.assertEqual(b"contents of a\n", line)
            self.assertEqual(tree_revision, revision)


class TestPlanFileMerge(TestCaseWithTree):
    def test_plan_file_merge(self):
        work_a = self.make_branch_and_tree("wta")
        self.build_tree_contents([("wta/file", b"a\nb\nc\nd\n")])
        work_a.add("file")
        work_a.commit("base version")
        work_b = work_a.controldir.sprout("wtb").open_workingtree()
        self.build_tree_contents([("wta/file", b"b\nc\nd\ne\n")])
        tree_a = self.workingtree_to_test_tree(work_a)
        if getattr(tree_a, "plan_file_merge", None) is None:
            raise tests.TestNotApplicable("Tree does not support plan_file_merge")
        tree_a.lock_read()
        self.addCleanup(tree_a.unlock)
        self.build_tree_contents([("wtb/file", b"a\nc\nd\nf\n")])
        tree_b = self.workingtree_to_test_tree(work_b)
        tree_b.lock_read()
        self.addCleanup(tree_b.unlock)
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


class TestReference(TestCaseWithTree):
    def skip_if_no_reference(self, tree):
        if not tree.supports_tree_reference():
            raise tests.TestNotApplicable("Tree references not supported")

    def create_nested(self):
        work_tree = self.make_branch_and_tree("wt")
        with work_tree.lock_write():
            self.skip_if_no_reference(work_tree)
            subtree = self.make_branch_and_tree("wt/subtree")
            subtree.commit("foo")
            work_tree.add_reference(subtree)
        tree = self._convert_tree(work_tree)
        self.skip_if_no_reference(tree)
        return tree, subtree

    def test_get_reference_revision(self):
        tree, subtree = self.create_nested()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            subtree.last_revision(), tree.get_reference_revision("subtree")
        )

    def test_iter_references(self):
        tree, subtree = self.create_nested()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(["subtree"], list(tree.iter_references()))

    def test_get_nested_tree(self):
        tree, subtree = self.create_nested()
        try:
            changes = subtree.changes_from(tree.get_nested_tree("subtree"))
            self.assertFalse(changes.has_changed())
        except MissingNestedTree:
            # Also okay.
            pass

    def test_get_root_id(self):
        # trees should return some kind of root id; it can be none
        tree = self.make_branch_and_tree("tree")
        if not tree.supports_file_ids:
            raise tests.TestNotApplicable("file ids not supported")
        root_id = tree.path2id("")
        if root_id is not None:
            self.assertIsInstance(root_id, bytes)

    def test_is_versioned(self):
        tree = self.make_branch_and_tree("tree")
        self.assertTrue(tree.is_versioned(""))
        self.assertFalse(tree.is_versioned("blah"))
        self.build_tree(["tree/dir/", "tree/dir/file"])
        self.assertFalse(tree.is_versioned("dir"))
        self.assertFalse(tree.is_versioned("dir/"))
        tree.add(["dir", "dir/file"])
        self.assertTrue(tree.is_versioned("dir"))
        self.assertTrue(tree.is_versioned("dir/"))


class TestFileIds(TestCaseWithTree):
    def setUp(self):
        super().setUp()
        if not self.workingtree_format.supports_setting_file_ids:
            raise tests.TestNotApplicable(
                "working tree does not support setting file ids"
            )

    def test_id2path(self):
        # translate from file-id back to path
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        a_id = tree.path2id("a")
        with tree.lock_read():
            self.assertEqual("a", tree.id2path(a_id))
            # other ids give an error- don't return None for this case
            self.assertRaises(errors.NoSuchId, tree.id2path, b"a")

    def test_all_file_ids(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            tree.all_file_ids(),
            {
                tree.path2id("a"),
                tree.path2id(""),
                tree.path2id("b"),
                tree.path2id("b/c"),
            },
        )


class TestStoredKind(TestCaseWithTree):
    def test_stored_kind(self):
        tree = self.make_branch_and_tree("tree")
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual("file", tree.stored_kind("a"))
        self.assertEqual("directory", tree.stored_kind("b"))


class TestFileContent(TestCaseWithTree):
    def test_get_file(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # Test lookup without path works
        file_without_path = tree.get_file("a")
        try:
            lines = file_without_path.readlines()
            self.assertEqual([b"foobar\n"], lines)
        finally:
            file_without_path.close()

    def test_get_file_context_manager(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        with tree.get_file("a") as f:
            self.assertEqual(b"foobar\n", f.read())

    def test_get_file_text(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # test read by path
        self.assertEqual(b"foobar\n", tree.get_file_text("a"))

    def test_get_file_lines(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # test read by path
        self.assertEqual([b"foobar\n"], tree.get_file_lines("a"))

    def test_get_file_lines_multi_line_breaks(self):
        work_tree = self.make_branch_and_tree("wt")
        self.build_tree_contents([("wt/foobar", b"a\rb\nc\r\nd")])
        work_tree.add("foobar")
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([b"a\rb\n", b"c\r\n", b"d"], tree.get_file_lines("foobar"))


class TestExtractFilesBytes(TestCaseWithTree):
    def test_iter_files_bytes(self):
        work_tree = self.make_branch_and_tree("wt")
        self.build_tree_contents(
            [("wt/foo", b"foo"), ("wt/bar", b"bar"), ("wt/baz", b"baz")]
        )
        work_tree.add(["foo", "bar", "baz"])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        extracted = {
            i: b"".join(b)
            for i, b in tree.iter_files_bytes(
                [("foo", "id1"), ("bar", "id2"), ("baz", "id3")]
            )
        }
        self.assertEqual(b"foo", extracted["id1"])
        self.assertEqual(b"bar", extracted["id2"])
        self.assertEqual(b"baz", extracted["id3"])
        self.assertRaises(
            _mod_transport.NoSuchFile,
            lambda: list(tree.iter_files_bytes([("qux", "file1-notpresent")])),
        )


class TestConflicts(TestCaseWithTree):
    def test_conflicts(self):
        """Tree.conflicts() should return a ConflictList instance."""
        work_tree = self.make_branch_and_tree("wt")
        tree = self._convert_tree(work_tree)
        self.assertIsInstance(tree.conflicts(), conflicts.ConflictList)


class TestIterEntriesByDir(TestCaseWithTree):
    def test_iteration_order(self):
        work_tree = self.make_branch_and_tree(".")
        self.build_tree(["a/", "a/b/", "a/b/c", "a/d/", "a/d/e", "f/", "f/g"])
        work_tree.add(["a", "a/b", "a/b/c", "a/d", "a/d/e", "f", "f/g"])
        tree = self._convert_tree(work_tree)
        output_order = [p for p, e in tree.iter_entries_by_dir()]
        self.assertEqual(
            ["", "a", "f", "a/b", "a/d", "a/b/c", "a/d/e", "f/g"], output_order
        )


class TestIterChildEntries(TestCaseWithTree):
    def test_iteration_order(self):
        work_tree = self.make_branch_and_tree(".")
        self.build_tree(["a/", "a/b/", "a/b/c", "a/d/", "a/d/e", "f/", "f/g"])
        work_tree.add(["a", "a/b", "a/b/c", "a/d", "a/d/e", "f", "f/g"])
        tree = self._convert_tree(work_tree)
        output = [e.name for e in tree.iter_child_entries("")]
        self.assertEqual({"a", "f"}, set(output))
        output = [e.name for e in tree.iter_child_entries("a")]
        self.assertEqual({"b", "d"}, set(output))

    def test_does_not_exist(self):
        work_tree = self.make_branch_and_tree(".")
        self.build_tree(["a/"])
        work_tree.add(["a"])
        tree = self._convert_tree(work_tree)
        self.assertRaises(
            _mod_transport.NoSuchFile, lambda: list(tree.iter_child_entries("unknown"))
        )


class TestExtras(TestCaseWithTree):
    def test_extras(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file", "tree/versioned-file"])
        work_tree.add(["file", "versioned-file"])
        work_tree.commit("add files")
        work_tree.remove("file")
        tree = self._convert_tree(work_tree)
        if isinstance(
            tree, (revisiontree.RevisionTree, workingtree_4.DirStateRevisionTree)
        ):
            expected = []
        else:
            expected = ["file"]
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(expected, list(tree.extras()))


class TestGetFileSha1(TestCaseWithTree):
    def test_get_file_sha1(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"file content")])
        work_tree.add("file")
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        expected = osutils.sha_string(b"file content")
        self.assertEqual(expected, tree.get_file_sha1("file"))


class TestGetFileVerifier(TestCaseWithTree):
    def test_get_file_verifier(self):
        work_tree = self.make_branch_and_tree("tree")
        self.build_tree_contents(
            [("tree/file1", b"file content"), ("tree/file2", b"file content")]
        )
        work_tree.add(["file1", "file2"])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        (kind, data) = tree.get_file_verifier("file1")
        self.assertEqual(
            tree.get_file_verifier("file1"), tree.get_file_verifier("file2")
        )
        if kind == "SHA1":
            expected = osutils.sha_string(b"file content")
            self.assertEqual(expected, data)


class TestHasVersionedDirectories(TestCaseWithTree):
    def test_has_versioned_directories(self):
        work_tree = self.make_branch_and_tree("tree")
        tree = self._convert_tree(work_tree)
        self.assertIn(tree.has_versioned_directories(), (True, False))


class TestSupportsRenameTracking(TestCaseWithTree):
    def test_supports_rename_tracking(self):
        work_tree = self.make_branch_and_tree("tree")
        tree = self._convert_tree(work_tree)
        self.assertSubset([tree.supports_rename_tracking()], (True, False))


class TestSupportsVersionableKind(TestCaseWithTree):
    def test_file(self):
        work_tree = self.make_branch_and_tree("tree")
        tree = self._convert_tree(work_tree)
        self.assertTrue(tree.versionable_kind("file"))

    def test_unknown(self):
        work_tree = self.make_branch_and_tree("tree")
        tree = self._convert_tree(work_tree)
        self.assertFalse(tree.versionable_kind("unknown"))


class TestSpecialFilename(TestCaseWithTree):
    def test_is_special_path(self):
        work_tree = self.make_branch_and_tree("tree")
        tree = self._convert_tree(work_tree)
        self.assertFalse(tree.is_special_path("foo"))

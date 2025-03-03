# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for the test trees used by the per_tree tests."""

import shutil

from breezy import errors
from breezy.tests import TestNotApplicable, TestSkipped, features, per_tree
from breezy.tree import MissingNestedTree


class TestTreeShapes(per_tree.TestCaseWithTree):
    def test_empty_tree_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_no_content(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        self.assertEqual([""], list(tree.all_versioned_paths()))
        if tree.supports_file_ids:
            self.assertEqual(
                [("", tree.path2id(""))],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual([""], [path for path, node in tree.iter_entries_by_dir()])

    def test_abc_tree_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_abc_content(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual({"", "a", "b", "b/c"}, set(tree.all_versioned_paths()))
        self.assertTrue(tree.is_versioned("a"))
        self.assertTrue(tree.is_versioned("b"))
        self.assertTrue(tree.is_versioned("b/c"))
        if tree.supports_file_ids:
            self.assertEqual(
                [(p, tree.path2id(p)) for p in ["", "a", "b", "b/c"]],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual(
                ["", "a", "b", "b/c"],
                [path for path, node in tree.iter_entries_by_dir()],
            )

        self.assertEqualDiff(b"contents of a\n", tree.get_file_text("a"))
        self.assertFalse(tree.is_executable("b/c"))

    def test_abc_tree_content_2_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_abc_content_2(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual({"", "a", "b", "b/c"}, set(tree.all_versioned_paths()))
        if tree.supports_file_ids:
            self.assertEqual(
                [(p, tree.path2id(p)) for p in ["", "a", "b", "b/c"]],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
            self.assertEqual(
                [(p, tree.path2id(p)) for p in ["b"]],
                [
                    (path, node.file_id)
                    for path, node in tree.iter_entries_by_dir(specific_files=["b"])
                ],
            )
        else:
            self.assertEqual(
                ["", "a", "b", "b/c"],
                [path for path, node in tree.iter_entries_by_dir()],
            )
            self.assertEqual(
                ["b"],
                [path for path, node in tree.iter_entries_by_dir(specific_files=["b"])],
            )
        self.assertEqualDiff(b"foobar\n", tree.get_file_text("a"))
        self.assertFalse(tree.is_executable("b//c"))
        self.assertFalse(tree.is_executable("b/c"))

    def test_abc_tree_content_3_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_abc_content_3(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual({"", "a", "b", "b/c"}, set(tree.all_versioned_paths()))
        if tree.supports_file_ids:
            self.assertEqual(
                [(p, tree.path2id(p)) for p in ["", "a", "b", "b/c"]],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual(
                ["", "a", "b", "b/c"],
                [path for path, node in tree.iter_entries_by_dir()],
            )
        self.assertEqualDiff(b"contents of a\n", tree.get_file_text("a"))
        self.assertTrue(tree.is_executable("b/c"))

    def test_abc_tree_content_4_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_abc_content_4(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual({"", "b", "d", "b/c"}, set(tree.all_versioned_paths()))
        if tree.supports_file_ids:
            self.assertEqual(
                [(p, tree.path2id(p)) for p in ["", "b", "d", "b/c"]],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual(
                ["", "b", "d", "b/c"],
                [path for path, node in tree.iter_entries_by_dir()],
            )
        self.assertEqualDiff(b"contents of a\n", tree.get_file_text("d"))
        self.assertFalse(tree.is_executable("b/c"))

    def test_abc_tree_content_5_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_abc_content_5(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual({"", "d", "b", "b/c"}, set(tree.all_versioned_paths()))
        if tree.supports_file_ids:
            self.assertEqual(
                [(p, tree.path2id(p)) for p in ["", "b", "d", "b/c"]],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual(
                ["", "b", "d", "b/c"],
                [path for path, node in tree.iter_entries_by_dir()],
            )
        self.assertEqualDiff(b"bar\n", tree.get_file_text("d"))
        self.assertFalse(tree.is_executable("b/c"))

    def test_abc_tree_content_6_no_parents(self):
        tree = self.make_branch_and_tree(".")
        tree = self.get_tree_no_parents_abc_content_6(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        expected_paths = (
            ["", "a"] + (["b"] if tree.has_versioned_directories() else []) + ["e"]
        )
        self.assertEqual(set(expected_paths), set(tree.all_versioned_paths()))
        if tree.supports_file_ids:
            self.assertEqual(
                [(p, tree.path2id(p)) for p in expected_paths],
                [(path, node.file_id) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual(
                expected_paths, [path for path, node in tree.iter_entries_by_dir()]
            )
        self.assertEqualDiff(b"contents of a\n", tree.get_file_text("a"))
        self.assertTrue(tree.is_executable("e"))

    def test_tree_with_subdirs_and_all_content_types(self):
        # currently this test tree requires unicode. It might be good
        # to have it simply stop having the single unicode file in it
        # when dealing with a non-unicode filesystem.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.get_tree_with_subdirs_and_all_content_types()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        try:
            all_file_ids = set(tree.all_file_ids())
            tree.path2id("")
        except AttributeError:
            # doesn't support file ids
            all_file_ids = None
        if tree.has_versioned_directories():
            if all_file_ids is not None:
                self.assertEqual(
                    {
                        tree.path2id(p)
                        for p in [
                            "",
                            "0file",
                            "1top-dir",
                            "1top-dir/1dir-in-1topdir",
                            "1top-dir/0file-in-1topdir",
                            "symlink",
                            "2utf\u1234file",
                        ]
                    },
                    set(tree.all_file_ids()),
                )
            # note that the order of the paths and fileids is deliberately
            # mismatched to ensure that the result order is path based.
            self.assertEqual(
                [
                    ("", "directory"),
                    ("0file", "file"),
                    ("1top-dir", "directory"),
                    ("2utf\u1234file", "file"),
                    ("symlink", "symlink"),
                    ("1top-dir/0file-in-1topdir", "file"),
                    ("1top-dir/1dir-in-1topdir", "directory"),
                ],
                [(path, node.kind) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            if all_file_ids is not None:
                self.assertEqual(
                    {
                        tree.path2id(p)
                        for p in [
                            "",
                            "0file",
                            "1top-dir",
                            "1top-dir/0file-in-1topdir",
                            "symlink",
                            "2utf\u1234file",
                        ]
                    },
                    set(tree.all_file_ids()),
                )
            # note that the order of the paths and fileids is deliberately
            # mismatched to ensure that the result order is path based.
            self.assertEqual(
                [
                    ("", "directory"),
                    ("0file", "file"),
                    ("1top-dir", "directory"),
                    ("2utf\u1234file", "file"),
                    ("symlink", "symlink"),
                    ("1top-dir/0file-in-1topdir", "file"),
                ],
                [(path, node.kind) for path, node in tree.iter_entries_by_dir()],
            )

    def test_tree_with_subdirs_and_all_content_types_wo_symlinks(self):
        # currently this test tree requires unicode. It might be good
        # to have it simply stop having the single unicode file in it
        # when dealing with a non-unicode filesystem.
        tree = self.get_tree_with_subdirs_and_all_supported_content_types(False)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        if tree.has_versioned_directories():
            self.assertEqual(
                {
                    "",
                    "0file",
                    "1top-dir",
                    "1top-dir/0file-in-1topdir",
                    "1top-dir/1dir-in-1topdir",
                    "2utf\u1234file",
                },
                set(tree.all_versioned_paths()),
            )
            # note that the order of the paths and fileids is deliberately
            # mismatched to ensure that the result order is path based.
            self.assertEqual(
                [
                    ("", "directory"),
                    ("0file", "file"),
                    ("1top-dir", "directory"),
                    ("2utf\u1234file", "file"),
                    ("1top-dir/0file-in-1topdir", "file"),
                    ("1top-dir/1dir-in-1topdir", "directory"),
                ],
                [(path, node.kind) for path, node in tree.iter_entries_by_dir()],
            )
        else:
            self.assertEqual(
                {
                    "",
                    "0file",
                    "1top-dir",
                    "1top-dir/0file-in-1topdir",
                    "2utf\u1234file",
                },
                set(tree.all_versioned_paths()),
            )
            # note that the order of the paths and fileids is deliberately
            # mismatched to ensure that the result order is path based.
            self.assertEqual(
                [
                    ("", "directory"),
                    ("0file", "file"),
                    ("1top-dir", "directory"),
                    ("2utf\u1234file", "file"),
                    ("1top-dir/0file-in-1topdir", "file"),
                ],
                [(path, node.kind) for path, node in tree.iter_entries_by_dir()],
            )

    def _create_tree_with_utf8(self, tree):
        self.requireFeature(features.UnicodeFilenameFeature)

        # We avoid combining characters in file names here, normalization
        # checks (as performed by some file systems (OSX) are outside the scope
        # of these tests).  We use the euro sign \N{Euro Sign} or \u20ac in
        # unicode strings or '\xe2\x82\ac' (its utf-8 encoding) in raw strings.
        paths = [
            "",
            "fo\N{EURO SIGN}o",
            "ba\N{EURO SIGN}r/",
            "ba\N{EURO SIGN}r/ba\N{EURO SIGN}z",
        ]
        # bzr itself does not create unicode file ids, but we want them for
        # testing.
        file_ids = [
            b"TREE_ROOT",
            b"fo\xe2\x82\xaco-id",
            b"ba\xe2\x82\xacr-id",
            b"ba\xe2\x82\xacz-id",
        ]
        self.build_tree(paths[1:])
        if not tree.is_versioned(""):
            # Some trees do not have a root yet.
            tree.add(paths, ids=file_ids)
        else:
            # Some trees will already have a root
            if tree.supports_setting_file_ids():
                tree.set_root_id(file_ids[0])
                tree.add(paths[1:], ids=file_ids[1:])
            else:
                tree.add(paths[1:])
        if tree.branch.repository._format.supports_setting_revision_ids:
            try:
                tree.commit("in\xedtial", rev_id="r\xe9v-1".encode())
            except errors.NonAsciiRevisionId:
                raise TestSkipped("non-ascii revision ids not supported")
        else:
            tree.commit("in\xedtial")

        return tree

    def test_tree_with_utf8(self):
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            raise TestNotApplicable("format does not support custom file ids")
        self._create_tree_with_utf8(tree)

        tree = self.workingtree_to_test_tree(tree)

        revision_id = "r\xe9v-1".encode()
        root_id = b"TREE_ROOT"
        bar_id = "ba\N{EURO SIGN}r-id".encode()
        foo_id = "fo\N{EURO SIGN}o-id".encode()
        baz_id = "ba\N{EURO SIGN}z-id".encode()
        path_and_ids = [
            ("", root_id, None, None),
            ("ba\N{EURO SIGN}r", bar_id, root_id, revision_id),
            ("fo\N{EURO SIGN}o", foo_id, root_id, revision_id),
            ("ba\N{EURO SIGN}r/ba\N{EURO SIGN}z", baz_id, bar_id, revision_id),
        ]
        with tree.lock_read():
            path_entries = list(tree.iter_entries_by_dir())

        for expected, (path, ie) in zip(path_and_ids, path_entries):
            self.assertEqual(expected[0], path)  # Paths should match
            self.assertIsInstance(path, str)
            self.assertEqual(expected[1], ie.file_id)
            self.assertIsInstance(ie.file_id, bytes)
            self.assertEqual(expected[2], ie.parent_id)
            if expected[2] is not None:
                self.assertIsInstance(ie.parent_id, bytes)
            # WorkingTree's return None for the last modified revision
            if ie.revision is not None:
                self.assertIsInstance(ie.revision, bytes)
                if expected[0] != "":
                    # Some trees will preserve the revision id of the tree root,
                    # but not all will
                    self.assertEqual(revision_id, ie.revision)
        self.assertEqual(len(path_and_ids), len(path_entries))
        get_revision_id = getattr(tree, "get_revision_id", None)
        if get_revision_id is not None:
            self.assertIsInstance(get_revision_id(), bytes)
        last_revision = getattr(tree, "last_revision", None)
        if last_revision is not None:
            self.assertIsInstance(last_revision(), bytes)

    def test_tree_with_merged_utf8(self):
        wt = self.make_branch_and_tree(".")

        self._create_tree_with_utf8(wt)

        tree2 = wt.controldir.sprout("tree2").open_workingtree()
        self.build_tree(["tree2/ba\N{EURO SIGN}r/qu\N{EURO SIGN}x"])
        if wt.supports_setting_file_ids():
            tree2.add(
                ["ba\N{EURO SIGN}r/qu\N{EURO SIGN}x"],
                ids=["qu\N{EURO SIGN}x-id".encode()],
            )
        else:
            tree2.add(["ba\N{EURO SIGN}r/qu\N{EURO SIGN}x"])
        if wt.branch.repository._format.supports_setting_revision_ids:
            tree2.commit("to m\xe9rge", rev_id="r\xe9v-2".encode())
        else:
            tree2.commit("to m\xe9rge")

        self.assertTrue(tree2.is_versioned("ba\N{EURO SIGN}r/qu\N{EURO SIGN}x"))
        wt.merge_from_branch(tree2.branch)
        self.assertTrue(wt.is_versioned("ba\N{EURO SIGN}r/qu\N{EURO SIGN}x"))

        if wt.branch.repository._format.supports_setting_revision_ids:
            wt.commit("m\xe9rge", rev_id="r\xe9v-3".encode())
        else:
            wt.commit("m\xe9rge")
        tree = self.workingtree_to_test_tree(wt)

        revision_id_1 = "r\xe9v-1".encode()
        revision_id_2 = "r\xe9v-2".encode()
        root_id = b"TREE_ROOT"
        bar_id = "ba\N{EURO SIGN}r-id".encode()
        foo_id = "fo\N{EURO SIGN}o-id".encode()
        baz_id = "ba\N{EURO SIGN}z-id".encode()
        qux_id = "qu\N{EURO SIGN}x-id".encode()
        path_and_ids = [
            ("", root_id, None, None),
            ("ba\N{EURO SIGN}r", bar_id, root_id, revision_id_1),
            ("fo\N{EURO SIGN}o", foo_id, root_id, revision_id_1),
            ("ba\N{EURO SIGN}r/ba\N{EURO SIGN}z", baz_id, bar_id, revision_id_1),
            ("ba\N{EURO SIGN}r/qu\N{EURO SIGN}x", qux_id, bar_id, revision_id_2),
        ]
        with tree.lock_read():
            path_entries = list(tree.iter_entries_by_dir())

        for (epath, efid, eparent, _erev), (path, ie) in zip(
            path_and_ids, path_entries
        ):
            self.assertEqual(epath, path)  # Paths should match
            self.assertIsInstance(path, str)
            self.assertIsInstance(ie.file_id, bytes)
            if wt.supports_setting_file_ids():
                self.assertEqual(efid, ie.file_id)
                self.assertEqual(eparent, ie.parent_id)
            if eparent is not None:
                self.assertIsInstance(ie.parent_id, bytes)
        self.assertEqual(
            len(path_and_ids),
            len(path_entries),
            "{!r} vs {!r}".format(
                [p for (p, f, pf, r) in path_and_ids], [p for (p, e) in path_entries]
            ),
        )
        get_revision_id = getattr(tree, "get_revision_id", None)
        if get_revision_id is not None:
            self.assertIsInstance(get_revision_id(), bytes)
        last_revision = getattr(tree, "last_revision", None)
        if last_revision is not None:
            self.assertIsInstance(last_revision(), bytes)

    def skip_if_no_reference(self, tree):
        if not getattr(tree, "supports_tree_reference", lambda: False)():
            raise TestNotApplicable("Tree references not supported")

    def create_nested(self):
        work_tree = self.make_branch_and_tree("wt")
        with work_tree.lock_write():
            self.skip_if_no_reference(work_tree)
            subtree = self.make_branch_and_tree("wt/subtree")
            self.build_tree(["wt/subtree/a"])
            subtree.add(["a"])
            subtree.commit("foo")
            work_tree.add_reference(subtree)
        tree = self._convert_tree(work_tree)
        self.skip_if_no_reference(tree)
        return tree, subtree

    def test_iter_entries_with_unfollowed_reference(self):
        tree, subtree = self.create_nested()
        expected = [("", "directory"), ("subtree", "tree-reference")]
        with tree.lock_read():
            path_entries = list(tree.iter_entries_by_dir(recurse_nested=False))
            actual = [(path, ie.kind) for path, ie in path_entries]
        self.assertEqual(expected, actual)

    def test_iter_entries_with_followed_reference(self):
        tree, subtree = self.create_nested()
        expected = [("", "directory"), ("subtree", "directory"), ("subtree/a", "file")]
        with tree.lock_read():
            path_entries = list(tree.iter_entries_by_dir(recurse_nested=True))
            actual = [(path, ie.kind) for path, ie in path_entries]
        self.assertEqual(expected, actual)

    def test_iter_entries_with_missing_reference(self):
        tree, subtree = self.create_nested()
        shutil.rmtree("wt/subtree")
        with tree.lock_read():
            self.assertRaises(
                MissingNestedTree, list, tree.iter_entries_by_dir(recurse_nested=True)
            )

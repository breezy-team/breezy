# Copyright (C) 2007 Canonical Ltd
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

"""Test that all trees support Tree.list_files()."""

from breezy import osutils
from breezy.tests import TestNotApplicable
from breezy.tests.per_tree import TestCaseWithTree


class TestListFiles(TestCaseWithTree):
    def assertFilesListEqual(self, tree, expected, **kwargs):
        with tree.lock_read():
            if tree.supports_file_ids:
                actual = [
                    (path, status, kind, ie.file_id)
                    for path, status, kind, ie in tree.list_files(**kwargs)
                ]
                expected = [
                    (
                        path,
                        status,
                        kind,
                        tree.path2id(
                            osutils.pathjoin(kwargs.get("from_dir", ""), path)
                        ),
                    )
                    for path, status, kind in expected
                ]
            else:
                actual = [
                    (path, status, kind)
                    for path, status, kind, ie in tree.list_files(**kwargs)
                ]
                expected = [(path, status, kind) for path, status, kind in expected]
        self.assertEqual(expected, actual)

    def test_list_files_with_root(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [
            ("", "V", "directory"),
            ("a", "V", "file"),
            ("b", "V", "directory"),
            ("b/c", "V", "file"),
        ]

        self.assertFilesListEqual(tree, expected, include_root=True)

    def test_list_files_no_root(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [
            ("a", "V", "file"),
            ("b", "V", "directory"),
            ("b/c", "V", "file"),
        ]
        self.assertFilesListEqual(tree, expected)

    def test_list_files_with_root_no_recurse(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [
            ("", "V", "directory"),
            ("a", "V", "file"),
        ]
        expected.append(("b", "V", "directory"))
        self.assertFilesListEqual(tree, expected, include_root=True, recursive=False)

    def test_list_files_no_root_no_recurse(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [("a", "V", "file")]
        expected.append(("b", "V", "directory"))
        self.assertFilesListEqual(tree, expected, recursive=False)

    def test_list_files_from_dir(self):
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [("c", "V", "file")]
        self.assertFilesListEqual(tree, expected, from_dir="b")

    def test_list_files_from_dir_no_recurse(self):
        # The test trees don't have much nesting so test with an explicit root
        work_tree = self.make_branch_and_tree("wt")
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [("a", "V", "file")]
        expected.append(("b", "V", "directory"))

        self.assertFilesListEqual(tree, expected, from_dir="", recursive=False)

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

    def test_list_files_with_unfollowed_reference(self):
        tree, subtree = self.create_nested()
        expected = [("", "V", "directory"), ("subtree", "V", "tree-reference")]
        self.assertFilesListEqual(
            tree, expected, recursive=True, recurse_nested=False, include_root=True
        )

    def test_list_files_with_followed_reference(self):
        tree, subtree = self.create_nested()
        expected = [
            ("", "V", "directory"),
            ("subtree", "V", "directory"),
            ("subtree/a", "V", "file"),
        ]
        self.assertFilesListEqual(
            tree, expected, recursive=True, recurse_nested=True, include_root=True
        )

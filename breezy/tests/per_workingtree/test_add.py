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

"""Tests for interface conformance of 'WorkingTree.add'."""

from breezy import errors, tests
from breezy.tests.per_workingtree import TestCaseWithWorkingTree
from bzrformats import inventory

from ..matchers import HasLayout, HasPathRelations


class TestAdd(TestCaseWithWorkingTree):
    def assertTreeLayout(self, expected, tree):
        """Check that the tree has the correct layout."""
        self.assertThat(tree, HasLayout(expected))

    def assertPathRelations(self, previous_tree, tree, relations):
        self.assertThat(tree, HasPathRelations(previous_tree, relations))

    def test_add_one(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["one"])
        tree.add("one")

        self.assertTreeLayout(["", "one"], tree)

    def test_add_existing_id(self):
        """Adding an entry with a pre-existing id raises DuplicateFileId."""
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(["a", "b"])
        tree.add(["a"])
        self.assertRaises(
            inventory.DuplicateFileId, tree.add, ["b"], ids=[tree.path2id("a")]
        )
        # And the entry should not have been added.
        self.assertTreeLayout(["", "a"], tree)

    def test_add_old_id(self):
        """We can add an old id, as long as it doesn't exist now."""
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(["a", "b"])
        tree.add(["a"])
        file_id = tree.path2id("a")
        tree.commit("first")
        # And the entry should not have been added.
        tree.unversion(["a"])
        tree.add(["b"], ids=[file_id])
        self.assertPathRelations(tree.basis_tree(), tree, [("", ""), ("b", "a")])

    def test_add_one_list(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["one"])
        tree.add(["one"])

        self.assertTreeLayout(["", "one"], tree)

    def test_add_one_new_id(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["one"])
        tree.add(["one"])

        self.assertTreeLayout(["", "one"], tree)

    def test_add_unicode(self):
        tree = self.make_branch_and_tree(".")
        try:
            self.build_tree(["f\xf6"])
        except UnicodeError as err:
            raise tests.TestSkipped("Filesystem does not support filename.") from err
        tree.add(["f\xf6"])

        self.assertTreeLayout(["", "f\xf6"], tree)

    def test_add_subdir_with_ids(self):
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(["dir/", "dir/subdir/", "dir/subdir/foo"])
        tree.add(["dir"], ids=[b"dir-id"])
        tree.add(["dir/subdir"], ids=[b"subdir-id"])
        tree.add(["dir/subdir/foo"], ids=[b"foo-id"])
        root_id = tree.path2id("")

        self.assertTreeLayout(
            [
                ("", root_id),
                ("dir/", b"dir-id"),
                ("dir/subdir/", b"subdir-id"),
                ("dir/subdir/foo", b"foo-id"),
            ],
            tree,
        )

    def test_add_subdir(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["dir/", "dir/subdir/", "dir/subdir/foo"])
        tree.add(["dir"])
        tree.add(["dir/subdir"])
        tree.add(["dir/subdir/foo"])

        self.assertTreeLayout(["", "dir/", "dir/subdir/", "dir/subdir/foo"], tree)

    def test_add_multiple(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b", "dir/", "dir/subdir/", "dir/subdir/foo"])
        tree.add(["a", "b", "dir", "dir/subdir", "dir/subdir/foo"])

        self.assertTreeLayout(
            ["", "a", "b", "dir/", "dir/subdir/", "dir/subdir/foo"], tree
        )

    def test_add_multiple_with_file_ids(self):
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(["a", "b", "dir/", "dir/subdir/", "dir/subdir/foo"])
        tree.add(
            ["a", "b", "dir", "dir/subdir", "dir/subdir/foo"],
            ids=[b"a-id", b"b-id", b"dir-id", b"subdir-id", b"foo-id"],
        )

        self.assertTreeLayout(
            [
                ("", tree.path2id("")),
                ("a", b"a-id"),
                ("b", b"b-id"),
                ("dir/", b"dir-id"),
                ("dir/subdir/", b"subdir-id"),
                ("dir/subdir/foo", b"foo-id"),
            ],
            tree,
        )

    def test_add_invalid(self):
        tree = self.make_branch_and_tree(".")
        if not tree._format.supports_versioned_directories:
            raise tests.TestNotApplicable(
                "format does not support versioned directories"
            )
        self.build_tree(["dir/", "dir/subdir/", "dir/subdir/foo"])

        self.assertRaises(errors.NotVersionedError, tree.add, ["dir/subdir"])
        self.assertTreeLayout([""], tree)

    def test_add_after_remove(self):
        tree = self.make_branch_and_tree(".")
        if not tree._format.supports_versioned_directories:
            raise tests.TestNotApplicable(
                "format does not support versioned directories"
            )
        self.build_tree(["dir/", "dir/subdir/", "dir/subdir/foo"])
        tree.add(["dir"])
        tree.commit("dir")
        tree.unversion(["dir"])
        self.assertRaises(errors.NotVersionedError, tree.add, ["dir/subdir/foo"])

    def test_add_root(self):
        # adding the root should be a no-op, or at least not
        # do anything whacky.
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            tree.add("")
            self.assertEqual([""], list(tree.all_versioned_paths()))
            # the root should have been changed to be a new unique root.
            if tree._format.supports_setting_file_ids:
                self.assertNotEqual(inventory.ROOT_ID, tree.path2id(""))

    def test_add_previously_added(self):
        # adding a path that was previously added should work
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"])
        tree.unversion(["foo"])
        tree.add(["foo"])
        self.assertTrue(tree.has_filename("foo"))

    def test_add_previously_added_with_file_id(self):
        # adding a path that was previously added should work
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(["foo"])
        tree.add(["foo"], ids=[b"foo-id"])
        tree.unversion(["foo"])
        tree.add(["foo"], ids=[b"foo-id"])
        self.assertEqual(b"foo-id", tree.path2id("foo"))

    def test_add_present_in_basis(self):
        # adding a path that was present in the basis should work.
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"])
        tree.commit("add foo")
        tree.unversion(["foo"])
        tree.add(["foo"])
        self.assertTrue(tree.has_filename("foo"))

    def test_add_present_in_basis_with_file_ids(self):
        # adding a path that was present in the basis should work.
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(["foo"])
        tree.add(["foo"], ids=[b"foo-id"])
        tree.commit("add foo")
        tree.unversion(["foo"])
        tree.add(["foo"], ids=[b"foo-id"])
        self.assertEqual(b"foo-id", tree.path2id("foo"))

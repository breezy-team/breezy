# Copyright (C) 2006-2009, 2011 Canonical Ltd
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

from breezy import errors, tests, workingtree
from breezy.mutabletree import BadReferenceTarget
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestBasisInventory(TestCaseWithWorkingTree):
    def make_trees(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file1"])
        tree.add("file1")
        sub_tree = self.make_branch_and_tree("tree/sub-tree")
        sub_tree.commit("commit")
        return tree, sub_tree

    def _references_unsupported(self, tree):
        if not tree.supports_tree_reference():
            raise tests.TestNotApplicable("Tree format does not support references")
        else:
            self.fail("{!r} does not support references but should".format(tree))

    def make_nested_trees(self):
        tree, sub_tree = self.make_trees()
        try:
            tree.add_reference(sub_tree)
        except errors.UnsupportedOperation:
            self._references_unsupported(tree)
        return tree, sub_tree

    def test_add_reference(self):
        tree, sub_tree = self.make_nested_trees()
        with tree.lock_write():
            if tree.supports_setting_file_ids():
                sub_tree_root_id = sub_tree.path2id("")
                self.assertEqual(tree.path2id("sub-tree"), sub_tree_root_id)
            self.assertEqual(tree.kind("sub-tree"), "tree-reference")
            tree.commit("commit reference")
            basis = tree.basis_tree()
            with basis.lock_read():
                sub_tree = tree.get_nested_tree("sub-tree")
                self.assertEqual(
                    sub_tree.last_revision(), tree.get_reference_revision("sub-tree")
                )
        self.assertEqual(["sub-tree"], list(tree.iter_references()))

    def test_add_reference_same_root(self):
        tree = self.make_branch_and_tree("tree")
        if not tree.supports_setting_file_ids():
            self.skipTest("format does not support setting file ids")
        self.build_tree(["tree/file1"])
        tree.add("file1")
        tree.set_root_id(b"root-id")
        sub_tree = self.make_branch_and_tree("tree/sub-tree")
        sub_tree.set_root_id(b"root-id")
        try:
            self.assertRaises(BadReferenceTarget, tree.add_reference, sub_tree)
        except errors.UnsupportedOperation:
            self._references_unsupported(tree)

    def test_root_present(self):
        """Subtree root is present, though not the working tree root."""
        tree, sub_tree = self.make_trees()
        if not tree.supports_setting_file_ids():
            self.skipTest("format does not support setting file ids")
        sub_tree.set_root_id(tree.path2id("file1"))
        try:
            self.assertRaises(BadReferenceTarget, tree.add_reference, sub_tree)
        except errors.UnsupportedOperation:
            self._references_unsupported(tree)

    def test_add_non_subtree(self):
        tree, _sub_tree = self.make_trees()
        os.rename("tree/sub-tree", "sibling")
        sibling = workingtree.WorkingTree.open("sibling")
        try:
            self.assertRaises(BadReferenceTarget, tree.add_reference, sibling)
        except errors.UnsupportedOperation:
            self._references_unsupported(tree)

    def test_get_nested_tree(self):
        tree, sub_tree = self.make_nested_trees()
        with tree.lock_read():
            sub_tree2 = tree.get_nested_tree("sub-tree")
            self.assertEqual(sub_tree.basedir, sub_tree2.basedir)

    def test_get_containing_nested_tree(self):
        tree, sub_tree = self.make_nested_trees()
        self.build_tree_contents([("tree/sub-tree/foo", "bar")])
        sub_tree.add("foo")
        sub_tree.commit("rev1")
        with tree.lock_read():
            sub_tree2, subpath = tree.get_containing_nested_tree("sub-tree/foo")
            self.assertEqual(sub_tree.basedir, sub_tree2.basedir)
            self.assertEqual(subpath, "foo")
            self.assertEqual(
                (None, None), tree.get_containing_nested_tree("not-subtree/bar")
            )

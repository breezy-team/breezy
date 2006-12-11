# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os

from bzrlib import errors, tests, workingtree
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree

class TestBasisInventory(TestCaseWithWorkingTree):

    def make_trees(self):
        tree = self.make_branch_and_tree('tree')
        tree.set_root_id('root-id')
        self.build_tree(['tree/file1'])
        tree.add('file1', 'file1-id')
        sub_tree = self.make_branch_and_tree('tree/sub-tree')
        sub_tree.set_root_id('sub-tree-root-id')
        return tree, sub_tree

    def test_add_reference(self):
        tree, sub_tree = self.make_trees()
        try:
            tree.add_reference(sub_tree)
        except errors.UnsupportedOperation:
            assert tree.__class__ in (workingtree.WorkingTree2, 
                                      workingtree.WorkingTree3)
            raise tests.TestSkipped('Tree format does not support references')
        self.assertEqual(tree.path2id('sub-tree'), 'sub-tree-root-id')
        self.assertEqual(tree.inventory['sub-tree-root-id'].kind, 
                         'tree-reference')

    def test_add_reference_same_root(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file1'])
        tree.add('file1', 'file1-id')
        tree.set_root_id('root-id')
        sub_tree = self.make_branch_and_tree('tree/sub-tree')
        sub_tree.set_root_id('root-id')
        try:
            self.assertRaises(errors.BadReferenceTarget, tree.add_reference, 
                              sub_tree)
        except errors.UnsupportedOperation:
            assert tree.__class__ in (workingtree.WorkingTree2, 
                                      workingtree.WorkingTree3)
            raise tests.TestSkipped('Tree format does not support references')

    def test_root_present(self):
        """Subtree root is present, though not the working tree root"""
        tree, sub_tree = self.make_trees()
        sub_tree.set_root_id('file1-id')
        try:
            self.assertRaises(errors.BadReferenceTarget, tree.add_reference, 
                              sub_tree)
        except errors.UnsupportedOperation:
            assert tree.__class__ in (workingtree.WorkingTree2, 
                                      workingtree.WorkingTree3)
            raise tests.TestSkipped('Tree format does not support references')

    def test_add_non_subtree(self):
        tree, sub_tree = self.make_trees()
        os.rename('tree/sub-tree', 'sibling')
        sibling = workingtree.WorkingTree.open('sibling')
        try:
            self.assertRaises(errors.BadReferenceTarget, tree.add_reference, 
                              sibling)
        except errors.UnsupportedOperation:
            assert tree.__class__ in (workingtree.WorkingTree2, 
                                      workingtree.WorkingTree3)
            raise tests.TestSkipped('Tree format does not support references')


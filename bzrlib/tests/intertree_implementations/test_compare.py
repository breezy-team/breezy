# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for the InterTree.compare() function."""

from bzrlib import inventory 
from bzrlib.tests.intertree_implementations import TestCaseWithTwoTrees


class TestCompare(TestCaseWithTwoTrees):

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_to_tree_no_parents_no_content(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)

    def test_empty_to_abc_content(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_to_tree_no_parents_abc_content(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)

    def test_abc_content_to_empty(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_to_tree_no_parents_no_content(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.removed)
        self.assertEqual([], d.renamed)

    def test_content_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_to_tree_no_parents_abc_content_2(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([('a', 'a-id', 'file', True, False)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        
    def test_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_to_tree_no_parents_abc_content_3(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([('b/c', 'c-id', 'file', False, True)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)

    def test_file_rename(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_to_tree_no_parents_abc_content_4(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', False, False)], d.renamed)

    def test_file_rename_and_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_to_tree_no_parents_abc_content_5(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', True, False)], d.renamed)

    def test_file_rename_and_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_to_tree_no_parents_abc_content_6(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('b/c', 'e', 'c-id', 'file', False, True)], d.renamed)

# Copyright (C) 2020 Jelmer Vernooij
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

"""Tests for breezy.branch.InterBranch.copy_content_into."""

from breezy import branch
from breezy.tests import TestNotApplicable
from breezy.tests.per_intertree import (
    TestCaseWithTwoTrees,
    )
from breezy.transport import NoSuchFile


class TestFindPaths(TestCaseWithTwoTrees):

    def test_path_missing(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        self.build_tree_contents([
            ('1/file', b'apples'),
            ('2/file', b'apples'),
            ])
        tree1.add('file')
        tree2.add('file')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        inter = self.intertree_class(tree1, tree2)
        self.assertRaises(NoSuchFile, inter.find_source_path, 'missing')
        self.assertRaises(NoSuchFile, inter.find_target_path, 'missing')
        self.assertRaises(NoSuchFile, inter.find_source_paths, ['missing'])
        self.assertRaises(NoSuchFile, inter.find_target_paths, ['missing'])

    def test_old_path(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        self.build_tree_contents([
            ('2/file', b'apples'),
            ])
        tree2.add('file')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        inter = self.intertree_class(tree1, tree2)
        self.assertIs(None, inter.find_source_path('file'))
        self.assertEqual({'file': None}, inter.find_source_paths(['file']))

    def test_new_path(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        self.build_tree_contents([
            ('1/file', b'apples'),
            ])
        tree1.add('file')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        inter = self.intertree_class(tree1, tree2)
        self.assertIs(None, inter.find_target_path('file'))
        self.assertEqual({'file': None}, inter.find_target_paths(['file']))

    def test_unchanged(self):
        tree1 = self.make_branch_and_tree('1')
        self.build_tree_contents([
            ('1/file', b'apples'),
            ])
        tree1.add('file')
        tree1.commit('foo')

        tree2 = self.make_to_branch_and_tree('2')
        tree2.pull(tree1.branch)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        inter = self.intertree_class(tree1, tree2)
        self.assertEqual('file', inter.find_target_path('file'))
        self.assertEqual({'file': 'file'}, inter.find_target_paths(['file']))
        self.assertEqual('file', inter.find_source_path('file'))
        self.assertEqual({'file': 'file'}, inter.find_source_paths(['file']))

    def test_rename(self):
        tree1 = self.make_branch_and_tree('1')
        self.build_tree_contents([
            ('1/file', b'apples'),
            ])
        tree1.add('file')
        tree1.commit('foo')

        tree2 = self.make_to_branch_and_tree('2')
        tree2.pull(tree1.branch)
        tree2.rename_one('file', 'newfile')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        inter = self.intertree_class(tree1, tree2)
        self.assertEqual('newfile', inter.find_target_path('file'))
        self.assertEqual({'file': 'newfile'}, inter.find_target_paths(['file']))
        self.assertEqual('file', inter.find_source_path('newfile'))
        self.assertEqual({'newfile': 'file'}, inter.find_source_paths(['newfile']))

    def test_copy(self):
        tree1 = self.make_branch_and_tree('1')
        self.build_tree_contents([
            ('1/file', b'apples'),
            ])
        tree1.add('file')
        tree1.commit('foo')

        tree2 = self.make_to_branch_and_tree('2')
        tree2.pull(tree1.branch)
        tree2.copy_one('file', 'newfile')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        inter = self.intertree_class(tree1, tree2)
        self.assertIn(inter.find_target_path('file'), ['file', 'newfile'])
        self.assertIn(inter.find_source_path('newfile'), ['file', None])
        self.assertEqual('file', inter.find_source_path('file'))
        self.assertIn(inter.find_source_paths(['newfile']), [{'newfile': 'file'}, {'newfile': None}])

        self.assertIn(
            inter.find_source_paths(['newfile', 'file']), [
                {'newfile': 'file', 'file': 'file'},
                {'newfile': None, 'file': 'file'},
                ])

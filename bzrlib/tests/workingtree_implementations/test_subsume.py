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

from bzrlib import errors, tests
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestWorkingTree(TestCaseWithWorkingTree):

    def make_trees(self):
        self.build_tree(['tree/', 
                         'tree/file',
                         'tree/subtree/',
                         'tree/subtree/file2'])
        base_tree = self.make_branch_and_tree('tree')
        base_tree.add('file', 'file-id')
        base_tree.commit('first commit', rev_id='tree-1')
        sub_tree = self.make_branch_and_tree('tree/subtree')
        sub_tree.add('file2', 'file2-id')
        sub_tree.commit('first commit', rev_id='subtree-1')
        if base_tree.get_root_id() == sub_tree.get_root_id():
            raise tests.TestSkipped('This test requires unique roots')
        return base_tree, sub_tree

    def test_subsume_tree(self):
        base_tree, sub_tree = self.make_trees()
        if base_tree.get_root_id() == sub_tree.get_root_id():
            raise tests.TestSkipped('This test requires unique roots')
        sub_root_id = sub_tree.get_root_id()
        base_tree.subsume(sub_tree)
        self.assertEqual(['tree-1', 'subtree-1'], base_tree.get_parent_ids())
        self.assertEqual(sub_root_id, base_tree.path2id('subtree'))
        self.assertEqual('file2-id', base_tree.path2id('subtree/file2'))

    def test_subsume_failure(self):
        base_tree, sub_tree = self.make_trees()
        if base_tree.get_root_id() == sub_tree.get_root_id():
            raise tests.TestSkipped('This test requires unique roots')
        sub_root_id = sub_tree.get_root_id()
        self.assertRaises(errors.BadSubsumeTarget, base_tree.subsume, 
                          base_tree)
        self.assertRaises(errors.BadSubsumeTarget, sub_tree.subsume, 
                          base_tree)
        self.build_tree(['subtree2/'])
        sub_tree2 = self.make_branch_and_tree('subtree2')
        self.assertRaises(errors.BadSubsumeTarget, sub_tree.subsume, 
                          sub_tree2)

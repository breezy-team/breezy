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

from bzrlib import bzrdir, errors, repository, workingtree, tests


class TestWorkingTree(tests.TestCaseWithTransport):

    def get_knit2_format(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = repository.RepositoryFormatKnit2()
        return format

    def get_knit1_format(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = repository.RepositoryFormatKnit1()
        return format

    def make_branch_and_tree(self, relpath, format=None):
        if format is None:
            format = self.get_knit2_format()
        return tests.TestCaseWithTransport.make_branch_and_tree(self, relpath, 
                                                          format)

    def make_trees(self, format=None, same_root=False):
        self.build_tree(['tree/', 
                         'tree/file',
                         'tree/subtree/',
                         'tree/subtree/file2'])
        base_tree = self.make_branch_and_tree('tree', format=format)
        base_tree.add('file', 'file-id')
        base_tree.commit('first commit', rev_id='tree-1')
        sub_tree = self.make_branch_and_tree('tree/subtree', 
                                             format=self.get_knit1_format())
        if same_root is True:
            sub_tree.set_root_id(base_tree.get_root_id())
        sub_tree.add('file2', 'file2-id')
        sub_tree.commit('first commit', rev_id='subtree-1')
        return base_tree, sub_tree

    def test_old_knit1_failure(self):
        """Ensure that BadSubsumeSource is raised.

        SubsumeTargetNeedsUpgrade must not be raised, because upgrading the
        target won't help.
        """
        base_tree, sub_tree = self.make_trees(format=self.get_knit1_format(),
                                              same_root=True)
        self.assertRaises(errors.BadSubsumeSource, base_tree.subsume, 
                          sub_tree)

    def test_knit1_failure(self):
        base_tree, sub_tree = self.make_trees(format=self.get_knit1_format())
        self.assertRaises(errors.SubsumeTargetNeedsUpgrade, base_tree.subsume, 
                          sub_tree)

    def test_subsume_tree(self):
        base_tree, sub_tree = self.make_trees()
        assert base_tree.get_root_id() != sub_tree.get_root_id()
        sub_root_id = sub_tree.get_root_id()
        base_tree.subsume(sub_tree)
        self.assertEqual(['tree-1', 'subtree-1'], base_tree.get_parent_ids())
        self.assertEqual(sub_root_id, base_tree.path2id('subtree'))
        self.assertEqual('file2-id', base_tree.path2id('subtree/file2'))
        sub_bzrdir = bzrdir.BzrDir.open('tree/subtree')
        self.assertRaises(errors.NoWorkingTree, sub_bzrdir.open_workingtree)
        sub_bzrdir.open_branch()
        file2 = open('tree/subtree/file2', 'rb')
        try:
            file2_contents = file2.read()
        finally:
            file2.close()
        base_tree = workingtree.WorkingTree.open('tree')
        base_tree.commit('combined', rev_id='combined-1')
        self.assertEqual('file2-id', base_tree.path2id('subtree/file2'))
        self.assertEqual('subtree/file2', base_tree.id2path('file2-id'))
        self.assertEqualDiff(file2_contents, 
                             base_tree.get_file_text('file2-id'))
        basis_tree = base_tree.basis_tree()
        self.assertEqualDiff(file2_contents, 
                             base_tree.get_file_text('file2-id'))
        self.assertEqualDiff(file2_contents, 
                             basis_tree.get_file_text('file2-id'))
        self.assertEqual('subtree-1', 
                         basis_tree.inventory['file2-id'].revision)
        self.assertEqual('combined-1', 
                         basis_tree.inventory[sub_root_id].revision)

    def test_subsume_failure(self):
        base_tree, sub_tree = self.make_trees()
        if base_tree.get_root_id() == sub_tree.get_root_id():
            raise tests.TestSkipped('This test requires unique roots')
        sub_root_id = sub_tree.get_root_id()
        self.assertRaises(errors.BadSubsumeSource, base_tree.subsume, 
                          base_tree)
        self.assertRaises(errors.BadSubsumeSource, sub_tree.subsume, 
                          base_tree)
        self.build_tree(['subtree2/'])
        sub_tree2 = self.make_branch_and_tree('subtree2')
        self.assertRaises(errors.BadSubsumeSource, sub_tree.subsume, 
                          sub_tree2)
        self.build_tree(['tree/subtree/subtree3/'])
        sub_tree3 = self.make_branch_and_tree('tree/subtree/subtree3')
        self.assertRaises(errors.BadSubsumeSource, base_tree.subsume,
                          sub_tree3)

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

from breezy import errors, workingtree, tests


class TestWorkingTree(tests.TestCaseWithTransport):

    def make_branch_and_tree(self, relpath, format=None):
        if format is None:
            format = 'development-subtree'
        return tests.TestCaseWithTransport.make_branch_and_tree(self, relpath,
                                                                format)

    def make_trees(self, format=None, same_root=False):
        self.build_tree(['tree/',
                         'tree/file',
                         'tree/subtree/',
                         'tree/subtree/file2'])
        base_tree = self.make_branch_and_tree('tree', format=format)
        base_tree.add('file', ids=b'file-id')
        base_tree.commit('first commit', rev_id=b'tree-1')
        sub_tree = self.make_branch_and_tree('tree/subtree',
                                             format='development-subtree')
        if same_root is True:
            sub_tree.set_root_id(base_tree.path2id(''))
        sub_tree.add('file2', ids=b'file2-id')
        sub_tree.commit('first commit', rev_id=b'subtree-1')
        return base_tree, sub_tree

    def test_old_knit1_failure(self):
        """Ensure that BadSubsumeSource is raised.

        SubsumeTargetNeedsUpgrade must not be raised, because upgrading the
        target won't help.
        """
        base_tree, sub_tree = self.make_trees(format='knit',
                                              same_root=True)
        self.assertRaises(errors.BadSubsumeSource, base_tree.subsume,
                          sub_tree)

    def test_knit1_failure(self):
        base_tree, sub_tree = self.make_trees(format='knit')
        self.assertRaises(errors.SubsumeTargetNeedsUpgrade, base_tree.subsume,
                          sub_tree)

    def test_subsume_tree(self):
        base_tree, sub_tree = self.make_trees()
        self.assertNotEqual(base_tree.path2id(''), sub_tree.path2id(''))
        sub_root_id = sub_tree.path2id('')
        # this test checks the subdir is removed, so it needs to know the
        # control directory; that changes rarely so just hardcode (and check)
        # it is correct.
        self.assertPathExists('tree/subtree/.bzr')
        base_tree.subsume(sub_tree)
        self.assertEqual([b'tree-1', b'subtree-1'], base_tree.get_parent_ids())
        self.assertEqual(sub_root_id, base_tree.path2id('subtree'))
        self.assertEqual(b'file2-id', base_tree.path2id('subtree/file2'))
        # subsuming the tree removes the control directory, so you can't open
        # it.
        self.assertPathDoesNotExist('tree/subtree/.bzr')
        with open('tree/subtree/file2', 'rb') as file2:
            file2_contents = file2.read()
        base_tree = workingtree.WorkingTree.open('tree')
        base_tree.commit('combined', rev_id=b'combined-1')
        self.assertEqual(b'file2-id', base_tree.path2id('subtree/file2'))
        if base_tree.supports_setting_file_ids():
            self.assertEqual('subtree/file2', base_tree.id2path(b'file2-id'))
        self.assertEqualDiff(file2_contents,
                             base_tree.get_file_text('subtree/file2'))
        basis_tree = base_tree.basis_tree()
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)
        self.assertEqualDiff(file2_contents,
                             base_tree.get_file_text('subtree/file2'))
        self.assertEqualDiff(file2_contents,
                             basis_tree.get_file_text('subtree/file2'))
        self.assertEqual(b'subtree-1',
                         basis_tree.get_file_revision('subtree/file2'))
        self.assertEqual(b'combined-1',
                         basis_tree.get_file_revision('subtree'))

    def test_subsume_failure(self):
        base_tree, sub_tree = self.make_trees()
        if base_tree.path2id('') == sub_tree.path2id(''):
            raise tests.TestSkipped('This test requires unique roots')
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

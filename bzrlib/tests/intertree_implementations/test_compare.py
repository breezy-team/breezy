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

"""Tests for the InterTree.compare() function."""

import os

from bzrlib import errors
from bzrlib.tests.intertree_implementations import TestCaseWithTwoTrees


class TestCompare(TestCaseWithTwoTrees):

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_dangling(self):
        # This test depends on the ability for some trees to have a difference
        # between a 'versioned present' and 'versioned not present' (aka
        # dangling) file. In this test there are two trees each with a separate
        # dangling file, and the dangling files should be considered absent for
        # the test.
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        self.build_tree(['2/a'])
        tree2.add('a')
        os.unlink('2/a')
        self.build_tree(['1/b'])
        tree1.add('b')
        os.unlink('1/b')
        # the conversion to test trees here will leave the trees intact for the
        # default intertree, but may perform a commit for other tree types,
        # which may reduce the validity of the test. XXX: Think about how to
        # address this.
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_abc_content_to_empty(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_content_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_2(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([('a', 'a-id', 'file', True, False)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)
        
    def test_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([('b/c', 'c-id', 'file', False, True)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_file_rename(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_4(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', False, False)], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_file_rename_and_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', True, False)], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_file_rename_and_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_6(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('b/c', 'e', 'c-id', 'file', False, True)], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_a_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(specific_files=['a'])
        self.assertEqual([('a', 'a-id', 'file')], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_a_and_c_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['a', 'b/c'])
        self.assertEqual(
            [('a', 'a-id', 'file'), ('b/c', 'c-id', 'file')],
            d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_b_only(self):
        """Restricting to a dir matches the children of the dir."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(specific_files=['b'])
        self.assertEqual(
            [('b', 'b-id', 'directory'),('b/c', 'c-id', 'file')],
            d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_unchanged_with_renames_and_modifications(self):
        """want_unchanged should generate a list of unchanged entries."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(want_unchanged=True)
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', True, False)], d.renamed)
        self.assertEqual(
            [(u'b', 'b-id', 'directory'), (u'b/c', 'c-id', 'file')],
            d.unchanged)

    def test_extra_trees_finds_ids(self):
        """Ask for a delta between two trees with a path present in a third."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(specific_files=['b'])
        # the type of tree-3 does not matter - it is used as a lookup, not
        # a dispatch. XXX: For dirstate it does speak to the optimisability of
        # the lookup, in merged trees it can be fast-pathed. We probably want
        # two tests: one as is, and one with it as a pending merge.
        tree3 = self.make_branch_and_tree('3')
        tree3 = self.get_tree_no_parents_abc_content_6(tree3)
        tree3.lock_read()
        self.addCleanup(tree3.unlock)
        # tree 3 has 'e' which is 'c-id'. Tree 1 has c-id at b/c, and Tree 2
        # has c-id at b/c with its exec flag toggled.
        # without extra_trees, we should get no modifications from this
        # so do one, to be sure the test is valid.
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['e'])
        self.assertEqual([], d.modified)
        # now give it an additional lookup:
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['e'], extra_trees=[tree3])
        self.assertEqual([], d.added)
        self.assertEqual([('b/c', 'c-id', 'file', False, True)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_require_versioned(self):
        # this does not quite robustly test, as it is passing in missing paths
        # rather than present-but-not-versioned paths. At the moment there is
        # no mechanism for managing the test trees (which are readonly) to 
        # get present-but-not-versioned files for trees that can do that.
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        self.assertRaises(errors.PathsNotVersionedError, 
            self.intertree_class(tree1, tree2).compare,
            specific_files=['d'],
            require_versioned=True)


class TestIterChanges(TestCaseWithTwoTrees):
    """Test the comparison iterator"""

    def do_iter_changes(self, tree1, tree2, **extra_args):
        """Helper to run _iter_changes from tree1 to tree2.
        
        :param tree1, tree2:  The source and target trees. These will be locked
            automatically.
        :param **extra_args: Extra args to pass to _iter_changes. This is not
            inspected by this test helper.
        """
        tree1.lock_read()
        tree2.lock_read()
        try:
            return list(self.intertree_class(tree1, tree2)
                ._iter_changes(**extra_args))
        finally:
            tree1.unlock()
            tree2.unlock()

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        self.assertEqual([], self.do_iter_changes(tree1, tree2))

    def added(self, tree, file_id):
        entry = tree.inventory[file_id]
        path = tree.id2path(file_id)
        return (file_id, path, True, (False, True), (None, entry.parent_id),
                (None, entry.name), (None, entry.kind), 
                (None, entry.executable))

    def deleted(self, tree, file_id):
        entry = tree.inventory[file_id]
        path = tree.id2path(file_id)
        return (file_id, path, True, (True, False), (entry.parent_id, None),
                (entry.name, None), (entry.kind, None), 
                (entry.executable, None))

    def test_empty_to_abc_content(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        tree2.lock_read()
        expected_results = [
            self.added(tree2, 'root-id'),
            self.added(tree2, 'a-id'),
            self.added(tree2, 'b-id'),
            self.added(tree2, 'c-id'),
            self.deleted(tree1, 'empty-root-id')]
        tree1.unlock()
        tree2.unlock()
        self.assertEqual(expected_results, self.do_iter_changes(tree1, tree2))

    def test_empty_to_abc_content_a_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        tree2.lock_read()
        self.assertEqual(
            [self.added(tree2, 'a-id')],
            self.do_iter_changes(tree1, tree2, specific_file_ids=['a-id']))
        tree1.unlock()
        tree2.unlock()

    def test_abc_content_to_empty_to_abc_content_a_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        tree2.lock_read()
        self.assertEqual(
            [self.deleted(tree1, 'a-id')],
            self.do_iter_changes(tree1, tree2, specific_file_ids=['a-id']))
        tree1.unlock()
        tree2.unlock()

    def test_empty_to_abc_content_a_and_c_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        tree2.lock_read()
        expected_result = [self.added(tree2, 'a-id'), self.added(tree2, 'c-id')]
        tree1.unlock()
        tree2.unlock()
        self.assertEqual(expected_result,
            self.do_iter_changes(tree1, tree2, specific_file_ids=['a-id', 'c-id']))

    def test_abc_content_to_empty(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        tree2.lock_read()
        def deleted(file_id):
            entry = tree1.inventory[file_id]
            path = tree1.id2path(file_id)
            return (file_id, path, True, (True, False),
                    (entry.parent_id, None),
                    (entry.name, None), (entry.kind, None),
                    (entry.executable, None))
        expected_results = [self.added(tree2, 'empty-root-id'),
                          deleted('root-id'), deleted('a-id'),
                          deleted('b-id'), deleted('c-id')]
        tree1.unlock()
        tree2.unlock()
        self.assertEqual(
            expected_results,
            self.do_iter_changes(tree1, tree2))

    def test_content_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_2(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', 'a', True, (True, True),
                          (root_id, root_id), ('a', 'a'),
                          ('file', 'file'), (False, False))],
                         self.do_iter_changes(tree1, tree2))

    def test_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        self.assertEqual([('c-id', 'b/c', False, (True, True),
                          ('b-id', 'b-id'), ('c', 'c'), ('file', 'file'),
                          (False, True))],
                         self.do_iter_changes(tree1, tree2))

    def test_file_rename(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_4(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', 'd', False, (True, True),
                          (root_id, root_id), ('a', 'd'), ('file', 'file'),
                          (False, False))],
                         self.do_iter_changes(tree1, tree2))

    def test_file_rename_and_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', 'd', True, (True, True),
                          (root_id, root_id), ('a', 'd'), ('file', 'file'),
                           (False, False))],
                         self.do_iter_changes(tree1, tree2))

    def test_file_rename_and_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_6(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('c-id', 'e', False, (True, True),
                          ('b-id', root_id), ('c', 'e'), ('file', 'file'),
                          (False, True))],
                         self.do_iter_changes(tree1, tree2))

    def test_unchanged_with_renames_and_modifications(self):
        """want_unchanged should generate a list of unchanged entries."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        def unchanged(file_id):
            entry = tree1.inventory[file_id]
            parent = entry.parent_id
            name = entry.name
            kind = entry.kind
            executable = entry.executable
            return (file_id, tree1.id2path(file_id), False, (True, True),
                   (parent, parent), (name, name), (kind, kind),
                   (executable, executable))
        self.assertEqual([unchanged(root_id), unchanged('b-id'),
                          ('a-id', 'd', True, (True, True),
                          (root_id, root_id), ('a', 'd'), ('file', 'file'),
                          (False, False)), unchanged('c-id')],
                         self.do_iter_changes(tree1, tree2, include_unchanged=True))

# Copyright (C) 2006, 2007 Canonical Ltd
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
import shutil

from bzrlib import errors, tests, workingtree_4
from bzrlib.osutils import file_kind
from bzrlib.tests.intertree_implementations import TestCaseWithTwoTrees

# TODO: test diff unversioned dir that exists
# TODO: test the include_root option.
# TODO: test that renaming a directory x->y does not emit a rename for the
#       child x/a->y/a.
# TODO: test that renaming a directory x-> does not emit a rename for the child
#        x/a -> y/a when a supplied_files argument gives either 'x/' or 'y/a'
#        -> that is, when the renamed parent is not processed by the function.
# TODO: include dangling in the diff output.
# TODO: test items are only emitted once when a specific_files list names a dir
#       whose parent is now a child.
# TODO: test require_versioned
# TODO: explicitly test specific_files listing a non-dir, and listing a symlink
#       (it should not follow the link)
# TODO: test specific_files when the target tree has a file and the source a
#       dir with children, same id and same path. 
# TODO: test comparisons between trees with different root ids. mbp 20070301
#
# TODO: More comparisons between trees with subtrees in different states.

class TestCompare(TestCaseWithTwoTrees):

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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
        tree2.set_root_id(tree1.get_root_id())
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

    def test_default_ignores_unversioned_files(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/a', 'tree1/c',
                         'tree2/a', 'tree2/b', 'tree2/c'])
        tree1.add(['a', 'c'], ['a-id', 'c-id'])
        tree2.add(['a', 'c'], ['a-id', 'c-id'])

        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([(u'a', 'a-id', 'file', True, False),
            (u'c', 'c-id', 'file', True, False)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)
        self.assertEqual([], d.unversioned)

    def test_unversioned_paths_in_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file', 'tree2/dir/'])
        # try:
        os.symlink('target', 'tree2/link')
        links_supported = True
        # except ???:
        #   links_supported = False
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(want_unversioned=True)
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)
        self.assertEqual([(u'dir', None, 'directory'), (u'file', None, 'file'),
            (u'link', None, 'symlink')], d.unversioned)


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
            # sort order of output is not strictly defined
            return sorted(self.intertree_class(tree1, tree2)
                ._iter_changes(**extra_args))
        finally:
            tree1.unlock()
            tree2.unlock()

    def make_tree_with_special_names(self):
        """Create a tree with filenames chosen to exercise the walk order."""
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        paths, path_ids = self._create_special_names(tree2, 'tree2')
        tree2.commit('initial', rev_id='rev-1')
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        return (tree1, tree2, paths, path_ids)

    def make_trees_with_special_names(self):
        """Both trees will use the special names.

        But the contents will differ for each file.
        """
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        paths, path_ids = self._create_special_names(tree1, 'tree1')
        paths, path_ids = self._create_special_names(tree2, 'tree2')
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        return (tree1, tree2, paths, path_ids)

    def _create_special_names(self, tree, base_path):
        """Create a tree with paths that expose differences in sort orders."""
        # Each directory will have a single file named 'f' inside
        dirs = ['a',
                'a-a',
                'a/a',
                'a/a-a',
                'a/a/a',
                'a/a/a-a',
                'a/a/a/a',
                'a/a/a/a-a',
                'a/a/a/a/a',
               ]
        with_slashes = []
        paths = []
        path_ids = []
        for d in dirs:
            with_slashes.append(base_path + '/' + d + '/')
            with_slashes.append(base_path + '/' + d + '/f')
            paths.append(d)
            paths.append(d+'/f')
            path_ids.append(d.replace('/', '_') + '-id')
            path_ids.append(d.replace('/', '_') + '_f-id')
        self.build_tree(with_slashes)
        tree.add(paths, path_ids)
        return paths, path_ids

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
        return (file_id, (None, path), True, (False, True), (None, entry.parent_id),
                (None, entry.name), (None, entry.kind),
                (None, entry.executable))

    def content_changed(self, tree, file_id):
        entry = tree.inventory[file_id]
        path = tree.id2path(file_id)
        return (file_id, (path, path), True, (True, True), (entry.parent_id, entry.parent_id),
                (entry.name, entry.name), (entry.kind, entry.kind),
                (entry.executable, entry.executable))

    def kind_changed(self, from_tree, to_tree, file_id):
        old_entry = from_tree.inventory[file_id]
        new_entry = to_tree.inventory[file_id]
        path = to_tree.id2path(file_id)
        from_path = from_tree.id2path(file_id)
        return (file_id, (from_path, path), True, (True, True), (old_entry.parent_id, new_entry.parent_id),
                (old_entry.name, new_entry.name), (old_entry.kind, new_entry.kind),
                (old_entry.executable, new_entry.executable))

    def missing(self, file_id, from_path, to_path, parent_id, kind):
        _, from_basename = os.path.split(from_path)
        _, to_basename = os.path.split(to_path)
        # missing files have both paths, but no kind.
        return (file_id, (from_path, to_path), True, (True, True),
            (parent_id, parent_id),
            (from_basename, to_basename), (kind, None), (False, False))

    def deleted(self, tree, file_id):
        entry = tree.inventory[file_id]
        path = tree.id2path(file_id)
        return (file_id, (path, None), True, (True, False), (entry.parent_id, None),
                (entry.name, None), (entry.kind, None),
                (entry.executable, None))

    def renamed(self, from_tree, to_tree, file_id, content_changed):
        from_entry = from_tree.inventory[file_id]
        to_entry = to_tree.inventory[file_id]
        from_path = from_tree.id2path(file_id)
        to_path = to_tree.id2path(file_id)
        return (file_id, (from_path, to_path), content_changed, (True, True),
            (from_entry.parent_id, to_entry.parent_id),
            (from_entry.name, to_entry.name),
            (from_entry.kind, to_entry.kind),
            (from_entry.executable, to_entry.executable))

    def unchanged(self, tree, file_id):
        entry = tree.inventory[file_id]
        parent = entry.parent_id
        name = entry.name
        kind = entry.kind
        executable = entry.executable
        path = tree.id2path(file_id)
        return (file_id, (path, path), False, (True, True),
               (parent, parent), (name, name), (kind, kind),
               (executable, executable))

    def unversioned(self, tree, path):
        """Create an unversioned result."""
        _, basename = os.path.split(path)
        kind = file_kind(tree.abspath(path))
        return (None, (None, path), True, (False, False), (None, None),
                (None, basename), (None, kind),
                (None, False))

    def test_empty_to_abc_content(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        tree2.lock_read()
        expected_results = sorted([
            self.added(tree2, 'root-id'),
            self.added(tree2, 'a-id'),
            self.added(tree2, 'b-id'),
            self.added(tree2, 'c-id'),
            self.deleted(tree1, 'empty-root-id')])
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
            self.do_iter_changes(tree1, tree2, specific_files=['a']))
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
            self.do_iter_changes(tree1, tree2, specific_files=['a']))
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
            self.do_iter_changes(tree1, tree2, specific_files=['a', 'b/c']))

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
            return (file_id, (path, None), True, (True, False),
                    (entry.parent_id, None),
                    (entry.name, None), (entry.kind, None),
                    (entry.executable, None))
        expected_results = sorted([
            self.added(tree2, 'empty-root-id'),
            deleted('root-id'), deleted('a-id'),
            deleted('b-id'), deleted('c-id')])
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
        self.assertEqual([('a-id', ('a', 'a'), True, (True, True),
                           (root_id, root_id), ('a', 'a'),
                           ('file', 'file'), (False, False))],
                         self.do_iter_changes(tree1, tree2))

    def test_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        self.assertEqual([('c-id', ('b/c', 'b/c'), False, (True, True),
                           ('b-id', 'b-id'), ('c', 'c'), ('file', 'file'),
                          (False, True))],
                         self.do_iter_changes(tree1, tree2))

    def test_empty_dir(self):
        """an empty dir should not cause glitches to surrounding files."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        # the pathname is chosen to fall between 'a' and 'b'.
        self.build_tree(['1/a-empty/', '2/a-empty/'])
        tree1.add(['a-empty'], ['a-empty'])
        tree2.add(['a-empty'], ['a-empty'])
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        expected = []
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_file_rename(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_4(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', ('a', 'd'), False, (True, True),
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
        self.assertEqual([('a-id', ('a', 'd'), True, (True, True),
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
        self.assertEqual([('c-id', ('b/c', 'e'), False, (True, True),
                           ('b-id', root_id), ('c', 'e'), ('file', 'file'),
                           (False, True))],
                         self.do_iter_changes(tree1, tree2))

    def test_missing_in_target(self):
        """Test with the target files versioned but absent from disk."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        os.unlink('2/a')
        shutil.rmtree('2/b')
        # TODO ? have a symlink here?
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        expected = sorted([
            self.missing('a-id', 'a', 'a', root_id, 'file'),
            self.missing('b-id', 'b', 'b', root_id, 'directory'),
            self.missing('c-id', 'b/c', 'b/c', 'b-id', 'file'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_missing_and_renamed(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/file'])
        tree1.add(['file'], ['file-id'])
        self.build_tree(['tree2/directory/'])
        tree2.add(['directory'], ['file-id'])
        os.rmdir('tree2/directory')
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        root_id = tree1.path2id('')
        expected = sorted([
            self.missing('file-id', 'file', 'directory', root_id, 'file'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

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
        self.assertEqual(sorted([self.unchanged(tree1, root_id),
            self.unchanged(tree1, 'b-id'),
            ('a-id', ('a', 'd'), True, (True, True),
             (root_id, root_id), ('a', 'd'), ('file', 'file'),
            (False, False)), self.unchanged(tree1, 'c-id')]),
            self.do_iter_changes(tree1, tree2, include_unchanged=True))

    def test_compare_subtrees(self):
        """want_unchanged should generate a list of unchanged entries."""
        tree1 = self.make_branch_and_tree('1')
        if not tree1.supports_tree_reference():
            raise tests.TestSkipped('Tree %s does not support references'
                % (tree1,))
        tree1.set_root_id('root-id')
        subtree1 = self.make_branch_and_tree('1/sub')
        subtree1.set_root_id('subtree-id')
        tree1.add_reference(subtree1)

        tree2 = self.make_to_branch_and_tree('2')
        if not tree2.supports_tree_reference():
            raise tests.TestSkipped('Tree %s does not support references'
                % (tree2,))
        tree2.set_root_id('root-id')
        subtree2 = self.make_to_branch_and_tree('2/sub')
        subtree2.set_root_id('subtree-id')
        tree2.add_reference(subtree2)
        tree1.lock_read()
        tree2.lock_read()
        try:
            self.assertEqual([], list(tree2._iter_changes(tree1)))
            subtree1.commit('commit', rev_id='commit-a')
            self.assertEqual([
                ('root-id',
                 (u'', u''),
                 False,
                 (True, True),
                 (None, None),
                 (u'', u''),
                 ('directory', 'directory'),
                 (False, False)),
                ('subtree-id',
                 ('sub', 'sub',),
                 False,
                 (True, True),
                 ('root-id', 'root-id'),
                 ('sub', 'sub'),
                 ('tree-reference', 'tree-reference'),
                 (False, False))],
                             list(tree2._iter_changes(tree1,
                                 include_unchanged=True)))
        finally:
            tree1.unlock()
            tree2.unlock()

    def test_default_ignores_unversioned_files(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/a', 'tree1/c',
                         'tree2/a', 'tree2/b', 'tree2/c'])
        tree1.add(['a', 'c'], ['a-id', 'c-id'])
        tree2.add(['a', 'c'], ['a-id', 'c-id'])

        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)

        # We should ignore the fact that 'b' exists in tree-2
        # because the want_unversioned parameter was not given.
        expected = sorted([
            self.content_changed(tree2, 'a-id'),
            self.content_changed(tree2, 'c-id'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_unversioned_paths_in_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file', 'tree2/dir/'])
        # try:
        os.symlink('target', 'tree2/link')
        links_supported = True
        # except ???:
        #   links_supported = False
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = [
            self.unversioned(tree2, 'file'),
            self.unversioned(tree2, 'dir'),
            ]
        if links_supported:
            expected.append(self.unversioned(tree2, 'link'))
        expected = sorted(expected)
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            want_unversioned=True))

    def test_unversioned_paths_in_tree_specific_files(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        self.build_tree(['tree2/file', 'tree2/dir/'])
        # try:
        os.symlink('target', 'tree2/link')
        links_supported = True
        # except ???:
        #   links_supported = False
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = [
            self.unversioned(tree2, 'file'),
            self.unversioned(tree2, 'dir'),
            ]
        specific_files=['file', 'dir']
        if links_supported:
            expected.append(self.unversioned(tree2, 'link'))
            specific_files.append('link')
        expected = sorted(expected)
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            specific_files=specific_files, require_versioned=False,
            want_unversioned=True))

    def test_unversioned_paths_in_target_matching_source_old_names(self):
        # its likely that naive implementations of unversioned file support
        # will fail if the path was versioned, but is not any more, 
        # due to a rename, not due to unversioning it.
        # That is, if the old tree has a versioned file 'foo', and
        # the new tree has the same file but versioned as 'bar', and also
        # has an unknown file 'foo', we should get back output for
        # both foo and bar.
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file', 'tree2/dir/',
            'tree1/file', 'tree2/movedfile',
            'tree1/dir/', 'tree2/moveddir/'])
        # try:
        os.symlink('target', 'tree1/link')
        os.symlink('target', 'tree2/link')
        os.symlink('target', 'tree2/movedlink')
        links_supported = True
        # except ???:
        #   links_supported = False
        tree1.add(['file', 'dir', 'link'], ['file-id', 'dir-id', 'link-id'])
        tree2.add(['movedfile', 'moveddir', 'movedlink'],
            ['file-id', 'dir-id', 'link-id'])
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = [
            self.renamed(tree1, tree2, 'dir-id', False),
            self.renamed(tree1, tree2, 'file-id', True),
            self.unversioned(tree2, 'file'),
            self.unversioned(tree2, 'dir'),
            ]
        specific_files=['file', 'dir']
        if links_supported:
            expected.append(self.renamed(tree1, tree2, 'link-id', False))
            expected.append(self.unversioned(tree2, 'link'))
            specific_files.append('link')
        expected = sorted(expected)
        # run once with, and once without specific files, to catch
        # potentially different code paths.
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            require_versioned=False,
            want_unversioned=True))
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            specific_files=specific_files, require_versioned=False,
            want_unversioned=True))

    def test_unversioned_subtree_only_emits_root(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/dir/', 'tree2/dir/file'])
        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        expected = [
            self.unversioned(tree2, 'dir'),
            ]
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            want_unversioned=True))

    def make_trees_with_symlinks(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/fromfile', 'tree1/fromdir/'])
        self.build_tree(['tree2/tofile', 'tree2/todir/', 'tree2/unknown'])
        # try:
        os.symlink('original', 'tree1/changed')
        os.symlink('original', 'tree1/removed')
        os.symlink('original', 'tree1/tofile')
        os.symlink('original', 'tree1/todir')
        # we make the unchanged link point at unknown to catch incorrect
        # symlink-following code in the specified_files test.
        os.symlink('unknown', 'tree1/unchanged')
        os.symlink('new',      'tree2/added')
        os.symlink('new',      'tree2/changed')
        os.symlink('new',      'tree2/fromfile')
        os.symlink('new',      'tree2/fromdir')
        os.symlink('unknown', 'tree2/unchanged')
        from_paths_and_ids = [
            'fromdir',
            'fromfile',
            'changed',
            'removed',
            'todir',
            'tofile',
            'unchanged',
            ]
        to_paths_and_ids = [
            'added',
            'fromdir',
            'fromfile',
            'changed',
            'todir',
            'tofile',
            'unchanged',
            ]
        tree1.add(from_paths_and_ids, from_paths_and_ids)
        tree2.add(to_paths_and_ids, to_paths_and_ids)
        # except ???:
        #   raise TestSkipped('OS does not support symlinks')
        #   links_supported = False
        return self.mutable_trees_to_test_trees(tree1, tree2)

    def make_trees_with_subtrees(self):
        # trees containing tree references
        # TODO: might have to skip if the format can't do tree references
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        self.build_tree(['tree1/fromdir/', 'tree1/common/',
            'tree2/todir/', 'tree2/common/'])
        # TODO: actually add the references
        return self.mutable_trees_to_test_trees(tree1, tree2)

    def test_versioned_symlinks(self):
        tree1, tree2 = self.make_trees_with_symlinks()
        root_id = tree1.path2id('')
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = [
            self.unchanged(tree1, tree1.path2id('')),
            self.added(tree2, 'added'),
            self.content_changed(tree2, 'changed'),
            self.kind_changed(tree1, tree2, 'fromdir'),
            self.kind_changed(tree1, tree2, 'fromfile'),
            self.deleted(tree1, 'removed'),
            self.unchanged(tree2, 'unchanged'),
            self.unversioned(tree2, 'unknown'),
            self.kind_changed(tree1, tree2, 'todir'),
            self.kind_changed(tree1, tree2, 'tofile'),
            ]
        expected = sorted(expected)
        self.assertEqual(expected,
            self.do_iter_changes(tree1, tree2, include_unchanged=True,
                want_unversioned=True))

    def test_versioned_symlinks_specific_files(self):
        tree1, tree2 = self.make_trees_with_symlinks()
        root_id = tree1.path2id('')
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = [
            self.added(tree2, 'added'),
            self.content_changed(tree2, 'changed'),
            self.kind_changed(tree1, tree2, 'fromdir'),
            self.kind_changed(tree1, tree2, 'fromfile'),
            self.deleted(tree1, 'removed'),
            self.kind_changed(tree1, tree2, 'todir'),
            self.kind_changed(tree1, tree2, 'tofile'),
            ]
        expected = sorted(expected)
        # we should get back just the changed links. We pass in 'unchanged' to
        # make sure that it is correctly not returned - and neither is the
        # unknown path 'unknown' which it points at.
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            specific_files=['added', 'changed', 'fromdir', 'fromfile',
            'removed', 'unchanged', 'todir', 'tofile']))

    def test_tree_with_special_names(self):
        tree1, tree2, paths, path_ids = self.make_tree_with_special_names()
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = sorted(self.added(tree2, f_id) for f_id in path_ids)
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_trees_with_special_names(self):
        tree1, tree2, paths, path_ids = self.make_trees_with_special_names()
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        expected = sorted(self.content_changed(tree2, f_id) for f_id in path_ids
                          if f_id.endswith('_f-id'))
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_trees_with_subtrees(self):
        tree1, tree2 = self.make_trees_with_subtrees()
        self.do_iter_changes(tree1, tree2)

    def test_trees_with_deleted_dir(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/a', 'tree1/b/', 'tree1/b/c',
                         'tree1/b/d/', 'tree1/b/d/e', 'tree1/f/', 'tree1/f/g',
                         'tree2/a', 'tree2/f/', 'tree2/f/g'])
        tree1.add(['a', 'b', 'b/c', 'b/d/', 'b/d/e', 'f', 'f/g'],
                  ['a-id', 'b-id', 'c-id', 'd-id', 'e-id', 'f-id', 'g-id'])
        tree2.add(['a', 'f', 'f/g'], ['a-id', 'f-id', 'g-id'])

        tree1, tree2 = self.mutable_trees_to_test_trees(tree1, tree2)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        # We should notice that 'b' and all its children are deleted
        expected = sorted([
            self.content_changed(tree2, 'a-id'),
            self.content_changed(tree2, 'g-id'),
            self.deleted(tree1, 'b-id'),
            self.deleted(tree1, 'c-id'),
            self.deleted(tree1, 'd-id'),
            self.deleted(tree1, 'e-id'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

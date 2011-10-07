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

"""Tests for Tree and InterTree."""

from bzrlib import (
    errors,
    revision,
    tree as _mod_tree,
    )
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tree import InterTree


class TestInterTree(TestCaseWithTransport):

    def test_revision_tree_revision_tree(self):
        # we should have an InterTree registered for RevisionTree to
        # RevisionTree.
        tree = self.make_branch_and_tree('.')
        rev_id = tree.commit('first post')
        rev_id2 = tree.commit('second post', allow_pointless=True)
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        rev_tree2 = tree.branch.repository.revision_tree(rev_id2)
        optimiser = InterTree.get(rev_tree, rev_tree2)
        self.assertIsInstance(optimiser, InterTree)
        optimiser = InterTree.get(rev_tree2, rev_tree)
        self.assertIsInstance(optimiser, InterTree)

    def test_working_tree_revision_tree(self):
        # we should have an InterTree available for WorkingTree to
        # RevisionTree.
        tree = self.make_branch_and_tree('.')
        rev_id = tree.commit('first post')
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        optimiser = InterTree.get(rev_tree, tree)
        self.assertIsInstance(optimiser, InterTree)
        optimiser = InterTree.get(tree, rev_tree)
        self.assertIsInstance(optimiser, InterTree)

    def test_working_tree_working_tree(self):
        # we should have an InterTree available for WorkingTree to
        # WorkingTree.
        tree = self.make_branch_and_tree('1')
        tree2 = self.make_branch_and_tree('2')
        optimiser = InterTree.get(tree, tree2)
        self.assertIsInstance(optimiser, InterTree)
        optimiser = InterTree.get(tree2, tree)
        self.assertIsInstance(optimiser, InterTree)


class RecordingOptimiser(InterTree):

    calls = []

    def compare(self, want_unchanged=False, specific_files=None,
        extra_trees=None, require_versioned=False, include_root=False,
        want_unversioned=False):
        self.calls.append(
            ('compare', self.source, self.target, want_unchanged,
             specific_files, extra_trees, require_versioned,
             include_root, want_unversioned)
            )

    @classmethod
    def is_compatible(klass, source, target):
        return True


class TestTree(TestCaseWithTransport):

    def test_compare_calls_InterTree_compare(self):
        """This test tests the way Tree.compare() uses InterTree."""
        old_optimisers = InterTree._optimisers
        try:
            InterTree._optimisers = []
            RecordingOptimiser.calls = []
            InterTree.register_optimiser(RecordingOptimiser)
            tree = self.make_branch_and_tree('1')
            tree2 = self.make_branch_and_tree('2')
            # do a series of calls:
            # trivial usage
            tree.changes_from(tree2)
            # pass in all optional arguments by position
            tree.changes_from(tree2, 'unchanged', 'specific', 'extra',
                              'require', True)
            # pass in all optional arguments by keyword
            tree.changes_from(tree2,
                specific_files='specific',
                want_unchanged='unchanged',
                extra_trees='extra',
                require_versioned='require',
                include_root=True,
                want_unversioned=True,
                )
        finally:
            InterTree._optimisers = old_optimisers
        self.assertEqual(
            [
             ('compare', tree2, tree, False, None, None, False, False, False),
             ('compare', tree2, tree, 'unchanged', 'specific', 'extra',
              'require', True, False),
             ('compare', tree2, tree, 'unchanged', 'specific', 'extra',
              'require', True, True),
            ], RecordingOptimiser.calls)

    def test_changes_from_with_root(self):
        """Ensure the include_root option does what's expected."""
        wt = self.make_branch_and_tree('.')
        delta = wt.changes_from(wt.basis_tree())
        self.assertEqual(len(delta.added), 0)
        delta = wt.changes_from(wt.basis_tree(), include_root=True)
        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0][0], '')

    def test_changes_from_with_require_versioned(self):
        """Ensure the require_versioned option does what's expected."""
        wt = self.make_branch_and_tree('.')
        self.build_tree(['known_file', 'unknown_file'])
        wt.add('known_file')

        self.assertRaises(errors.PathsNotVersionedError,
            wt.changes_from, wt.basis_tree(), wt, specific_files=['known_file',
            'unknown_file'], require_versioned=True)

        # we need to pass a known file with an unknown file to get this to
        # fail when expected.
        delta = wt.changes_from(wt.basis_tree(),
            specific_files=['known_file', 'unknown_file'] ,
            require_versioned=False)
        self.assertEqual(len(delta.added), 1)


class TestMultiWalker(TestCaseWithTransport):

    def assertStepOne(self, has_more, path, file_id, iterator):
        retval = _mod_tree.MultiWalker._step_one(iterator)
        if not has_more:
            self.assertIs(None, path)
            self.assertIs(None, file_id)
            self.assertEqual((False, None, None), retval)
        else:
            self.assertEqual((has_more, path, file_id),
                             (retval[0], retval[1], retval[2].file_id))

    def test__step_one_empty(self):
        tree = self.make_branch_and_tree('empty')
        repo = tree.branch.repository
        empty_tree = repo.revision_tree(revision.NULL_REVISION)

        iterator = empty_tree.iter_entries_by_dir()
        self.assertStepOne(False, None, None, iterator)
        self.assertStepOne(False, None, None, iterator)

    def test__step_one(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b/', 'tree/b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])

        iterator = tree.iter_entries_by_dir()
        tree.lock_read()
        self.addCleanup(tree.unlock)

        root_id = tree.path2id('')
        self.assertStepOne(True, '', root_id, iterator)
        self.assertStepOne(True, 'a', 'a-id', iterator)
        self.assertStepOne(True, 'b', 'b-id', iterator)
        self.assertStepOne(True, 'b/c', 'c-id', iterator)
        self.assertStepOne(False, None, None, iterator)
        self.assertStepOne(False, None, None, iterator)

    def assertWalkerNext(self, exp_path, exp_file_id, master_has_node,
                         exp_other_paths, iterator):
        """Check what happens when we step the iterator.

        :param path: The path for this entry
        :param file_id: The file_id for this entry
        :param master_has_node: Does the master tree have this entry?
        :param exp_other_paths: A list of other_path values.
        :param iterator: The iterator to step
        """
        path, file_id, master_ie, other_values = iterator.next()
        self.assertEqual((exp_path, exp_file_id), (path, file_id),
                         'Master entry did not match')
        if master_has_node:
            self.assertIsNot(None, master_ie, 'master should have an entry')
        else:
            self.assertIs(None, master_ie, 'master should not have an entry')
        self.assertEqual(len(exp_other_paths), len(other_values),
                            'Wrong number of other entries')
        other_paths = []
        other_file_ids = []
        for path, ie in other_values:
            other_paths.append(path)
            if ie is None:
                other_file_ids.append(None)
            else:
                other_file_ids.append(ie.file_id)

        exp_file_ids = []
        for path in exp_other_paths:
            if path is None:
                exp_file_ids.append(None)
            else:
                exp_file_ids.append(file_id)
        self.assertEqual(exp_other_paths, other_paths, "Other paths incorrect")
        self.assertEqual(exp_file_ids, other_file_ids,
                         "Other file_ids incorrect")

    def lock_and_get_basis_and_root_id(self, tree):
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)
        root_id = tree.path2id('')
        return basis_tree, root_id

    def test_simple_stepping(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b/', 'tree/b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])

        tree.commit('first', rev_id='first-rev-id')

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a'], iterator)
        self.assertWalkerNext(u'b', 'b-id', True, [u'b'], iterator)
        self.assertWalkerNext(u'b/c', 'c-id', True, [u'b/c'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_master_has_extra(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b/', 'tree/c', 'tree/d'])
        tree.add(['a', 'b', 'd'], ['a-id', 'b-id', 'd-id'])

        tree.commit('first', rev_id='first-rev-id')

        tree.add(['c'], ['c-id'])
        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a'], iterator)
        self.assertWalkerNext(u'b', 'b-id', True, [u'b'], iterator)
        self.assertWalkerNext(u'c', 'c-id', True, [None], iterator)
        self.assertWalkerNext(u'd', 'd-id', True, [u'd'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_master_renamed_to_earlier(self):
        """The record is still present, it just shows up early."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/c', 'tree/d'])
        tree.add(['a', 'c', 'd'], ['a-id', 'c-id', 'd-id'])
        tree.commit('first', rev_id='first-rev-id')
        tree.rename_one('d', 'b')

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a'], iterator)
        self.assertWalkerNext(u'b', 'd-id', True, [u'd'], iterator)
        self.assertWalkerNext(u'c', 'c-id', True, [u'c'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_master_renamed_to_later(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/d'])
        tree.add(['a', 'b', 'd'], ['a-id', 'b-id', 'd-id'])
        tree.commit('first', rev_id='first-rev-id')
        tree.rename_one('b', 'e')

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a'], iterator)
        self.assertWalkerNext(u'd', 'd-id', True, [u'd'], iterator)
        self.assertWalkerNext(u'e', 'b-id', True, [u'b'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_other_extra_in_middle(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/d'])
        tree.add(['a', 'b', 'd'], ['a-id', 'b-id', 'd-id'])
        tree.commit('first', rev_id='first-rev-id')
        tree.remove(['b'])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a'], iterator)
        self.assertWalkerNext(u'd', 'd-id', True, [u'd'], iterator)
        self.assertWalkerNext(u'b', 'b-id', False, [u'b'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_other_extra_at_end(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/d'])
        tree.add(['a', 'b', 'd'], ['a-id', 'b-id', 'd-id'])
        tree.commit('first', rev_id='first-rev-id')
        tree.remove(['d'])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a'], iterator)
        self.assertWalkerNext(u'b', 'b-id', True, [u'b'], iterator)
        self.assertWalkerNext(u'd', 'd-id', False, [u'd'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_others_extra_at_end(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/c', 'tree/d', 'tree/e'])
        tree.add(['a', 'b', 'c', 'd', 'e'],
                 ['a-id', 'b-id', 'c-id', 'd-id', 'e-id'])
        tree.commit('first', rev_id='first-rev-id')
        tree.remove(['e'])
        tree.commit('second', rev_id='second-rev-id')
        tree.remove(['d'])
        tree.commit('third', rev_id='third-rev-id')
        tree.remove(['c'])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        first_tree = tree.branch.repository.revision_tree('first-rev-id')
        second_tree = tree.branch.repository.revision_tree('second-rev-id')
        walker = _mod_tree.MultiWalker(tree, [basis_tree, first_tree,
                                              second_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u'', u'', u''], iterator)
        self.assertWalkerNext(u'a', 'a-id', True, [u'a', u'a', u'a'], iterator)
        self.assertWalkerNext(u'b', 'b-id', True, [u'b', u'b', u'b'], iterator)
        self.assertWalkerNext(u'c', 'c-id', False, [u'c', u'c', u'c'], iterator)
        self.assertWalkerNext(u'd', 'd-id', False, [None, u'd', u'd'], iterator)
        self.assertWalkerNext(u'e', 'e-id', False, [None, u'e', None], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def test_different_file_id_in_others(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/c/'])
        tree.add(['a', 'b', 'c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('first', rev_id='first-rev-id')

        tree.rename_one('b', 'c/d')
        self.build_tree(['tree/b'])
        tree.add(['b'], ['b2-id'])
        tree.commit('second', rev_id='second-rev-id')

        tree.rename_one('a', 'c/e')
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a2-id'])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        first_tree = tree.branch.repository.revision_tree('first-rev-id')
        walker = _mod_tree.MultiWalker(tree, [basis_tree, first_tree])

        iterator = walker.iter_all()
        self.assertWalkerNext(u'', root_id, True, [u'', u''], iterator)
        self.assertWalkerNext(u'a', 'a2-id', True, [None, None], iterator)
        self.assertWalkerNext(u'b', 'b2-id', True, [u'b', None], iterator)
        self.assertWalkerNext(u'c', 'c-id', True, [u'c', u'c'], iterator)
        self.assertWalkerNext(u'c/d', 'b-id', True, [u'c/d', u'b'], iterator)
        self.assertWalkerNext(u'c/e', 'a-id', True, [u'a', u'a'], iterator)
        self.assertRaises(StopIteration, iterator.next)

    def assertCmpByDirblock(self, cmp_val, path1, path2):
        self.assertEqual(cmp_val,
            _mod_tree.MultiWalker._cmp_path_by_dirblock(path1, path2))

    def test__cmp_path_by_dirblock(self):
        # We only support Unicode strings at this point
        self.assertRaises(TypeError,
            _mod_tree.MultiWalker._cmp_path_by_dirblock, '', 'b')
        self.assertCmpByDirblock(0, u'', u'')
        self.assertCmpByDirblock(0, u'a', u'a')
        self.assertCmpByDirblock(0, u'a/b', u'a/b')
        self.assertCmpByDirblock(0, u'a/b/c', u'a/b/c')
        self.assertCmpByDirblock(1, u'a-a', u'a')
        self.assertCmpByDirblock(-1, u'a-a', u'a/a')
        self.assertCmpByDirblock(-1, u'a=a', u'a/a')
        self.assertCmpByDirblock(1, u'a-a/a', u'a/a')
        self.assertCmpByDirblock(1, u'a=a/a', u'a/a')
        self.assertCmpByDirblock(1, u'a-a/a', u'a/a/a')
        self.assertCmpByDirblock(1, u'a=a/a', u'a/a/a')
        self.assertCmpByDirblock(1, u'a-a/a/a', u'a/a/a')
        self.assertCmpByDirblock(1, u'a=a/a/a', u'a/a/a')

    def assertPathToKey(self, expected, path):
        self.assertEqual(expected, _mod_tree.MultiWalker._path_to_key(path))

    def test__path_to_key(self):
        self.assertPathToKey(([u''], u''), u'')
        self.assertPathToKey(([u''], u'a'), u'a')
        self.assertPathToKey(([u'a'], u'b'), u'a/b')
        self.assertPathToKey(([u'a', u'b'], u'c'), u'a/b/c')

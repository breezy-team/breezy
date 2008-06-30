# Copyright (C) 2006, 2008 Canonical Ltd
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

"""Tests for Tree and InterTree."""

from bzrlib import (
    errors,
    revision,
    tests,
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
        delta = wt.changes_from(wt.basis_tree(), wt, include_root=True)
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
        delta = wt.changes_from(wt.basis_tree(), wt, 
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
        root_id = tree.path2id('')
        self.assertStepOne(True, '', root_id, iterator)
        self.assertStepOne(True, 'a', 'a-id', iterator)
        self.assertStepOne(True, 'b', 'b-id', iterator)
        self.assertStepOne(True, 'b/c', 'c-id', iterator)
        self.assertStepOne(False, None, None, iterator)
        self.assertStepOne(False, None, None, iterator)

    def test_simple_stepping(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b/', 'tree/b/c'])
        tree.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])

        tree.commit('first', rev_id='first-rev-id')
        basis_tree = tree.basis_tree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)

        walker = _mod_tree.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        master_path, file_id, master_ie, other_values = iterator.next()
        root_id = tree.path2id('')
        self.assertEqual('', master_path)
        self.assertEqual(root_id, file_id)
        self.assertEqual(1, len(other_values))
        other_path, other_ie = other_values[0]
        self.assertEqual('', other_path)
        self.assertEqual(root_id, other_ie.file_id)

        master_path, file_id, master_ie, other_values = iterator.next()
        self.assertEqual(u'a', master_path)
        self.assertEqual('a-id', file_id)
        self.assertEqual(1, len(other_values))
        other_path, other_ie = other_values[0]
        self.assertEqual(u'a', other_path)
        self.assertEqual('a-id', other_ie.file_id)

        master_path, file_id, master_ie, other_values = iterator.next()
        self.assertEqual(u'b', master_path)
        self.assertEqual('b-id', file_id)
        self.assertEqual(1, len(other_values))
        other_path, other_ie = other_values[0]
        self.assertEqual(u'b', other_path)
        self.assertEqual('b-id', other_ie.file_id)

        master_path, file_id, master_ie, other_values = iterator.next()
        self.assertEqual(u'b/c', master_path)
        self.assertEqual('c-id', file_id)
        self.assertEqual(1, len(other_values))
        other_path, other_ie = other_values[0]
        self.assertEqual(u'b/c', other_path)
        self.assertEqual('c-id', other_ie.file_id)

        self.assertRaises(StopIteration, iterator.next)

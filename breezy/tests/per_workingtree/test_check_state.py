# Copyright (C) 2011 Canonical Ltd
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

"""Tests for WorkingTree.check_state."""

from breezy import (
    errors,
    tests,
    )
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestCaseWithState(TestCaseWithWorkingTree):

    def make_tree_with_broken_dirstate(self, path):
        tree = self.make_branch_and_tree(path)
        self.break_dirstate(tree)
        return tree

    def break_dirstate(self, tree, completely=False):
        """Write garbage into the dirstate file."""
        if getattr(tree, 'current_dirstate', None) is None:
            raise tests.TestNotApplicable(
                'Only applies to dirstate-based trees')
        tree.lock_read()
        try:
            dirstate = tree.current_dirstate()
            dirstate_path = dirstate._filename
            self.assertPathExists(dirstate_path)
        finally:
            tree.unlock()
        # We have to have the tree unlocked at this point, so we can safely
        # mutate the state file on all platforms.
        if completely:
            f = open(dirstate_path, 'wb')
        else:
            f = open(dirstate_path, 'ab')
        try:
            f.write(b'garbage-at-end-of-file\n')
        finally:
            f.close()


class TestCheckState(TestCaseWithState):

    def test_check_state(self):
        tree = self.make_branch_and_tree('tree')
        # Everything should be fine with an unmodified tree, no exception
        # should be raised.
        tree.check_state()

    def test_check_broken_dirstate(self):
        tree = self.make_tree_with_broken_dirstate('tree')
        self.assertRaises(errors.BzrError, tree.check_state)


class TestResetState(TestCaseWithState):

    def make_initial_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo', 'tree/dir/', 'tree/dir/bar'])
        tree.add(['foo', 'dir', 'dir/bar'])
        tree.commit('initial')
        return tree

    def test_reset_state_forgets_changes(self):
        tree = self.make_initial_tree()
        tree.rename_one('foo', 'baz')
        self.assertFalse(tree.is_versioned('foo'))
        if tree.supports_rename_tracking() and tree.supports_file_ids:
            foo_id = tree.basis_tree().path2id('foo')
            self.assertEqual(foo_id, tree.path2id('baz'))
        else:
            self.assertTrue(tree.is_versioned('baz'))
        tree.reset_state()
        # After reset, we should have forgotten about the rename, but we won't
        # have
        if tree.supports_file_ids:
            self.assertEqual(foo_id, tree.path2id('foo'))
            self.assertEqual(None, tree.path2id('baz'))
        self.assertPathDoesNotExist('tree/foo')
        self.assertPathExists('tree/baz')

    def test_reset_state_handles_corrupted_dirstate(self):
        tree = self.make_initial_tree()
        rev_id = tree.last_revision()
        self.break_dirstate(tree)
        tree.reset_state()
        tree.check_state()
        self.assertEqual(rev_id, tree.last_revision())

    def test_reset_state_handles_destroyed_dirstate(self):
        # If you pass the revision_id, we can handle a completely destroyed
        # dirstate file.
        tree = self.make_initial_tree()
        rev_id = tree.last_revision()
        self.break_dirstate(tree, completely=True)
        tree.reset_state(revision_ids=[rev_id])
        tree.check_state()
        self.assertEqual(rev_id, tree.last_revision())

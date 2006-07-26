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

"""Tests for Tree and InterTree."""

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

    def compare(self, specific_files=None):
        self.calls.append(('compare', specific_files))
    
    @classmethod
    def is_compatible(klass, source, target):
        return True


class TestTree(TestCaseWithTransport):

    def test_compare_calls_InterTree_compare(self):
        old_optimisers = InterTree._optimisers
        try:
            InterTree._optimisers = set()
            RecordingOptimiser.calls = []
            InterTree.register_optimiser(RecordingOptimiser)
            tree = self.make_branch_and_tree('1')
            tree2 = self.make_branch_and_tree('2')
            # do a series of calls:
            # trivial usage
            tree.compare(tree2)
            # pass in all optional arguments by position
            tree.compare(tree2, 'specific')
            # pass in all optional arguments by keyword
            tree.compare(tree2, specific_files='specific')
        finally:
            InterTree._optimisers = old_optimisers
        self.assertEqual(
            [
             ('compare', None),
             ('compare', 'specific'),
             ('compare', 'specific'),
            ], RecordingOptimiser.calls)

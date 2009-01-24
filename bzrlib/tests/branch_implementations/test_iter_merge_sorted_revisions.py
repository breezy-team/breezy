# Copyright (C) 2007 Canonical Ltd
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

"""Tests for Branch.iter_merge_sorted_revisions()"""

from bzrlib import (
    errors,
    revision,
    )

from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestIterMergeSortedRevisions(TestCaseWithBranch):

    def test_merge_sorted(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-3', 0, (3,), False),
            ('rev-1.1.1', 1, (1,1,1), True),
            ('rev-2', 0, (2,), False),
            ('rev-1', 0, (1,), True),
            ], list(the_branch.iter_merge_sorted_revisions()))

    def test_merge_sorted_range(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-1.1.1', 1, (1,1,1), True),
            ('rev-2', 0, (2,), False),
            ], list(the_branch.iter_merge_sorted_revisions(
                start_revision_id='rev-1.1.1', stop_revision_id='rev-2')))

    def test_merge_sorted_range_start_only(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-1.1.1', 1, (1,1,1), True),
            ('rev-2', 0, (2,), False),
            ('rev-1', 0, (1,), True),
            ], list(the_branch.iter_merge_sorted_revisions(
                start_revision_id='rev-1.1.1')))

    def test_merge_sorted_range_stop_only(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-3', 0, (3,), False),
            ('rev-1.1.1', 1, (1,1,1), True),
            ('rev-2', 0, (2,), False),
            ], list(the_branch.iter_merge_sorted_revisions(
                stop_revision_id='rev-2')))

    def test_merge_sorted_forward(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-1', 0, (1,), True),
            ('rev-2', 0, (2,), False),
            ('rev-1.1.1', 1, (1,1,1), True),
            ('rev-3', 0, (3,), False),
            ], list(the_branch.iter_merge_sorted_revisions(
                direction='forward')))

    def test_merge_sorted_range_forward(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-2', 0, (2,), False),
            ('rev-1.1.1', 1, (1,1,1), True),
            ], list(the_branch.iter_merge_sorted_revisions(
                start_revision_id='rev-1.1.1', stop_revision_id='rev-2',
                direction='forward')))

    def test_merge_sorted_range_start_only_forward(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-1', 0, (1,), True),
            ('rev-2', 0, (2,), False),
            ('rev-1.1.1', 1, (1,1,1), True),
            ], list(the_branch.iter_merge_sorted_revisions(
                start_revision_id='rev-1.1.1', direction='forward')))

    def test_merge_sorted_range_stop_only_forward(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.bzrdir.open_branch()
        self.assertEqual([
            ('rev-2', 0, (2,), False),
            ('rev-1.1.1', 1, (1,1,1), True),
            ('rev-3', 0, (3,), False),
            ], list(the_branch.iter_merge_sorted_revisions(
                stop_revision_id='rev-2', direction='forward')))

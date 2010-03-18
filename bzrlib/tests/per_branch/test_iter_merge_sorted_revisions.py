# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Tests for Branch.iter_merge_sorted_revisions()"""

from bzrlib import (
    errors,
    revision,
    )

from bzrlib.tests.per_branch import TestCaseWithBranch


class TestIterMergeSortedRevisions(TestCaseWithBranch):

    def setUp(self):
        super(TestIterMergeSortedRevisions, self).setUp()
        tree = self.create_tree_with_merge()
        self.branch = tree.bzrdir.open_branch()

    def assertRevisions(self, expected, *args, **kwargs):
        self.assertEqual(expected,
                         list(self.branch.iter_merge_sorted_revisions(
                    *args, **kwargs)))

    def test_merge_sorted(self):
        self.assertRevisions([('rev-3', 0, (3,), False),
                              ('rev-1.1.1', 1, (1,1,1), True),
                              ('rev-2', 0, (2,), False),
                              ('rev-1', 0, (1,), True),])

    def test_merge_sorted_range(self):
        self.assertRevisions(
            [('rev-1.1.1', 1, (1,1,1), True),
             ('rev-2', 0, (2,), False),],
            start_revision_id='rev-1.1.1', stop_revision_id='rev-1')

    def test_merge_sorted_range_start_only(self):
        self.assertRevisions(
            [('rev-1.1.1', 1, (1,1,1), True),
             ('rev-2', 0, (2,), False),
             ('rev-1', 0, (1,), True),],
            start_revision_id='rev-1.1.1')

    def test_merge_sorted_range_stop_exclude(self):
        self.assertRevisions(
            [('rev-3', 0, (3,), False),
             ('rev-1.1.1', 1, (1,1,1), True),
             ('rev-2', 0, (2,), False),],
            stop_revision_id='rev-1')

    def test_merge_sorted_range_stop_include(self):
        self.assertRevisions(
            [('rev-3', 0, (3,), False),
             ('rev-1.1.1', 1, (1,1,1), True),
             ('rev-2', 0, (2,), False),],
            stop_revision_id='rev-2', stop_rule='include')

    def test_merge_sorted_range_stop_with_merges(self):
        self.assertRevisions(
            [('rev-3', 0, (3,), False),
             ('rev-1.1.1', 1, (1,1,1), True),],
            stop_revision_id='rev-3', stop_rule='with-merges')

    def test_merge_sorted_range_stop_with_merges_can_show_non_parents(self):
        # rev-1.1.1 gets logged before the end revision is reached.
        # so it is returned even though rev-1.1.1 is not a parent of rev-2.
        self.assertRevisions(
            [('rev-3', 0, (3,), False),
             ('rev-1.1.1', 1, (1,1,1), True),
             ('rev-2', 0, (2,), False),],
            stop_revision_id='rev-2', stop_rule='with-merges')

    def test_merge_sorted_range_stop_with_merges_ignore_non_parents(self):
        # rev-2 is not a parent of rev-1.1.1 so it must not be returned
        self.assertRevisions(
            [('rev-3', 0, (3,), False),
             ('rev-1.1.1', 1, (1,1,1), True),],
            stop_revision_id='rev-1.1.1', stop_rule='with-merges')

    def test_merge_sorted_single_stop_exclude(self):
        # from X..X exclusive is an empty result
        self.assertRevisions(
            [],
            start_revision_id='rev-3', stop_revision_id='rev-3')

    def test_merge_sorted_single_stop_include(self):
        # from X..X inclusive is [X]
        self.assertRevisions(
            [('rev-3', 0, (3,), False),],
            start_revision_id='rev-3', stop_revision_id='rev-3',
            stop_rule='include')

    def test_merge_sorted_single_stop_with_merges(self):
        self.assertRevisions(
            [('rev-3', 0, (3,), False),
             ('rev-1.1.1', 1, (1,1,1), True),],
            start_revision_id='rev-3', stop_revision_id='rev-3',
            stop_rule='with-merges')

    def test_merge_sorted_forward(self):
        self.assertRevisions(
            [('rev-1', 0, (1,), True),
             ('rev-2', 0, (2,), False),
             ('rev-1.1.1', 1, (1,1,1), True),
             ('rev-3', 0, (3,), False),],
            direction='forward')

    def test_merge_sorted_range_forward(self):
        self.assertRevisions(
            [('rev-2', 0, (2,), False),
             ('rev-1.1.1', 1, (1,1,1), True),],
            start_revision_id='rev-1.1.1', stop_revision_id='rev-1',
            direction='forward')

    def test_merge_sorted_range_start_only_forward(self):
        self.assertRevisions(
            [('rev-1', 0, (1,), True),
             ('rev-2', 0, (2,), False),
             ('rev-1.1.1', 1, (1,1,1), True),],
            start_revision_id='rev-1.1.1', direction='forward')

    def test_merge_sorted_range_stop_exclude_forward(self):
        self.assertRevisions(
            [('rev-2', 0, (2,), False),
             ('rev-1.1.1', 1, (1,1,1), True),
             ('rev-3', 0, (3,), False),],
            stop_revision_id='rev-1', direction='forward')

    def test_merge_sorted_range_stop_include_forward(self):
        self.assertRevisions(
            [('rev-2', 0, (2,), False),
             ('rev-1.1.1', 1, (1,1,1), True),
             ('rev-3', 0, (3,), False),],
            stop_revision_id='rev-2', stop_rule='include', direction='forward')

    def test_merge_sorted_range_stop_with_merges_forward(self):
        self.assertRevisions(
            [('rev-1.1.1', 1, (1,1,1), True),
             ('rev-3', 0, (3,), False),],
            stop_revision_id='rev-3', stop_rule='with-merges',
            direction='forward')

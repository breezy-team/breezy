# Copyright (C) 2011 by Canonical Ltd
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

from bzrlib import (
    tests,
    )
from bzrlib.plugins.changelog_merge import changelog_merge


sample_base_entries = [
    'Base entry B1',
    'Base entry B2',
    'Base entry B3',
    ]

sample_this_entries = [
    'This entry T1',
    'This entry T2',
    #'Base entry B1 updated',
    'Base entry B1',
    'Base entry B2',
    'Base entry B3',
    ]

sample_other_entries = [
    'Other entry O1',
    #'Base entry B1',
    'Base entry B1',
    'Base entry B2 updated',
    'Base entry B3',
    ]


sample2_base_entries = [
    'Base entry B1',
    'Base entry B2',
    'Base entry B3',
    ]

sample2_this_entries = [
    'This entry T1',
    'This entry T2',
    #'Base entry B1 updated',
    'Base entry B1',
    'Base entry B2',
    ]

sample2_other_entries = [
    'Other entry O1',
    #'Base entry B1',
    'Base entry B1 edit',  # > 80% similar according to difflib
    'Base entry B2',
    ]


class TestMergeCoreLogic(tests.TestCase):

    def test_new_in_other_floats_to_top(self):
        """Changes at the top of 'other' float to the top.

        Given a changelog in THIS containing::

          NEW-1
          OLD-1

        and a changelog in OTHER containing::

          NEW-2
          OLD-1

        it will merge as::

          NEW-2
          NEW-1
          OLD-1
        """
        base_entries = ['OLD-1']
        this_entries = ['NEW-1', 'OLD-1']
        other_entries = ['NEW-2', 'OLD-1']
        result_entries = changelog_merge.merge_entries(
            base_entries, this_entries, other_entries)
        self.assertEqual(
            ['NEW-2', 'NEW-1', 'OLD-1'], result_entries)

    def test_acceptance_bug_723968(self):
        """Merging a branch that:

         1. adds a new entry, and
         2. edits an old entry (e.g. to fix a typo or twiddle formatting)

        will:

         1. add the new entry to the top
         2. keep the edit, without duplicating the edited entry or moving it.
        """
        result_entries = changelog_merge.merge_entries(
            sample_base_entries, sample_this_entries, sample_other_entries)
        self.assertEqual([
            'Other entry O1',
            'This entry T1',
            'This entry T2',
            'Base entry B1',
            'Base entry B2 updated',
            'Base entry B3',
            ],
            list(result_entries))

    def test_more_complex_conflict(self):
        """Like test_acceptance_bug_723968, but with a more difficult conflict:
        the new entry and the edited entry are adjacent.
        """
        def guess_edits(new, deleted):
            #import pdb; pdb.set_trace()
            return changelog_merge.default_guess_edits(new, deleted,
                    entry_as_str=lambda x: x)
        result_entries = changelog_merge.merge_entries(
            sample2_base_entries, sample2_this_entries, sample2_other_entries,
            guess_edits=guess_edits)
        self.assertEqual([
            'Other entry O1',
            'This entry T1',
            'This entry T2',
            'Base entry B1 edit',
            'Base entry B2',
            ],
            list(result_entries))


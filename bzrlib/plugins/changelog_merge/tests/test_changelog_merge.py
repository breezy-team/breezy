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
    merge,
    tests,
    )
from bzrlib.tests import test_merge_core
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

    def test_too_hard(self):
        """A conflict this plugin cannot resolve raises EntryConflict.
        """
        # An entry edited in other but deleted in this is a conflict we can't
        # resolve.  (Ideally perhaps we'd generate a nice conflict file, but
        # for now we just give up.)
        self.assertRaises(changelog_merge.EntryConflict,
            changelog_merge.merge_entries,
            sample2_base_entries, [], sample2_other_entries)

    def test_default_guess_edits(self):
        """default_guess_edits matches a new entry only once.
        
        (Even when that entry is the best match for multiple old entries.)
        """
        new_in_other = [('AAAAA',), ('BBBBB',)]
        deleted_in_other = [('DDDDD',), ('BBBBBx',), ('BBBBBxx',)]
        # BBBBB is the best match for both BBBBBx and BBBBBxx
        result = changelog_merge.default_guess_edits(
            new_in_other, deleted_in_other)
        self.assertEqual(
            ([('AAAAA',)], # new
             [('DDDDD',), ('BBBBBxx',)], # deleted
             [(('BBBBBx',), ('BBBBB',))]), # edits
            result)


class TestChangeLogMerger(tests.TestCaseWithTransport):
    """Tests for ChangeLogMerger class.
    
    Most tests should be unit tests for merge_entries (and its helpers).
    This class is just to cover the handful of lines of code in ChangeLogMerger
    itself.
    """

    def make_builder(self):
        builder = test_merge_core.MergeBuilder(self.test_base_dir)
        self.addCleanup(builder.cleanup)
        return builder

    def make_changelog_merger(self, base_text, this_text, other_text):
        builder = self.make_builder()
        builder.add_file('clog-id', builder.tree_root, 'ChangeLog',
            base_text, True)
        builder.change_contents('clog-id', other=other_text, this=this_text)
        merger = builder.make_merger(merge.Merge3Merger, ['clog-id'])
        # The following can't use config stacks until the plugin itself does
        # ('this_branch' is already write locked at this point and as such
        # won't write the new value to disk where get_user_option can get it).
        merger.this_branch.get_config().set_user_option(
            'changelog_merge_files', 'ChangeLog')
        merge_hook_params = merge.MergeFileHookParams(merger, 'clog-id', None,
            'file', 'file', 'conflict')
        changelog_merger = changelog_merge.ChangeLogMerger(merger)
        return changelog_merger, merge_hook_params

    def test_merge_text_returns_not_applicable(self):
        """A conflict this plugin cannot resolve returns (not_applicable, None).
        """
        # Build same example as TestMergeCoreLogic.test_too_hard: edit an entry
        # in other but delete it in this.
        def entries_as_str(entries):
            return ''.join(entry + '\n' for entry in entries)
        changelog_merger, merge_hook_params = self.make_changelog_merger(
            entries_as_str(sample2_base_entries),
            '',
            entries_as_str(sample2_other_entries))
        self.assertEqual(
            ('not_applicable', None),
            changelog_merger.merge_contents(merge_hook_params))

    def test_merge_text_returns_success(self):
        """A successful merge returns ('success', lines)."""
        changelog_merger, merge_hook_params = self.make_changelog_merger(
            '', 'this text\n', 'other text\n')
        status, lines = changelog_merger.merge_contents(merge_hook_params)
        self.assertEqual(
            ('success', ['other text\n', 'this text\n']),
            (status, list(lines)))


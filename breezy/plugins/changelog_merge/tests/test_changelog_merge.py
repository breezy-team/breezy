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

from breezy import merge, tests
from breezy.plugins.changelog_merge import changelog_merge
from breezy.tests import test_merge_core

sample_base_entries = [
    b"Base entry B1",
    b"Base entry B2",
    b"Base entry B3",
]

sample_this_entries = [
    b"This entry T1",
    b"This entry T2",
    #'Base entry B1 updated',
    b"Base entry B1",
    b"Base entry B2",
    b"Base entry B3",
]

sample_other_entries = [
    b"Other entry O1",
    #'Base entry B1',
    b"Base entry B1",
    b"Base entry B2 updated",
    b"Base entry B3",
]


sample2_base_entries = [
    b"Base entry B1",
    b"Base entry B2",
    b"Base entry B3",
]

sample2_this_entries = [
    b"This entry T1",
    b"This entry T2",
    #'Base entry B1 updated',
    b"Base entry B1",
    b"Base entry B2",
]

sample2_other_entries = [
    b"Other entry O1",
    #'Base entry B1',
    b"Base entry B1 edit",  # > 80% similar according to difflib
    b"Base entry B2",
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
        base_entries = [b"OLD-1"]
        this_entries = [b"NEW-1", b"OLD-1"]
        other_entries = [b"NEW-2", b"OLD-1"]
        result_entries = changelog_merge.merge_entries(
            base_entries, this_entries, other_entries
        )
        self.assertEqual([b"NEW-2", b"NEW-1", b"OLD-1"], result_entries)

    def test_acceptance_bug_723968(self):
        """Acceptance test for bug 723968.

        Merging a branch that:

         1. adds a new entry, and
         2. edits an old entry (e.g. to fix a typo or twiddle formatting)

        will:

         1. add the new entry to the top
         2. keep the edit, without duplicating the edited entry or moving it.
        """
        result_entries = changelog_merge.merge_entries(
            sample_base_entries, sample_this_entries, sample_other_entries
        )
        self.assertEqual(
            [
                b"Other entry O1",
                b"This entry T1",
                b"This entry T2",
                b"Base entry B1",
                b"Base entry B2 updated",
                b"Base entry B3",
            ],
            list(result_entries),
        )

    def test_more_complex_conflict(self):
        """Like test_acceptance_bug_723968, but with a more difficult conflict:
        the new entry and the edited entry are adjacent.
        """

        def guess_edits(new, deleted):
            # import pdb; pdb.set_trace()
            return changelog_merge.default_guess_edits(
                new, deleted, entry_as_str=lambda x: x
            )

        result_entries = changelog_merge.merge_entries(
            sample2_base_entries,
            sample2_this_entries,
            sample2_other_entries,
            guess_edits=guess_edits,
        )
        self.assertEqual(
            [
                b"Other entry O1",
                b"This entry T1",
                b"This entry T2",
                b"Base entry B1 edit",
                b"Base entry B2",
            ],
            list(result_entries),
        )

    def test_too_hard(self):
        """A conflict this plugin cannot resolve raises EntryConflict."""
        # An entry edited in other but deleted in this is a conflict we can't
        # resolve.  (Ideally perhaps we'd generate a nice conflict file, but
        # for now we just give up.)
        self.assertRaises(
            changelog_merge.EntryConflict,
            changelog_merge.merge_entries,
            [(entry,) for entry in sample2_base_entries],
            [],
            [(entry,) for entry in sample2_other_entries],
        )

    def test_default_guess_edits(self):
        """default_guess_edits matches a new entry only once.

        (Even when that entry is the best match for multiple old entries.)
        """
        new_in_other = [(b"AAAAA",), (b"BBBBB",)]
        deleted_in_other = [(b"DDDDD",), (b"BBBBBx",), (b"BBBBBxx",)]
        # BBBBB is the best match for both BBBBBx and BBBBBxx
        result = changelog_merge.default_guess_edits(new_in_other, deleted_in_other)
        self.assertEqual(
            (
                [(b"AAAAA",)],  # new
                [(b"DDDDD",), (b"BBBBBxx",)],  # deleted
                [((b"BBBBBx",), (b"BBBBB",))],
            ),  # edits
            result,
        )


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
        clog = builder.add_file(
            builder.root(), "ChangeLog", base_text, True, file_id=b"clog-id"
        )
        builder.change_contents(clog, other=other_text, this=this_text)
        merger = builder.make_merger(merge.Merge3Merger, ["ChangeLog"])
        # The following can't use config stacks until the plugin itself does
        # ('this_branch' is already write locked at this point and as such
        # won't write the new value to disk where get_user_option can get it).
        merger.this_branch.get_config().set_user_option(
            "changelog_merge_files", "ChangeLog"
        )
        merge_hook_params = merge.MergeFileHookParams(
            merger,
            ["ChangeLog", "ChangeLog", "ChangeLog"],
            None,
            "file",
            "file",
            "conflict",
        )
        changelog_merger = changelog_merge.ChangeLogMerger(merger)
        return changelog_merger, merge_hook_params

    def test_merge_text_returns_not_applicable(self):
        """A conflict this plugin cannot resolve returns (not_applicable, None)."""

        # Build same example as TestMergeCoreLogic.test_too_hard: edit an entry
        # in other but delete it in this.
        def entries_as_str(entries):
            return b"".join(entry + b"\n" for entry in entries)

        changelog_merger, merge_hook_params = self.make_changelog_merger(
            entries_as_str(sample2_base_entries),
            b"",
            entries_as_str(sample2_other_entries),
        )
        self.assertEqual(
            ("not_applicable", None), changelog_merger.merge_contents(merge_hook_params)
        )

    def test_merge_text_returns_success(self):
        """A successful merge returns ('success', lines)."""
        changelog_merger, merge_hook_params = self.make_changelog_merger(
            b"", b"this text\n", b"other text\n"
        )
        status, lines = changelog_merger.merge_contents(merge_hook_params)
        self.assertEqual(
            ("success", [b"other text\n", b"this text\n"]), (status, list(lines))
        )

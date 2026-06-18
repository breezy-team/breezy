# Copyright (C) 2010 Canonical Ltd
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

"""Merge logic for changelog_merge plugin."""

import difflib

import patiencediff
from merge3 import Merge3

from ... import debug, merge, osutils
from ...trace import mutter


def changelog_entries(lines):
    """Return a list of changelog entries.

    :param lines: lines of a changelog file.
    :returns: list of entries.  Each entry is a tuple of lines.
    """
    entries = []
    for line in lines:
        if line[0] not in (" ", "\t", "\n"):
            # new entry
            entries.append([line])
        else:
            try:
                entry = entries[-1]
            except IndexError:
                # Cope with leading blank lines.
                entries.append([])
                entry = entries[-1]
            entry.append(line)
    return list(map(tuple, entries))


def entries_to_lines(entries):
    """Turn a list of entries into a flat iterable of lines."""
    for entry in entries:
        yield from entry


class ChangeLogMerger(merge.ConfigurableFileMerger):
    """Merge GNU-format ChangeLog files."""

    name_prefix = "changelog"

    def file_matches(self, params):
        """Check if a file should be merged using the changelog merger.

        Args:
            params: Parameters containing file paths to check.

        Returns:
            True if the file should be handled by this merger, False otherwise.
        """
        affected_files = self.affected_files
        if affected_files is None:
            config = self.merger.this_branch.get_config()
            # Until bzr provides a better policy for caching the config, we
            # just add the part we're interested in to the params to avoid
            # reading the config files repeatedly (breezy.conf, location.conf,
            # branch.conf).
            config_key = self.name_prefix + "_merge_files"
            affected_files = config.get_user_option_as_list(config_key)
            if affected_files is None:
                # If nothing was specified in the config, use the default.
                affected_files = self.default_files
            self.affected_files = affected_files
        if affected_files:
            filepath = osutils.basename(params.this_path)
            if filepath in affected_files:
                return True
        return False

    def merge_text(self, params):
        """Merge changelog changes.

        * new entries from other will float to the top
        * edits to older entries are preserved
        """
        # Transform files into lists of changelog entries
        this_entries = changelog_entries(params.this_lines)
        other_entries = changelog_entries(params.other_lines)
        base_entries = changelog_entries(params.base_lines)
        try:
            result_entries = merge_entries(base_entries, this_entries, other_entries)
        except EntryConflict:
            # XXX: generating a nice conflict file would be better
            return "not_applicable", None
        # Transform the merged elements back into real blocks of lines.
        return "success", entries_to_lines(result_entries)


class EntryConflict(Exception):
    """Raised when changelog entries cannot be merged automatically."""

    pass


def default_guess_edits(new_entries, deleted_entries, entry_as_str=b"".join):
    """Default implementation of guess_edits param of merge_entries.

    This algorithm does O(N^2 * logN) SequenceMatcher.ratio() calls, which is
    pretty bad, but it shouldn't be used very often.
    """
    deleted_entries_as_strs = list(map(entry_as_str, deleted_entries))
    new_entries_as_strs = list(map(entry_as_str, new_entries))
    result_new = list(new_entries)
    result_deleted = list(deleted_entries)
    result_edits = []
    sm = difflib.SequenceMatcher()
    CUTOFF = 0.8
    while True:
        best = None
        best_score = CUTOFF
        # Compare each new entry with each old entry to find the best match
        for new_entry_as_str in new_entries_as_strs:
            sm.set_seq1(new_entry_as_str)
            for old_entry_as_str in deleted_entries_as_strs:
                sm.set_seq2(old_entry_as_str)
                score = sm.ratio()
                if score > best_score:
                    best = new_entry_as_str, old_entry_as_str
                    best_score = score
        if best is not None:
            # Add the best match to the list of edits, and remove it from the
            # the list of new/old entries.  Also remove it from the new/old
            # lists for the next round.
            del_index = deleted_entries_as_strs.index(best[1])
            new_index = new_entries_as_strs.index(best[0])
            result_edits.append((result_deleted[del_index], result_new[new_index]))
            del deleted_entries_as_strs[del_index], result_deleted[del_index]
            del new_entries_as_strs[new_index], result_new[new_index]
        else:
            # No match better than CUTOFF exists in the remaining new and old
            # entries.
            break
    return result_new, result_deleted, result_edits


def merge_entries(
    base_entries, this_entries, other_entries, guess_edits=default_guess_edits
):
    """Merge changelog given base, this, and other versions."""
    m3 = Merge3(
        base_entries,
        this_entries,
        other_entries,
        sequence_matcher=patiencediff.PatienceSequenceMatcher,
    )
    result_entries = []
    at_top = True
    for group in m3.merge_groups():
        if debug.debug_flag_enabled("changelog_merge"):
            mutter("merge group:\n%r", group)
        group_kind = group[0]
        if group_kind == "conflict":
            _, base, this, other = group
            # Find additions
            new_in_other = [entry for entry in other if entry not in base]
            # Find deletions
            deleted_in_other = [entry for entry in base if entry not in other]
            if at_top and deleted_in_other:
                # Magic!  Compare deletions and additions to try spot edits
                new_in_other, deleted_in_other, edits_in_other = guess_edits(
                    new_in_other, deleted_in_other
                )
            else:
                # Changes not made at the top are always preserved as is, no
                # need to try distinguish edits from adds and deletes.
                edits_in_other = []
            if debug.debug_flag_enabled("changelog_merge"):
                mutter("at_top: %r", at_top)
                mutter("new_in_other: %r", new_in_other)
                mutter("deleted_in_other: %r", deleted_in_other)
                mutter("edits_in_other: %r", edits_in_other)
            # Apply deletes and edits
            updated_this = [entry for entry in this if entry not in deleted_in_other]
            for old_entry, new_entry in edits_in_other:
                try:
                    index = updated_this.index(old_entry)
                except ValueError as e:
                    # edited entry no longer present in this!  Just give up and
                    # declare a conflict.
                    raise EntryConflict() from e
                updated_this[index] = new_entry
            if debug.debug_flag_enabled("changelog_merge"):
                mutter("updated_this: %r", updated_this)
            if at_top:
                # Float new entries from other to the top
                result_entries = new_in_other + result_entries
            else:
                result_entries.extend(new_in_other)
            result_entries.extend(updated_this)
        else:  # unchanged, same, a, or b.
            lines = group[1]
            result_entries.extend(lines)
        at_top = False
    return result_entries

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

from bzrlib import merge


def changelog_entries(lines):
    """Return a list of changelog entries.

    :param lines: lines of a changelog file.
    :returns: list of entries.  Each entry is a tuple of lines.
    """
    entries = []
    for line in lines:
        if line[0] not in (' ', '\t', '\n'):
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
    return map(tuple, entries)


def entries_to_lines(entries):
    """Turn a list of entries into a flat iterable of lines."""
    for entry in entries:
        for line in entry:
            yield line


class ChangeLogMerger(merge.ConfigurableFileMerger):
    """Merge GNU-format ChangeLog files."""

    name_prefix = "changelog"

    def merge_text(self, params):
        """Float new changelog sections from other to the top of the changelog.

        e.g. Given a changelog in THIS containing::

          NEW-1
          OLD-2
          OLD-1

        and a changelog in OTHER containing::

          NEW-2
          OLD-1

        it will merge as::

          NEW-2
          NEW-1
          OLD-2
          OLD-1
        """
        # Transform files into lists of changelog entries
        this_entries = changelog_entries(params.this_lines)
        other_entries = changelog_entries(params.other_lines)
        base_entries = changelog_entries(params.base_lines)
        # Determine which entries have been added by base
        base_entries = frozenset(base_entries)
        new_in_other = [
            entry for entry in other_entries if entry not in base_entries]
        # Prepend them to the entries in this
        result_entries = new_in_other + this_entries
        # Transform the merged elements back into real blocks of lines.
        return 'success', entries_to_lines(result_entries)


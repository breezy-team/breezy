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


#def analyse_changes(from_entries, to_entries):
#    # Added to top == new entry
#    # Replace non-top entry == edit old entry
#    #   (apply degree of fuzzy matching?)
#    # Delete non-top entry == delete old
#    # Delete top entry == delete old?




class ChangeLogMerger(merge.ConfigurableFileMerger):
    """Merge GNU-format ChangeLog files."""

    name_prefix = "changelog"

    def get_filepath(self, params, tree):
        """Calculate the path to the file in a tree.

        This is overridden to return just the basename, rather than full path,
        so that e.g. if the config says ``changelog_merge_files = ChangeLog``,
        then all ChangeLog files in the tree will match (not just one in the
        root of the tree).
        
        :param params: A MergeHookParams describing the file to merge
        :param tree: a Tree, e.g. self.merger.this_tree.
        """
        return tree.inventory[params.file_id].name

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
        result_entries = merge_entries(
            base_entries, this_entries, other_entries)
        # Transform the merged elements back into real blocks of lines.
        return 'success', entries_to_lines(result_entries)


def merge_entries_old(base_entries, this_entries, other_entries):
    # Determine which entries have been added by other (compared to base)
    base_entries = frozenset(base_entries)
    new_in_other = [
        entry for entry in other_entries if entry not in base_entries]
    # Prepend them to the entries in this
    result_entries = new_in_other + this_entries
    return result_entries


def merge_entries_new(base_entries, this_entries, other_entries):
    # PROPOSAL:
    #  - Find changes in other vs. base
    #  - Categorise other-vs-base changes as 'new entry' (if added to top)
    #    or 'edit entry' (everything else)
    #  - Merge 

    from bzrlib.merge3 import Merge3
    m3 = Merge3(base_entries, this_entries, other_entries,
        allow_objects=True)
    result_entries = []
    at_top = True
    for group in m3.merge_groups():
        from bzrlib.trace import mutter
        mutter('merge group:\n%r', group)
#           'unchanged', lines
#                Lines unchanged from base
#           'a', lines
#                Lines taken from a
#           'same', lines
#                Lines taken from a (and equal to b)
#           'b', lines
#                Lines taken from b
#           'conflict', base_lines, a_lines, b_lines
#                Lines from base were changed to either a or b and conflict.
        group_kind = group[0]
        if group_kind == 'conflict':
            _, base, this, other = group
            new_in_other = [
                entry for entry in other if entry not in base]
            new_in_this = [
                entry for entry in this if entry not in base]
            result_entries.extend(new_in_other)
            result_entries.extend(new_in_this)
            # XXX: if at_top then put new_in_other at front result_entries?
            # i.e. need test for case in merge_text docstring.
        else: # unchanged, same, a, or b.
            lines = group[1]
            result_entries.extend(lines)
        at_top = False
    return result_entries


merge_entries = merge_entries_new

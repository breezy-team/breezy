# Copyright (C) 2006, 2009, 2010 Canonical Ltd
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
#
# Author: Martin Pool <mbp@canonical.com>
#         Aaron Bentley <aaron.bentley@utoronto.ca>

"""Text merge functionality for handling two-way and three-way merges.

This module provides classes for merging text files with conflict detection
and resolution. It supports structured merge information representation and
various merge strategies.
"""


class TextMerge:
    """Base class for text-mergers
    Subclasses must implement _merge_struct.

    Many methods produce or consume structured merge information.
    This is an iterable of tuples of lists of lines.
    Each tuple may have a length of 1 - 3, depending on whether the region it
    represents is conflicted.

    Unconflicted region tuples have length 1.
    Conflicted region tuples have length 2 or 3.  Index 1 is text_a, e.g. THIS.
    Index 1 is text_b, e.g. OTHER.  Index 2 is optional.  If present, it
    represents BASE.
    """

    # TODO: Show some version information (e.g. author, date) on conflicted
    # regions.
    A_MARKER = b"<<<<<<< \n"
    B_MARKER = b">>>>>>> \n"
    SPLIT_MARKER = b"=======\n"

    def __init__(self, a_marker=A_MARKER, b_marker=B_MARKER, split_marker=SPLIT_MARKER):
        r"""Initialize a TextMerge instance with conflict markers.

        Args:
            a_marker: Marker for the start of conflicted region A (THIS).
                Defaults to "<<<<<<< \n".
            b_marker: Marker for the end of conflicted region B (OTHER).
                Defaults to ">>>>>>> \n".
            split_marker: Marker separating conflicted regions A and B.
                Defaults to "=======\n".
        """
        self.a_marker = a_marker
        self.b_marker = b_marker
        self.split_marker = split_marker

    def _merge_struct(self):
        """Return structured merge info.  Must be implemented by subclasses.
        See TextMerge docstring for details on the format.
        """
        raise NotImplementedError("_merge_struct is abstract")

    def struct_to_lines(self, struct_iter):
        """Convert merge result tuples to lines."""
        for lines in struct_iter:
            if len(lines) == 1:
                yield from lines[0]
            else:
                yield self.a_marker
                yield from lines[0]
                yield self.split_marker
                yield from lines[1]
                yield self.b_marker

    def iter_useful(self, struct_iter):
        """Iterate through input tuples, skipping empty ones."""
        for group in struct_iter:
            if len(group[0]) > 0:
                yield group
            elif len(group) > 1 and len(group[1]) > 0:
                yield group

    def merge_lines(self, reprocess=False):
        """Produce an iterable of lines, suitable for writing to a file
        Returns a tuple of (line iterable, conflict indicator)
        If reprocess is True, a two-way merge will be performed on the
        intermediate structure, to reduce conflict regions.
        """
        struct = []
        conflicts = False
        for group in self.merge_struct(reprocess):
            struct.append(group)
            if len(group) > 1:
                conflicts = True
        return self.struct_to_lines(struct), conflicts

    def merge_struct(self, reprocess=False):
        """Produce structured merge info."""
        struct_iter = self.iter_useful(self._merge_struct())
        if reprocess is True:
            return self.reprocess_struct(struct_iter)
        else:
            return struct_iter

    @staticmethod
    def reprocess_struct(struct_iter):
        """Perform a two-way merge on structural merge info.
        This reduces the size of conflict regions, but breaks the connection
        between the BASE text and the conflict region.

        This process may split a single conflict region into several smaller
        ones, but will not introduce new conflicts.
        """
        for group in struct_iter:
            if len(group) == 1:
                yield group
            else:
                yield from Merge2(group[0], group[1]).merge_struct()


class Merge2(TextMerge):
    """Two-way merge.
    In a two way merge, common regions are shown as unconflicting, and uncommon
    regions produce conflicts.
    """

    def __init__(
        self,
        lines_a,
        lines_b,
        a_marker=TextMerge.A_MARKER,
        b_marker=TextMerge.B_MARKER,
        split_marker=TextMerge.SPLIT_MARKER,
    ):
        """Initialize a two-way merge operation.

        Args:
            lines_a: Sequence of lines from the first text (THIS).
            lines_b: Sequence of lines from the second text (OTHER).
            a_marker: Marker for the start of conflicted region A.
                Defaults to TextMerge.A_MARKER.
            b_marker: Marker for the end of conflicted region B.
                Defaults to TextMerge.B_MARKER.
            split_marker: Marker separating conflicted regions A and B.
                Defaults to TextMerge.SPLIT_MARKER.
        """
        TextMerge.__init__(self, a_marker, b_marker, split_marker)
        self.lines_a = lines_a
        self.lines_b = lines_b

    def _merge_struct(self):
        """Return structured merge info.
        See TextMerge docstring.
        """
        import patiencediff

        sm = patiencediff.PatienceSequenceMatcher(None, self.lines_a, self.lines_b)
        pos_a = 0
        pos_b = 0
        for ai, bi, l in sm.get_matching_blocks():
            # non-matching lines
            yield (self.lines_a[pos_a:ai], self.lines_b[pos_b:bi])
            # matching lines
            yield (self.lines_a[ai : ai + l],)
            pos_a = ai + l
            pos_b = bi + l
        # final non-matching lines
        yield (self.lines_a[pos_a:-1], self.lines_b[pos_b:-1])

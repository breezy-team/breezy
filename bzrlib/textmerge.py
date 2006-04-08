# Copyright (C) 2005, 2006 Canonical Ltd
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
#
# Author: Martin Pool <mbp@canonical.com> 
#         Aaron Bentley <aaron.bentley@utoronto.ca>

from difflib import SequenceMatcher


class TextMerge(object):
    """Base class for text-mergers
    Subclasses must implement _merge_struct.
    """
    def __init__(self, a_marker='<<<<<<< \n', b_marker='>>>>>>> \n',
                 split_marker='=======\n'):
        self.a_marker = a_marker
        self.b_marker = b_marker
        self.split_marker = split_marker

    def struct_to_lines(self, struct_iter):
        """Convert merge result tuples to lines"""
        for lines in struct_iter:
            if len(lines) == 1:
                for line in lines[0]:
                    yield line
            else:
                yield self.a_marker
                for line in lines[0]: 
                    yield line
                yield self.split_marker
                for line in lines[1]: 
                    yield line
                yield self.b_marker

    def iter_useful(self, struct_iter):
        """Iterate through input tuples, skipping empty ones."""
        for group in struct_iter:
            if len(group[0]) > 0:
                yield group
            elif len(group) > 1 and len(group[1]) > 0:
                yield group

    def merge_lines(self, reprocess=False):
        struct = []
        conflicts = False
        for group in self.merge_struct(reprocess):
            struct.append(group)
            if len(group) > 1:
                conflicts = True
        return self.struct_to_lines(struct), conflicts

    def merge_struct(self, reprocess=False):
        struct_iter = self.iter_useful(self._merge_struct())
        if reprocess is True:
            return self.reprocess_struct(struct_iter)
        else:
            return struct_iter

    @staticmethod
    def reprocess_struct(struct_iter):
        for group in struct_iter:
            if len(group) == 1:
                yield group
            else:
                for newgroup in Merge2(group[0], group[1]).merge_struct():
                    yield newgroup


class Merge2(TextMerge):

    """
    Two-way merge.
    In a two way merge, common regions are shown as unconflicting, and uncommon
    regions produce conflicts.
    """
    def __init__(self, lines_a, lines_b, a_marker='<<<<<<< \n', 
                 b_marker='>>>>>>> \n', split_marker='=======\n'):
        TextMerge.__init__(self, a_marker, b_marker, split_marker)
        self.lines_a = lines_a
        self.lines_b = lines_b

    def _merge_struct(self):
        sm = SequenceMatcher(None, self.lines_a, self.lines_b)
        pos_a = 0
        pos_b = 0
        for ai, bi, l in sm.get_matching_blocks():
            # non-matching lines
            yield(self.lines_a[pos_a:ai], self.lines_b[pos_b:bi])
            # matching lines
            yield(self.lines_a[ai:ai+l],)
            pos_a = ai + l 
            pos_b = bi + l
        # final non-matching lines
        yield(self.lines_a[pos_a:-1], self.lines_b[pos_b:-1])

# Copyright (C) 2008 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#

"""Functions for dealing with a persistent equivalency table."""


SENTINEL = -1


class EquivalenceTable(object):
    """This class tracks equivalencies between lists of hashable objects.

    :ivar _left_lines: The 'static' lines that will be preserved between runs.
    :ivar _right_lines: The current set of lines that we are matching against
    """

    def __init__(self, left_lines):
        self._left_lines = left_lines
        self._right_lines = None
        # For each line in 'left' give the offset to the other lines which
        # match it.
        self._generate_matching_left_lines()

    def _generate_matching_left_lines(self):
        matches = {}
        for idx, line in enumerate(self._left_lines):
            left_matches, right_matches = matches.setdefault(line, ([], []))
            left_matches.append(idx)
        self._matching_lines = matches

    def _update_right_matches(self):
        matches = self._matching_lines
        to_remove = []
        for line, (left_matches, right_matches) in matches.iteritems():
            if not left_matches: # queue for deletion
                to_remove.append(line)
            else:
                del right_matches[:]
        for line in to_remove:
            del matches[line]
        del to_remove
        for idx, line in enumerate(self._right_lines):
            left_matches, right_matches = matches.setdefault(line, ([], []))
            right_matches.append(idx)

    def set_right_lines(self, right_lines):
        """Use new right lines, and update the equivalences."""
        self._right_lines = right_lines
        self._update_right_matches()

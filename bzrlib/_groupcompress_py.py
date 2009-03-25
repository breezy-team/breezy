# Copyright (C) 2009 Canonical Limited.
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

"""Python version of compiled extensions for doing compression.

We separate the implementation from the groupcompress.py to avoid importing
useless stuff.
"""

### v imported from gc plugin@revno30
class EquivalenceTable(object):
    """This class tracks equivalencies between lists of hashable objects.

    :ivar lines: The 'static' lines that will be preserved between runs.
    :ival _matching_lines: A dict of {line:[matching offsets]}
    """

    def __init__(self, lines):
        self.lines = lines
        self._right_lines = None
        # For each line in 'left' give the offset to the other lines which
        # match it.
        self._generate_matching_lines()

    def _generate_matching_lines(self):
        matches = {}
        for idx, line in enumerate(self.lines):
            matches.setdefault(line, []).append(idx)
        self._matching_lines = matches

    def _update_matching_lines(self, new_lines, index):
        matches = self._matching_lines
        start_idx = len(self.lines)
        for idx, do_index in enumerate(index):
            if not do_index:
                continue
            matches.setdefault(new_lines[idx], []).append(start_idx + idx)

    def get_matches(self, line):
        """Return the lines which match the line in right."""
        try:
            return self._matching_lines[line]
        except KeyError:
            return None

    def _get_matching_lines(self):
        """Return a dictionary showing matching lines."""
        matching = {}
        for line in self.lines:
            matching[line] = self.get_matches(line)
        return matching

    def get_idx_matches(self, right_idx):
        """Return the left lines matching the right line at the given offset."""
        line = self._right_lines[right_idx]
        try:
            return self._matching_lines[line]
        except KeyError:
            return None

    def extend_lines(self, lines, index):
        """Add more lines to the left-lines list.

        :param lines: A list of lines to add
        :param index: A True/False for each node to define if it should be
            indexed.
        """
        self._update_matching_lines(lines, index)
        self.lines.extend(lines)

    def set_right_lines(self, lines):
        """Set the lines we will be matching against."""
        self._right_lines = lines


def _get_longest_match(equivalence_table, pos, max_pos, locations):
    """Get the longest possible match for the current position."""
    range_start = pos
    range_len = 0
    copy_ends = None
    while pos < max_pos:
        if locations is None:
            locations = equivalence_table.get_idx_matches(pos)
        if locations is None:
            # No more matches, just return whatever we have, but we know that
            # this last position is not going to match anything
            pos += 1
            break
        else:
            if copy_ends is None:
                # We are starting a new range
                copy_ends = [loc + 1 for loc in locations]
                range_len = 1
                locations = None # Consumed
            else:
                # We are currently in the middle of a match
                next_locations = set(copy_ends).intersection(locations)
                if len(next_locations):
                    # range continues
                    copy_ends = [loc + 1 for loc in next_locations]
                    range_len += 1
                    locations = None # Consumed
                else:
                    # But we are done with this match, we should be
                    # starting a new one, though. We will pass back 'locations'
                    # so that we don't have to do another lookup.
                    break
        pos += 1
    if copy_ends is None:
        return None, pos, locations
    return ((min(copy_ends) - range_len, range_start, range_len)), pos, locations


def parse(line_list):
    result = []
    lines = iter(line_list)
    next = lines.next
    label_line = next()
    sha1_line = next()
    if (not label_line.startswith('label: ') or
        not sha1_line.startswith('sha1: ')):
        raise AssertionError("bad text record %r" % lines)
    label = tuple(label_line[7:-1].split('\x00'))
    sha1 = sha1_line[6:-1]
    for header in lines:
        op = header[0]
        numbers = header[2:]
        numbers = [int(n) for n in header[2:].split(',')]
        if op == 'c':
            result.append((op, numbers[0], numbers[1], None))
        else:
            contents = [next() for i in xrange(numbers[0])]
            result.append((op, None, numbers[0], contents))
    ## return result
    return label, sha1, result


def apply_delta(basis, delta):
    """Apply delta to this object to become new_version_id."""
    lines = []
    last_offset = 0
    # eq ranges occur where gaps occur
    # start, end refer to offsets in basis
    for op, start, count, delta_lines in delta:
        if op == 'c':
            lines.append(basis[start:start+count])
        else:
            lines.extend(delta_lines)
    trim_encoding_newline(lines)
    return lines


def trim_encoding_newline(lines):
    if lines[-1] == '\n':
        del lines[-1]
    else:
        lines[-1] = lines[-1][:-1]


### ^ imported from gc plugin@revno30

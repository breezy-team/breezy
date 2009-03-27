# Copyright (C) 2009 Canonical Ltd
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

"""Python version of compiled extensions for doing compression.

We separate the implementation from the groupcompress.py to avoid importing
useless stuff.
"""

from bzrlib import osutils


class EquivalenceTable(object):
    """This class tracks equivalencies between lists of hashable objects.

    :ivar lines: The 'static' lines that will be preserved between runs.
    :ival _matching_lines: A dict of {line:[matching offsets]}
    """

    def __init__(self, lines):
        self.lines = lines
        self.line_offsets = []
        self.endpoint = sum(map(len, lines))
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
        assert len(new_lines) == len(index)
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

    def _get_longest_match(self, pos, max_pos, locations):
        """Get the longest possible match for the current position."""
        range_start = pos
        range_len = 0
        copy_ends = None
        while pos < max_pos:
            if locations is None:
                locations = self.get_idx_matches(pos)
            if locations is None:
                # No more matches, just return whatever we have, but we know
                # that this last position is not going to match anything
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
                        # starting a new one, though. We will pass back
                        # 'locations' so that we don't have to do another
                        # lookup.
                        break
            pos += 1
        if copy_ends is None:
            return None, pos, locations
        return (((min(copy_ends) - range_len, range_start, range_len)),
                pos, locations)

    def get_matching_blocks(self, lines, soft=False):
        """Return the ranges in lines which match self.lines.

        :param lines: lines to compress
        :return: A list of (old_start, new_start, length) tuples which reflect
            a region in self.lines that is present in lines.  The last element
            of the list is always (old_len, new_len, 0) to provide a end point
            for generating instructions from the matching blocks list.
        """
        result = []
        pos = 0
        self.set_right_lines(lines)
        locations = None
        max_pos = len(lines)
        result_append = result.append
        min_match_bytes = 10
        if soft:
            min_match_bytes = 200
        while pos < max_pos:
            block, pos, locations = self._get_longest_match(pos, max_pos,
                                                            locations)
            if block is not None:
                # Check to see if we are matching fewer than 5 characters,
                # which is turned into a simple 'insert', rather than a copy
                # If we have more than 5 lines, we definitely have more than 5
                # chars
                if block[-1] < min_match_bytes:
                    # This block may be a 'short' block, check
                    old_start, new_start, range_len = block
                    matched_bytes = sum(map(len,
                        lines[new_start:new_start + range_len]))
                    if matched_bytes < min_match_bytes:
                        block = None
            if block is not None:
                result_append(block)
        result_append((len(self.lines), len(lines), 0))
        return result

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
        endpoint = self.endpoint
        for line in lines:
            endpoint += len(line)
            self.line_offsets.append(endpoint)
        assert len(self.line_offsets) == len(self.lines)
        self.endpoint = endpoint

    def set_right_lines(self, lines):
        """Set the lines we will be matching against."""
        self._right_lines = lines

    def _flush_insert(self, start_linenum, end_linenum,
                      new_lines, out_lines, index_lines):
        """Add an 'insert' request to the data stream."""
        bytes_to_insert = ''.join(new_lines[start_linenum:end_linenum])
        insert_length = len(bytes_to_insert)
        # Each insert instruction is at most 127 bytes long
        for start_byte in xrange(0, insert_length, 127):
            insert_count = min(insert_length - start_byte, 127)
            assert insert_count <= 127
            out_lines.append(chr(insert_count))
            # Don't index the 'insert' instruction
            index_lines.append(False)
            insert = bytes_to_insert[start_byte:start_byte+insert_count]
            as_lines = osutils.split_lines(insert)
            out_lines.extend(as_lines)
            index_lines.extend([True]*len(as_lines))

    def _flush_copy(self, old_start_linenum, num_lines,
                    out_lines, index_lines):
        if old_start_linenum == 0:
            first_byte = 0
        else:
            first_byte = self.line_offsets[old_start_linenum - 1]
        stop_byte = self.line_offsets[old_start_linenum + num_lines - 1]
        num_bytes = stop_byte - first_byte
        # The data stream allows >64kB in a copy, but to match the compiled
        # code, we will also limit it to a 64kB copy
        for start_byte in xrange(first_byte, stop_byte, 64*1024):
            num_bytes = min(64*1024, stop_byte - first_byte)
            copy_bytes = encode_copy_instruction(start_byte, num_bytes)
            out_lines.append(copy_bytes)
            index_lines.append(False)

    def make_delta(self, new_lines, bytes_length=None, soft=False):
        """Compute the delta for this content versus the original content."""
        if bytes_length is None:
            bytes_length = sum(map(len, new_lines))
        # reserved for content type, content length
        out_lines = ['', '', encode_base128_int(bytes_length)]
        index_lines = [False, False, False]
        blocks = self.get_matching_blocks(new_lines, soft=soft)
        current_line_num = 0
        # We either copy a range (while there are reusable lines) or we
        # insert new lines. To find reusable lines we traverse
        for old_start, new_start, range_len in blocks:
            if new_start != current_line_num:
                # non-matching region, insert the content
                self._flush_insert(current_line_num, new_start,
                                   new_lines, out_lines, index_lines)
            current_line_num = new_start + range_len
            if range_len:
                self._flush_copy(old_start, range_len, out_lines, index_lines)
        return out_lines, index_lines


def encode_base128_int(val):
    """Convert an integer into a 7-bit lsb encoding."""
    bytes = []
    count = 0
    while val >= 0x80:
        bytes.append(chr((val | 0x80) & 0xFF))
        val >>= 7
    bytes.append(chr(val))
    return ''.join(bytes)


def decode_base128_int(bytes):
    """Decode an integer from a 7-bit lsb encoding."""
    offset = 0
    val = 0
    shift = 0
    bval = ord(bytes[offset])
    while bval >= 0x80:
        val |= (bval & 0x7F) << shift
        shift += 7
        offset += 1
        bval = ord(bytes[offset])
    val |= bval << shift
    offset += 1
    return val, offset


def encode_copy_instruction(offset, length):
    """Convert this offset into a control code and bytes."""
    copy_command = 0x80
    copy_bytes = [None]

    for copy_bit in (0x01, 0x02, 0x04, 0x08):
        base_byte = offset & 0xff
        if base_byte:
            copy_command |= copy_bit
            copy_bytes.append(chr(base_byte))
        offset >>= 8
    if length is None:
        # None is used by the test suite
        copy_bytes[0] = chr(copy_command)
        return ''.join(copy_bytes)
    if length > 0x10000:
        raise ValueError("we don't emit copy records for lengths > 64KiB")
    if length == 0:
        raise ValueError("We cannot emit a copy of length 0")
    if length != 0x10000:
        # A copy of length exactly 64*1024 == 0x10000 is sent as a length of 0,
        # since that saves bytes for large chained copies
        for copy_bit in (0x10, 0x20):
            base_byte = length & 0xff
            if base_byte:
                copy_command |= copy_bit
                copy_bytes.append(chr(base_byte))
            length >>= 8
    copy_bytes[0] = chr(copy_command)
    return ''.join(copy_bytes)


def decode_copy_instruction(bytes, cmd, pos):
    """Decode a copy instruction from the next few bytes.

    A copy instruction is a variable number of bytes, so we will parse the
    bytes we care about, and return the new position, as well as the offset and
    length referred to in the bytes.

    :param bytes: A string of bytes
    :param cmd: The command code
    :param pos: The position in bytes right after the copy command
    :return: (offset, length, newpos)
        The offset of the copy start, the number of bytes to copy, and the
        position after the last byte of the copy
    """
    if cmd & 0x80 != 0x80:
        raise ValueError('copy instructions must have bit 0x80 set')
    offset = 0
    length = 0
    if (cmd & 0x01):
        offset = ord(bytes[pos])
        pos += 1
    if (cmd & 0x02):
        offset = offset | (ord(bytes[pos]) << 8)
        pos += 1
    if (cmd & 0x04):
        offset = offset | (ord(bytes[pos]) << 16)
        pos += 1
    if (cmd & 0x08):
        offset = offset | (ord(bytes[pos]) << 24)
        pos += 1
    if (cmd & 0x10):
        length = ord(bytes[pos])
        pos += 1
    if (cmd & 0x20):
        length = length | (ord(bytes[pos]) << 8)
        pos += 1
    if (cmd & 0x40):
        length = length | (ord(bytes[pos]) << 16)
        pos += 1
    if length == 0:
        length = 65536
    return (offset, length, pos)


def make_delta(source_bytes, target_bytes):
    """Create a delta from source to target."""
    # TODO: The checks below may not be a the right place yet.
    if type(source_bytes) is not str:
        raise TypeError('source is not a str')
    if type(target_bytes) is not str:
        raise TypeError('target is not a str')
    line_locations = EquivalenceTable([])
    source_lines = osutils.split_lines(source_bytes)
    line_locations.extend_lines(source_lines, [True]*len(source_lines))
    delta, _ = line_locations.make_delta(osutils.split_lines(target_bytes),
                                         bytes_length=len(target_bytes))
    return ''.join(delta)


def apply_delta(basis, delta):
    """Apply delta to this object to become new_version_id."""
    if type(basis) is not str:
        raise TypeError('basis is not a str')
    if type(delta) is not str:
        raise TypeError('delta is not a str')
    target_length, pos = decode_base128_int(delta)
    lines = []
    len_delta = len(delta)
    while pos < len_delta:
        cmd = ord(delta[pos])
        pos += 1
        if cmd & 0x80:
            offset, length, pos = decode_copy_instruction(delta, cmd, pos)
            lines.append(basis[offset:offset+length])
        else: # Insert of 'cmd' bytes
            if cmd == 0:
                raise ValueError('Command == 0 not supported yet')
            lines.append(delta[pos:pos+cmd])
            pos += cmd
    bytes = ''.join(lines)
    if len(bytes) != target_length:
        raise ValueError('Delta claimed to be %d long, but ended up'
                         ' %d long' % (target_length, len(bytes)))
    return bytes

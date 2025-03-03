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

from .. import osutils


class _OutputHandler:
    """A simple class which just tracks how to split up an insert request."""

    def __init__(self, out_lines, index_lines, min_len_to_index):
        self.out_lines = out_lines
        self.index_lines = index_lines
        self.min_len_to_index = min_len_to_index
        self.cur_insert_lines = []
        self.cur_insert_len = 0

    def add_copy(self, start_byte, end_byte):
        # The data stream allows >64kB in a copy, but to match the compiled
        # code, we will also limit it to a 64kB copy
        for start_byte in range(start_byte, end_byte, 64 * 1024):  # noqa: B020
            num_bytes = min(64 * 1024, end_byte - start_byte)
            copy_bytes = encode_copy_instruction(start_byte, num_bytes)
            self.out_lines.append(copy_bytes)
            self.index_lines.append(False)

    def _flush_insert(self):
        if not self.cur_insert_lines:
            return
        if self.cur_insert_len > 127:
            raise AssertionError("We cannot insert more than 127 bytes at a time.")
        self.out_lines.append(bytes([self.cur_insert_len]))
        self.index_lines.append(False)
        self.out_lines.extend(self.cur_insert_lines)
        if self.cur_insert_len < self.min_len_to_index:
            self.index_lines.extend([False] * len(self.cur_insert_lines))
        else:
            self.index_lines.extend([True] * len(self.cur_insert_lines))
        self.cur_insert_lines = []
        self.cur_insert_len = 0

    def _insert_long_line(self, line):
        # Flush out anything pending
        self._flush_insert()
        line_len = len(line)
        for start_index in range(0, line_len, 127):
            next_len = min(127, line_len - start_index)
            self.out_lines.append(bytes([next_len]))
            self.index_lines.append(False)
            self.out_lines.append(line[start_index : start_index + next_len])
            # We don't index long lines, because we won't be able to match
            # a line split across multiple inserts anway
            self.index_lines.append(False)

    def add_insert(self, lines):
        if self.cur_insert_lines != []:
            raise AssertionError(
                "self.cur_insert_lines must be empty when adding a new insert"
            )
        for line in lines:
            if len(line) > 127:
                self._insert_long_line(line)
            else:
                next_len = len(line) + self.cur_insert_len
                if next_len > 127:
                    # Adding this line would overflow, so flush, and start over
                    self._flush_insert()
                    self.cur_insert_lines = [line]
                    self.cur_insert_len = len(line)
                else:
                    self.cur_insert_lines.append(line)
                    self.cur_insert_len = next_len
        self._flush_insert()


class LinesDeltaIndex:
    """This class indexes matches between strings.

    :ivar lines: The 'static' lines that will be preserved between runs.
    :ivar _matching_lines: A dict of {line:[matching offsets]}
    :ivar line_offsets: The byte offset for the end of each line, used to
        quickly map between a matching line number and the byte location
    :ivar endpoint: The total number of bytes in self.line_offsets
    """

    _MIN_MATCH_BYTES = 10
    _SOFT_MIN_MATCH_BYTES = 200

    def __init__(self, lines):
        self.lines = []
        self.line_offsets = []
        self.endpoint = 0
        self._matching_lines = {}
        self.extend_lines(lines, [True] * len(lines))

    def _update_matching_lines(self, new_lines, index):
        matches = self._matching_lines
        start_idx = len(self.lines)
        if len(new_lines) != len(index):
            raise AssertionError(
                "The number of lines to be indexed does"
                + f" not match the index/don't index flags: {len(new_lines)} != {len(index)}"
            )
        for idx, do_index in enumerate(index):
            if not do_index:
                continue
            line = new_lines[idx]
            try:
                matches[line].add(start_idx + idx)
            except KeyError:
                matches[line] = {start_idx + idx}

    def get_matches(self, line):
        """Return the lines which match the line in right."""
        try:
            return self._matching_lines[line]
        except KeyError:
            return None

    def _get_longest_match(self, lines, pos):
        """Look at all matches for the current line, return the longest.

        :param lines: The lines we are matching against
        :param pos: The current location we care about
        :param locations: A list of lines that matched the current location.
            This may be None, but often we'll have already found matches for
            this line.
        :return: (start_in_self, start_in_lines, num_lines)
            All values are the offset in the list (aka the line number)
            If start_in_self is None, then we have no matches, and this line
            should be inserted in the target.
        """
        range_start = pos
        range_len = 0
        prev_locations = None
        max_pos = len(lines)
        matching = self._matching_lines
        while pos < max_pos:
            try:
                locations = matching[lines[pos]]
            except KeyError:
                # No more matches, just return whatever we have, but we know
                # that this last position is not going to match anything
                pos += 1
                break
            # We have a match
            if prev_locations is None:
                # This is the first match in a range
                prev_locations = locations
                range_len = 1
                locations = None  # Consumed
            else:
                # We have a match started, compare to see if any of the
                # current matches can be continued
                next_locations = locations.intersection(
                    [loc + 1 for loc in prev_locations]
                )
                if next_locations:
                    # At least one of the regions continues to match
                    prev_locations = set(next_locations)
                    range_len += 1
                    locations = None  # Consumed
                else:
                    # All current regions no longer match.
                    # This line does still match something, just not at the
                    # end of the previous matches. We will return locations
                    # so that we can avoid another _matching_lines lookup.
                    break
            pos += 1
        if prev_locations is None:
            # We have no matches, this is a pure insert
            return None, pos
        smallest = min(prev_locations)
        return (smallest - range_len + 1, range_start, range_len), pos

    def get_matching_blocks(self, lines, soft=False):
        """Return the ranges in lines which match self.lines.

        :param lines: lines to compress
        :return: A list of (old_start, new_start, length) tuples which reflect
            a region in self.lines that is present in lines.  The last element
            of the list is always (old_len, new_len, 0) to provide a end point
            for generating instructions from the matching blocks list.
        """
        # In this code, we iterate over multiple _get_longest_match calls, to
        # find the next longest copy, and possible insert regions. We then
        # convert that to the simple matching_blocks representation, since
        # otherwise inserting 10 lines in a row would show up as 10
        # instructions.
        result = []
        pos = 0
        max_pos = len(lines)
        result_append = result.append
        min_match_bytes = self._MIN_MATCH_BYTES
        if soft:
            min_match_bytes = self._SOFT_MIN_MATCH_BYTES
        while pos < max_pos:
            block, pos = self._get_longest_match(lines, pos)
            if block is not None:
                # Check to see if we match fewer than min_match_bytes. As we
                # will turn this into a pure 'insert', rather than a copy.
                # block[-1] is the number of lines. A quick check says if we
                # have more lines than min_match_bytes, then we know we have
                # enough bytes.
                if block[-1] < min_match_bytes:
                    # This block may be a 'short' block, check
                    old_start, new_start, range_len = block
                    matched_bytes = sum(
                        map(len, lines[new_start : new_start + range_len])
                    )
                    if matched_bytes < min_match_bytes:
                        block = None
            if block is not None:
                result_append(block)
        result_append((len(self.lines), len(lines), 0))
        return result

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
        if len(self.line_offsets) != len(self.lines):
            raise AssertionError(
                "Somehow the line offset indicator"
                " got out of sync with the line counter."
            )
        self.endpoint = endpoint

    def _flush_insert(
        self, start_linenum, end_linenum, new_lines, out_lines, index_lines
    ):
        """Add an 'insert' request to the data stream."""
        bytes_to_insert = b"".join(new_lines[start_linenum:end_linenum])
        insert_length = len(bytes_to_insert)
        # Each insert instruction is at most 127 bytes long
        for start_byte in range(0, insert_length, 127):
            insert_count = min(insert_length - start_byte, 127)
            out_lines.append(bytes([insert_count]))
            # Don't index the 'insert' instruction
            index_lines.append(False)
            insert = bytes_to_insert[start_byte : start_byte + insert_count]
            as_lines = osutils.split_lines(insert)
            out_lines.extend(as_lines)
            index_lines.extend([True] * len(as_lines))

    def _flush_copy(self, old_start_linenum, num_lines, out_lines, index_lines):
        if old_start_linenum == 0:
            first_byte = 0
        else:
            first_byte = self.line_offsets[old_start_linenum - 1]
        stop_byte = self.line_offsets[old_start_linenum + num_lines - 1]
        num_bytes = stop_byte - first_byte
        # The data stream allows >64kB in a copy, but to match the compiled
        # code, we will also limit it to a 64kB copy
        for start_byte in range(first_byte, stop_byte, 64 * 1024):
            num_bytes = min(64 * 1024, stop_byte - start_byte)
            copy_bytes = encode_copy_instruction(start_byte, num_bytes)
            out_lines.append(copy_bytes)
            index_lines.append(False)

    def make_delta(self, new_lines, bytes_length, soft=False):
        """Compute the delta for this content versus the original content."""
        # reserved for content type, content length
        out_lines = [b"", b"", encode_base128_int(bytes_length)]
        index_lines = [False, False, False]
        output_handler = _OutputHandler(out_lines, index_lines, self._MIN_MATCH_BYTES)
        blocks = self.get_matching_blocks(new_lines, soft=soft)
        current_line_num = 0
        # We either copy a range (while there are reusable lines) or we
        # insert new lines. To find reusable lines we traverse
        for old_start, new_start, range_len in blocks:
            if new_start != current_line_num:
                # non-matching region, insert the content
                output_handler.add_insert(new_lines[current_line_num:new_start])
            current_line_num = new_start + range_len
            if range_len:
                # Convert the line based offsets into byte based offsets
                if old_start == 0:
                    first_byte = 0
                else:
                    first_byte = self.line_offsets[old_start - 1]
                last_byte = self.line_offsets[old_start + range_len - 1]
                output_handler.add_copy(first_byte, last_byte)
        return out_lines, index_lines


def encode_base128_int(val):
    """Convert an integer into a 7-bit lsb encoding."""
    data = bytearray()
    while val >= 0x80:
        data.append((val | 0x80) & 0xFF)
        val >>= 7
    data.append(val)
    return bytes(data)


def decode_base128_int(data):
    """Decode an integer from a 7-bit lsb encoding."""
    offset = 0
    val = 0
    shift = 0
    bval = data[offset]
    while bval >= 0x80:
        val |= (bval & 0x7F) << shift
        shift += 7
        offset += 1
        bval = data[offset]
    val |= bval << shift
    offset += 1
    return val, offset


def encode_copy_instruction(offset, length):
    """Convert this offset into a control code and bytes."""
    copy_command = 0x80
    copy_bytes = [None]

    for copy_bit in (0x01, 0x02, 0x04, 0x08):
        base_byte = offset & 0xFF
        if base_byte:
            copy_command |= copy_bit
            copy_bytes.append(bytes([base_byte]))
        offset >>= 8
    if length is None:
        raise ValueError("cannot supply a length of None")
    if length > 0x10000:
        raise ValueError("we don't emit copy records for lengths > 64KiB")
    if length == 0:
        raise ValueError("We cannot emit a copy of length 0")
    if length != 0x10000:
        # A copy of length exactly 64*1024 == 0x10000 is sent as a length of 0,
        # since that saves bytes for large chained copies
        for copy_bit in (0x10, 0x20):
            base_byte = length & 0xFF
            if base_byte:
                copy_command |= copy_bit
                copy_bytes.append(bytes([base_byte]))
            length >>= 8
    copy_bytes[0] = bytes([copy_command])
    return b"".join(copy_bytes)


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
        raise ValueError("copy instructions must have bit 0x80 set")
    offset = 0
    length = 0
    if cmd & 0x01:
        offset = bytes[pos]
        pos += 1
    if cmd & 0x02:
        offset = offset | (bytes[pos] << 8)
        pos += 1
    if cmd & 0x04:
        offset = offset | (bytes[pos] << 16)
        pos += 1
    if cmd & 0x08:
        offset = offset | (bytes[pos] << 24)
        pos += 1
    if cmd & 0x10:
        length = bytes[pos]
        pos += 1
    if cmd & 0x20:
        length = length | (bytes[pos] << 8)
        pos += 1
    if cmd & 0x40:
        length = length | (bytes[pos] << 16)
        pos += 1
    if length == 0:
        length = 65536
    return (offset, length, pos)


def make_delta(source_bytes, target_bytes):
    """Create a delta from source to target."""
    if not isinstance(source_bytes, bytes):
        raise TypeError("source is not bytes")
    if not isinstance(target_bytes, bytes):
        raise TypeError("target is not bytes")
    line_locations = LinesDeltaIndex(osutils.split_lines(source_bytes))
    delta, _ = line_locations.make_delta(
        osutils.split_lines(target_bytes), bytes_length=len(target_bytes)
    )
    return b"".join(delta)


def apply_delta(basis, delta):
    """Apply delta to this object to become new_version_id."""
    if not isinstance(basis, bytes):
        raise TypeError("basis is not bytes")
    if not isinstance(delta, bytes):
        raise TypeError("delta is not bytes")
    target_length, pos = decode_base128_int(delta)
    lines = []
    len_delta = len(delta)
    while pos < len_delta:
        cmd = delta[pos]
        pos += 1
        if cmd & 0x80:
            offset, length, pos = decode_copy_instruction(delta, cmd, pos)
            last = offset + length
            if last > len(basis):
                raise ValueError("data would copy bytes past theend of source")
            lines.append(basis[offset:last])
        else:  # Insert of 'cmd' bytes
            if cmd == 0:
                raise ValueError("Command == 0 not supported yet")
            lines.append(delta[pos : pos + cmd])
            pos += cmd
    data = b"".join(lines)
    if len(data) != target_length:
        raise ValueError(
            f"Delta claimed to be {target_length} long, but ended up {len(bytes)} long"
        )
    return data


def apply_delta_to_source(source, delta_start, delta_end):
    """Extract a delta from source bytes, and apply it."""
    source_size = len(source)
    if delta_start >= source_size:
        raise ValueError("delta starts after source")
    if delta_end > source_size:
        raise ValueError("delta ends after source")
    if delta_start >= delta_end:
        raise ValueError("delta starts after it ends")
    delta_bytes = source[delta_start:delta_end]
    return apply_delta(source, delta_bytes)

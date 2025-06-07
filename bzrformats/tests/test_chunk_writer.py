# Copyright (C) 2008 Canonical Ltd
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

"""Tests for writing fixed size chunks with compression."""

import zlib

from breezy.tests import TestCaseWithTransport

from .. import chunk_writer


class TestWriter(TestCaseWithTransport):
    def check_chunk(self, bytes_list, size):
        data = b"".join(bytes_list)
        self.assertEqual(size, len(data))
        return zlib.decompress(data)

    def test_chunk_writer_empty(self):
        writer = chunk_writer.ChunkWriter(4096)
        bytes_list, unused, padding = writer.finish()
        node_bytes = self.check_chunk(bytes_list, 4096)
        self.assertEqual(b"", node_bytes)
        self.assertEqual(None, unused)
        # Only a zlib header.
        self.assertEqual(4088, padding)

    def test_optimize_for_speed(self):
        writer = chunk_writer.ChunkWriter(4096)
        writer.set_optimize(for_size=False)
        self.assertEqual(
            chunk_writer.ChunkWriter._repack_opts_for_speed,
            (writer._max_repack, writer._max_zsync),
        )
        writer = chunk_writer.ChunkWriter(4096, optimize_for_size=False)
        self.assertEqual(
            chunk_writer.ChunkWriter._repack_opts_for_speed,
            (writer._max_repack, writer._max_zsync),
        )

    def test_optimize_for_size(self):
        writer = chunk_writer.ChunkWriter(4096)
        writer.set_optimize(for_size=True)
        self.assertEqual(
            chunk_writer.ChunkWriter._repack_opts_for_size,
            (writer._max_repack, writer._max_zsync),
        )
        writer = chunk_writer.ChunkWriter(4096, optimize_for_size=True)
        self.assertEqual(
            chunk_writer.ChunkWriter._repack_opts_for_size,
            (writer._max_repack, writer._max_zsync),
        )

    def test_some_data(self):
        writer = chunk_writer.ChunkWriter(4096)
        writer.write(b"foo bar baz quux\n")
        bytes_list, unused, padding = writer.finish()
        node_bytes = self.check_chunk(bytes_list, 4096)
        self.assertEqual(b"foo bar baz quux\n", node_bytes)
        self.assertEqual(None, unused)
        # More than just the header..
        self.assertEqual(4073, padding)

    @staticmethod
    def _make_lines():
        lines = []
        for group in range(48):
            offset = group * 50
            numbers = list(range(offset, offset + 50))
            # Create a line with this group
            lines.append(b"".join(b"%d" % n for n in numbers) + b"\n")
        return lines

    def test_too_much_data_does_not_exceed_size(self):
        # Generate enough data to exceed 4K
        lines = self._make_lines()
        writer = chunk_writer.ChunkWriter(4096)
        for idx, line in enumerate(lines):
            if writer.write(line):
                self.assertEqual(46, idx)
                break
        bytes_list, unused, _ = writer.finish()
        node_bytes = self.check_chunk(bytes_list, 4096)
        # the first 46 lines should have been added
        expected_bytes = b"".join(lines[:46])
        self.assertEqualDiff(expected_bytes, node_bytes)
        # And the line that failed should have been saved for us
        self.assertEqual(lines[46], unused)

    def test_too_much_data_preserves_reserve_space(self):
        # Generate enough data to exceed 4K
        lines = self._make_lines()
        writer = chunk_writer.ChunkWriter(4096, 256)
        for idx, line in enumerate(lines):
            if writer.write(line):
                self.assertEqual(44, idx)
                break
        else:
            self.fail("We were able to write all lines")
        self.assertFalse(writer.write(b"A" * 256, reserved=True))
        bytes_list, unused, _ = writer.finish()
        node_bytes = self.check_chunk(bytes_list, 4096)
        # the first 44 lines should have been added
        expected_bytes = b"".join(lines[:44]) + b"A" * 256
        self.assertEqualDiff(expected_bytes, node_bytes)
        # And the line that failed should have been saved for us
        self.assertEqual(lines[44], unused)

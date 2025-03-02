# Copyright (C) 2006, 2009, 2010, 2011 Canonical Ltd
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


"""Tests for tuned_gzip."""

import gzip
from io import BytesIO

from .. import tests, tuned_gzip


class TestToGzip(tests.TestCase):
    def assertToGzip(self, chunks):
        raw_bytes = b"".join(chunks)
        gzfromchunks = tuned_gzip.chunks_to_gzip(chunks)
        decoded = gzip.GzipFile(fileobj=BytesIO(b"".join(gzfromchunks))).read()
        lraw, ldecoded = len(raw_bytes), len(decoded)
        self.assertEqual(
            lraw, ldecoded, f"Expecting data length {lraw}, got {ldecoded}"
        )
        self.assertEqual(raw_bytes, decoded)

    def test_single_chunk(self):
        self.assertToGzip([b"a modest chunk\nwith some various\nbits\n"])

    def test_simple_text(self):
        self.assertToGzip([b"some\n", b"strings\n", b"to\n", b"process\n"])

    def test_large_chunks(self):
        self.assertToGzip([b"a large string\n" * 1024])
        self.assertToGzip([b"a large string\n"] * 1024)

    def test_enormous_chunks(self):
        self.assertToGzip([b"a large string\n" * 1024 * 256])
        self.assertToGzip([b"a large string\n"] * 1024 * 256)

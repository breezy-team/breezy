# Copyright (C) 2011 Canonical Ltd
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

"""Tests for our estimation of compressed content."""

import zlib
import hashlib

from .. import (
    estimate_compressed_size,
    tests,
    )


class TestZLibEstimator(tests.TestCase):

    def get_slightly_random_content(self, length, seed=b''):
        """We generate some hex-data that can be seeded.

        The output should be deterministic, but the data stream is effectively
        random.
        """
        h = hashlib.md5(seed)
        hex_content = []
        count = 0
        while count < length:
            b = h.hexdigest().encode('ascii')
            hex_content.append(b)
            h.update(b)
            count += len(b)
        return b''.join(hex_content)[:length]

    def test_adding_content(self):
        ze = estimate_compressed_size.ZLibEstimator(32000)
        raw_data = self.get_slightly_random_content(60000)
        block_size = 1000
        for start in range(0, len(raw_data), block_size):
            ze.add_content(raw_data[start:start + block_size])
            if ze.full():
                break
        # Practise showed that 'start' was 56000. However, zlib is a bit
        # platform dependent, so give it +/- 5%.
        self.assertTrue(54000 <= start <= 58000,
                        "Unexpected amount of raw data added: %d bytes" % (start,))
        # The real compression should be 'close' to 32000, real measurement was
        # 32401
        raw_comp = zlib.compress(raw_data[:start])
        self.assertTrue(31000 < len(raw_comp) < 33000,
                        "Unexpected compressed size: %d bytes" % (len(raw_comp),))

    def test_adding_more_content(self):
        ze = estimate_compressed_size.ZLibEstimator(64000)
        raw_data = self.get_slightly_random_content(150000)
        block_size = 1000
        for start in range(0, len(raw_data), block_size):
            ze.add_content(raw_data[start:start + block_size])
            if ze.full():
                break
        # Practise showed that 'start' was 112000
        self.assertTrue(110000 <= start <= 114000,
                        "Unexpected amount of raw data added: %d bytes" % (start,))
        # The real compression should be 'close' to 32000, real measurement was
        # 32401
        raw_comp = zlib.compress(raw_data[:start])
        self.assertTrue(63000 < len(raw_comp) < 65000,
                        "Unexpected compressed size: %d bytes" % (len(raw_comp),))

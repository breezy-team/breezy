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

"""Code to estimate the entropy of content"""

import math
import zlib

class ZLibEstimator(object):
    """Uses zlib.compressobj to estimate compressed size."""

    def __init__(self, target_size):
        self._target_size = target_size
        self._compressor = zlib.compressobj()
        self._uncompressed_size_added = 0
        self._compressed_size_added = 0
        self._unflushed_size_added = 0

    def add_content(self, content):
        self._uncompressed_size_added += len(content)
        self._unflushed_size_added += len(content)
        z_size = len(self._compressor.compress(content))
        if z_size > 0:
            self._compressed_size_added += z_size
            self._unflushed_size_added = 0

    def full(self):
        """Have we reached the target size?"""
        if self._unflushed_size_added > self._target_size:
            z_size = len(self._compressor.flush(zlib.Z_SYNC_FLUSH))
            self._compressed_size_added += z_size
            self._unflushed_size_added = 0
        return self._compressed_size_added >= self._target_size


_il2 = 1.0/math.log(2.0)

class HistogramEstimator(object):
    """Uses a histogram to determine ~entropy"""

    def __init__(self, target_size):
        self._target_size = target_size
        self._counts = [0]*256
        self._bytes_added = 0

    def add_content(self, content):
        for c in content:
            self._counts[ord(c)] += 1
        self._bytes_added += len(content)

    def _compute_entropy(self):
        entropy = 0.0
        if self._bytes_added == 0:
            return 0
        iba = 1.0 / self._bytes_added
        for count in self._counts:
            if count == 0:
                continue
            p = float(count) * iba
            lp = math.log(p) * _il2
            entropy += p * lp
        # entropy *should* be a measurement of the number of bits it will take
        # to encode each byte of the input. So we use:
        return (-entropy)

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

"""Code to estimate the entropy of content."""

import zlib


class ZLibEstimator:
    """Uses zlib.compressobj to estimate compressed size."""

    def __init__(self, target_size, min_compression=2.0):
        """Create a new estimator.

        :param target_size: The desired size of the compressed content.
        :param min_compression: Estimated minimum compression. By default we
            assume that the content is 'text', which means a min compression of
            about 2:1.
        """
        self._target_size = target_size
        self._compressor = zlib.compressobj()
        self._uncompressed_size_added = 0
        self._compressed_size_added = 0
        self._unflushed_size_added = 0
        self._estimated_compression = 2.0

    def add_content(self, content):
        self._uncompressed_size_added += len(content)
        self._unflushed_size_added += len(content)
        z_size = len(self._compressor.compress(content))
        if z_size > 0:
            self._record_z_len(z_size)

    def _record_z_len(self, count):
        # We got some compressed bytes, update the counters
        self._compressed_size_added += count
        self._unflushed_size_added = 0
        # So far we've read X uncompressed bytes, and written Y compressed
        # bytes. We should have a decent estimate of the final compression.
        self._estimated_compression = (
            float(self._uncompressed_size_added) / self._compressed_size_added
        )

    def full(self):
        """Have we reached the target size?"""
        if self._unflushed_size_added:
            remaining_size = self._target_size - self._compressed_size_added
            # Estimate how much compressed content the unflushed data will
            # consume
            est_z_size = self._unflushed_size_added / self._estimated_compression
            if est_z_size >= remaining_size:
                # We estimate we are close to remaining
                z_size = len(self._compressor.flush(zlib.Z_SYNC_FLUSH))
                self._record_z_len(z_size)
        return self._compressed_size_added >= self._target_size

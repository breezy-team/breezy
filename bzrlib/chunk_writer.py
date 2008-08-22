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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

"""ChunkWriter: write compressed data out with a fixed upper bound."""

import zlib
from zlib import Z_FINISH, Z_SYNC_FLUSH

_stats = [0, 0, 0]

class ChunkWriter(object):
    """ChunkWriter allows writing of compressed data with a fixed size.

    If less data is supplied than fills a chunk, the chunk is padded with
    NULL bytes. If more data is supplied, then the writer packs as much
    in as it can, but never splits any item it was given.

    The algorithm for packing is open to improvement! Current it is:
     - write the bytes given
     - if the total seen bytes so far exceeds the chunk size, flush.

    :cvar _max_repack: To fit the maximum number of entries into a node, we
        will sometimes start over and compress the whole list to get tighter
        packing. We get diminishing returns after a while, so this limits the
        number of times we will try.
        In testing, some values for bzr.dev::

            repack  time  MB    hit_max_repack  buffer_full
             1       7.9  5.1   1268            0
             2       8.8  4.4   1069            0
             3       9.7  4.2   1022            46
             4      11.1  4.1   974             619
            20      11.9  4.1   0               1012

        In testing, some values for mysql-unpacked::

            repack  time  MB    hit_max_repack  buffer_full
             1      52.4  16.9  4295            0
             2      55.8  14.1  3561            0
             3      60.3  13.5  3407            197
             4      66.7  13.4  3203            2154
            20      69.3  13.4  0               3380

    :cvar _default_min_compression_size: The expected minimum compression.
        While packing nodes into the page, we won't Z_SYNC_FLUSH until we have
        received this much input data. This saves time, because we don't bloat
        the result with SYNC entries (and then need to repack), but if it is
        set too high we will accept data that will never fit and trigger a
        fault later.
    """

    _max_repack = 2
    _default_min_compression_size = 1.8

    def __init__(self, chunk_size, reserved=0):
        """Create a ChunkWriter to write chunk_size chunks.

        :param chunk_size: The total byte count to emit at the end of the
            chunk.
        :param reserved: How many bytes to allow for reserved data. reserved
            data space can only be written to via the write_reserved method.
        """
        self.chunk_size = chunk_size
        self.compressor = zlib.compressobj()
        self.bytes_in = []
        self.bytes_list = []
        self.bytes_out_len = 0
        self.compressed = None
        self.seen_bytes = 0
        self.num_repack = 0
        self.unused_bytes = None
        self.reserved_size = reserved
        self.min_compress_size = self._default_min_compression_size

    def finish(self):
        """Finish the chunk.

        This returns the final compressed chunk, and either None, or the
        bytes that did not fit in the chunk.
        """
        self.bytes_in = None # Free the data cached so far, we don't need it
        out = self.compressor.flush(Z_FINISH)
        self.bytes_list.append(out)
        self.bytes_out_len += len(out)
        if self.bytes_out_len > self.chunk_size:
            raise AssertionError('Somehow we ended up with too much'
                                 ' compressed data, %d > %d'
                                 % (self.bytes_out_len, self.chunk_size))
        nulls_needed = self.chunk_size - self.bytes_out_len % self.chunk_size
        if nulls_needed:
            self.bytes_list.append("\x00" * nulls_needed)
        return self.bytes_list, self.unused_bytes, nulls_needed

    def _recompress_all_bytes_in(self, extra_bytes=None):
        """Recompress the current bytes_in, and optionally more.

        :param extra_bytes: Optional, if supplied we will try to add it with
            Z_SYNC_FLUSH
        :return: (bytes_out, compressor, alt_compressed)
            bytes_out   is the compressed bytes returned from the compressor
            compressor  An object with everything packed in so far, and
                        Z_SYNC_FLUSH called.
            alt_compressed  If the compressor supports copy(), then this is a
                            snapshot just before extra_bytes is added.
                            It is (bytes_out, compressor) as well.
                            The idea is if you find you cannot fit the new
                            bytes, you don't have to start over.
                            And if you *can* you don't have to Z_SYNC_FLUSH
                            yet.
        """
        compressor = zlib.compressobj()
        bytes_out = []
        append = bytes_out.append
        compress = compressor.compress
        for accepted_bytes in self.bytes_in:
            out = compress(accepted_bytes)
            if out:
                append(out)
        if extra_bytes:
            out = compress(extra_bytes)
            out += compressor.flush(Z_SYNC_FLUSH)
            if out:
                append(out)
        bytes_out_len = sum(map(len, bytes_out))
        return bytes_out, bytes_out_len, compressor

    def write(self, bytes, reserved=False):
        """Write some bytes to the chunk.

        If the bytes fit, False is returned. Otherwise True is returned
        and the bytes have not been added to the chunk.
        """
        if reserved:
            capacity = self.chunk_size
        else:
            capacity = self.chunk_size - self.reserved_size
        # Check quickly to see if this is likely to put us outside of our
        # budget:
        next_seen_size = self.seen_bytes + len(bytes)
        comp = self.compressor
        if (next_seen_size < self.min_compress_size * capacity):
            # No need, we assume this will "just fit"
            out = comp.compress(bytes)
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)
            self.bytes_in.append(bytes)
            self.seen_bytes = next_seen_size
        else:
            if self.num_repack > self._max_repack and not reserved:
                self.unused_bytes = bytes
                return True
            # This may or may not fit, try to add it with Z_SYNC_FLUSH
            out = comp.compress(bytes)
            out += comp.flush(Z_SYNC_FLUSH)
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)
            if self.bytes_out_len + 10 <= capacity:
                # It fit, so mark it added
                self.bytes_in.append(bytes)
                self.seen_bytes = next_seen_size
            else:
                # We are over budget, try to squeeze this in without any
                # Z_SYNC_FLUSH calls
                self.num_repack += 1
                (bytes_out, this_len,
                 compressor) = self._recompress_all_bytes_in(bytes)
                if self.num_repack >= self._max_repack:
                    # When we get *to* _max_repack, bump over so that the
                    # earlier > _max_repack will be triggered.
                    self.num_repack += 1
                    _stats[0] += 1
                if this_len + 10 > capacity:
                    # In real-world testing, this only happens when _max_repack
                    # is set >2, and even then rarely (46 out of 1022)
                    (bytes_out, this_len,
                     compressor) = self._recompress_all_bytes_in()
                    _stats[1] += 1
                    self.compressor = compressor
                    self.bytes_list = bytes_out
                    self.bytes_out_len = this_len
                    self.unused_bytes = bytes
                    return True
                else:
                    # This fits when we pack it tighter, so use the new packing
                    # There is one Z_SYNC_FLUSH call in
                    # _recompress_all_bytes_in
                    _stats[2] += 1
                    self.compressor = compressor
                    self.bytes_in.append(bytes)
                    self.bytes_list = bytes_out
                    self.bytes_out_len = this_len
        return False


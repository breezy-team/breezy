# index2, a bzr plugin providing experimental index types.
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

"""ChunkWriter: write compressed data out with a fixed upper bound."""

import zlib
from zlib import Z_FINISH, Z_SYNC_FLUSH


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
    :cvar _default_min_compression_size: The expected minimum compression.
        While packing nodes into the page, we won't Z_SYNC_FLUSH until we have
        received this much input data. This saves time, because we don't bloat
        the result with SYNC entries (and then need to repack), but if it is
        set too high we will accept data that will never fit.
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
        self.bytes_list.append(self.compressor.flush(Z_FINISH))
        total_len = sum(len(b) for b in self.bytes_list)
        if total_len > self.chunk_size:
            raise AssertionError('Somehow we ended up with too much'
                                 ' compressed data, %d > %d'
                                 % (total_len, self.chunk_size))
        nulls_needed = self.chunk_size - total_len % self.chunk_size
        if nulls_needed:
            self.bytes_list.append("\x00" * nulls_needed)
        return self.bytes_list, self.unused_bytes, nulls_needed

    def _recompress_all_bytes_in(self, extra_bytes=None):
        compressor = zlib.compressobj()
        bytes_out = []
        for accepted_bytes in self.bytes_in:
            out = compressor.compress(accepted_bytes)
            if out:
                bytes_out.append(out)
        if extra_bytes:
            out = compressor.compress(extra_bytes)
            if out:
                bytes_out.append(out)
            out = compressor.flush(Z_SYNC_FLUSH)
            if out:
                bytes_out.append(out)
        return bytes_out, compressor

    def write(self, bytes):
        """Write some bytes to the chunk.

        If the bytes fit, False is returned. Otherwise True is returned
        and the bytes have not been added to the chunk.
        """
        return self._write(bytes, False)

    def write_reserved(self, bytes):
        """Write some bytes to the chunk bypassing the reserved check.

        If the bytes fit, False is returned. Otherwise True is returned
        and the bytes have not been added to the chunk.
        """
        return self._write(bytes, True)

    def _write(self, bytes, reserved):
        if reserved:
            capacity = self.chunk_size
        else:
            capacity = self.chunk_size - self.reserved_size
        # Check quickly to see if this is likely to put us outside of our
        # budget:
        next_seen_size = self.seen_bytes + len(bytes)
        if (next_seen_size < self.min_compress_size * capacity):
            # No need, we assume this will "just fit"
            out = self.compressor.compress(bytes)
            self.bytes_in.append(bytes)
            self.seen_bytes = next_seen_size
            if out:
                self.bytes_list.append(out)
        else:
            if not reserved and self.num_repack >= self._max_repack:
                # We have packed too many times already.
                return True
            # This may or may not fit, try to add it with Z_SYNC_FLUSH
            out = self.compressor.compress(bytes)
            if out:
                self.bytes_list.append(out)
            out = self.compressor.flush(Z_SYNC_FLUSH)
            if out:
                self.bytes_list.append(out)
            # TODO: We may want to cache total_len, as the 'sum' call seems to
            #       be showing up a bit on lsprof output
            total_len = sum(map(len, self.bytes_list))
            # Give us some extra room for a final Z_FINISH call.
            if total_len + 10 > capacity:
                # We are over budget, try to squeeze this in without any
                # Z_SYNC_FLUSH calls
                self.num_repack += 1
                bytes_out, compressor = self._recompress_all_bytes_in(bytes)
                this_len = sum(map(len, bytes_out))
                if this_len + 10 > capacity:
                    # No way we can add anymore, we need to re-pack because our
                    # compressor is now out of sync
                    bytes_out, compressor = self._recompress_all_bytes_in()
                    self.compressor = compressor
                    self.bytes_list = bytes_out
                    self.unused_bytes = bytes
                    return True
                else:
                    # This fits when we pack it tighter, so use the new packing
                    self.compressor = compressor
                    self.bytes_in.append(bytes)
                    self.bytes_list = bytes_out
            else:
                # It fit, so mark it added
                self.bytes_in.append(bytes)
                self.seen_bytes = next_seen_size
        return False


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
        In testing, some values for bzr.dev::

                    w/o copy    w/ copy     w/ copy ins w/ copy & save
            repack  time  MB    time  MB    time  MB    time  MB
             1       8.8  5.1    8.9  5.1    9.6  4.4   12.5  4.1
             2       9.6  4.4   10.1  4.3   10.4  4.2   11.1  4.1
             3      10.6  4.2   11.1  4.1   11.2  4.1   11.3  4.1
             4      12.0  4.1
             5      12.6  4.1
            20      12.9  4.1   12.2  4.1   12.3  4.1

        In testing, some values for mysql-unpacked::

                    w/o copy    w/ copy     w/ copy ins w/ copy & save
            repack  time  MB    time  MB    time  MB    time  MB
             1      56.6  16.9              60.7  14.2
             2      59.3  14.1              62.6  13.5  64.3  13.4
             3      64.4  13.5
            20      73.4  13.4

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
            if self.num_repack >= self._max_repack and not reserved:
                # We already know we don't want to try to fit more
                return True
            # This may or may not fit, try to add it with Z_SYNC_FLUSH
            out = comp.compress(bytes)
            out += comp.flush(Z_SYNC_FLUSH)
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)
            if self.bytes_out_len + 10 > capacity:
                # We are over budget, try to squeeze this in without any
                # Z_SYNC_FLUSH calls
                self.num_repack += 1
                bytes_out, this_len, compressor = self._recompress_all_bytes_in(bytes)
                if this_len + 10 > capacity:
                    # No way we can add anymore, we need to re-pack because our
                    # compressor is now out of sync.
                    # This seems to be rarely triggered over
                    #   num_repack > _max_repack
                    bytes_out, this_len, compressor = self._recompress_all_bytes_in()
                    self.compressor = compressor
                    self.bytes_list = bytes_out
                    self.bytes_out_len = this_len
                    self.unused_bytes = bytes
                    return True
                else:
                    # This fits when we pack it tighter, so use the new packing
                    # There is one Z_SYNC_FLUSH call in
                    # _recompress_all_bytes_in
                    self.compressor = compressor
                    self.bytes_in.append(bytes)
                    self.bytes_list = bytes_out
                    self.bytes_out_len = this_len
            else:
                # It fit, so mark it added
                self.bytes_in.append(bytes)
                self.seen_bytes = next_seen_size
        return False


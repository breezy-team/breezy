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

# [max_repack, buffer_full, repacks_with_space, min_compression,
#  total_bytes_in, total_bytes_out, avg_comp,
#  bytes_autopack, bytes_sync_packed]
_stats = [0, 0, 0, 999, 0, 0, 0, 0, 0]

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
    """

    _max_repack = 2

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
        # bytes that have been seen, but not included in a flush to out yet
        self.unflushed_in_bytes = 0
        self.num_repack = 0
        self.done = False # We will accept no more bytes
        self.unused_bytes = None
        self.reserved_size = reserved

    def finish(self):
        """Finish the chunk.

        This returns the final compressed chunk, and either None, or the
        bytes that did not fit in the chunk.
        """
        self.bytes_in = None # Free the data cached so far, we don't need it
        out = self.compressor.flush(Z_FINISH)
        self.bytes_list.append(out)
        self.bytes_out_len += len(out)
        if self.num_repack > 0 and self.bytes_out_len > 0:
            comp = float(self.seen_bytes) / self.bytes_out_len
            if comp < _stats[3]:
                _stats[3] = comp
        _stats[4] += self.seen_bytes
        _stats[5] += self.bytes_out_len
        _stats[6] = float(_stats[4]) / _stats[5]

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
            if out:
                append(out)
        append(compressor.flush(Z_SYNC_FLUSH))
        bytes_out_len = sum(map(len, bytes_out))
        return bytes_out, bytes_out_len, compressor

    def write(self, bytes, reserved=False):
        """Write some bytes to the chunk.

        If the bytes fit, False is returned. Otherwise True is returned
        and the bytes have not been added to the chunk.
        """
        if self.num_repack > self._max_repack and not reserved:
            self.unused_bytes = bytes
            return True
        if reserved:
            capacity = self.chunk_size
        else:
            capacity = self.chunk_size - self.reserved_size
        comp = self.compressor
        # Check to see if the currently unflushed bytes would fit with a bit of
        # room to spare, assuming no compression.
        next_unflushed = self.unflushed_in_bytes + len(bytes)
        remaining_capacity = capacity - self.bytes_out_len - 10
        if (next_unflushed < remaining_capacity):
            # Yes, just push it in, assuming it will fit
            out = comp.compress(bytes)
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)
            self.bytes_in.append(bytes)
            self.seen_bytes += len(bytes)
            self.unflushed_in_bytes += len(bytes)
            _stats[7] += 1 # len(bytes)
        else:
            # This may or may not fit, try to add it with Z_SYNC_FLUSH
            _stats[8] += 1 # len(bytes)
            # Note: It is tempting to do this as a look-ahead pass, and to
            # 'copy()' the compressor before flushing. However, it seems that
            # 'flush()' is when the compressor actually does most work
            # (consider it the real compression pass over the data-so-far).
            # Which means that it is the same thing as increasing repack,
            # similar cost, same benefit. And this way we still have the
            # 'repack' knob that can be adjusted, and not depend on a
            # platform-specific 'copy()' function.
            out = comp.compress(bytes)
            out += comp.flush(Z_SYNC_FLUSH)
            self.unflushed_in_bytes = 0
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)

            # We are a bit extra conservative, because it seems that you *can*
            # get better compression with Z_SYNC_FLUSH than a full compress. It
            # is probably very rare, but we were able to trigger it.
            if self.num_repack == 0:
                safety_margin = 100
            else:
                safety_margin = 10
            if self.bytes_out_len + safety_margin <= capacity:
                # It fit, so mark it added
                self.bytes_in.append(bytes)
                self.seen_bytes += len(bytes)
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
                    (bytes_out, this_len,
                     compressor) = self._recompress_all_bytes_in()
                    _stats[1] += 1
                    self.compressor = compressor
                    # Force us to not allow more data
                    self.num_repack = self._max_repack + 1
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


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
        In testing, some values for 100k nodes::

                            w/o copy            w/ copy             w/ copy & save
            _max_repack     time    node count  time    node count  t       nc
             1               8.0s   704          8.8s   494         14.2    390 #
             2               9.2s   491          9.6s   432 #       12.9    390
             3              10.6s   430 #       10.8s   408         12.0    390
             4              12.5s   406                             12.8    390
             5              13.9s   395
            20              17.7s   390         17.8s   390
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
        self.compressed = None
        self.seen_bytes = 0
        self.num_repack = 0
        self.unused_bytes = None
        self.reserved_size = reserved
        self.min_compress_size = self._default_min_compression_size
        self.num_zsync = 0
        self.compressor_has_copy = (getattr(self.compressor, 'copy', None)
                                    is not None)

    def finish(self):
        """Finish the chunk.

        This returns the final compressed chunk, and either None, or the
        bytes that did not fit in the chunk.
        """
        self.bytes_in = None # Free the data cached so far, we don't need it
        self.bytes_list.append(self.compressor.flush(Z_FINISH))
        total_len = sum(map(len, self.bytes_list))
        if total_len > self.chunk_size:
            raise AssertionError('Somehow we ended up with too much'
                                 ' compressed data, %d > %d'
                                 % (total_len, self.chunk_size))
        nulls_needed = self.chunk_size - total_len % self.chunk_size
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
        alt_compressed = None
        if extra_bytes:
            if self.compressor_has_copy:
                alt_compressed = (list(bytes_out), compressor.copy())
            out = compress(extra_bytes)
            if out:
                append(out)
            out = compressor.flush(Z_SYNC_FLUSH)
            if out:
                append(out)
        return bytes_out, compressor, alt_compressed

    def write(self, bytes):
        """Write some bytes to the chunk.

        If the bytes fit, False is returned. Otherwise True is returned
        and the bytes have not been added to the chunk.
        """
        # TODO: lsprof claims that we spend 0.4/10s in calls to write just to
        #       thunk over to _write. We don't seem to need write_reserved
        #       unless we have blooms, so this *might* be worth removing
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
            if out:
                self.bytes_list.append(out)
            self.bytes_in.append(bytes)
            self.seen_bytes = next_seen_size
        else:
            if not reserved and self.num_repack >= self._max_repack:
            # if (not reserved
            #     and (self.num_repack > self._max_repack
            #          or (self._max_repack == self._max_repack
            #              and not self.compressor_has_copy))):
            #     # We have packed too many times already.
                return True
            if not reserved and self.num_repack == self._max_repack:
                assert self.compressor_has_copy
                # We are trying to sneak in a few more keys before we run out
                # of room, so copy the compressor. If we bust, we stop right
                # now
                copy = self.compressor.copy()
                out = self.compressor.compress(bytes)
                out += self.compressor.flush(Z_SYNC_FLUSH)
                total_len = sum(map(len, self.bytes_list)) + len(out)
                if total_len + 10 > capacity:
                    self.compressor = copy
                    # Don't try any more
                    self.num_repack += 1
                    return True
                # It is tempting to use the copied compressor here, because it
                # is more tightly packed. It gets us to the maximum packing
                # value. However, it adds about the same overhead as setting
                # _max_repack to a higher value
                # self.compressor = copy
                # out = self.compressor.compress(bytes)
                self.bytes_in.append(bytes)
                if out:
                    self.bytes_list.append(out)
                return False
            # This may or may not fit, try to add it with Z_SYNC_FLUSH
            out = self.compressor.compress(bytes)
            if out:
                self.bytes_list.append(out)
            out = self.compressor.flush(Z_SYNC_FLUSH)
            if out:
                self.bytes_list.append(out)
            self.num_zsync += 1
            # TODO: We may want to cache total_len, as the 'sum' call seems to
            #       be showing up a bit on lsprof output
            total_len = sum(map(len, self.bytes_list))
            # Give us some extra room for a final Z_FINISH call.
            if total_len + 10 > capacity:
                # We are over budget, try to squeeze this in without any
                # Z_SYNC_FLUSH calls
                self.num_repack += 1
                if False and self.num_repack >= self._max_repack:
                    this_len = None
                    alt_compressed = None
                else:
                    (bytes_out, compressor,
                     alt_compressed) = self._recompress_all_bytes_in(bytes)
                    this_len = sum(map(len, bytes_out))
                if this_len is None or this_len + 10 > capacity:
                    # No way we can add anymore, we need to re-pack because our
                    # compressor is now out of sync
                    if alt_compressed is None:
                        bytes_out, compressor, _ = self._recompress_all_bytes_in()
                    else:
                        bytes_out, compressor = alt_compressed
                    self.compressor = compressor
                    self.bytes_list = bytes_out
                    self.unused_bytes = bytes
                    return True
                else:
                    # This fits when we pack it tighter, so use the new packing
                    if alt_compressed is not None:
                        # We know it will fit, so put it into another
                        # compressor without Z_SYNC_FLUSH
                        bytes_out, compressor = alt_compressed
                        compressor.compress(bytes)
                        self.num_zsync = 0
                    else:
                        # There is one Z_SYNC_FLUSH call in
                        # _recompress_all_bytes_in
                        self.num_zsync = 1
                    self.compressor = compressor
                    self.bytes_in.append(bytes)
                    self.bytes_list = bytes_out
            else:
                # It fit, so mark it added
                self.bytes_in.append(bytes)
                self.seen_bytes = next_seen_size
        return False


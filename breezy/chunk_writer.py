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

"""ChunkWriter: write compressed data out with a fixed upper bound."""

import zlib
from typing import Optional
from zlib import Z_FINISH, Z_SYNC_FLUSH


class ChunkWriter:
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
        The default is to try to avoid recompressing entirely, but setting this
        to something like 20 will give maximum compression.

    :cvar _max_zsync: Another tunable nob. If _max_repack is set to 0, then you
        can limit the number of times we will try to pack more data into a
        node. This allows us to do a single compression pass, rather than
        trying until we overflow, and then recompressing again.
    """

    #    In testing, some values for bzr.dev::
    #        repack  time  MB   max   full
    #         1       7.5  4.6  1140  0
    #         2       8.4  4.2  1036  1
    #         3       9.8  4.1  1012  278
    #         4      10.8  4.1  728   945
    #        20      11.1  4.1  0     1012
    #        repack = 0
    #        zsync   time  MB    repack  stop_for_z
    #         0       5.0  24.7  0       6270
    #         1       4.3  13.2  0       3342
    #         2       4.9   9.6  0       2414
    #         5       4.8   6.2  0       1549
    #         6       4.8   5.8  1       1435
    #         7       4.8   5.5  19      1337
    #         8       4.4   5.3  81      1220
    #        10       5.3   5.0  260     967
    #        11       5.3   4.9  366     839
    #        12       5.1   4.8  454     731
    #        15       5.8   4.7  704     450
    #        20       5.8   4.6  1133    7

    #    In testing, some values for mysql-unpacked::
    #                next_bytes estim
    #        repack  time  MB    full    stop_for_repack
    #         1            15.4  0       3913
    #         2      35.4  13.7  0       346
    #        20      46.7  13.4  3380    0
    #        repack=0
    #        zsync                       stop_for_z
    #         0      29.5 116.5  0       29782
    #         1      27.8  60.2  0       15356
    #         2      27.8  42.4  0       10822
    #         5      26.8  25.5  0       6491
    #         6      27.3  23.2  13      5896
    #         7      27.5  21.6  29      5451
    #         8      27.1  20.3  52      5108
    #        10      29.4  18.6  195     4526
    #        11      29.2  18.0  421     4143
    #        12      28.0  17.5  702     3738
    #        15      28.9  16.5  1223    2969
    #        20      29.6  15.7  2182    1810
    #        30      31.4  15.4  3891    23

    # Tuple of (num_repack_attempts, num_zsync_attempts)
    # num_zsync_attempts only has meaning if num_repack_attempts is 0.
    _repack_opts_for_speed = (0, 8)
    _repack_opts_for_size = (20, 0)

    def __init__(
        self, chunk_size: int, reserved: int = 0, optimize_for_size: bool = False
    ) -> None:
        """Create a ChunkWriter to write chunk_size chunks.

        :param chunk_size: The total byte count to emit at the end of the
            chunk.
        :param reserved: How many bytes to allow for reserved data. reserved
            data space can only be written to via the write(...,
            reserved=True).
        """
        self.chunk_size = chunk_size
        self.compressor = zlib.compressobj()
        self.bytes_in: list[bytes] = []
        self.bytes_list: list[bytes] = []
        self.bytes_out_len = 0
        # bytes that have been seen, but not included in a flush to out yet
        self.unflushed_in_bytes = 0
        self.num_repack = 0
        self.num_zsync = 0
        self.unused_bytes: Optional[bytes] = None
        self.reserved_size = reserved
        # Default is to make building fast rather than compact
        self.set_optimize(for_size=optimize_for_size)

    def finish(self) -> tuple[list[bytes], Optional[bytes], int]:
        """Finish the chunk.

        This returns the final compressed chunk, and either None, or the
        bytes that did not fit in the chunk.

        :return: (compressed_bytes, unused_bytes, num_nulls_needed)

            * compressed_bytes: a list of bytes that were output from the
              compressor. If the compressed length was not exactly chunk_size,
              the final string will be a string of all null bytes to pad this
              to chunk_size
            * unused_bytes: None, or the last bytes that were added, which we
              could not fit.
            * num_nulls_needed: How many nulls are padded at the end
        """
        self.bytes_in = []
        out = self.compressor.flush(Z_FINISH)
        self.bytes_list.append(out)
        self.bytes_out_len += len(out)

        if self.bytes_out_len > self.chunk_size:
            raise AssertionError(
                "Somehow we ended up with too much"
                " compressed data, %d > %d" % (self.bytes_out_len, self.chunk_size)
            )
        nulls_needed = self.chunk_size - self.bytes_out_len
        if nulls_needed:
            self.bytes_list.append(b"\x00" * nulls_needed)
        return self.bytes_list, self.unused_bytes, nulls_needed

    def set_optimize(self, for_size: bool = True) -> None:
        """Change how we optimize our writes.

        :param for_size: If True, optimize for minimum space usage, otherwise
            optimize for fastest writing speed.
        :return: None
        """
        if for_size:
            opts = ChunkWriter._repack_opts_for_size
        else:
            opts = ChunkWriter._repack_opts_for_speed
        self._max_repack, self._max_zsync = opts

    def _recompress_all_bytes_in(
        self, extra_bytes: Optional[bytes] = None
    ) -> tuple[list[bytes], int, "zlib._Compress"]:
        """Recompress the current bytes_in, and optionally more.

        :param extra_bytes: Optional, if supplied we will add it with
            Z_SYNC_FLUSH
        :return: (bytes_out, bytes_out_len, alt_compressed)

            * bytes_out: is the compressed bytes returned from the compressor
            * bytes_out_len: the length of the compressed output
            * compressor: An object with everything packed in so far, and
              Z_SYNC_FLUSH called.
        """
        compressor = zlib.compressobj()
        bytes_out: list[bytes] = []
        append = bytes_out.append
        compress = compressor.compress
        for accepted_bytes in self.bytes_in:
            out = compress(accepted_bytes)
            if out:
                append(out)
        if extra_bytes:
            out = compress(extra_bytes)
            out += compressor.flush(Z_SYNC_FLUSH)
            append(out)
        bytes_out_len = sum(map(len, bytes_out))
        return bytes_out, bytes_out_len, compressor

    def write(self, bytes: bytes, reserved: bool = False) -> bool:
        """Write some bytes to the chunk.

        If the bytes fit, False is returned. Otherwise True is returned
        and the bytes have not been added to the chunk.

        :param bytes: The bytes to include
        :param reserved: If True, we can use the space reserved in the
            constructor.
        """
        if self.num_repack > self._max_repack and not reserved:
            self.unused_bytes = bytes
            return True
        capacity = self.chunk_size if reserved else self.chunk_size - self.reserved_size
        comp = self.compressor

        # Check to see if the currently unflushed bytes would fit with a bit of
        # room to spare, assuming no compression.
        next_unflushed = self.unflushed_in_bytes + len(bytes)
        remaining_capacity = capacity - self.bytes_out_len - 10
        if next_unflushed < remaining_capacity:
            # looks like it will fit
            out = comp.compress(bytes)
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)
            self.bytes_in.append(bytes)
            self.unflushed_in_bytes += len(bytes)
        else:
            # This may or may not fit, try to add it with Z_SYNC_FLUSH
            # Note: It is tempting to do this as a look-ahead pass, and to
            #       'copy()' the compressor before flushing. However, it seems
            #       that Which means that it is the same thing as increasing
            #       repack, similar cost, same benefit. And this way we still
            #       have the 'repack' knob that can be adjusted, and not depend
            #       on a platform-specific 'copy()' function.
            self.num_zsync += 1
            if self._max_repack == 0 and self.num_zsync > self._max_zsync:
                self.num_repack += 1
                self.unused_bytes = bytes
                return True
            out = comp.compress(bytes)
            out += comp.flush(Z_SYNC_FLUSH)
            self.unflushed_in_bytes = 0
            if out:
                self.bytes_list.append(out)
                self.bytes_out_len += len(out)

            # We are a bit extra conservative, because it seems that you *can*
            # get better compression with Z_SYNC_FLUSH than a full compress. It
            # is probably very rare, but we were able to trigger it.
            safety_margin = 100 if self.num_repack == 0 else 10
            if self.bytes_out_len + safety_margin <= capacity:
                # It fit, so mark it added
                self.bytes_in.append(bytes)
            else:
                # We are over budget, try to squeeze this in without any
                # Z_SYNC_FLUSH calls
                self.num_repack += 1
                (bytes_out, this_len, compressor) = self._recompress_all_bytes_in(bytes)
                if self.num_repack >= self._max_repack:
                    # When we get *to* _max_repack, bump over so that the
                    # earlier > _max_repack will be triggered.
                    self.num_repack += 1
                if this_len + 10 > capacity:
                    (bytes_out, this_len, compressor) = self._recompress_all_bytes_in()
                    self.compressor = compressor
                    # Force us to not allow more data
                    self.num_repack = self._max_repack + 1
                    self.bytes_list = bytes_out
                    self.bytes_out_len = this_len
                    self.unused_bytes = bytes
                    return True
                else:
                    # This fits when we pack it tighter, so use the new packing
                    self.compressor = compressor
                    self.bytes_in.append(bytes)
                    self.bytes_list = bytes_out
                    self.bytes_out_len = this_len
        return False

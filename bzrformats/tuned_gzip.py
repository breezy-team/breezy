# Copyright (C) 2006-2011 Canonical Ltd
# Written by Robert Collins <robert.collins@canonical.com>
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

"""Legacy breezy specific gzip tunings."""

import struct
import zlib

__all__ = ["chunks_to_gzip"]


def U32(i):
    """Return i as an unsigned integer, assuming it fits in 32 bits.

    If it's >= 2GB when viewed as a 32-bit unsigned int, return a long.
    """
    if i < 0:
        i += 1 << 32
    return i


def LOWU32(i):
    """Return the low-order 32 bits of an int, as a non-negative int."""
    return i & 0xFFFFFFFF


def chunks_to_gzip(
    chunks,
    factory=zlib.compressobj,
    level=zlib.Z_DEFAULT_COMPRESSION,
    method=zlib.DEFLATED,
    width=-zlib.MAX_WBITS,
    mem=zlib.DEF_MEM_LEVEL,
    crc32=zlib.crc32,
):
    """Create a gzip file containing chunks and return its content.

    :param chunks: An iterable of strings. Each string can have arbitrary
        layout.
    """
    result = [
        b"\037\213"  # self.fileobj.write('\037\213')  # magic header
        b"\010"  # self.fileobj.write('\010')      # compression method
        # fname = self.filename[:-3]
        # flags = 0
        # if fname:
        #     flags = FNAME
        b"\x00"  # self.fileobj.write(chr(flags))
        b"\0\0\0\0"  # write32u(self.fileobj, long(time.time()))
        b"\002"  # self.fileobj.write('\002')
        b"\377"  # self.fileobj.write('\377')
        # if fname:
        b""  # self.fileobj.write(fname + '\000')
    ]
    # using a compressobj avoids a small header and trailer that the compress()
    # utility function adds.
    compress = factory(level, method, width, mem, 0)
    crc = 0
    total_len = 0
    for chunk in chunks:
        crc = crc32(chunk, crc)
        total_len += len(chunk)
        zbytes = compress.compress(chunk)
        if zbytes:
            result.append(zbytes)
    result.append(compress.flush())
    # size may exceed 2GB, or even 4GB
    result.append(struct.pack("<LL", LOWU32(crc), LOWU32(total_len)))
    return result

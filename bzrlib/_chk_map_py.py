# Copyright (C) 2009 Canonical Ltd
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

"""Python implementation of _search_key functions, etc."""

import zlib
import struct


def _crc32(bit):
    # Depending on python version and platform, zlib.crc32 will return either a
    # signed (<= 2.5 >= 3.0) or an unsigned (2.5, 2.6).
    # http://docs.python.org/library/zlib.html recommends using a mask to force
    # an unsigned value to ensure the same numeric value (unsigned) is obtained
    # across all python versions and platforms.
    # Note: However, on 32-bit platforms this causes an upcast to PyLong, which
    #       are generally slower than PyInts. However, if performance becomes
    #       critical, we should probably write the whole thing as an extension
    #       anyway.
    #       Though we really don't need that 32nd bit of accuracy. (even 2**24
    #       is probably enough node fan out for realistic trees.)
    return zlib.crc32(bit)&0xFFFFFFFF


def _search_key_16(key):
    """Map the key tuple into a search key string which has 16-way fan out."""
    return '\x00'.join(['%08X' % _crc32(bit) for bit in key])


def _search_key_255(key):
    """Map the key tuple into a search key string which has 255-way fan out.

    We use 255-way because '\n' is used as a delimiter, and causes problems
    while parsing.
    """
    bytes = '\x00'.join([struct.pack('>L', _crc32(bit)) for bit in key])
    return bytes.replace('\n', '_')



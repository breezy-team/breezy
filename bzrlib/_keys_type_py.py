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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""The pure-python implementation of the Keys type.

Note that it is generally just implemented as using tuples of tuples of
strings.
"""


def Key(*args):
    """Implemented as just returning a tuple of the arguments supplied."""
    for bit in args:
        if not isinstance(bit, str):
            raise TypeError('key bits must be strings')
    num_keys = len(args)
    if num_keys <= 0 or num_keys > 256:
        raise ValueError('must have 1 => 256 key bits')
    return args


def Keys(width, *args):
    if not isinstance(width, int):
        raise TypeError('width must be an integer.')
    if width <= 0 or width > 256:
        raise ValueError('width must be in the range 1 => 256')
    num_keys = len(args) // width
    if (num_keys * width != len(args)):
        raise ValueError('number of entries not a multiple of width')
    if num_keys > 256:
        raise ValueError('too many keys [must be <= 256 keys]')
    result = []
    for i in xrange(0, num_keys):
        start = i*width
        key = args[start:start+width]
        for bit in key:
            if not isinstance(bit, str):
                raise TypeError('key bits must be strings')
        result.append(key)
    return tuple(result)

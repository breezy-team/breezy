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


class Key(object):
    """A Key type, similar to a tuple of strings."""

    __slots__ = ('_tuple',)

    def __init__(self, *args):
        """Create a new 'Key'"""
        for bit in args:
            if not isinstance(bit, str):
                raise TypeError('key bits must be strings')
        num_keys = len(args)
        if num_keys <= 0 or num_keys > 256:
            raise ValueError('must have 1 => 256 key bits')
        self._tuple = args

    def __repr__(self):
        return repr(self._tuple)

    def __hash__(self):
        return hash(self._tuple)

    def __eq__(self, other):
        if isinstance(other, Key):
            return self._tuple == other._tuple
        if isinstance(other, tuple):
            return other == self._tuple
        return NotImplemented

    def __len__(self):
        return len(self._tuple)

    def __cmp__(self, other):
        return cmp(self._tuple, other)

    def __getitem__(self, idx):
        return self._tuple[idx]

    def as_tuple(self):
        return self._tuple



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


_intern = {}

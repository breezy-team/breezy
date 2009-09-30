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

"""The pure-python implementation of the StaticTuple type.

Note that it is generally just implemented as using tuples of tuples of
strings.
"""


class StaticTuple(object):
    """A static type, similar to a tuple of strings."""

    __slots__ = ('_tuple',)

    def __init__(self, *args):
        """Create a new 'StaticTuple'"""
        for bit in args:
            if not isinstance(bit, str) and not isinstance(bit, StaticTuple):
                raise TypeError('key bits must be strings or StaticTuple')
        num_keys = len(args)
        if num_keys < 0 or num_keys > 255:
            raise ValueError('must have 1 => 256 key bits')
        self._tuple = args

    def __repr__(self):
        return repr(self._tuple)

    def __hash__(self):
        return hash(self._tuple)

    def __eq__(self, other):
        if isinstance(other, StaticTuple):
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

    def intern(self):
        return _interned_keys.setdefault(self, self)


_interned_keys = {}

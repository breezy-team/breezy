# Copyright (C) 2005 Canonical Ltd
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

from __future__ import absolute_import

# Author: Martin Pool <mbp@canonical.com>


# Somewhat surprisingly, it turns out that this is much slower than
# simply storing the ints in a set() type.  Python's performance model
# is very different to that of C.


class IntSet(Exception):
    """Faster set-like class storing only whole numbers.

    Despite the name this stores long integers happily, but negative
    values are not allowed.

    >>> a = IntSet([0, 2, 5])
    >>> bool(a)
    True
    >>> 2 in a
    True
    >>> 4 in a
    False
    >>> a.add(4)
    >>> 4 in a
    True

    >>> b = IntSet()
    >>> not b
    True
    >>> b.add(10)
    >>> 10 in a
    False
    >>> a.update(b)
    >>> 10 in a
    True
    >>> a.update(range(5))
    >>> 3 in a
    True

    Being a set, duplicates are ignored:
    >>> a = IntSet()
    >>> a.add(10)
    >>> a.add(10)
    >>> 10 in a
    True
    >>> list(a)
    [10]

    """
    __slots__ = ['_val']

    def __init__(self, values=None, bitmask=0):
        """Create a new intset.

        values
            If specified, an initial collection of values.
        """
        self._val = bitmask
        if values is not None:
            self.update(values)

    def __bool__(self):
        """IntSets are false if empty, otherwise True.

        >>> bool(IntSet())
        False

        >>> bool(IntSet([0]))
        True
        """
        return bool(self._val)

    __nonzero__ = __bool__

    def __len__(self):
        """Number of elements in set.

        >>> len(IntSet(xrange(20000)))
        20000
        """
        v = self._val
        c = 0
        while v:
            if v & 1:
                c += 1
            v = v >> 1
        return c

    def __and__(self, other):
        """Set intersection.

        >>> a = IntSet(range(10))
        >>> len(a)
        10
        >>> b = a & a
        >>> b == a
        True
        >>> a = a & IntSet([5, 7, 11, 13])
        >>> list(a)
        [5, 7]
        """
        if not isinstance(other, IntSet):
            raise NotImplementedError(type(other))
        return IntSet(bitmask=(self._val & other._val))

    def __or__(self, other):
        """Set union.

        >>> a = IntSet(range(10)) | IntSet([5, 15, 25])
        >>> len(a)
        12
        """
        if not isinstance(other, IntSet):
            raise NotImplementedError(type(other))
        return IntSet(bitmask=(self._val | other._val))

    def __eq__(self, other):
        """Comparison.

        >>> IntSet(range(3)) == IntSet([2, 0, 1])
        True
        """
        if isinstance(other, IntSet):
            return self._val == other._val
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __contains__(self, i):
        return self._val & (1 << i)

    def __iter__(self):
        """Return contents of set.

        >>> list(IntSet())
        []
        >>> list(IntSet([0, 1, 5, 7]))
        [0, 1, 5, 7]
        """
        v = self._val
        o = 0
        # XXX: This is a bit slow
        while v:
            if v & 1:
                yield o
            v = v >> 1
            o = o + 1

    def update(self, to_add):
        """Add all the values from the sequence or intset to_add"""
        if isinstance(to_add, IntSet):
            self._val |= to_add._val
        else:
            for i in to_add:
                self._val |= (1 << i)

    def add(self, to_add):
        self._val |= (1 << to_add)

    def remove(self, to_remove):
        """Remove one value from the set.

        Raises KeyError if the value is not present.

        >>> a = IntSet([10])
        >>> a.remove(9)
        Traceback (most recent call last):
          File "/usr/lib/python2.4/doctest.py", line 1243, in __run
            compileflags, 1) in test.globs
          File "<doctest __main__.IntSet.remove[1]>", line 1, in ?
            a.remove(9)
        KeyError: 9
        >>> a.remove(10)
        >>> not a
        True
        """
        m = 1 << to_remove
        if not self._val & m:
            raise KeyError(to_remove)
        self._val ^= m

    def set_remove(self, to_remove):
        """Remove all values that exist in to_remove.

        >>> a = IntSet(range(10))
        >>> b = IntSet([2,3,4,7,12])
        >>> a.set_remove(b)
        >>> list(a)
        [0, 1, 5, 6, 8, 9]
        >>> a.set_remove([1,2,5])
        >>> list(a)
        [0, 6, 8, 9]
        """
        if not isinstance(to_remove, IntSet):
            self.set_remove(IntSet(to_remove))
            return
        intersect = self._val & to_remove._val
        self._val ^= intersect

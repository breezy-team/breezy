# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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

"""Tests for the StaticTupleInterned type."""

import sys

from breezy import (
    tests,
    )
from breezy.tests import (
    features,
    )

try:
    from .. import _simple_set_pyx
except ImportError:
    _simple_set_pyx = None


class _Hashable(object):
    """A simple object which has a fixed hash value.

    We could have used an 'int', but it turns out that Int objects don't
    implement tp_richcompare in Python 2.
    """

    def __init__(self, the_hash):
        self.hash = the_hash

    def __hash__(self):
        return self.hash

    def __eq__(self, other):
        if not isinstance(other, _Hashable):
            return NotImplemented
        return other.hash == self.hash


class _BadSecondHash(_Hashable):

    def __init__(self, the_hash):
        _Hashable.__init__(self, the_hash)
        self._first = True

    def __hash__(self):
        if self._first:
            self._first = False
            return self.hash
        else:
            raise ValueError('I can only be hashed once.')


class _BadCompare(_Hashable):

    def __eq__(self, other):
        raise RuntimeError('I refuse to play nice')

    __hash__ = _Hashable.__hash__


class _NoImplementCompare(_Hashable):

    def __eq__(self, other):
        return NotImplemented

    __hash__ = _Hashable.__hash__


# Even though this is an extension, we don't permute the tests for a python
# version. As the plain python version is just a dict or set
compiled_simpleset_feature = features.ModuleAvailableFeature(
    'breezy.bzr._simple_set_pyx')


class TestSimpleSet(tests.TestCase):

    _test_needs_features = [compiled_simpleset_feature]
    module = _simple_set_pyx

    def assertFillState(self, used, fill, mask, obj):
        self.assertEqual((used, fill, mask), (obj.used, obj.fill, obj.mask))

    def assertLookup(self, offset, value, obj, key):
        self.assertEqual((offset, value), obj._test_lookup(key))

    def assertRefcount(self, count, obj):
        """Assert that the refcount for obj is what we expect.

        Note that this automatically adjusts for the fact that calling
        assertRefcount actually creates a new pointer, as does calling
        sys.getrefcount. So pass the expected value *before* the call.
        """
        # I'm not sure why the offset is 3, but I've check that in the caller,
        # an offset of 1 works, which is expected. Not sure why assertRefcount
        # is incrementing/decrementing 2 times
        self.assertEqual(count, sys.getrefcount(obj) - 3)

    def test_initial(self):
        obj = self.module.SimpleSet()
        self.assertEqual(0, len(obj))
        self.assertFillState(0, 0, 0x3ff, obj)

    def test__lookup(self):
        # These are carefully chosen integers to force hash collisions in the
        # algorithm, based on the initial set size of 1024
        obj = self.module.SimpleSet()
        self.assertLookup(643, '<null>', obj, _Hashable(643))
        self.assertLookup(643, '<null>', obj, _Hashable(643 + 1024))
        self.assertLookup(643, '<null>', obj, _Hashable(643 + 50 * 1024))

    def test__lookup_collision(self):
        obj = self.module.SimpleSet()
        k1 = _Hashable(643)
        k2 = _Hashable(643 + 1024)
        self.assertLookup(643, '<null>', obj, k1)
        self.assertLookup(643, '<null>', obj, k2)
        obj.add(k1)
        self.assertLookup(643, k1, obj, k1)
        self.assertLookup(644, '<null>', obj, k2)

    def test__lookup_after_resize(self):
        obj = self.module.SimpleSet()
        k1 = _Hashable(643)
        k2 = _Hashable(643 + 1024)
        obj.add(k1)
        obj.add(k2)
        self.assertLookup(643, k1, obj, k1)
        self.assertLookup(644, k2, obj, k2)
        obj._py_resize(2047)  # resized to 2048
        self.assertEqual(2048, obj.mask + 1)
        self.assertLookup(643, k1, obj, k1)
        self.assertLookup(643 + 1024, k2, obj, k2)
        obj._py_resize(1023)  # resized back to 1024
        self.assertEqual(1024, obj.mask + 1)
        self.assertLookup(643, k1, obj, k1)
        self.assertLookup(644, k2, obj, k2)

    def test_get_set_del_with_collisions(self):
        obj = self.module.SimpleSet()

        h1 = 643
        h2 = 643 + 1024
        h3 = 643 + 1024 * 50
        h4 = 643 + 1024 * 25
        h5 = 644
        h6 = 644 + 1024

        k1 = _Hashable(h1)
        k2 = _Hashable(h2)
        k3 = _Hashable(h3)
        k4 = _Hashable(h4)
        k5 = _Hashable(h5)
        k6 = _Hashable(h6)
        self.assertLookup(643, '<null>', obj, k1)
        self.assertLookup(643, '<null>', obj, k2)
        self.assertLookup(643, '<null>', obj, k3)
        self.assertLookup(643, '<null>', obj, k4)
        self.assertLookup(644, '<null>', obj, k5)
        self.assertLookup(644, '<null>', obj, k6)
        obj.add(k1)
        self.assertIn(k1, obj)
        self.assertNotIn(k2, obj)
        self.assertNotIn(k3, obj)
        self.assertNotIn(k4, obj)
        self.assertLookup(643, k1, obj, k1)
        self.assertLookup(644, '<null>', obj, k2)
        self.assertLookup(644, '<null>', obj, k3)
        self.assertLookup(644, '<null>', obj, k4)
        self.assertLookup(644, '<null>', obj, k5)
        self.assertLookup(644, '<null>', obj, k6)
        self.assertIs(k1, obj[k1])
        self.assertIs(k2, obj.add(k2))
        self.assertIs(k2, obj[k2])
        self.assertLookup(643, k1, obj, k1)
        self.assertLookup(644, k2, obj, k2)
        self.assertLookup(646, '<null>', obj, k3)
        self.assertLookup(646, '<null>', obj, k4)
        self.assertLookup(645, '<null>', obj, k5)
        self.assertLookup(645, '<null>', obj, k6)
        self.assertLookup(643, k1, obj, _Hashable(h1))
        self.assertLookup(644, k2, obj, _Hashable(h2))
        self.assertLookup(646, '<null>', obj, _Hashable(h3))
        self.assertLookup(646, '<null>', obj, _Hashable(h4))
        self.assertLookup(645, '<null>', obj, _Hashable(h5))
        self.assertLookup(645, '<null>', obj, _Hashable(h6))
        obj.add(k3)
        self.assertIs(k3, obj[k3])
        self.assertIn(k1, obj)
        self.assertIn(k2, obj)
        self.assertIn(k3, obj)
        self.assertNotIn(k4, obj)

        obj.discard(k1)
        self.assertLookup(643, '<dummy>', obj, k1)
        self.assertLookup(644, k2, obj, k2)
        self.assertLookup(646, k3, obj, k3)
        self.assertLookup(643, '<dummy>', obj, k4)
        self.assertNotIn(k1, obj)
        self.assertIn(k2, obj)
        self.assertIn(k3, obj)
        self.assertNotIn(k4, obj)

    def test_add(self):
        obj = self.module.SimpleSet()
        self.assertFillState(0, 0, 0x3ff, obj)
        # We use this clumsy notation, because otherwise the refcounts are off.
        # I'm guessing the python compiler sees it is a static tuple, and adds
        # it to the function variables, or somesuch
        k1 = tuple(['foo'])
        self.assertRefcount(1, k1)
        self.assertIs(k1, obj.add(k1))
        self.assertFillState(1, 1, 0x3ff, obj)
        self.assertRefcount(2, k1)
        ktest = obj[k1]
        self.assertRefcount(3, k1)
        self.assertIs(k1, ktest)
        del ktest
        self.assertRefcount(2, k1)
        k2 = tuple(['foo'])
        self.assertRefcount(1, k2)
        self.assertIsNot(k1, k2)
        # doesn't add anything, so the counters shouldn't be adjusted
        self.assertIs(k1, obj.add(k2))
        self.assertFillState(1, 1, 0x3ff, obj)
        self.assertRefcount(2, k1)  # not changed
        self.assertRefcount(1, k2)  # not incremented
        self.assertIs(k1, obj[k1])
        self.assertIs(k1, obj[k2])
        self.assertRefcount(2, k1)
        self.assertRefcount(1, k2)
        # Deleting an entry should remove the fill, but not the used
        obj.discard(k1)
        self.assertFillState(0, 1, 0x3ff, obj)
        self.assertRefcount(1, k1)
        k3 = tuple(['bar'])
        self.assertRefcount(1, k3)
        self.assertIs(k3, obj.add(k3))
        self.assertFillState(1, 2, 0x3ff, obj)
        self.assertRefcount(2, k3)
        self.assertIs(k2, obj.add(k2))
        self.assertFillState(2, 2, 0x3ff, obj)
        self.assertRefcount(1, k1)
        self.assertRefcount(2, k2)
        self.assertRefcount(2, k3)

    def test_discard(self):
        obj = self.module.SimpleSet()
        k1 = tuple(['foo'])
        k2 = tuple(['foo'])
        k3 = tuple(['bar'])
        self.assertRefcount(1, k1)
        self.assertRefcount(1, k2)
        self.assertRefcount(1, k3)
        obj.add(k1)
        self.assertRefcount(2, k1)
        self.assertEqual(0, obj.discard(k3))
        self.assertRefcount(1, k3)
        obj.add(k3)
        self.assertRefcount(2, k3)
        self.assertEqual(1, obj.discard(k3))
        self.assertRefcount(1, k3)

    def test__resize(self):
        obj = self.module.SimpleSet()
        # Need objects with exact hash as checking offset of <null> later
        k1 = _Hashable(501)
        k2 = _Hashable(591)
        k3 = _Hashable(2051)
        obj.add(k1)
        obj.add(k2)
        obj.add(k3)
        obj.discard(k2)
        self.assertFillState(2, 3, 0x3ff, obj)
        self.assertEqual(1024, obj._py_resize(500))
        # Doesn't change the size, but does change the content
        self.assertFillState(2, 2, 0x3ff, obj)
        obj.add(k2)
        obj.discard(k3)
        self.assertFillState(2, 3, 0x3ff, obj)
        self.assertEqual(4096, obj._py_resize(4095))
        self.assertFillState(2, 2, 0xfff, obj)
        self.assertIn(k1, obj)
        self.assertIn(k2, obj)
        self.assertNotIn(k3, obj)
        obj.add(k2)
        self.assertIn(k2, obj)
        obj.discard(k2)
        self.assertEqual((591, '<dummy>'), obj._test_lookup(k2))
        self.assertFillState(1, 2, 0xfff, obj)
        self.assertEqual(2048, obj._py_resize(1024))
        self.assertFillState(1, 1, 0x7ff, obj)
        self.assertEqual((591, '<null>'), obj._test_lookup(k2))

    def test_second_hash_failure(self):
        obj = self.module.SimpleSet()
        k1 = _BadSecondHash(200)
        k2 = _Hashable(200)
        # Should only call hash() one time
        obj.add(k1)
        self.assertFalse(k1._first)
        self.assertRaises(ValueError, obj.add, k2)

    def test_richcompare_failure(self):
        obj = self.module.SimpleSet()
        k1 = _Hashable(200)
        k2 = _BadCompare(200)
        obj.add(k1)
        # Tries to compare with k1, fails
        self.assertRaises(RuntimeError, obj.add, k2)

    def test_richcompare_not_implemented(self):
        obj = self.module.SimpleSet()
        # Even though their hashes are the same, tp_richcompare returns
        # NotImplemented, which means we treat them as not equal
        k1 = _NoImplementCompare(200)
        k2 = _NoImplementCompare(200)
        self.assertLookup(200, '<null>', obj, k1)
        self.assertLookup(200, '<null>', obj, k2)
        self.assertIs(k1, obj.add(k1))
        self.assertLookup(200, k1, obj, k1)
        self.assertLookup(201, '<null>', obj, k2)
        self.assertIs(k2, obj.add(k2))
        self.assertIs(k1, obj[k1])

    def test_add_and_remove_lots_of_items(self):
        obj = self.module.SimpleSet()
        chars = ('ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                 'abcdefghijklmnopqrstuvwxyz1234567890')
        for i in chars:
            for j in chars:
                k = (i, j)
                obj.add(k)
        num = len(chars) * len(chars)
        self.assertFillState(num, num, 0x1fff, obj)
        # Now delete all of the entries and it should shrink again
        for i in chars:
            for j in chars:
                k = (i, j)
                obj.discard(k)
        # It should be back to 1024 wide mask, though there may still be some
        # dummy values in there
        self.assertFillState(0, obj.fill, 0x3ff, obj)
        # but there should be fewer than 1/5th dummy entries
        self.assertTrue(obj.fill < 1024 / 5)

    def test__iter__(self):
        obj = self.module.SimpleSet()
        k1 = ('1',)
        k2 = ('1', '2')
        k3 = ('3', '4')
        obj.add(k1)
        obj.add(k2)
        obj.add(k3)
        all = set()
        for key in obj:
            all.add(key)
        self.assertEqual(sorted([k1, k2, k3]), sorted(all))
        iterator = iter(obj)
        self.assertIn(next(iterator), all)
        obj.add(('foo',))
        # Set changed size
        self.assertRaises(RuntimeError, next, iterator)
        # And even removing an item still causes it to fail
        obj.discard(k2)
        self.assertRaises(RuntimeError, next, iterator)

    def test__sizeof__(self):
        # SimpleSet needs a custom sizeof implementation, because it allocates
        # memory that Python cannot directly see (_table).
        # Too much variability in platform sizes for us to give a fixed size
        # here. However without a custom implementation, __sizeof__ would give
        # us only the size of the object, and not its table. We know the table
        # is at least 4bytes*1024entries in size.
        obj = self.module.SimpleSet()
        self.assertTrue(obj.__sizeof__() > 4096)

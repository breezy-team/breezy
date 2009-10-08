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

"""Tests for the StaticTupleInterned type."""

import sys

from bzrlib import (
    errors,
    osutils,
    tests,
    )

try:
    from bzrlib import _simple_set_pyx
except ImportError:
    _simple_set_pyx = None


# Even though this is an extension, we don't permute the tests for a python
# version. As the plain python version is just a dict or set

class _CompiledSimpleSet(tests.Feature):

    def _probe(self):
        if _simple_set_pyx is None:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._simple_set_pyx'

CompiledSimpleSet = _CompiledSimpleSet()


class TestSimpleSet(tests.TestCase):

    _test_needs_features = [CompiledSimpleSet]
    module = _simple_set_pyx

    def assertIn(self, obj, container):
        self.assertTrue(obj in container,
            '%s not found in %s' % (obj, container))

    def assertNotIn(self, obj, container):
        self.assertTrue(obj not in container,
            'We found %s in %s' % (obj, container))

    def assertFillState(self, used, fill, mask, obj):
        self.assertEqual((used, fill, mask), (obj.used, obj.fill, obj.mask))

    def assertRefcount(self, count, obj):
        """Assert that the refcount for obj is what we expect.

        Note that this automatically adjusts for the fact that calling
        assertRefcount actually creates a new pointer, as does calling
        sys.getrefcount. So pass the expected value *before* the call.
        """
        # I'm not sure why the offset is 3, but I've check that in the caller,
        # an offset of 1 works, which is expected. Not sure why assertRefcount
        # is incrementing/decrementing 2 times
        self.assertEqual(count, sys.getrefcount(obj)-3)

    def test_initial(self):
        obj = self.module.SimpleSet()
        self.assertEqual(0, len(obj))
        st = ('foo', 'bar')
        self.assertFillState(0, 0, 0x3ff, obj)

    def test__lookup(self):
        # The tuple hash function is rather good at entropy. For all integers
        # 0=>1023, hash((i,)) & 1023 maps to a unique output, and hash((i,j))
        # maps to all 1024 fields evenly.
        # However, hash((c,d))& 1023 for characters has an uneven distribution
        # of collisions, for example:
        #  ('a', 'a'), ('f', '4'), ('p', 'r'), ('q', '1'), ('F', 'T'),
        #  ('Q', 'Q'), ('V', 'd'), ('7', 'C')
        # all collide @ 643
        obj = self.module.SimpleSet()
        offset, val = obj._test_lookup(('a', 'a'))
        self.assertEqual(643, offset)
        self.assertEqual('<null>', val)
        offset, val = obj._test_lookup(('f', '4'))
        self.assertEqual(643, offset)
        self.assertEqual('<null>', val)
        offset, val = obj._test_lookup(('p', 'r'))
        self.assertEqual(643, offset)
        self.assertEqual('<null>', val)

    def test_get_set_del_with_collisions(self):
        obj = self.module.SimpleSet()
        k1 = ('a', 'a')
        k2 = ('f', '4') # collides
        k3 = ('p', 'r')
        k4 = ('q', '1')
        self.assertEqual((643, '<null>'), obj._test_lookup(k1))
        self.assertEqual((643, '<null>'), obj._test_lookup(k2))
        self.assertEqual((643, '<null>'), obj._test_lookup(k3))
        self.assertEqual((643, '<null>'), obj._test_lookup(k4))
        obj.add(k1)
        self.assertIn(k1, obj)
        self.assertNotIn(k2, obj)
        self.assertNotIn(k3, obj)
        self.assertNotIn(k4, obj)
        self.assertEqual((643, k1), obj._test_lookup(k1))
        self.assertEqual((787, '<null>'), obj._test_lookup(k2))
        self.assertEqual((787, '<null>'), obj._test_lookup(k3))
        self.assertEqual((787, '<null>'), obj._test_lookup(k4))
        self.assertIs(k1, obj[k1])
        obj.add(k2)
        self.assertIs(k2, obj[k2])
        self.assertEqual((643, k1), obj._test_lookup(k1))
        self.assertEqual((787, k2), obj._test_lookup(k2))
        self.assertEqual((660, '<null>'), obj._test_lookup(k3))
        # Even though k4 collides for the first couple of iterations, the hash
        # perturbation uses the full width hash (not just the masked value), so
        # it now diverges
        self.assertEqual((180, '<null>'), obj._test_lookup(k4))
        self.assertEqual((643, k1), obj._test_lookup(('a', 'a')))
        self.assertEqual((787, k2), obj._test_lookup(('f', '4')))
        self.assertEqual((660, '<null>'), obj._test_lookup(('p', 'r')))
        self.assertEqual((180, '<null>'), obj._test_lookup(('q', '1')))
        obj.add(k3)
        self.assertIs(k3, obj[k3])
        self.assertIn(k1, obj)
        self.assertIn(k2, obj)
        self.assertIn(k3, obj)
        self.assertNotIn(k4, obj)

        del obj[k1]
        self.assertEqual((643, '<dummy>'), obj._test_lookup(k1))
        self.assertEqual((787, k2), obj._test_lookup(k2))
        self.assertEqual((660, k3), obj._test_lookup(k3))
        self.assertEqual((643, '<dummy>'), obj._test_lookup(k4))
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
        self.assertRefcount(2, k1) # not changed
        self.assertRefcount(1, k2) # not incremented
        self.assertIs(k1, obj[k1])
        self.assertIs(k1, obj[k2])
        self.assertRefcount(2, k1)
        self.assertRefcount(1, k2)
        # Deleting an entry should remove the fill, but not the used
        del obj[k1]
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

    def test__delitem__(self):
        obj = self.module.SimpleSet()
        k1 = tuple(['foo'])
        k2 = tuple(['foo'])
        k3 = tuple(['bar'])
        self.assertRefcount(1, k1)
        self.assertRefcount(1, k2)
        self.assertRefcount(1, k3)
        obj.add(k1)
        self.assertRefcount(2, k1)
        self.assertRaises(KeyError, obj.__delitem__, k3)
        self.assertRefcount(1, k3)
        obj.add(k3)
        self.assertRefcount(2, k3)
        del obj[k3]
        self.assertRefcount(1, k3)

    def test__resize(self):
        obj = self.module.SimpleSet()
        k1 = ('foo',)
        k2 = ('bar',)
        k3 = ('baz',)
        obj.add(k1)
        obj.add(k2)
        obj.add(k3)
        del obj[k2]
        self.assertFillState(2, 3, 0x3ff, obj)
        self.assertEqual(1024, obj._py_resize(500))
        # Doesn't change the size, but does change the content
        self.assertFillState(2, 2, 0x3ff, obj)
        obj.add(k2)
        del obj[k3]
        self.assertFillState(2, 3, 0x3ff, obj)
        self.assertEqual(4096, obj._py_resize(4095))
        self.assertFillState(2, 2, 0xfff, obj)
        self.assertIn(k1, obj)
        self.assertIn(k2, obj)
        self.assertNotIn(k3, obj)
        obj.add(k2)
        self.assertIn(k2, obj)
        del obj[k2]
        self.assertEqual((591, '<dummy>'), obj._test_lookup(k2))
        self.assertFillState(1, 2, 0xfff, obj)
        self.assertEqual(2048, obj._py_resize(1024))
        self.assertFillState(1, 1, 0x7ff, obj)
        self.assertEqual((591, '<null>'), obj._test_lookup(k2))

    def test_add_and_remove_lots_of_items(self):
        obj = self.module.SimpleSet()
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz1234567890'
        for i in chars:
            for j in chars:
                k = (i, j)
                obj.add(k)
        num = len(chars)*len(chars)
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
        iterator.next()
        obj.add(('foo',))
        # Set changed size
        self.assertRaises(RuntimeError, iterator.next)
        # And even removing an item still causes it to fail
        del obj[k2]
        self.assertRaises(RuntimeError, iterator.next)

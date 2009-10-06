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

"""Tests for the StaticTuple type."""

import gc
import sys

from bzrlib import (
    _static_tuple_py,
    errors,
    osutils,
    tests,
    )


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ('python', {'module': _static_tuple_py}),
    ]
    suite = loader.suiteClass()
    if CompiledStaticTuple.available():
        from bzrlib import _static_tuple_pyx
        scenarios.append(('C', {'module': _static_tuple_pyx}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledStaticTuple)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


class _CompiledStaticTuple(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._static_tuple_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._static_tuple_pyx'

CompiledStaticTuple = _CompiledStaticTuple()


class _Meliae(tests.Feature):

    def _probe(self):
        try:
            from meliae import scanner
        except ImportError:
            return False
        return True

    def feature_name(self):
        return "Meliae - python memory debugger"

Meliae = _Meliae()


class TestStaticTuple(tests.TestCase):

    def test_create(self):
        k = self.module.StaticTuple('foo')
        k = self.module.StaticTuple('foo', 'bar')

    def test_create_bad_args(self):
        args_256 = ['a']*256
        # too many args
        self.assertRaises(ValueError, self.module.StaticTuple, *args_256)
        args_300 = ['a']*300
        self.assertRaises(ValueError, self.module.StaticTuple, *args_300)
        # not a string
        self.assertRaises(TypeError, self.module.StaticTuple, 10)
        
    def test_as_tuple(self):
        k = self.module.StaticTuple('foo')
        t = k.as_tuple()
        self.assertEqual(('foo',), t)
        k = self.module.StaticTuple('foo', 'bar')
        t = k.as_tuple()
        self.assertEqual(('foo', 'bar'), t)

    def test_len(self):
        k = self.module.StaticTuple()
        self.assertEqual(0, len(k))
        k = self.module.StaticTuple('foo')
        self.assertEqual(1, len(k))
        k = self.module.StaticTuple('foo', 'bar')
        self.assertEqual(2, len(k))
        k = self.module.StaticTuple('foo', 'bar', 'b', 'b', 'b', 'b', 'b')
        self.assertEqual(7, len(k))
        args = ['foo']*255
        k = self.module.StaticTuple(*args)
        self.assertEqual(255, len(k))

    def test_hold_other_static_tuples(self):
        k = self.module.StaticTuple('foo', 'bar')
        k2 = self.module.StaticTuple(k, k)
        self.assertEqual(2, len(k2))
        self.assertIs(k, k2[0])
        self.assertIs(k, k2[1])

    def test_getitem(self):
        k = self.module.StaticTuple('foo', 'bar', 'b', 'b', 'b', 'b', 'z')
        self.assertEqual('foo', k[0])
        self.assertEqual('foo', k[0])
        self.assertEqual('foo', k[0])
        self.assertEqual('z', k[6])
        self.assertEqual('z', k[-1])

    def test_refcount(self):
        f = 'fo' + 'oo'
        num_refs = sys.getrefcount(f)
        k = self.module.StaticTuple(f)
        self.assertEqual(num_refs + 1, sys.getrefcount(f))
        b = k[0]
        self.assertEqual(num_refs + 2, sys.getrefcount(f))
        b = k[0]
        self.assertEqual(num_refs + 2, sys.getrefcount(f))
        c = k[0]
        self.assertEqual(num_refs + 3, sys.getrefcount(f))
        del b, c
        self.assertEqual(num_refs + 1, sys.getrefcount(f))
        del k
        self.assertEqual(num_refs, sys.getrefcount(f))

    def test__repr__(self):
        k = self.module.StaticTuple('foo', 'bar', 'baz', 'bing')
        self.assertEqual("('foo', 'bar', 'baz', 'bing')", repr(k))

    def assertCompareEqual(self, k1, k2):
        self.assertTrue(k1 == k2)
        self.assertTrue(k1 <= k2)
        self.assertTrue(k1 >= k2)
        self.assertFalse(k1 != k2)
        self.assertFalse(k1 < k2)
        self.assertFalse(k1 > k2)

    def test_compare_same_obj(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareEqual(k1, k1)
        k2 = self.module.StaticTuple(k1, k1)
        self.assertCompareEqual(k2, k2)

    def test_compare_equivalent_obj(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareEqual(k1, k2)
        k3 = self.module.StaticTuple(k1, k2)
        k4 = self.module.StaticTuple(k2, k1)
        self.assertCompareEqual(k1, k2)

    def test_compare_similar_obj(self):
        k1 = self.module.StaticTuple('foo' + ' bar', 'bar' + ' baz')
        k2 = self.module.StaticTuple('fo' + 'o bar', 'ba' + 'r baz')
        self.assertCompareEqual(k1, k2)
        k3 = self.module.StaticTuple('foo ' + 'bar', 'bar ' + 'baz')
        k4 = self.module.StaticTuple('f' + 'oo bar', 'b' + 'ar baz')
        k5 = self.module.StaticTuple(k1, k2)
        k6 = self.module.StaticTuple(k3, k4)
        self.assertCompareEqual(k5, k6)

    def assertCompareDifferent(self, k_small, k_big):
        self.assertFalse(k_small == k_big)
        self.assertFalse(k_small >= k_big)
        self.assertFalse(k_small > k_big)
        self.assertTrue(k_small != k_big)
        self.assertTrue(k_small <= k_big)
        self.assertTrue(k_small < k_big)

    def test_compare_vs_none(self):
        k1 = self.module.StaticTuple('baz', 'bing')
        self.assertCompareDifferent(None, k1)
        self.assertCompareDifferent(10, k1)
        # Comparison with a string is poorly-defined, I seem to get failures
        # regardless of which one comes first...
        # self.assertCompareDifferent('baz', k1)

    def test_compare_all_different_same_width(self):
        k1 = self.module.StaticTuple('baz', 'bing')
        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareDifferent(k1, k2)
        k3 = self.module.StaticTuple(k1, k2)
        k4 = self.module.StaticTuple(k2, k1)
        self.assertCompareDifferent(k3, k4)

    def test_compare_some_different(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        k2 = self.module.StaticTuple('foo', 'zzz')
        self.assertCompareDifferent(k1, k2)
        k3 = self.module.StaticTuple(k1, k1)
        k4 = self.module.StaticTuple(k1, k2)
        self.assertCompareDifferent(k3, k4)

    def test_compare_diff_width(self):
        k1 = self.module.StaticTuple('foo')
        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareDifferent(k1, k2)
        k3 = self.module.StaticTuple(k1)
        k4 = self.module.StaticTuple(k1, k2)
        self.assertCompareDifferent(k3, k4)

    def test_compare_to_tuples(self):
        k1 = self.module.StaticTuple('foo')
        self.assertCompareEqual(k1, ('foo',))
        self.assertCompareEqual(('foo',), k1)
        self.assertCompareDifferent(k1, ('foo', 'bar'))
        self.assertCompareDifferent(k1, ('foo', 10))

        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareEqual(k2, ('foo', 'bar'))
        self.assertCompareEqual(('foo', 'bar'), k2)
        self.assertCompareDifferent(k2, ('foo', 'zzz'))
        self.assertCompareDifferent(('foo',), k2)
        self.assertCompareDifferent(('foo', 'aaa'), k2)
        self.assertCompareDifferent(('baz', 'bing'), k2)
        self.assertCompareDifferent(('foo', 10), k2)

        k3 = self.module.StaticTuple(k1, k2)
        self.assertCompareEqual(k3, (('foo',), ('foo', 'bar')))
        self.assertCompareEqual((('foo',), ('foo', 'bar')), k3)
        self.assertCompareEqual(k3, (k1, ('foo', 'bar')))
        self.assertCompareEqual((k1, ('foo', 'bar')), k3)

    def test_hash(self):
        k = self.module.StaticTuple('foo')
        self.assertEqual(hash(k), hash(('foo',)))
        k = self.module.StaticTuple('foo', 'bar', 'baz', 'bing')
        as_tuple = ('foo', 'bar', 'baz', 'bing')
        self.assertEqual(hash(k), hash(as_tuple))
        x = {k: 'foo'}
        # Because k == , it replaces the slot, rather than having both
        # present in the dict.
        self.assertEqual('foo', x[as_tuple])
        x[as_tuple] = 'bar'
        self.assertEqual({as_tuple: 'bar'}, x)

        k2 = self.module.StaticTuple(k)
        as_tuple2 = (('foo', 'bar', 'baz', 'bing'),)
        self.assertEqual(hash(k2), hash(as_tuple2))

    def test_slice(self):
        k = self.module.StaticTuple('foo', 'bar', 'baz', 'bing')
        self.assertEqual(('foo', 'bar'), k[:2])
        self.assertEqual(('baz',), k[2:-1])

    def test_referents(self):
        # We implement tp_traverse so that things like 'meliae' can measure the
        # amount of referenced memory. Unfortunately gc.get_referents() first
        # checks the IS_GC flag before it traverses anything. So there isn't a
        # way to expose it that I can see.
        self.requireFeature(Meliae)
        from meliae import scanner
        strs = ['foo', 'bar', 'baz', 'bing']
        k = self.module.StaticTuple(*strs)
        if self.module is _static_tuple_py:
            # The python version references objects slightly different than the
            # compiled version
            self.assertEqual([k._tuple, _static_tuple_py.StaticTuple],
                             scanner.get_referents(k))
            self.assertEqual(sorted(strs),
                             sorted(scanner.get_referents(k._tuple)))
        else:
            self.assertEqual(sorted(strs), sorted(scanner.get_referents(k)))

    def test_nested_referents(self):
        self.requireFeature(Meliae)

    def test_empty_is_singleton(self):
        self.requireFeature(Meliae)
        from meliae import scanner
        key = self.module.StaticTuple()
        self.assertIs(key, self.module._empty_tuple)
        strs = ['foo', 'bar', 'baz', 'bing']
        k1 = self.module.StaticTuple(*strs[:2])
        k2 = self.module.StaticTuple(*strs[2:])
        k3 = self.module.StaticTuple(k1, k2)
        if self.module is _static_tuple_py:
            # The python version references objects slightly different than the
            # compiled version
            self.assertEqual([k3._tuple, _static_tuple_py.StaticTuple],
                             scanner.get_referents(k3))
            self.assertEqual(sorted([k1, k2]),
                             sorted(scanner.get_referents(k3._tuple)))
        else:
            self.assertEqual(sorted([k1, k2]),
                             sorted(scanner.get_referents(k3)))

    def test_intern(self):
        unique_str1 = 'unique str ' + osutils.rand_chars(20)
        unique_str2 = 'unique str ' + osutils.rand_chars(20)
        key = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertFalse(key in self.module._interned_tuples)
        key2 = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertEqual(key, key2)
        self.assertIsNot(key, key2)
        key3 = key.intern()
        self.assertIs(key, key3)
        self.assertTrue(key in self.module._interned_tuples)
        self.assertEqual(key, self.module._interned_tuples[key])
        key2 = key2.intern()
        self.assertIs(key, key2)

    def test__c_intern_handles_refcount(self):
        if self.module is _static_tuple_py:
            return # Not applicable
        unique_str1 = 'unique str ' + osutils.rand_chars(20)
        unique_str2 = 'unique str ' + osutils.rand_chars(20)
        key = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertFalse(key in self.module._interned_tuples)
        self.assertFalse(key._is_interned())
        key2 = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertEqual(key, key2)
        self.assertIsNot(key, key2)
        refcount = sys.getrefcount(key)
        self.assertEqual(2, refcount)

        key3 = key.intern()
        self.assertIs(key, key3)
        self.assertTrue(key in self.module._interned_tuples)
        self.assertEqual(key, self.module._interned_tuples[key])
        self.assertEqual(3, sys.getrefcount(key))
        del key3
        # We should not increase the refcount just via 'intern'
        self.assertEqual(2, sys.getrefcount(key))
        self.assertTrue(key._is_interned())
        key2 = key2.intern()
        # We have one more ref in 'key2' but otherwise no extra refs
        self.assertEqual(3, sys.getrefcount(key))
        self.assertIs(key, key2)

    def test__c_keys_are_not_immortal(self):
        if self.module is _static_tuple_py:
            return # Not applicable
        unique_str1 = 'unique str ' + osutils.rand_chars(20)
        unique_str2 = 'unique str ' + osutils.rand_chars(20)
        key = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertFalse(key in self.module._interned_tuples)
        self.assertEqual(2, sys.getrefcount(key))
        key = key.intern()
        self.assertEqual(2, sys.getrefcount(key))
        self.assertTrue(key in self.module._interned_tuples)
        self.assertTrue(key._is_interned())
        del key
        # Create a new entry, which would point to the same location
        key = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertEqual(2, sys.getrefcount(key))
        # This old entry in _interned_tuples should be gone
        self.assertFalse(key in self.module._interned_tuples)
        self.assertFalse(key._is_interned())

    def test__c_has_C_API(self):
        if self.module is _static_tuple_py:
            return
        self.assertIsNot(None, self.module._C_API)



class TestStaticTupleInterned(tests.TestCase):

    _test_needs_features = [CompiledStaticTuple]

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
        # I don't understand why it is count+3 here, but it seems to be
        # correct. If I check in the calling function, with:
        # self.assertEqual(count+1, sys.getrefcount(obj))
        # Then it works fine. Something about passing it to assertRefcount is
        # actually double-incrementing (and decrementing) the refcount
        self.assertEqual(count+3, sys.getrefcount(obj))

    def test_initial(self):
        obj = _module.StaticTupleInterner()
        self.assertEqual(0, len(obj))
        st = StaticTuple('foo', 'bar')
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
        obj = _module.StaticTupleInterner()
        offset, val = obj._test_lookup(StaticTuple('a', 'a'))
        self.assertEqual(643, offset)
        self.assertEqual('<null>', val)
        offset, val = obj._test_lookup(StaticTuple('f', '4'))
        self.assertEqual(643, offset)
        self.assertEqual('<null>', val)
        offset, val = obj._test_lookup(StaticTuple('p', 'r'))
        self.assertEqual(643, offset)
        self.assertEqual('<null>', val)

    def test_get_set_del_with_collisions(self):
        obj = _module.StaticTupleInterner()
        k1 = StaticTuple('a', 'a')
        k2 = StaticTuple('f', '4') # collides
        k3 = StaticTuple('p', 'r')
        k4 = StaticTuple('q', '1')
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
        obj = _module.StaticTupleInterner()
        self.assertFillState(0, 0, 0x3ff, obj)
        k1 = StaticTuple('foo')
        self.assertRefcount(1, k1)
        self.assertIs(k1, obj.add(k1))
        self.assertFillState(1, 1, 0x3ff, obj)
        self.assertRefcount(2, k1)
        ktest = obj[k1]
        self.assertRefcount(3, k1)
        self.assertIs(k1, ktest)
        del ktest
        self.assertRefcount(2, k1)
        k2 = StaticTuple('foo')
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
        k3 = StaticTuple('bar')
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
        obj = _module.StaticTupleInterner()
        k1 = StaticTuple('foo')
        k2 = StaticTuple('foo')
        k3 = StaticTuple('bar')
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
        obj = _module.StaticTupleInterner()
        k1 = StaticTuple('foo')
        k2 = StaticTuple('foo')
        k3 = StaticTuple('bar')
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
        obj = _module.StaticTupleInterner()
        k1 = StaticTuple('foo')
        k2 = StaticTuple('bar')
        k3 = StaticTuple('baz')
        obj.add(k1)
        obj.add(k2)
        obj.add(k3)
        del obj[k2]
        self.assertFillState(2, 3, 0x3ff, obj)
        self.assertEqual(1024, obj._resize(500))
        # Doesn't change the size, but does change the content
        self.assertFillState(2, 2, 0x3ff, obj)
        obj.add(k2)
        del obj[k3]
        self.assertFillState(2, 3, 0x3ff, obj)
        self.assertEqual(4096, obj._resize(4095))
        self.assertFillState(2, 2, 0xfff, obj)
        self.assertIn(k1, obj)
        self.assertIn(k2, obj)
        self.assertNotIn(k3, obj)
        obj.add(k2)
        self.assertIn(k2, obj)
        del obj[k2]
        self.assertEqual((591, '<dummy>'), obj._test_lookup(k2))
        self.assertFillState(1, 2, 0xfff, obj)
        self.assertEqual(2048, obj._resize(1024))
        self.assertFillState(1, 1, 0x7ff, obj)
        self.assertEqual((591, '<null>'), obj._test_lookup(k2))

    def test_add_and_remove_lots_of_items(self):
        obj = _module.StaticTupleInterner()
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz1234567890'
        for i in chars:
            for j in chars:
                k = StaticTuple(i, j)
                obj.add(k)
        num = len(chars)*len(chars)
        self.assertFillState(num, num, 0x1fff, obj)
        # Now delete all of the entries and it should shrink again
        for i in chars:
            for j in chars:
                k = StaticTuple(i, j)
                obj.discard(k)
        # It should be back to 1024 wide mask, though there may still be some
        # dummy values in there
        self.assertFillState(0, obj.fill, 0x3ff, obj)
        # but there should be fewer than 1/5th dummy entries
        self.assertTrue(obj.fill < 1024 / 5)

    def test__iter__(self):
        obj = _module.StaticTupleInterner()
        k1 = StaticTuple('1')
        k2 = StaticTuple('1', '2')
        k3 = StaticTuple('3', '4')
        obj.add(k1)
        obj.add(k2)
        obj.add(k3)
        all = set()
        for key in obj:
            all.add(key)
        self.assertEqual(sorted([k1, k2, k3]), sorted(all))
        iterator = iter(obj)
        iterator.next()
        obj.add(StaticTuple('foo'))
        # Set changed size
        self.assertRaises(RuntimeError, iterator.next)
        # And even removing an item still causes it to fail
        del obj[k2]
        self.assertRaises(RuntimeError, iterator.next)

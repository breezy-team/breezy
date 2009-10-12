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
        from bzrlib import _static_tuple_c
        scenarios.append(('C', {'module': _static_tuple_c}))
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
            import bzrlib._static_tuple_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._static_tuple_c'

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

    def assertRefcount(self, count, obj):
        """Assert that the refcount for obj is what we expect.

        Note that this automatically adjusts for the fact that calling
        assertRefcount actually creates a new pointer, as does calling
        sys.getrefcount. So pass the expected value *before* the call.
        """
        # I don't understand why it is getrefcount()-3 here, but it seems to be
        # correct. If I check in the calling function, with:
        # self.assertEqual(count, sys.getrefcount(obj)-1)
        # Then it works fine. Something about passing it to assertRefcount is
        # actually double-incrementing (and decrementing) the refcount
        self.assertEqual(count, sys.getrefcount(obj)-3)

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
        self.assertRaises(IndexError, k.__getitem__, 7)
        self.assertRaises(IndexError, k.__getitem__, 256+7)
        self.assertRaises(IndexError, k.__getitem__, 12024)
        # Python's [] resolver handles the negative arguments, so we can't
        # really test StaticTuple_item() with negative values.
        self.assertRaises(TypeError, k.__getitem__, 'not-an-int')
        self.assertRaises(TypeError, k.__getitem__, '5')

    def test_refcount(self):
        f = 'fo' + 'oo'
        num_refs = sys.getrefcount(f) - 1 #sys.getrefcount() adds one
        k = self.module.StaticTuple(f)
        self.assertRefcount(num_refs + 1, f)
        b = k[0]
        self.assertRefcount(num_refs + 2, f)
        b = k[0]
        self.assertRefcount(num_refs + 2, f)
        c = k[0]
        self.assertRefcount(num_refs + 3, f)
        del b, c
        self.assertRefcount(num_refs + 1, f)
        del k
        self.assertRefcount(num_refs, f)

    def test__repr__(self):
        k = self.module.StaticTuple('foo', 'bar', 'baz', 'bing')
        self.assertEqual("StaticTuple('foo', 'bar', 'baz', 'bing')", repr(k))

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
        try:
            val = k[::2]
        except TypeError:
            # C implementation raises a TypeError, we don't need the
            # implementation yet, so allow this to pass
            pass
        else:
            # Python implementation uses a regular Tuple, so make sure it gives
            # the right result
            self.assertEqual(('foo', 'baz'), val)

    def test_referents(self):
        # We implement tp_traverse so that things like 'meliae' can measure the
        # amount of referenced memory. Unfortunately gc.get_referents() first
        # checks the IS_GC flag before it traverses anything. We could write a
        # helper func, but that won't work for the generic implementation...
        self.requireFeature(Meliae)
        from meliae import scanner
        strs = ['foo', 'bar', 'baz', 'bing']
        k = self.module.StaticTuple(*strs)
        if self.module is _static_tuple_py:
            refs = strs + [self.module.StaticTuple]
        else:
            refs = strs
        self.assertEqual(sorted(refs), sorted(scanner.get_referents(k)))

    def test_nested_referents(self):
        self.requireFeature(Meliae)
        from meliae import scanner
        strs = ['foo', 'bar', 'baz', 'bing']
        k1 = self.module.StaticTuple(*strs[:2])
        k2 = self.module.StaticTuple(*strs[2:])
        k3 = self.module.StaticTuple(k1, k2)
        refs = [k1, k2]
        if self.module is _static_tuple_py:
            refs.append(self.module.StaticTuple)
        self.assertEqual(sorted(refs),
                         sorted(scanner.get_referents(k3)))

    def test_empty_is_singleton(self):
        key = self.module.StaticTuple()
        self.assertIs(key, self.module._empty_tuple)

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
        self.assertRefcount(1, key)
        self.assertFalse(key in self.module._interned_tuples)
        self.assertFalse(key._is_interned())
        key2 = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertRefcount(1, key)
        self.assertRefcount(1, key2)
        self.assertEqual(key, key2)
        self.assertIsNot(key, key2)

        key3 = key.intern()
        self.assertIs(key, key3)
        self.assertTrue(key in self.module._interned_tuples)
        self.assertEqual(key, self.module._interned_tuples[key])
        # key and key3, but we 'hide' the one in _interned_tuples
        self.assertRefcount(2, key)
        del key3
        self.assertRefcount(1, key)
        self.assertTrue(key._is_interned())
        self.assertRefcount(1, key2)
        key3 = key2.intern()
        # key3 now points to key as well, and *not* to key2
        self.assertRefcount(2, key)
        self.assertRefcount(1, key2)
        self.assertIs(key, key3)
        self.assertIsNot(key3, key2)
        del key2
        del key3
        self.assertRefcount(1, key)

    def test__c_keys_are_not_immortal(self):
        if self.module is _static_tuple_py:
            return # Not applicable
        unique_str1 = 'unique str ' + osutils.rand_chars(20)
        unique_str2 = 'unique str ' + osutils.rand_chars(20)
        key = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertFalse(key in self.module._interned_tuples)
        self.assertRefcount(1, key)
        key = key.intern()
        self.assertRefcount(1, key)
        self.assertTrue(key in self.module._interned_tuples)
        self.assertTrue(key._is_interned())
        del key
        # Create a new entry, which would point to the same location
        key = self.module.StaticTuple(unique_str1, unique_str2)
        self.assertRefcount(1, key)
        # This old entry in _interned_tuples should be gone
        self.assertFalse(key in self.module._interned_tuples)
        self.assertFalse(key._is_interned())

    def test__c_has_C_API(self):
        if self.module is _static_tuple_py:
            return
        self.assertIsNot(None, self.module._C_API)

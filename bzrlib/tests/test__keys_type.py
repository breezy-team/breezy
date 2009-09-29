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

"""Tests for the Keys type."""

import gc
import sys

from bzrlib import (
    _keys_type_py,
    errors,
    osutils,
    tests,
    )


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ('python', {'module': _keys_type_py}),
    ]
    suite = loader.suiteClass()
    if CompiledKeysType.available():
        from bzrlib import _keys_type_c
        scenarios.append(('C', {'module': _keys_type_c}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledKeysType)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


class _CompiledKeysType(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._keys_type_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._keys_type_c'

CompiledKeysType = _CompiledKeysType()


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


class TestKeyType(tests.TestCase):

    def test_create(self):
        k = self.module.Key('foo')
        k = self.module.Key('foo', 'bar')

    def test_create_bad_args(self):
        self.assertRaises(ValueError, self.module.Key)
        lots_of_args = ['a']*300
        # too many args
        self.assertRaises(ValueError, self.module.Key, *lots_of_args)
        # not a string
        self.assertRaises(TypeError, self.module.Key, 10)
        
    def test_as_tuple(self):
        k = self.module.Key('foo')
        t = k.as_tuple()
        self.assertEqual(('foo',), t)
        k = self.module.Key('foo', 'bar')
        t = k.as_tuple()
        self.assertEqual(('foo', 'bar'), t)

    def test_len(self):
        k = self.module.Key('foo')
        self.assertEqual(1, len(k))
        k = self.module.Key('foo', 'bar')
        self.assertEqual(2, len(k))
        k = self.module.Key('foo', 'bar', 'b', 'b', 'b', 'b', 'b')
        self.assertEqual(7, len(k))

    def test_getitem(self):
        k = self.module.Key('foo', 'bar', 'b', 'b', 'b', 'b', 'z')
        self.assertEqual('foo', k[0])
        self.assertEqual('foo', k[0])
        self.assertEqual('foo', k[0])
        self.assertEqual('z', k[6])
        self.assertEqual('z', k[-1])

    def test_refcount(self):
        f = 'fo' + 'oo'
        num_refs = sys.getrefcount(f)
        k = self.module.Key(f)
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
        k = self.module.Key('foo', 'bar', 'baz', 'bing')
        self.assertEqual("('foo', 'bar', 'baz', 'bing')", repr(k))

    def assertCompareEqual(self, k1, k2):
        self.assertTrue(k1 == k2)
        self.assertTrue(k1 <= k2)
        self.assertTrue(k1 >= k2)
        self.assertFalse(k1 != k2)
        self.assertFalse(k1 < k2)
        self.assertFalse(k1 > k2)

    def test_compare_same_obj(self):
        k1 = self.module.Key('foo', 'bar')
        self.assertCompareEqual(k1, k1)

    def test_compare_equivalent_obj(self):
        k1 = self.module.Key('foo', 'bar')
        k2 = self.module.Key('foo', 'bar')
        self.assertCompareEqual(k1, k2)

    def test_compare_similar_obj(self):
        k1 = self.module.Key('foo' + ' bar', 'bar' + ' baz')
        k2 = self.module.Key('fo' + 'o bar', 'ba' + 'r baz')
        self.assertCompareEqual(k1, k2)

    def assertCompareDifferent(self, k_small, k_big):
        self.assertFalse(k_small == k_big)
        self.assertFalse(k_small >= k_big)
        self.assertFalse(k_small > k_big)
        self.assertTrue(k_small != k_big)
        self.assertTrue(k_small <= k_big)
        self.assertTrue(k_small < k_big)

    def test_compare_all_different_same_width(self):
        k1 = self.module.Key('baz', 'bing')
        k2 = self.module.Key('foo', 'bar')
        self.assertCompareDifferent(k1, k2)

    def test_compare_some_different(self):
        k1 = self.module.Key('foo', 'bar')
        k2 = self.module.Key('foo', 'zzz')
        self.assertCompareDifferent(k1, k2)

    def test_compare_diff_width(self):
        k1 = self.module.Key('foo')
        k2 = self.module.Key('foo', 'bar')
        self.assertCompareDifferent(k1, k2)

    def test_compare_to_tuples(self):
        k1 = self.module.Key('foo')
        self.assertCompareEqual(k1, ('foo',))
        self.assertCompareEqual(('foo',), k1)
        self.assertCompareDifferent(k1, ('foo', 'bar'))
        self.assertCompareDifferent(k1, ('foo', 10))

        k2 = self.module.Key('foo', 'bar')
        self.assertCompareEqual(k2, ('foo', 'bar'))
        self.assertCompareEqual(('foo', 'bar'), k2)
        self.assertCompareDifferent(k2, ('foo', 'zzz'))
        self.assertCompareDifferent(('foo',), k2)
        self.assertCompareDifferent(('foo', 'aaa'), k2)
        self.assertCompareDifferent(('baz', 'bing'), k2)
        self.assertCompareDifferent(('foo', 10), k2)

    def test_hash(self):
        k = self.module.Key('foo')
        self.assertEqual(hash(k), hash(('foo',)))
        k = self.module.Key('foo', 'bar', 'baz', 'bing')
        as_tuple = ('foo', 'bar', 'baz', 'bing')
        self.assertEqual(hash(k), hash(as_tuple))
        x = {k: 'foo'}
        # Because k == , it replaces the slot, rather than having both
        # present in the dict.
        self.assertEqual('foo', x[as_tuple])
        x[as_tuple] = 'bar'
        self.assertEqual({as_tuple: 'bar'}, x)

    def test_slice(self):
        k = self.module.Key('foo', 'bar', 'baz', 'bing')
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
        k = self.module.Key(*strs)
        if isinstance(k, _keys_type_py.Key):
            # The python version references objects slightly different than the
            # compiled version
            self.assertEqual([k._tuple, _keys_type_py.Key],
                             scanner.get_referents(k))
        else:
            self.assertEqual(sorted(strs), sorted(scanner.get_referents(k)))


class TestKeysType(tests.TestCase):

    def test_create(self):
        k = self.module.Keys(1, 'foo', 'bar')
        k = self.module.Keys(2, 'foo', 'bar')

    def test_create_bad_args(self):
        self.assertRaises(TypeError, self.module.Keys)
        self.assertRaises(TypeError, self.module.Keys, 'foo')
        self.assertRaises(ValueError, self.module.Keys, 0)
        self.assertRaises(ValueError, self.module.Keys, -1)
        self.assertRaises(ValueError, self.module.Keys, -200)
        self.assertRaises(ValueError, self.module.Keys, 2, 'foo')
        self.assertRaises(ValueError, self.module.Keys, 257)
        lots_of_args = ['a']*300
        # too many args
        self.assertRaises(ValueError, self.module.Keys, 1, *lots_of_args)
        self.assertRaises(TypeError, self.module.Keys, 1, 'foo', 10)

    def test_create_and_del_correct_refcount(self):
        s = 'my custom' + ' foo bar'
        n_ref = sys.getrefcount(s)
        k = self.module.Keys(1, s)
        self.assertEqual(n_ref + 1, sys.getrefcount(s))
        del k
        self.assertEqual(n_ref, sys.getrefcount(s))

    def test_getitem(self):
        f = 'fo' + 'o'
        k = self.module.Keys(1, f, 'bar')
        self.assertEqual(('foo',), k[0])
        self.assertEqual(('bar',), k[1])
        self.assertRaises(IndexError, k.__getitem__, 2)
        n_refs = sys.getrefcount(f)
        f_key = k[0]
        # The pure-python version returns a tuple it already created, rather
        # than creating a new one, so the refcount doesn't change
        self.assertTrue(n_refs + 1 >= sys.getrefcount(f) >= n_refs)
        del f_key
        # This is the important check, that the final refcount should be
        # unchanged
        self.assertEqual(n_refs, sys.getrefcount(f))
        self.assertEqual(2, len(k))

    def test_get_wide_key(self):
        k = self.module.Keys(2, 'foo', 'bar', 'baz', 'bing')
        self.assertEqual(('foo', 'bar'), k[0])
        self.assertEqual(('baz', 'bing'), k[1])
        self.assertRaises(IndexError, k.__getitem__, 2)
        self.assertEqual(2, len(k))

    def test_as_tuple(self):
        k = self.module.Keys(2, 'foo', 'bar', 'baz', 'bing')
        if getattr(k, 'as_tuple', None) is not None:
            t = k.as_tuple()
        else:
            t = k # The pure-python form is in tuples already
        self.assertEqual((('foo', 'bar'), ('baz', 'bing')), t)

    def test_repr(self):
        k = self.module.Keys(2, 'foo', 'bar', 'baz', 'bing')
        self.assertEqual("(('foo', 'bar'), ('baz', 'bing'))", repr(k))

    def test_compare(self):
        k1 = self.module.Keys(2, 'foo', 'bar')
        k2 = self.module.Keys(2, 'baz', 'bing')
        k3 = self.module.Keys(2, 'foo', 'zzz')
        k4 = self.module.Keys(2, 'foo', 'bar')
        # Comparison should be done on the keys themselves, and not based on
        # object id, etc.
        self.assertTrue(k1 == k1)
        self.assertTrue(k1 == k4)
        self.assertTrue(k2 < k1)
        self.assertTrue(k2 < k4)
        self.assertTrue(k3 > k1)
        self.assertTrue(k3 > k4)
        # We should also be able to compare against raw tuples
        self.assertTrue(k1 == (('foo', 'bar'),))

    def test_sorted(self):
        k1 = self.module.Keys(2, 'foo', 'bar', 'baz', 'bing', 'foo', 'zzz')
        self.assertEqual([('baz', 'bing'), ('foo', 'bar'), ('foo', 'zzz')],
                         sorted(k1))

        k1 = self.module.Keys(2, 'foo', 'bar')
        k2 = self.module.Keys(2, 'baz', 'bing')
        k3 = self.module.Keys(2, 'foo', 'zzz')
        self.assertEqual([(('baz', 'bing'),), (('foo', 'bar'),),
                          (('foo', 'zzz'),)], sorted([k1, k2, k3]))

    def test_hash(self):
        k1 = self.module.Keys(2, 'foo', 'bar', 'baz', 'bing', 'foo', 'zzz')
        as_tuple =(('foo', 'bar'), ('baz', 'bing'), ('foo', 'zzz')) 
        self.assertEqual(hash(k1), hash(as_tuple))
        x = {k1: 'foo'}
        # Because k1 == as_tuple, it replaces the slot, rather than having both
        # present in the dict.
        self.assertEqual('foo', x[as_tuple])
        x[as_tuple] = 'bar'
        self.assertEqual({as_tuple: 'bar'}, x)

    def test_referents(self):
        # We implement tp_traverse so that things like 'meliae' can measure the
        # amount of referenced memory. Unfortunately gc.get_referents() first
        # checks the IS_GC flag before it traverses anything. So there isn't a
        # way to expose it that I can see.
        self.requireFeature(Meliae)
        from meliae import scanner
        strs = ['foo', 'bar', 'baz', 'bing']
        k = self.module.Keys(2, *strs)
        if type(k) == tuple:
            self.assertEqual(sorted([('foo', 'bar'), ('baz', 'bing')]),
                             sorted(scanner.get_referents(k)))
        else:
            self.assertEqual(sorted(strs), sorted(scanner.get_referents(k)))

    def test_intern(self):
        unique_str1 = 'unique str ' + osutils.rand_chars(20)
        unique_str2 = 'unique str ' + osutils.rand_chars(20)
        key = self.module.Key(unique_str1, unique_str2)
        self.assertFalse(key in self.module._intern)
        key2 = self.module.Key(unique_str1, unique_str2)
        self.assertEqual(key, key2)
        self.assertIsNot(key, key2)

        refcount = sys.getrefcount(key)
        self.assertEqual(2, refcount)

        # TODO: Eventually the C version will diverge from the python version
        #       here. Namely, it will follow the String route, and interning()
        #       a string will not make it immortal. Instead it will remove
        #       itself from the intern dict when all other references are
        #       removed.
        #       Further, the intern dict may become a custom type rather than a
        #       pure 'dict'.
        key3 = key.intern()
        self.assertIs(key, key3)
        self.assertTrue(key in self.module._intern)
        self.assertEqual(key, self.module._intern[key])
        del key3
        self.assertEqual(4, sys.getrefcount(key))
        key2 = key2.intern()
        self.assertEqual(5, sys.getrefcount(key))
        self.assertIs(key, key2)

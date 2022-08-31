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

"""Tests for the StaticTuple type."""

try:
    import cPickle as pickle
except ImportError:
    import pickle
import operator
import sys

from breezy import (
    debug,
    osutils,
    tests,
    )
from breezy.bzr import (
    _static_tuple_py,
    static_tuple,
    )
from breezy.tests import (
    features,
    )


def load_tests(loader, standard_tests, pattern):
    """Parameterize tests for all versions of groupcompress."""
    global compiled_static_tuple_feature
    suite, compiled_static_tuple_feature = tests.permute_tests_for_extension(
        standard_tests, loader, 'breezy.bzr._static_tuple_py',
        'breezy.bzr._static_tuple_c')
    return suite


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
        self.assertEqual(count, sys.getrefcount(obj) - 3)

    def test_create(self):
        k = self.module.StaticTuple('foo')
        k = self.module.StaticTuple('foo', 'bar')

    def test_create_bad_args(self):
        args_256 = ['a'] * 256
        # too many args
        self.assertRaises(TypeError, self.module.StaticTuple, *args_256)
        args_300 = ['a'] * 300
        self.assertRaises(TypeError, self.module.StaticTuple, *args_300)
        # not a string
        self.assertRaises(TypeError, self.module.StaticTuple, object())

    def test_concat(self):
        st1 = self.module.StaticTuple('foo')
        st2 = self.module.StaticTuple('bar')
        st3 = self.module.StaticTuple('foo', 'bar')
        st4 = st1 + st2
        self.assertEqual(st3, st4)
        self.assertIsInstance(st4, self.module.StaticTuple)

    def test_concat_with_tuple(self):
        st1 = self.module.StaticTuple('foo')
        t2 = ('bar',)
        st3 = self.module.StaticTuple('foo', 'bar')
        st4 = self.module.StaticTuple('bar', 'foo')
        st5 = st1 + t2
        st6 = t2 + st1
        self.assertEqual(st3, st5)
        self.assertIsInstance(st5, self.module.StaticTuple)
        self.assertEqual(st4, st6)
        if self.module is _static_tuple_py:
            # _static_tuple_py has StaticTuple(tuple), so tuple thinks it
            # already knows how to concatenate, as such we can't "inject" our
            # own concatenation...
            self.assertIsInstance(st6, tuple)
        else:
            self.assertIsInstance(st6, self.module.StaticTuple)

    def test_concat_with_bad_tuple(self):
        st1 = self.module.StaticTuple('foo')
        t2 = (object(),)
        # Using st1.__add__ doesn't give the same results as doing the '+' form
        self.assertRaises(TypeError, lambda: st1 + t2)

    def test_concat_with_non_tuple(self):
        st1 = self.module.StaticTuple('foo')
        self.assertRaises(TypeError, lambda: st1 + 10)

    def test_as_tuple(self):
        k = self.module.StaticTuple('foo')
        t = k.as_tuple()
        self.assertEqual(('foo',), t)
        self.assertIsInstance(t, tuple)
        self.assertFalse(isinstance(t, self.module.StaticTuple))
        k = self.module.StaticTuple('foo', 'bar')
        t = k.as_tuple()
        self.assertEqual(('foo', 'bar'), t)
        k2 = self.module.StaticTuple(1, k)
        t = k2.as_tuple()
        self.assertIsInstance(t, tuple)
        # For pickling to work, we need to keep the sub-items as StaticTuple so
        # that it knows that they also need to be converted.
        self.assertIsInstance(t[1], self.module.StaticTuple)
        self.assertEqual((1, ('foo', 'bar')), t)

    def test_as_tuples(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        t = static_tuple.as_tuples(k1)
        self.assertIsInstance(t, tuple)
        self.assertEqual(('foo', 'bar'), t)
        k2 = self.module.StaticTuple(1, k1)
        t = static_tuple.as_tuples(k2)
        self.assertIsInstance(t, tuple)
        self.assertIsInstance(t[1], tuple)
        self.assertEqual((1, ('foo', 'bar')), t)
        mixed = (1, k1)
        t = static_tuple.as_tuples(mixed)
        self.assertIsInstance(t, tuple)
        self.assertIsInstance(t[1], tuple)
        self.assertEqual((1, ('foo', 'bar')), t)

    def test_len(self):
        k = self.module.StaticTuple()
        self.assertEqual(0, len(k))
        k = self.module.StaticTuple('foo')
        self.assertEqual(1, len(k))
        k = self.module.StaticTuple('foo', 'bar')
        self.assertEqual(2, len(k))
        k = self.module.StaticTuple('foo', 'bar', 'b', 'b', 'b', 'b', 'b')
        self.assertEqual(7, len(k))
        args = ['foo'] * 255
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
        self.assertRaises(IndexError, k.__getitem__, 256 + 7)
        self.assertRaises(IndexError, k.__getitem__, 12024)
        # Python's [] resolver handles the negative arguments, so we can't
        # really test StaticTuple_item() with negative values.
        self.assertRaises(TypeError, k.__getitem__, 'not-an-int')
        self.assertRaises(TypeError, k.__getitem__, '5')

    def test_refcount(self):
        f = 'fo' + 'oo'
        num_refs = sys.getrefcount(f) - 1  # sys.getrefcount() adds one
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

    def test_holds_None(self):
        k1 = self.module.StaticTuple(None)
        # You cannot subclass None anyway

    def test_holds_int(self):
        k1 = self.module.StaticTuple(1)

        class subint(int):
            pass
        # But not a subclass, because subint could introduce refcycles
        self.assertRaises(TypeError, self.module.StaticTuple, subint(2))

    def test_holds_float(self):
        k1 = self.module.StaticTuple(1.2)

        class subfloat(float):
            pass
        self.assertRaises(TypeError, self.module.StaticTuple, subfloat(1.5))

    def test_holds_bytes(self):
        k1 = self.module.StaticTuple(b'astring')

        class substr(bytes):
            pass
        self.assertRaises(TypeError, self.module.StaticTuple, substr(b'a'))

    def test_holds_unicode(self):
        k1 = self.module.StaticTuple(u'\xb5')

        class subunicode(str):
            pass
        self.assertRaises(TypeError, self.module.StaticTuple,
                          subunicode(u'\xb5'))

    def test_hold_bool(self):
        k1 = self.module.StaticTuple(True)
        k2 = self.module.StaticTuple(False)
        # Cannot subclass bool

    def test_compare_same_obj(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareEqual(k1, k1)
        k2 = self.module.StaticTuple(k1, k1)
        self.assertCompareEqual(k2, k2)
        k3 = self.module.StaticTuple('foo', 1, None, u'\xb5', 1.2, 2**65, True,
                                     k1)
        self.assertCompareEqual(k3, k3)

    def test_compare_equivalent_obj(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareEqual(k1, k2)
        k3 = self.module.StaticTuple(k1, k2)
        k4 = self.module.StaticTuple(k2, k1)
        self.assertCompareEqual(k1, k2)
        k5 = self.module.StaticTuple('foo', 1, None, u'\xb5', 1.2, 2**65, True,
                                     k1)
        k6 = self.module.StaticTuple('foo', 1, None, u'\xb5', 1.2, 2**65, True,
                                     k1)
        self.assertCompareEqual(k5, k6)
        k7 = self.module.StaticTuple(None)
        k8 = self.module.StaticTuple(None)
        self.assertCompareEqual(k7, k8)

    def test_compare_similar_obj(self):
        k1 = self.module.StaticTuple('foo' + ' bar', 'bar' + ' baz')
        k2 = self.module.StaticTuple('fo' + 'o bar', 'ba' + 'r baz')
        self.assertCompareEqual(k1, k2)
        k3 = self.module.StaticTuple('foo ' + 'bar', 'bar ' + 'baz')
        k4 = self.module.StaticTuple('f' + 'oo bar', 'b' + 'ar baz')
        k5 = self.module.StaticTuple(k1, k2)
        k6 = self.module.StaticTuple(k3, k4)
        self.assertCompareEqual(k5, k6)

    def check_strict_compare(self, k1, k2, mismatched_types):
        """True if on Python 3 and stricter comparison semantics are used."""
        if mismatched_types:
            for op in ("ge", "gt", "le", "lt"):
                self.assertRaises(TypeError, getattr(operator, op), k1, k2)
            return True
        return False

    def assertCompareDifferent(self, k_small, k_big, mismatched_types=False):
        self.assertFalse(k_small == k_big)
        self.assertTrue(k_small != k_big)
        if not self.check_strict_compare(k_small, k_big, mismatched_types):
            self.assertFalse(k_small >= k_big)
            self.assertFalse(k_small > k_big)
            self.assertTrue(k_small <= k_big)
            self.assertTrue(k_small < k_big)

    def assertCompareNoRelation(self, k1, k2, mismatched_types=False):
        """Run the comparison operators, make sure they do something.

        However, we don't actually care what comes first or second. This is
        stuff like cross-class comparisons. We don't want to segfault/raise an
        exception, but we don't care about the sort order.
        """
        self.assertFalse(k1 == k2)
        self.assertTrue(k1 != k2)
        if not self.check_strict_compare(k1, k2, mismatched_types):
            # Do the comparison, but we don't care about the result
            k1 >= k2
            k1 > k2
            k1 <= k2
            k1 < k2

    def test_compare_vs_none(self):
        k1 = self.module.StaticTuple('baz', 'bing')
        self.assertCompareDifferent(None, k1, mismatched_types=True)

    def test_compare_cross_class(self):
        k1 = self.module.StaticTuple('baz', 'bing')
        self.assertCompareNoRelation(10, k1, mismatched_types=True)
        self.assertCompareNoRelation('baz', k1, mismatched_types=True)

    def test_compare_all_different_same_width(self):
        k1 = self.module.StaticTuple('baz', 'bing')
        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareDifferent(k1, k2)
        k3 = self.module.StaticTuple(k1, k2)
        k4 = self.module.StaticTuple(k2, k1)
        self.assertCompareDifferent(k3, k4)
        k5 = self.module.StaticTuple(1)
        k6 = self.module.StaticTuple(2)
        self.assertCompareDifferent(k5, k6)
        k7 = self.module.StaticTuple(1.2)
        k8 = self.module.StaticTuple(2.4)
        self.assertCompareDifferent(k7, k8)
        k9 = self.module.StaticTuple(u's\xb5')
        k10 = self.module.StaticTuple(u's\xe5')
        self.assertCompareDifferent(k9, k10)

    def test_compare_some_different(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        k2 = self.module.StaticTuple('foo', 'zzz')
        self.assertCompareDifferent(k1, k2)
        k3 = self.module.StaticTuple(k1, k1)
        k4 = self.module.StaticTuple(k1, k2)
        self.assertCompareDifferent(k3, k4)
        k5 = self.module.StaticTuple('foo', None)
        self.assertCompareDifferent(k5, k1, mismatched_types=True)
        self.assertCompareDifferent(k5, k2, mismatched_types=True)

    def test_compare_diff_width(self):
        k1 = self.module.StaticTuple('foo')
        k2 = self.module.StaticTuple('foo', 'bar')
        self.assertCompareDifferent(k1, k2)
        k3 = self.module.StaticTuple(k1)
        k4 = self.module.StaticTuple(k1, k2)
        self.assertCompareDifferent(k3, k4)

    def test_compare_different_types(self):
        k1 = self.module.StaticTuple('foo', 'bar')
        k2 = self.module.StaticTuple('foo', 1, None, u'\xb5', 1.2, 2**65, True,
                                     k1)
        self.assertCompareNoRelation(k1, k2, mismatched_types=True)
        k3 = self.module.StaticTuple('foo')
        self.assertCompareDifferent(k3, k1)
        k4 = self.module.StaticTuple(None)
        self.assertCompareDifferent(k4, k1, mismatched_types=True)
        k5 = self.module.StaticTuple(1)
        self.assertCompareNoRelation(k1, k5, mismatched_types=True)

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
        self.assertCompareDifferent(('foo', 10), k2, mismatched_types=True)

        k3 = self.module.StaticTuple(k1, k2)
        self.assertCompareEqual(k3, (('foo',), ('foo', 'bar')))
        self.assertCompareEqual((('foo',), ('foo', 'bar')), k3)
        self.assertCompareEqual(k3, (k1, ('foo', 'bar')))
        self.assertCompareEqual((k1, ('foo', 'bar')), k3)

    def test_compare_mixed_depths(self):
        stuple = self.module.StaticTuple
        k1 = stuple(stuple('a',), stuple('b',))
        k2 = stuple(stuple(stuple('c',), stuple('d',)),
                    stuple('b',))
        # This requires comparing a StaticTuple to a 'string', and then
        # interpreting that value in the next higher StaticTuple. This used to
        # generate a PyErr_BadIternalCall. We now fall back to *something*.
        self.assertCompareNoRelation(k1, k2, mismatched_types=True)

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

        k3 = self.module.StaticTuple('foo', 1, None, u'\xb5', 1.2, 2**65, True,
                                     k)
        as_tuple3 = ('foo', 1, None, u'\xb5', 1.2, 2**65, True, k)
        self.assertEqual(hash(as_tuple3), hash(k3))

    def test_slice(self):
        k = self.module.StaticTuple('foo', 'bar', 'baz', 'bing')
        self.assertEqual(('foo', 'bar'), k[:2])
        self.assertEqual(('baz',), k[2:-1])
        self.assertEqual(('foo', 'baz',), k[::2])
        self.assertRaises(TypeError, k.__getitem__, 'not_slice')

    def test_referents(self):
        # We implement tp_traverse so that things like 'meliae' can measure the
        # amount of referenced memory. Unfortunately gc.get_referents() first
        # checks the IS_GC flag before it traverses anything. We could write a
        # helper func, but that won't work for the generic implementation...
        self.requireFeature(features.meliae)
        from meliae import scanner
        strs = ['foo', 'bar', 'baz', 'bing']
        k = self.module.StaticTuple(*strs)
        if self.module is _static_tuple_py:
            refs = strs + [self.module.StaticTuple]
        else:
            refs = strs
        def key(k):
            if isinstance(k, type):
                return (0, k)
            if isinstance(k, str):
                return (1, k)
            raise TypeError(k)
        self.assertEqual(
            sorted(refs, key=key),
            sorted(scanner.get_referents(k), key=key))

    def test_nested_referents(self):
        self.requireFeature(features.meliae)
        from meliae import scanner
        strs = ['foo', 'bar', 'baz', 'bing']
        k1 = self.module.StaticTuple(*strs[:2])
        k2 = self.module.StaticTuple(*strs[2:])
        k3 = self.module.StaticTuple(k1, k2)
        refs = [k1, k2]
        if self.module is _static_tuple_py:
            refs.append(self.module.StaticTuple)
        def key(k):
            if isinstance(k, type):
                return (0, k)
            if isinstance(k, self.module.StaticTuple):
                return (1, k)
            raise TypeError(k)

        self.assertEqual(sorted(refs, key=key),
                         sorted(scanner.get_referents(k3), key=key))

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
            return  # Not applicable
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
            return  # Not applicable
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

    def test_from_sequence_tuple(self):
        st = self.module.StaticTuple.from_sequence(('foo', 'bar'))
        self.assertIsInstance(st, self.module.StaticTuple)
        self.assertEqual(('foo', 'bar'), st)

    def test_from_sequence_str(self):
        st = self.module.StaticTuple.from_sequence('foo')
        self.assertIsInstance(st, self.module.StaticTuple)
        self.assertEqual(('f', 'o', 'o'), st)

    def test_from_sequence_list(self):
        st = self.module.StaticTuple.from_sequence(['foo', 'bar'])
        self.assertIsInstance(st, self.module.StaticTuple)
        self.assertEqual(('foo', 'bar'), st)

    def test_from_sequence_static_tuple(self):
        st = self.module.StaticTuple('foo', 'bar')
        st2 = self.module.StaticTuple.from_sequence(st)
        # If the source is a StaticTuple already, we return the exact object
        self.assertIs(st, st2)

    def test_from_sequence_not_sequence(self):
        self.assertRaises(TypeError,
                          self.module.StaticTuple.from_sequence, object())
        self.assertRaises(TypeError,
                          self.module.StaticTuple.from_sequence, 10)

    def test_from_sequence_incorrect_args(self):
        self.assertRaises(TypeError,
                          self.module.StaticTuple.from_sequence, object(), 'a')
        self.assertRaises(TypeError,
                          self.module.StaticTuple.from_sequence, foo='a')

    def test_from_sequence_iterable(self):
        st = self.module.StaticTuple.from_sequence(iter(['foo', 'bar']))
        self.assertIsInstance(st, self.module.StaticTuple)
        self.assertEqual(('foo', 'bar'), st)

    def test_from_sequence_generator(self):
        def generate_tuple():
            yield 'foo'
            yield 'bar'
        st = self.module.StaticTuple.from_sequence(generate_tuple())
        self.assertIsInstance(st, self.module.StaticTuple)
        self.assertEqual(('foo', 'bar'), st)

    def test_pickle(self):
        st = self.module.StaticTuple('foo', 'bar')
        pickled = pickle.dumps(st)
        unpickled = pickle.loads(pickled)
        self.assertEqual(unpickled, st)

    def test_pickle_empty(self):
        st = self.module.StaticTuple()
        pickled = pickle.dumps(st)
        unpickled = pickle.loads(pickled)
        self.assertIs(st, unpickled)

    def test_pickle_nested(self):
        st = self.module.StaticTuple('foo', self.module.StaticTuple('bar'))
        pickled = pickle.dumps(st)
        unpickled = pickle.loads(pickled)
        self.assertEqual(unpickled, st)

    def test_static_tuple_thunk(self):
        # Make sure the right implementation is available from
        # breezy.static_tuple.StaticTuple.
        if self.module is _static_tuple_py:
            if compiled_static_tuple_feature.available():
                # We will be using the C version
                return
        self.assertIs(static_tuple.StaticTuple,
                      self.module.StaticTuple)


class TestEnsureStaticTuple(tests.TestCase):

    def test_is_static_tuple(self):
        st = static_tuple.StaticTuple('foo')
        st2 = static_tuple.expect_static_tuple(st)
        self.assertIs(st, st2)

    def test_is_tuple(self):
        t = ('foo',)
        st = static_tuple.expect_static_tuple(t)
        self.assertIsInstance(st, static_tuple.StaticTuple)
        self.assertEqual(t, st)

    def test_flagged_is_static_tuple(self):
        debug.debug_flags.add('static_tuple')
        st = static_tuple.StaticTuple('foo')
        st2 = static_tuple.expect_static_tuple(st)
        self.assertIs(st, st2)

    def test_flagged_is_tuple(self):
        debug.debug_flags.add('static_tuple')
        t = ('foo',)
        self.assertRaises(TypeError, static_tuple.expect_static_tuple, t)

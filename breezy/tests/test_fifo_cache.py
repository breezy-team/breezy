# Copyright (C) 2008 Canonical Ltd
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

"""Tests for the fifo_cache module."""

from .. import (
    fifo_cache,
    tests,
    )


class TestFIFOCache(tests.TestCase):
    """Test that FIFO cache properly keeps track of entries."""

    def test_add_is_present(self):
        c = fifo_cache.FIFOCache()
        c[1] = 2
        self.assertTrue(1 in c)
        self.assertEqual(1, len(c))
        self.assertEqual(2, c[1])
        self.assertEqual(2, c.get(1))
        self.assertEqual(2, c.get(1, None))
        self.assertEqual([1], list(c))
        self.assertEqual({1}, c.keys())
        self.assertEqual([(1, 2)], sorted(c.items()))
        self.assertEqual([2], sorted(c.values()))
        self.assertEqual({1: 2}, c)

    def test_cache_size(self):
        c = fifo_cache.FIFOCache()
        self.assertEqual(100, c.cache_size())
        c.resize(20, 5)
        self.assertEqual(20, c.cache_size())

    def test_missing(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(KeyError, c.__getitem__, 1)
        self.assertFalse(1 in c)
        self.assertEqual(0, len(c))
        self.assertEqual(None, c.get(1))
        self.assertEqual(None, c.get(1, None))
        self.assertEqual([], list(c))
        self.assertEqual(set(), c.keys())
        self.assertEqual([], list(c.items()))
        self.assertEqual([], list(c.values()))
        self.assertEqual({}, c)

    def test_add_maintains_fifo(self):
        c = fifo_cache.FIFOCache(4, 4)
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        self.assertEqual({1, 2, 3, 4}, c.keys())
        c[5] = 6
        # This should pop out the oldest entry
        self.assertEqual({2, 3, 4, 5}, c.keys())
        # Replacing an item doesn't change the stored keys
        c[2] = 7
        self.assertEqual({2, 3, 4, 5}, c.keys())
        # But it does change the position in the FIFO
        c[6] = 7
        self.assertEqual({2, 4, 5, 6}, c.keys())
        self.assertEqual([4, 5, 2, 6], list(c._queue))

    def test_default_after_cleanup_count(self):
        c = fifo_cache.FIFOCache(5)
        self.assertEqual(4, c._after_cleanup_count)
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        c[5] = 6
        # So far, everything fits
        self.assertEqual({1, 2, 3, 4, 5}, c.keys())
        c[6] = 7
        # But adding one more should shrink down to after_cleanup_count
        self.assertEqual({3, 4, 5, 6}, c.keys())

    def test_clear(self):
        c = fifo_cache.FIFOCache(5)
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        c[5] = 6
        c.cleanup()
        self.assertEqual({2, 3, 4, 5}, c.keys())
        c.clear()
        self.assertEqual(set(), c.keys())
        self.assertEqual([], list(c._queue))
        self.assertEqual({}, c)

    def test_copy_not_implemented(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.copy)

    def test_pop_not_implemeted(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.pop, 'key')

    def test_popitem_not_implemeted(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.popitem)

    def test_resize_smaller(self):
        c = fifo_cache.FIFOCache()
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        c[5] = 6
        # No cleanup, because it is the exact size
        c.resize(5)
        self.assertEqual({1: 2, 2: 3, 3: 4, 4: 5, 5: 6}, c)
        self.assertEqual(5, c.cache_size())
        # Adding one more will trigger a cleanup, though
        c[6] = 7
        self.assertEqual({3: 4, 4: 5, 5: 6, 6: 7}, c)
        c.resize(3, 2)
        self.assertEqual({5: 6, 6: 7}, c)

    def test_resize_larger(self):
        c = fifo_cache.FIFOCache(5, 4)
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        c[5] = 6
        # No cleanup, because it is the exact size
        c.resize(10)
        self.assertEqual({1: 2, 2: 3, 3: 4, 4: 5, 5: 6}, c)
        self.assertEqual(10, c.cache_size())
        c[6] = 7
        c[7] = 8
        c[8] = 9
        c[9] = 10
        c[10] = 11
        self.assertEqual({1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9,
                          9: 10, 10: 11}, c)
        c[11] = 12
        self.assertEqual({4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11,
                          11: 12}, c)

    def test_setdefault(self):
        c = fifo_cache.FIFOCache(5, 4)
        c['one'] = 1
        c['two'] = 2
        c['three'] = 3
        myobj = object()
        self.assertIs(myobj, c.setdefault('four', myobj))
        self.assertEqual({'one': 1, 'two': 2, 'three': 3, 'four': myobj}, c)
        self.assertEqual(3, c.setdefault('three', myobj))
        c.setdefault('five', myobj)
        c.setdefault('six', myobj)
        self.assertEqual({'three': 3, 'four': myobj, 'five': myobj,
                          'six': myobj}, c)

    def test_update(self):
        c = fifo_cache.FIFOCache(5, 4)
        # We allow an iterable
        c.update([(1, 2), (3, 4)])
        self.assertEqual({1: 2, 3: 4}, c)
        # Or kwarg form
        c.update(foo=3, bar=4)
        self.assertEqual({1: 2, 3: 4, 'foo': 3, 'bar': 4}, c)
        # Even a dict (This triggers a cleanup)
        c.update({'baz': 'biz', 'bing': 'bang'})
        self.assertEqual({'foo': 3, 'bar': 4, 'baz': 'biz', 'bing': 'bang'}, c)
        # We only allow 1 iterable, just like dict
        self.assertRaises(TypeError, c.update, [(1, 2)], [(3, 4)])
        # But you can mix and match. kwargs take precedence over iterable
        c.update([('a', 'b'), ('d', 'e')], a='c', q='r')
        self.assertEqual({'baz': 'biz', 'bing': 'bang',
                          'a': 'c', 'd': 'e', 'q': 'r'}, c)

    def test_cleanup_funcs(self):
        log = []

        def logging_cleanup(key, value):
            log.append((key, value))
        c = fifo_cache.FIFOCache(5, 4)
        c.add(1, 2, cleanup=logging_cleanup)
        c.add(2, 3, cleanup=logging_cleanup)
        c.add(3, 4, cleanup=logging_cleanup)
        c.add(4, 5, cleanup=None)  # no cleanup for 4
        c[5] = 6  # no cleanup for 5
        self.assertEqual([], log)
        # Adding another key should cleanup 1 & 2
        c.add(6, 7, cleanup=logging_cleanup)
        self.assertEqual([(1, 2), (2, 3)], log)
        del log[:]
        # replacing 3 should trigger a cleanup
        c.add(3, 8, cleanup=logging_cleanup)
        self.assertEqual([(3, 4)], log)
        del log[:]
        c[3] = 9
        self.assertEqual([(3, 8)], log)
        del log[:]
        # Clearing everything should call all remaining cleanups
        c.clear()
        self.assertEqual([(6, 7)], log)
        del log[:]
        c.add(8, 9, cleanup=logging_cleanup)
        # __delitem__ should also trigger a cleanup
        del c[8]
        self.assertEqual([(8, 9)], log)

    def test_cleanup_at_deconstruct(self):
        log = []

        def logging_cleanup(key, value):
            log.append((key, value))
        c = fifo_cache.FIFOCache()
        c.add(1, 2, cleanup=logging_cleanup)
        del c
        # As a matter of design, bzr does not (can not) count on anything
        # being run from Python __del__ methods, because they may not run for
        # a long time, and because in cPython merely having them defined
        # interferes with garbage collection.
        self.assertEqual([], log)


class TestFIFOSizeCache(tests.TestCase):

    def test_add_is_present(self):
        c = fifo_cache.FIFOSizeCache()
        c[1] = '2'
        self.assertTrue(1 in c)
        self.assertEqual(1, len(c))
        self.assertEqual('2', c[1])
        self.assertEqual('2', c.get(1))
        self.assertEqual('2', c.get(1, None))
        self.assertEqual([1], list(c))
        self.assertEqual({1}, c.keys())
        self.assertEqual([(1, '2')], sorted(c.items()))
        self.assertEqual(['2'], sorted(c.values()))
        self.assertEqual({1: '2'}, c)
        self.assertEqual(1024 * 1024, c.cache_size())

    def test_missing(self):
        c = fifo_cache.FIFOSizeCache()
        self.assertRaises(KeyError, c.__getitem__, 1)
        self.assertFalse(1 in c)
        self.assertEqual(0, len(c))
        self.assertEqual(None, c.get(1))
        self.assertEqual(None, c.get(1, None))
        self.assertEqual([], list(c))
        self.assertEqual(set(), c.keys())
        self.assertEqual([], list(c.items()))
        self.assertEqual([], list(c.values()))
        self.assertEqual({}, c)

    def test_add_maintains_fifo(self):
        c = fifo_cache.FIFOSizeCache(10, 8)
        c[1] = 'ab'
        c[2] = 'cde'
        c[3] = 'fghi'
        self.assertEqual({1: 'ab', 2: 'cde', 3: 'fghi'}, c)
        c[4] = 'jkl'  # Collapse
        self.assertEqual({3: 'fghi', 4: 'jkl'}, c)
        # Replacing an item will bump it to the end of the queue
        c[3] = 'mnop'
        self.assertEqual({3: 'mnop', 4: 'jkl'}, c)
        c[5] = 'qrst'
        self.assertEqual({3: 'mnop', 5: 'qrst'}, c)

    def test_adding_large_key(self):
        c = fifo_cache.FIFOSizeCache(10, 8)
        c[1] = 'abcdefgh'  # Adding a large key won't get cached at all
        self.assertEqual({}, c)
        c[1] = 'abcdefg'
        self.assertEqual({1: 'abcdefg'}, c)
        # Replacing with a too-large key will remove it
        c[1] = 'abcdefgh'
        self.assertEqual({}, c)
        self.assertEqual(0, c._value_size)

    def test_resize_smaller(self):
        c = fifo_cache.FIFOSizeCache(20, 16)
        c[1] = 'a'
        c[2] = 'bc'
        c[3] = 'def'
        c[4] = 'ghij'
        # No cleanup, because it is the exact size
        c.resize(10, 8)
        self.assertEqual({1: 'a', 2: 'bc', 3: 'def', 4: 'ghij'}, c)
        self.assertEqual(10, c.cache_size())
        # Adding one more will trigger a cleanup, though
        c[5] = 'k'
        self.assertEqual({3: 'def', 4: 'ghij', 5: 'k'}, c)
        c.resize(5, 4)
        self.assertEqual({5: 'k'}, c)

    def test_resize_larger(self):
        c = fifo_cache.FIFOSizeCache(10, 8)
        c[1] = 'a'
        c[2] = 'bc'
        c[3] = 'def'
        c[4] = 'ghij'
        c.resize(12, 10)
        self.assertEqual({1: 'a', 2: 'bc', 3: 'def', 4: 'ghij'}, c)
        c[5] = 'kl'
        self.assertEqual({1: 'a', 2: 'bc', 3: 'def', 4: 'ghij', 5: 'kl'}, c)
        c[6] = 'mn'
        self.assertEqual({4: 'ghij', 5: 'kl', 6: 'mn'}, c)

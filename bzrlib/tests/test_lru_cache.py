# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the lru_cache module."""

from bzrlib import (
    lru_cache,
    tests,
    )


class TestLRUCache(tests.TestCase):
    """Test that LRU cache properly keeps track of entries."""

    def test_missing(self):
        cache = lru_cache.LRUCache(max_cache=10)

        self.failIf('foo' in cache)
        self.assertRaises(KeyError, cache.__getitem__, 'foo')

        cache['foo'] = 'bar'
        self.assertEqual('bar', cache['foo'])
        self.failUnless('foo' in cache)
        self.failIf('bar' in cache)

    def test_overflow(self):
        """Adding extra entries will pop out old ones."""
        cache = lru_cache.LRUCache(max_cache=1)

        cache['foo'] = 'bar'
        # With a max cache of 1, adding 'baz' should pop out 'foo'
        cache['baz'] = 'biz'

        self.failIf('foo' in cache)
        self.failUnless('baz' in cache)

        self.assertEqual('biz', cache['baz'])

    def test_by_usage(self):
        """Accessing entries bumps them up in priority."""
        cache = lru_cache.LRUCache(max_cache=2)

        cache['baz'] = 'biz'
        cache['foo'] = 'bar'

        self.assertEqual('biz', cache['baz'])

        # This must kick out 'foo' because it was the last accessed
        cache['nub'] = 'in'

        self.failIf('foo' in cache)

    def test_queue_stays_bounded(self):
        """Lots of accesses does not cause the queue to grow without bound."""
        cache = lru_cache.LRUCache(max_cache=10)

        cache['baz'] = 'biz'
        cache['foo'] = 'bar'

        for i in xrange(1000):
            cache['baz']

        self.failUnless(len(cache._queue) < 40)

    def test_cleanup(self):
        """Test that we can use a cleanup function."""
        cleanup_called = []
        def cleanup_func(key, val):
            cleanup_called.append((key, val))

        cache = lru_cache.LRUCache(max_cache=2)

        cache.add('baz', '1', cleanup=cleanup_func)
        cache.add('foo', '2', cleanup=cleanup_func)
        cache.add('biz', '3', cleanup=cleanup_func)

        self.assertEqual([('baz', '1')], cleanup_called)

        # 'foo' is now most recent, so final cleanup will call it last
        cache['foo']
        cache.clear()
        self.assertEqual([('baz', '1'), ('biz', '3'), ('foo', '2')], cleanup_called)

    def test_cleanup_on_replace(self):
        """Replacing an object should cleanup the old value."""
        cleanup_called = []
        def cleanup_func(key, val):
            cleanup_called.append((key, val))

        cache = lru_cache.LRUCache(max_cache=2)
        cache.add(1, 10, cleanup=cleanup_func)
        cache.add(2, 20, cleanup=cleanup_func)
        cache.add(2, 25, cleanup=cleanup_func)

        self.assertEqual([(2, 20)], cleanup_called)
        self.assertEqual(25, cache[2])
        
        # Even __setitem__ should make sure cleanup() is called
        cache[2] = 26
        self.assertEqual([(2, 20), (2, 25)], cleanup_called)

    def test_len(self):
        cache = lru_cache.LRUCache(max_cache=10)

        cache[1] = 10
        cache[2] = 20
        cache[3] = 30
        cache[4] = 40

        self.assertEqual(4, len(cache))

        cache[5] = 50
        cache[6] = 60
        cache[7] = 70
        cache[8] = 80

        self.assertEqual(8, len(cache))

        cache[1] = 15 # replacement

        self.assertEqual(8, len(cache))

        cache[9] = 90
        cache[10] = 100
        cache[11] = 110

        # We hit the max
        self.assertEqual(10, len(cache))

    def test_cleanup_shrinks_to_after_clean_size(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_size=3)

        cache.add(1, 10)
        cache.add(2, 20)
        cache.add(3, 25)
        cache.add(4, 30)
        cache.add(5, 35)

        self.assertEqual(5, len(cache))
        # This will bump us over the max, which causes us to shrink down to
        # after_cleanup_cache size
        cache.add(6, 40)
        self.assertEqual(3, len(cache))

    def test_after_cleanup_larger_than_max(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_size=10)
        self.assertEqual(5, cache._after_cleanup_size)

    def test_after_cleanup_none(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_size=None)
        self.assertEqual(5, cache._after_cleanup_size)

    def test_cleanup(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_size=2)

        # Add these in order
        cache.add(1, 10)
        cache.add(2, 20)
        cache.add(3, 25)
        cache.add(4, 30)
        cache.add(5, 35)

        self.assertEqual(5, len(cache))
        # Force a compaction
        cache.cleanup()
        self.assertEqual(2, len(cache))

    def test_compact_preserves_last_access_order(self):
        cache = lru_cache.LRUCache(max_cache=5)

        # Add these in order
        cache.add(1, 10)
        cache.add(2, 20)
        cache.add(3, 25)
        cache.add(4, 30)
        cache.add(5, 35)

        self.assertEqual([1, 2, 3, 4, 5], list(cache._queue))

        # Now access some randomly
        cache[2]
        cache[5]
        cache[3]
        cache[2]
        self.assertEqual([1, 2, 3, 4, 5, 2, 5, 3, 2], list(cache._queue))
        self.assertEqual({1:1, 2:3, 3:2, 4:1, 5:2}, cache._refcount)

        # Compacting should save the last position
        cache._compact_queue()
        self.assertEqual([1, 4, 5, 3, 2], list(cache._queue))
        self.assertEqual({1:1, 2:1, 3:1, 4:1, 5:1}, cache._refcount)

    def test_get(self):
        cache = lru_cache.LRUCache(max_cache=5)

        cache.add(1, 10)
        cache.add(2, 20)
        self.assertEqual(20, cache.get(2))
        self.assertIs(None, cache.get(3))
        obj = object()
        self.assertIs(obj, cache.get(3, obj))


class TestLRUSizeCache(tests.TestCase):

    def test_basic_init(self):
        cache = lru_cache.LRUSizeCache()
        self.assertEqual(2048, cache._max_cache)
        self.assertEqual(4*2048, cache._compact_queue_length)
        self.assertEqual(cache._max_size, cache._after_cleanup_size)
        self.assertEqual(0, cache._value_size)

    def test_add_tracks_size(self):
        cache = lru_cache.LRUSizeCache()
        self.assertEqual(0, cache._value_size)
        cache.add('my key', 'my value text')
        self.assertEqual(13, cache._value_size)

    def test_remove_tracks_size(self):
        cache = lru_cache.LRUSizeCache()
        self.assertEqual(0, cache._value_size)
        cache.add('my key', 'my value text')
        self.assertEqual(13, cache._value_size)
        cache._remove('my key')
        self.assertEqual(0, cache._value_size)

    def test_no_add_over_size(self):
        """Adding a large value may not be cached at all."""
        cache = lru_cache.LRUSizeCache(max_size=10, after_cleanup_size=5)
        self.assertEqual(0, cache._value_size)
        self.assertEqual({}, cache._cache)
        cache.add('test', 'key')
        self.assertEqual(3, cache._value_size)
        self.assertEqual({'test':'key'}, cache._cache)
        cache.add('test2', 'key that is too big')
        self.assertEqual(3, cache._value_size)
        self.assertEqual({'test':'key'}, cache._cache)
        # If we would add a key, only to cleanup and remove all cached entries,
        # then obviously that value should not be stored
        cache.add('test3', 'bigkey')
        self.assertEqual(3, cache._value_size)
        self.assertEqual({'test':'key'}, cache._cache)

        cache.add('test4', 'bikey')
        self.assertEqual(3, cache._value_size)
        self.assertEqual({'test':'key'}, cache._cache)

    def test_adding_clears_cache_based_on_size(self):
        """The cache is cleared in LRU order until small enough"""
        cache = lru_cache.LRUSizeCache(max_size=20)
        cache.add('key1', 'value') # 5 chars
        cache.add('key2', 'value2') # 6 chars
        cache.add('key3', 'value23') # 7 chars
        self.assertEqual(5+6+7, cache._value_size)
        cache['key2'] # reference key2 so it gets a newer reference time
        cache.add('key4', 'value234') # 8 chars, over limit
        # We have to remove 2 keys to get back under limit
        self.assertEqual(6+8, cache._value_size)
        self.assertEqual({'key2':'value2', 'key4':'value234'},
                         cache._cache)

    def test_adding_clears_to_after_cleanup_size(self):
        cache = lru_cache.LRUSizeCache(max_size=20, after_cleanup_size=10)
        cache.add('key1', 'value') # 5 chars
        cache.add('key2', 'value2') # 6 chars
        cache.add('key3', 'value23') # 7 chars
        self.assertEqual(5+6+7, cache._value_size)
        cache['key2'] # reference key2 so it gets a newer reference time
        cache.add('key4', 'value234') # 8 chars, over limit
        # We have to remove 3 keys to get back under limit
        self.assertEqual(8, cache._value_size)
        self.assertEqual({'key4':'value234'}, cache._cache)

    def test_custom_sizes(self):
        def size_of_list(lst):
            return sum(len(x) for x in lst)
        cache = lru_cache.LRUSizeCache(max_size=20, after_cleanup_size=10,
                                       compute_size=size_of_list)

        cache.add('key1', ['val', 'ue']) # 5 chars
        cache.add('key2', ['val', 'ue2']) # 6 chars
        cache.add('key3', ['val', 'ue23']) # 7 chars
        self.assertEqual(5+6+7, cache._value_size)
        cache['key2'] # reference key2 so it gets a newer reference time
        cache.add('key4', ['value', '234']) # 8 chars, over limit
        # We have to remove 3 keys to get back under limit
        self.assertEqual(8, cache._value_size)
        self.assertEqual({'key4':['value', '234']}, cache._cache)

    def test_cleanup(self):
        cache = lru_cache.LRUSizeCache(max_size=20, after_cleanup_size=10)

        # Add these in order
        cache.add('key1', 'value') # 5 chars
        cache.add('key2', 'value2') # 6 chars
        cache.add('key3', 'value23') # 7 chars
        self.assertEqual(5+6+7, cache._value_size)

        cache.cleanup()
        # Only the most recent fits after cleaning up
        self.assertEqual(7, cache._value_size)

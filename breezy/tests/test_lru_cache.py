# Copyright (C) 2006, 2008, 2009 Canonical Ltd
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

"""Tests for the lru_cache module."""

from .. import lru_cache, tests


def walk_lru(lru):
    """Test helper to walk the LRU list and assert its consistency."""
    node = lru._most_recently_used
    if node is not None and node.prev is not None:
        raise AssertionError(
            "the _most_recently_used entry is not"
            " supposed to have a previous entry"
            f" {node}"
        )
    while node is not None:
        if node.next_key is lru_cache._null_key:
            if node is not lru._least_recently_used:
                raise AssertionError(
                    f"only the last node should have no next value: {node}"
                )
            node_next = None
        else:
            node_next = lru._cache[node.next_key]
            if node_next.prev is not node:
                raise AssertionError(
                    f"inconsistency found, node.next.prev != node: {node}"
                )
        if node.prev is None:
            if node is not lru._most_recently_used:
                raise AssertionError(
                    "only the _most_recently_used should"
                    f" not have a previous node: {node}"
                )
        else:
            if node.prev.next_key != node.key:
                raise AssertionError(
                    f"inconsistency found, node.prev.next != node: {node}"
                )
        yield node
        node = node_next


class TestLRUCache(tests.TestCase):
    """Test that LRU cache properly keeps track of entries."""

    def test_cache_size(self):
        cache = lru_cache.LRUCache(max_cache=10)
        self.assertEqual(10, cache.cache_size())

        cache = lru_cache.LRUCache(max_cache=256)
        self.assertEqual(256, cache.cache_size())

        cache.resize(512)
        self.assertEqual(512, cache.cache_size())

    def test_missing(self):
        cache = lru_cache.LRUCache(max_cache=10)

        self.assertNotIn("foo", cache)
        self.assertRaises(KeyError, cache.__getitem__, "foo")

        cache["foo"] = "bar"
        self.assertEqual("bar", cache["foo"])
        self.assertIn("foo", cache)
        self.assertNotIn("bar", cache)

    def test_map_None(self):
        # Make sure that we can properly map None as a key.
        cache = lru_cache.LRUCache(max_cache=10)
        self.assertNotIn(None, cache)
        cache[None] = 1
        self.assertEqual(1, cache[None])
        cache[None] = 2
        self.assertEqual(2, cache[None])
        # Test the various code paths of __getitem__, to make sure that we can
        # handle when None is the key for the LRU and the MRU
        cache[1] = 3
        cache[None] = 1
        cache[None]
        cache[1]
        cache[None]
        self.assertEqual([None, 1], [n.key for n in walk_lru(cache)])

    def test_add__null_key(self):
        cache = lru_cache.LRUCache(max_cache=10)
        self.assertRaises(ValueError, cache.__setitem__, lru_cache._null_key, 1)

    def test_overflow(self):
        """Adding extra entries will pop out old ones."""
        cache = lru_cache.LRUCache(max_cache=1, after_cleanup_count=1)

        cache["foo"] = "bar"
        # With a max cache of 1, adding 'baz' should pop out 'foo'
        cache["baz"] = "biz"

        self.assertNotIn("foo", cache)
        self.assertIn("baz", cache)

        self.assertEqual("biz", cache["baz"])

    def test_by_usage(self):
        """Accessing entries bumps them up in priority."""
        cache = lru_cache.LRUCache(max_cache=2)

        cache["baz"] = "biz"
        cache["foo"] = "bar"

        self.assertEqual("biz", cache["baz"])

        # This must kick out 'foo' because it was the last accessed
        cache["nub"] = "in"

        self.assertNotIn("foo", cache)

    def test_len(self):
        cache = lru_cache.LRUCache(max_cache=10, after_cleanup_count=10)

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

        cache[1] = 15  # replacement

        self.assertEqual(8, len(cache))

        cache[9] = 90
        cache[10] = 100
        cache[11] = 110

        # We hit the max
        self.assertEqual(10, len(cache))
        self.assertEqual(
            [11, 10, 9, 1, 8, 7, 6, 5, 4, 3], [n.key for n in walk_lru(cache)]
        )

    def test_cleanup_shrinks_to_after_clean_count(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=3)

        cache[1] = 10
        cache[2] = 20
        cache[3] = 25
        cache[4] = 30
        cache[5] = 35

        self.assertEqual(5, len(cache))
        # This will bump us over the max, which causes us to shrink down to
        # after_cleanup_cache size
        cache[6] = 40
        self.assertEqual(3, len(cache))

    def test_after_cleanup_larger_than_max(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=10)
        self.assertEqual(5, cache._after_cleanup_count)

    def test_after_cleanup_none(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=None)
        # By default _after_cleanup_size is 80% of the normal size
        self.assertEqual(4, cache._after_cleanup_count)

    def test_cleanup(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=2)

        # Add these in order
        cache[1] = 10
        cache[2] = 20
        cache[3] = 25
        cache[4] = 30
        cache[5] = 35

        self.assertEqual(5, len(cache))
        # Force a compaction
        cache.cleanup()
        self.assertEqual(2, len(cache))

    def test_preserve_last_access_order(self):
        cache = lru_cache.LRUCache(max_cache=5)

        # Add these in order
        cache[1] = 10
        cache[2] = 20
        cache[3] = 25
        cache[4] = 30
        cache[5] = 35

        self.assertEqual([5, 4, 3, 2, 1], [n.key for n in walk_lru(cache)])

        # Now access some randomly
        cache[2]
        cache[5]
        cache[3]
        cache[2]
        self.assertEqual([2, 3, 5, 4, 1], [n.key for n in walk_lru(cache)])

    def test_get(self):
        cache = lru_cache.LRUCache(max_cache=5)

        cache[1] = 10
        cache[2] = 20
        self.assertEqual(20, cache.get(2))
        self.assertIs(None, cache.get(3))
        obj = object()
        self.assertIs(obj, cache.get(3, obj))
        self.assertEqual([2, 1], [n.key for n in walk_lru(cache)])
        self.assertEqual(10, cache.get(1))
        self.assertEqual([1, 2], [n.key for n in walk_lru(cache)])

    def test_keys(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=5)

        cache[1] = 2
        cache[2] = 3
        cache[3] = 4
        self.assertEqual([1, 2, 3], sorted(cache.keys()))
        cache[4] = 5
        cache[5] = 6
        cache[6] = 7
        self.assertEqual([2, 3, 4, 5, 6], sorted(cache.keys()))

    def test_resize_smaller(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=4)
        cache[1] = 2
        cache[2] = 3
        cache[3] = 4
        cache[4] = 5
        cache[5] = 6
        self.assertEqual([1, 2, 3, 4, 5], sorted(cache.keys()))
        cache[6] = 7
        self.assertEqual([3, 4, 5, 6], sorted(cache.keys()))
        # Now resize to something smaller, which triggers a cleanup
        cache.resize(max_cache=3, after_cleanup_count=2)
        self.assertEqual([5, 6], sorted(cache.keys()))
        # Adding something will use the new size
        cache[7] = 8
        self.assertEqual([5, 6, 7], sorted(cache.keys()))
        cache[8] = 9
        self.assertEqual([7, 8], sorted(cache.keys()))

    def test_resize_larger(self):
        cache = lru_cache.LRUCache(max_cache=5, after_cleanup_count=4)
        cache[1] = 2
        cache[2] = 3
        cache[3] = 4
        cache[4] = 5
        cache[5] = 6
        self.assertEqual([1, 2, 3, 4, 5], sorted(cache.keys()))
        cache[6] = 7
        self.assertEqual([3, 4, 5, 6], sorted(cache.keys()))
        cache.resize(max_cache=8, after_cleanup_count=6)
        self.assertEqual([3, 4, 5, 6], sorted(cache.keys()))
        cache[7] = 8
        cache[8] = 9
        cache[9] = 10
        cache[10] = 11
        self.assertEqual([3, 4, 5, 6, 7, 8, 9, 10], sorted(cache.keys()))
        cache[11] = 12  # triggers cleanup back to new after_cleanup_count
        self.assertEqual([6, 7, 8, 9, 10, 11], sorted(cache.keys()))


class TestLRUSizeCache(tests.TestCase):
    def test_basic_init(self):
        cache = lru_cache.LRUSizeCache()
        self.assertEqual(2048, cache._max_cache)
        self.assertEqual(int(cache._max_size * 0.8), cache._after_cleanup_size)
        self.assertEqual(0, cache._value_size)

    def test_add__null_key(self):
        cache = lru_cache.LRUSizeCache()
        self.assertRaises(ValueError, cache.__setitem__, lru_cache._null_key, 1)

    def test_add_tracks_size(self):
        cache = lru_cache.LRUSizeCache()
        self.assertEqual(0, cache._value_size)
        cache["my key"] = "my value text"
        self.assertEqual(13, cache._value_size)

    def test_remove_tracks_size(self):
        cache = lru_cache.LRUSizeCache()
        self.assertEqual(0, cache._value_size)
        cache["my key"] = "my value text"
        self.assertEqual(13, cache._value_size)
        node = cache._cache["my key"]
        cache._remove_node(node)
        self.assertEqual(0, cache._value_size)

    def test_no_add_over_size(self):
        """Adding a large value may not be cached at all."""
        cache = lru_cache.LRUSizeCache(max_size=10, after_cleanup_size=5)
        self.assertEqual(0, cache._value_size)
        self.assertEqual({}, cache.as_dict())
        cache["test"] = "key"
        self.assertEqual(3, cache._value_size)
        self.assertEqual({"test": "key"}, cache.as_dict())
        cache["test2"] = "key that is too big"
        self.assertEqual(3, cache._value_size)
        self.assertEqual({"test": "key"}, cache.as_dict())
        # If we would add a key, only to cleanup and remove all cached entries,
        # then obviously that value should not be stored
        cache["test3"] = "bigkey"
        self.assertEqual(3, cache._value_size)
        self.assertEqual({"test": "key"}, cache.as_dict())

        cache["test4"] = "bikey"
        self.assertEqual(3, cache._value_size)
        self.assertEqual({"test": "key"}, cache.as_dict())

    def test_adding_clears_cache_based_on_size(self):
        """The cache is cleared in LRU order until small enough."""
        cache = lru_cache.LRUSizeCache(max_size=20)
        cache["key1"] = "value"  # 5 chars
        cache["key2"] = "value2"  # 6 chars
        cache["key3"] = "value23"  # 7 chars
        self.assertEqual(5 + 6 + 7, cache._value_size)
        cache["key2"]  # reference key2 so it gets a newer reference time
        cache["key4"] = "value234"  # 8 chars, over limit
        # We have to remove 2 keys to get back under limit
        self.assertEqual(6 + 8, cache._value_size)
        self.assertEqual({"key2": "value2", "key4": "value234"}, cache.as_dict())

    def test_adding_clears_to_after_cleanup_size(self):
        cache = lru_cache.LRUSizeCache(max_size=20, after_cleanup_size=10)
        cache["key1"] = "value"  # 5 chars
        cache["key2"] = "value2"  # 6 chars
        cache["key3"] = "value23"  # 7 chars
        self.assertEqual(5 + 6 + 7, cache._value_size)
        cache["key2"]  # reference key2 so it gets a newer reference time
        cache["key4"] = "value234"  # 8 chars, over limit
        # We have to remove 3 keys to get back under limit
        self.assertEqual(8, cache._value_size)
        self.assertEqual({"key4": "value234"}, cache.as_dict())

    def test_custom_sizes(self):
        def size_of_list(lst):
            return sum(len(x) for x in lst)

        cache = lru_cache.LRUSizeCache(
            max_size=20, after_cleanup_size=10, compute_size=size_of_list
        )

        cache["key1"] = ["val", "ue"]  # 5 chars
        cache["key2"] = ["val", "ue2"]  # 6 chars
        cache["key3"] = ["val", "ue23"]  # 7 chars
        self.assertEqual(5 + 6 + 7, cache._value_size)
        cache["key2"]  # reference key2 so it gets a newer reference time
        cache["key4"] = ["value", "234"]  # 8 chars, over limit
        # We have to remove 3 keys to get back under limit
        self.assertEqual(8, cache._value_size)
        self.assertEqual({"key4": ["value", "234"]}, cache.as_dict())

    def test_cleanup(self):
        cache = lru_cache.LRUSizeCache(max_size=20, after_cleanup_size=10)

        # Add these in order
        cache["key1"] = "value"  # 5 chars
        cache["key2"] = "value2"  # 6 chars
        cache["key3"] = "value23"  # 7 chars
        self.assertEqual(5 + 6 + 7, cache._value_size)

        cache.cleanup()
        # Only the most recent fits after cleaning up
        self.assertEqual(7, cache._value_size)

    def test_keys(self):
        cache = lru_cache.LRUSizeCache(max_size=10)

        cache[1] = "a"
        cache[2] = "b"
        cache[3] = "cdef"
        self.assertEqual([1, 2, 3], sorted(cache.keys()))

    def test_resize_smaller(self):
        cache = lru_cache.LRUSizeCache(max_size=10, after_cleanup_size=9)
        cache[1] = "abc"
        cache[2] = "def"
        cache[3] = "ghi"
        cache[4] = "jkl"
        # Triggers a cleanup
        self.assertEqual([2, 3, 4], sorted(cache.keys()))
        # Resize should also cleanup again
        cache.resize(max_size=6, after_cleanup_size=4)
        self.assertEqual([4], sorted(cache.keys()))
        # Adding should use the new max size
        cache[5] = "mno"
        self.assertEqual([4, 5], sorted(cache.keys()))
        cache[6] = "pqr"
        self.assertEqual([6], sorted(cache.keys()))

    def test_resize_larger(self):
        cache = lru_cache.LRUSizeCache(max_size=10, after_cleanup_size=9)
        cache[1] = "abc"
        cache[2] = "def"
        cache[3] = "ghi"
        cache[4] = "jkl"
        # Triggers a cleanup
        self.assertEqual([2, 3, 4], sorted(cache.keys()))
        cache.resize(max_size=15, after_cleanup_size=12)
        self.assertEqual([2, 3, 4], sorted(cache.keys()))
        cache[5] = "mno"
        cache[6] = "pqr"
        self.assertEqual([2, 3, 4, 5, 6], sorted(cache.keys()))
        cache[7] = "stu"
        self.assertEqual([4, 5, 6, 7], sorted(cache.keys()))

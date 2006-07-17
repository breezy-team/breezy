# Copyright (C) 2006 by Canonical Ltd
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

"""Test that caching works correctly."""

from bzrlib.disk_backed_cache import DiskBackedCache
from bzrlib.tests import TestCase


class TestDiskBackedCache(TestCase):
    """Tests for the disk-backed cache that don't use the disk."""

    def get_cache(self, **kwargs):
        return DiskBackedCache(**kwargs)

    def test_like_dict(self):
        """Test that the cache acts like a dict object."""
        cache = self.get_cache()

        cache['foo'] = 'bar'
        self.assertEqual(1, len(cache))
        self.assertEqual('bar', cache['foo'])
        self.assertEqual('bar', cache.get('foo'))

        self.assertRaises(KeyError, cache.__getitem__, 'baz')
        self.assertEqual(None, cache.get('baz'))
        self.assertEqual('newval', cache.get('baz', 'newval'))

        self.failUnless('foo' in cache)
        self.failUnless(cache.has_key('foo'))
        self.failIf('baz' in cache)
        self.failIf(cache.has_key('baz'))

        cache['tempkey'] = 'xxyyzz'
        self.assertEqual(2, len(cache))
        self.failUnless('tempkey' in cache)

        self.assertEqual(['foo', 'tempkey'], sorted(cache.keys()))
        self.assertEqual(['foo', 'tempkey'], sorted(cache.iterkeys()))

        self.assertEqual([('foo', 'bar'), ('tempkey', 'xxyyzz')],
                         sorted(cache.iteritems()))
        self.assertEqual(['bar', 'xxyyzz'], sorted(cache.itervalues()))

        # Make sure values() is a list, not an iterator
        values = cache.values()
        self.assertEqual(2, len(values))
        self.assertEqual(['bar', 'xxyyzz'], sorted(values))

        del cache['tempkey']
        self.failIf('tempkey' in cache)
        self.assertEqual(['foo'], sorted(cache.keys()))

        key, val = cache.popitem()
        self.assertEqual('foo', key)
        self.assertEqual('bar', val)
        self.assertEqual([], cache.keys())

        self.assertRaises(KeyError, cache.popitem)
        self.assertEqual(0, len(cache))

    def test_only_store_string(self):
        """DiskBackedCache can only store string objects."""
        cache = self.get_cache()

        self.assertRaises(TypeError, cache.__setitem__, 'foo', u'bar')
        self.assertRaises(TypeError, cache.__setitem__, 'foo', 1)
        self.assertRaises(TypeError, cache.__setitem__, 'foo', 1.0)
        self.assertRaises(TypeError, cache.__setitem__, 'foo', object())
        self.assertRaises(TypeError, cache.__setitem__, 'foo', object)

    def test_funky_key(self):
        """We suppport any Dict supported key type"""
        cache = self.get_cache()

        cache['str'] = 'str'
        cache[u'm\xb5'] = 'mu'
        cache[1] = 'one'
        cache[('x', 1)] = 'x1'

        self.failUnless('str' in cache)
        self.failUnless(u'm\xb5' in cache)
        self.failUnless(1 in cache)
        self.failUnless(('x', 1) in cache)

    def test_tracks_size(self):
        cache = self.get_cache()

        self.assertEqual(0, cache.cache_size)
        cache['foo'] = 'bar'
        self.assertEqual(3, cache.cache_size)
        cache['baz'] = 'jiggly'
        self.assertEqual(9, cache.cache_size)

        del cache['foo']
        self.assertEqual(6, cache.cache_size)

        cache['baz'] = 'alt'
        self.assertEqual(3, cache.cache_size)

        cache.clear()
        self.assertEqual(0, cache.cache_size)
        self.assertEqual({}, cache._dict)

    def test_no_disk_stops_caching(self):
        cache = self.get_cache(max_size=10, use_disk=False)

        cache['foo'] = 'bar'
        cache['baz'] = 'six'
        cache['bar'] = 'toomuch'
        self.assertEqual(['baz', 'foo'], sorted(cache.keys()))

    def test_disallow_replace(self):
        cache = self.get_cache(allow_replace=False)
        cache['foo'] = 'bar'
        self.assertRaises(KeyError, cache.__setitem__, 'foo', 'baz')

    def test_overflow_to_disk(self):
        cache = self.get_cache(max_size=10)

        cache['bar'] = '1234567890'
        self.assertEqual(10, cache.cache_size)
        self.assertEqual(None, cache._disk_cache)
        
        # This should spill to disk
        cache['baz'] = 'foobar'
        self.assertNotEqual(None, cache._disk_cache)

        self.assertEqual('foobar', cache['baz'])

        cache._disk_cache.seek(0)
        self.assertEqual('foobar', cache._disk_cache.read())

    def test_flush_all(self):
        """All entries are written to disk on overflow if flush_all is set."""
        cache = self.get_cache(max_size=10, flush_all=True)

        cache['bar'] = '1234567890'
        self.assertEqual(10, cache.cache_size)
        self.assertEqual(None, cache._disk_cache)
        
        # This should spill to disk
        cache['baz'] = 'foobar'
        self.assertNotEqual(None, cache._disk_cache)

        # The entries should still be accessible, but
        # the should all be on disk.
        self.assertEqual('foobar', cache['baz'])
        self.assertEqual('1234567890', cache['bar'])

        # The order on disk doesn't matter, but existing items
        # should be written before the new item, and since
        # we only have 1 existing item, the order is fixed
        cache._disk_cache.seek(0)
        self.assertEqual('1234567890foobar', cache._disk_cache.read())

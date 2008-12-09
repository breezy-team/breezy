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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the fifo_cache module."""

from bzrlib import (
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
        self.assertEqual([1], c.keys())
        self.assertEqual([1], list(c.iterkeys()))
        self.assertEqual([(1, 2)], c.items())
        self.assertEqual([(1, 2)], list(c.iteritems()))
        self.assertEqual([2], c.values())
        self.assertEqual([2], list(c.itervalues()))

    def test_missing(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(KeyError, c.__getitem__, 1)
        self.assertFalse(1 in c)
        self.assertEqual(0, len(c))
        self.assertEqual(None, c.get(1))
        self.assertEqual(None, c.get(1, None))
        self.assertEqual([], c.keys())
        self.assertEqual([], list(c.iterkeys()))
        self.assertEqual([], c.items())
        self.assertEqual([], list(c.iteritems()))
        self.assertEqual([], c.values())
        self.assertEqual([], list(c.itervalues()))

    def test_add_maintains_fifo(self):
        c = fifo_cache.FIFOCache(4, 4)
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        self.assertEqual([1, 2, 3, 4], sorted(c.keys()))
        c[5] = 6
        # This should pop out the oldest entry
        self.assertEqual([2, 3, 4, 5], sorted(c.keys()))
        # Replacing an item doesn't change the stored keys
        c[2] = 7
        self.assertEqual([2, 3, 4, 5], sorted(c.keys()))
        # But it does change the position in the FIFO
        c[6] = 7
        self.assertEqual([2, 4, 5, 6], sorted(c.keys()))
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
        self.assertEqual([1, 2, 3, 4, 5], sorted(c.keys()))
        c[6] = 7
        # But adding one more should shrink down to after_cleanup_count
        self.assertEqual([3, 4, 5, 6], sorted(c.keys()))

    def test_clear(self):
        c = fifo_cache.FIFOCache(5)
        c[1] = 2
        c[2] = 3
        c[3] = 4
        c[4] = 5
        c[5] = 6
        c.cleanup()
        self.assertEqual([2, 3, 4, 5], sorted(c.keys()))
        c.clear()
        self.assertEqual([], c.keys())
        self.assertEqual([], list(c._queue))

    def test_copy_not_implemented(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.copy)

    def test_pop_not_implemeted(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.pop, 'key')

    def test_popitem_not_implemeted(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.popitem)

    def test_setdefault_not_implemented(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.setdefault)

    def test_update_not_implemented(self):
        c = fifo_cache.FIFOCache()
        self.assertRaises(NotImplementedError, c.update)

    def test_cleanup_funcs(self):
        log = []
        def logging_cleanup(key, value):
            log.append((key, value))
        c = fifo_cache.FIFOCache(5, 4)
        c.add(1, 2, cleanup=logging_cleanup)
        c.add(2, 3, cleanup=logging_cleanup)
        c.add(3, 4, cleanup=logging_cleanup)
        c.add(4, 5, cleanup=None) # no cleanup for 4
        c[5] = 6 # no cleanup for 5
        self.assertEqual([], log)
        # Adding another key should cleanup 1 & 2
        c[6] = 7
        self.assertEqual([(1, 2), (2, 3)], log)
        del log[:]
        c.clear()
        self.assertEqual([(3, 4)], log)

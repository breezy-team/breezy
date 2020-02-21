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

"""A simple first-in-first-out (FIFO) cache."""

from collections import deque


class FIFOCache(dict):
    """A class which manages a cache of entries, removing old ones."""

    def __init__(self, max_cache=100, after_cleanup_count=None):
        dict.__init__(self)
        self._max_cache = max_cache
        if after_cleanup_count is None:
            self._after_cleanup_count = self._max_cache * 8 // 10
        else:
            self._after_cleanup_count = min(after_cleanup_count,
                                            self._max_cache)
        self._cleanup = {}  # map to cleanup functions when items are removed
        self._queue = deque()  # Track when things are accessed

    def __setitem__(self, key, value):
        """Add a value to the cache, there will be no cleanup function."""
        self.add(key, value, cleanup=None)

    def __delitem__(self, key):
        # Remove the key from an arbitrary location in the queue
        self._queue.remove(key)
        self._remove(key)

    def add(self, key, value, cleanup=None):
        """Add a new value to the cache.

        Also, if the entry is ever removed from the queue, call cleanup.
        Passing it the key and value being removed.

        :param key: The key to store it under
        :param value: The object to store
        :param cleanup: None or a function taking (key, value) to indicate
                        'value' should be cleaned up
        """
        if key in self:
            # Remove the earlier reference to this key, adding it again bumps
            # it to the end of the queue
            del self[key]
        self._queue.append(key)
        dict.__setitem__(self, key, value)
        if cleanup is not None:
            self._cleanup[key] = cleanup
        if len(self) > self._max_cache:
            self.cleanup()

    def cache_size(self):
        """Get the number of entries we will cache."""
        return self._max_cache

    def cleanup(self):
        """Clear the cache until it shrinks to the requested size.

        This does not completely wipe the cache, just makes sure it is under
        the after_cleanup_count.
        """
        # Make sure the cache is shrunk to the correct size
        while len(self) > self._after_cleanup_count:
            self._remove_oldest()
        if len(self._queue) != len(self):
            raise AssertionError('The length of the queue should always equal'
                                 ' the length of the dict. %s != %s'
                                 % (len(self._queue), len(self)))

    def clear(self):
        """Clear out all of the cache."""
        # Clean up in FIFO order
        while self:
            self._remove_oldest()

    def _remove(self, key):
        """Remove an entry, making sure to call any cleanup function."""
        cleanup = self._cleanup.pop(key, None)
        # We override self.pop() because it doesn't play well with cleanup
        # functions.
        val = dict.pop(self, key)
        if cleanup is not None:
            cleanup(key, val)
        return val

    def _remove_oldest(self):
        """Remove the oldest entry."""
        key = self._queue.popleft()
        self._remove(key)

    def resize(self, max_cache, after_cleanup_count=None):
        """Increase/decrease the number of cached entries.

        :param max_cache: The maximum number of entries to cache.
        :param after_cleanup_count: After cleanup, we should have at most this
            many entries. This defaults to 80% of max_cache.
        """
        self._max_cache = max_cache
        if after_cleanup_count is None:
            self._after_cleanup_count = max_cache * 8 // 10
        else:
            self._after_cleanup_count = min(max_cache, after_cleanup_count)
        if len(self) > self._max_cache:
            self.cleanup()

    # raise NotImplementedError on dict functions that would mutate the cache
    # which have not been properly implemented yet.
    def copy(self):
        raise NotImplementedError(self.copy)

    def pop(self, key, default=None):
        # If there is a cleanup() function, than it is unclear what pop()
        # should do. Specifically, we would have to call the cleanup on the
        # value before we return it, which should cause whatever resources were
        # allocated to be removed, which makes the return value fairly useless.
        # So instead, we just don't implement it.
        raise NotImplementedError(self.pop)

    def popitem(self):
        # See pop()
        raise NotImplementedError(self.popitem)

    def setdefault(self, key, defaultval=None):
        """similar to dict.setdefault"""
        if key in self:
            return self[key]
        self[key] = defaultval
        return defaultval

    def update(self, *args, **kwargs):
        """Similar to dict.update()"""
        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, dict):
                for key in arg:
                    self.add(key, arg[key])
            else:
                for key, val in args[0]:
                    self.add(key, val)
        elif len(args) > 1:
            raise TypeError('update expected at most 1 argument, got %d'
                            % len(args))
        if kwargs:
            for key in kwargs:
                self.add(key, kwargs[key])


class FIFOSizeCache(FIFOCache):
    """An FIFOCache that removes things based on the size of the values.

    This differs in that it doesn't care how many actual items there are,
    it restricts the cache to be cleaned based on the size of the data.
    """

    def __init__(self, max_size=1024 * 1024, after_cleanup_size=None,
                 compute_size=None):
        """Create a new FIFOSizeCache.

        :param max_size: The max number of bytes to store before we start
            clearing out entries.
        :param after_cleanup_size: After cleaning up, shrink everything to this
            size (defaults to 80% of max_size).
        :param compute_size: A function to compute the size of a value. If
            not supplied we default to 'len'.
        """
        # Arbitrary, we won't really be using the value anyway.
        FIFOCache.__init__(self, max_cache=max_size)
        self._max_size = max_size
        if after_cleanup_size is None:
            self._after_cleanup_size = self._max_size * 8 // 10
        else:
            self._after_cleanup_size = min(after_cleanup_size, self._max_size)

        self._value_size = 0
        self._compute_size = compute_size
        if compute_size is None:
            self._compute_size = len

    def add(self, key, value, cleanup=None):
        """Add a new value to the cache.

        Also, if the entry is ever removed from the queue, call cleanup.
        Passing it the key and value being removed.

        :param key: The key to store it under
        :param value: The object to store, this value by itself is >=
            after_cleanup_size, then we will not store it at all.
        :param cleanup: None or a function taking (key, value) to indicate
                        'value' sohuld be cleaned up.
        """
        # Even if the new value won't be stored, we need to remove the old
        # value
        if key in self:
            # Remove the earlier reference to this key, adding it again bumps
            # it to the end of the queue
            del self[key]
        value_len = self._compute_size(value)
        if value_len >= self._after_cleanup_size:
            return
        self._queue.append(key)
        dict.__setitem__(self, key, value)
        if cleanup is not None:
            self._cleanup[key] = cleanup
        self._value_size += value_len
        if self._value_size > self._max_size:
            # Time to cleanup
            self.cleanup()

    def cache_size(self):
        """Get the number of bytes we will cache."""
        return self._max_size

    def cleanup(self):
        """Clear the cache until it shrinks to the requested size.

        This does not completely wipe the cache, just makes sure it is under
        the after_cleanup_size.
        """
        # Make sure the cache is shrunk to the correct size
        while self._value_size > self._after_cleanup_size:
            self._remove_oldest()

    def _remove(self, key):
        """Remove an entry, making sure to maintain the invariants."""
        val = FIFOCache._remove(self, key)
        self._value_size -= self._compute_size(val)
        return val

    def resize(self, max_size, after_cleanup_size=None):
        """Increase/decrease the amount of cached data.

        :param max_size: The maximum number of bytes to cache.
        :param after_cleanup_size: After cleanup, we should have at most this
            many bytes cached. This defaults to 80% of max_size.
        """
        FIFOCache.resize(self, max_size)
        self._max_size = max_size
        if after_cleanup_size is None:
            self._after_cleanup_size = max_size * 8 // 10
        else:
            self._after_cleanup_size = min(max_size, after_cleanup_size)
        if self._value_size > self._max_size:
            self.cleanup()

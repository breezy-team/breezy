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

"""A simple first-in-first-out (FIFO) cache."""

from collections import deque


class FIFOCache(dict):
    """A class which manages a cache of entries, removing old ones."""

    def __init__(self, max_cache=100, after_cleanup_count=None):
        dict.__init__(self)
        self._max_cache = max_cache
        if after_cleanup_count is None:
            self._after_cleanup_count = self._max_cache * 8 / 10
        else:
            self._after_cleanup_count = min(after_cleanup_count,
                                            self._max_cache)
        self._cleanup = {} # map to cleanup functions when items are removed
        self._queue = deque() # Track when things are accessed

    def __setitem__(self, key, value):
        """Add a value to the cache, there will be no cleanup function."""
        self.add(key, value, cleanup=None)

    def __delitem__(self, key):
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
        if len(self) > self._max_cache:
            self.cleanup()
        if cleanup is not None:
            self._cleanup[key] = cleanup

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
                for key, val in arg.iteritems():
                    self.add(key, val)
            else:
                for key, val in args[0]:
                    self.add(key, val)
        elif len(args) > 1:
            raise TypeError('update expected at most 1 argument, got %d'
                            % len(args))
        if kwargs:
            for key, val in kwargs.iteritems():
                self.add(key, val)

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

"""An in-memory cache that falls back to disk when necessary."""

import tempfile


_PARAM_NOT_SUPPLIED = object()


class DiskBackedCache(object):
    """A dict-like object that caches using a disk object.

    This caches in memory until the amount cache exceeds the
    given amount. It will then either flush to disk, or just
    stop caching new requests, depending on how it was set up.

    (The use case is for loading remote or local information.
    If it is local, cache it in memory, but don't cache too
    much. For remote, cache in memory, but if size is too great
    start flushing to disk.)

    This doesn't implement 100% of the dict interface, but it
    implements most of it to be useful. This is also meant to
    be more used as a cache which is built up, and then cleared
    all at once. Rather than one which is continually updated.
    """

    # Default memory size is 10MB
    _default_max_size = 10*1024*1024

    def __init__(self, use_disk=True, flush_all=False, max_size=None,
                 allow_replace=True):
        """Initialize a new Cache object.

        :param use_disk: If False, will not cache requests
            on disk. After max_size has been reached, further
            requests will be ignored.
            If True, requests after max_size will be cached
            in a local temporary file.
        :param flush_all: Once max_size is reached, flush all the
            data to disk, rather than keeping the current cache
            in memory.
        :param max_size: The maximum amount of data to cache in RAM.
            This class measures the amount of data cached, not the
            size of keys, or any overhead.
            If None, will default to self._default_max_size
            Passing 0 disables all caching. Passing -1 will cache
            everything in memory.
        :param allow_replace: If True, allow cache['foo'] = 'bar'
            to replace an existing 'foo' key. Otherwise a KeyError
            will be raised.
        """

        self._use_disk = use_disk
        self._flush_all = flush_all
        self._allow_replace = allow_replace
        if max_size is None:
            self._max_size = self._default_max_size
        else:
            self._max_size = max_size
        self._cur_size = 0
        # Mapping from key => (pos_in_file, data)
        # if pos_in_file is None, then data contains the actual string
        # else data is the length of the string in the file
        # the file
        self._dict = {}
        self._disk_cache = None

        # Functions that just look at the keys just use the
        # dicts builtin functions
        self.iterkeys = self._dict.iterkeys
        self.has_key = self._dict.has_key
        self.keys = self._dict.keys

    # These special functions just thunk into self._dict
    # but they must exist on the class for python to support len()
    # "if 'foo' in cache:", etc.
    def __len__(self):
        return len(self._dict)

    def __contains__(self, *args, **kwargs):
        return self._dict.__contains__(*args, **kwargs)

    def __iter__(self):
        return iter(self._dict)

    # Dict api functions
    def iteritems(self):
        """Return a generator that yields the contents of the cache"""
        for key, (pos_in_file, data_or_size) in self._dict.iteritems():
            yield key, self._get_mem_or_disk(pos_in_file, data_or_size)

    def items(self):
        """Return the list of key, value pairs"""
        return list(self.iteritems())

    def itervalues(self):
        """Iterate over the values in the cache"""
        for pos_in_file, data_or_size in self._dict.itervalues():
            yield self._get_mem_or_disk(pos_in_file, data_or_size)

    def values(self):
        """Return a list of the values in the dict"""
        return list(self.itervalues())

    # Start of custom functionality
    def _get_mem_or_disk(self, pos_in_file, data_or_size):
        """Return the data, either directly or by reading the file."""
        if pos_in_file is None:
            return data_or_size
        else:
            self._disk_cache.seek(pos_in_file)
            return self._disk_cache.read(data_or_size)

    def __getitem__(self, key):
        """x.__getitem__(y) <==> x[y]"""
        return self._get_mem_or_disk(*self._dict[key])

    def get(self, key, val=None):
        """Same as dict.get()"""
        return self._get_mem_or_disk(*self._dict.get(key, (None, val)))

    def __delitem__(self, key):
        """Delete an item from the cache.

        This does not actually delete anything that was written
        to disk. That will be cleaned up when finished.
        """
        pos_in_file, data_or_size = self._dict.pop(key)
        if pos_in_file is None:
            self._cur_size -= len(data_or_size)
        else:
            # No need to read the file if we are just removing
            self._cur_size -= data_or_size

    def _remove(self, pos_in_file, data_or_size):
        """Decrement the current size information and return the data"""
        if pos_in_file is None:
            self._cur_size -= len(data_or_size)
            return data_or_size
        else:
            self._cur_size -= data_or_size
            self._disk_cache.seek(pos_in_file)
            return self._disk_cache.read(data_or_size)

    def pop(self, key, val=_PARAM_NOT_SUPPLIED):
        """Same as dict.pop()"""
        if val is not _PARAM_NOT_SUPPLIED:
            if key not in self._dict:
                return val
        pos_in_file, data_or_size = self._dict.pop(key)
        return self._remove(pos_in_file, data_or_size)

    def popitem(self):
        key, (pos_in_file, data_or_size) = self._dict.popitem()
        return key, self._remove(pos_in_file, data_or_size)

    def clear(self):
        """Remove all items.

        If a disk cache is used, it will be closed
        """
        self._dict.clear()
        if self._disk_cache:
            self._disk_cache.close()
            self._disk_cache = None
        self._cur_size = 0

    def _add_to_disk(self, key, val):
        """Add the given value to the disk cache.

        :param key: The key to add the value under
        :param val: A string to add to the disk cache.
        """
        if self._disk_cache is None:
            # This creates a temporary file, but on Unix-like machines
            # it actually deletes the disk record, so that it cannot be
            # reached by other means.
            self._disk_cache = tempfile.TemporaryFile()
            pos = 0
            if self._flush_all:
                # Go through all the items and update them
                for old_key, (old_pos, data) in self._dict.items():
                    assert old_pos is None
                    self._disk_cache.write(data)
                    self._dict[old_key] = (pos, len(data))
                    pos += len(data)
        else:
            # Seek to the end of the file
            self._disk_cache.seek(0, 2)
            pos = self._disk_cache.tell()
        size = len(val)
        self._disk_cache.write(val)
        self._dict[key] = (pos, size)

    def _add_new_item(self, key, val):
        """Get a function that can return the new value.

        Any function which wants to add something to the cache
        should go through here. It will preserve the cache size
        and either add the item to disk, or to memory, or possibly
        add nothing.
        """
        if self._max_size == 0:
            return
        if not isinstance(val, str):
            raise TypeError('DiskBackedCache can only store strings, not %s'
                            % val.__class__.__name__)
        old_size = 0
        if key in self._dict:
            if not self._allow_replace:
                raise KeyError('Key %r already exists,'
                               ' and replace is disallowed'
                               % (key,))
            else:
                pos, data_or_size = self._dict[key]
                if pos is None:
                    old_size = len(data_or_size)
                else:
                    old_size = data_or_size
        size = len(val)
        size_delta = size - old_size
        new_size =  self._cur_size + size_delta

        if self._max_size < 0 or new_size <= self._max_size:
            # Store it directly
            self._cur_size = new_size
            self._dict[key] = (None, val)
            return

        # This is too big to fit in memory
        # check if we put in disk
        if not self._use_disk:
            return
        self._add_to_disk(key, val)

    def __setitem__(self, key, val):
        """Add a new entry to the cache."""
        self._add_new_item(key, val)

    cache_size = property(lambda self: self._cur_size)

# Copyright (C) 2005 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""This module provides a transactional facility.

Transactions provide hooks to allow data objects (i.e. inventory weaves or
the revision-history file) to be placed in a registry and retrieved later
during the same transaction. Transactions in bzr are not atomic - they
depend on data ordering of writes, so we do not have commit or rollback
facilities at the transaction level.

Read only transactions raise an assert when objects are listed as dirty
against them - preventing unintended writes.

Write transactions preserve dirty objects in the cache, though due to the
write ordering approach we use for consistency 'dirty' is a misleading term.
A dirty object is one we have modified.

Both read and write transactions *may* flush unchanged objects out of
memory, unless they are marked as 'precious' which indicates that
repeated reads cannot be obtained if the object is ejected, or that
the object is an expensive one for obtaining.
"""

import sys

from . import errors as errors
from .identitymap import IdentityMap, NullIdentityMap
from .trace import mutter


class Transaction:
    """Base class for transactions."""

    def writeable(self) -> bool:
        """Return whether this transaction allows writes.

        Returns:
            True if writes are allowed, False otherwise.
        """
        raise NotImplementedError(self.writeable)


class ReadOnlyTransaction(Transaction):
    """A read only unit of work for data objects."""

    def finish(self):
        """Clean up this transaction."""

    def __init__(self):
        """Initialize a read-only transaction."""
        super().__init__()
        self.map = IdentityMap()
        self._clean_objects = set()
        self._clean_queue = []
        self._limit = -1
        self._precious_objects = set()

    def is_clean(self, an_object):
        """Return True if an_object is clean."""
        return an_object in self._clean_objects

    def register_clean(self, an_object, precious: bool = False) -> None:
        """Register an_object as being clean.

        If the precious hint is True, the object will not
        be ejected from the object identity map ever.
        """
        self._clean_objects.add(an_object)
        self._clean_queue.append(an_object)
        if precious:
            self._precious_objects.add(an_object)
        self._trim()

    def register_dirty(self, an_object):
        """Register an_object as being dirty."""
        raise errors.ReadOnlyObjectDirtiedError(an_object)

    def set_cache_size(self, size):
        """Set a new cache size."""
        if size < -1:
            raise ValueError(size)
        self._limit = size
        self._trim()

    def _trim(self):
        """Trim the cache back if needed."""
        if self._limit < 0 or self._limit - len(self._clean_objects) > 0:
            return
        needed = len(self._clean_objects) - self._limit
        offset = 0
        while needed and offset < len(self._clean_objects):
            # references we know of:
            # temp passed to getrefcount in our frame
            # temp in getrefcount's frame
            # the map forward
            # the map backwards
            # _clean_objects
            # _clean_queue
            if sys.version_info >= (3, 11):
                ref_threshold = 6
            else:
                # 1 missing on Python < 3.11
                ref_threshold = 7
            if (
                sys.getrefcount(self._clean_queue[offset]) <= ref_threshold
                and self._clean_queue[offset] not in self._precious_objects
            ):
                removed = self._clean_queue[offset]
                self._clean_objects.remove(removed)
                del self._clean_queue[offset]
                self.map.remove_object(removed)
                mutter("removed object %r", removed)
                needed -= 1
            else:
                offset += 1

    def writeable(self):
        """Read only transactions do not allow writes."""
        return False


class WriteTransaction(ReadOnlyTransaction):
    """A write transaction.

    - caches domain objects
    - clean objects can be removed from the cache
    - dirty objects are retained.
    """

    def finish(self):
        """Clean up this transaction."""
        for thing in self._dirty_objects:
            callback = getattr(thing, "transaction_finished", None)
            if callback is not None:
                callback()

    def __init__(self):
        """Initialize a write transaction."""
        super().__init__()
        self._dirty_objects = set()

    def is_dirty(self, an_object):
        """Return True if an_object is dirty."""
        return an_object in self._dirty_objects

    def register_dirty(self, an_object):
        """Register an_object as being dirty.

        Dirty objects are not ejected from the identity map
        until the transaction finishes and get informed
        when the transaction finishes.
        """
        self._dirty_objects.add(an_object)
        if self.is_clean(an_object):
            self._clean_objects.remove(an_object)
            del self._clean_queue[self._clean_queue.index(an_object)]
        self._trim()

    def writeable(self):
        """Write transactions allow writes."""
        return True


class PassThroughTransaction(Transaction):
    """A pass through transaction.

    - nothing is cached.
    - nothing ever gets into the identity map.
    """

    def finish(self):
        """Clean up this transaction."""
        for thing in self._dirty_objects:
            callback = getattr(thing, "transaction_finished", None)
            if callback is not None:
                callback()

    def __init__(self):
        """Initialize a pass-through transaction."""
        super().__init__()
        self.map = NullIdentityMap()
        self._dirty_objects = set()

    def register_clean(self, an_object, precious=False):
        """Register an_object as being clean.

        Note that precious is only a hint, and PassThroughTransaction
        ignores it.
        """

    def register_dirty(self, an_object):
        """Register an_object as being dirty.

        Dirty objects get informed
        when the transaction finishes.
        """
        self._dirty_objects.add(an_object)

    def set_cache_size(self, ignored):
        """Do nothing, we are passing through."""

    def writeable(self):
        """Pass through transactions allow writes."""
        return True

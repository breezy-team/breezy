# Copyright (C) 2005 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""This module provides a transactional facility.

Transactions provide hooks to allow data objects (i.e. inventory weaves or
the revision-history file) to be placed in a registry and retrieved later
during the same transaction.  This allows for repeated read isolation. At
the end of a transaction, a callback is issued to each registered changed
item informing it whether it should commit or not. We provide a two layer
facility - domain objects are notified first, then data objects.

Read only transactions raise an assert when objects are listed as dirty
against them - preventing unintended writes. Once all the data storage is
hooked into this facility, it might be nice to have a readonly transaction
that just excepts on commit, for testing or simulating of things.

Write transactions queue all changes in the transaction (which may in the 
future involve writing them to uncommitted atomic files in preparation 
for commit - i.e. on network connections where latency matters) and then
notify each object of commit or rollback.

Both read and write transactions *may* flush unchanged objects out of 
memory, unless they are marked as 'preserve' which indicates that 
repeated reads cannot be obtained if the object is ejected.
"""

import sys

import bzrlib.errors as errors
from bzrlib.identitymap import IdentityMap, NullIdentityMap
from bzrlib.trace import mutter


class ReadOnlyTransaction(object):
    """A read only unit of work for data objects."""

    def commit(self):
        """ReadOnlyTransactions cannot commit."""
        raise errors.CommitNotPossible('In a read only transaction')

    def finish(self):
        """Clean up this transaction

        This will rollback on transactions that can if they have nto been
        committed.
        """

    def __init__(self):
        super(ReadOnlyTransaction, self).__init__()
        self.map = IdentityMap()
        self._clean_objects = set()
        self._clean_queue = []
        self._limit = -1
        self._precious_objects = set()

    def register_clean(self, an_object, precious=False):
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
        raise errors.ReadOnlyError(
            "Cannot dirty objects in a read only transaction")

    def rollback(self):
        """Let people call this even though nothing has to happen."""

    def set_cache_size(self, size):
        """Set a new cache size."""
        assert -1 <= size
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
            # 1 missing ?
            if (sys.getrefcount(self._clean_queue[offset]) <= 7 and
                not self._clean_queue[offset] in self._precious_objects):
                removed = self._clean_queue[offset]
                self._clean_objects.remove(removed)
                del self._clean_queue[offset]
                self.map.remove_object(removed)
                mutter('removed object %r', removed)
                needed -= 1
            else:
                offset += 1


        
class PassThroughTransaction(object):
    """A pass through transaction
    
    - all actions are committed immediately.
    - rollback is not supported.
    - commit() is a no-op.
    """

    def commit(self):
        """PassThroughTransactions have nothing to do."""

    def finish(self):
        """Clean up this transaction

        This will rollback on transactions that can if they have nto been
        committed.
        """

    def __init__(self):
        super(PassThroughTransaction, self).__init__()
        self.map = NullIdentityMap()

    def register_clean(self, an_object, precious=False):
        """Register an_object as being clean.
        
        Note that precious is only a hint, and PassThroughTransaction
        ignores it.
        """

    def register_dirty(self, an_object):
        """Register an_object as being dirty."""

    def rollback(self):
        """Cannot rollback a pass through transaction."""
        raise errors.AlreadyCommitted

    def set_cache_size(self, ignored):
        """Do nothing, we are passing through."""

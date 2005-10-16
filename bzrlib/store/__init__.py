# Copyright (C) 2005 by Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# TODO: Could remember a bias towards whether a particular store is typically
# compressed or not.

"""
Stores are the main data-storage mechanism for Bazaar-NG.

A store is a simple write-once container indexed by a universally
unique ID.
"""

from cStringIO import StringIO
from stat import ST_MODE, S_ISDIR
from zlib import adler32

import bzrlib.errors as errors
from bzrlib.errors import BzrError, UnlistableStore, TransportNotPossible
from bzrlib.trace import mutter
import bzrlib.transport
from bzrlib.transport.local import LocalTransport

######################################################################
# stores

class StoreError(Exception):
    pass


class Store(object):
    """This class represents the abstract storage layout for saving information.
    
    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.
    """

    def __len__(self):
        raise NotImplementedError('Children should define their length')

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        raise NotImplementedError

    def __contains__(self, fileid):
        """"""
        raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

    def add(self, f, fileid):
        """Add a file object f to the store accessible from the given fileid"""
        raise NotImplementedError('Children of Store must define their method of adding entries.')

    def add_multi(self, entries):
        """Add a series of file-like or string objects to the store with the given
        identities.
        
        :param entries: A list of tuples of file,id pairs [(file1, id1), (file2, id2), ...]
                        This could also be a generator yielding (file,id) pairs.
        """
        for f, fileid in entries:
            self.add(f, fileid)

    def has(self, fileids):
        """Return True/False for each entry in fileids.

        :param fileids: A List or generator yielding file ids.
        :return: A generator or list returning True/False for each entry.
        """
        for fileid in fileids:
            if fileid in self:
                yield True
            else:
                yield False

    def listable(self):
        """Return True if this store is able to be listed."""
        return hasattr(self, "__iter__")

    def get(self, fileids, permit_failure=False, pb=None):
        """Return a set of files, one for each requested entry.
        
        :param permit_failure: If true, return None for entries which do not 
                               exist.
        :return: A list or generator of file-like objects, one for each id.
        """
        for fileid in fileids:
            try:
                yield self[fileid]
            except KeyError:
                if permit_failure:
                    yield None
                else:
                    raise

    def copy_multi(self, other, ids, pb=None, permit_failure=False):
        """Copy texts for ids from other into self.

        If an id is present in self, it is skipped.  A count of copied
        ids is returned, which may be less than len(ids).

        :param other: Another Store object
        :param ids: A list of entry ids to be copied
        :param pb: A ProgressBar object, if none is given, the default will be created.
        :param permit_failure: Allow missing entries to be ignored
        :return: (n_copied, [failed]) The number of entries copied successfully,
            followed by a list of entries which could not be copied (because they
            were missing)
        """
        if pb is None:
            pb = bzrlib.ui.ui_factory.progress_bar()

        # XXX: Is there any reason why we couldn't make this accept a generator
        # and build a list as it finds things to copy?
        ids = list(ids) # Make sure we don't have a generator, since we iterate 2 times
        pb.update('preparing to copy')
        to_copy = []
        for file_id, has in zip(ids, self.has(ids)):
            if not has:
                to_copy.append(file_id)
        return self._do_copy(other, to_copy, pb, permit_failure=permit_failure)

    def _do_copy(self, other, to_copy, pb, permit_failure=False):
        """This is the standard copying mechanism, just get them one at
        a time from remote, and store them locally.

        :param other: Another Store object
        :param to_copy: A list of entry ids to copy
        :param pb: A ProgressBar object to display completion status.
        :param permit_failure: Allow missing entries to be ignored
        :return: (n_copied, [failed])
            The number of entries copied, and a list of failed entries.
        """
        # This should be updated to use add_multi() rather than
        # the current methods of buffering requests.
        # One question, is it faster to queue up 1-10 and then copy 1-10
        # then queue up 11-20, copy 11-20
        # or to queue up 1-10, copy 1, queue 11, copy 2, etc?
        # sort of pipeline versus batch.

        # We can't use self._transport.copy_to because we don't know
        # whether the local tree is in the same format as other
        failed = set()
        def buffer_requests():
            count = 0
            buffered_requests = []
            for fileid in to_copy:
                try:
                    f = other[fileid]
                except KeyError:
                    if permit_failure:
                        failed.add(fileid)
                        continue
                    else:
                        raise

                buffered_requests.append((f, fileid))
                if len(buffered_requests) > self._max_buffered_requests:
                    yield buffered_requests.pop(0)
                    count += 1
                    pb.update('copy', count, len(to_copy))

            for req in buffered_requests:
                yield req
                count += 1
                pb.update('copy', count, len(to_copy))

            assert count == len(to_copy)

        self.add_multi(buffer_requests())

        pb.clear()
        return len(to_copy), failed


class TransportStore(Store):
    """A TransportStore is a Store superclass for Stores that use Transports."""

    _max_buffered_requests = 10

    def _check_fileid(self, fileid):
        if not isinstance(fileid, basestring):
            raise TypeError('Fileids should be a string type: %s %r' % (type(fileid), fileid))
        if '\\' in fileid or '/' in fileid:
            raise ValueError("invalid store id %r" % fileid)

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        fn = self._relpath(fileid)
        try:
            return self._transport.get(fn)
        except errors.NoSuchFile:
            raise KeyError(fileid)

    def __init__(self, transport, prefixed=False):
        assert isinstance(transport, bzrlib.transport.Transport)
        super(TransportStore, self).__init__()
        self._transport = transport
        self._prefixed = prefixed

    def _relpath(self, fileid):
        self._check_fileid(fileid)
        if self._prefixed:
            return hash_prefix(fileid) + fileid
        else:
            return fileid

    def __repr__(self):
        if self._transport is None:
            return "%s(None)" % (self.__class__.__name__)
        else:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)

    __str__ = __repr__

    def _iter_relpaths(self):
        """Iter the relative paths of files in the transports sub-tree."""
        transport = self._transport
        queue = list(transport.list_dir('.'))
        while queue:
            relpath = queue.pop(0)
            st = transport.stat(relpath)
            if S_ISDIR(st[ST_MODE]):
                for i, basename in enumerate(transport.list_dir(relpath)):
                    queue.insert(i, relpath+'/'+basename)
            else:
                yield relpath, st

    def listable(self):
        """Return True if this store is able to be listed."""
        return self._transport.listable()


class ImmutableMemoryStore(Store):
    """A memory only store."""

    def __contains__(self, fileid):
        return self._contents.has_key(fileid)

    def __init__(self):
        super(ImmutableMemoryStore, self).__init__()
        self._contents = {}

    def add(self, stream, fileid, compressed=True):
        if self._contents.has_key(fileid):
            raise StoreError("fileid %s already in the store" % fileid)
        self._contents[fileid] = stream.read()

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        if not self._contents.has_key(fileid):
            raise IndexError
        return StringIO(self._contents[fileid])

    def _item_size(self, fileid):
        return len(self._contents[fileid])

    def __iter__(self):
        return iter(self._contents.keys())

    def total_size(self):
        result = 0
        count = 0
        for fileid in self:
            count += 1
            result += self._item_size(fileid)
        return count, result
        

class CachedStore(Store):
    """A store that caches data locally, to avoid repeated downloads.
    The precacache method should be used to avoid server round-trips for
    every piece of data.
    """

    def __init__(self, store, cache_dir):
        super(CachedStore, self).__init__()
        self.source_store = store
        # This clones the source store type with a locally bound
        # transport. FIXME: it assumes a constructor is == cloning.
        # clonable store - it might be nicer to actually have a clone()
        # or something. RBC 20051003
        self.cache_store = store.__class__(LocalTransport(cache_dir))

    def __getitem__(self, id):
        mutter("Cache add %s" % id)
        if id not in self.cache_store:
            self.cache_store.add(self.source_store[id], id)
        return self.cache_store[id]

    def __contains__(self, fileid):
        if fileid in self.cache_store:
            return True
        if fileid in self.source_store:
            # We could copy at this time
            return True
        return False

    def get(self, fileids, permit_failure=False, pb=None):
        fileids = list(fileids)
        hasids = self.cache_store.has(fileids)
        needs = set()
        for has, fileid in zip(hasids, fileids):
            if not has:
                needs.add(fileid)
        if needs:
            self.cache_store.copy_multi(self.source_store, needs,
                    permit_failure=permit_failure)
        return self.cache_store.get(fileids,
                permit_failure=permit_failure, pb=pb)

    def prefetch(self, ids):
        """Copy a series of ids into the cache, before they are used.
        For remote stores that support pipelining or async downloads, this can
        increase speed considerably.

        Failures while prefetching are ignored.
        """
        mutter("Prefetch of ids %s" % ",".join(ids))
        self.cache_store.copy_multi(self.source_store, ids, 
                                    permit_failure=True)


def copy_all(store_from, store_to):
    """Copy all ids from one store to another."""
    # TODO: Optional progress indicator
    if not store_from.listable():
        raise UnlistableStore(store_from)
    ids = [f for f in store_from]
    store_to.copy_multi(store_from, ids)

def hash_prefix(file_id):
    return "%02x/" % (adler32(file_id) & 0xff)


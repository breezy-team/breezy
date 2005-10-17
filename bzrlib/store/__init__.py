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
from zlib import adler32

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import BzrError, UnlistableStore, TransportNotPossible
from bzrlib.trace import mutter
import bzrlib.transport as transport
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

    def get(self, file_id, suffix=None):
        """Returns a file reading from a particular entry.
        
        If suffix is present, retrieve the named suffix for file_id.
        """
        raise NotImplementedError

    def __getitem__(self, fileid):
        """DEPRECATED. Please use .get(file_id) instead."""
        raise NotImplementedError

    #def __contains__(self, fileid):
    #    """Deprecated, please use has_id"""
    #    raise NotImplementedError

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

    def has_id(self, file_id, suffix=None):
        """Return True or false for the presence of file_id in the store.
        
        suffix, if present, is a per file suffix, i.e. for digital signature 
        data."""
        raise NotImplementedError

    def listable(self):
        """Return True if this store is able to be listed."""
        return hasattr(self, "__iter__")

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
        for file_id in ids:
            if not self.has_id(file_id):
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
                    f = other.get(fileid)
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

    def add(self, f, fileid, suffix=None):
        """Add contents of a file into the store.

        f -- A file-like object, or string
        """
        mutter("add store entry %r" % (fileid))
        
        if suffix is not None:
            fn = self._relpath(fileid, [suffix])
        else:
            fn = self._relpath(fileid)
        if self._transport.has(fn):
            raise BzrError("store %r already contains id %r" % (self._transport.base, fileid))

        if self._prefixed:
            try:
                self._transport.mkdir(hash_prefix(fileid)[:-1])
            except errors.FileExists:
                pass

        self._add(fn, f)

    def _check_fileid(self, fileid):
        if not isinstance(fileid, basestring):
            raise TypeError('Fileids should be a string type: %s %r' % (type(fileid), fileid))
        if '\\' in fileid or '/' in fileid:
            raise ValueError("invalid store id %r" % fileid)

    def has_id(self, fileid, suffix=None):
        """See Store.has_id."""
        if suffix is not None:
            fn = self._relpath(fileid, [suffix])
        else:
            fn = self._relpath(fileid)
        return self._transport.has(fn)

    def _get(self, filename):
        """Return an vanilla file stream for clients to read from.

        This is the body of a template method on 'get', and should be 
        implemented by subclasses.
        """
        raise NotImplementedError

    def get(self, fileid, suffix=None):
        """See Store.get()."""
        if suffix is None:
            fn = self._relpath(fileid)
        else:
            fn = self._relpath(fileid, [suffix])
        try:
            return self._get(fn)
        except errors.NoSuchFile:
            raise KeyError(fileid)

    def __init__(self, a_transport, prefixed=False):
        assert isinstance(a_transport, transport.Transport)
        super(TransportStore, self).__init__()
        self._transport = a_transport
        self._prefixed = prefixed
        self._suffixes = set()

    def __len__(self):
        return len(list(self.__iter__()))

    def _relpath(self, fileid, suffixes=[]):
        self._check_fileid(fileid)
        for suffix in suffixes:
            if not suffix in self._suffixes:
                raise ValueError("Unregistered suffix %r" % suffix)
            self._check_fileid(suffix)
        if self._prefixed:
            path = [hash_prefix(fileid) + fileid]
        else:
            path = [fileid]
        path.extend(suffixes)
        return '.'.join(path)

    def __repr__(self):
        if self._transport is None:
            return "%s(None)" % (self.__class__.__name__)
        else:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)

    __str__ = __repr__

    def listable(self):
        """Return True if this store is able to be listed."""
        return self._transport.listable()

    def register_suffix(self, suffix):
        """Register a suffix as being expected in this store."""
        self._check_fileid(suffix)
        self._suffixes.add(suffix)

    def total_size(self):
        """Return (count, bytes)

        This is the (compressed) size stored on disk, not the size of
        the content."""
        total = 0
        count = 0
        for relpath in self._transport.iter_files_recursive():
            count += 1
            total += self._transport.stat(relpath).st_size
                
        return count, total


def ImmutableMemoryStore():
    return bzrlib.store.text.TextStore(transport.memory.MemoryTransport())
        

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

    def get(self, id):
        mutter("Cache add %s" % id)
        if id not in self.cache_store:
            self.cache_store.add(self.source_store.get(id), id)
        return self.cache_store.get(id)

    def has_id(self, fileid, suffix=None):
        """See Store.has_id."""
        if self.cache_store.has_id(fileid, suffix):
            return True
        if self.source_store.has_id(fileid, suffix):
            # We could copy at this time
            return True
        return False

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


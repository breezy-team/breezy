# Copyright (C) 2005, 2006 Canonical Ltd

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

# XXX: Some consideration of the problems that might occur if there are
# files whose id differs only in case.  That should probably be forbidden.


import errno
import os
from cStringIO import StringIO
import urllib

from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.weave import WeaveFile, Weave
from bzrlib.store import TransportStore
from bzrlib.atomicfile import AtomicFile
from bzrlib.errors import NoSuchFile, FileExists
from bzrlib.symbol_versioning import *
from bzrlib.trace import mutter
import bzrlib.ui


class VersionedFileStore(TransportStore):
    """Collection of many versioned files in a transport."""

    def __init__(self, transport, prefixed=False, precious=False,
                 dir_mode=None, file_mode=None,
                 versionedfile_class=WeaveFile,
                 escaped=False):
        super(VersionedFileStore, self).__init__(transport,
                dir_mode=dir_mode, file_mode=file_mode,
                prefixed=prefixed, compressed=False, escaped=escaped)
        self._precious = precious
        self._versionedfile_class = versionedfile_class

    def _clear_cache_id(self, file_id, transaction):
        """WARNING may lead to inconsistent object references for file_id.

        Remove file_id from the transaction map. 

        NOT in the transaction api because theres no reliable way to clear
        callers. So its here for very specialised use rather than having an
        'api' that isn't.
        """
        weave = transaction.map.find_weave(file_id)
        if weave is not None:
            mutter("old data in transaction in %s for %s", self, file_id)
            # FIXME abstraction violation - transaction now has stale data.
            transaction.map.remove_object(weave)

    def filename(self, file_id):
        """Return the path relative to the transport root."""
        return self._relpath(file_id)

    def __iter__(self):
        suffixes = self._versionedfile_class.get_suffixes()
        ids = set()
        for relpath in self._iter_files_recursive():
            for suffix in suffixes:
                if relpath.endswith(suffix):
                    # TODO: use standard remove_suffix function
                    escaped_id = os.path.basename(relpath[:-len(suffix)])
                    file_id = self._unescape(escaped_id)
                    if file_id not in ids:
                        ids.add(file_id)
                        yield file_id
                    break # only one suffix can match

    def has_id(self, fileid):
        suffixes = self._versionedfile_class.get_suffixes()
        filename = self.filename(fileid)
        for suffix in suffixes:
            if not self._transport.has(filename + suffix):
                return False
        return True

    def get_empty(self, file_id, transaction):
        """Get an empty weave, which implies deleting the existing one first."""
        if self.has_id(file_id):
            self.delete(file_id, transaction)
        return self.get_weave_or_empty(file_id, transaction)

    def delete(self, file_id, transaction):
        """Remove file_id from the store."""
        suffixes = self._versionedfile_class.get_suffixes()
        filename = self.filename(file_id)
        for suffix in suffixes:
            self._transport.delete(filename + suffix)
        self._clear_cache_id(file_id, transaction)

    def _get(self, file_id):
        return self._transport.get(self.filename(file_id))

    def _put(self, file_id, f):
        fn = self.filename(file_id)
        try:
            return self._transport.put(fn, f, mode=self._file_mode)
        except NoSuchFile:
            if not self._prefixed:
                raise
            self._transport.mkdir(os.path.dirname(fn), mode=self._dir_mode)
            return self._transport.put(fn, f, mode=self._file_mode)

    def get_weave(self, file_id, transaction):
        weave = transaction.map.find_weave(file_id)
        if weave is not None:
            #mutter("cache hit in %s for %s", self, file_id)
            return weave
        if transaction.writeable():
            w = self._versionedfile_class(self.filename(file_id), self._transport, self._file_mode)
            transaction.map.add_weave(file_id, w)
            transaction.register_dirty(w)
        else:
            w = self._versionedfile_class(self.filename(file_id),
                                          self._transport,
                                          self._file_mode,
                                          create=False,
                                          access_mode='r')
            transaction.map.add_weave(file_id, w)
            transaction.register_clean(w, precious=self._precious)
        return w

    @deprecated_method(zero_eight)
    def get_lines(self, file_id, rev_id, transaction):
        """Return text from a particular version of a weave.

        Returned as a list of lines.
        """
        w = self.get_weave(file_id, transaction)
        return w.get_lines(rev_id)
    
    def _new_weave(self, file_id, transaction):
        """Make a new weave for file_id and return it."""
        weave = self._make_new_versionedfile(file_id, transaction)
        transaction.map.add_weave(file_id, weave)
        # has to be dirty - its able to mutate on its own.
        transaction.register_dirty(weave)
        return weave

    def _make_new_versionedfile(self, file_id, transaction):
        if self.has_id(file_id):
            self.delete(file_id, transaction)
        try:
            weave = self._versionedfile_class(self.filename(file_id), self._transport, self._file_mode, create=True)
        except NoSuchFile:
            if not self._prefixed:
                # unexpected error - NoSuchFile is raised on a missing dir only and that
                # only occurs when we are prefixed.
                raise
            self._transport.mkdir(self.hash_prefix(file_id), mode=self._dir_mode)
            weave = self._versionedfile_class(self.filename(file_id), self._transport, self._file_mode, create=True)
        return weave

    def get_weave_or_empty(self, file_id, transaction):
        """Return a weave, or an empty one if it doesn't exist.""" 
        try:
            return self.get_weave(file_id, transaction)
        except NoSuchFile:
            return self._new_weave(file_id, transaction)

    @deprecated_method(zero_eight)
    def put_weave(self, file_id, weave, transaction):
        """This is a deprecated API: It writes an entire collection of ids out.
        
        This became inappropriate when we made a versioned file api which
        tracks the state of the collection of versions for a single id.
        
        Its maintained for backwards compatability but will only work on
        weave stores - pre 0.8 repositories.
        """
        self._put_weave(self, file_id, weave, transaction)

    def _put_weave(self, file_id, weave, transaction):
        """Preserved here for upgrades-to-weaves to use."""
        myweave = self._make_new_versionedfile(file_id, transaction)
        myweave.join(weave)

    @deprecated_method(zero_eight)
    def add_text(self, file_id, rev_id, new_lines, parents, transaction):
        """This method was a shorthand for 

        vfile = self.get_weave_or_empty(file_id, transaction)
        vfile.add_lines(rev_id, parents, new_lines)
        """
        vfile = self.get_weave_or_empty(file_id, transaction)
        vfile.add_lines(rev_id, parents, new_lines)
        
    @deprecated_method(zero_eight)
    def add_identical_text(self, file_id, old_rev_id, new_rev_id, parents,
                           transaction):
        """This method was a shorthand for

        vfile = self.get_weave_or_empty(file_id, transaction)
        vfile.clone_text(new_rev_id, old_rev_id, parents)
        """
        vfile = self.get_weave_or_empty(file_id, transaction)
        vfile.clone_text(new_rev_id, old_rev_id, parents)
 
    def copy(self, source, result_id, transaction):
        """Copy the source versioned file to result_id in this store."""
        self._clear_cache_id(result_id, transaction)
        source.copy_to(self.filename(result_id), self._transport)
 
    def copy_all_ids(self, store_from, pb=None, from_transaction=None,
                     to_transaction=None):
        """Copy all the file ids from store_from into self."""
        if from_transaction is None:
            warn("Please pass from_transaction into "
                 "versioned_store.copy_all_ids.", stacklevel=2)
        if to_transaction is None:
            warn("Please pass to_transaction into "
                 "versioned_store.copy_all_ids.", stacklevel=2)
        if not store_from.listable():
            raise UnlistableStore(store_from)
        ids = []
        for count, file_id in enumerate(store_from):
            if pb:
                pb.update('listing files', count, count)
            ids.append(file_id)
        if pb:
            pb.clear()
        mutter('copy_all ids: %r', ids)
        self.copy_multi(store_from, ids, pb=pb,
                        from_transaction=from_transaction,
                        to_transaction=to_transaction)

    def copy_multi(self, from_store, file_ids, pb=None, from_transaction=None,
                   to_transaction=None):
        """Copy all the versions for multiple file_ids from from_store.
        
        :param from_transaction: required current transaction in from_store.
        """
        from bzrlib.transactions import PassThroughTransaction
        assert isinstance(from_store, WeaveStore)
        if from_transaction is None:
            warn("WeaveStore.copy_multi without a from_transaction parameter "
                 "is deprecated. Please provide a from_transaction.",
                 DeprecationWarning,
                 stacklevel=2)
            # we are reading one object - caching is irrelevant.
            from_transaction = PassThroughTransaction()
        if to_transaction is None:
            warn("WeaveStore.copy_multi without a to_transaction parameter "
                 "is deprecated. Please provide a to_transaction.",
                 DeprecationWarning,
                 stacklevel=2)
            # we are copying single objects, and there may be open tranasactions
            # so again with the passthrough
            to_transaction = PassThroughTransaction()
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        for count, f in enumerate(file_ids):
            mutter("copy weave {%s} into %s", f, self)
            pb.update('copy', count, len(file_ids))
            # if we have it in cache, its faster.
            # joining is fast with knits, and bearable for weaves -
            # indeed the new case can be optimised if needed.
            target = self._make_new_versionedfile(f, to_transaction)
            target.join(from_store.get_weave(f, from_transaction))
        pb.finished()

    def total_size(self):
        count, bytes =  super(VersionedFileStore, self).total_size()
        return (count / len(self._versionedfile_class.get_suffixes())), bytes

WeaveStore = VersionedFileStore

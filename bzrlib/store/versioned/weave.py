#! /usr/bin/python

# Copyright (C) 2005 Canonical Ltd

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
from bzrlib.weave import WeaveFile
from bzrlib.store import TransportStore, hash_prefix
from bzrlib.atomicfile import AtomicFile
from bzrlib.errors import NoSuchFile, FileExists
from bzrlib.symbol_versioning import *
from bzrlib.trace import mutter


class WeaveStore(TransportStore):
    """Collection of several weave files in a directory.

    This has some shortcuts for reading and writing them.
    """

    def __init__(self, transport, prefixed=False, precious=False,
                 dir_mode=None, file_mode=None):
        super(WeaveStore, self).__init__(transport,
                dir_mode=dir_mode, file_mode=file_mode,
                prefixed=prefixed, compressed=False)
        self._precious = precious

    def filename(self, file_id):
        """Return the path relative to the transport root."""
        if self._prefixed:
            return hash_prefix(file_id) + urllib.quote(file_id)
        else:
            return urllib.quote(file_id)

    def __iter__(self):
        suffixes = WeaveFile.get_suffixes()
        ids = set()
        for relpath in self._iter_files_recursive():
            for suffix in suffixes:
                if relpath.endswith(suffix):
                    id = os.path.basename(relpath[:-len(suffix)])
                    if not id in ids:
                        yield id
                        ids.add(id)

    def has_id(self, fileid):
        suffixes = WeaveFile.get_suffixes()
        filename = self.filename(fileid)
        for suffix in suffixes:
            if not self._transport.has(filename + suffix):
                return False
        return True

    def get_weave(self, file_id, transaction):
        weave = transaction.map.find_weave(file_id)
        if weave:
            mutter("cache hit in %s for %s", self, file_id)
            return weave
        w = WeaveFile(self.filename(file_id), self._transport, self._file_mode)
        transaction.map.add_weave(file_id, w)
        transaction.register_clean(w, precious=self._precious)
        return w

    def get_lines(self, file_id, rev_id, transaction):
        """Return text from a particular version of a weave.

        Returned as a list of lines."""
        w = self.get_weave(file_id, transaction)
        return w.get(rev_id)
    
    def _new_weave(self, file_id, transaction):
        """Make a new weave for file_id and return it."""
        weave = self._make_new_versionedfile(file_id)
        transaction.map.add_weave(file_id, weave)
        transaction.register_clean(weave, precious=self._precious)
        return weave

    def _make_new_versionedfile(self, file_id):
        try:
            weave = WeaveFile(self.filename(file_id), self._transport, self._file_mode)
        except NoSuchFile:
            if not self._prefixed:
                # unexpected error - NoSuchFile is raised on a missing dir only.
                raise
            self._transport.mkdir(hash_prefix(file_id), mode=self._dir_mode)
            weave = WeaveFile(self.filename(file_id), self._transport, self._file_mode)
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
        myweave = self._make_new_versionedfile(file_id)
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
     
    def copy_all_ids(self, store_from, pb=None, from_transaction=None):
        """Copy all the file ids from store_from into self."""
        if from_transaction is None:
            warn("Please pase from_transaction into "
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
                        from_transaction=from_transaction)

    def copy_multi(self, from_store, file_ids, pb=None, from_transaction=None):
        """Copy all the versions for multiple file_ids from from_store.
        
        :param from_transaction: required current transaction in from_store.
        """
        assert isinstance(from_store, WeaveStore)
        if from_transaction is None:
            warn("WeaveStore.copy_multi without a from_transaction parameter "
                 "is deprecated. Please provide a from_transaction.",
                 DeprecationWarning,
                 stacklevel=2)
        for count, f in enumerate(file_ids):
            mutter("copy weave {%s} into %s", f, self)
            if pb:
                pb.update('copy', count, len(file_ids))
            # if we have it in cache, its faster.
            if not from_transaction:
                from bzrlib.transactions import PassThroughTransaction
                from_transaction = PassThroughTransaction()
            # joining is fast with knits, and bearable for weaves -
            # indeed the new case can be optimised
            target = self._make_new_versionedfile(f)
            target.join(from_store.get_weave(f, from_transaction))
        if pb:
            pb.clear()

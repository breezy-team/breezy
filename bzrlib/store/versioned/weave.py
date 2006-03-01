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
from bzrlib.weave import Weave, WeaveFile
from bzrlib.store import TransportStore, hash_prefix
from bzrlib.atomicfile import AtomicFile
from bzrlib.errors import NoSuchFile, FileExists
from bzrlib.symbol_versioning import *
from bzrlib.trace import mutter


class WeaveStore(TransportStore):
    """Collection of several weave files in a directory.

    This has some shortcuts for reading and writing them.
    """
    FILE_SUFFIX = '.weave'

    def __init__(self, transport, prefixed=False, precious=False,
                 dir_mode=None, file_mode=None):
        super(WeaveStore, self).__init__(transport,
                dir_mode=dir_mode, file_mode=file_mode,
                prefixed=prefixed, compressed=False)
        self._precious = precious

    def filename(self, file_id):
        """Return the path relative to the transport root."""
        if self._prefixed:
            return hash_prefix(file_id) + urllib.quote(file_id) + WeaveStore.FILE_SUFFIX
        else:
            return urllib.quote(file_id) + WeaveStore.FILE_SUFFIX

    def __iter__(self):
        l = len(WeaveStore.FILE_SUFFIX)
        for relpath in self._iter_files_recursive():
            if relpath.endswith(WeaveStore.FILE_SUFFIX):
                yield os.path.basename(relpath[:-l])

    def has_id(self, fileid):
        return self._transport.has(self.filename(fileid))

    def _get(self, file_id):
        return self._transport.get(self.filename(file_id))

    def _put(self, file_id, f):
        # less round trips to mkdir on failure than mkdir always
        try:
            return self._transport.put(self.filename(file_id), f, mode=self._file_mode)
        except NoSuchFile:
            if not self._prefixed:
                raise
            self._transport.mkdir(hash_prefix(file_id), mode=self._dir_mode)
            return self._transport.put(self.filename(file_id), f, mode=self._file_mode)

    def get_weave(self, file_id, transaction):
        weave = transaction.map.find_weave(file_id)
        if weave:
            mutter("cache hit in %s for %s", self, file_id)
            return weave
        w = WeaveFile(self.filename(file_id), self._transport, self._file_mode)
        transaction.map.add_weave(file_id, w)
        transaction.register_clean(w, precious=self._precious)
        # TODO: jam 20051219 This should check if there is a prelude
        #       which is already cached, and if so, should remove it
        #       But transaction doesn't seem to have a 'remove'
        #       One workaround would be to re-add the object with
        #       the PRELUDE marker.
        return w

    def get_weave_prelude(self, file_id, transaction):
        weave_id = file_id
        weave = transaction.map.find_weave(weave_id)
        if weave:
            mutter("cache hit in %s for %s", self, weave_id)
            return weave
        w = read_weave(self._get(file_id), prelude=True)
        # no point caching the prelude: any repeat action will need the real 
        # thing
        return w

    def get_lines(self, file_id, rev_id, transaction):
        """Return text from a particular version of a weave.

        Returned as a list of lines."""
        w = self.get_weave(file_id, transaction)
        return w.get(rev_id)
    
    def get_weave_prelude_or_empty(self, file_id, transaction):
        """cheap version that reads the prelude but not the lines
        """
        try:
            return self.get_weave_prelude(file_id, transaction)
        except NoSuchFile:
            # returns more than needed - harmless as its empty.
            return self._new_weave(file_id, transaction)

    def _new_weave(self, file_id, transaction):
        """Make a new weave for file_id and return it."""
        weave = WeaveFile(self.filename(file_id), self._transport, self._file_mode)
        # ensure that the directories are created.
        # this is so that weave does not encounter ENOTDIR etc.
        weave_stream = self._weave_to_stream(weave)
        self._put(file_id, weave_stream)
        transaction.map.add_weave(file_id, weave)
        transaction.register_clean(weave, precious=self._precious)
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
        transaction.register_dirty(weave)
        weave_stream = self._weave_to_stream(weave)
        self._put(file_id, weave_stream)

    def _weave_to_stream(self, weave):
        """Make a stream from a weave."""
        sio = StringIO()
        write_weave_v5(weave, sio)
        sio.seek(0)
        return sio

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
     
    def copy_multi(self, from_store, file_ids, pb=None, from_transaction=None):
        assert isinstance(from_store, WeaveStore)
        for count, f in enumerate(file_ids):
            mutter("copy weave {%s} into %s", f, self)
            if pb:
                pb.update('copy', count, len(file_ids))
            # if we have it in cache, its faster.
            if from_transaction and from_transaction.map.find_weave(f):
                mutter("cache hit in %s for %s", from_store, f)
                weave = from_transaction.map.find_weave(f)
                weave_stream = self._weave_to_stream(weave)
                self._put(f, weave_stream)
            else:
                self._put(f, from_store._get(f))
        if pb:
            pb.clear()

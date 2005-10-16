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


from cStringIO import StringIO
import os
import errno

from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.weave import Weave
from bzrlib.store import TransportStore, hash_prefix
from bzrlib.atomicfile import AtomicFile
from bzrlib.errors import NoSuchFile, FileExists
from bzrlib.trace import mutter


class WeaveStore(TransportStore):
    """Collection of several weave files in a directory.

    This has some shortcuts for reading and writing them.
    """
    FILE_SUFFIX = '.weave'

    def __init__(self, transport, prefixed=False, precious=False):
        self._transport = transport
        self._prefixed = prefixed
        self._precious = precious

    def filename(self, file_id):
        """Return the path relative to the transport root."""
        if self._prefixed:
            return hash_prefix(file_id) + file_id + WeaveStore.FILE_SUFFIX
        else:
            return file_id + WeaveStore.FILE_SUFFIX

    def __iter__(self):
        l = len(WeaveStore.FILE_SUFFIX)
        for relpath in self._transport.iter_files_recursive():
            if relpath.endswith(WeaveStore.FILE_SUFFIX):
                yield os.path.basename(relpath[:-l])

    def has_id(self, fileid):
        return self._transport.has(self.filename(fileid))

    def _get(self, file_id):
        return self._transport.get(self.filename(file_id))

    def _put(self, file_id, f):
        if self._prefixed:
            try:
                self._transport.mkdir(hash_prefix(file_id))
            except FileExists:
                pass
        return self._transport.put(self.filename(file_id), f)

    def get_weave(self, file_id, transaction):
        weave = transaction.map.find_weave(file_id)
        if weave:
            mutter("cache hit in %s for %s", self, file_id)
            return weave
        w = read_weave(self._get(file_id))
        transaction.map.add_weave(file_id, w)
        transaction.register_clean(w, precious=self._precious)
        return w

    def get_lines(self, file_id, rev_id, transaction):
        """Return text from a particular version of a weave.

        Returned as a list of lines."""
        w = self.get_weave(file_id, transaction)
        return w.get(w.lookup(rev_id))
    
    def get_weave_or_empty(self, file_id, transaction):
        """Return a weave, or an empty one if it doesn't exist.""" 
        try:
            return self.get_weave(file_id, transaction)
        except NoSuchFile:
            weave = Weave(weave_name=file_id)
            transaction.map.add_weave(file_id, weave)
            transaction.register_clean(weave, precious=self._precious)
            return weave

    def put_weave(self, file_id, weave, transaction):
        """Write back a modified weave"""
        transaction.register_dirty(weave)
        # TODO FOR WRITE TRANSACTIONS: this should be done in a callback
        # from the transaction, when it decides to save.
        sio = StringIO()
        write_weave_v5(weave, sio)
        sio.seek(0)
        self._put(file_id, sio)

    def add_text(self, file_id, rev_id, new_lines, parents, transaction):
        w = self.get_weave_or_empty(file_id, transaction)
        parent_idxs = map(w.lookup, parents)
        w.add(rev_id, parent_idxs, new_lines)
        self.put_weave(file_id, w, transaction)
        
    def add_identical_text(self, file_id, old_rev_id, new_rev_id, parents,
                           transaction):
        w = self.get_weave_or_empty(file_id, transaction)
        parent_idxs = map(w.lookup, parents)
        w.add_identical(old_rev_id, new_rev_id, parent_idxs)
        self.put_weave(file_id, w, transaction)
     
    def copy_multi(self, from_store, file_ids):
        assert isinstance(from_store, WeaveStore)
        for f in file_ids:
            mutter("copy weave {%s} into %s", f, self)
            self._put(f, from_store._get(f))

# groupcompress, a bzr plugin providing improved disk utilisation
# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Repostory formats using B+Tree indices and groupcompress compression."""

import md5
import time

from bzrlib import debug, errors, pack, repository
from bzrlib.index import GraphIndex, GraphIndexBuilder
from bzrlib.repository import InterPackRepo
from bzrlib.plugins.groupcompress.groupcompress import (
    _GCGraphIndex,
    GroupCompressVersionedFiles,
    )
from bzrlib.plugins.index2.btree_index import (
    BTreeBuilder,
    BTreeGraphIndex,
    FixedMemoryGraphIndex,
    )
from bzrlib.osutils import rand_chars
from bzrlib.repofmt.pack_repo import (
    Pack,
    NewPack,
    KnitPackRepository,
    RepositoryPackCollection,
    RepositoryFormatPackDevelopment0,
    RepositoryFormatPackDevelopment0Subtree,
    RepositoryFormatKnitPack1,
    RepositoryFormatKnitPack3,
    RepositoryFormatKnitPack4,
    Packer,
    ReconcilePacker,
    OptimisingPacker,
    )
from bzrlib import ui


def open_pack(self):
    return self._pack_collection.pack_factory(self._pack_collection._upload_transport,
        self._pack_collection._index_transport,
        self._pack_collection._pack_transport, upload_suffix=self.suffix,
        file_mode=self._pack_collection.repo.bzrdir._get_file_mode())


Packer.open_pack = open_pack


class GCPack(NewPack):

    def __init__(self, upload_transport, index_transport, pack_transport,
        upload_suffix='', file_mode=None):
        """Create a NewPack instance.

        :param upload_transport: A writable transport for the pack to be
            incrementally uploaded to.
        :param index_transport: A writable transport for the pack's indices to
            be written to when the pack is finished.
        :param pack_transport: A writable transport for the pack to be renamed
            to when the upload is complete. This *must* be the same as
            upload_transport.clone('../packs').
        :param upload_suffix: An optional suffix to be given to any temporary
            files created during the pack creation. e.g '.autopack'
        :param file_mode: An optional file mode to create the new files with.
        """
        # The relative locations of the packs are constrained, but all are
        # passed in because the caller has them, so as to avoid object churn.
        Pack.__init__(self,
            # Revisions: parents list, no text compression.
            BTreeBuilder(reference_lists=1),
            # Inventory: compressed, with graph for compatibility with other
            # existing bzrlib code.
            BTreeBuilder(reference_lists=1),
            # Texts: per file graph:
            BTreeBuilder(reference_lists=1, key_elements=2),
            # Signatures: Just blobs to store, no compression, no parents
            # listing.
            BTreeBuilder(reference_lists=0),
            )
        # where should the new pack be opened
        self.upload_transport = upload_transport
        # where are indices written out to
        self.index_transport = index_transport
        # where is the pack renamed to when it is finished?
        self.pack_transport = pack_transport
        # What file mode to upload the pack and indices with.
        self._file_mode = file_mode
        # tracks the content written to the .pack file.
        self._hash = md5.new()
        # a four-tuple with the length in bytes of the indices, once the pack
        # is finalised. (rev, inv, text, sigs)
        self.index_sizes = None
        # How much data to cache when writing packs. Note that this is not
        # synchronised with reads, because it's not in the transport layer, so
        # is not safe unless the client knows it won't be reading from the pack
        # under creation.
        self._cache_limit = 0
        # the temporary pack file name.
        self.random_name = rand_chars(20) + upload_suffix
        # when was this pack started ?
        self.start_time = time.time()
        # open an output stream for the data added to the pack.
        self.write_stream = self.upload_transport.open_write_stream(
            self.random_name, mode=self._file_mode)
        if 'pack' in debug.debug_flags:
            mutter('%s: create_pack: pack stream open: %s%s t+%6.3fs',
                time.ctime(), self.upload_transport.base, self.random_name,
                time.time() - self.start_time)
        # A list of byte sequences to be written to the new pack, and the 
        # aggregate size of them.  Stored as a list rather than separate 
        # variables so that the _write_data closure below can update them.
        self._buffer = [[], 0]
        # create a callable for adding data 
        #
        # robertc says- this is a closure rather than a method on the object
        # so that the variables are locals, and faster than accessing object
        # members.
        def _write_data(bytes, flush=False, _buffer=self._buffer,
            _write=self.write_stream.write, _update=self._hash.update):
            _buffer[0].append(bytes)
            _buffer[1] += len(bytes)
            # buffer cap
            if _buffer[1] > self._cache_limit or flush:
                bytes = ''.join(_buffer[0])
                _write(bytes)
                _update(bytes)
                _buffer[:] = [[], 0]
        # expose this on self, for the occasion when clients want to add data.
        self._write_data = _write_data
        # a pack writer object to serialise pack records.
        self._writer = pack.ContainerWriter(self._write_data)
        self._writer.begin()
        # what state is the pack in? (open, finished, aborted)
        self._state = 'open'

    def _replace_index_with_readonly(self, index_type):
        setattr(self, index_type + '_index',
            BTreeGraphIndex(self.index_transport,
                self.index_name(index_type, self.name),
                self.index_sizes[self.index_offset(index_type)]))


RepositoryPackCollection.pack_factory = NewPack

class GCRepositoryPackCollection(RepositoryPackCollection):

    pack_factory = GCPack

    def _make_index(self, name, suffix):
        """Overridden to use BTreeGraphIndex objects."""
        size_offset = self._suffix_offsets[suffix]
        index_name = name + suffix
        index_size = self._names[name][size_offset]
        return BTreeGraphIndex(
            self._index_transport, index_name, index_size)

    def _start_write_group(self):
        # Do not permit preparation for writing if we're not in a 'write lock'.
        if not self.repo.is_write_locked():
            raise errors.NotWriteLocked(self)
        self._new_pack = self.pack_factory(self._upload_transport, self._index_transport,
            self._pack_transport, upload_suffix='.pack',
            file_mode=self.repo.bzrdir._get_file_mode())
        # allow writing: queue writes to a new index
        self.revision_index.add_writable_index(self._new_pack.revision_index,
            self._new_pack)
        self.inventory_index.add_writable_index(self._new_pack.inventory_index,
            self._new_pack)
        self.text_index.add_writable_index(self._new_pack.text_index,
            self._new_pack)
        self.signature_index.add_writable_index(self._new_pack.signature_index,
            self._new_pack)

        self.repo.inventories._index._add_callback = self.inventory_index.add_callback
        self.repo.revisions._index._add_callback = self.revision_index.add_callback
        self.repo.signatures._index._add_callback = self.signature_index.add_callback
        self.repo.texts._index._add_callback = self.text_index.add_callback



class GCPackRepository(KnitPackRepository):
    """GC customisation of KnitPackRepository."""

    def __init__(self, _format, a_bzrdir, control_files, _commit_builder_class,
        _serializer):
        """Overridden to change pack collection class."""
        KnitPackRepository.__init__(self, _format, a_bzrdir, control_files,
            _commit_builder_class, _serializer)
        # and now replace everything it did :)
        index_transport = self._transport.clone('indices')
        self._pack_collection = GCRepositoryPackCollection(self,
            self._transport, index_transport,
            self._transport.clone('upload'),
            self._transport.clone('packs'))
        self.inventories = GroupCompressVersionedFiles(
            _GCGraphIndex(self._pack_collection.inventory_index.combined_index,
                add_callback=self._pack_collection.inventory_index.add_callback,
                parents=True, is_locked=self.is_locked),
            access=self._pack_collection.inventory_index.data_access)
        self.revisions = GroupCompressVersionedFiles(
            _GCGraphIndex(self._pack_collection.revision_index.combined_index,
                add_callback=self._pack_collection.revision_index.add_callback,
                parents=True, is_locked=self.is_locked),
            access=self._pack_collection.revision_index.data_access,
            delta=False)
        self.signatures = GroupCompressVersionedFiles(
            _GCGraphIndex(self._pack_collection.signature_index.combined_index,
                add_callback=self._pack_collection.signature_index.add_callback,
                parents=False, is_locked=self.is_locked),
            access=self._pack_collection.signature_index.data_access,
            delta=False)
        self.texts = GroupCompressVersionedFiles(
            _GCGraphIndex(self._pack_collection.text_index.combined_index,
                add_callback=self._pack_collection.text_index.add_callback,
                parents=True, is_locked=self.is_locked),
            access=self._pack_collection.text_index.data_access)
        # True when the repository object is 'write locked' (as opposed to the
        # physical lock only taken out around changes to the pack-names list.) 
        # Another way to represent this would be a decorator around the control
        # files object that presents logical locks as physical ones - if this
        # gets ugly consider that alternative design. RBC 20071011
        self._write_lock_count = 0
        self._transaction = None
        # for tests
        self._reconcile_does_inventory_gc = True
        self._reconcile_fixes_text_parents = True
        self._reconcile_backsup_inventory = False


class RepositoryFormatPackGCPlain(RepositoryFormatPackDevelopment0):
    """A B+Tree index using pack repository."""

    repository_class = GCPackRepository

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format - btree+gc "
            "(needs bzr.dev from 1.6)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format - btree+groupcompress "
            ", interoperates with pack-0.92\n")


class RepositoryFormatPackGCRichRoot(RepositoryFormatKnitPack4):
    """A B+Tree index using pack repository."""

    repository_class = GCPackRepository

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format - btree+gc-rich-root "
            "(needs bzr.dev from 1.6)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format - btree+groupcompress "
            ", interoperates with rich-root-pack\n")


class RepositoryFormatPackGCSubtrees(RepositoryFormatPackDevelopment0Subtree):
    """A B+Tree index using pack repository."""

    repository_class = GCPackRepository

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format - btree+gc-subtrees "
            "(needs bzr.dev from 1.6)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format - btree+groupcompress "
            ", interoperates with pack-0.92-subtrees\n")


def pack_incompatible(source, target, orig_method=InterPackRepo.is_compatible):
    formats = (RepositoryFormatPackGCPlain, RepositoryFormatPackGCRichRoot,
        RepositoryFormatPackGCSubtrees)
    if isinstance(source._format, formats) or isinstance(target._format, formats):
        return False
    else:
        return orig_method(source, target)


InterPackRepo.is_compatible = staticmethod(pack_incompatible)

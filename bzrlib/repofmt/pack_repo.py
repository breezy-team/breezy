# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from itertools import izip
import md5
import time

from bzrlib import (
    debug,
    graph,
    pack,
    transactions,
    ui,
    )
from bzrlib.index import (
    GraphIndex,
    GraphIndexBuilder,
    InMemoryGraphIndex,
    CombinedGraphIndex,
    GraphIndexPrefixAdapter,
    )
from bzrlib.knit import (
    KnitPlainFactory,
    KnitVersionedFiles,
    _KnitGraphIndex,
    _DirectPackAccess,
    )
from bzrlib.osutils import rand_chars, split_lines
from bzrlib import tsort
""")
from bzrlib import (
    bzrdir,
    errors,
    lockable_files,
    lockdir,
    symbol_versioning,
    xml5,
    xml6,
    xml7,
    )

from bzrlib.decorators import needs_write_lock
from bzrlib.repofmt.knitrepo import KnitRepository
from bzrlib.repository import (
    CommitBuilder,
    MetaDirRepositoryFormat,
    RepositoryFormat,
    RootCommitBuilder,
    )
import bzrlib.revision as _mod_revision
from bzrlib.trace import (
    mutter,
    warning,
    )


class PackCommitBuilder(CommitBuilder):
    """A subclass of CommitBuilder to add texts with pack semantics.
    
    Specifically this uses one knit object rather than one knit object per
    added text, reducing memory and object pressure.
    """

    def __init__(self, repository, parents, config, timestamp=None,
                 timezone=None, committer=None, revprops=None,
                 revision_id=None):
        CommitBuilder.__init__(self, repository, parents, config,
            timestamp=timestamp, timezone=timezone, committer=committer,
            revprops=revprops, revision_id=revision_id)
        self._file_graph = graph.Graph(
            repository._pack_collection.text_index.combined_index)

    def _heads(self, file_id, revision_ids):
        keys = [(file_id, revision_id) for revision_id in revision_ids]
        return set([key[1] for key in self._file_graph.heads(keys)])


class PackRootCommitBuilder(RootCommitBuilder):
    """A subclass of RootCommitBuilder to add texts with pack semantics.
    
    Specifically this uses one knit object rather than one knit object per
    added text, reducing memory and object pressure.
    """

    def __init__(self, repository, parents, config, timestamp=None,
                 timezone=None, committer=None, revprops=None,
                 revision_id=None):
        CommitBuilder.__init__(self, repository, parents, config,
            timestamp=timestamp, timezone=timezone, committer=committer,
            revprops=revprops, revision_id=revision_id)
        self._file_graph = graph.Graph(
            repository._pack_collection.text_index.combined_index)

    def _heads(self, file_id, revision_ids):
        keys = [(file_id, revision_id) for revision_id in revision_ids]
        return set([key[1] for key in self._file_graph.heads(keys)])


class Pack(object):
    """An in memory proxy for a pack and its indices.

    This is a base class that is not directly used, instead the classes
    ExistingPack and NewPack are used.
    """

    def __init__(self, revision_index, inventory_index, text_index,
        signature_index):
        """Create a pack instance.

        :param revision_index: A GraphIndex for determining what revisions are
            present in the Pack and accessing the locations of their texts.
        :param inventory_index: A GraphIndex for determining what inventories are
            present in the Pack and accessing the locations of their
            texts/deltas.
        :param text_index: A GraphIndex for determining what file texts
            are present in the pack and accessing the locations of their
            texts/deltas (via (fileid, revisionid) tuples).
        :param signature_index: A GraphIndex for determining what signatures are
            present in the Pack and accessing the locations of their texts.
        """
        self.revision_index = revision_index
        self.inventory_index = inventory_index
        self.text_index = text_index
        self.signature_index = signature_index

    def access_tuple(self):
        """Return a tuple (transport, name) for the pack content."""
        return self.pack_transport, self.file_name()

    def file_name(self):
        """Get the file name for the pack on disk."""
        return self.name + '.pack'

    def get_revision_count(self):
        return self.revision_index.key_count()

    def inventory_index_name(self, name):
        """The inv index is the name + .iix."""
        return self.index_name('inventory', name)

    def revision_index_name(self, name):
        """The revision index is the name + .rix."""
        return self.index_name('revision', name)

    def signature_index_name(self, name):
        """The signature index is the name + .six."""
        return self.index_name('signature', name)

    def text_index_name(self, name):
        """The text index is the name + .tix."""
        return self.index_name('text', name)

    def _external_compression_parents_of_texts(self):
        keys = set()
        refs = set()
        for node in self.text_index.iter_all_entries():
            keys.add(node[1])
            refs.update(node[3][1])
        return refs - keys


class ExistingPack(Pack):
    """An in memory proxy for an existing .pack and its disk indices."""

    def __init__(self, pack_transport, name, revision_index, inventory_index,
        text_index, signature_index):
        """Create an ExistingPack object.

        :param pack_transport: The transport where the pack file resides.
        :param name: The name of the pack on disk in the pack_transport.
        """
        Pack.__init__(self, revision_index, inventory_index, text_index,
            signature_index)
        self.name = name
        self.pack_transport = pack_transport
        if None in (revision_index, inventory_index, text_index,
                signature_index, name, pack_transport):
            raise AssertionError()

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<bzrlib.repofmt.pack_repo.Pack object at 0x%x, %s, %s" % (
            id(self), self.pack_transport, self.name)


class NewPack(Pack):
    """An in memory proxy for a pack which is being created."""

    # A map of index 'type' to the file extension and position in the
    # index_sizes array.
    index_definitions = {
        'revision': ('.rix', 0),
        'inventory': ('.iix', 1),
        'text': ('.tix', 2),
        'signature': ('.six', 3),
        }

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
            InMemoryGraphIndex(reference_lists=1),
            # Inventory: We want to map compression only, but currently the
            # knit code hasn't been updated enough to understand that, so we
            # have a regular 2-list index giving parents and compression
            # source.
            InMemoryGraphIndex(reference_lists=2),
            # Texts: compression and per file graph, for all fileids - so two
            # reference lists and two elements in the key tuple.
            InMemoryGraphIndex(reference_lists=2, key_elements=2),
            # Signatures: Just blobs to store, no compression, no parents
            # listing.
            InMemoryGraphIndex(reference_lists=0),
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

    def abort(self):
        """Cancel creating this pack."""
        self._state = 'aborted'
        self.write_stream.close()
        # Remove the temporary pack file.
        self.upload_transport.delete(self.random_name)
        # The indices have no state on disk.

    def access_tuple(self):
        """Return a tuple (transport, name) for the pack content."""
        if self._state == 'finished':
            return Pack.access_tuple(self)
        elif self._state == 'open':
            return self.upload_transport, self.random_name
        else:
            raise AssertionError(self._state)

    def data_inserted(self):
        """True if data has been added to this pack."""
        return bool(self.get_revision_count() or
            self.inventory_index.key_count() or
            self.text_index.key_count() or
            self.signature_index.key_count())

    def finish(self):
        """Finish the new pack.

        This:
         - finalises the content
         - assigns a name (the md5 of the content, currently)
         - writes out the associated indices
         - renames the pack into place.
         - stores the index size tuple for the pack in the index_sizes
           attribute.
        """
        self._writer.end()
        if self._buffer[1]:
            self._write_data('', flush=True)
        self.name = self._hash.hexdigest()
        # write indices
        # XXX: It'd be better to write them all to temporary names, then
        # rename them all into place, so that the window when only some are
        # visible is smaller.  On the other hand none will be seen until
        # they're in the names list.
        self.index_sizes = [None, None, None, None]
        self._write_index('revision', self.revision_index, 'revision')
        self._write_index('inventory', self.inventory_index, 'inventory')
        self._write_index('text', self.text_index, 'file texts')
        self._write_index('signature', self.signature_index,
            'revision signatures')
        self.write_stream.close()
        # Note that this will clobber an existing pack with the same name,
        # without checking for hash collisions. While this is undesirable this
        # is something that can be rectified in a subsequent release. One way
        # to rectify it may be to leave the pack at the original name, writing
        # its pack-names entry as something like 'HASH: index-sizes
        # temporary-name'. Allocate that and check for collisions, if it is
        # collision free then rename it into place. If clients know this scheme
        # they can handle missing-file errors by:
        #  - try for HASH.pack
        #  - try for temporary-name
        #  - refresh the pack-list to see if the pack is now absent
        self.upload_transport.rename(self.random_name,
                '../packs/' + self.name + '.pack')
        self._state = 'finished'
        if 'pack' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: pack renamed into place: %s%s->%s%s t+%6.3fs',
                time.ctime(), self.upload_transport.base, self.random_name,
                self.pack_transport, self.name,
                time.time() - self.start_time)

    def flush(self):
        """Flush any current data."""
        if self._buffer[1]:
            bytes = ''.join(self._buffer[0])
            self.write_stream.write(bytes)
            self._hash.update(bytes)
            self._buffer[:] = [[], 0]

    def index_name(self, index_type, name):
        """Get the disk name of an index type for pack name 'name'."""
        return name + NewPack.index_definitions[index_type][0]

    def index_offset(self, index_type):
        """Get the position in a index_size array for a given index type."""
        return NewPack.index_definitions[index_type][1]

    def _replace_index_with_readonly(self, index_type):
        setattr(self, index_type + '_index',
            GraphIndex(self.index_transport,
                self.index_name(index_type, self.name),
                self.index_sizes[self.index_offset(index_type)]))

    def set_write_cache_size(self, size):
        self._cache_limit = size

    def _write_index(self, index_type, index, label):
        """Write out an index.

        :param index_type: The type of index to write - e.g. 'revision'.
        :param index: The index object to serialise.
        :param label: What label to give the index e.g. 'revision'.
        """
        index_name = self.index_name(index_type, self.name)
        self.index_sizes[self.index_offset(index_type)] = \
            self.index_transport.put_file(index_name, index.finish(),
            mode=self._file_mode)
        if 'pack' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: wrote %s index: %s%s t+%6.3fs',
                time.ctime(), label, self.upload_transport.base,
                self.random_name, time.time() - self.start_time)
        # Replace the writable index on this object with a readonly, 
        # presently unloaded index. We should alter
        # the index layer to make its finish() error if add_node is
        # subsequently used. RBC
        self._replace_index_with_readonly(index_type)


class AggregateIndex(object):
    """An aggregated index for the RepositoryPackCollection.

    AggregateIndex is reponsible for managing the PackAccess object,
    Index-To-Pack mapping, and all indices list for a specific type of index
    such as 'revision index'.

    A CombinedIndex provides an index on a single key space built up
    from several on-disk indices.  The AggregateIndex builds on this 
    to provide a knit access layer, and allows having up to one writable
    index within the collection.
    """
    # XXX: Probably 'can be written to' could/should be separated from 'acts
    # like a knit index' -- mbp 20071024

    def __init__(self):
        """Create an AggregateIndex."""
        self.index_to_pack = {}
        self.combined_index = CombinedGraphIndex([])
        self.data_access = _DirectPackAccess(self.index_to_pack)
        self.add_callback = None

    def replace_indices(self, index_to_pack, indices):
        """Replace the current mappings with fresh ones.

        This should probably not be used eventually, rather incremental add and
        removal of indices. It has been added during refactoring of existing
        code.

        :param index_to_pack: A mapping from index objects to
            (transport, name) tuples for the pack file data.
        :param indices: A list of indices.
        """
        # refresh the revision pack map dict without replacing the instance.
        self.index_to_pack.clear()
        self.index_to_pack.update(index_to_pack)
        # XXX: API break - clearly a 'replace' method would be good?
        self.combined_index._indices[:] = indices
        # the current add nodes callback for the current writable index if
        # there is one.
        self.add_callback = None

    def add_index(self, index, pack):
        """Add index to the aggregate, which is an index for Pack pack.

        Future searches on the aggregate index will seach this new index
        before all previously inserted indices.
        
        :param index: An Index for the pack.
        :param pack: A Pack instance.
        """
        # expose it to the index map
        self.index_to_pack[index] = pack.access_tuple()
        # put it at the front of the linear index list
        self.combined_index.insert_index(0, index)

    def add_writable_index(self, index, pack):
        """Add an index which is able to have data added to it.

        There can be at most one writable index at any time.  Any
        modifications made to the knit are put into this index.
        
        :param index: An index from the pack parameter.
        :param pack: A Pack instance.
        """
        if self.add_callback is not None:
            raise AssertionError(
                "%s already has a writable index through %s" % \
                (self, self.add_callback))
        # allow writing: queue writes to a new index
        self.add_index(index, pack)
        # Updates the index to packs mapping as a side effect,
        self.data_access.set_writer(pack._writer, index, pack.access_tuple())
        self.add_callback = index.add_nodes

    def clear(self):
        """Reset all the aggregate data to nothing."""
        self.data_access.set_writer(None, None, (None, None))
        self.index_to_pack.clear()
        del self.combined_index._indices[:]
        self.add_callback = None

    def remove_index(self, index, pack):
        """Remove index from the indices used to answer queries.
        
        :param index: An index from the pack parameter.
        :param pack: A Pack instance.
        """
        del self.index_to_pack[index]
        self.combined_index._indices.remove(index)
        if (self.add_callback is not None and
            getattr(index, 'add_nodes', None) == self.add_callback):
            self.add_callback = None
            self.data_access.set_writer(None, None, (None, None))


class Packer(object):
    """Create a pack from packs."""

    def __init__(self, pack_collection, packs, suffix, revision_ids=None):
        """Create a Packer.

        :param pack_collection: A RepositoryPackCollection object where the
            new pack is being written to.
        :param packs: The packs to combine.
        :param suffix: The suffix to use on the temporary files for the pack.
        :param revision_ids: Revision ids to limit the pack to.
        """
        self.packs = packs
        self.suffix = suffix
        self.revision_ids = revision_ids
        # The pack object we are creating.
        self.new_pack = None
        self._pack_collection = pack_collection
        # The index layer keys for the revisions being copied. None for 'all
        # objects'.
        self._revision_keys = None
        # What text keys to copy. None for 'all texts'. This is set by
        # _copy_inventory_texts
        self._text_filter = None
        self._extra_init()

    def _extra_init(self):
        """A template hook to allow extending the constructor trivially."""

    def pack(self, pb=None):
        """Create a new pack by reading data from other packs.

        This does little more than a bulk copy of data. One key difference
        is that data with the same item key across multiple packs is elided
        from the output. The new pack is written into the current pack store
        along with its indices, and the name added to the pack names. The 
        source packs are not altered and are not required to be in the current
        pack collection.

        :param pb: An optional progress bar to use. A nested bar is created if
            this is None.
        :return: A Pack object, or None if nothing was copied.
        """
        # open a pack - using the same name as the last temporary file
        # - which has already been flushed, so its safe.
        # XXX: - duplicate code warning with start_write_group; fix before
        #      considering 'done'.
        if self._pack_collection._new_pack is not None:
            raise errors.BzrError('call to create_pack_from_packs while '
                'another pack is being written.')
        if self.revision_ids is not None:
            if len(self.revision_ids) == 0:
                # silly fetch request.
                return None
            else:
                self.revision_ids = frozenset(self.revision_ids)
                self.revision_keys = frozenset((revid,) for revid in
                    self.revision_ids)
        if pb is None:
            self.pb = ui.ui_factory.nested_progress_bar()
        else:
            self.pb = pb
        try:
            return self._create_pack_from_packs()
        finally:
            if pb is None:
                self.pb.finished()

    def open_pack(self):
        """Open a pack for the pack we are creating."""
        return NewPack(self._pack_collection._upload_transport,
            self._pack_collection._index_transport,
            self._pack_collection._pack_transport, upload_suffix=self.suffix,
            file_mode=self._pack_collection.repo.bzrdir._get_file_mode())

    def _copy_revision_texts(self):
        """Copy revision data to the new pack."""
        # select revisions
        if self.revision_ids:
            revision_keys = [(revision_id,) for revision_id in self.revision_ids]
        else:
            revision_keys = None
        # select revision keys
        revision_index_map = self._pack_collection._packs_list_to_pack_map_and_index_list(
            self.packs, 'revision_index')[0]
        revision_nodes = self._pack_collection._index_contents(revision_index_map, revision_keys)
        # copy revision keys and adjust values
        self.pb.update("Copying revision texts", 1)
        total_items, readv_group_iter = self._revision_node_readv(revision_nodes)
        list(self._copy_nodes_graph(revision_index_map, self.new_pack._writer,
            self.new_pack.revision_index, readv_group_iter, total_items))
        if 'pack' in debug.debug_flags:
            mutter('%s: create_pack: revisions copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.revision_index.key_count(),
                time.time() - self.new_pack.start_time)
        self._revision_keys = revision_keys

    def _copy_inventory_texts(self):
        """Copy the inventory texts to the new pack.

        self._revision_keys is used to determine what inventories to copy.

        Sets self._text_filter appropriately.
        """
        # select inventory keys
        inv_keys = self._revision_keys # currently the same keyspace, and note that
        # querying for keys here could introduce a bug where an inventory item
        # is missed, so do not change it to query separately without cross
        # checking like the text key check below.
        inventory_index_map = self._pack_collection._packs_list_to_pack_map_and_index_list(
            self.packs, 'inventory_index')[0]
        inv_nodes = self._pack_collection._index_contents(inventory_index_map, inv_keys)
        # copy inventory keys and adjust values
        # XXX: Should be a helper function to allow different inv representation
        # at this point.
        self.pb.update("Copying inventory texts", 2)
        total_items, readv_group_iter = self._least_readv_node_readv(inv_nodes)
        # Only grab the output lines if we will be processing them
        output_lines = bool(self.revision_ids)
        inv_lines = self._copy_nodes_graph(inventory_index_map,
            self.new_pack._writer, self.new_pack.inventory_index,
            readv_group_iter, total_items, output_lines=output_lines)
        if self.revision_ids:
            self._process_inventory_lines(inv_lines)
        else:
            # eat the iterator to cause it to execute.
            list(inv_lines)
            self._text_filter = None
        if 'pack' in debug.debug_flags:
            mutter('%s: create_pack: inventories copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.inventory_index.key_count(),
                time.time() - self.new_pack.start_time)

    def _copy_text_texts(self):
        # select text keys
        text_index_map, text_nodes = self._get_text_nodes()
        if self._text_filter is not None:
            # We could return the keys copied as part of the return value from
            # _copy_nodes_graph but this doesn't work all that well with the
            # need to get line output too, so we check separately, and as we're
            # going to buffer everything anyway, we check beforehand, which
            # saves reading knit data over the wire when we know there are
            # mising records.
            text_nodes = set(text_nodes)
            present_text_keys = set(_node[1] for _node in text_nodes)
            missing_text_keys = set(self._text_filter) - present_text_keys
            if missing_text_keys:
                # TODO: raise a specific error that can handle many missing
                # keys.
                a_missing_key = missing_text_keys.pop()
                raise errors.RevisionNotPresent(a_missing_key[1],
                    a_missing_key[0])
        # copy text keys and adjust values
        self.pb.update("Copying content texts", 3)
        total_items, readv_group_iter = self._least_readv_node_readv(text_nodes)
        list(self._copy_nodes_graph(text_index_map, self.new_pack._writer,
            self.new_pack.text_index, readv_group_iter, total_items))
        self._log_copied_texts()

    def _check_references(self):
        """Make sure our external refereneces are present."""
        external_refs = self.new_pack._external_compression_parents_of_texts()
        if external_refs:
            index = self._pack_collection.text_index.combined_index
            found_items = list(index.iter_entries(external_refs))
            if len(found_items) != len(external_refs):
                found_keys = set(k for idx, k, refs, value in found_items)
                missing_items = external_refs - found_keys
                missing_file_id, missing_revision_id = missing_items.pop()
                raise errors.RevisionNotPresent(missing_revision_id,
                                                missing_file_id)

    def _create_pack_from_packs(self):
        self.pb.update("Opening pack", 0, 5)
        self.new_pack = self.open_pack()
        new_pack = self.new_pack
        # buffer data - we won't be reading-back during the pack creation and
        # this makes a significant difference on sftp pushes.
        new_pack.set_write_cache_size(1024*1024)
        if 'pack' in debug.debug_flags:
            plain_pack_list = ['%s%s' % (a_pack.pack_transport.base, a_pack.name)
                for a_pack in self.packs]
            if self.revision_ids is not None:
                rev_count = len(self.revision_ids)
            else:
                rev_count = 'all'
            mutter('%s: create_pack: creating pack from source packs: '
                '%s%s %s revisions wanted %s t=0',
                time.ctime(), self._pack_collection._upload_transport.base, new_pack.random_name,
                plain_pack_list, rev_count)
        self._copy_revision_texts()
        self._copy_inventory_texts()
        self._copy_text_texts()
        # select signature keys
        signature_filter = self._revision_keys # same keyspace
        signature_index_map = self._pack_collection._packs_list_to_pack_map_and_index_list(
            self.packs, 'signature_index')[0]
        signature_nodes = self._pack_collection._index_contents(signature_index_map,
            signature_filter)
        # copy signature keys and adjust values
        self.pb.update("Copying signature texts", 4)
        self._copy_nodes(signature_nodes, signature_index_map, new_pack._writer,
            new_pack.signature_index)
        if 'pack' in debug.debug_flags:
            mutter('%s: create_pack: revision signatures copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._pack_collection._upload_transport.base, new_pack.random_name,
                new_pack.signature_index.key_count(),
                time.time() - new_pack.start_time)
        self._check_references()
        if not self._use_pack(new_pack):
            new_pack.abort()
            return None
        self.pb.update("Finishing pack", 5)
        new_pack.finish()
        self._pack_collection.allocate(new_pack)
        return new_pack

    def _copy_nodes(self, nodes, index_map, writer, write_index):
        """Copy knit nodes between packs with no graph references."""
        pb = ui.ui_factory.nested_progress_bar()
        try:
            return self._do_copy_nodes(nodes, index_map, writer,
                write_index, pb)
        finally:
            pb.finished()

    def _do_copy_nodes(self, nodes, index_map, writer, write_index, pb):
        # for record verification
        knit = KnitVersionedFiles(None, None)
        # plan a readv on each source pack:
        # group by pack
        nodes = sorted(nodes)
        # how to map this into knit.py - or knit.py into this?
        # we don't want the typical knit logic, we want grouping by pack
        # at this point - perhaps a helper library for the following code 
        # duplication points?
        request_groups = {}
        for index, key, value in nodes:
            if index not in request_groups:
                request_groups[index] = []
            request_groups[index].append((key, value))
        record_index = 0
        pb.update("Copied record", record_index, len(nodes))
        for index, items in request_groups.iteritems():
            pack_readv_requests = []
            for key, value in items:
                # ---- KnitGraphIndex.get_position
                bits = value[1:].split(' ')
                offset, length = int(bits[0]), int(bits[1])
                pack_readv_requests.append((offset, length, (key, value[0])))
            # linear scan up the pack
            pack_readv_requests.sort()
            # copy the data
            transport, path = index_map[index]
            reader = pack.make_readv_reader(transport, path,
                [offset[0:2] for offset in pack_readv_requests])
            for (names, read_func), (_1, _2, (key, eol_flag)) in \
                izip(reader.iter_records(), pack_readv_requests):
                raw_data = read_func(None)
                # check the header only
                df, _ = knit._parse_record_header(key, raw_data)
                df.close()
                pos, size = writer.add_bytes_record(raw_data, names)
                write_index.add_node(key, eol_flag + "%d %d" % (pos, size))
                pb.update("Copied record", record_index)
                record_index += 1

    def _copy_nodes_graph(self, index_map, writer, write_index,
        readv_group_iter, total_items, output_lines=False):
        """Copy knit nodes between packs.

        :param output_lines: Return lines present in the copied data as
            an iterator of line,version_id.
        """
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for result in self._do_copy_nodes_graph(index_map, writer,
                write_index, output_lines, pb, readv_group_iter, total_items):
                yield result
        except Exception:
            # Python 2.4 does not permit try:finally: in a generator.
            pb.finished()
            raise
        else:
            pb.finished()

    def _do_copy_nodes_graph(self, index_map, writer, write_index,
        output_lines, pb, readv_group_iter, total_items):
        # for record verification
        knit = KnitVersionedFiles(None, None)
        # for line extraction when requested (inventories only)
        if output_lines:
            factory = KnitPlainFactory()
        record_index = 0
        pb.update("Copied record", record_index, total_items)
        for index, readv_vector, node_vector in readv_group_iter:
            # copy the data
            transport, path = index_map[index]
            reader = pack.make_readv_reader(transport, path, readv_vector)
            for (names, read_func), (key, eol_flag, references) in \
                izip(reader.iter_records(), node_vector):
                raw_data = read_func(None)
                if output_lines:
                    # read the entire thing
                    content, _ = knit._parse_record(key[-1], raw_data)
                    if len(references[-1]) == 0:
                        line_iterator = factory.get_fulltext_content(content)
                    else:
                        line_iterator = factory.get_linedelta_content(content)
                    for line in line_iterator:
                        yield line, key
                else:
                    # check the header only
                    df, _ = knit._parse_record_header(key, raw_data)
                    df.close()
                pos, size = writer.add_bytes_record(raw_data, names)
                write_index.add_node(key, eol_flag + "%d %d" % (pos, size), references)
                pb.update("Copied record", record_index)
                record_index += 1

    def _get_text_nodes(self):
        text_index_map = self._pack_collection._packs_list_to_pack_map_and_index_list(
            self.packs, 'text_index')[0]
        return text_index_map, self._pack_collection._index_contents(text_index_map,
            self._text_filter)

    def _least_readv_node_readv(self, nodes):
        """Generate request groups for nodes using the least readv's.
        
        :param nodes: An iterable of graph index nodes.
        :return: Total node count and an iterator of the data needed to perform
            readvs to obtain the data for nodes. Each item yielded by the
            iterator is a tuple with:
            index, readv_vector, node_vector. readv_vector is a list ready to
            hand to the transport readv method, and node_vector is a list of
            (key, eol_flag, references) for the the node retrieved by the
            matching readv_vector.
        """
        # group by pack so we do one readv per pack
        nodes = sorted(nodes)
        total = len(nodes)
        request_groups = {}
        for index, key, value, references in nodes:
            if index not in request_groups:
                request_groups[index] = []
            request_groups[index].append((key, value, references))
        result = []
        for index, items in request_groups.iteritems():
            pack_readv_requests = []
            for key, value, references in items:
                # ---- KnitGraphIndex.get_position
                bits = value[1:].split(' ')
                offset, length = int(bits[0]), int(bits[1])
                pack_readv_requests.append(
                    ((offset, length), (key, value[0], references)))
            # linear scan up the pack to maximum range combining.
            pack_readv_requests.sort()
            # split out the readv and the node data.
            pack_readv = [readv for readv, node in pack_readv_requests]
            node_vector = [node for readv, node in pack_readv_requests]
            result.append((index, pack_readv, node_vector))
        return total, result

    def _log_copied_texts(self):
        if 'pack' in debug.debug_flags:
            mutter('%s: create_pack: file texts copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.text_index.key_count(),
                time.time() - self.new_pack.start_time)

    def _process_inventory_lines(self, inv_lines):
        """Use up the inv_lines generator and setup a text key filter."""
        repo = self._pack_collection.repo
        fileid_revisions = repo._find_file_ids_from_xml_inventory_lines(
            inv_lines, self.revision_keys)
        text_filter = []
        for fileid, file_revids in fileid_revisions.iteritems():
            text_filter.extend([(fileid, file_revid) for file_revid in file_revids])
        self._text_filter = text_filter

    def _revision_node_readv(self, revision_nodes):
        """Return the total revisions and the readv's to issue.

        :param revision_nodes: The revision index contents for the packs being
            incorporated into the new pack.
        :return: As per _least_readv_node_readv.
        """
        return self._least_readv_node_readv(revision_nodes)

    def _use_pack(self, new_pack):
        """Return True if new_pack should be used.

        :param new_pack: The pack that has just been created.
        :return: True if the pack should be used.
        """
        return new_pack.data_inserted()


class OptimisingPacker(Packer):
    """A packer which spends more time to create better disk layouts."""

    def _revision_node_readv(self, revision_nodes):
        """Return the total revisions and the readv's to issue.

        This sort places revisions in topological order with the ancestors
        after the children.

        :param revision_nodes: The revision index contents for the packs being
            incorporated into the new pack.
        :return: As per _least_readv_node_readv.
        """
        # build an ancestors dict
        ancestors = {}
        by_key = {}
        for index, key, value, references in revision_nodes:
            ancestors[key] = references[0]
            by_key[key] = (index, value, references)
        order = tsort.topo_sort(ancestors)
        total = len(order)
        # Single IO is pathological, but it will work as a starting point.
        requests = []
        for key in reversed(order):
            index, value, references = by_key[key]
            # ---- KnitGraphIndex.get_position
            bits = value[1:].split(' ')
            offset, length = int(bits[0]), int(bits[1])
            requests.append(
                (index, [(offset, length)], [(key, value[0], references)]))
        # TODO: combine requests in the same index that are in ascending order.
        return total, requests


class ReconcilePacker(Packer):
    """A packer which regenerates indices etc as it copies.
    
    This is used by ``bzr reconcile`` to cause parent text pointers to be
    regenerated.
    """

    def _extra_init(self):
        self._data_changed = False

    def _process_inventory_lines(self, inv_lines):
        """Generate a text key reference map rather for reconciling with."""
        repo = self._pack_collection.repo
        refs = repo._find_text_key_references_from_xml_inventory_lines(
            inv_lines)
        self._text_refs = refs
        # during reconcile we:
        #  - convert unreferenced texts to full texts
        #  - correct texts which reference a text not copied to be full texts
        #  - copy all others as-is but with corrected parents.
        #  - so at this point we don't know enough to decide what becomes a full
        #    text.
        self._text_filter = None

    def _copy_text_texts(self):
        """generate what texts we should have and then copy."""
        self.pb.update("Copying content texts", 3)
        # we have three major tasks here:
        # 1) generate the ideal index
        repo = self._pack_collection.repo
        ancestors = dict([(key[0], tuple(ref[0] for ref in refs[0])) for
            _1, key, _2, refs in 
            self.new_pack.revision_index.iter_all_entries()])
        ideal_index = repo._generate_text_key_index(self._text_refs, ancestors)
        # 2) generate a text_nodes list that contains all the deltas that can
        #    be used as-is, with corrected parents.
        ok_nodes = []
        bad_texts = []
        discarded_nodes = []
        NULL_REVISION = _mod_revision.NULL_REVISION
        text_index_map, text_nodes = self._get_text_nodes()
        for node in text_nodes:
            # 0 - index
            # 1 - key 
            # 2 - value
            # 3 - refs
            try:
                ideal_parents = tuple(ideal_index[node[1]])
            except KeyError:
                discarded_nodes.append(node)
                self._data_changed = True
            else:
                if ideal_parents == (NULL_REVISION,):
                    ideal_parents = ()
                if ideal_parents == node[3][0]:
                    # no change needed.
                    ok_nodes.append(node)
                elif ideal_parents[0:1] == node[3][0][0:1]:
                    # the left most parent is the same, or there are no parents
                    # today. Either way, we can preserve the representation as
                    # long as we change the refs to be inserted.
                    self._data_changed = True
                    ok_nodes.append((node[0], node[1], node[2],
                        (ideal_parents, node[3][1])))
                    self._data_changed = True
                else:
                    # Reinsert this text completely
                    bad_texts.append((node[1], ideal_parents))
                    self._data_changed = True
        # we're finished with some data.
        del ideal_index
        del text_nodes
        # 3) bulk copy the ok data
        total_items, readv_group_iter = self._least_readv_node_readv(ok_nodes)
        list(self._copy_nodes_graph(text_index_map, self.new_pack._writer,
            self.new_pack.text_index, readv_group_iter, total_items))
        # 4) adhoc copy all the other texts.
        # We have to topologically insert all texts otherwise we can fail to
        # reconcile when parts of a single delta chain are preserved intact,
        # and other parts are not. E.g. Discarded->d1->d2->d3. d1 will be
        # reinserted, and if d3 has incorrect parents it will also be
        # reinserted. If we insert d3 first, d2 is present (as it was bulk
        # copied), so we will try to delta, but d2 is not currently able to be
        # extracted because it's basis d1 is not present. Topologically sorting
        # addresses this. The following generates a sort for all the texts that
        # are being inserted without having to reference the entire text key
        # space (we only topo sort the revisions, which is smaller).
        topo_order = tsort.topo_sort(ancestors)
        rev_order = dict(zip(topo_order, range(len(topo_order))))
        bad_texts.sort(key=lambda key:rev_order[key[0][1]])
        transaction = repo.get_transaction()
        file_id_index = GraphIndexPrefixAdapter(
            self.new_pack.text_index,
            ('blank', ), 1,
            add_nodes_callback=self.new_pack.text_index.add_nodes)
        data_access = _DirectPackAccess(
                {self.new_pack.text_index:self.new_pack.access_tuple()})
        data_access.set_writer(self.new_pack._writer, self.new_pack.text_index,
            self.new_pack.access_tuple())
        output_texts = KnitVersionedFiles(
            _KnitGraphIndex(self.new_pack.text_index,
                add_callback=self.new_pack.text_index.add_nodes,
                deltas=True, parents=True, is_locked=repo.is_locked),
            data_access=data_access, max_delta_chain=200)
        for key, parent_keys in bad_texts:
            # We refer to the new pack to delta data being output.
            # A possible improvement would be to catch errors on short reads
            # and only flush then.
            self.new_pack.flush()
            parents = []
            for parent_key in parent_keys:
                if parent_key[0] != key[0]:
                    # Graph parents must match the fileid
                    raise errors.BzrError('Mismatched key parent %r:%r' %
                        (key, parent_keys))
                parents.append(parent_key[1])
            text_lines = split_lines(repo.texts.get_record_stream(
                [key], 'unordered', True).next().get_bytes_as('fulltext'))
            output_texts.add_lines(key, parent_keys, text_lines,
                random_id=True, check_content=False)
        # 5) check that nothing inserted has a reference outside the keyspace.
        missing_text_keys = self.new_pack._external_compression_parents_of_texts()
        if missing_text_keys:
            raise errors.BzrError('Reference to missing compression parents %r'
                % (missing_text_keys,))
        self._log_copied_texts()

    def _use_pack(self, new_pack):
        """Override _use_pack to check for reconcile having changed content."""
        # XXX: we might be better checking this at the copy time.
        original_inventory_keys = set()
        inv_index = self._pack_collection.inventory_index.combined_index
        for entry in inv_index.iter_all_entries():
            original_inventory_keys.add(entry[1])
        new_inventory_keys = set()
        for entry in new_pack.inventory_index.iter_all_entries():
            new_inventory_keys.add(entry[1])
        if new_inventory_keys != original_inventory_keys:
            self._data_changed = True
        return new_pack.data_inserted() and self._data_changed


class RepositoryPackCollection(object):
    """Management of packs within a repository.
    
    :ivar _names: map of {pack_name: (index_size,)}
    """

    def __init__(self, repo, transport, index_transport, upload_transport,
                 pack_transport):
        """Create a new RepositoryPackCollection.

        :param transport: Addresses the repository base directory 
            (typically .bzr/repository/).
        :param index_transport: Addresses the directory containing indices.
        :param upload_transport: Addresses the directory into which packs are written
            while they're being created.
        :param pack_transport: Addresses the directory of existing complete packs.
        """
        self.repo = repo
        self.transport = transport
        self._index_transport = index_transport
        self._upload_transport = upload_transport
        self._pack_transport = pack_transport
        self._suffix_offsets = {'.rix': 0, '.iix': 1, '.tix': 2, '.six': 3}
        self.packs = []
        # name:Pack mapping
        self._packs_by_name = {}
        # the previous pack-names content
        self._packs_at_load = None
        # when a pack is being created by this object, the state of that pack.
        self._new_pack = None
        # aggregated revision index data
        self.revision_index = AggregateIndex()
        self.inventory_index = AggregateIndex()
        self.text_index = AggregateIndex()
        self.signature_index = AggregateIndex()

    def add_pack_to_memory(self, pack):
        """Make a Pack object available to the repository to satisfy queries.
        
        :param pack: A Pack object.
        """
        if pack.name in self._packs_by_name:
            raise AssertionError()
        self.packs.append(pack)
        self._packs_by_name[pack.name] = pack
        self.revision_index.add_index(pack.revision_index, pack)
        self.inventory_index.add_index(pack.inventory_index, pack)
        self.text_index.add_index(pack.text_index, pack)
        self.signature_index.add_index(pack.signature_index, pack)
        
    def all_packs(self):
        """Return a list of all the Pack objects this repository has.

        Note that an in-progress pack being created is not returned.

        :return: A list of Pack objects for all the packs in the repository.
        """
        result = []
        for name in self.names():
            result.append(self.get_pack_by_name(name))
        return result

    def autopack(self):
        """Pack the pack collection incrementally.
        
        This will not attempt global reorganisation or recompression,
        rather it will just ensure that the total number of packs does
        not grow without bound. It uses the _max_pack_count method to
        determine if autopacking is needed, and the pack_distribution
        method to determine the number of revisions in each pack.

        If autopacking takes place then the packs name collection will have
        been flushed to disk - packing requires updating the name collection
        in synchronisation with certain steps. Otherwise the names collection
        is not flushed.

        :return: True if packing took place.
        """
        # XXX: Should not be needed when the management of indices is sane.
        total_revisions = self.revision_index.combined_index.key_count()
        total_packs = len(self._names)
        if self._max_pack_count(total_revisions) >= total_packs:
            return False
        # XXX: the following may want to be a class, to pack with a given
        # policy.
        mutter('Auto-packing repository %s, which has %d pack files, '
            'containing %d revisions into %d packs.', self, total_packs,
            total_revisions, self._max_pack_count(total_revisions))
        # determine which packs need changing
        pack_distribution = self.pack_distribution(total_revisions)
        existing_packs = []
        for pack in self.all_packs():
            revision_count = pack.get_revision_count()
            if revision_count == 0:
                # revision less packs are not generated by normal operation,
                # only by operations like sign-my-commits, and thus will not
                # tend to grow rapdily or without bound like commit containing
                # packs do - leave them alone as packing them really should
                # group their data with the relevant commit, and that may
                # involve rewriting ancient history - which autopack tries to
                # avoid. Alternatively we could not group the data but treat
                # each of these as having a single revision, and thus add 
                # one revision for each to the total revision count, to get
                # a matching distribution.
                continue
            existing_packs.append((revision_count, pack))
        pack_operations = self.plan_autopack_combinations(
            existing_packs, pack_distribution)
        self._execute_pack_operations(pack_operations)
        return True

    def _execute_pack_operations(self, pack_operations, _packer_class=Packer):
        """Execute a series of pack operations.

        :param pack_operations: A list of [revision_count, packs_to_combine].
        :param _packer_class: The class of packer to use (default: Packer).
        :return: None.
        """
        for revision_count, packs in pack_operations:
            # we may have no-ops from the setup logic
            if len(packs) == 0:
                continue
            _packer_class(self, packs, '.autopack').pack()
            for pack in packs:
                self._remove_pack_from_memory(pack)
        # record the newly available packs and stop advertising the old
        # packs
        self._save_pack_names(clear_obsolete_packs=True)
        # Move the old packs out of the way now they are no longer referenced.
        for revision_count, packs in pack_operations:
            self._obsolete_packs(packs)

    def lock_names(self):
        """Acquire the mutex around the pack-names index.
        
        This cannot be used in the middle of a read-only transaction on the
        repository.
        """
        self.repo.control_files.lock_write()

    def pack(self):
        """Pack the pack collection totally."""
        self.ensure_loaded()
        total_packs = len(self._names)
        if total_packs < 2:
            # This is arguably wrong because we might not be optimal, but for
            # now lets leave it in. (e.g. reconcile -> one pack. But not
            # optimal.
            return
        total_revisions = self.revision_index.combined_index.key_count()
        # XXX: the following may want to be a class, to pack with a given
        # policy.
        mutter('Packing repository %s, which has %d pack files, '
            'containing %d revisions into 1 packs.', self, total_packs,
            total_revisions)
        # determine which packs need changing
        pack_distribution = [1]
        pack_operations = [[0, []]]
        for pack in self.all_packs():
            pack_operations[-1][0] += pack.get_revision_count()
            pack_operations[-1][1].append(pack)
        self._execute_pack_operations(pack_operations, OptimisingPacker)

    def plan_autopack_combinations(self, existing_packs, pack_distribution):
        """Plan a pack operation.

        :param existing_packs: The packs to pack. (A list of (revcount, Pack)
            tuples).
        :param pack_distribution: A list with the number of revisions desired
            in each pack.
        """
        if len(existing_packs) <= len(pack_distribution):
            return []
        existing_packs.sort(reverse=True)
        pack_operations = [[0, []]]
        # plan out what packs to keep, and what to reorganise
        while len(existing_packs):
            # take the largest pack, and if its less than the head of the
            # distribution chart we will include its contents in the new pack for
            # that position. If its larger, we remove its size from the
            # distribution chart
            next_pack_rev_count, next_pack = existing_packs.pop(0)
            if next_pack_rev_count >= pack_distribution[0]:
                # this is already packed 'better' than this, so we can
                # not waste time packing it.
                while next_pack_rev_count > 0:
                    next_pack_rev_count -= pack_distribution[0]
                    if next_pack_rev_count >= 0:
                        # more to go
                        del pack_distribution[0]
                    else:
                        # didn't use that entire bucket up
                        pack_distribution[0] = -next_pack_rev_count
            else:
                # add the revisions we're going to add to the next output pack
                pack_operations[-1][0] += next_pack_rev_count
                # allocate this pack to the next pack sub operation
                pack_operations[-1][1].append(next_pack)
                if pack_operations[-1][0] >= pack_distribution[0]:
                    # this pack is used up, shift left.
                    del pack_distribution[0]
                    pack_operations.append([0, []])
        
        return pack_operations

    def ensure_loaded(self):
        # NB: if you see an assertion error here, its probably access against
        # an unlocked repo. Naughty.
        if not self.repo.is_locked():
            raise errors.ObjectNotLocked(self.repo)
        if self._names is None:
            self._names = {}
            self._packs_at_load = set()
            for index, key, value in self._iter_disk_pack_index():
                name = key[0]
                self._names[name] = self._parse_index_sizes(value)
                self._packs_at_load.add((key, value))
        # populate all the metadata.
        self.all_packs()

    def _parse_index_sizes(self, value):
        """Parse a string of index sizes."""
        return tuple([int(digits) for digits in value.split(' ')])

    def get_pack_by_name(self, name):
        """Get a Pack object by name.

        :param name: The name of the pack - e.g. '123456'
        :return: A Pack object.
        """
        try:
            return self._packs_by_name[name]
        except KeyError:
            rev_index = self._make_index(name, '.rix')
            inv_index = self._make_index(name, '.iix')
            txt_index = self._make_index(name, '.tix')
            sig_index = self._make_index(name, '.six')
            result = ExistingPack(self._pack_transport, name, rev_index,
                inv_index, txt_index, sig_index)
            self.add_pack_to_memory(result)
            return result

    def allocate(self, a_new_pack):
        """Allocate name in the list of packs.

        :param a_new_pack: A NewPack instance to be added to the collection of
            packs for this repository.
        """
        self.ensure_loaded()
        if a_new_pack.name in self._names:
            raise errors.BzrError(
                'Pack %r already exists in %s' % (a_new_pack.name, self))
        self._names[a_new_pack.name] = tuple(a_new_pack.index_sizes)
        self.add_pack_to_memory(a_new_pack)

    def _iter_disk_pack_index(self):
        """Iterate over the contents of the pack-names index.
        
        This is used when loading the list from disk, and before writing to
        detect updates from others during our write operation.
        :return: An iterator of the index contents.
        """
        return GraphIndex(self.transport, 'pack-names', None
                ).iter_all_entries()

    def _make_index(self, name, suffix):
        size_offset = self._suffix_offsets[suffix]
        index_name = name + suffix
        index_size = self._names[name][size_offset]
        return GraphIndex(
            self._index_transport, index_name, index_size)

    def _max_pack_count(self, total_revisions):
        """Return the maximum number of packs to use for total revisions.
        
        :param total_revisions: The total number of revisions in the
            repository.
        """
        if not total_revisions:
            return 1
        digits = str(total_revisions)
        result = 0
        for digit in digits:
            result += int(digit)
        return result

    def names(self):
        """Provide an order to the underlying names."""
        return sorted(self._names.keys())

    def _obsolete_packs(self, packs):
        """Move a number of packs which have been obsoleted out of the way.

        Each pack and its associated indices are moved out of the way.

        Note: for correctness this function should only be called after a new
        pack names index has been written without these pack names, and with
        the names of packs that contain the data previously available via these
        packs.

        :param packs: The packs to obsolete.
        :param return: None.
        """
        for pack in packs:
            pack.pack_transport.rename(pack.file_name(),
                '../obsolete_packs/' + pack.file_name())
            # TODO: Probably needs to know all possible indices for this pack
            # - or maybe list the directory and move all indices matching this
            # name whether we recognize it or not?
            for suffix in ('.iix', '.six', '.tix', '.rix'):
                self._index_transport.rename(pack.name + suffix,
                    '../obsolete_packs/' + pack.name + suffix)

    def pack_distribution(self, total_revisions):
        """Generate a list of the number of revisions to put in each pack.

        :param total_revisions: The total number of revisions in the
            repository.
        """
        if total_revisions == 0:
            return [0]
        digits = reversed(str(total_revisions))
        result = []
        for exponent, count in enumerate(digits):
            size = 10 ** exponent
            for pos in range(int(count)):
                result.append(size)
        return list(reversed(result))

    def _pack_tuple(self, name):
        """Return a tuple with the transport and file name for a pack name."""
        return self._pack_transport, name + '.pack'

    def _remove_pack_from_memory(self, pack):
        """Remove pack from the packs accessed by this repository.
        
        Only affects memory state, until self._save_pack_names() is invoked.
        """
        self._names.pop(pack.name)
        self._packs_by_name.pop(pack.name)
        self._remove_pack_indices(pack)

    def _remove_pack_indices(self, pack):
        """Remove the indices for pack from the aggregated indices."""
        self.revision_index.remove_index(pack.revision_index, pack)
        self.inventory_index.remove_index(pack.inventory_index, pack)
        self.text_index.remove_index(pack.text_index, pack)
        self.signature_index.remove_index(pack.signature_index, pack)

    def reset(self):
        """Clear all cached data."""
        # cached revision data
        self.repo._revision_knit = None
        self.revision_index.clear()
        # cached signature data
        self.repo._signature_knit = None
        self.signature_index.clear()
        # cached file text data
        self.text_index.clear()
        self.repo._text_knit = None
        # cached inventory data
        self.inventory_index.clear()
        # remove the open pack
        self._new_pack = None
        # information about packs.
        self._names = None
        self.packs = []
        self._packs_by_name = {}
        self._packs_at_load = None

    def _make_index_map(self, index_suffix):
        """Return information on existing indices.

        :param suffix: Index suffix added to pack name.

        :returns: (pack_map, indices) where indices is a list of GraphIndex 
        objects, and pack_map is a mapping from those objects to the 
        pack tuple they describe.
        """
        # TODO: stop using this; it creates new indices unnecessarily.
        self.ensure_loaded()
        suffix_map = {'.rix': 'revision_index',
            '.six': 'signature_index',
            '.iix': 'inventory_index',
            '.tix': 'text_index',
        }
        return self._packs_list_to_pack_map_and_index_list(self.all_packs(),
            suffix_map[index_suffix])

    def _packs_list_to_pack_map_and_index_list(self, packs, index_attribute):
        """Convert a list of packs to an index pack map and index list.

        :param packs: The packs list to process.
        :param index_attribute: The attribute that the desired index is found
            on.
        :return: A tuple (map, list) where map contains the dict from
            index:pack_tuple, and lsit contains the indices in the same order
            as the packs list.
        """
        indices = []
        pack_map = {}
        for pack in packs:
            index = getattr(pack, index_attribute)
            indices.append(index)
            pack_map[index] = (pack.pack_transport, pack.file_name())
        return pack_map, indices

    def _index_contents(self, pack_map, key_filter=None):
        """Get an iterable of the index contents from a pack_map.

        :param pack_map: A map from indices to pack details.
        :param key_filter: An optional filter to limit the
            keys returned.
        """
        indices = [index for index in pack_map.iterkeys()]
        all_index = CombinedGraphIndex(indices)
        if key_filter is None:
            return all_index.iter_all_entries()
        else:
            return all_index.iter_entries(key_filter)

    def _unlock_names(self):
        """Release the mutex around the pack-names index."""
        self.repo.control_files.unlock()

    def _save_pack_names(self, clear_obsolete_packs=False):
        """Save the list of packs.

        This will take out the mutex around the pack names list for the
        duration of the method call. If concurrent updates have been made, a
        three-way merge between the current list and the current in memory list
        is performed.

        :param clear_obsolete_packs: If True, clear out the contents of the
            obsolete_packs directory.
        """
        self.lock_names()
        try:
            builder = GraphIndexBuilder()
            # load the disk nodes across
            disk_nodes = set()
            for index, key, value in self._iter_disk_pack_index():
                disk_nodes.add((key, value))
            # do a two-way diff against our original content
            current_nodes = set()
            for name, sizes in self._names.iteritems():
                current_nodes.add(
                    ((name, ), ' '.join(str(size) for size in sizes)))
            deleted_nodes = self._packs_at_load - current_nodes
            new_nodes = current_nodes - self._packs_at_load
            disk_nodes.difference_update(deleted_nodes)
            disk_nodes.update(new_nodes)
            # TODO: handle same-name, index-size-changes here - 
            # e.g. use the value from disk, not ours, *unless* we're the one
            # changing it.
            for key, value in disk_nodes:
                builder.add_node(key, value)
            self.transport.put_file('pack-names', builder.finish(),
                mode=self.repo.bzrdir._get_file_mode())
            # move the baseline forward
            self._packs_at_load = disk_nodes
            if clear_obsolete_packs:
                self._clear_obsolete_packs()
        finally:
            self._unlock_names()
        # synchronise the memory packs list with what we just wrote:
        new_names = dict(disk_nodes)
        # drop no longer present nodes
        for pack in self.all_packs():
            if (pack.name,) not in new_names:
                self._remove_pack_from_memory(pack)
        # add new nodes/refresh existing ones
        for key, value in disk_nodes:
            name = key[0]
            sizes = self._parse_index_sizes(value)
            if name in self._names:
                # existing
                if sizes != self._names[name]:
                    # the pack for name has had its indices replaced - rare but
                    # important to handle. XXX: probably can never happen today
                    # because the three-way merge code above does not handle it
                    # - you may end up adding the same key twice to the new
                    # disk index because the set values are the same, unless
                    # the only index shows up as deleted by the set difference
                    # - which it may. Until there is a specific test for this,
                    # assume its broken. RBC 20071017.
                    self._remove_pack_from_memory(self.get_pack_by_name(name))
                    self._names[name] = sizes
                    self.get_pack_by_name(name)
            else:
                # new
                self._names[name] = sizes
                self.get_pack_by_name(name)

    def _clear_obsolete_packs(self):
        """Delete everything from the obsolete-packs directory.
        """
        obsolete_pack_transport = self.transport.clone('obsolete_packs')
        for filename in obsolete_pack_transport.list_dir('.'):
            try:
                obsolete_pack_transport.delete(filename)
            except (errors.PathError, errors.TransportError), e:
                warning("couldn't delete obsolete pack, skipping it:\n%s" % (e,))

    def _start_write_group(self):
        # Do not permit preparation for writing if we're not in a 'write lock'.
        if not self.repo.is_write_locked():
            raise errors.NotWriteLocked(self)
        self._new_pack = NewPack(self._upload_transport, self._index_transport,
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

    def _abort_write_group(self):
        # FIXME: just drop the transient index.
        # forget what names there are
        if self._new_pack is not None:
            self._new_pack.abort()
            self._remove_pack_indices(self._new_pack)
            self._new_pack = None
        self.repo._text_knit = None

    def _commit_write_group(self):
        self._remove_pack_indices(self._new_pack)
        if self._new_pack.data_inserted():
            # get all the data to disk and read to use
            self._new_pack.finish()
            self.allocate(self._new_pack)
            self._new_pack = None
            if not self.autopack():
                # when autopack takes no steps, the names list is still
                # unsaved.
                self._save_pack_names()
        else:
            self._new_pack.abort()
            self._new_pack = None
        self.repo._text_knit = None


class KnitPackRepository(KnitRepository):
    """Repository with knit objects stored inside pack containers.
    
    The layering for a KnitPackRepository is:

    Graph        |  HPSS    | Repository public layer |
    ===================================================
    Tuple based apis below, string based, and key based apis above
    ---------------------------------------------------
    KnitVersionedFiles
      Provides .texts, .revisions etc
      This adapts the N-tuple keys to physical knit records which only have a
      single string identifier (for historical reasons), which in older formats
      was always the revision_id, and in the mapped code for packs is always
      the last element of key tuples.
    ---------------------------------------------------
    GraphIndex
      A separate GraphIndex is used for each of the
      texts/inventories/revisions/signatures contained within each individual
      pack file. The GraphIndex layer works in N-tuples and is unaware of any
      semantic value.
    ===================================================
    
    """

    def __init__(self, _format, a_bzrdir, control_files, _commit_builder_class,
        _serializer):
        KnitRepository.__init__(self, _format, a_bzrdir, control_files,
            _commit_builder_class, _serializer)
        index_transport = self._transport.clone('indices')
        self._pack_collection = RepositoryPackCollection(self, self._transport,
            index_transport,
            self._transport.clone('upload'),
            self._transport.clone('packs'))
        self.inventories = KnitVersionedFiles(
            _KnitGraphIndex(self._pack_collection.inventory_index.combined_index,
                add_callback=self._pack_collection.inventory_index.add_callback,
                deltas=True, parents=True, is_locked=self.is_locked),
            data_access=self._pack_collection.inventory_index.data_access,
            max_delta_chain=200)
        self.revisions = KnitVersionedFiles(
            _KnitGraphIndex(self._pack_collection.revision_index.combined_index,
                add_callback=self._pack_collection.revision_index.add_callback,
                deltas=False, parents=True, is_locked=self.is_locked),
            data_access=self._pack_collection.revision_index.data_access,
            max_delta_chain=0)
        self.signatures = KnitVersionedFiles(
            _KnitGraphIndex(self._pack_collection.signature_index.combined_index,
                add_callback=self._pack_collection.signature_index.add_callback,
                deltas=False, parents=False, is_locked=self.is_locked),
            data_access=self._pack_collection.signature_index.data_access,
            max_delta_chain=0)
        self.texts = KnitVersionedFiles(
            _KnitGraphIndex(self._pack_collection.text_index.combined_index,
                add_callback=self._pack_collection.text_index.add_callback,
                deltas=True, parents=True, is_locked=self.is_locked),
            data_access=self._pack_collection.text_index.data_access,
            max_delta_chain=200)
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
        self._fetch_order = 'unordered'

    def _warn_if_deprecated(self):
        # This class isn't deprecated, but one sub-format is
        if isinstance(self._format, RepositoryFormatKnitPack5RichRootBroken):
            from bzrlib import repository
            if repository._deprecation_warning_done:
                return
            repository._deprecation_warning_done = True
            warning("Format %s for %s is deprecated - please use"
                    " 'bzr upgrade --1.6.1-rich-root'"
                    % (self._format, self.bzrdir.transport.base))

    def _abort_write_group(self):
        self._pack_collection._abort_write_group()

    def _find_inconsistent_revision_parents(self):
        """Find revisions with incorrectly cached parents.

        :returns: an iterator yielding tuples of (revison-id, parents-in-index,
            parents-in-revision).
        """
        if not self.is_locked():
            raise errors.ObjectNotLocked(self)
        pb = ui.ui_factory.nested_progress_bar()
        result = []
        try:
            revision_nodes = self._pack_collection.revision_index \
                .combined_index.iter_all_entries()
            index_positions = []
            # Get the cached index values for all revisions, and also the location
            # in each index of the revision text so we can perform linear IO.
            for index, key, value, refs in revision_nodes:
                pos, length = value[1:].split(' ')
                index_positions.append((index, int(pos), key[0],
                    tuple(parent[0] for parent in refs[0])))
                pb.update("Reading revision index.", 0, 0)
            index_positions.sort()
            batch_count = len(index_positions) / 1000 + 1
            pb.update("Checking cached revision graph.", 0, batch_count)
            for offset in xrange(batch_count):
                pb.update("Checking cached revision graph.", offset)
                to_query = index_positions[offset * 1000:(offset + 1) * 1000]
                if not to_query:
                    break
                rev_ids = [item[2] for item in to_query]
                revs = self.get_revisions(rev_ids)
                for revision, item in zip(revs, to_query):
                    index_parents = item[3]
                    rev_parents = tuple(revision.parent_ids)
                    if index_parents != rev_parents:
                        result.append((revision.revision_id, index_parents, rev_parents))
        finally:
            pb.finished()
        return result

    @symbol_versioning.deprecated_method(symbol_versioning.one_one)
    def get_parents(self, revision_ids):
        """See graph._StackedParentsProvider.get_parents."""
        parent_map = self.get_parent_map(revision_ids)
        return [parent_map.get(r, None) for r in revision_ids]

    def _make_parents_provider(self):
        return graph.CachingParentsProvider(self)

    def _refresh_data(self):
        if self._write_lock_count == 1 or (
            self.control_files._lock_count == 1 and
            self.control_files._lock_mode == 'r'):
            # forget what names there are
            self._pack_collection.reset()
            # XXX: Better to do an in-memory merge when acquiring a new lock -
            # factor out code from _save_pack_names.
            self._pack_collection.ensure_loaded()

    def _start_write_group(self):
        self._pack_collection._start_write_group()

    def _commit_write_group(self):
        return self._pack_collection._commit_write_group()

    def get_transaction(self):
        if self._write_lock_count:
            return self._transaction
        else:
            return self.control_files.get_transaction()

    def is_locked(self):
        return self._write_lock_count or self.control_files.is_locked()

    def is_write_locked(self):
        return self._write_lock_count

    def lock_write(self, token=None):
        if not self._write_lock_count and self.is_locked():
            raise errors.ReadOnlyError(self)
        self._write_lock_count += 1
        if self._write_lock_count == 1:
            self._transaction = transactions.WriteTransaction()
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
        self._refresh_data()

    def lock_read(self):
        if self._write_lock_count:
            self._write_lock_count += 1
        else:
            self.control_files.lock_read()
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
        self._refresh_data()

    def leave_lock_in_place(self):
        # not supported - raise an error
        raise NotImplementedError(self.leave_lock_in_place)

    def dont_leave_lock_in_place(self):
        # not supported - raise an error
        raise NotImplementedError(self.dont_leave_lock_in_place)

    @needs_write_lock
    def pack(self):
        """Compress the data within the repository.

        This will pack all the data to a single pack. In future it may
        recompress deltas or do other such expensive operations.
        """
        self._pack_collection.pack()

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import PackReconciler
        reconciler = PackReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler

    def unlock(self):
        if self._write_lock_count == 1 and self._write_group is not None:
            self.abort_write_group()
            self._transaction = None
            self._write_lock_count = 0
            raise errors.BzrError(
                'Must end write group before releasing write lock on %s'
                % self)
        if self._write_lock_count:
            self._write_lock_count -= 1
            if not self._write_lock_count:
                transaction = self._transaction
                self._transaction = None
                transaction.finish()
                for repo in self._fallback_repositories:
                    repo.unlock()
        else:
            self.control_files.unlock()
            for repo in self._fallback_repositories:
                repo.unlock()


class RepositoryFormatPack(MetaDirRepositoryFormat):
    """Format logic for pack structured repositories.

    This repository format has:
     - a list of packs in pack-names
     - packs in packs/NAME.pack
     - indices in indices/NAME.{iix,six,tix,rix}
     - knit deltas in the packs, knit indices mapped to the indices.
     - thunk objects to support the knits programming API.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
    """

    # Set this attribute in derived classes to control the repository class
    # created by open and initialize.
    repository_class = None
    # Set this attribute in derived classes to control the
    # _commit_builder_class that the repository objects will have passed to
    # their constructor.
    _commit_builder_class = None
    # Set this attribute in derived clases to control the _serializer that the
    # repository objects will have passed to their constructor.
    _serializer = None
    # External references are not supported in pack repositories yet.
    supports_external_lookups = False

    def initialize(self, a_bzrdir, shared=False):
        """Create a pack based repository.

        :param a_bzrdir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['indices', 'obsolete_packs', 'packs', 'upload']
        builder = GraphIndexBuilder()
        files = [('pack-names', builder.finish())]
        utf8_files = [('format', self.get_format_string())]
        
        self._upload_blank_content(a_bzrdir, dirs, files, utf8_files, shared)
        return self.open(a_bzrdir=a_bzrdir, _found=True)

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        return self.repository_class(_format=self,
                              a_bzrdir=a_bzrdir,
                              control_files=control_files,
                              _commit_builder_class=self._commit_builder_class,
                              _serializer=self._serializer)


class RepositoryFormatKnitPack1(RepositoryFormatPack):
    """A no-subtrees parameterized Pack repository.

    This format was introduced in 0.92.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    _serializer = xml5.serializer_v5

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('pack-0.92')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar pack repository format 1 (needs bzr 0.92)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs containing knits without subtree support"

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatKnitPack3(RepositoryFormatPack):
    """A subtrees parameterized Pack repository.

    This repository format uses the xml7 serializer to get:
     - support for recording full info about the tree root
     - support for recording tree-references

    This format was introduced in 0.92.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = True
    _serializer = xml7.serializer_v7

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'pack-0.92-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)
        if not getattr(target_format, 'supports_tree_reference', False):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format)
            
    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar pack repository format 1 with subtree support (needs bzr 0.92)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs containing knits with subtree support\n"


class RepositoryFormatKnitPack4(RepositoryFormatPack):
    """A rich-root, no subtrees parameterized Pack repository.

    This repository format uses the xml6 serializer to get:
     - support for recording full info about the tree root

    This format was introduced in 1.0.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = False
    _serializer = xml6.serializer_v6

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'rich-root-pack')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar pack repository format 1 with rich root"
                " (needs bzr 1.0)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs containing knits with rich root support\n"


class RepositoryFormatKnitPack5(RepositoryFormatPack):
    """Repository that supports external references to allow stacking.

    New in release 1.6.

    Supports external lookups, which results in non-truncated ghosts after
    reconcile compared to pack-0.92 formats.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    _serializer = xml5.serializer_v5
    supports_external_lookups = True

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('development1')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 5 (adds stacking support, requires bzr 1.6)"

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatKnitPack5RichRoot(RepositoryFormatPack):
    """A repository with rich roots and stacking.

    New in release 1.6.1.

    Supports stacking on other repositories, allowing data to be accessed
    without being stored locally.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = False # no subtrees
    _serializer = xml6.serializer_v6
    supports_external_lookups = True

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            '1.6.1-rich-root')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n"

    def get_format_description(self):
        return "Packs 5 rich-root (adds stacking support, requires bzr 1.6.1)"


class RepositoryFormatKnitPack5RichRootBroken(RepositoryFormatPack):
    """A repository with rich roots and external references.

    New in release 1.6.

    Supports external lookups, which results in non-truncated ghosts after
    reconcile compared to pack-0.92 formats.

    This format was deprecated because the serializer it uses accidentally
    supported subtrees, when the format was not intended to. This meant that
    someone could accidentally fetch from an incorrect repository.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = False # no subtrees
    _serializer = xml7.serializer_v7

    supports_external_lookups = True

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'development1-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n"

    def get_format_description(self):
        return ("Packs 5 rich-root (adds stacking support, requires bzr 1.6)"
                " (deprecated)")


class RepositoryFormatPackDevelopment0(RepositoryFormatPack):
    """A no-subtrees development repository.

    This format should be retained until the second release after bzr 1.0.

    No changes to the disk behaviour from pack-0.92.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    _serializer = xml5.serializer_v5

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('development0')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar development format 0 (needs bzr.dev from before 1.3)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format, currently the same as "
            "pack-0.92\n")

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatPackDevelopment0Subtree(RepositoryFormatPack):
    """A subtrees development repository.

    This format should be retained until the second release after bzr 1.0.

    No changes to the disk behaviour from pack-0.92-subtree.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = True
    _serializer = xml7.serializer_v7

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'development0-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)
        if not getattr(target_format, 'supports_tree_reference', False):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format)
            
    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format 0 with subtree support "
            "(needs bzr.dev from before 1.3)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format, currently the same as "
            "pack-0.92-subtree\n")


class RepositoryFormatPackDevelopment1(RepositoryFormatPackDevelopment0):
    """A no-subtrees development repository.

    This format should be retained until the second release after bzr 1.5.

    Supports external lookups, which results in non-truncated ghosts after
    reconcile compared to pack-0.92 formats.
    """

    supports_external_lookups = True

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('development1')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar development format 1 (needs bzr.dev from before 1.6)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format, currently the same as "
            "pack-0.92 with external reference support.\n")

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatPackDevelopment1Subtree(RepositoryFormatPackDevelopment0Subtree):
    """A subtrees development repository.

    This format should be retained until the second release after bzr 1.5.

    Supports external lookups, which results in non-truncated ghosts after
    reconcile compared to pack-0.92 formats.
    """

    supports_external_lookups = True

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'development1-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)
        if not getattr(target_format, 'supports_tree_reference', False):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format)
            
    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format 1 with subtree support "
            "(needs bzr.dev from before 1.6)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format, currently the same as "
            "pack-0.92-subtree with external reference support.\n")

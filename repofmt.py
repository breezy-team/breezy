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

from bzrlib import (
    debug,
    errors,
    knit,
    inventory,
    pack,
    repository,
    ui,
    )
from bzrlib.btree_index import (
    BTreeBuilder,
    BTreeGraphIndex,
    )
from bzrlib.index import GraphIndex, GraphIndexBuilder
from bzrlib.repository import InterPackRepo
from bzrlib.plugins.groupcompress_rabin.groupcompress import (
    _GCGraphIndex,
    GroupCompressVersionedFiles,
    )
from bzrlib.osutils import rand_chars
from bzrlib.repofmt.pack_repo import (
    Pack,
    NewPack,
    KnitPackRepository,
    RepositoryPackCollection,
    RepositoryFormatPackDevelopment2,
    RepositoryFormatPackDevelopment2Subtree,
    RepositoryFormatKnitPack1,
    RepositoryFormatKnitPack3,
    RepositoryFormatKnitPack4,
    Packer,
    ReconcilePacker,
    OptimisingPacker,
    )
try:
    from bzrlib.repofmt.pack_repo import (
    CHKInventoryRepository,
    RepositoryFormatPackDevelopment5,
    RepositoryFormatPackDevelopment5Hash16,
##    RepositoryFormatPackDevelopment5Hash16b,
##    RepositoryFormatPackDevelopment5Hash63,
##    RepositoryFormatPackDevelopment5Hash127a,
##    RepositoryFormatPackDevelopment5Hash127b,
    RepositoryFormatPackDevelopment5Hash255,
    )
    from bzrlib import chk_map
    chk_support = True
except ImportError:
    chk_support = False
from bzrlib import ui


def open_pack(self):
    return self._pack_collection.pack_factory(self._pack_collection,
        upload_suffix=self.suffix,
        file_mode=self._pack_collection.repo.bzrdir._get_file_mode())


Packer.open_pack = open_pack


class GCPack(NewPack):

    def __init__(self, pack_collection, upload_suffix='', file_mode=None):
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
        # replaced from bzr.dev to:
        # - change inventory reference list length to 1
        # - change texts reference lists to 1
        # TODO: patch this to be parameterised upstream
        
        # The relative locations of the packs are constrained, but all are
        # passed in because the caller has them, so as to avoid object churn.
        index_builder_class = pack_collection._index_builder_class
        if chk_support:
            # from brisbane-core
            if pack_collection.chk_index is not None:
                chk_index = index_builder_class(reference_lists=0)
            else:
                chk_index = None
            Pack.__init__(self,
                # Revisions: parents list, no text compression.
                index_builder_class(reference_lists=1),
                # Inventory: We want to map compression only, but currently the
                # knit code hasn't been updated enough to understand that, so we
                # have a regular 2-list index giving parents and compression
                # source.
                index_builder_class(reference_lists=1),
                # Texts: compression and per file graph, for all fileids - so two
                # reference lists and two elements in the key tuple.
                index_builder_class(reference_lists=1, key_elements=2),
                # Signatures: Just blobs to store, no compression, no parents
                # listing.
                index_builder_class(reference_lists=0),
                # CHK based storage - just blobs, no compression or parents.
                chk_index=chk_index
                )
        else:
            # from bzr.dev
            Pack.__init__(self,
                # Revisions: parents list, no text compression.
                index_builder_class(reference_lists=1),
                # Inventory: compressed, with graph for compatibility with other
                # existing bzrlib code.
                index_builder_class(reference_lists=1),
                # Texts: per file graph:
                index_builder_class(reference_lists=1, key_elements=2),
                # Signatures: Just blobs to store, no compression, no parents
                # listing.
                index_builder_class(reference_lists=0),
                )
        self._pack_collection = pack_collection
        # When we make readonly indices, we need this.
        self.index_class = pack_collection._index_class
        # where should the new pack be opened
        self.upload_transport = pack_collection._upload_transport
        # where are indices written out to
        self.index_transport = pack_collection._index_transport
        # where is the pack renamed to when it is finished?
        self.pack_transport = pack_collection._pack_transport
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
        # Overridden to add 'self.pack_factory()'
        # Do not permit preparation for writing if we're not in a 'write lock'.
        if not self.repo.is_write_locked():
            raise errors.NotWriteLocked(self)
        self._new_pack = self.pack_factory(self, upload_suffix='.pack',
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
        if chk_support and self.chk_index is not None:
            self.chk_index.add_writable_index(self._new_pack.chk_index,
                self._new_pack)
            self.repo.chk_bytes._index._add_callback = self.chk_index.add_callback

        self.repo.inventories._index._add_callback = self.inventory_index.add_callback
        self.repo.revisions._index._add_callback = self.revision_index.add_callback
        self.repo.signatures._index._add_callback = self.signature_index.add_callback
        self.repo.texts._index._add_callback = self.text_index.add_callback

    def _get_filtered_inv_stream(self, source_vf, keys):
        """Filter the texts of inventories, to find the chk pages."""
        id_roots = []
        p_id_roots = []
        id_roots_set = set()
        p_id_roots_set = set()
        def _filter_inv_stream(stream):
            for idx, record in enumerate(stream):
                ### child_pb.update('fetch inv', idx, len(inv_keys_to_fetch))
                bytes = record.get_bytes_as('fulltext')
                chk_inv = inventory.CHKInventory.deserialise(None, bytes, record.key)
                key = chk_inv.id_to_entry.key()
                if key not in id_roots_set:
                    id_roots.append(key)
                    id_roots_set.add(key)
                p_id_map = chk_inv.parent_id_basename_to_file_id
                if p_id_map is not None:
                    key = p_id_map.key()
                    if key not in p_id_roots_set:
                        p_id_roots_set.add(key)
                        p_id_roots.append(key)
                yield record
        stream = source_vf.get_record_stream(keys, 'gc-optimal', True)
        return _filter_inv_stream(stream), id_roots, p_id_roots

    def _get_chk_stream(self, source_vf, keys, id_roots, p_id_roots, pb=None):
        # We want to stream the keys from 'id_roots', and things they
        # reference, and then stream things from p_id_roots and things they
        # reference, and then any remaining keys that we didn't get to.

        # We also group referenced texts together, so if one root references a
        # text with prefix 'a', and another root references a node with prefix
        # 'a', we want to yield those nodes before we yield the nodes for 'b'
        # This keeps 'similar' nodes together

        # Note: We probably actually want multiple streams here, to help the
        #       client understand that the different levels won't compress well
        #       against eachother
        #       Test the difference between using one Group per level, and
        #       using 1 Group per prefix. (so '' (root) would get a group, then
        #       all the references to search-key 'a' would get a group, etc.)
        remaining_keys = set(keys)
        counter = [0]
        def _get_referenced_stream(root_keys):
            cur_keys = root_keys
            while cur_keys:
                keys_by_search_prefix = {}
                remaining_keys.difference_update(cur_keys)
                next_keys = set()
                stream = source_vf.get_record_stream(cur_keys, 'as-requested',
                                                     True)
                def next_stream():
                    for record in stream:
                        bytes = record.get_bytes_as('fulltext')
                        # We don't care about search_key_func for this code,
                        # because we only care about external references.
                        node = chk_map._deserialise(bytes, record.key,
                                                    search_key_func=None)
                        common_base = node._search_prefix
                        if isinstance(node, chk_map.InternalNode):
                            for prefix, value in node._items.iteritems():
                                assert isinstance(value, tuple)
                                if value not in next_keys:
                                    keys_by_search_prefix.setdefault(prefix,
                                        []).append(value)
                                    next_keys.add(value)
                        counter[0] += 1
                        if pb is not None:
                            pb.update('chk node', counter[0])
                        yield record
                yield next_stream()
                # Double check that we won't be emitting any keys twice
                next_keys = next_keys.intersection(remaining_keys)
                cur_keys = []
                for prefix in sorted(keys_by_search_prefix):
                    cur_keys.extend(keys_by_search_prefix[prefix])
        for stream in _get_referenced_stream(id_roots):
            yield stream
        for stream in _get_referenced_stream(p_id_roots):
            yield stream
        if remaining_keys:
            trace.note('There were %d keys in the chk index, which'
                       ' were not referenced from inventories',
                       len(remaining_keys))
            stream = source_vf.get_record_stream(remaining_keys, 'unordered',
                                                 True)
            yield stream

    def _execute_pack_operations(self, pack_operations, _packer_class=Packer,
                                 reload_func=None):
        """Execute a series of pack operations.

        :param pack_operations: A list of [revision_count, packs_to_combine].
        :param _packer_class: The class of packer to use (default: Packer).
        :return: None.
        """
        for revision_count, packs in pack_operations:
            # we may have no-ops from the setup logic
            if len(packs) == 0:
                continue
            # Create a new temp VersionedFile instance based on these packs,
            # and then just fetch everything into the target

            # XXX: Find a way to 'set_optimize' on the newly created pack
            #      indexes
            #    def open_pack(self):
            #       """Open a pack for the pack we are creating."""
            #       new_pack = super(OptimisingPacker, self).open_pack()
            #       # Turn on the optimization flags for all the index builders.
            #       new_pack.revision_index.set_optimize(for_size=True)
            #       new_pack.inventory_index.set_optimize(for_size=True)
            #       new_pack.text_index.set_optimize(for_size=True)
            #       new_pack.signature_index.set_optimize(for_size=True)
            #       return new_pack
            to_copy = [('revision_index', 'revisions'),
                       ('inventory_index', 'inventories'),
                       ('text_index', 'texts'),
                       ('signature_index', 'signatures'),
                      ]
            # TODO: This is a very non-optimal ordering for chk_bytes. The
            #       issue is that pages that are similar are not transmitted
            #       together. Perhaps get_record_stream('gc-optimal') should be
            #       taught about how to group chk pages?
            has_chk = False
            if getattr(self, 'chk_index', None) is not None:
                has_chk = True
                to_copy.insert(2, ('chk_index', 'chk_bytes'))

            # Shouldn't we start_write_group around this?
            if self._new_pack is not None:
                raise errors.BzrError('call to %s.pack() while another pack is'
                                      ' being written.'
                                      % (self.__class__.__name__,))
            new_pack = self.pack_factory(self, 'autopack',
                                         self.repo.bzrdir._get_file_mode())
            new_pack.set_write_cache_size(1024*1024)
            # TODO: A better alternative is to probably use Packer.open_pack(), and
            #       then create a GroupCompressVersionedFiles() around the
            #       target pack to insert into.
            pb = ui.ui_factory.nested_progress_bar()
            try:
                for idx, (index_name, vf_name) in enumerate(to_copy):
                    pb.update('repacking %s' % (vf_name,), idx + 1, len(to_copy))
                    keys = set()
                    new_index = getattr(new_pack, index_name)
                    new_index.set_optimize(for_size=True)
                    for pack in packs:
                        source_index = getattr(pack, index_name)
                        keys.update(e[1] for e in source_index.iter_all_entries())
                    trace.mutter('repacking %s with %d keys',
                                 vf_name, len(keys))
                    source_vf = getattr(self.repo, vf_name)
                    target_access = knit._DirectPackAccess({})
                    target_access.set_writer(new_pack._writer, new_index,
                                             new_pack.access_tuple())
                    target_vf = GroupCompressVersionedFiles(
                        _GCGraphIndex(new_index,
                                      add_callback=new_index.add_nodes,
                                      parents=source_vf._index._parents,
                                      is_locked=self.repo.is_locked),
                        access=target_access,
                        delta=source_vf._delta)
                    stream = None
                    child_pb = ui.ui_factory.nested_progress_bar()
                    try:
                        if has_chk:
                            if vf_name == 'inventories':
                                stream, id_roots, p_id_roots = self._get_filtered_inv_stream(
                                    source_vf, keys)
                            elif vf_name == 'chk_bytes':
                                for stream in self._get_chk_stream(source_vf, keys,
                                                    id_roots, p_id_roots,
                                                    pb=child_pb):
                                    target_vf.insert_record_stream(stream)
                                # No more to copy
                                stream = []
                        if stream is None:
                            def pb_stream():
                                substream = source_vf.get_record_stream(keys, 'gc-optimal', True)
                                for idx, record in enumerate(substream):
                                    child_pb.update(vf_name, idx, len(keys))
                                    yield record
                            stream = pb_stream()
                        target_vf.insert_record_stream(stream)
                    finally:
                        child_pb.finished()
                new_pack._check_references() # shouldn't be needed
            except:
                pb.finished()
                new_pack.abort()
                raise
            else:
                pb.finished()
                if not new_pack.data_inserted():
                    raise AssertionError('We copied from pack files,'
                                         ' but had no data copied')
                    # we need to abort somehow, because we don't want to remove
                    # the other packs
                new_pack.finish()
                self.allocate(new_pack)
            for pack in packs:
                self._remove_pack_from_memory(pack)
        # record the newly available packs and stop advertising the old
        # packs
        self._save_pack_names(clear_obsolete_packs=True)
        # Move the old packs out of the way now they are no longer referenced.
        for revision_count, packs in pack_operations:
            self._obsolete_packs(packs)



class GCRPackRepository(KnitPackRepository):
    """GC customisation of KnitPackRepository."""

    def __init__(self, _format, a_bzrdir, control_files, _commit_builder_class,
        _serializer):
        """Overridden to change pack collection class."""
        KnitPackRepository.__init__(self, _format, a_bzrdir, control_files,
            _commit_builder_class, _serializer)
        # and now replace everything it did :)
        index_transport = self._transport.clone('indices')
        if chk_support:
            self._pack_collection = GCRepositoryPackCollection(self,
                self._transport, index_transport,
                self._transport.clone('upload'),
                self._transport.clone('packs'),
                _format.index_builder_class,
                _format.index_class,
                use_chk_index=self._format.supports_chks,
                )
        else:
            self._pack_collection = GCRepositoryPackCollection(self,
                self._transport, index_transport,
                self._transport.clone('upload'),
                self._transport.clone('packs'),
                _format.index_builder_class,
                _format.index_class)
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
        if chk_support and _format.supports_chks:
            # No graph, no compression:- references from chks are between
            # different objects not temporal versions of the same; and without
            # some sort of temporal structure knit compression will just fail.
            self.chk_bytes = GroupCompressVersionedFiles(
                _GCGraphIndex(self._pack_collection.chk_index.combined_index,
                    add_callback=self._pack_collection.chk_index.add_callback,
                    parents=False, is_locked=self.is_locked),
                access=self._pack_collection.chk_index.data_access)
        else:
            self.chk_bytes = None
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
        # Note: We cannot unpack a delta that references a text we haven't seen yet.
        #       there are 2 options, work in fulltexts, or require topological
        #       sorting. Using fulltexts is more optimal for local operations,
        #       because the source can be smart about extracting multiple
        #       in-a-row (and sharing strings). Topological is better for
        #       remote, because we access less data.
        self._fetch_order = 'unordered'
        self._fetch_gc_optimal = True
        self._fetch_uses_deltas = False


if chk_support:
    class GCRCHKPackRepository(CHKInventoryRepository):
        """GC customisation of CHKInventoryRepository."""

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
                self._transport.clone('packs'),
                _format.index_builder_class,
                _format.index_class,
                use_chk_index=self._format.supports_chks,
                )
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
            assert _format.supports_chks
            # No parents, individual CHK pages don't have specific ancestry
            self.chk_bytes = GroupCompressVersionedFiles(
                _GCGraphIndex(self._pack_collection.chk_index.combined_index,
                    add_callback=self._pack_collection.chk_index.add_callback,
                    parents=False, is_locked=self.is_locked),
                access=self._pack_collection.chk_index.data_access)
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
            self._fetch_gc_optimal = True
            self._fetch_uses_deltas = False


class RepositoryFormatPackGCRabin(RepositoryFormatPackDevelopment2):
    """A B+Tree index using pack repository."""

    repository_class = GCRPackRepository

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format - btree+gcr "
            "(needs bzr.dev from 1.13)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format - btree+groupcompress "
            ", interoperates with pack-0.92\n")


if chk_support:
    class RepositoryFormatPackGCRabinCHK16(RepositoryFormatPackDevelopment5Hash16):
        """A hashed CHK+group compress pack repository."""

        repository_class = GCRCHKPackRepository

        def get_format_string(self):
            """See RepositoryFormat.get_format_string()."""
            return ('Bazaar development format - hash16chk+gcr'
                    ' (needs bzr.dev from 1.13)\n')

        def get_format_description(self):
            """See RepositoryFormat.get_format_description()."""
            return ("Development repository format - hash16chk+groupcompress")


    class RepositoryFormatPackGCRabinCHK255(RepositoryFormatPackDevelopment5Hash255):
        """A hashed CHK+group compress pack repository."""

        repository_class = GCRCHKPackRepository

        def get_format_string(self):
            """See RepositoryFormat.get_format_string()."""
            return ('Bazaar development format - hash255chk+gcr'
                    ' (needs bzr.dev from 1.13)\n')

        def get_format_description(self):
            """See RepositoryFormat.get_format_description()."""
            return ("Development repository format - hash255chk+groupcompress")


def pack_incompatible(source, target, orig_method=InterPackRepo.is_compatible):
    """Be incompatible with the regular fetch code."""
    formats = (RepositoryFormatPackGCRabin,)
    if chk_support:
        formats = formats + (RepositoryFormatPackGCRabinCHK16,
                             RepositoryFormatPackGCRabinCHK255)
    if isinstance(source._format, formats) or isinstance(target._format, formats):
        return False
    else:
        return orig_method(source, target)


InterPackRepo.is_compatible = staticmethod(pack_incompatible)

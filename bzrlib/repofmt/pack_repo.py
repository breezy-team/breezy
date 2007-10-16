# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
import math
import md5
import time

from bzrlib import (
        debug,
        pack,
        ui,
        )
from bzrlib.index import (
    GraphIndex,
    GraphIndexBuilder,
    InMemoryGraphIndex,
    CombinedGraphIndex,
    GraphIndexPrefixAdapter,
    )
from bzrlib.knit import KnitGraphIndex, _PackAccess, _KnitData
from bzrlib.osutils import rand_chars
from bzrlib.pack import ContainerWriter
from bzrlib.store import revision
""")
from bzrlib import (
    bzrdir,
    deprecated_graph,
    errors,
    knit,
    lockable_files,
    lockdir,
    osutils,
    transactions,
    xml5,
    xml7,
    )

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.repofmt.knitrepo import KnitRepository
from bzrlib.repository import (
    CommitBuilder,
    MetaDirRepository,
    MetaDirRepositoryFormat,
    RootCommitBuilder,
    )
import bzrlib.revision as _mod_revision
from bzrlib.store.revision.knit import KnitRevisionStore
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.trace import mutter, note, warning


class PackCommitBuilder(CommitBuilder):
    """A subclass of CommitBuilder to add texts with pack semantics.
    
    Specifically this uses one knit object rather than one knit object per
    added text, reducing memory and object pressure.
    """

    def _add_text_to_weave(self, file_id, new_lines, parents, nostore_sha):
        return self.repository._packs._add_text_to_weave(file_id,
            self._new_revision_id, new_lines, parents, nostore_sha,
            self.random_revid)


class PackRootCommitBuilder(RootCommitBuilder):
    """A subclass of RootCommitBuilder to add texts with pack semantics.
    
    Specifically this uses one knit object rather than one knit object per
    added text, reducing memory and object pressure.
    """

    def _add_text_to_weave(self, file_id, new_lines, parents, nostore_sha):
        return self.repository._packs._add_text_to_weave(file_id,
            self._new_revision_id, new_lines, parents, nostore_sha,
            self.random_revid)


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
        :param revision_index: A GraphIndex for determining what signatures are
            present in the Pack and accessing the locations of their texts.
        """
        self.revision_index = revision_index
        self.inventory_index = inventory_index
        self.text_index = text_index
        self.signature_index = signature_index

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


class ExistingPack(Pack):
    """An in memory proxy for an exisiting .pack and its disk indices."""

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
        assert None not in (revision_index, inventory_index, text_index,
            signature_index, name, pack_transport)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<bzrlib.repofmt.pack_repo.Pack object at 0x%x, %s, %s" % (
            id(self), self.transport, self.name)


class NewPack(Pack):
    """An in memory proxy for a pack which is being created."""

    # A map of index 'type' to the file extension and position in the
    # index_sizes array.
    indices = {
        'revision':('.rix', 0),
        'inventory':('.iix', 1),
        'text':('.tix', 2),
        'signature':('.six', 3),
        }

    def __init__(self, upload_transport, index_transport, pack_transport,
        upload_suffix=''):
        """Create a NewPack instance.

        :param upload_transport: A writable transport for the pack to be
            incrementally uploaded to.
        :param index_transport: A writable transport for the pack's indices to
            be written to when the pack is finished.
        :param pack_transport: A writable transport for the pack to be renamed
            to when the upload is complete.
        :param upload_suffix: An optional suffix to be given to any temporary
            files created during the pack creation. e.g '.autopack'
        """
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
        # tracks the content written to the .pack file.
        self._hash = md5.new()
        # a four-tuple with the length in bytes of the indices, once the pack
        # is finalised. (rev, inv, text, sigs)
        self.index_sizes = None
        # the temporary pack file name.
        self.random_name = rand_chars(20) + upload_suffix
        # when was this pack started ?
        self.start_time = time.time()

    def data_inserted(self):
        """True if data has been added to this pack."""
        return 0 != sum((self.get_revision_count(),
            self.inventory_index.key_count(),
            self.text_index.key_count(),
            self.signature_index.key_count(),
            ))

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
        self.name = self._hash.hexdigest()
        self.index_sizes = [None, None, None, None]
        self._write_index('revision', self.revision_index, 'revision')
        self._write_index('inventory', self.inventory_index, 'inventory')
        self._write_index('text', self.text_index, 'file texts')
        self._write_index('signature', self.signature_index,
            'revision signatures')


    def make_index(self, index_type):
        """Construct a GraphIndex object for this packs index 'index_type'."""
        setattr(self, index_type + '_index',
            GraphIndex(self.index_transport,
                self.index_name(index_type, self.name),
                self.index_sizes[self.index_offset(index_type)]))

    def index_name(self, index_type, name):
        """Get the disk name of an index type for pack name 'name'."""
        return name + NewPack.indices[index_type][0]

    def index_offset(self, index_type):
        """Get the position in a index_size array for a given index type."""
        return NewPack.indices[index_type][1]

    def _write_index(self, index_type, index, label):
        """Write out an index.

        :param index: The index object to serialise.
        :param index_offset: Where in self.index_sizes to remember this.
        :param name_getter: What to use to get the name of the index on disk.
        :param label: What label to give the index e.g. 'revision'.
        """
        index_name = self.index_name(index_type, self.name)
        self.index_sizes[self.index_offset(index_type)] = \
            self.index_transport.put_file(index_name, index.finish())
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: wrote %s index: %s%s t+%6.3fs',
                time.ctime(), label, self.upload_transport.base,
                self.random_name, time.time() - self.start_time)
        # As we have no current protection against erroneous additional
        # insertions, load the index from disk on further use. We should alter
        # the index layer to make it's finish() error if add_node is
        # subsequently used. RBC
        self.make_index(index_type)


class RepositoryPackCollection(object):
    """Management of packs within a repository."""

    def __init__(self, repo, transport, index_transport, upload_transport,
                 pack_transport):
        """Create a new RepositoryPackCollection.

        :param transport: Addresses the repository base directory 
            (typically .bzr/repository/).
        :param index_transport: Addresses the directory containing indexes.
        :param upload_transport: Addresses the directory into which packs are written
            while they're being created.
        :param pack_transport: Addresses the directory of existing complete packs.
        """
        self.repo = repo
        self.transport = transport
        self._index_transport = index_transport
        self._upload_transport = upload_transport
        self._pack_transport = pack_transport
        self._suffix_offsets = {'.rix':0, '.iix':1, '.tix':2, '.six':3}
        self.packs = []
        # name:Pack mapping
        self._packs = {}
        # the previous pack-names content
        self._packs_at_load = None
        # when a pack is being created by this object, the state of that pack.
        self._new_pack = None

    def add_pack_to_memory(self, pack):
        """Make a Pack object available to the repository to satisfy queries.
        
        :param pack: A Pack object.
        """
        self.packs.append(pack)
        assert pack.name not in self._packs
        self._packs[pack.name] = pack
        if self.repo._revision_all_indices is None:
            # to make this function more useful, perhaps we should make an
            # all_indices object in future?
            pass
        else:
            self.repo._revision_pack_map[pack.revision_index] = (
                pack.pack_transport, pack.name + '.pack')
            self.repo._revision_all_indices.insert_index(0, pack.revision_index)
        if self.repo._inv_all_indices is not None:
            # inv 'knit' has been used : update it.
            self.repo._inv_all_indices.insert_index(0,
                pack.inventory_index)
            self.repo._inv_pack_map[pack.inventory_index] = pack.pack_transport, pack.name + '.pack'
        if self.repo._text_all_indices is not None:
            # text 'knits' have been used : update it.
            self.repo._text_all_indices.insert_index(0,
                pack.text_index)
        if self.repo._signature_all_indices is not None:
            # sigatures 'knit' accessed : update it.
            self.repo._signature_all_indices.insert_index(0,
                pack.signature_index)
        
    def _add_text_to_weave(self, file_id, revision_id, new_lines, parents,
        nostore_sha, random_revid):
        file_id_index = GraphIndexPrefixAdapter(
            self.repo._text_all_indices,
            (file_id, ), 1,
            add_nodes_callback=self._new_pack.text_index.add_nodes)
        self.repo._text_knit._index._graph_index = file_id_index
        self.repo._text_knit._index._add_callback = file_id_index.add_nodes
        return self.repo._text_knit.add_lines_with_ghosts(
            revision_id, parents, new_lines, nostore_sha=nostore_sha,
            random_id=random_revid, check_content=False)[0:2]

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
        if self.repo._revision_all_indices is None:
            # trigger creation of the all revision index.
            self.repo._revision_store.get_revision_file(self.repo.get_transaction())
        total_revisions = self.repo._revision_all_indices.key_count()
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

    def refresh_revision_signature_indices(self):
        """Refresh the mappings for revisions."""
        index_map, index_list = self._make_index_map('.rix')
        if self.repo._revision_all_indices is None:
            # create a pack map for the autopack code - XXX finish
            # making a clear managed list of packs, indices and use
            # that in these mapping classes
            self.repo._revision_pack_map = index_map
        else:
            # refresh the revision pack map dict without replacing the instance.
            self.repo._revision_pack_map.clear()
            self.repo._revision_pack_map.update(index_map)
            # revisions 'knit' accessed : update it.
            # XXX: API break - clearly a 'replace' method would be good?
            self.repo._revision_all_indices._indices[:] = index_list
            # reset the knit access writer
            self.repo._revision_knit_access.set_writer(None, None, (None, None))

        index_map, index_list = self._make_index_map('.six')
        if self.repo._signature_all_indices is not None:
            # signature 'knit' accessed : update it.
            # XXX: API break - clearly a 'replace' method would be good?
            self.repo._signature_all_indices._indices[:] = index_list
            # reset the knit access writer
            self.repo._signature_knit_access.set_writer(None, None, (None, None))

    def refresh_inventory_index(self):
        """Refresh the inventory access index mappings."""
        index_map, index_list = self._make_index_map('.iix')
        if self.repo._inv_all_indices is not None:
            # refresh the pack map dict without replacing the instance.
            self.repo._inv_pack_map.clear()
            self.repo._inv_pack_map.update(index_map)
            # invs 'knit' accessed : update it.
            # XXX: API break - clearly a 'replace' method would be good?
            self.repo._inv_all_indices._indices[:] = index_list
            # reset the knit access writer
            self.repo._inv_knit_access.set_writer(None, None, (None, None))
        else:
            # inventory knit not used, ensure the pack map is regenerated at
            # next use.
            self.repo._inv_pack_map = None

    def refresh_text_index(self):
        """Refresh the text index mappings."""
        index_map, index_list = self._make_index_map('.tix')
        self.repo.weave_store._setup_knit(False)
        if self.repo._text_all_indices is not None:
            # refresh the pack map dict without replacing the instance.
            self.repo._text_pack_map.clear()
            self.repo._text_pack_map.update(index_map)
            # invs 'knit' accessed : update it.
            # XXX: API break - clearly a 'replace' method would be good?
            self.repo._text_all_indices._indices[:] = index_list

    def create_pack_from_packs(self, packs, suffix, revision_ids=None):
        """Create a new pack by reading data from other packs.

        This does little more than a bulk copy of data. One key difference
        is that data with the same item key across multiple packs is elided
        from the output. The new pack is written into the current pack store
        along with its indices, and the name added to the pack names. The 
        source packs are not altered and are not required to be in the current
        pack collection.

        :param packs: An iterable of Packs to combine.
        :param revision_ids: Either None, to copy all data, or a list
            of revision_ids to limit the copied data to the data they
            introduced.
        :return: A Pack object, or None if nothing was copied.
        """
        # open a pack - using the same name as the last temporary file
        # - which has already been flushed, so its safe.
        # XXX: - duplicate code warning with start_write_group; fix before
        #      considering 'done'.
        if getattr(self.repo, '_open_pack_tuple', None) is not None:
            raise errors.BzrError('call to create_pack_from_packs while '
                'another pack is being written.')
        if self._new_pack is not None:
            raise errors.BzrError('call to create_pack_from_packs while '
                'another pack is being written.')
        if revision_ids is not None and len(revision_ids) == 0:
            # silly fetch request.
            return None
        new_pack = NewPack(self._upload_transport, self._index_transport,
            self._pack_transport, upload_suffix=suffix)
        random_name = new_pack.random_name
        if 'fetch' in debug.debug_flags:
            plain_pack_list = ['%s%s' % (a_pack.pack_transport.base, a_pack.name)
                for a_pack in packs]
            if revision_ids is not None:
                rev_count = len(revision_ids)
            else:
                rev_count = 'all'
            mutter('%s: create_pack: creating pack from source packs: '
                '%s%s %s revisions wanted %s t=0',
                time.ctime(), self._upload_transport.base, random_name,
                plain_pack_list, rev_count)
        write_stream = self._upload_transport.open_write_stream(random_name)
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: pack stream open: %s%s t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                time.time() - new_pack.start_time)
        buffer = []
        def write_data(bytes, update=new_pack._hash.update, write=write_stream.write):
            buffer.append(bytes)
            if len(buffer) == 640:
                bytes = ''.join(buffer)
                write(bytes)
                update(bytes)
                del buffer[:]
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        # select revisions
        if revision_ids:
            revision_keys = [(revision_id,) for revision_id in revision_ids]
        else:
            revision_keys = None

        # select revision keys
        revision_index_map = self._packs_list_to_pack_map_and_index_list(
            packs, 'revision_index')[0]
        revision_nodes = self._index_contents(revision_index_map, revision_keys)
        # copy revision keys and adjust values
        list(self._copy_nodes_graph(revision_nodes, revision_index_map, writer,
            new_pack.revision_index))
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: revisions copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                new_pack.revision_index.key_count(),
                time.time() - new_pack.start_time)
        # select inventory keys
        inv_keys = revision_keys # currently the same keyspace, and note that
        # querying for keys here could introduce a bug where an inventory item
        # is missed, so do not change it to query separately without cross
        # checking like the text key check below.
        inventory_index_map = self._packs_list_to_pack_map_and_index_list(
            packs, 'inventory_index')[0]
        inv_nodes = self._index_contents(inventory_index_map, inv_keys)
        # copy inventory keys and adjust values
        # XXX: Should be a helper function to allow different inv representation
        # at this point.
        inv_lines = self._copy_nodes_graph(inv_nodes, inventory_index_map,
            writer, new_pack.inventory_index, output_lines=True)
        if revision_ids:
            fileid_revisions = self.repo._find_file_ids_from_xml_inventory_lines(
                inv_lines, revision_ids)
            text_filter = []
            for fileid, file_revids in fileid_revisions.iteritems():
                text_filter.extend(
                    [(fileid, file_revid) for file_revid in file_revids])
        else:
            # eat the iterator to cause it to execute.
            list(inv_lines)
            text_filter = None
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: inventories copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                new_pack.inventory_index.key_count(),
                time.time() - new_pack.start_time)
        # select text keys
        text_index_map = self._packs_list_to_pack_map_and_index_list(
            packs, 'text_index')[0]
        text_nodes = self._index_contents(text_index_map, text_filter)
        if text_filter is not None:
            # We could return the keys copied as part of the return value from
            # _copy_nodes_graph but this doesn't work all that well with the
            # need to get line output too, so we check separately, and as we're
            # going to buffer everything anyway, we check beforehand, which
            # saves reading knit data over the wire when we know there are
            # mising records.
            text_nodes = set(text_nodes)
            present_text_keys = set(_node[1] for _node in text_nodes)
            missing_text_keys = set(text_filter) - present_text_keys
            if missing_text_keys:
                # TODO: raise a specific error that can handle many missing
                # keys.
                a_missing_key = missing_text_keys.pop()
                raise errors.RevisionNotPresent(a_missing_key[1],
                    a_missing_key[0])
        # copy text keys and adjust values
        list(self._copy_nodes_graph(text_nodes, text_index_map, writer,
            new_pack.text_index))
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: file texts copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                new_pack.text_index.key_count(),
                time.time() - new_pack.start_time)
        # select signature keys
        signature_filter = revision_keys # same keyspace
        signature_index_map = self._packs_list_to_pack_map_and_index_list(
            packs, 'signature_index')[0]
        signature_nodes = self._index_contents(signature_index_map,
            signature_filter)
        # copy signature keys and adjust values
        self._copy_nodes(signature_nodes, signature_index_map, writer, new_pack.signature_index)
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: revision signatures copied: %s%s %d items t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                new_pack.signature_index.key_count(),
                time.time() - new_pack.start_time)
        # finish the pack
        writer.end()
        if len(buffer):
            bytes = ''.join(buffer)
            write_stream.write(bytes)
            new_pack._hash.update(bytes)
        if not new_pack.data_inserted():
            # nothing was copied, discard the new pack.
            self._upload_transport.delete(random_name)
            return None
        # write indices
        new_pack.finish()
        # add to name
        self.allocate(new_pack, new_pack.name, new_pack.index_sizes[0],
            new_pack.index_sizes[1], new_pack.index_sizes[2],
            new_pack.index_sizes[3])
        # rename into place. XXX: should rename each index too rather than just
        # uploading blind under the chosen name.
        write_stream.close()
        self._upload_transport.rename(random_name, '../packs/' + new_pack.name + '.pack')
        result = new_pack
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: pack renamed into place: %s%s->%s%s t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                result.pack_transport, result.name,
                time.time() - new_pack.start_time)
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: finished: %s%s t+%6.3fs',
                time.ctime(), self._upload_transport.base, random_name,
                time.time() - new_pack.start_time)
        return result

    def _execute_pack_operations(self, pack_operations):
        """Execute a series of pack operations.

        :param pack_operations: A list of [revision_count, packs_to_combine].
        :return: None.
        """
        for revision_count, packs in pack_operations:
            # we may have no-ops from the setup logic
            if len(packs) == 0:
                continue
            # have a progress bar?
            self.create_pack_from_packs(packs, '.autopack')
            for pack in packs:
                self._remove_pack_by_name(pack.name)
        # record the newly available packs and stop advertising the old
        # packs
        self._save_pack_names()
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
        try:
            total_packs = len(self._names)
            if total_packs < 2:
                return
            if self.repo._revision_all_indices is None:
                # trigger creation of the all revision index.
                self.repo._revision_store.get_revision_file(self.repo.get_transaction())
            total_revisions = self.repo._revision_all_indices.key_count()
            # XXX: the following may want to be a class, to pack with a given
            # policy.
            mutter('Packing repository %s, which has %d pack files, '
                'containing %d revisions into 1 packs.', self, total_packs,
                total_revisions)
            # determine which packs need changing
            pack_distribution = [1]
            pack_operations = [[0, []]]
            for pack in self.all_packs():
                revision_count = pack.get_revision_count()
                pack_operations[-1][0] += revision_count
                pack_operations[-1][1].append(pack)
            self._execute_pack_operations(pack_operations)
        finally:
            if not self.repo.is_in_write_group():
                self.reset()

    def plan_autopack_combinations(self, existing_packs, pack_distribution):
        """Plan a pack operation.

        :param existing_packs: The packs to pack. (A list of (revcount, Pack)
            tuples).
        :parma pack_distribution: A list with the number of revisions desired
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

    def _copy_nodes(self, nodes, index_map, writer, write_index):
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
                pos, size = writer.add_bytes_record(raw_data, names)
                write_index.add_node(key, eol_flag + "%d %d" % (pos, size))

    def _copy_nodes_graph(self, nodes, index_map, writer, write_index,
        output_lines=False):
        """Copy knit nodes between packs.

        :param output_lines: Return lines present in the copied data as
            an iterator.
        """
        # for record verification
        knit_data = _KnitData(None)
        # for line extraction when requested (inventories only)
        if output_lines:
            factory = knit.KnitPlainFactory()
        # plan a readv on each source pack:
        # group by pack
        nodes = sorted(nodes)
        # how to map this into knit.py - or knit.py into this?
        # we don't want the typical knit logic, we want grouping by pack
        # at this point - perhaps a helper library for the following code 
        # duplication points?
        request_groups = {}
        for index, key, value, references in nodes:
            if index not in request_groups:
                request_groups[index] = []
            request_groups[index].append((key, value, references))
        for index, items in request_groups.iteritems():
            pack_readv_requests = []
            for key, value, references in items:
                # ---- KnitGraphIndex.get_position
                bits = value[1:].split(' ')
                offset, length = int(bits[0]), int(bits[1])
                pack_readv_requests.append((offset, length, (key, value[0], references)))
            # linear scan up the pack
            pack_readv_requests.sort()
            # copy the data
            transport, path = index_map[index]
            reader = pack.make_readv_reader(transport, path,
                [offset[0:2] for offset in pack_readv_requests])
            for (names, read_func), (_1, _2, (key, eol_flag, references)) in \
                izip(reader.iter_records(), pack_readv_requests):
                raw_data = read_func(None)
                if output_lines:
                    # read the entire thing
                    content, _ = knit_data._parse_record(key[-1], raw_data)
                    if len(references[-1]) == 0:
                        line_iterator = factory.get_fulltext_content(content)
                    else:
                        line_iterator = factory.get_linedelta_content(content)
                    for line in line_iterator:
                        yield line
                else:
                    # check the header only
                    df, _ = knit_data._parse_record_header(key[-1], raw_data)
                    df.close()
                pos, size = writer.add_bytes_record(raw_data, names)
                write_index.add_node(key, eol_flag + "%d %d" % (pos, size), references)

    def ensure_loaded(self):
        if self._names is None:
            self._names = {}
            self._packs_at_load = set()
            for index, key, value in self._iter_disk_pack_index():
                name = key[0]
                sizes = [int(digits) for digits in value.split(' ')]
                self._names[name] = sizes
                self._packs_at_load.add((key, value))

    def get_pack_by_name(self, name):
        """Get a Pack object by name.

        :param name: The name of the pack - e.g. '123456'
        :return: A Pack object.
        """
        try:
            return self._packs[name]
        except KeyError:
            rev_index = self._make_index(name, '.rix')
            inv_index = self._make_index(name, '.iix')
            txt_index = self._make_index(name, '.tix')
            sig_index = self._make_index(name, '.six')
            result = ExistingPack(self._pack_transport, name, rev_index,
                inv_index, txt_index, sig_index)
            self.add_pack_to_memory(result)
            return result

    def allocate(self, a_new_pack, name, revision_index_length, inventory_index_length,
        text_index_length, signature_index_length):
        """Allocate name in the list of packs.

        :param name: The basename - e.g. the md5 hash hexdigest.
        :param revision_index_length: The length of the revision index in
            bytes.
        :param inventory_index_length: The length of the inventory index in
            bytes.
        :param text_index_length: The length of the text index in bytes.
        :param signature_index_length: The length of the signature index in
            bytes.
        """
        self.ensure_loaded()
        if name in self._names:
            raise errors.DuplicateKey(name)
        self._names[name] = (revision_index_length, inventory_index_length,
            text_index_length, signature_index_length)

    def _iter_disk_pack_index(self):
        """Iterate over the contents of the pack-names index.
        
        This is used when loading the list from disk, and before writing to
        detect updates from others during our write operation.
        :return: An iterator of the index contents.
        """
        return GraphIndex(self.transport, 'pack-names', None
                ).iter_all_entries()

    def _make_index_map(self, suffix):
        """Return information on existing indexes.

        :param suffix: Index suffix added to pack name.

        :returns: (pack_map, indices) where indices is a list of GraphIndex 
        objects, and pack_map is a mapping from those objects to the 
        pack tuple they describe.
        """
        # TODO: stop using this; it creates new indices unnecessarily.
        self.ensure_loaded()
        details = []
        for name in self.names():
            # TODO: maybe this should expose size to us  to allow
            # sorting of the indices for better performance ?
            details.append(self._pack_tuple(name))
        return self._make_index_to_pack_map(details, suffix)

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
            # TODO: Probably needs to know all possible indexes for this pack
            # - or maybe list the directory and move all indexes matching this
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

    def _remove_pack_by_name(self, name):
        # strip .pack
        self._names.pop(name)

    def reset(self):
        """Clear all cached data."""
        # cached revision data
        self.repo._revision_knit = None
        self.repo._revision_all_indices = None
        self.repo._revision_knit_access = None
        # cached signature data
        self.repo._signature_knit = None
        self.repo._signature_all_indices = None
        self.repo._signature_knit_access = None
        # no access object.
        self.repo._text_knit_access = None
        # no write-knit
        self.repo._text_knit = None
        # remove all constructed text data indices
        self.repo._text_all_indices = None
        # and the pack map
        self.repo._text_pack_map = None
        # remove all constructed inv data indices
        self.repo._inv_all_indices = None
        # remove the knit access object
        self.repo._inv_knit_access = None
        self.repo._inv_pack_map = None
        # remove the open pack
        self._new_pack = None
        # information about packs.
        self._names = None
        self.packs = []
        self._packs = {}
        self._packs_at_load = None

    def _make_index_to_pack_map(self, pack_details, index_suffix):
        """Given a list (transport,name), return a map of (index)->(transport, name)."""
        # the simplest thing for now is to create new index objects.
        # this should really reuse the existing index objects for these 
        # packs - this means making the way they are managed in the repo be 
        # more sane.
        indices = []
        pack_map = {}
        self.ensure_loaded()
        for transport, name in pack_details:
            index_name = name[:-5] + index_suffix
            new_index = self._make_index(name[:-5], index_suffix)
            indices.append(new_index)
            pack_map[new_index] = (transport, name)
        return pack_map, indices

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

    def release_names(self):
        """Release the mutex around the pack-names index."""
        self.repo.control_files.unlock()

    def _save_pack_names(self):
        """Save the list of packs.

        This will take out the mutex around the pack names list for the
        duration of the method call. If concurrent updates have been made, a
        three-way merge between the current list and the current in memory list
        is performed.
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
            for key, value in disk_nodes:
                builder.add_node(key, value)
            self.transport.put_file('pack-names', builder.finish())
        finally:
            self.release_names()

    def setup(self):
        # Do not permit preparation for writing if we're not in a 'write lock'.
        if not self.repo.is_write_locked():
            raise errors.NotWriteLocked(self)
        self._new_pack = NewPack(self._upload_transport, self._index_transport,
            self._pack_transport, upload_suffix='.pack')

    def _start_write_group(self):
        self.setup()
        random_name = self._new_pack.random_name
        self.repo._open_pack_tuple = (self._upload_transport, random_name)
        write_stream = self._upload_transport.open_write_stream(random_name)
        self._write_stream = write_stream
        def write_data(bytes, write=write_stream.write,
                       update=self._new_pack._hash.update):
            write(bytes)
            update(bytes)
        self._open_pack_writer = pack.ContainerWriter(write_data)
        self._open_pack_writer.begin()
        self.repo._revision_store.setup()
        self.repo.weave_store.setup()
        self.repo._inv_thunk.setup()

    def _abort_write_group(self):
        # FIXME: just drop the transient index.
        # forget what names there are
        self.reset()

    def _commit_write_group(self):
        if self._new_pack.data_inserted():
            self._open_pack_writer.end()
            self._new_pack.finish()
            self._write_stream.close()
            self._upload_transport.rename(self.repo._open_pack_tuple[1],
                '../packs/' + self._new_pack.name + '.pack')
            # If this fails, its a hash collision. We should:
            # - determine if its a collision or
            # - the same content or
            # - the existing name is not the actual hash - e.g.
            #   its a deliberate attack or data corruption has
            #   occuring during the write of that file.
            self.allocate(self._new_pack, self._new_pack.name, self._new_pack.index_sizes[0],
                self._new_pack.index_sizes[1], self._new_pack.index_sizes[2],
                self._new_pack.index_sizes[3])
            self.repo._open_pack_tuple = None
            self._new_pack = None
            if not self.autopack():
                self._save_pack_names()
            # now setup the maps we need to access data again.
            self.refresh_text_index()
            self.refresh_inventory_index()
            self.refresh_revision_signature_indices()
        else:
            # remove the pending upload
            self._upload_transport.delete(self.repo._open_pack_tuple[1])
        # forget what names there are - should just refresh and deal with the
        # delta.
        self.reset()
        self._write_stream = None


class GraphKnitRevisionStore(KnitRevisionStore):
    """An object to adapt access from RevisionStore's to use GraphKnits.

    This should not live through to production: by production time we should
    have fully integrated the new indexing and have new data for the
    repository classes; also we may choose not to do a Knit1 compatible
    new repository, just a Knit3 one. If neither of these happen, this 
    should definately be cleaned up before merging.

    This class works by replacing the original RevisionStore.
    We need to do this because the GraphKnitRevisionStore is less
    isolated in its layering - it uses services from the repo.
    """

    def __init__(self, repo, transport, revisionstore):
        """Create a GraphKnitRevisionStore on repo with revisionstore.

        This will store its state in the Repository, use the
        indices FileNames to provide a KnitGraphIndex,
        and at the end of transactions write new indices.
        """
        KnitRevisionStore.__init__(self, revisionstore.versioned_file_store)
        self.repo = repo
        self._serializer = revisionstore._serializer
        self.transport = transport

    def get_revision_file(self, transaction):
        """Get the revision versioned file object."""
        if getattr(self.repo, '_revision_knit', None) is not None:
            return self.repo._revision_knit
        pack_map, indices = self.repo._packs._make_index_map('.rix')
        if self.repo._packs._new_pack is not None:
            # allow writing: queue writes to a new index
            indices.insert(0, self.repo._packs._new_pack.revision_index)
            pack_map[self.repo._packs._new_pack.revision_index] = self.repo._open_pack_tuple
            writer = self.repo._packs._open_pack_writer, self.repo._packs._new_pack.revision_index
            add_callback = self.repo._packs._new_pack.revision_index.add_nodes
        else:
            writer = None
            add_callback = None # no data-adding permitted.
        self.repo._revision_all_indices = CombinedGraphIndex(indices)
        knit_index = KnitGraphIndex(self.repo._revision_all_indices,
            add_callback=add_callback)
        knit_access = _PackAccess(pack_map, writer)
        self.repo._revision_pack_map = pack_map
        self.repo._revision_knit_access = knit_access
        self.repo._revision_knit = knit.KnitVersionedFile(
            'revisions', self.transport.clone('..'),
            self.repo.control_files._file_mode,
            create=False, access_mode=self.repo._access_mode(),
            index=knit_index, delta=False, factory=knit.KnitPlainFactory(),
            access_method=knit_access)
        return self.repo._revision_knit

    def get_signature_file(self, transaction):
        """Get the signature versioned file object."""
        if getattr(self.repo, '_signature_knit', None) is not None:
            return self.repo._signature_knit
        pack_map, indices = self.repo._packs._make_index_map('.six')
        if self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.insert(0, self.repo._packs._new_pack.signature_index)
            pack_map[self.repo._packs._new_pack.signature_index] = self.repo._open_pack_tuple
            writer = self.repo._packs._open_pack_writer, self.repo._packs._new_pack.signature_index
            add_callback = self.repo._packs._new_pack.signature_index.add_nodes
        else:
            writer = None
            add_callback = None # no data-adding permitted.
        self.repo._signature_all_indices = CombinedGraphIndex(indices)
        knit_index = KnitGraphIndex(self.repo._signature_all_indices,
            add_callback=add_callback, parents=False)
        knit_access = _PackAccess(pack_map, writer)
        self.repo._signature_knit_access = knit_access
        self.repo._signature_knit = knit.KnitVersionedFile(
            'signatures', self.transport.clone('..'),
            self.repo.control_files._file_mode,
            create=False, access_mode=self.repo._access_mode(),
            index=knit_index, delta=False, factory=knit.KnitPlainFactory(),
            access_method=knit_access)
        return self.repo._signature_knit

    def setup(self):
        # if knit indices have been handed out, add a mutable
        # index to them
        if self.repo._revision_knit is not None:
            self.repo._revision_all_indices.insert_index(0, self.repo._packs._new_pack.revision_index)
            self.repo._revision_knit._index._add_callback = self.repo._packs._new_pack.revision_index.add_nodes
            self.repo._revision_knit_access.set_writer(
                self.repo._packs._open_pack_writer,
                self.repo._packs._new_pack.revision_index, self.repo._open_pack_tuple)
        if self.repo._signature_knit is not None:
            self.repo._signature_all_indices.insert_index(0, self.repo._packs._new_pack.signature_index)
            self.repo._signature_knit._index._add_callback = self.repo._packs._new_pack.signature_index.add_nodes
            self.repo._signature_knit_access.set_writer(
                self.repo._packs._open_pack_writer,
                self.repo._packs._new_pack.signature_index, self.repo._open_pack_tuple)


class GraphKnitTextStore(VersionedFileStore):
    """An object to adapt access from VersionedFileStore's to use GraphKnits.

    This should not live through to production: by production time we should
    have fully integrated the new indexing and have new data for the
    repository classes; also we may choose not to do a Knit1 compatible
    new repository, just a Knit3 one. If neither of these happen, this 
    should definately be cleaned up before merging.

    This class works by replacing the original VersionedFileStore.
    We need to do this because the GraphKnitRevisionStore is less
    isolated in its layering - it uses services from the repo and shares them
    with all the data written in a single write group.
    """

    def __init__(self, repo, transport, weavestore):
        """Create a GraphKnitTextStore on repo with weavestore.

        This will store its state in the Repository, use the
        indices FileNames to provide a KnitGraphIndex,
        and at the end of transactions write new indices.
        """
        # don't call base class constructor - its not suitable.
        # no transient data stored in the transaction
        # cache.
        self._precious = False
        self.repo = repo
        self.transport = transport
        self.weavestore = weavestore
        # XXX for check() which isn't updated yet
        self._transport = weavestore._transport

    def _ensure_all_index(self, for_write=None):
        """Create the combined index for all texts."""
        if getattr(self.repo, '_text_all_indices', None) is not None:
            return
        pack_map, indices = self.repo._packs._make_index_map('.tix')
        self.repo._text_pack_map = pack_map
        if for_write or self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.insert(0, self.repo._packs._new_pack.text_index)
        self._setup_knit(self.repo.is_in_write_group())
        self.repo._text_all_indices = CombinedGraphIndex(indices)

    def get_weave_or_empty(self, file_id, transaction, force_write=False):
        """Get a 'Knit' backed by the .tix indices.

        The transaction parameter is ignored.
        """
        self._ensure_all_index()
        if force_write or self.repo.is_in_write_group():
            add_callback = self.repo._packs._new_pack.text_index.add_nodes
            self.repo._text_pack_map[self.repo._packs._new_pack.text_index] = self.repo._open_pack_tuple
        else:
            add_callback = None # no data-adding permitted.

        file_id_index = GraphIndexPrefixAdapter(self.repo._text_all_indices,
            (file_id, ), 1, add_nodes_callback=add_callback)
        knit_index = KnitGraphIndex(file_id_index,
            add_callback=file_id_index.add_nodes,
            deltas=True, parents=True)
        return knit.KnitVersionedFile('text:' + file_id,
            self.transport.clone('..'),
            None,
            index=knit_index,
            access_method=self.repo._text_knit_access,
            factory=knit.KnitPlainFactory())

    get_weave = get_weave_or_empty

    def __iter__(self):
        """Generate a list of the fileids inserted, for use by check."""
        self._ensure_all_index()
        ids = set()
        for index, key, value, refs in self.repo._text_all_indices.iter_all_entries():
            ids.add(key[0])
        return iter(ids)

    def setup(self):
        # we require that text 'knits' be accessed from within the write 
        # group to be able to be written to, simply because it makes this
        # code cleaner - we don't need to track all 'open' knits and 
        # adjust them.
        # prepare to do writes.
        self._ensure_all_index(True)
        self._setup_knit(True)
    
    def _setup_knit(self, for_write):
        if for_write:
            writer = (self.repo._packs._open_pack_writer, self.repo._packs._new_pack.text_index)
        else:
            writer = None
        self.repo._text_knit_access = _PackAccess(
            self.repo._text_pack_map, writer)
        if for_write:
            # a reused knit object for commit specifically.
            self.repo._text_knit = self.get_weave_or_empty(
                'all-texts', None, for_write)
        else:
            self.repo._text_knit = None


class InventoryKnitThunk(object):
    """An object to manage thunking get_inventory_weave to pack based knits."""

    def __init__(self, repo, transport):
        """Create an InventoryKnitThunk for repo at transport.

        This will store its state in the Repository, use the
        indices FileNames to provide a KnitGraphIndex,
        and at the end of transactions write a new index..
        """
        self.repo = repo
        self.transport = transport

    def _ensure_all_index(self):
        """Create the combined index for all inventories."""
        if getattr(self.repo, '_inv_all_indices', None) is not None:
            return
        pack_map, indices = self.repo._packs._make_index_map('.iix')
        if self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.append(self.repo._packs._new_pack.inventory_index)
        self.repo._inv_all_indices = CombinedGraphIndex(indices)
        self.repo._inv_pack_map = pack_map

    def get_weave(self):
        """Get a 'Knit' that contains inventory data."""
        self._ensure_all_index()
        filename = 'inventory'
        if self.repo.is_in_write_group():
            add_callback = self.repo._packs._new_pack.inventory_index.add_nodes
            self.repo._inv_pack_map[self.repo._packs._new_pack.inventory_index] = self.repo._open_pack_tuple
            writer = self.repo._packs._open_pack_writer, self.repo._packs._new_pack.inventory_index
        else:
            add_callback = None # no data-adding permitted.
            writer = None

        knit_index = KnitGraphIndex(self.repo._inv_all_indices,
            add_callback=add_callback,
            deltas=True, parents=True)
        # TODO - mode support. self.weavestore._file_mode,
        knit_access = _PackAccess(self.repo._inv_pack_map, writer)
        self.repo._inv_knit_access = knit_access
        return knit.KnitVersionedFile('inventory', self.transport.clone('..'),
            index=knit_index,
            factory=knit.KnitPlainFactory(),
            access_method=knit_access)

    def setup(self):
        # setup in-memory indices to accumulate data.
        # if we have created an inventory index, add the new write index to it
        if getattr(self.repo, '_inv_all_indices', None) is not None:
            self.repo._inv_all_indices.insert_index(0, self.repo._packs._new_pack.inventory_index)
            # we don't bother updating the knit layer, because there is not
            # defined interface for adding inventories that should need the 
            # existing knit to be changed - its all behind 'repo.add_inventory'.


class GraphKnitRepository(KnitRepository):
    """Experimental graph-knit using repository."""

    def __init__(self, _format, a_bzrdir, control_files, _revision_store,
        control_store, text_store, _commit_builder_class, _serializer):
        KnitRepository.__init__(self, _format, a_bzrdir, control_files,
            _revision_store, control_store, text_store, _commit_builder_class,
            _serializer)
        index_transport = control_files._transport.clone('indices')
        self._packs = RepositoryPackCollection(self, control_files._transport,
            index_transport,
            control_files._transport.clone('upload'),
            control_files._transport.clone('packs'))
        self._revision_store = GraphKnitRevisionStore(self, index_transport, self._revision_store)
        self.weave_store = GraphKnitTextStore(self, index_transport, self.weave_store)
        self._inv_thunk = InventoryKnitThunk(self, index_transport)
        # True when the repository object is 'write locked' (as opposed to the
        # physical lock only taken out around changes to the pack-names list.) 
        # Another way to represent this would be a decorator around the control
        # files object that presents logical locks as physical ones - if this
        # gets ugly consider that alternative design. RBC 20071011
        self._write_lock_count = 0
        self._transaction = None
        # for tests
        self._reconcile_does_inventory_gc = False

    def _abort_write_group(self):
        self._packs._abort_write_group()

    def _access_mode(self):
        """Return 'w' or 'r' for depending on whether a write lock is active.
        
        This method is a helper for the Knit-thunking support objects.
        """
        if self.is_write_locked():
            return 'w'
        return 'r'

    def _refresh_data(self):
        if self._write_lock_count == 1 or self.control_files._lock_count==1:
            # forget what names there are
            self._packs.reset()

    def _start_write_group(self):
        self._packs._start_write_group()

    def _commit_write_group(self):
        return self._packs._commit_write_group()

    def get_inventory_weave(self):
        return self._inv_thunk.get_weave()

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
            from bzrlib import transactions
            self._transaction = transactions.WriteTransaction()
        self._refresh_data()

    def lock_read(self):
        if self._write_lock_count:
            self._write_lock_count += 1
        else:
            self.control_files.lock_read()
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
        self._packs.pack()

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import PackReconciler
        reconciler = PackReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler

    def unlock(self):
        if self._write_lock_count == 1 and self._write_group is not None:
            raise errors.BzrError(
                'Must end write groups before releasing write locks.')
        if self._write_lock_count:
            self._write_lock_count -= 1
            if not self._write_lock_count:
                transaction = self._transaction
                self._transaction = None
                transaction.finish()
        else:
            self.control_files.unlock()


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

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return VersionedFileStore(
            repo_transport,
            prefixed=False,
            file_mode=control_files._file_mode,
            versionedfile_class=knit.KnitVersionedFile,
            versionedfile_kwargs={'factory':knit.KnitPlainFactory()},
            )

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        versioned_file_store = VersionedFileStore(
            repo_transport,
            file_mode=control_files._file_mode,
            prefixed=False,
            precious=True,
            versionedfile_class=knit.KnitVersionedFile,
            versionedfile_kwargs={'delta':False,
                                  'factory':knit.KnitPlainFactory(),
                                 },
            escaped=True,
            )
        return KnitRevisionStore(versioned_file_store)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('knits',
                                  transport,
                                  control_files,
                                  versionedfile_class=knit.KnitVersionedFile,
                                  versionedfile_kwargs={
                                      'create_parent_dir':True,
                                      'delay_create':True,
                                      'dir_mode':control_files._dir_mode,
                                  },
                                  escaped=True)

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
            assert format.__class__ ==  self.__class__
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return self.repository_class(_format=self,
                              a_bzrdir=a_bzrdir,
                              control_files=control_files,
                              _revision_store=_revision_store,
                              control_store=control_store,
                              text_store=text_store,
                              _commit_builder_class=self._commit_builder_class,
                              _serializer=self._serializer)


class RepositoryFormatGraphKnit1(RepositoryFormatPack):
    """Experimental pack based repository with knit1 style data.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - uses a GraphKnitIndex for revisions.knit.
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock

    This format was introduced in bzr.dev.
    """

    repository_class = GraphKnitRepository
    _commit_builder_class = PackCommitBuilder
    _serializer = xml5.serializer_v5

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('experimental')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def __ne__(self, other):
        return self.__class__ is not other.__class__

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar Experimental no-subtrees\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Experimental no-subtrees"

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatGraphKnit3(RepositoryFormatPack):
    """Experimental repository with knit3 style data.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - uses a GraphKnitIndex for revisions.knit.
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
     - support for recording full info about the tree root
     - support for recording tree-references
    """

    repository_class = GraphKnitRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = True
    _serializer = xml7.serializer_v7

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('experimental-subtree')

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
        return "Bazaar Experimental subtrees\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Experimental no-subtrees\n"

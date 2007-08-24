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
from bzrlib.repofmt.knitrepo import KnitRepository, KnitRepository3
from bzrlib.repository import (
    MetaDirRepository,
    MetaDirRepositoryFormat,
    )
import bzrlib.revision as _mod_revision
from bzrlib.store.revision.knit import KnitRevisionStore
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.trace import mutter, note, warning


class Pack(object):
    """An in memory proxy for a .pack and its indices."""

    def __init__(self):
        self.revision_index = None
        self.inventory_index = None
        self.text_index = None
        self.signature_index = None
        self.name = None
        self.transport = None

    def get_revision_count(self):
        return self.revision_index.key_count()


class RepositoryPackCollection(object):

    def __init__(self, repo, transport):
        self.repo = repo
        self.transport = transport
        self.packs = []

    def add_pack_to_memory(self, pack):
        """Make a Pack object available to the repository to satisfy queries.
        
        :param pack: A Pack object.
        """
        self.packs.append(pack)
        if self.repo._revision_all_indices is None:
            # to make this function more useful, perhaps we should make an
            # all_indices object in future?
            pass
        else:
            self.repo._revision_pack_map[pack.revision_index] = (
                pack.transport, pack.name)
            self.repo._revision_all_indices.insert_index(0, pack.revision_index)
        if self.repo._inv_all_indices is not None:
            # inv 'knit' has been used : update it.
            self.repo._inv_all_indices.insert_index(0,
                pack.inventory_index)
            self.repo._inv_pack_map[pack.inventory_index] = pack.transport, pack.name + '.pack'
        if self.repo._text_all_indices is not None:
            # text 'knits' have been used : update it.
            self.repo._text_all_indices.insert_index(0,
                pack.text_index)
        if self.repo._signature_all_indices is not None:
            # sigatures 'knit' accessed : update it.
            self.repo._signature_all_indices.insert_index(0,
                pack.signature_index)

    def all_pack_details(self):
        """Return a list of all the packs as transport,name tuples.

        :return: A list of (transport, name) tuples for all the packs in the
            repository.
        """
        # XXX: fix me, should be direct rather than indirect
        if self.repo._revision_all_indices is None:
            # trigger creation of the all revision index.
            self.repo._revision_store.get_revision_file(self.repo.get_transaction())
        result = []
        for index, transport_and_name in self.repo._revision_pack_map.iteritems():
            result.append(transport_and_name)
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
        for index, transport_and_name in self.repo._revision_pack_map.iteritems():
            if index is None:
                continue
            revision_count = index.key_count()
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
            existing_packs.append((revision_count, transport_and_name))
        pack_operations = self.plan_autopack_combinations(
            existing_packs, pack_distribution)
        self._execute_pack_operations(pack_operations)
        return True

    def create_pack_from_packs(self, revision_index_map, inventory_index_map,
        text_index_map, signature_index_map, suffix, revision_ids=None):
        """Create a new pack by reading data from other packs.

        This does little more than a bulk copy of data. One key difference
        is that data with the same item key across multiple packs is elided
        from the output. The new pack is written into the current pack store
        along with its indices, and the name added to the pack names. The 
        source packs are not altered.

        :param revision_index_map: A revision index map.
        :param inventory_index_map: A inventory index map.
        :param text_index_map: A text index map.
        :param signature_index_map: A signature index map.
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
        random_name = self.repo.control_files._lock.nonce + suffix
        if 'fetch' in debug.debug_flags:
            plain_pack_list = ['%s%s' % (transport.base, name) for
                transport, name in revision_index_map.itervalues()]
            mutter('%s: create_pack: creating pack from source packs: %s%s %s t=0',
                time.ctime(), self.repo._upload_transport.base, random_name,
                plain_pack_list)
            start_time = time.time()
        write_stream = self.repo._upload_transport.open_write_stream(random_name)
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: pack stream open: %s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                time.time() - start_time)
        pack_hash = md5.new()
        buffer = []
        def write_data(bytes, update=pack_hash.update, write=write_stream.write):
            buffer.append(bytes)
            if len(buffer) == 640:
                bytes = ''.join(buffer)
                write(bytes)
                update(bytes)
                del buffer[:]
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        # open new indices
        revision_index = InMemoryGraphIndex(reference_lists=1)
        inv_index = InMemoryGraphIndex(reference_lists=2)
        text_index = InMemoryGraphIndex(reference_lists=2, key_elements=2)
        signature_index = InMemoryGraphIndex(reference_lists=0)
        # select revisions
        if revision_ids:
            revision_keys = [(revision_id,) for revision_id in revision_ids]
        else:
            revision_keys = None
        revision_nodes = self._index_contents(revision_index_map, revision_keys)
        # copy revision keys and adjust values
        list(self._copy_nodes_graph(revision_nodes, revision_index_map, writer,
            revision_index))
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: revisions copied: %s%s %d items t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                revision_index.key_count(),
                time.time() - start_time)
        # select inventory keys
        inv_keys = revision_keys # currently the same keyspace
        inv_nodes = self._index_contents(inventory_index_map, inv_keys)
        # copy inventory keys and adjust values
        # XXX: Should be a helper function to allow different inv representation
        # at this point.
        inv_lines = self._copy_nodes_graph(inv_nodes, inventory_index_map,
            writer, inv_index, output_lines=True)
        if revision_ids:
            fileid_revisions = self.repo._find_file_ids_from_xml_inventory_lines(
                inv_lines, revision_ids)
            text_filter = []
            for fileid, file_revids in fileid_revisions.iteritems():
                text_filter.extend(
                    [(fileid, file_revid) for file_revid in file_revids])
        else:
            list(inv_lines)
            text_filter = None
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: inventories copied: %s%s %d items t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                inv_index.key_count(),
                time.time() - start_time)
        # select text keys
        text_nodes = self._index_contents(text_index_map, text_filter)
        # copy text keys and adjust values
        list(self._copy_nodes_graph(text_nodes, text_index_map, writer,
            text_index))
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: file texts copied: %s%s %d items t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                text_index.key_count(),
                time.time() - start_time)
        # select signature keys
        signature_filter = revision_keys # same keyspace
        signature_nodes = self._index_contents(signature_index_map,
            signature_filter)
        # copy signature keys and adjust values
        self._copy_nodes(signature_nodes, signature_index_map, writer, signature_index)
        if 'fetch' in debug.debug_flags:
            mutter('%s: create_pack: revision signatures copied: %s%s %d items t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                signature_index.key_count(),
                time.time() - start_time)
        # finish the pack
        writer.end()
        if len(buffer):
            bytes = ''.join(buffer)
            write_stream.write(bytes)
            pack_hash.update(bytes)
        new_name = pack_hash.hexdigest()
        # if nothing has been written, discard the new pack.
        if 0 == sum((revision_index.key_count(),
            inv_index.key_count(),
            text_index.key_count(),
            signature_index.key_count(),
            )):
            self.repo._upload_transport.delete(random_name)
            return None
        # add to names
        self.allocate(new_name)
        # rename into place
        write_stream.close()
        self.repo._upload_transport.rename(random_name, '../packs/' + new_name + '.pack')
        result = Pack()
        result.name = new_name
        result.transport = self.repo._upload_transport.clone('../packs/')
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: pack renamed into place: %s%s->%s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                result.transport, result.name,
                time.time() - start_time)
        # write indices
        index_transport = self.repo._upload_transport.clone('../indices')
        rev_index_name = self.repo._revision_store.name_to_revision_index_name(new_name)
        index_transport.put_file(rev_index_name, revision_index.finish())
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: wrote revision index: %s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                time.time() - start_time)
        inv_index_name = self.repo._inv_thunk.name_to_inv_index_name(new_name)
        index_transport.put_file(inv_index_name, inv_index.finish())
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: wrote inventory index: %s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                time.time() - start_time)
        text_index_name = self.repo.weave_store.name_to_text_index_name(new_name)
        index_transport.put_file(text_index_name, text_index.finish())
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: wrote file texts index: %s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                time.time() - start_time)
        signature_index_name = self.repo._revision_store.name_to_signature_index_name(new_name)
        index_transport.put_file(signature_index_name, signature_index.finish())
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: wrote revision signatures index: %s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                time.time() - start_time)
        result.revision_index = revision_index
        result.inventory_index = inv_index
        result.text_index = text_index
        result.signature_index = signature_index
        if 'fetch' in debug.debug_flags:
            # XXX: size might be interesting?
            mutter('%s: create_pack: finished: %s%s t+%6.3fs',
                time.ctime(), self.repo._upload_transport.base, random_name,
                time.time() - start_time)
        return result

    def _execute_pack_operations(self, pack_operations):
        """Execute a series of pack operations.

        :param pack_operations: A list of [revision_count, packs_to_combine].
        :return: None.
        """
        for revision_count, pack_details in pack_operations:
            # we may have no-ops from the setup logic
            if len(pack_details) == 0:
                continue
            # have a progress bar?
            self._combine_packs(pack_details)
            for pack_detail in pack_details:
                self._remove_pack_name(pack_detail[1])
        # record the newly available packs and stop advertising the old
        # packs
        self.save()
        # move the old packs out of the way
        for revision_count, pack_details in pack_operations:
            self._obsolete_packs(pack_details)

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
                'containing %d revisions into %d packs.', self, total_packs,
                total_revisions, self._max_pack_count(total_revisions))
            # determine which packs need changing
            pack_distribution = [1]
            pack_operations = [[0, []]]
            for index, transport_and_name in self.repo._revision_pack_map.iteritems():
                if index is None:
                    continue
                revision_count = index.key_count()
                pack_operations[-1][0] += revision_count
                pack_operations[-1][1].append(transport_and_name)
            self._execute_pack_operations(pack_operations)
        finally:
            if not self.repo.is_in_write_group():
                self.reset()

    def plan_autopack_combinations(self, existing_packs, pack_distribution):
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
            next_pack_rev_count, next_pack_details = existing_packs.pop(0)
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
                pack_operations[-1][1].append(next_pack_details)
                if pack_operations[-1][0] >= pack_distribution[0]:
                    # this pack is used up, shift left.
                    del pack_distribution[0]
                    pack_operations.append([0, []])
        
        return pack_operations

    def _combine_packs(self, pack_details):
        """Combine the data from the packs listed in pack_details.

        This does little more than a bulk copy of data. One key difference
        is that data with the same item key across multiple packs is elided
        from the output. The new pack is written into the current pack store
        along with its indices, and the name added to the pack names. The 
        source packs are not altered.

        :param pack_details: A list of tuples with the transport and pack name
            in use.
        :return: None
        """
        # select revision keys
        revision_index_map = self._revision_index_map(pack_details)
        # select inventory keys
        inv_index_map = self._inv_index_map(pack_details)
        # select text keys
        text_index_map = self._text_index_map(pack_details)
        # select signature keys
        signature_index_map = self._signature_index_map(pack_details)
        self.create_pack_from_packs(revision_index_map, inv_index_map,
            text_index_map, signature_index_map, '.autopack')

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
            self._names = set(node[1][0] for node in 
                GraphIndex(self.transport, 'pack-names').iter_all_entries())

    def allocate(self, name):
        self.ensure_loaded()
        if name in self._names:
            raise errors.DuplicateKey(name)
        self._names.add(name)

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
        return sorted(self._names)

    def _obsolete_packs(self, pack_details):
        """Move a number of packs which have been obsoleted out of the way.

        Each pack and its associated indices are moved out of the way.

        Note: for correctness this function should only be called after a new
        pack names index has been written without these pack names, and with
        the names of packs that contain the data previously available via these
        packs.

        :param pack_details: The transport, name tuples for the packs.
        :param return: None.
        """
        for pack_detail in pack_details:
            pack_detail[0].rename(pack_detail[1],
                '../obsolete_packs/' + pack_detail[1])
            basename = pack_detail[1][:-4]
            index_transport = pack_detail[0].clone('../indices')
            for suffix in ('iix', 'six', 'tix', 'rix'):
                index_transport.rename(basename + suffix,
                    '../obsolete_packs/' + basename + suffix)

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

    def _remove_pack_name(self, name):
        # strip .pack
        self._names.remove(name[:-5])

    def reset(self):
        self._names = None
        self.packs = []

    def _inv_index_map(self, pack_details):
        """Get a map of inv index -> packs for pack_details."""
        # the simplest thing for now is to create new index objects.
        # this should really reuse the existing index objects for these 
        # packs - this means making the way they are managed in the repo be 
        # more sane.
        indices = {}
        for transport, name in pack_details:
            index_name = name[:-5]
            index_name = self.repo._inv_thunk.name_to_inv_index_name(index_name)
            indices[GraphIndex(transport.clone('../indices'), index_name)] = \
                (transport, name)
        return indices

    def _revision_index_map(self, pack_details):
        """Get a map of revision index -> packs for pack_details."""
        # the simplest thing for now is to create new index objects.
        # this should really reuse the existing index objects for these 
        # packs - this means making the way they are managed in the repo be 
        # more sane.
        indices = {}
        for transport, name in pack_details:
            index_name = name[:-5]
            index_name = self.repo._revision_store.name_to_revision_index_name(index_name)
            indices[GraphIndex(transport.clone('../indices'), index_name)] = \
                (transport, name)
        return indices

    def _signature_index_map(self, pack_details):
        """Get a map of signature index -> packs for pack_details."""
        # the simplest thing for now is to create new index objects.
        # this should really reuse the existing index objects for these 
        # packs - this means making the way they are managed in the repo be 
        # more sane.
        indices = {}
        for transport, name in pack_details:
            index_name = name[:-5]
            index_name = self.repo._revision_store.name_to_signature_index_name(index_name)
            indices[GraphIndex(transport.clone('../indices'), index_name)] = \
                (transport, name)
        return indices

    def _text_index_map(self, pack_details):
        """Get a map of text index -> packs for pack_details."""
        # the simplest thing for now is to create new index objects.
        # this should really reuse the existing index objects for these 
        # packs - this means making the way they are managed in the repo be 
        # more sane.
        indices = {}
        for transport, name in pack_details:
            index_name = name[:-5]
            index_name = self.repo.weave_store.name_to_text_index_name(index_name)
            indices[GraphIndex(transport.clone('../indices'), index_name)] = \
                (transport, name)
        return indices

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

    def save(self):
        builder = GraphIndexBuilder()
        for name in self._names:
            builder.add_node((name, ), '')
        self.transport.put_file('pack-names', builder.finish())

    def setup(self):
        # cannot add names if we're not in a 'write lock'.
        if self.repo.control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)


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
        self.repo._packs.ensure_loaded()
        pack_map, indices = self._make_rev_pack_map()
        if self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.insert(0, self.repo._revision_write_index)
            pack_map[self.repo._revision_write_index] = self.repo._open_pack_tuple
            writer = self.repo._open_pack_writer, self.repo._revision_write_index
            add_callback = self.repo._revision_write_index.add_nodes
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
            create=False, access_mode=self.repo.control_files._lock_mode,
            index=knit_index, delta=False, factory=knit.KnitPlainFactory(),
            access_method=knit_access)
        return self.repo._revision_knit

    def _make_rev_pack_map(self):
        indices = []
        pack_map = {}
        for name in self.repo._packs.names():
            # TODO: maybe this should expose size to us  to allow
            # sorting of the indices for better performance ?
            index_name = self.name_to_revision_index_name(name)
            indices.append(GraphIndex(self.transport, index_name))
            pack_map[indices[-1]] = (self.repo._pack_tuple(name))
        return pack_map, indices

    def get_signature_file(self, transaction):
        """Get the signature versioned file object."""
        if getattr(self.repo, '_signature_knit', None) is not None:
            return self.repo._signature_knit
        indices = []
        self.repo._packs.ensure_loaded()
        pack_map = {}
        for name in self.repo._packs.names():
            # TODO: maybe this should expose size to us  to allow
            # sorting of the indices for better performance ?
            index_name = self.name_to_signature_index_name(name)
            indices.append(GraphIndex(self.transport, index_name))
            pack_map[indices[-1]] = (self.repo._pack_tuple(name))
        if self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.insert(0, self.repo._signature_write_index)
            pack_map[self.repo._signature_write_index] = self.repo._open_pack_tuple
            writer = self.repo._open_pack_writer, self.repo._signature_write_index
            add_callback = self.repo._signature_write_index.add_nodes
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
            create=False, access_mode=self.repo.control_files._lock_mode,
            index=knit_index, delta=False, factory=knit.KnitPlainFactory(),
            access_method=knit_access)
        return self.repo._signature_knit

    def data_inserted(self):
        if (getattr(self.repo, '_revision_write_index', None) and
            self.repo._revision_write_index.key_count()):
            return True
        if (getattr(self.repo, '_signature_write_index', None) and
            self.repo._signature_write_index.key_count()):
            return True
        return False

    def flush(self, new_name):
        """Write out pending indices."""
        # write a revision index (might be empty)
        new_index_name = self.name_to_revision_index_name(new_name)
        self.transport.put_file(new_index_name,
            self.repo._revision_write_index.finish())
        if self.repo._revision_all_indices is None:
            # create a pack map for the autopack code - XXX finish
            # making a clear managed list of packs, indices and use
            # that in these mapping classes
            self.repo._revision_pack_map = self._make_rev_pack_map()[0]
        else:
            del self.repo._revision_pack_map[self.repo._revision_write_index]
            self.repo._revision_write_index = None
            new_index = GraphIndex(self.transport, new_index_name)
            self.repo._revision_pack_map[new_index] = (self.repo._pack_tuple(new_name))
            # revisions 'knit' accessed : update it.
            self.repo._revision_all_indices.insert_index(0, new_index)
            # remove the write buffering index. XXX: API break
            # - clearly we need a remove_index call too.
            del self.repo._revision_all_indices._indices[1]
            # reset the knit access writer
            self.repo._revision_knit_access.set_writer(None, None, (None, None))

        # write a signatures index (might be empty)
        new_index_name = self.name_to_signature_index_name(new_name)
        self.transport.put_file(new_index_name,
            self.repo._signature_write_index.finish())
        self.repo._signature_write_index = None
        if self.repo._signature_all_indices is not None:
            # sigatures 'knit' accessed : update it.
            self.repo._signature_all_indices.insert_index(0,
                GraphIndex(self.transport, new_index_name))
            # remove the write buffering index. XXX: API break
            # - clearly we need a remove_index call too.
            del self.repo._signature_all_indices._indices[1]
            # reset the knit access writer
            self.repo._signature_knit_access.set_writer(None, None, (None, None))

    def name_to_revision_index_name(self, name):
        """The revision index is the name + .rix."""
        return name + '.rix'

    def name_to_signature_index_name(self, name):
        """The signature index is the name + .six."""
        return name + '.six'

    def reset(self):
        """Clear all cached data."""
        # cached revision data
        self.repo._revision_knit = None
        self.repo._revision_write_index = None
        self.repo._revision_all_indices = None
        self.repo._revision_knit_access = None
        # cached signature data
        self.repo._signature_knit = None
        self.repo._signature_write_index = None
        self.repo._signature_all_indices = None
        self.repo._signature_knit_access = None

    def setup(self):
        # setup in-memory indices to accumulate data.
        self.repo._revision_write_index = InMemoryGraphIndex(1)
        self.repo._signature_write_index = InMemoryGraphIndex(0)
        # if knit indices have been handed out, add a mutable
        # index to them
        if self.repo._revision_knit is not None:
            self.repo._revision_all_indices.insert_index(0, self.repo._revision_write_index)
            self.repo._revision_knit._index._add_callback = self.repo._revision_write_index.add_nodes
            self.repo._revision_knit_access.set_writer(self.repo._open_pack_writer,
                self.repo._revision_write_index, self.repo._open_pack_tuple)
        if self.repo._signature_knit is not None:
            self.repo._signature_all_indices.insert_index(0, self.repo._signature_write_index)
            self.repo._signature_knit._index._add_callback = self.repo._signature_write_index.add_nodes
            self.repo._signature_knit_access.set_writer(self.repo._open_pack_writer,
                self.repo._signature_write_index, self.repo._open_pack_tuple)


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

    def data_inserted(self):
        # XXX: Should we define __len__ for indices?
        if (getattr(self.repo, '_text_write_index', None) and
            self.repo._text_write_index.key_count()):
            return True

    def _ensure_all_index(self):
        """Create the combined index for all texts."""
        if getattr(self.repo, '_text_all_indices', None) is not None:
            return
        indices = []
        self.repo._packs.ensure_loaded()
        self.repo._text_pack_map = {}
        for name in self.repo._packs.names():
            # TODO: maybe this should expose size to us  to allow
            # sorting of the indices for better performance ?
            index_name = self.name_to_text_index_name(name)
            indices.append(GraphIndex(self.transport, index_name))
            self.repo._text_pack_map[indices[-1]] = (self.repo._pack_tuple(name))
        if self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.insert(0, self.repo._text_write_index)
        self.repo._text_all_indices = CombinedGraphIndex(indices)

    def flush(self, new_name):
        """Write the index out to new_name."""
        # write a revision index (might be empty)
        new_index_name = self.name_to_text_index_name(new_name)
        self.transport.put_file(new_index_name,
            self.repo._text_write_index.finish())
        self.repo._text_write_index = None
        if self.repo._text_all_indices is not None:
            # text 'knits' have been used, replace the mutated memory index
            # with the new on-disk one. XXX: is this really a good idea?
            # perhaps just keep using the memory one ?
            self.repo._text_all_indices.insert_index(0,
                GraphIndex(self.transport, new_index_name))
            # remove the write buffering index. XXX: API break
            # - clearly we need a remove_index call too.
            del self.repo._text_all_indices._indices[1]

    def get_weave_or_empty(self, file_id, transaction):
        """Get a 'Knit' backed by the .tix indices.

        The transaction parameter is ignored.
        """
        self._ensure_all_index()
        filename = self.weavestore.filename(file_id)
        if self.repo.is_in_write_group():
            add_callback = self.repo._text_write_index.add_nodes
            self.repo._text_pack_map[self.repo._text_write_index] = self.repo._open_pack_tuple
            writer = self.repo._open_pack_writer, self.repo._text_write_index
        else:
            add_callback = None # no data-adding permitted.
            writer = None

        file_id_index = GraphIndexPrefixAdapter(self.repo._text_all_indices,
            (file_id, ), 1, add_nodes_callback=add_callback)
        knit_index = KnitGraphIndex(file_id_index,
            add_callback=file_id_index.add_nodes,
            deltas=True, parents=True)
        knit_access = _PackAccess(self.repo._text_pack_map, writer)
        return knit.KnitVersionedFile(filename, self.weavestore._transport,
            self.weavestore._file_mode,
            index=knit_index,
            access_method=knit_access,
            **self.weavestore._versionedfile_kwargs)

    get_weave = get_weave_or_empty

    def __iter__(self):
        """Generate a list of the fileids inserted, for use by check."""
        self._ensure_all_index()
        ids = set()
        for index, key, value, refs in self.repo._text_all_indices.iter_all_entries():
            ids.add(key[0])
        return iter(ids)

    def name_to_text_index_name(self, name):
        """The text index is the name + .tix."""
        return name + '.tix'

    def reset(self):
        """Clear all cached data."""
        # remove any accumlating index of text data
        self.repo._text_write_index = None
        # remove all constructed text data indices
        self.repo._text_all_indices = None
        # and the pack map
        self.repo._text_pack_map = None

    def setup(self):
        # setup in-memory indices to accumulate data.
        self.repo._text_write_index = InMemoryGraphIndex(reference_lists=2,
            key_elements=2)
        # we require that text 'knits' be accessed from within the write 
        # group to be able to be written to, simply because it makes this
        # code cleaner - we don't need to track all 'open' knits and 
        # adjust them.


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

    def data_inserted(self):
        # XXX: Should we define __len__ for indices?
        if (getattr(self.repo, '_inv_write_index', None) and
            self.repo._inv_write_index.key_count()):
            return True

    def _ensure_all_index(self):
        """Create the combined index for all inventories."""
        if getattr(self.repo, '_inv_all_indices', None) is not None:
            return
        indices = []
        self.repo._packs.ensure_loaded()
        pack_map = {}
        for name in self.repo._packs.names():
            # TODO: maybe this should expose size to us  to allow
            # sorting of the indices for better performance ?
            index_name = self.name_to_inv_index_name(name)
            indices.append(GraphIndex(self.transport, index_name))
            pack_map[indices[-1]] = (self.repo._pack_tuple(name))
        if self.repo.is_in_write_group():
            # allow writing: queue writes to a new index
            indices.append(self.repo._inv_write_index)
        self.repo._inv_all_indices = CombinedGraphIndex(indices)
        self.repo._inv_pack_map = pack_map

    def flush(self, new_name):
        """Write the index out to new_name."""
        # write an index (might be empty)
        new_index_name = self.name_to_inv_index_name(new_name)
        self.transport.put_file(new_index_name,
            self.repo._inv_write_index.finish())
        self.repo._inv_write_index = None
        if self.repo._inv_all_indices is not None:
            # inv 'knit' has been used, replace the mutated memory index
            # with the new on-disk one. XXX: is this really a good idea?
            # perhaps just keep using the memory one ?
            self.repo._inv_all_indices.insert_index(0,
                GraphIndex(self.transport, new_index_name))
            # remove the write buffering index. XXX: API break
            # - clearly we need a remove_index call too.
            del self.repo._inv_all_indices._indices[1]
            self.repo._inv_knit_access.set_writer(None, None, (None, None))
        self.repo._inv_pack_map = None

    def get_weave(self):
        """Get a 'Knit' that contains inventory data."""
        self._ensure_all_index()
        filename = 'inventory'
        if self.repo.is_in_write_group():
            add_callback = self.repo._inv_write_index.add_nodes
            self.repo._inv_pack_map[self.repo._inv_write_index] = self.repo._open_pack_tuple
            writer = self.repo._open_pack_writer, self.repo._inv_write_index
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

    def name_to_inv_index_name(self, name):
        """The inv index is the name + .iix."""
        return name + '.iix'

    def reset(self):
        """Clear all cached data."""
        # remove any accumlating index of inv data
        self.repo._inv_write_index = None
        # remove all constructed inv data indices
        self.repo._inv_all_indices = None
        # remove the knit access object
        self.repo._inv_knit_access = None
        self.repo._inv_pack_map = None

    def setup(self):
        # setup in-memory indices to accumulate data.
        # - we want to map compression only, but currently the knit code hasn't
        # been updated enough to understand that, so we have a regular 2-list
        # index giving parents and compression source.
        self.repo._inv_write_index = InMemoryGraphIndex(reference_lists=2)
        # if we have created an inventory index, add the new write index to it
        if getattr(self.repo, '_inv_all_indices', None) is not None:
            self.repo._inv_all_indices.insert_index(0, self.repo._inv_write_index)
            # we don't bother updating the knit layer, because there is not
            # defined interface for adding inventories that should need the 
            # existing knit to be changed - its all behind 'repo.add_inventory'.


class GraphKnitRepository1(KnitRepository):
    """Experimental graph-knit using repository."""

    def __init__(self, _format, a_bzrdir, control_files, _revision_store,
                 control_store, text_store):
        KnitRepository.__init__(self, _format, a_bzrdir, control_files,
                              _revision_store, control_store, text_store)
        index_transport = control_files._transport.clone('indices')
        self._packs = RepositoryPackCollection(self, control_files._transport)
        self._revision_store = GraphKnitRevisionStore(self, index_transport, self._revision_store)
        self.weave_store = GraphKnitTextStore(self, index_transport, self.weave_store)
        self._inv_thunk = InventoryKnitThunk(self, index_transport)
        self._upload_transport = control_files._transport.clone('upload')
        self._pack_transport = control_files._transport.clone('packs')
        # for tests
        self._reconcile_does_inventory_gc = False

    def _abort_write_group(self):
        # FIXME: just drop the transient index.
        self._revision_store.reset()
        self.weave_store.reset()
        self._inv_thunk.reset()
        # forget what names there are
        self._packs.reset()
        self._open_pack_hash = None

    def _pack_tuple(self, name):
        """Return a tuple with the transport and file name for a pack name."""
        return self._pack_transport, name + '.pack'

    def _refresh_data(self):
        if self.control_files._lock_count==1:
            self._revision_store.reset()
            self.weave_store.reset()
            self._inv_thunk.reset()
            # forget what names there are
            self._packs.reset()

    def _start_write_group(self):
        random_name = self.control_files._lock.nonce
        self._open_pack_tuple = (self._upload_transport, random_name + '.pack')
        write_stream = self._upload_transport.open_write_stream(random_name + '.pack')
        self._write_stream = write_stream
        self._open_pack_hash = md5.new()
        def write_data(bytes, write=write_stream.write, update=self._open_pack_hash.update):
            write(bytes)
            update(bytes)
        self._open_pack_writer = pack.ContainerWriter(write_data)
        self._open_pack_writer.begin()
        self._packs.setup()
        self._revision_store.setup()
        self.weave_store.setup()
        self._inv_thunk.setup()

    def _commit_write_group(self):
        data_inserted = (self._revision_store.data_inserted() or
            self.weave_store.data_inserted() or 
            self._inv_thunk.data_inserted())
        if data_inserted:
            self._open_pack_writer.end()
            new_name = self._open_pack_hash.hexdigest()
            # If this fails, its a hash collision. We should:
            # - determine if its a collision or
            # - the same content or
            # - the existing name is not the actual hash - e.g.
            #   its a deliberate attack or data corruption has
            #   occuring during the write of that file.
            new_pack = Pack()
            new_pack.name = new_name
            new_pack.transport = self._upload_transport.clone('../packs/')
            # To populate:
            # new_pack.revision_index = 
            # new_pack.inventory_index = 
            # new_pack.text_index = 
            # new_pack.signature_index = 
            self._packs.allocate(new_name)
            self.weave_store.flush(new_name)
            self._inv_thunk.flush(new_name)
            self._revision_store.flush(new_name)
            self._write_stream.close()
            self._upload_transport.rename(self._open_pack_tuple[1],
                '../packs/' + new_name + '.pack')
            self._open_pack_tuple = None
            if not self._packs.autopack():
                self._packs.save()
        else:
            # remove the pending upload
            self._upload_transport.delete(self._open_pack_tuple[1])
        self._revision_store.reset()
        self.weave_store.reset()
        self._inv_thunk.reset()
        # forget what names there are - should just refresh and deal with the
        # delta.
        self._packs.reset()
        self._open_pack_hash = None
        self._write_stream = None

    def get_inventory_weave(self):
        return self._inv_thunk.get_weave()

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

    def reconcile_actions(self):
        """Return a set of actions taken by reconcile on this repository.
 
        Pack repositories currently perform no reconciliation.

        :return: A set of actions. e.g. set(['inventory_gc']).
        """
        return set([])


class GraphKnitRepository3(KnitRepository3):
    """Experimental graph-knit using subtrees repository."""

    def __init__(self, _format, a_bzrdir, control_files, _revision_store,
                 control_store, text_store):
        KnitRepository3.__init__(self, _format, a_bzrdir, control_files,
                              _revision_store, control_store, text_store)
        index_transport = control_files._transport.clone('indices')
        self._packs = RepositoryPackCollection(self, control_files._transport)
        self._revision_store = GraphKnitRevisionStore(self, index_transport, self._revision_store)
        self.weave_store = GraphKnitTextStore(self, index_transport, self.weave_store)
        self._inv_thunk = InventoryKnitThunk(self, index_transport)
        self._upload_transport = control_files._transport.clone('upload')
        self._pack_transport = control_files._transport.clone('packs')
        # for tests
        self._reconcile_does_inventory_gc = False

    def _abort_write_group(self):
        # FIXME: just drop the transient index.
        self._revision_store.reset()
        self.weave_store.reset()
        self._inv_thunk.reset()
        # forget what names there are
        self._packs.reset()
        self._open_pack_hash = None

    def _pack_tuple(self, name):
        """Return a tuple with the transport and file name for a pack name."""
        return self._pack_transport, name + '.pack'

    def _refresh_data(self):
        if self.control_files._lock_count==1:
            self._revision_store.reset()
            self.weave_store.reset()
            self._inv_thunk.reset()
            # forget what names there are
            self._packs.reset()

    def _start_write_group(self):
        random_name = self.control_files._lock.nonce
        self._open_pack_tuple = (self._upload_transport, random_name + '.pack')
        write_stream = self._upload_transport.open_write_stream(random_name + '.pack')
        self._write_stream = write_stream
        self._open_pack_hash = md5.new()
        def write_data(bytes, write=write_stream.write, update=self._open_pack_hash.update):
            write(bytes)
            update(bytes)
        self._open_pack_writer = pack.ContainerWriter(write_data)
        self._open_pack_writer.begin()
        self._packs.setup()
        self._revision_store.setup()
        self.weave_store.setup()
        self._inv_thunk.setup()

    def _commit_write_group(self):
        data_inserted = (self._revision_store.data_inserted() or
            self.weave_store.data_inserted() or 
            self._inv_thunk.data_inserted())
        if data_inserted:
            self._open_pack_writer.end()
            new_name = self._open_pack_hash.hexdigest()
            # If this fails, its a hash collision. We should:
            # - determine if its a collision or
            # - the same content or
            # - the existing name is not the actual hash - e.g.
            #   its a deliberate attack or data corruption has
            #   occuring during the write of that file.
            self._packs.allocate(new_name)
            self.weave_store.flush(new_name)
            self._inv_thunk.flush(new_name)
            self._revision_store.flush(new_name)
            self._write_stream.close()
            self._upload_transport.rename(self._open_pack_tuple[1],
                '../packs/' + new_name + '.pack')
            self._open_pack_tuple = None
            if not self._packs.autopack():
                self._packs.save()
        else:
            # remove the pending upload
            self._upload_transport.delete(self._open_pack_tuple[1])
        self._revision_store.reset()
        self.weave_store.reset()
        self._inv_thunk.reset()
        # forget what names there are - should just refresh and deal with the
        # delta.
        self._packs.reset()
        self._open_pack_hash = None
        self._write_stream = None

    def get_inventory_weave(self):
        return self._inv_thunk.get_weave()

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

    def reconcile_actions(self):
        """Return a set of actions taken by reconcile on this repository.
        
        :return: A set of actions. e.g. set(['inventory_gc']).
        """
        return set([])


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
                              text_store=text_store)


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

    repository_class = GraphKnitRepository1

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

    repository_class = GraphKnitRepository3
    rich_root_data = True
    supports_tree_reference = True

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

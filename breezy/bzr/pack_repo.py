# Copyright (C) 2007-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Pack-based repository format implementation.

This module implements a repository format that stores data in 'pack' files,
which are container files that hold multiple versioned texts, inventories,
revisions, and signatures. The pack format provides efficient storage and
fast access to repository data through specialized indices.
"""

import contextlib
import re
import sys

import vcsgraph.graph as _vcsgraph

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import time

from breezy import (
    config,
    transactions,
    ui,
    )
from bzrformats import pack
from bzrformats.index import (
    CombinedGraphIndex,
    )
""",
)
from bzrformats import btree_index
from bzrformats import index as _mod_index
from bzrformats.errors import BzrCheckError, ObjectNotLocked
from bzrformats.pack_repo import RetryWithNewPacks
from bzrformats.serializer import InventorySerializer, RevisionSerializer

from .. import debug, errors, lockdir, osutils
from .. import transport as _mod_transport
from ..bzr import lockable_files
from ..decorators import only_raises
from ..lock import LogicalLockResult
from ..repository import RepositoryWriteLockResult, _LazyListJoin
from ..trace import mutter, note, warning
from .repository import MetaDirRepository, RepositoryFormatMetaDir
from .vf_repository import (
    MetaDirVersionedFileRepository,
    MetaDirVersionedFileRepositoryFormat,
    VersionedFileCommitBuilder,
)


class RetryAutopack(RetryWithNewPacks):
    """Raised when we are autopacking and we find a missing file.

    Meant as a signaling exception, to tell the autopack code it should try
    again.
    """

    internal_error = True

    _fmt = (
        "Pack files have changed, reload and try autopack again."
        " context: %(context)s %(orig_error)s"
    )


class PackCommitBuilder(VersionedFileCommitBuilder):
    """Subclass of VersionedFileCommitBuilder to add texts with pack semantics.

    Specifically this uses one knit object rather than one knit object per
    added text, reducing memory and object pressure.
    """

    def __init__(
        self,
        repository,
        parents,
        config,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
        owns_transaction=True,
    ):
        """Initialize a PackCommitBuilder.

        Args:
            repository: The target repository for the commit.
            parents: Parent revision IDs for the commit.
            config: Branch configuration.
            timestamp: Commit timestamp (optional).
            timezone: Commit timezone (optional).
            committer: Committer identity (optional).
            revprops: Revision properties (optional).
            revision_id: Specific revision ID to use (optional).
            lossy: Whether this is a lossy conversion (optional).
            owns_transaction: Whether this builder owns the transaction (optional).
        """
        VersionedFileCommitBuilder.__init__(
            self,
            repository,
            parents,
            config,
            timestamp=timestamp,
            timezone=timezone,
            committer=committer,
            revprops=revprops,
            revision_id=revision_id,
            lossy=lossy,
            owns_transaction=owns_transaction,
        )
        self._file_graph = _vcsgraph.Graph(
            repository._pack_collection.text_index.combined_index
        )

    def _heads(self, file_id, revision_ids):
        keys = [(file_id, revision_id) for revision_id in revision_ids]
        return {key[1] for key in self._file_graph.heads(keys)}


# Pack primitives are provided by bzrformats; breezy still wraps them
# with higher-level orchestration classes below.
from bzrformats.pack_repo import ExistingPack, NewPack, Pack, ResumedPack


class AggregateIndex:
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

    def __init__(self, reload_func=None, flush_func=None):
        """Create an AggregateIndex.

        :param reload_func: A function to call if we find we are missing an
            index. Should have the form reload_func() => True if the list of
            active pack files has changed.
        """
        self._reload_func = reload_func
        self.index_to_pack = {}
        self.combined_index = CombinedGraphIndex([], reload_func=reload_func)
        self.data_access = _DirectPackAccess(
            self.index_to_pack, reload_func=reload_func, flush_func=flush_func
        )
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
        self.combined_index.insert_index(0, index, pack.name)

    def add_writable_index(self, index, pack):
        """Add an index which is able to have data added to it.

        There can be at most one writable index at any time.  Any
        modifications made to the knit are put into this index.

        :param index: An index from the pack parameter.
        :param pack: A Pack instance.
        """
        if self.add_callback is not None:
            raise AssertionError(
                f"{self} already has a writable index through {self.add_callback}"
            )
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
        del self.combined_index._index_names[:]
        self.add_callback = None

    def remove_index(self, index):
        """Remove index from the indices used to answer queries.

        :param index: An index from the pack parameter.
        """
        del self.index_to_pack[index]
        pos = self.combined_index._indices.index(index)
        del self.combined_index._indices[pos]
        del self.combined_index._index_names[pos]
        if (
            self.add_callback is not None
            and getattr(index, "add_nodes", None) == self.add_callback
        ):
            self.add_callback = None
            self.data_access.set_writer(None, None, (None, None))


class Packer:
    """Create a pack from packs."""

    def __init__(
        self, pack_collection, packs, suffix, revision_ids=None, reload_func=None
    ):
        """Create a Packer.

        :param pack_collection: A RepositoryPackCollection object where the
            new pack is being written to.
        :param packs: The packs to combine.
        :param suffix: The suffix to use on the temporary files for the pack.
        :param revision_ids: Revision ids to limit the pack to.
        :param reload_func: A function to call if a pack file/index goes
            missing. The side effect of calling this function should be to
            update self.packs. See also AggregateIndex
        """
        self.packs = packs
        self.suffix = suffix
        self.revision_ids = revision_ids
        # The pack object we are creating.
        self.new_pack = None
        self._pack_collection = pack_collection
        self._reload_func = reload_func
        # The index layer keys for the revisions being copied. None for 'all
        # objects'.
        self._revision_keys = None
        # What text keys to copy. None for 'all texts'. This is set by
        # _copy_inventory_texts
        self._text_filter = None

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
        # - which has already been flushed, so it's safe.
        # XXX: - duplicate code warning with start_write_group; fix before
        #      considering 'done'.
        if self._pack_collection._new_pack is not None:
            raise errors.BzrError(
                "call to {}.pack() while another pack is being written.".format(
                    self.__class__.__name__
                )
            )
        if self.revision_ids is not None:
            if len(self.revision_ids) == 0:
                # silly fetch request.
                return None
            else:
                self.revision_ids = frozenset(self.revision_ids)
                self.revision_keys = frozenset((revid,) for revid in self.revision_ids)
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
        new_pack = self._pack_collection.pack_factory(
            self._pack_collection,
            upload_suffix=self.suffix,
            file_mode=self._pack_collection.repo.controldir._get_file_mode(),
        )
        # We know that we will process all nodes in order, and don't need to
        # query, so don't combine any indices spilled to disk until we are done
        new_pack.revision_index.set_optimize(combine_backing_indices=False)
        new_pack.inventory_index.set_optimize(combine_backing_indices=False)
        new_pack.text_index.set_optimize(combine_backing_indices=False)
        new_pack.signature_index.set_optimize(combine_backing_indices=False)
        return new_pack

    def _copy_revision_texts(self):
        """Copy revision data to the new pack."""
        raise NotImplementedError(self._copy_revision_texts)

    def _copy_inventory_texts(self):
        """Copy the inventory texts to the new pack.

        self._revision_keys is used to determine what inventories to copy.

        Sets self._text_filter appropriately.
        """
        raise NotImplementedError(self._copy_inventory_texts)

    def _copy_text_texts(self):
        raise NotImplementedError(self._copy_text_texts)

    def _create_pack_from_packs(self):
        raise NotImplementedError(self._create_pack_from_packs)

    def _log_copied_texts(self):
        if debug.debug_flag_enabled("pack"):
            mutter(
                "%s: create_pack: file texts copied: %s%s %d items t+%6.3fs",
                time.ctime(),
                self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.text_index.key_count(),
                time.time() - self.new_pack.start_time,
            )

    def _use_pack(self, new_pack):
        """Return True if new_pack should be used.

        :param new_pack: The pack that has just been created.
        :return: True if the pack should be used.
        """
        return new_pack.data_inserted()


class RepositoryPackCollection:
    """Management of packs within a repository.

    :ivar _names: map of {pack_name: (index_size,)}
    """

    pack_factory: type[NewPack]
    resumed_pack_factory: type[ResumedPack]
    normal_packer_class: type[Packer]
    optimising_packer_class: type[Packer]

    def __init__(
        self,
        repo,
        transport,
        index_transport,
        upload_transport,
        pack_transport,
        index_builder_class,
        index_class,
        use_chk_index,
    ):
        """Create a new RepositoryPackCollection.

        :param transport: Addresses the repository base directory
            (typically .bzr/repository/).
        :param index_transport: Addresses the directory containing indices.
        :param upload_transport: Addresses the directory into which packs are written
            while they're being created.
        :param pack_transport: Addresses the directory of existing complete packs.
        :param index_builder_class: The index builder class to use.
        :param index_class: The index class to use.
        :param use_chk_index: Whether to setup and manage a CHK index.
        """
        # XXX: This should call self.reset()
        self.repo = repo
        self.transport = transport
        self._index_transport = _mod_transport.ErrorConvertingTransport(index_transport)
        self._upload_transport = _mod_transport.ErrorConvertingTransport(
            upload_transport
        )
        self._pack_transport = pack_transport
        self._index_builder_class = index_builder_class
        self._index_class = index_class
        self._suffix_offsets = {".rix": 0, ".iix": 1, ".tix": 2, ".six": 3, ".cix": 4}
        self.packs = []
        # name:Pack mapping
        self._names = None
        self._packs_by_name = {}
        # the previous pack-names content
        self._packs_at_load = None
        # when a pack is being created by this object, the state of that pack.
        self._new_pack = None
        # aggregated revision index data
        flush = self._flush_new_pack
        self.revision_index = AggregateIndex(self.reload_pack_names, flush)
        self.inventory_index = AggregateIndex(self.reload_pack_names, flush)
        self.text_index = AggregateIndex(self.reload_pack_names, flush)
        self.signature_index = AggregateIndex(self.reload_pack_names, flush)
        all_indices = [
            self.revision_index,
            self.inventory_index,
            self.text_index,
            self.signature_index,
        ]
        if use_chk_index:
            self.chk_index = AggregateIndex(self.reload_pack_names, flush)
            all_indices.append(self.chk_index)
        else:
            # used to determine if we're using a chk_index elsewhere.
            self.chk_index = None
        # Tell all the CombinedGraphIndex objects about each other, so they can
        # share hints about which pack names to search first.
        all_combined = [agg_idx.combined_index for agg_idx in all_indices]
        for combined_idx in all_combined:
            combined_idx.set_sibling_indices(
                set(all_combined).difference([combined_idx])
            )
        # resumed packs
        self._resumed_packs = []
        self.config_stack = config.LocationStack(self.transport.base)

    def __repr__(self):
        """Return string representation of the pack collection.

        Returns:
            str: String representation including class name and repository.
        """
        return f"{self.__class__.__name__}({self.repo!r})"

    def add_pack_to_memory(self, pack):
        """Make a Pack object available to the repository to satisfy queries.

        :param pack: A Pack object.
        """
        if pack.name in self._packs_by_name:
            raise AssertionError(f"pack {pack.name} already in _packs_by_name")
        self.packs.append(pack)
        self._packs_by_name[pack.name] = pack
        self.revision_index.add_index(pack.revision_index, pack)
        self.inventory_index.add_index(pack.inventory_index, pack)
        self.text_index.add_index(pack.text_index, pack)
        self.signature_index.add_index(pack.signature_index, pack)
        if self.chk_index is not None:
            self.chk_index.add_index(pack.chk_index, pack)

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

        :return: Something evaluating true if packing took place.
        """
        while True:
            try:
                return self._do_autopack()
            except RetryAutopack:
                # If we get a RetryAutopack exception, we should abort the
                # current action, and retry.
                pass

    def _do_autopack(self):
        # XXX: Should not be needed when the management of indices is sane.
        total_revisions = self.revision_index.combined_index.key_count()
        total_packs = len(self._names)
        if self._max_pack_count(total_revisions) >= total_packs:
            return None
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
            existing_packs, pack_distribution
        )
        num_new_packs = len(pack_operations)
        num_old_packs = sum([len(po[1]) for po in pack_operations])
        num_revs_affected = sum([po[0] for po in pack_operations])
        mutter(
            "Auto-packing repository %s, which has %d pack files, "
            "containing %d revisions. Packing %d files into %d affecting %d"
            " revisions",
            str(self),
            total_packs,
            total_revisions,
            num_old_packs,
            num_new_packs,
            num_revs_affected,
        )
        result = self._execute_pack_operations(
            pack_operations,
            packer_class=self.normal_packer_class,
            reload_func=self._restart_autopack,
        )
        mutter("Auto-packing repository %s completed", str(self))
        return result

    def _execute_pack_operations(self, pack_operations, packer_class, reload_func=None):
        """Execute a series of pack operations.

        :param pack_operations: A list of [revision_count, packs_to_combine].
        :param packer_class: The class of packer to use
        :return: The new pack names.
        """
        for _revision_count, packs in pack_operations:
            # we may have no-ops from the setup logic
            if len(packs) == 0:
                continue
            packer = packer_class(self, packs, ".autopack", reload_func=reload_func)
            try:
                result = packer.pack()
            except RetryWithNewPacks:
                # An exception is propagating out of this context, make sure
                # this packer has cleaned up. Packer() doesn't set its new_pack
                # state into the RepositoryPackCollection object, so we only
                # have access to it directly here.
                if packer.new_pack is not None:
                    packer.new_pack.abort()
                raise
            if result is None:
                return
            for pack in packs:
                self._remove_pack_from_memory(pack)
        # record the newly available packs and stop advertising the old
        # packs
        to_be_obsoleted = []
        for _, packs in pack_operations:
            to_be_obsoleted.extend(packs)
        result = self._save_pack_names(
            clear_obsolete_packs=True, obsolete_packs=to_be_obsoleted
        )
        return result

    def _flush_new_pack(self):
        if self._new_pack is not None:
            self._new_pack.flush()

    def lock_names(self):
        """Acquire the mutex around the pack-names index.

        This cannot be used in the middle of a read-only transaction on the
        repository.
        """
        self.repo.control_files.lock_write()

    def _already_packed(self):
        """Is the collection already packed?"""
        return not (self.repo._format.pack_compresses or (len(self._names) > 1))

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Pack the pack collection totally."""
        self.ensure_loaded()
        total_packs = len(self._names)
        if self._already_packed():
            return
        total_revisions = self.revision_index.combined_index.key_count()
        # XXX: the following may want to be a class, to pack with a given
        # policy.
        mutter(
            "Packing repository %s, which has %d pack files, "
            "containing %d revisions with hint %r.",
            str(self),
            total_packs,
            total_revisions,
            hint,
        )
        while True:
            try:
                self._try_pack_operations(hint)
            except RetryPackOperations:
                continue
            break

        if clean_obsolete_packs:
            self._clear_obsolete_packs()

    def _try_pack_operations(self, hint):
        """Calculate the pack operations based on the hint (if any), and
        execute them.
        """
        # determine which packs need changing
        pack_operations = [[0, []]]
        for pack in self.all_packs():
            if hint is None or pack.name in hint:
                # Either no hint was provided (so we are packing everything),
                # or this pack was included in the hint.
                pack_operations[-1][0] += pack.get_revision_count()
                pack_operations[-1][1].append(pack)
        self._execute_pack_operations(
            pack_operations,
            packer_class=self.optimising_packer_class,
            reload_func=self._restart_pack_operations,
        )

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
            # take the largest pack, and if it's less than the head of the
            # distribution chart we will include its contents in the new pack
            # for that position. If it's larger, we remove its size from the
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
        # Now that we know which pack files we want to move, shove them all
        # into a single pack file.
        final_rev_count = 0
        final_pack_list = []
        for num_revs, pack_files in pack_operations:
            final_rev_count += num_revs
            final_pack_list.extend(pack_files)
        if len(final_pack_list) == 1:
            raise AssertionError(
                "We somehow generated an autopack with a single pack file being moved."
            )
            return []
        return [[final_rev_count, final_pack_list]]

    def ensure_loaded(self):
        """Ensure we have read names from disk.

        :return: True if the disk names had not been previously read.
        """
        # NB: if you see an assertion error here, it's probably access against
        # an unlocked repo. Naughty.
        if not self.repo.is_locked():
            raise ObjectNotLocked(self.repo)
        if self._names is None:
            self._names = {}
            self._packs_at_load = set()
            for _index, key, value in self._iter_disk_pack_index():
                name = key[0].decode("ascii")
                self._names[name] = self._parse_index_sizes(value)
                self._packs_at_load.add((name, value))
            result = True
        else:
            result = False
        # populate all the metadata.
        self.all_packs()
        return result

    def _parse_index_sizes(self, value):
        """Parse a string of index sizes."""
        return tuple(int(digits) for digits in value.split(b" "))

    def get_pack_by_name(self, name):
        """Get a Pack object by name.

        :param name: The name of the pack - e.g. '123456'
        :return: A Pack object.
        """
        try:
            return self._packs_by_name[name]
        except KeyError:
            rev_index = self._make_index(name, ".rix")
            inv_index = self._make_index(name, ".iix")
            txt_index = self._make_index(name, ".tix")
            sig_index = self._make_index(name, ".six")
            if self.chk_index is not None:
                chk_index = self._make_index(name, ".cix", is_chk=True)
            else:
                chk_index = None
            result = ExistingPack(
                self._pack_transport,
                name,
                rev_index,
                inv_index,
                txt_index,
                sig_index,
                chk_index,
            )
            self.add_pack_to_memory(result)
            return result

    def _resume_pack(self, name):
        """Get a suspended Pack object by name.

        :param name: The name of the pack - e.g. '123456'
        :return: A Pack object.
        """
        if not re.match("[a-f0-9]{32}", name):
            # Tokens should be md5sums of the suspended pack file, i.e. 32 hex
            # digits.
            raise errors.UnresumableWriteGroup(
                self.repo, [name], "Malformed write group token"
            )
        try:
            rev_index = self._make_index(name, ".rix", resume=True)
            inv_index = self._make_index(name, ".iix", resume=True)
            txt_index = self._make_index(name, ".tix", resume=True)
            sig_index = self._make_index(name, ".six", resume=True)
            if self.chk_index is not None:
                chk_index = self._make_index(name, ".cix", resume=True, is_chk=True)
            else:
                chk_index = None
            result = self.resumed_pack_factory(
                name,
                rev_index,
                inv_index,
                txt_index,
                sig_index,
                self._upload_transport,
                self._pack_transport,
                self._index_transport,
                self,
                chk_index=chk_index,
            )
        except _mod_transport.NoSuchFile as e:
            raise errors.UnresumableWriteGroup(self.repo, [name], str(e)) from e
        self.add_pack_to_memory(result)
        self._resumed_packs.append(result)
        return result

    def allocate(self, a_new_pack):
        """Allocate name in the list of packs.

        :param a_new_pack: A NewPack instance to be added to the collection of
            packs for this repository.
        """
        self.ensure_loaded()
        if a_new_pack.name in self._names:
            raise errors.BzrError(f"Pack {a_new_pack.name!r} already exists in {self}")
        self._names[a_new_pack.name] = tuple(a_new_pack.index_sizes)
        self.add_pack_to_memory(a_new_pack)

    def _iter_disk_pack_index(self):
        """Iterate over the contents of the pack-names index.

        This is used when loading the list from disk, and before writing to
        detect updates from others during our write operation.
        :return: An iterator of the index contents.
        """
        return self._index_class(self.transport, "pack-names", None).iter_all_entries()

    def _make_index(self, name, suffix, resume=False, is_chk=False):
        size_offset = self._suffix_offsets[suffix]
        index_name = name + suffix
        if resume:
            transport = self._upload_transport
            index_size = transport.stat(index_name).st_size
        else:
            transport = self._index_transport
            index_size = self._names[name][size_offset]
        index = self._index_class(
            transport, index_name, index_size, unlimited_cache=is_chk
        )
        if is_chk and self._index_class is btree_index.BTreeGraphIndex:
            index._leaf_factory = btree_index._gcchk_factory
        return index

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
            try:
                try:
                    pack.pack_transport.move(
                        pack.file_name(), "../obsolete_packs/" + pack.file_name()
                    )
                except _mod_transport.NoSuchFile:
                    # perhaps obsolete_packs was removed? Let's create it and
                    # try again
                    with contextlib.suppress(_mod_transport.FileExists):
                        pack.pack_transport.mkdir("../obsolete_packs/")
                    pack.pack_transport.move(
                        pack.file_name(), "../obsolete_packs/" + pack.file_name()
                    )
            except (errors.PathError, errors.TransportError) as e:
                # TODO: Should these be warnings or mutters?
                mutter(f"couldn't rename obsolete pack, skipping it:\n{e}")
            # TODO: Probably needs to know all possible indices for this pack
            # - or maybe list the directory and move all indices matching this
            # name whether we recognize it or not?
            suffixes = [".iix", ".six", ".tix", ".rix"]
            if self.chk_index is not None:
                suffixes.append(".cix")
            for suffix in suffixes:
                try:
                    self._index_transport.move(
                        pack.name + suffix, "../obsolete_packs/" + pack.name + suffix
                    )
                except (errors.PathError, errors.TransportError) as e:
                    mutter(f"couldn't rename obsolete index, skipping it:\n{e}")

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
            size = 10**exponent
            for _pos in range(int(count)):
                result.append(size)
        return list(reversed(result))

    def _pack_tuple(self, name):
        """Return a tuple with the transport and file name for a pack name."""
        return self._pack_transport, name + ".pack"

    def _remove_pack_from_memory(self, pack):
        """Remove pack from the packs accessed by this repository.

        Only affects memory state, until self._save_pack_names() is invoked.
        """
        self._names.pop(pack.name)
        self._packs_by_name.pop(pack.name)
        self._remove_pack_indices(pack)
        self.packs.remove(pack)

    def _remove_pack_indices(self, pack, ignore_missing=False):
        """Remove the indices for pack from the aggregated indices.

        :param ignore_missing: Suppress KeyErrors from calling remove_index.
        """
        for index_type in Pack.index_definitions:
            attr_name = index_type + "_index"
            aggregate_index = getattr(self, attr_name)
            if aggregate_index is not None:
                pack_index = getattr(pack, attr_name)
                try:
                    aggregate_index.remove_index(pack_index)
                except KeyError:
                    if ignore_missing:
                        continue
                    raise

    def reset(self):
        """Clear all cached data."""
        # cached revision data
        self.revision_index.clear()
        # cached signature data
        self.signature_index.clear()
        # cached file text data
        self.text_index.clear()
        # cached inventory data
        self.inventory_index.clear()
        # cached chk data
        if self.chk_index is not None:
            self.chk_index.clear()
        # remove the open pack
        self._new_pack = None
        # information about packs.
        self._names = None
        self.packs = []
        self._packs_by_name = {}
        self._packs_at_load = None

    def _unlock_names(self):
        """Release the mutex around the pack-names index."""
        self.repo.control_files.unlock()

    def _diff_pack_names(self):
        """Read the pack names from disk, and compare it to the one in memory.

        :return: (disk_nodes, deleted_nodes, new_nodes)
            disk_nodes    The final set of nodes that should be referenced
            deleted_nodes Nodes which have been removed from when we started
            new_nodes     Nodes that are newly introduced
        """
        # load the disk nodes across
        disk_nodes = set()
        for _index, key, value in self._iter_disk_pack_index():
            disk_nodes.add((key[0].decode("ascii"), value))
        orig_disk_nodes = set(disk_nodes)

        # do a two-way diff against our original content
        current_nodes = set()
        for name, sizes in self._names.items():
            current_nodes.add((name, b" ".join(b"%d" % size for size in sizes)))

        # Packs no longer present in the repository, which were present when we
        # locked the repository
        deleted_nodes = self._packs_at_load - current_nodes
        # Packs which this process is adding
        new_nodes = current_nodes - self._packs_at_load

        # Update the disk_nodes set to include the ones we are adding, and
        # remove the ones which were removed by someone else
        disk_nodes.difference_update(deleted_nodes)
        disk_nodes.update(new_nodes)

        return disk_nodes, deleted_nodes, new_nodes, orig_disk_nodes

    def _syncronize_pack_names_from_disk_nodes(self, disk_nodes):
        """Given the correct set of pack files, update our saved info.

        :return: (removed, added, modified)
            removed     pack names removed from self._names
            added       pack names added to self._names
            modified    pack names that had changed value
        """
        removed = []
        added = []
        modified = []
        ## self._packs_at_load = disk_nodes
        new_names = dict(disk_nodes)
        # drop no longer present nodes
        for pack in self.all_packs():
            if pack.name not in new_names:
                removed.append(pack.name)
                self._remove_pack_from_memory(pack)
        # add new nodes/refresh existing ones
        for name, value in disk_nodes:
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
                    # assume it's broken. RBC 20071017.
                    self._remove_pack_from_memory(self.get_pack_by_name(name))
                    self._names[name] = sizes
                    self.get_pack_by_name(name)
                    modified.append(name)
            else:
                # new
                self._names[name] = sizes
                self.get_pack_by_name(name)
                added.append(name)
        return removed, added, modified

    def _save_pack_names(self, clear_obsolete_packs=False, obsolete_packs=None):
        """Save the list of packs.

        This will take out the mutex around the pack names list for the
        duration of the method call. If concurrent updates have been made, a
        three-way merge between the current list and the current in memory list
        is performed.

        :param clear_obsolete_packs: If True, clear out the contents of the
            obsolete_packs directory.
        :param obsolete_packs: Packs that are obsolete once the new pack-names
            file has been written.
        :return: A list of the names saved that were not previously on disk.
        """
        already_obsolete = []
        self.lock_names()
        try:
            builder = self._index_builder_class()
            (
                disk_nodes,
                _deleted_nodes,
                new_nodes,
                _orig_disk_nodes,
            ) = self._diff_pack_names()
            # TODO: handle same-name, index-size-changes here -
            # e.g. use the value from disk, not ours, *unless* we're the one
            # changing it.
            for name, value in disk_nodes:
                builder.add_node((name.encode("ascii"),), value)
            self.transport.put_file(
                "pack-names",
                builder.finish(),
                mode=self.repo.controldir._get_file_mode(),
            )
            self._packs_at_load = disk_nodes
            if clear_obsolete_packs:
                to_preserve = None
                if obsolete_packs:
                    to_preserve = {o.name for o in obsolete_packs}
                already_obsolete = self._clear_obsolete_packs(to_preserve)
        finally:
            self._unlock_names()
        # synchronise the memory packs list with what we just wrote:
        self._syncronize_pack_names_from_disk_nodes(disk_nodes)
        if obsolete_packs:
            # TODO: We could add one more condition here. "if o.name not in
            #       orig_disk_nodes and o != the new_pack we haven't written to
            #       disk yet. However, the new pack object is not easily
            #       accessible here (it would have to be passed through the
            #       autopacking code, etc.)
            obsolete_packs = [
                o for o in obsolete_packs if o.name not in already_obsolete
            ]
            self._obsolete_packs(obsolete_packs)
        return [new_node[0] for new_node in new_nodes]

    def reload_pack_names(self):
        """Sync our pack listing with what is present in the repository.

        This should be called when we find out that something we thought was
        present is now missing. This happens when another process re-packs the
        repository, etc.

        :return: True if the in-memory list of packs has been altered at all.
        """
        # The ensure_loaded call is to handle the case where the first call
        # made involving the collection was to reload_pack_names, where we
        # don't have a view of disk contents. It's a bit of a bandaid, and
        # causes two reads of pack-names, but it's a rare corner case not
        # struck with regular push/pull etc.
        first_read = self.ensure_loaded()
        if first_read:
            return True
        # out the new value.
        (
            disk_nodes,
            _deleted_nodes,
            _new_nodes,
            orig_disk_nodes,
        ) = self._diff_pack_names()
        # _packs_at_load is meant to be the explicit list of names in
        # 'pack-names' at then start. As such, it should not contain any
        # pending names that haven't been written out yet.
        self._packs_at_load = orig_disk_nodes
        (removed, added, modified) = self._syncronize_pack_names_from_disk_nodes(
            disk_nodes
        )
        return bool(removed or added or modified)

    def _restart_autopack(self):
        """Reload the pack names list, and restart the autopack code."""
        if not self.reload_pack_names():
            # Re-raise the original exception, because something went missing
            # and a restart didn't find it
            raise
        raise RetryAutopack(self.repo, False, sys.exc_info())

    def _restart_pack_operations(self):
        """Reload the pack names list, and restart the autopack code."""
        if not self.reload_pack_names():
            # Re-raise the original exception, because something went missing
            # and a restart didn't find it
            raise
        raise RetryPackOperations(self.repo, False, sys.exc_info())

    def _clear_obsolete_packs(self, preserve=None):
        """Delete everything from the obsolete-packs directory.

        :return: A list of pack identifiers (the filename without '.pack') that
            were found in obsolete_packs.
        """
        found = []
        obsolete_pack_transport = self.transport.clone("obsolete_packs")
        if preserve is None:
            preserve = set()
        try:
            obsolete_pack_files = obsolete_pack_transport.list_dir(".")
        except _mod_transport.NoSuchFile:
            return found
        for filename in obsolete_pack_files:
            name, ext = osutils.splitext(filename)
            if ext == ".pack":
                found.append(name)
            if name in preserve:
                continue
            try:
                obsolete_pack_transport.delete(filename)
            except (errors.PathError, errors.TransportError) as e:
                warning(f"couldn't delete obsolete pack, skipping it:\n{e}")
        return found

    def _start_write_group(self):
        # Do not permit preparation for writing if we're not in a 'write lock'.
        if not self.repo.is_write_locked():
            raise errors.NotWriteLocked(self)
        self._new_pack = self.pack_factory(
            self, upload_suffix=".pack", file_mode=self.repo.controldir._get_file_mode()
        )
        # allow writing: queue writes to a new index
        self.revision_index.add_writable_index(
            self._new_pack.revision_index, self._new_pack
        )
        self.inventory_index.add_writable_index(
            self._new_pack.inventory_index, self._new_pack
        )
        self.text_index.add_writable_index(self._new_pack.text_index, self._new_pack)
        self._new_pack.text_index.set_optimize(combine_backing_indices=False)
        self.signature_index.add_writable_index(
            self._new_pack.signature_index, self._new_pack
        )
        if self.chk_index is not None:
            self.chk_index.add_writable_index(self._new_pack.chk_index, self._new_pack)
            self.repo.chk_bytes._index._add_callback = self.chk_index.add_callback
            self._new_pack.chk_index.set_optimize(combine_backing_indices=False)

        self.repo.inventories._index._add_callback = self.inventory_index.add_callback
        self.repo.revisions._index._add_callback = self.revision_index.add_callback
        self.repo.signatures._index._add_callback = self.signature_index.add_callback
        self.repo.texts._index._add_callback = self.text_index.add_callback

    def _abort_write_group(self):
        # FIXME: just drop the transient index.
        # forget what names there are
        if self._new_pack is not None:
            with contextlib.ExitStack() as stack:
                stack.callback(setattr, self, "_new_pack", None)
                # If we aborted while in the middle of finishing the write
                # group, _remove_pack_indices could fail because the indexes are
                # already gone.  But they're not there we shouldn't fail in this
                # case, so we pass ignore_missing=True.
                stack.callback(
                    self._remove_pack_indices, self._new_pack, ignore_missing=True
                )
                self._new_pack.abort()
        for resumed_pack in self._resumed_packs:
            with contextlib.ExitStack() as stack:
                # See comment in previous finally block.
                stack.callback(
                    self._remove_pack_indices, resumed_pack, ignore_missing=True
                )
                resumed_pack.abort()
        del self._resumed_packs[:]

    def _remove_resumed_pack_indices(self):
        for resumed_pack in self._resumed_packs:
            self._remove_pack_indices(resumed_pack)
        del self._resumed_packs[:]

    def _check_new_inventories(self):
        """Detect missing inventories in this write group.

        :returns: list of strs, summarising any problems found.  If the list is
            empty no problems were found.
        """
        # The base implementation does no checks.  GCRepositoryPackCollection
        # overrides this.
        return []

    def _commit_write_group(self):
        all_missing = set()
        for prefix, versioned_file in (
            ("revisions", self.repo.revisions),
            ("inventories", self.repo.inventories),
            ("texts", self.repo.texts),
            ("signatures", self.repo.signatures),
        ):
            missing = versioned_file.get_missing_compression_parent_keys()
            all_missing.update([(prefix,) + key for key in missing])
        if all_missing:
            raise BzrCheckError(
                "Repository {} has missing compression parent(s) {!r} ".format(
                    self.repo, sorted(all_missing)
                )
            )
        problems = self._check_new_inventories()
        if problems:
            problems_summary = "\n".join(problems)
            raise BzrCheckError(
                "Cannot add revision(s) to repository: " + problems_summary
            )
        self._remove_pack_indices(self._new_pack)
        any_new_content = False
        if self._new_pack.data_inserted():
            # get all the data to disk and read to use
            self._new_pack.finish()
            self.allocate(self._new_pack)
            self._new_pack = None
            any_new_content = True
        else:
            self._new_pack.abort()
            self._new_pack = None
        for resumed_pack in self._resumed_packs:
            # XXX: this is a pretty ugly way to turn the resumed pack into a
            # properly committed pack.
            self._names[resumed_pack.name] = None
            self._remove_pack_from_memory(resumed_pack)
            resumed_pack.finish()
            self.allocate(resumed_pack)
            any_new_content = True
        del self._resumed_packs[:]
        if any_new_content:
            result = self.autopack()
            if not result:
                # when autopack takes no steps, the names list is still
                # unsaved.
                return self._save_pack_names()
            return result
        return []

    def _suspend_write_group(self):
        tokens = [pack.name for pack in self._resumed_packs]
        self._remove_pack_indices(self._new_pack)
        if self._new_pack.data_inserted():
            # get all the data to disk and read to use
            self._new_pack.finish(suspend=True)
            tokens.append(self._new_pack.name)
            self._new_pack = None
        else:
            self._new_pack.abort()
            self._new_pack = None
        self._remove_resumed_pack_indices()
        return tokens

    def _resume_write_group(self, tokens):
        for token in tokens:
            self._resume_pack(token)


class PackRepository(MetaDirVersionedFileRepository):
    """Repository with knit objects stored inside pack containers.

    The layering for a KnitPackRepository is:

    Graph        |  HPSS    | Repository public layer |
    ===================================================
    Tuple based apis below, string based, and key based apis above
    ---------------------------------------------------
    VersionedFiles
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

    # These attributes are inherited from the Repository base class. Setting
    # them to None ensures that if the constructor is changed to not initialize
    # them, or a subclass fails to call the constructor, that an error will
    # occur rather than the system working but generating incorrect data.
    _commit_builder_class: type[VersionedFileCommitBuilder]
    _inventory_serializer: InventorySerializer
    _revision_serializer: RevisionSerializer

    def __init__(
        self,
        _format,
        a_controldir,
        control_files,
        _commit_builder_class,
        _inventory_serializer,
        _revision_serializer,
    ):
        """Initialize a PackRepository.

        Args:
            _format: The repository format.
            a_controldir: The control directory containing this repository.
            control_files: LockableFiles instance for repository control files.
            _commit_builder_class: Class to use for commit builders.
            _revision_serializer: Serializer for revision objects.
            _inventory_serializer: Serializer for inventory objects.
        """
        MetaDirRepository.__init__(self, _format, a_controldir, control_files)
        self._commit_builder_class = _commit_builder_class
        self._inventory_serializer = _inventory_serializer
        self._revision_serializer = _revision_serializer
        self._reconcile_fixes_text_parents = True
        if self._format.supports_external_lookups:
            self._unstacked_provider = _vcsgraph.CachingParentsProvider(
                self._make_parents_provider_unstacked()
            )
        else:
            self._unstacked_provider = _vcsgraph.CachingParentsProvider(self)
        self._unstacked_provider.disable_cache()

    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        with self.lock_read():
            return [key[0] for key in self.revisions.keys()]

    def _abort_write_group(self):
        self.revisions._index._key_dependencies.clear()
        self._pack_collection._abort_write_group()

    def _make_parents_provider(self):
        if not self._format.supports_external_lookups:
            return self._unstacked_provider
        return _vcsgraph.StackedParentsProvider(
            _LazyListJoin([self._unstacked_provider], self._fallback_repositories)
        )

    def _refresh_data(self):
        if not self.is_locked():
            return
        self._pack_collection.reload_pack_names()
        self._unstacked_provider.disable_cache()
        self._unstacked_provider.enable_cache()

    def _start_write_group(self):
        self._pack_collection._start_write_group()

    def _commit_write_group(self):
        hint = self._pack_collection._commit_write_group()
        self.revisions._index._key_dependencies.clear()
        # The commit may have added keys that were previously cached as
        # missing, so reset the cache.
        self._unstacked_provider.disable_cache()
        self._unstacked_provider.enable_cache()
        return hint

    def suspend_write_group(self):
        """Suspend the current write group and return resume tokens.

        Returns:
            list: Tokens that can be used to resume the write group later.
        """
        # XXX check self._write_group is self.get_transaction()?
        tokens = self._pack_collection._suspend_write_group()
        self.revisions._index._key_dependencies.clear()
        self._write_group = None
        return tokens

    def _resume_write_group(self, tokens):
        self._start_write_group()
        try:
            self._pack_collection._resume_write_group(tokens)
        except errors.UnresumableWriteGroup:
            self._abort_write_group()
            raise
        for pack in self._pack_collection._resumed_packs:
            self.revisions._index.scan_unvalidated_index(pack.revision_index)

    def get_transaction(self):
        """Get the current transaction for this repository.

        Returns:
            Transaction: The current transaction, either write or read-only.
        """
        if self._write_lock_count:
            return self._transaction
        else:
            return self.control_files.get_transaction()

    def is_locked(self):
        """Check if the repository is locked.

        Returns:
            bool: True if the repository is locked for reading or writing.
        """
        return self._write_lock_count or self.control_files.is_locked()

    def is_write_locked(self):
        """Check if the repository is write-locked.

        Returns:
            bool: True if the repository is locked for writing.
        """
        return self._write_lock_count

    def lock_write(self, token=None):
        """Lock the repository for writes.

        :return: A breezy.repository.RepositoryWriteLockResult.
        """
        locked = self.is_locked()
        if not self._write_lock_count and locked:
            raise errors.ReadOnlyError(self)
        self._write_lock_count += 1
        if self._write_lock_count == 1:
            self._transaction = transactions.WriteTransaction()
        if not locked:
            if debug.debug_flag_enabled("relock") and self._prev_lock == "w":
                note("%r was write locked again", self)
            self._prev_lock = "w"
            self._unstacked_provider.enable_cache()
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
            self._refresh_data()
        return RepositoryWriteLockResult(self.unlock, None)

    def lock_read(self):
        """Lock the repository for reads.

        :return: A breezy.lock.LogicalLockResult.
        """
        locked = self.is_locked()
        if self._write_lock_count:
            self._write_lock_count += 1
        else:
            self.control_files.lock_read()
        if not locked:
            if debug.debug_flag_enabled("relock") and self._prev_lock == "r":
                note("%r was read locked again", self)
            self._prev_lock = "r"
            self._unstacked_provider.enable_cache()
            for repo in self._fallback_repositories:
                repo.lock_read()
            self._refresh_data()
        return LogicalLockResult(self.unlock)

    def leave_lock_in_place(self):
        """Leave the lock in place when unlocking.

        This operation is not supported for pack repositories.

        Raises:
            NotImplementedError: Always, as this operation is not supported.
        """
        # not supported - raise an error
        raise NotImplementedError(self.leave_lock_in_place)

    def dont_leave_lock_in_place(self):
        """Don't leave the lock in place when unlocking.

        This operation is not supported for pack repositories.

        Raises:
            NotImplementedError: Always, as this operation is not supported.
        """
        # not supported - raise an error
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Compress the data within the repository.

        This will pack all the data to a single pack. In future it may
        recompress deltas or do other such expensive operations.
        """
        with self.lock_write():
            self._pack_collection.pack(
                hint=hint, clean_obsolete_packs=clean_obsolete_packs
            )

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from .reconcile import PackReconciler

        with self.lock_write():
            reconciler = PackReconciler(self, thorough=thorough)
            return reconciler.reconcile()

    def _reconcile_pack(self, collection, packs, extension, revs, pb):
        raise NotImplementedError(self._reconcile_pack)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        """Unlock the repository.

        Decrements the lock count and releases locks when count reaches zero.
        If a write group is still active when trying to release a write lock,
        raises an error.

        Raises:
            BzrError: If trying to unlock while a write group is active.
            LockNotHeld: If the repository is not locked.
            LockBroken: If the lock has been broken.
        """
        if self._write_lock_count == 1 and self._write_group is not None:
            self.abort_write_group()
            self._unstacked_provider.disable_cache()
            self._transaction = None
            self._write_lock_count = 0
            raise errors.BzrError(
                f"Must end write group before releasing write lock on {self}"
            )
        if self._write_lock_count:
            self._write_lock_count -= 1
            if not self._write_lock_count:
                transaction = self._transaction
                self._transaction = None
                transaction.finish()
        else:
            self.control_files.unlock()

        if not self.is_locked():
            self._unstacked_provider.disable_cache()
            for repo in self._fallback_repositories:
                repo.unlock()


class RepositoryFormatPack(MetaDirVersionedFileRepositoryFormat):
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
    repository_class: type[PackRepository]
    # Set this attribute in derived classes to control the
    # _commit_builder_class that the repository objects will have passed to
    # their constructor.
    _commit_builder_class: type[VersionedFileCommitBuilder]
    # Set these attributes in derived clases to control the serializers that
    # the repository objects will have passed to their constructor.
    _inventory_serializer: InventorySerializer
    _revision_serializer: RevisionSerializer
    # Packs are not confused by ghosts.
    supports_ghosts: bool = True
    # External references are not supported in pack repositories yet.
    supports_external_lookups: bool = False
    # Most pack formats do not use chk lookups.
    supports_chks: bool = False
    # What index classes to use
    index_builder_class: type[_mod_index.GraphIndexBuilder]
    index_class: type[object]
    _fetch_uses_deltas: bool = True
    fast_deltas: bool = False
    supports_funky_characters: bool = True
    revision_graph_can_have_wrong_parents: bool = True

    def initialize(self, a_controldir, shared=False):
        """Create a pack based repository.

        :param a_controldir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        mutter("creating repository in %s.", a_controldir.transport.base)
        dirs = ["indices", "obsolete_packs", "packs", "upload"]
        builder = self.index_builder_class()
        files = [("pack-names", builder.finish())]
        utf8_files = [("format", self.get_format_string())]

        self._upload_blank_content(a_controldir, dirs, files, utf8_files, shared)
        repository = self.open(a_controldir=a_controldir, _found=True)
        self._run_post_repo_init_hooks(repository, a_controldir, shared)
        return repository

    def open(self, a_controldir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().

        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            RepositoryFormatMetaDir.find_format(a_controldir)
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_controldir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(
            repo_transport, "lock", lockdir.LockDir
        )
        return self.repository_class(
            _format=self,
            a_controldir=a_controldir,
            control_files=control_files,
            _commit_builder_class=self._commit_builder_class,
            _inventory_serializer=self._inventory_serializer,
            _revision_serializer=self._revision_serializer,
        )


class RetryPackOperations(RetryWithNewPacks):
    """Raised when we are packing and we find a missing file.

    Meant as a signaling exception, to tell the RepositoryPackCollection.pack
    code it should try again.
    """

    internal_error = True

    _fmt = (
        "Pack files have changed, reload and try pack again."
        " context: %(context)s %(orig_error)s"
    )


# _DirectPackAccess is provided by bzrformats.
from bzrformats.pack_repo import _DirectPackAccess

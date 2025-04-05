# Copyright (C) 2008-2011 Canonical Ltd
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

"""Repository formats using CHK inventories and groupcompress compression."""

import hashlib
import time

from .. import _bzr_rs, controldir, debug, errors, osutils, trace, ui
from .. import revision as _mod_revision
from ..bzr import chk_map, chk_serializer, inventory, versionedfile
from ..bzr import index as _mod_index
from ..bzr import pack as _mod_pack
from ..bzr.btree_index import BTreeBuilder, BTreeGraphIndex
from ..bzr.groupcompress import GroupCompressVersionedFiles, _GCGraphIndex
from ..bzr.vf_repository import StreamSource
from .pack_repo import (
    NewPack,
    Pack,
    PackCommitBuilder,
    Packer,
    PackRepository,
    RepositoryFormatPack,
    RepositoryPackCollection,
    ResumedPack,
    _DirectPackAccess,
)


class GCPack(NewPack):
    def __init__(self, pack_collection, upload_suffix="", file_mode=None):
        """Create a NewPack instance.

        :param pack_collection: A PackCollection into which this is being
            inserted.
        :param upload_suffix: An optional suffix to be given to any temporary
            files created during the pack creation. e.g '.autopack'
        :param file_mode: An optional file mode to create the new files with.
        """
        # replaced from NewPack to:
        # - change inventory reference list length to 1
        # - change texts reference lists to 1
        # TODO: patch this to be parameterised

        # The relative locations of the packs are constrained, but all are
        # passed in because the caller has them, so as to avoid object churn.
        index_builder_class = pack_collection._index_builder_class
        # from brisbane-core
        if pack_collection.chk_index is not None:
            chk_index = index_builder_class(reference_lists=0)
        else:
            chk_index = None
        Pack.__init__(
            self,
            # Revisions: parents list, no text compression.
            index_builder_class(reference_lists=1),
            # Inventory: We want to map compression only, but currently the
            # knit code hasn't been updated enough to understand that, so we
            # have a regular 2-list index giving parents and compression
            # source.
            index_builder_class(reference_lists=1),
            # Texts: per file graph, for all fileids - so one reference list
            # and two elements in the key tuple.
            index_builder_class(reference_lists=1, key_elements=2),
            # Signatures: Just blobs to store, no compression, no parents
            # listing.
            index_builder_class(reference_lists=0),
            # CHK based storage - just blobs, no compression or parents.
            chk_index=chk_index,
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
        self._hash = hashlib.md5()  # noqa: S324
        # a four-tuple with the length in bytes of the indices, once the pack
        # is finalised. (rev, inv, text, sigs)
        self.index_sizes = None
        # How much data to cache when writing packs. Note that this is not
        # synchronised with reads, because it's not in the transport layer, so
        # is not safe unless the client knows it won't be reading from the pack
        # under creation.
        self._cache_limit = 0
        # the temporary pack file name.
        self.random_name = osutils.rand_chars(20) + upload_suffix
        # when was this pack started ?
        self.start_time = time.time()
        # open an output stream for the data added to the pack.
        self.write_stream = self.upload_transport.open_write_stream(
            self.random_name, mode=self._file_mode
        )
        if debug.debug_flag_enabled("pack"):
            trace.mutter(
                "%s: create_pack: pack stream open: %s%s t+%6.3fs",
                time.ctime(),
                self.upload_transport.base,
                self.random_name,
                time.time() - self.start_time,
            )
        # A list of byte sequences to be written to the new pack, and the
        # aggregate size of them.  Stored as a list rather than separate
        # variables so that the _write_data closure below can update them.
        self._buffer = [[], 0]
        # create a callable for adding data
        #
        # robertc says- this is a closure rather than a method on the object
        # so that the variables are locals, and faster than accessing object
        # members.

        def _write_data(
            data,
            flush=False,
            _buffer=self._buffer,
            _write=self.write_stream.write,
            _update=self._hash.update,
        ):
            _buffer[0].append(data)
            _buffer[1] += len(data)
            # buffer cap
            if _buffer[1] > self._cache_limit or flush:
                data = b"".join(_buffer[0])
                _write(data)
                _update(data)
                _buffer[:] = [[], 0]

        # expose this on self, for the occasion when clients want to add data.
        self._write_data = _write_data
        # a pack writer object to serialise pack records.
        self._writer = _mod_pack.ContainerWriter(self._write_data)
        self._writer.begin()
        # what state is the pack in? (open, finished, aborted)
        self._state = "open"
        # no name until we finish writing the content
        self.name = None

    def _check_references(self):
        """Make sure our external references are present.

        Packs are allowed to have deltas whose base is not in the pack, but it
        must be present somewhere in this collection.  It is not allowed to
        have deltas based on a fallback repository.
        (See <https://bugs.launchpad.net/bzr/+bug/288751>)
        """
        # Groupcompress packs don't have any external references, arguably CHK
        # pages have external references, but we cannot 'cheaply' determine
        # them without actually walking all of the chk pages.


class ResumedGCPack(ResumedPack):
    def _check_references(self):
        """Make sure our external compression parents are present."""
        # See GCPack._check_references for why this is empty

    def _get_external_refs(self, index):
        # GC repositories don't have compression parents external to a given
        # pack file
        return set()


class GCCHKPacker(Packer):
    """This class understand what it takes to collect a GCCHK repo."""

    def __init__(
        self, pack_collection, packs, suffix, revision_ids=None, reload_func=None
    ):
        super().__init__(
            pack_collection,
            packs,
            suffix,
            revision_ids=revision_ids,
            reload_func=reload_func,
        )
        self._pack_collection = pack_collection
        # ATM, We only support this for GCCHK repositories
        if pack_collection.chk_index is None:
            raise AssertionError("pack_collection.chk_index should not be None")
        self._gather_text_refs = False
        self._chk_id_roots = []
        self._chk_p_id_roots = []
        self._text_refs = None
        # set by .pack() if self.revision_ids is not None
        self.revision_keys = None

    def _get_progress_stream(self, source_vf, keys, message, pb):
        def pb_stream():
            substream = source_vf.get_record_stream(keys, "groupcompress", True)
            for idx, record in enumerate(substream):
                if pb is not None:
                    pb.update(message, idx + 1, len(keys))
                yield record

        return pb_stream()

    def _get_filtered_inv_stream(self, source_vf, keys, message, pb=None):
        """Filter the texts of inventories, to find the chk pages."""
        total_keys = len(keys)

        def _filtered_inv_stream():
            id_roots_set = set()
            p_id_roots_set = set()
            stream = source_vf.get_record_stream(keys, "groupcompress", True)
            for idx, record in enumerate(stream):
                # Inventories should always be with revisions; assume success.
                lines = record.get_bytes_as("lines")
                chk_inv = inventory.CHKInventory.deserialise(None, lines, record.key)
                if pb is not None:
                    pb.update("inv", idx, total_keys)
                key = chk_inv.id_to_entry.key()
                if key not in id_roots_set:
                    self._chk_id_roots.append(key)
                    id_roots_set.add(key)
                p_id_map = chk_inv.parent_id_basename_to_file_id
                if p_id_map is None:
                    raise AssertionError("Parent id -> file_id map not set")
                key = p_id_map.key()
                if key not in p_id_roots_set:
                    p_id_roots_set.add(key)
                    self._chk_p_id_roots.append(key)
                yield record
            # We have finished processing all of the inventory records, we
            # don't need these sets anymore
            id_roots_set.clear()
            p_id_roots_set.clear()

        return _filtered_inv_stream()

    def _get_chk_streams(self, source_vf, keys, pb=None):
        # We want to stream the keys from 'id_roots', and things they
        # reference, and then stream things from p_id_roots and things they
        # reference, and then any remaining keys that we didn't get to.

        # We also group referenced texts together, so if one root references a
        # text with prefix 'a', and another root references a node with prefix
        # 'a', we want to yield those nodes before we yield the nodes for 'b'
        # This keeps 'similar' nodes together.

        # Note: We probably actually want multiple streams here, to help the
        #       client understand that the different levels won't compress well
        #       against each other.
        #       Test the difference between using one Group per level, and
        #       using 1 Group per prefix. (so '' (root) would get a group, then
        #       all the references to search-key 'a' would get a group, etc.)
        total_keys = len(keys)
        remaining_keys = set(keys)
        counter = [0]
        if self._gather_text_refs:
            self._text_refs = set()

        def _get_referenced_stream(root_keys, parse_leaf_nodes=False):
            cur_keys = root_keys
            while cur_keys:
                keys_by_search_prefix = {}
                remaining_keys.difference_update(cur_keys)
                next_keys = set()

                def handle_internal_node(node):
                    for prefix, value in node._items.items():
                        # We don't want to request the same key twice, and we
                        # want to order it by the first time it is seen.
                        # Even further, we don't want to request a key which is
                        # not in this group of pack files (it should be in the
                        # repo, but it doesn't have to be in the group being
                        # packed.)
                        # TODO: consider how to treat externally referenced chk
                        #       pages as 'external_references' so that we
                        #       always fill them in for stacked branches
                        if value not in next_keys and value in remaining_keys:  # noqa: B023
                            keys_by_search_prefix.setdefault(  # noqa: B023
                                prefix,
                                [],
                            ).append(value)
                            next_keys.add(value)  # noqa: B023

                def handle_leaf_node(node):
                    # Store is None, because we know we have a LeafNode, and we
                    # just want its entries
                    for _file_id, bytes in node.iteritems(None):
                        self._text_refs.add(chk_map._bytes_to_text_key(bytes))

                def next_stream():
                    stream = source_vf.get_record_stream(
                        cur_keys,  # noqa: B023
                        "as-requested",
                        True,
                    )
                    for record in stream:
                        if record.storage_kind == "absent":
                            # An absent CHK record: we assume that the missing
                            # record is in a different pack - e.g. a page not
                            # altered by the commit we're packing.
                            continue
                        bytes = record.get_bytes_as("fulltext")
                        # We don't care about search_key_func for this code,
                        # because we only care about external references.
                        node = chk_map._deserialise(
                            bytes, record.key, search_key_func=None
                        )
                        if isinstance(node, chk_map.InternalNode):
                            handle_internal_node(node)
                        elif parse_leaf_nodes:
                            handle_leaf_node(node)
                        counter[0] += 1
                        if pb is not None:
                            pb.update("chk node", counter[0], total_keys)
                        yield record

                yield next_stream()
                # Double check that we won't be emitting any keys twice
                # If we get rid of the pre-calculation of all keys, we could
                # turn this around and do
                # next_keys.difference_update(seen_keys)
                # However, we also may have references to chk pages in another
                # pack file during autopack. We filter earlier, so we should no
                # longer need to do this
                # next_keys = next_keys.intersection(remaining_keys)
                cur_keys = []
                for prefix in sorted(keys_by_search_prefix):
                    cur_keys.extend(keys_by_search_prefix.pop(prefix))

        for stream in _get_referenced_stream(
            self._chk_id_roots, self._gather_text_refs
        ):
            yield stream
        del self._chk_id_roots
        # while it isn't really possible for chk_id_roots to not be in the
        # local group of packs, it is possible that the tree shape has not
        # changed recently, so we need to filter _chk_p_id_roots by the
        # available keys
        chk_p_id_roots = [key for key in self._chk_p_id_roots if key in remaining_keys]
        del self._chk_p_id_roots
        for stream in _get_referenced_stream(chk_p_id_roots, False):
            yield stream
        if remaining_keys:
            trace.mutter(
                "There were %d keys in the chk index, %d of which were not referenced",
                total_keys,
                len(remaining_keys),
            )
            if self.revision_ids is None:
                stream = source_vf.get_record_stream(remaining_keys, "unordered", True)
                yield stream

    def _build_vf(self, index_name, parents, delta, for_write=False):
        """Build a VersionedFiles instance on top of this group of packs."""
        index_name = index_name + "_index"
        index_to_pack = {}
        access = _DirectPackAccess(index_to_pack, reload_func=self._reload_func)
        if for_write:
            # Use new_pack
            if self.new_pack is None:
                raise AssertionError("No new pack has been set")
            index = getattr(self.new_pack, index_name)
            index_to_pack[index] = self.new_pack.access_tuple()
            index.set_optimize(for_size=True)
            access.set_writer(
                self.new_pack._writer, index, self.new_pack.access_tuple()
            )
            add_callback = index.add_nodes
        else:
            indices = []
            for pack in self.packs:
                sub_index = getattr(pack, index_name)
                index_to_pack[sub_index] = pack.access_tuple()
                indices.append(sub_index)
            index = _mod_index.CombinedGraphIndex(indices)
            add_callback = None
        vf = GroupCompressVersionedFiles(
            _GCGraphIndex(
                index,
                add_callback=add_callback,
                parents=parents,
                is_locked=self._pack_collection.repo.is_locked,
            ),
            access=access,
            delta=delta,
        )
        return vf

    def _build_vfs(self, index_name, parents, delta):
        """Build the source and target VersionedFiles."""
        source_vf = self._build_vf(index_name, parents, delta, for_write=False)
        target_vf = self._build_vf(index_name, parents, delta, for_write=True)
        return source_vf, target_vf

    def _copy_stream(
        self, source_vf, target_vf, keys, message, vf_to_stream, pb_offset
    ):
        trace.mutter("repacking %d %s", len(keys), message)
        self.pb.update(f"repacking {message}", pb_offset)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            stream = vf_to_stream(source_vf, keys, message, child_pb)
            for _, _ in target_vf._insert_record_stream(
                stream, random_id=True, reuse_blocks=False
            ):
                pass

    def _copy_revision_texts(self):
        source_vf, target_vf = self._build_vfs("revision", True, False)
        if not self.revision_keys:
            # We are doing a full fetch, aka 'pack'
            self.revision_keys = source_vf.keys()
        self._copy_stream(
            source_vf,
            target_vf,
            self.revision_keys,
            "revisions",
            self._get_progress_stream,
            1,
        )

    def _copy_inventory_texts(self):
        source_vf, target_vf = self._build_vfs("inventory", True, True)
        # It is not sufficient to just use self.revision_keys, as stacked
        # repositories can have more inventories than they have revisions.
        # One alternative would be to do something with
        # get_parent_map(self.revision_keys), but that shouldn't be any faster
        # than this.
        inventory_keys = source_vf.keys()
        missing_inventories = set(self.revision_keys).difference(inventory_keys)
        if missing_inventories:
            # Go back to the original repo, to see if these are really missing
            # https://bugs.launchpad.net/bzr/+bug/437003
            # If we are packing a subset of the repo, it is fine to just have
            # the data in another Pack file, which is not included in this pack
            # operation.
            inv_index = self._pack_collection.repo.inventories._index
            pmap = inv_index.get_parent_map(missing_inventories)
            really_missing = missing_inventories.difference(pmap)
            if really_missing:
                missing_inventories = sorted(really_missing)
                raise ValueError(
                    f"We are missing inventories for revisions: {missing_inventories}"
                )
        self._copy_stream(
            source_vf,
            target_vf,
            inventory_keys,
            "inventories",
            self._get_filtered_inv_stream,
            2,
        )

    def _get_chk_vfs_for_copy(self):
        return self._build_vfs("chk", False, False)

    def _copy_chk_texts(self):
        source_vf, target_vf = self._get_chk_vfs_for_copy()
        # TODO: This is technically spurious... if it is a performance issue,
        #       remove it
        total_keys = source_vf.keys()
        trace.mutter(
            "repacking chk: %d id_to_entry roots, %d p_id_map roots, %d total keys",
            len(self._chk_id_roots),
            len(self._chk_p_id_roots),
            len(total_keys),
        )
        self.pb.update("repacking chk", 3)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for stream in self._get_chk_streams(source_vf, total_keys, pb=child_pb):
                for _, _ in target_vf._insert_record_stream(
                    stream, random_id=True, reuse_blocks=False
                ):
                    pass

    def _copy_text_texts(self):
        source_vf, target_vf = self._build_vfs("text", True, True)
        # XXX: We don't walk the chk map to determine referenced (file_id,
        #      revision_id) keys.  We don't do it yet because you really need
        #      to filter out the ones that are present in the parents of the
        #      rev just before the ones you are copying, otherwise the filter
        #      is grabbing too many keys...
        text_keys = source_vf.keys()
        self._copy_stream(
            source_vf, target_vf, text_keys, "texts", self._get_progress_stream, 4
        )

    def _copy_signature_texts(self):
        source_vf, target_vf = self._build_vfs("signature", False, False)
        signature_keys = source_vf.keys()
        signature_keys.intersection(self.revision_keys)
        self._copy_stream(
            source_vf,
            target_vf,
            signature_keys,
            "signatures",
            self._get_progress_stream,
            5,
        )

    def _create_pack_from_packs(self):
        self.pb.update("repacking", 0, 7)
        self.new_pack = self.open_pack()
        # Is this necessary for GC ?
        self.new_pack.set_write_cache_size(1024 * 1024)
        self._copy_revision_texts()
        self._copy_inventory_texts()
        self._copy_chk_texts()
        self._copy_text_texts()
        self._copy_signature_texts()
        self.new_pack._check_references()
        if not self._use_pack(self.new_pack):
            self.new_pack.abort()
            return None
        self.new_pack.finish_content()
        if len(self.packs) == 1:
            old_pack = self.packs[0]
            if old_pack.name == self.new_pack._hash.hexdigest():
                # The single old pack was already optimally packed.
                trace.mutter(
                    "single pack %s was already optimally packed", old_pack.name
                )
                self.new_pack.abort()
                return None
        self.pb.update("finishing repack", 6, 7)
        self.new_pack.finish()
        self._pack_collection.allocate(self.new_pack)
        return self.new_pack


class GCCHKReconcilePacker(GCCHKPacker):
    """A packer which regenerates indices etc as it copies.

    This is used by ``brz reconcile`` to cause parent text pointers to be
    regenerated.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data_changed = False
        self._gather_text_refs = True

    def _copy_inventory_texts(self):
        source_vf, target_vf = self._build_vfs("inventory", True, True)
        self._copy_stream(
            source_vf,
            target_vf,
            self.revision_keys,
            "inventories",
            self._get_filtered_inv_stream,
            2,
        )
        if source_vf.keys() != self.revision_keys:
            self._data_changed = True

    def _copy_text_texts(self):
        """Generate what texts we should have and then copy."""
        source_vf, target_vf = self._build_vfs("text", True, True)
        trace.mutter("repacking %d texts", len(self._text_refs))
        self.pb.update("repacking texts", 4)
        # we have three major tasks here:
        # 1) generate the ideal index
        repo = self._pack_collection.repo
        # We want the one we just wrote, so base it on self.new_pack
        revision_vf = self._build_vf("revision", True, False, for_write=True)
        ancestor_keys = revision_vf.get_parent_map(revision_vf.keys())
        # Strip keys back into revision_ids.
        ancestors = {
            k[0]: tuple([p[0] for p in parents]) for k, parents in ancestor_keys.items()
        }
        del ancestor_keys
        # TODO: _generate_text_key_index should be much cheaper to generate from
        #       a chk repository, rather than the current implementation
        ideal_index = repo._generate_text_key_index(None, ancestors)
        file_id_parent_map = source_vf.get_parent_map(self._text_refs)
        # 2) generate a keys list that contains all the entries that can
        #    be used as-is, with corrected parents.
        ok_keys = []
        new_parent_keys = {}  # (key, parent_keys)
        discarded_keys = []
        NULL_REVISION = _mod_revision.NULL_REVISION
        for key in self._text_refs:
            # 0 - index
            # 1 - key
            # 2 - value
            # 3 - refs
            try:
                ideal_parents = tuple(ideal_index[key])
            except KeyError:
                discarded_keys.append(key)
                self._data_changed = True
            else:
                if ideal_parents == (NULL_REVISION,):
                    ideal_parents = ()
                source_parents = file_id_parent_map[key]
                if ideal_parents == source_parents:
                    # no change needed.
                    ok_keys.append(key)
                else:
                    # We need to change the parent graph, but we don't need to
                    # re-insert the text (since we don't pun the compression
                    # parent with the parents list)
                    self._data_changed = True
                    new_parent_keys[key] = ideal_parents
        # we're finished with some data.
        del ideal_index
        del file_id_parent_map
        # 3) bulk copy the data, updating records than need it

        def _update_parents_for_texts():
            stream = source_vf.get_record_stream(
                self._text_refs, "groupcompress", False
            )
            for record in stream:
                if record.key in new_parent_keys:
                    record.parents = new_parent_keys[record.key]
                yield record

        target_vf.insert_record_stream(_update_parents_for_texts())

    def _use_pack(self, new_pack):
        """Override _use_pack to check for reconcile having changed content."""
        return new_pack.data_inserted() and self._data_changed


class GCCHKCanonicalizingPacker(GCCHKPacker):
    """A packer that ensures inventories have canonical-form CHK maps.

    Ideally this would be part of reconcile, but it's very slow and rarely
    needed.  (It repairs repositories affected by
    https://bugs.launchpad.net/bzr/+bug/522637).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data_changed = False

    def _exhaust_stream(self, source_vf, keys, message, vf_to_stream, pb_offset):
        """Create and exhaust a stream, but don't insert it.

        This is useful to get the side-effects of generating a stream.
        """
        self.pb.update(f"scanning {message}", pb_offset)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            list(vf_to_stream(source_vf, keys, message, child_pb))

    def _copy_inventory_texts(self):
        source_vf, target_vf = self._build_vfs("inventory", True, True)
        source_chk_vf, target_chk_vf = self._get_chk_vfs_for_copy()
        inventory_keys = source_vf.keys()
        # First, copy the existing CHKs on the assumption that most of them
        # will be correct.  This will save us from having to reinsert (and
        # recompress) these records later at the cost of perhaps preserving a
        # few unused CHKs.
        # (Iterate but don't insert _get_filtered_inv_stream to populate the
        # variables needed by GCCHKPacker._copy_chk_texts.)
        self._exhaust_stream(
            source_vf, inventory_keys, "inventories", self._get_filtered_inv_stream, 2
        )
        GCCHKPacker._copy_chk_texts(self)
        # Now copy and fix the inventories, and any regenerated CHKs.

        def chk_canonicalizing_inv_stream(source_vf, keys, message, pb=None):
            return self._get_filtered_canonicalizing_inv_stream(
                source_vf, keys, message, pb, source_chk_vf, target_chk_vf
            )

        self._copy_stream(
            source_vf,
            target_vf,
            inventory_keys,
            "inventories",
            chk_canonicalizing_inv_stream,
            4,
        )

    def _copy_chk_texts(self):
        # No-op; in this class this happens during _copy_inventory_texts.
        pass

    def _get_filtered_canonicalizing_inv_stream(
        self, source_vf, keys, message, pb=None, source_chk_vf=None, target_chk_vf=None
    ):
        """Filter the texts of inventories, regenerating CHKs to make sure they
        are canonical.
        """
        total_keys = len(keys)
        target_chk_vf = versionedfile.NoDupeAddLinesDecorator(target_chk_vf)

        def _filtered_inv_stream():
            stream = source_vf.get_record_stream(keys, "groupcompress", True)
            search_key_name = None
            for idx, record in enumerate(stream):
                # Inventories should always be with revisions; assume success.
                lines = record.get_bytes_as("lines")
                chk_inv = inventory.CHKInventory.deserialise(
                    source_chk_vf, lines, record.key
                )
                if pb is not None:
                    pb.update("inv", idx, total_keys)
                chk_inv.id_to_entry._ensure_root()
                if search_key_name is None:
                    # Find the name corresponding to the search_key_func
                    search_key_reg = chk_map.search_key_registry
                    for search_key_name, func in search_key_reg.items():  # noqa: B007
                        if func == chk_inv.id_to_entry._search_key_func:
                            break
                canonical_inv = inventory.CHKInventory.from_inventory(
                    target_chk_vf,
                    chk_inv,
                    maximum_size=chk_inv.id_to_entry._root_node._maximum_size,
                    search_key_name=search_key_name,
                )
                if chk_inv.id_to_entry.key() != canonical_inv.id_to_entry.key():
                    trace.mutter(
                        "Non-canonical CHK map for id_to_entry of inv: {} "
                        "(root is {}, should be {})".format(
                            chk_inv.revision_id,
                            chk_inv.id_to_entry.key()[0],
                            canonical_inv.id_to_entry.key()[0],
                        )
                    )
                    self._data_changed = True
                p_id_map = chk_inv.parent_id_basename_to_file_id
                p_id_map._ensure_root()
                canon_p_id_map = canonical_inv.parent_id_basename_to_file_id
                if p_id_map.key() != canon_p_id_map.key():
                    trace.mutter(
                        "Non-canonical CHK map for parent_id_to_basename of "
                        "inv: {} (root is {}, should be {})".format(
                            chk_inv.revision_id,
                            p_id_map.key()[0],
                            canon_p_id_map.key()[0],
                        )
                    )
                    self._data_changed = True
                yield versionedfile.ChunkedContentFactory(
                    record.key,
                    record.parents,
                    record.sha1,
                    canonical_inv.to_lines(),
                    chunks_are_lines=True,
                )
            # We have finished processing all of the inventory records, we
            # don't need these sets anymore

        return _filtered_inv_stream()

    def _use_pack(self, new_pack):
        """Override _use_pack to check for reconcile having changed content."""
        return new_pack.data_inserted() and self._data_changed


class GCRepositoryPackCollection(RepositoryPackCollection):
    pack_factory = GCPack
    resumed_pack_factory = ResumedGCPack
    normal_packer_class = GCCHKPacker
    optimising_packer_class = GCCHKPacker

    def _check_new_inventories(self):
        """Detect missing inventories or chk root entries for the new revisions
        in this write group.

        :returns: list of strs, summarising any problems found.  If the list is
            empty no problems were found.
        """
        # Ensure that all revisions added in this write group have:
        #   - corresponding inventories,
        #   - chk root entries for those inventories,
        #   - and any present parent inventories have their chk root
        #     entries too.
        # And all this should be independent of any fallback repository.
        problems = []
        key_deps = self.repo.revisions._index._key_dependencies
        new_revisions_keys = key_deps.get_new_keys()
        no_fallback_inv_index = self.repo.inventories._index
        no_fallback_chk_bytes_index = self.repo.chk_bytes._index
        no_fallback_texts_index = self.repo.texts._index
        inv_parent_map = no_fallback_inv_index.get_parent_map(new_revisions_keys)
        # Are any inventories for corresponding to the new revisions missing?
        corresponding_invs = set(inv_parent_map)
        missing_corresponding = set(new_revisions_keys)
        missing_corresponding.difference_update(corresponding_invs)
        if missing_corresponding:
            problems.append(
                f"inventories missing for revisions {sorted(missing_corresponding)}"
            )
            return problems
        # Are any chk root entries missing for any inventories?  This includes
        # any present parent inventories, which may be used when calculating
        # deltas for streaming.
        all_inv_keys = set(corresponding_invs)
        for parent_inv_keys in inv_parent_map.values():
            all_inv_keys.update(parent_inv_keys)
        # Filter out ghost parents.
        all_inv_keys.intersection_update(
            no_fallback_inv_index.get_parent_map(all_inv_keys)
        )
        parent_invs_only_keys = all_inv_keys.symmetric_difference(corresponding_invs)
        inv_ids = [key[-1] for key in all_inv_keys]
        parent_invs_only_ids = [key[-1] for key in parent_invs_only_keys]
        root_key_info = _build_interesting_key_sets(
            self.repo, inv_ids, parent_invs_only_ids
        )
        expected_chk_roots = root_key_info.all_keys()
        present_chk_roots = no_fallback_chk_bytes_index.get_parent_map(
            expected_chk_roots
        )
        missing_chk_roots = expected_chk_roots.difference(present_chk_roots)
        if missing_chk_roots:
            problems.append(
                f"missing referenced chk root keys: {sorted(missing_chk_roots)}."
                "Run 'brz reconcile --canonicalize-chks' on the affected "
                "repository."
            )
            # Don't bother checking any further.
            return problems
        # Find all interesting chk_bytes records, and make sure they are
        # present, as well as the text keys they reference.
        chk_bytes_no_fallbacks = self.repo.chk_bytes.without_fallbacks()
        chk_bytes_no_fallbacks._search_key_func = self.repo.chk_bytes._search_key_func
        chk_diff = chk_map.iter_interesting_nodes(
            chk_bytes_no_fallbacks,
            root_key_info.interesting_root_keys,
            root_key_info.uninteresting_root_keys,
        )
        text_keys = set()
        try:
            for _record in _filter_text_keys(
                chk_diff, text_keys, chk_map._bytes_to_text_key
            ):
                pass
        except errors.NoSuchRevision:
            # XXX: It would be nice if we could give a more precise error here.
            problems.append("missing chk node(s) for id_to_entry maps")
        chk_diff = chk_map.iter_interesting_nodes(
            chk_bytes_no_fallbacks,
            root_key_info.interesting_pid_root_keys,
            root_key_info.uninteresting_pid_root_keys,
        )
        try:
            for _interesting_rec, _interesting_map in chk_diff:
                pass
        except errors.NoSuchRevision:
            problems.append(
                "missing chk node(s) for parent_id_basename_to_file_id maps"
            )
        present_text_keys = no_fallback_texts_index.get_parent_map(text_keys)
        missing_text_keys = text_keys.difference(present_text_keys)
        if missing_text_keys:
            problems.append(f"missing text keys: {sorted(missing_text_keys)!r}")
        return problems


class CHKInventoryRepository(PackRepository):
    """subclass of PackRepository that uses CHK based inventories."""

    def __init__(
        self,
        _format,
        a_controldir,
        control_files,
        _commit_builder_class,
        _revision_serializer,
        _inventory_serializer,
    ):
        """Overridden to change pack collection class."""
        super().__init__(
            _format,
            a_controldir,
            control_files,
            _commit_builder_class,
            _revision_serializer,
            _inventory_serializer,
        )
        index_transport = self._transport.clone("indices")
        self._pack_collection = GCRepositoryPackCollection(
            self,
            self._transport,
            index_transport,
            self._transport.clone("upload"),
            self._transport.clone("packs"),
            _format.index_builder_class,
            _format.index_class,
            use_chk_index=self._format.supports_chks,
        )
        self.inventories = GroupCompressVersionedFiles(
            _GCGraphIndex(
                self._pack_collection.inventory_index.combined_index,
                add_callback=self._pack_collection.inventory_index.add_callback,
                parents=True,
                is_locked=self.is_locked,
                inconsistency_fatal=False,
            ),
            access=self._pack_collection.inventory_index.data_access,
        )
        self.revisions = GroupCompressVersionedFiles(
            _GCGraphIndex(
                self._pack_collection.revision_index.combined_index,
                add_callback=self._pack_collection.revision_index.add_callback,
                parents=True,
                is_locked=self.is_locked,
                track_external_parent_refs=True,
                track_new_keys=True,
            ),
            access=self._pack_collection.revision_index.data_access,
            delta=False,
        )
        self.signatures = GroupCompressVersionedFiles(
            _GCGraphIndex(
                self._pack_collection.signature_index.combined_index,
                add_callback=self._pack_collection.signature_index.add_callback,
                parents=False,
                is_locked=self.is_locked,
                inconsistency_fatal=False,
            ),
            access=self._pack_collection.signature_index.data_access,
            delta=False,
        )
        self.texts = GroupCompressVersionedFiles(
            _GCGraphIndex(
                self._pack_collection.text_index.combined_index,
                add_callback=self._pack_collection.text_index.add_callback,
                parents=True,
                is_locked=self.is_locked,
                inconsistency_fatal=False,
            ),
            access=self._pack_collection.text_index.data_access,
        )
        # No parents, individual CHK pages don't have specific ancestry
        self.chk_bytes = GroupCompressVersionedFiles(
            _GCGraphIndex(
                self._pack_collection.chk_index.combined_index,
                add_callback=self._pack_collection.chk_index.add_callback,
                parents=False,
                is_locked=self.is_locked,
                inconsistency_fatal=False,
            ),
            access=self._pack_collection.chk_index.data_access,
        )
        search_key_name = self._format._inventory_serializer.search_key_name
        search_key_func = chk_map.search_key_registry.get(search_key_name)
        self.chk_bytes._search_key_func = search_key_func
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

    def _add_inventory_checked(self, revision_id, inv, parents):
        """Add inv to the repository after checking the inputs.

        This function can be overridden to allow different inventory styles.

        :seealso: add_inventory, for the contract.
        """
        # make inventory
        serializer = self._format._inventory_serializer
        result = inventory.CHKInventory.from_inventory(
            self.chk_bytes,
            inv,
            maximum_size=serializer.maximum_size,
            search_key_name=serializer.search_key_name,
        )
        inv_lines = result.to_lines()
        return self._inventory_add_lines(
            revision_id, parents, inv_lines, check_content=False
        )

    def _create_inv_from_null(self, delta, revision_id):
        """This will mutate new_inv directly.

        This is a simplified form of create_by_apply_delta which knows that all
        the old values must be None, so everything is a create.
        """
        serializer = self._format._inventory_serializer
        new_inv = inventory.CHKInventory(serializer.search_key_name)
        new_inv.revision_id = revision_id
        entry_to_bytes = inventory._chk_inventory_entry_to_bytes
        id_to_entry_dict = {}
        parent_id_basename_dict = {}
        for old_path, new_path, file_id, entry in delta:
            if old_path is not None:
                raise ValueError(
                    f"Invalid delta, somebody tried to delete {(old_path, file_id)!r}"
                    " from the NULL_REVISION"
                )
            if new_path is None:
                raise ValueError(
                    "Invalid delta, delta from NULL_REVISION has"
                    f" no new_path {file_id!r}"
                )
            if new_path == "":
                new_inv.root_id = file_id
                parent_id_basename_key = (b"", b"")
            else:
                utf8_entry_name = entry.name.encode("utf-8")
                parent_id_basename_key = (
                    entry.parent_id, utf8_entry_name
                )
            new_value = entry_to_bytes(entry)
            # Populate Caches?
            # new_inv._path_to_fileid_cache[new_path] = file_id
            key = (file_id,)
            id_to_entry_dict[key] = new_value
            parent_id_basename_dict[parent_id_basename_key] = file_id

        new_inv._populate_from_dicts(
            self.chk_bytes,
            id_to_entry_dict,
            parent_id_basename_dict,
            maximum_size=serializer.maximum_size,
        )
        return new_inv

    def add_inventory_by_delta(
        self,
        basis_revision_id,
        delta,
        new_revision_id,
        parents,
        basis_inv=None,
        propagate_caches=False,
    ):
        """Add a new inventory expressed as a delta against another revision.

        :param basis_revision_id: The inventory id the delta was created
            against.
        :param delta: The inventory delta (see Inventory.apply_delta for
            details).
        :param new_revision_id: The revision id that the inventory is being
            added for.
        :param parents: The revision ids of the parents that revision_id is
            known to have and are in the repository already. These are supplied
            for repositories that depend on the inventory graph for revision
            graph access, as well as for those that pun ancestry with delta
            compression.
        :param basis_inv: The basis inventory if it is already known,
            otherwise None.
        :param propagate_caches: If True, the caches for this inventory are
          copied to and updated for the result if possible.

        :returns: (validator, new_inv)
            The validator(which is a sha1 digest, though what is sha'd is
            repository format specific) of the serialized inventory, and the
            resulting inventory.
        """
        if not self.is_in_write_group():
            raise AssertionError(f"{self!r} not in write group")
        _mod_revision.check_not_reserved_id(new_revision_id)
        basis_tree = None
        if basis_inv is None or not isinstance(basis_inv, inventory.CHKInventory):
            if basis_revision_id == _mod_revision.NULL_REVISION:
                new_inv = self._create_inv_from_null(delta, new_revision_id)
                if new_inv.root_id is None:
                    raise errors.RootMissing()
                inv_lines = new_inv.to_lines()
                return self._inventory_add_lines(
                    new_revision_id, parents, inv_lines, check_content=False
                ), new_inv
            else:
                basis_tree = self.revision_tree(basis_revision_id)
                basis_tree.lock_read()
                basis_inv = basis_tree.root_inventory
        try:
            result = basis_inv.create_by_apply_delta(
                delta, new_revision_id, propagate_caches=propagate_caches
            )
            inv_lines = result.to_lines()
            return self._inventory_add_lines(
                new_revision_id, parents, inv_lines, check_content=False
            ), result
        finally:
            if basis_tree is not None:
                basis_tree.unlock()

    def _deserialise_inventory(self, revision_id, lines):
        return inventory.CHKInventory.deserialise(self.chk_bytes, lines, (revision_id,))

    def _iter_inventories(self, revision_ids, ordering):
        """Iterate over many inventory objects."""
        if ordering is None:
            ordering = "unordered"
        keys = [(revision_id,) for revision_id in revision_ids]
        stream = self.inventories.get_record_stream(keys, ordering, True)
        texts = {}
        for record in stream:
            if record.storage_kind != "absent":
                texts[record.key] = record.get_bytes_as("lines")
            else:
                texts[record.key] = None
        for key in keys:
            lines = texts[key]
            if lines is None:
                yield (None, key[-1])
            else:
                yield (
                    inventory.CHKInventory.deserialise(self.chk_bytes, lines, key),
                    key[-1],
                )

    def _get_inventory_xml(self, revision_id):
        """Get serialized inventory as a string."""
        # Without a native 'xml' inventory, this method doesn't make sense.
        # However older working trees, and older bundles want it - so we supply
        # it allowing _get_inventory_xml to work. Bundles currently use the
        # serializer directly; this also isn't ideal, but there isn't an xml
        # iteration interface offered at all for repositories.
        return self._inventory_serializer.write_inventory_to_lines(
            self.get_inventory(revision_id)
        )

    def _find_present_inventory_keys(self, revision_keys):
        parent_map = self.inventories.get_parent_map(revision_keys)
        present_inventory_keys = set(parent_map)
        return present_inventory_keys

    def fileids_altered_by_revision_ids(self, revision_ids, _inv_weave=None):
        """Find the file ids and versions affected by revisions.

        :param revisions: an iterable containing revision ids.
        :param _inv_weave: The inventory weave from this repository or None.
            If None, the inventory weave will be opened automatically.
        :return: a dictionary mapping altered file-ids to an iterable of
            revision_ids. Each altered file-ids has the exact revision_ids that
            altered it listed explicitly.
        """
        rich_root = self.supports_rich_root()
        bytes_to_info = inventory.chk_inventory_bytes_to_utf8name_key
        file_id_revisions = {}
        with ui.ui_factory.nested_progress_bar() as pb:
            revision_keys = [(r,) for r in revision_ids]
            parent_keys = self._find_parent_keys_of_revisions(revision_keys)
            # TODO: instead of using _find_present_inventory_keys, change the
            #       code paths to allow missing inventories to be tolerated.
            #       However, we only want to tolerate missing parent
            #       inventories, not missing inventories for revision_ids
            present_parent_inv_keys = self._find_present_inventory_keys(parent_keys)
            present_parent_inv_ids = {k[-1] for k in present_parent_inv_keys}
            inventories_to_read = set(revision_ids)
            inventories_to_read.update(present_parent_inv_ids)
            root_key_info = _build_interesting_key_sets(
                self, inventories_to_read, present_parent_inv_ids
            )
            interesting_root_keys = root_key_info.interesting_root_keys
            uninteresting_root_keys = root_key_info.uninteresting_root_keys
            chk_bytes = self.chk_bytes
            for _record, items in chk_map.iter_interesting_nodes(
                chk_bytes, interesting_root_keys, uninteresting_root_keys, pb=pb
            ):
                for _name, bytes in items:
                    (name_utf8, file_id, revision_id) = bytes_to_info(bytes)
                    # TODO: consider interning file_id, revision_id here, or
                    #       pushing that intern() into bytes_to_info()
                    # TODO: rich_root should always be True here, for all
                    #       repositories that support chk_bytes
                    if not rich_root and name_utf8 == "":
                        continue
                    try:
                        file_id_revisions[file_id].add(revision_id)
                    except KeyError:
                        file_id_revisions[file_id] = {revision_id}
        return file_id_revisions

    def find_text_key_references(self):
        """Find the text key references within the repository.

        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. The inventory texts from all present
            revision ids are assessed to generate this report.
        """
        # XXX: Slow version but correct: rewrite as a series of delta
        # examinations/direct tree traversal. Note that that will require care
        # as a common node is reachable both from the inventory that added it,
        # and others afterwards.
        self.revisions.keys()
        result = {}
        rich_roots = self.supports_rich_root()
        with ui.ui_factory.nested_progress_bar() as pb:
            all_revs = self.all_revision_ids()
            total = len(all_revs)
            for pos, inv in enumerate(self.iter_inventories(all_revs)):
                pb.update("Finding text references", pos, total)
                for _, entry in inv.iter_entries():
                    if not rich_roots and entry.file_id == inv.root_id:
                        continue
                    key = (entry.file_id, entry.revision)
                    result.setdefault(key, False)
                    if entry.revision == inv.revision_id:
                        result[key] = True
            return result

    def reconcile_canonicalize_chks(self):
        """Reconcile this repository to make sure all CHKs are in canonical
        form.
        """
        from .reconcile import PackReconciler

        with self.lock_write():
            reconciler = PackReconciler(self, thorough=True, canonicalize_chks=True)
            return reconciler.reconcile()

    def _reconcile_pack(self, collection, packs, extension, revs, pb):
        packer = GCCHKReconcilePacker(collection, packs, extension)
        return packer.pack(pb)

    def _canonicalize_chks_pack(self, collection, packs, extension, revs, pb):
        packer = GCCHKCanonicalizingPacker(collection, packs, extension, revs)
        return packer.pack(pb)

    def _get_source(self, to_format):
        """Return a source for streaming from this repository."""
        if (
            self._format._inventory_serializer == to_format._inventory_serializer
            and self._format._revision_serializer == to_format._revision_serializer
        ):
            # We must be exactly the same format, otherwise stuff like the chk
            # page layout might be different.
            # Actually, this test is just slightly looser than exact so that
            # CHK2 <-> 2a transfers will work.
            return GroupCHKStreamSource(self, to_format)
        return super()._get_source(to_format)

    def _find_inconsistent_revision_parents(self, revisions_iterator=None):
        """Find revisions with different parent lists in the revision object
        and in the index graph.

        :param revisions_iterator: None, or an iterator of (revid,
            Revision-or-None). This iterator controls the revisions checked.
        :returns: an iterator yielding tuples of (revison-id, parents-in-index,
            parents-in-revision).
        """
        if not self.is_locked():
            raise AssertionError()
        vf = self.revisions
        if revisions_iterator is None:
            revisions_iterator = self.iter_revisions(self.all_revision_ids())
        for revid, revision in revisions_iterator:
            if revision is None:
                pass
            parent_map = vf.get_parent_map([(revid,)])
            parents_according_to_index = tuple(
                parent[-1] for parent in parent_map[(revid,)]
            )
            parents_according_to_revision = tuple(revision.parent_ids)
            if parents_according_to_index != parents_according_to_revision:
                yield (revid, parents_according_to_index, parents_according_to_revision)

    def _check_for_inconsistent_revision_parents(self):
        inconsistencies = list(self._find_inconsistent_revision_parents())
        if inconsistencies:
            raise errors.BzrCheckError("Revision index has inconsistent parents.")


class GroupCHKStreamSource(StreamSource):
    """Used when both the source and target repo are GroupCHK repos."""

    def __init__(self, from_repository, to_format):
        """Create a StreamSource streaming from from_repository."""
        super().__init__(from_repository, to_format)
        self._revision_keys = None
        self._text_keys = None
        self._text_fetch_order = "groupcompress"
        self._chk_id_roots = None
        self._chk_p_id_roots = None

    def _get_inventory_stream(self, inventory_keys, allow_absent=False):
        """Get a stream of inventory texts.

        When this function returns, self._chk_id_roots and self._chk_p_id_roots
        should be populated.
        """
        self._chk_id_roots = []
        self._chk_p_id_roots = []

        def _filtered_inv_stream():
            id_roots_set = set()
            p_id_roots_set = set()
            source_vf = self.from_repository.inventories
            stream = source_vf.get_record_stream(inventory_keys, "groupcompress", True)
            for record in stream:
                if record.storage_kind == "absent":
                    if allow_absent:
                        continue
                    else:
                        raise errors.NoSuchRevision(self, record.key)
                lines = record.get_bytes_as("lines")
                chk_inv = inventory.CHKInventory.deserialise(None, lines, record.key)
                key = chk_inv.id_to_entry.key()
                if key not in id_roots_set:
                    self._chk_id_roots.append(key)
                    id_roots_set.add(key)
                p_id_map = chk_inv.parent_id_basename_to_file_id
                if p_id_map is None:
                    raise AssertionError("Parent id -> file_id map not set")
                key = p_id_map.key()
                if key not in p_id_roots_set:
                    p_id_roots_set.add(key)
                    self._chk_p_id_roots.append(key)
                yield record
            # We have finished processing all of the inventory records, we
            # don't need these sets anymore
            id_roots_set.clear()
            p_id_roots_set.clear()

        return ("inventories", _filtered_inv_stream())

    def _get_filtered_chk_streams(self, excluded_revision_keys):
        self._text_keys = set()
        excluded_revision_keys.discard(_mod_revision.NULL_REVISION)
        if not excluded_revision_keys:
            uninteresting_root_keys = set()
            uninteresting_pid_root_keys = set()
        else:
            # filter out any excluded revisions whose inventories are not
            # actually present
            # TODO: Update Repository.iter_inventories() to add
            #       ignore_missing=True
            present_keys = self.from_repository._find_present_inventory_keys(
                excluded_revision_keys
            )
            present_ids = [k[-1] for k in present_keys]
            uninteresting_root_keys = set()
            uninteresting_pid_root_keys = set()
            for inv in self.from_repository.iter_inventories(present_ids):
                uninteresting_root_keys.add(inv.id_to_entry.key())
                uninteresting_pid_root_keys.add(inv.parent_id_basename_to_file_id.key())
        chk_bytes = self.from_repository.chk_bytes

        def _filter_id_to_entry():
            interesting_nodes = chk_map.iter_interesting_nodes(
                chk_bytes, self._chk_id_roots, uninteresting_root_keys
            )
            for record in _filter_text_keys(
                interesting_nodes, self._text_keys, chk_map._bytes_to_text_key
            ):
                if record is not None:
                    yield record
            # Consumed
            self._chk_id_roots = None

        yield "chk_bytes", _filter_id_to_entry()

        def _get_parent_id_basename_to_file_id_pages():
            for record, _items in chk_map.iter_interesting_nodes(
                chk_bytes, self._chk_p_id_roots, uninteresting_pid_root_keys
            ):
                if record is not None:
                    yield record
            # Consumed
            self._chk_p_id_roots = None

        yield "chk_bytes", _get_parent_id_basename_to_file_id_pages()

    def _get_text_stream(self):
        # Note: We know we don't have to handle adding root keys, because both
        # the source and target are the identical network name.
        text_stream = self.from_repository.texts.get_record_stream(
            self._text_keys, self._text_fetch_order, False
        )
        return ("texts", text_stream)

    def get_stream(self, search):
        def wrap_and_count(pb, rc, stream):
            """Yield records from stream while showing progress."""
            count = 0
            for record in stream:
                if count == rc.STEP:
                    rc.increment(count)
                    pb.update("Estimate", rc.current, rc.max)
                    count = 0
                count += 1
                yield record

        revision_ids = search.get_keys()
        with ui.ui_factory.nested_progress_bar() as pb:
            rc = self._record_counter
            self._record_counter.setup(len(revision_ids))
            for stream_info in self._fetch_revision_texts(revision_ids):
                yield (stream_info[0], wrap_and_count(pb, rc, stream_info[1]))
            self._revision_keys = [(rev_id,) for rev_id in revision_ids]
            # TODO: The keys to exclude might be part of the search recipe
            # For now, exclude all parents that are at the edge of ancestry, for
            # which we have inventories
            from_repo = self.from_repository
            parent_keys = from_repo._find_parent_keys_of_revisions(self._revision_keys)
            self.from_repository.revisions.clear_cache()
            self.from_repository.signatures.clear_cache()
            # Clear the repo's get_parent_map cache too.
            self.from_repository._unstacked_provider.disable_cache()
            self.from_repository._unstacked_provider.enable_cache()
            s = self._get_inventory_stream(self._revision_keys)
            yield (s[0], wrap_and_count(pb, rc, s[1]))
            self.from_repository.inventories.clear_cache()
            for stream_info in self._get_filtered_chk_streams(parent_keys):
                yield (stream_info[0], wrap_and_count(pb, rc, stream_info[1]))
            self.from_repository.chk_bytes.clear_cache()
            s = self._get_text_stream()
            yield (s[0], wrap_and_count(pb, rc, s[1]))
            self.from_repository.texts.clear_cache()
            pb.update("Done", rc.max, rc.max)

    def get_stream_for_missing_keys(self, missing_keys):
        # missing keys can only occur when we are byte copying and not
        # translating (because translation means we don't send
        # unreconstructable deltas ever).
        missing_inventory_keys = set()
        for key in missing_keys:
            if key[0] != "inventories":
                raise AssertionError(
                    "The only missing keys we should"
                    f" be filling in are inventory keys, not {key[0]}"
                )
            missing_inventory_keys.add(key[1:])
        if self._chk_id_roots or self._chk_p_id_roots:
            raise AssertionError(
                "Cannot call get_stream_for_missing_keys"
                " until all of get_stream() has been consumed."
            )
        # Yield the inventory stream, so we can find the chk stream
        # Some of the missing_keys will be missing because they are ghosts.
        # As such, we can ignore them. The Sink is required to verify there are
        # no unavailable texts when the ghost inventories are not filled in.
        yield self._get_inventory_stream(missing_inventory_keys, allow_absent=True)
        # We use the empty set for excluded_revision_keys, to make it clear
        # that we want to transmit all referenced chk pages.
        yield from self._get_filtered_chk_streams(set())


class _InterestingKeyInfo:
    def __init__(self):
        self.interesting_root_keys = set()
        self.interesting_pid_root_keys = set()
        self.uninteresting_root_keys = set()
        self.uninteresting_pid_root_keys = set()

    def all_interesting(self):
        return self.interesting_root_keys.union(self.interesting_pid_root_keys)

    def all_uninteresting(self):
        return self.uninteresting_root_keys.union(self.uninteresting_pid_root_keys)

    def all_keys(self):
        return self.all_interesting().union(self.all_uninteresting())


def _build_interesting_key_sets(repo, inventory_ids, parent_only_inv_ids):
    result = _InterestingKeyInfo()
    for inv in repo.iter_inventories(inventory_ids, "unordered"):
        root_key = inv.id_to_entry.key()
        pid_root_key = inv.parent_id_basename_to_file_id.key()
        if inv.revision_id in parent_only_inv_ids:
            result.uninteresting_root_keys.add(root_key)
            result.uninteresting_pid_root_keys.add(pid_root_key)
        else:
            result.interesting_root_keys.add(root_key)
            result.interesting_pid_root_keys.add(pid_root_key)
    return result


def _filter_text_keys(interesting_nodes_iterable, text_keys, bytes_to_text_key):
    """Iterate the result of iter_interesting_nodes, yielding the records
    and adding to text_keys.
    """
    text_keys_update = text_keys.update
    for record, items in interesting_nodes_iterable:
        text_keys_update([bytes_to_text_key(b) for n, b in items])
        yield record


class RepositoryFormat2a(RepositoryFormatPack):
    """A CHK repository that uses the bencode revision serializer."""

    repository_class = CHKInventoryRepository
    supports_external_lookups = True
    supports_chks = True
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    _revision_serializer = _bzr_rs.revision_bencode_serializer
    _inventory_serializer = chk_serializer.inventory_chk_serializer_255_bigpage_10
    _commit_inv_deltas = True
    # What index classes to use
    index_builder_class = BTreeBuilder
    index_class = BTreeGraphIndex
    # Note: We cannot unpack a delta that references a text we haven't
    # seen yet. There are 2 options, work in fulltexts, or require
    # topological sorting. Using fulltexts is more optimal for local
    # operations, because the source can be smart about extracting
    # multiple in-a-row (and sharing strings). Topological is better
    # for remote, because we access less data.
    _fetch_order = "unordered"
    # essentially ignored by the groupcompress code.
    _fetch_uses_deltas = False
    fast_deltas = True
    pack_compresses = True
    supports_tree_reference = True

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("2a")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        return b"Bazaar repository format 2a (needs bzr 1.16 or later)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return (
            "Repository format 2a - rich roots, group compression and chk inventories"
        )


class RepositoryFormat2aSubtree(RepositoryFormat2a):
    """A 2a repository format that supports nested trees."""

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("development-subtree")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        return b"Bazaar development format 8\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return (
            "Development repository format 8 - nested trees, "
            "group compression and chk inventories"
        )

    experimental = True
    supports_tree_reference = True

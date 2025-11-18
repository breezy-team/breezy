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

"""Knit-based pack repository formats."""

from .. import controldir, debug, errors, trace
from .. import transport as _mod_transport
from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import time

from vcsgraph import tsort

from breezy import (
    revision as _mod_revision,
    ui,
    )
from breezy.bzr import (
    pack,
    )
from breezy.bzr.knit import (
    _KnitGraphIndex,
    KnitPlainFactory,
    KnitVersionedFiles,
    )
""",
)

from ..bzr import btree_index
from ..bzr.index import (
    CombinedGraphIndex,
    GraphIndex,
    GraphIndexPrefixAdapter,
    InMemoryGraphIndex,
)
from ..bzr.vf_repository import StreamSource
from .knitrepo import KnitRepository
from .pack_repo import (
    NewPack,
    PackCommitBuilder,
    Packer,
    PackRepository,
    RepositoryFormatPack,
    RepositoryPackCollection,
    ResumedPack,
    _DirectPackAccess,
)


class KnitPackRepository(PackRepository, KnitRepository):
    """A repository that uses knit format with pack storage.

    Combines the knit versioned file format with pack-based storage.
    """

    def __init__(
        self,
        _format,
        a_controldir,
        control_files,
        _commit_builder_class,
        _revision_serializer,
        _inventory_serializer,
    ):
        """Initialize a KnitPackRepository.

        Args:
            _format: The repository format.
            a_controldir: The control directory.
            control_files: Control files for the repository.
            _commit_builder_class: Class to use for building commits.
            _revision_serializer: Serializer for revisions.
            _inventory_serializer: Serializer for inventories.
        """
        PackRepository.__init__(
            self,
            _format,
            a_controldir,
            control_files,
            _commit_builder_class,
            _revision_serializer,
            _inventory_serializer,
        )
        if self._format.supports_chks:
            raise AssertionError("chk not supported")
        index_transport = self._transport.clone("indices")
        self._pack_collection = KnitRepositoryPackCollection(
            self,
            self._transport,
            index_transport,
            self._transport.clone("upload"),
            self._transport.clone("packs"),
            _format.index_builder_class,
            _format.index_class,
            use_chk_index=False,
        )
        self.inventories = KnitVersionedFiles(
            _KnitGraphIndex(
                self._pack_collection.inventory_index.combined_index,
                add_callback=self._pack_collection.inventory_index.add_callback,
                deltas=True,
                parents=True,
                is_locked=self.is_locked,
            ),
            data_access=self._pack_collection.inventory_index.data_access,
            max_delta_chain=200,
        )
        self.revisions = KnitVersionedFiles(
            _KnitGraphIndex(
                self._pack_collection.revision_index.combined_index,
                add_callback=self._pack_collection.revision_index.add_callback,
                deltas=False,
                parents=True,
                is_locked=self.is_locked,
                track_external_parent_refs=True,
            ),
            data_access=self._pack_collection.revision_index.data_access,
            max_delta_chain=0,
        )
        self.signatures = KnitVersionedFiles(
            _KnitGraphIndex(
                self._pack_collection.signature_index.combined_index,
                add_callback=self._pack_collection.signature_index.add_callback,
                deltas=False,
                parents=False,
                is_locked=self.is_locked,
            ),
            data_access=self._pack_collection.signature_index.data_access,
            max_delta_chain=0,
        )
        self.texts = KnitVersionedFiles(
            _KnitGraphIndex(
                self._pack_collection.text_index.combined_index,
                add_callback=self._pack_collection.text_index.add_callback,
                deltas=True,
                parents=True,
                is_locked=self.is_locked,
            ),
            data_access=self._pack_collection.text_index.data_access,
            max_delta_chain=200,
        )
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

    def _get_source(self, to_format):
        if to_format.network_name() == self._format.network_name():
            return KnitPackStreamSource(self, to_format)
        return PackRepository._get_source(self, to_format)

    def _reconcile_pack(self, collection, packs, extension, revs, pb):
        packer = KnitReconcilePacker(collection, packs, extension, revs)
        return packer.pack(pb)


class RepositoryFormatKnitPack1(RepositoryFormatPack):
    """A no-subtrees parameterized Pack repository.

    This format was introduced in 0.92.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("pack-0.92")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar pack repository format 1 (needs bzr 0.92)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs containing knits without subtree support"


class RepositoryFormatKnitPack3(RepositoryFormatPack):
    """A subtrees parameterized Pack repository.

    This repository format uses the xml7 serializer to get:
     - support for recording full info about the tree root
     - support for recording tree-references

    This format was introduced in 0.92.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    experimental = True
    supports_tree_reference = True

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml7 import inventory_serializer_v7

        return inventory_serializer_v7

    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("pack-0.92-subtree")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return (
            b"Bazaar pack repository format 1 with subtree support (needs bzr 0.92)\n"
        )

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
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    supports_tree_reference = False

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml6 import inventory_serializer_v6

        return inventory_serializer_v6

    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("rich-root-pack")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar pack repository format 1 with rich root (needs bzr 1.0)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs containing knits with rich root support\n"


class RepositoryFormatKnitPack5(RepositoryFormatPack):
    """Repository that supports external references to allow stacking.

    Supports external lookups, which results in non-truncated ghosts after
    reconcile compared to pack-0.92 formats.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("1.6")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 5 (adds stacking support, requires bzr 1.6)"


class RepositoryFormatKnitPack5RichRoot(RepositoryFormatPack):
    """A repository with rich roots and stacking.

    Supports stacking on other repositories, allowing data to be accessed
    without being stored locally.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    supports_tree_reference = False  # no subtrees
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml6 import inventory_serializer_v6

        return inventory_serializer_v6

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("1.6.1-rich-root")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 5 rich-root (adds stacking support, requires bzr 1.6.1)"


class RepositoryFormatKnitPack5RichRootBroken(RepositoryFormatPack):
    """A repository with rich roots and external references.

    Supports external lookups, which results in non-truncated ghosts after
    reconcile compared to pack-0.92 formats.

    This format was deprecated because the serializer it uses accidentally
    supported subtrees, when the format was not intended to. This meant that
    someone could accidentally fetch from an incorrect repository.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    supports_tree_reference = False  # no subtrees

    supports_external_lookups = True
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml7 import inventory_serializer_v7

        return inventory_serializer_v7

    def _get_matching_bzrdir(self):
        matching = controldir.format_registry.make_controldir("1.6.1-rich-root")
        matching.repository_format = self
        return matching

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return (
            "Packs 5 rich-root (adds stacking support, requires bzr 1.6) (deprecated)"
        )

    def is_deprecated(self):
        """Check if this format is deprecated.

        Returns:
            True, as this format is deprecated.
        """
        return True


class RepositoryFormatKnitPack6(RepositoryFormatPack):
    """A repository with stacking and btree indexes,
    without rich roots or subtrees.

    This is equivalent to pack-1.6 with B+Tree indices.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = btree_index.BTreeBuilder
    index_class = btree_index.BTreeGraphIndex

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("1.9")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar RepositoryFormatKnitPack6 (bzr 1.9)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 6 (uses btree indexes, requires bzr 1.9)"


class RepositoryFormatKnitPack6RichRoot(RepositoryFormatPack):
    """A repository with rich roots, no subtrees, stacking and btree indexes.

    1.6-rich-root with B+Tree indices.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    supports_tree_reference = False  # no subtrees
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = btree_index.BTreeBuilder
    index_class = btree_index.BTreeGraphIndex

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml6 import inventory_serializer_v6

        return inventory_serializer_v6

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("1.9-rich-root")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar RepositoryFormatKnitPack6RichRoot (bzr 1.9)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 6 rich-root (uses btree indexes, requires bzr 1.9)"


class RepositoryFormatPackDevelopment2Subtree(RepositoryFormatPack):
    """A subtrees development repository.

    This format should be retained in 2.3, to provide an upgrade path from this
    to RepositoryFormat2aSubtree.  It can be removed in later releases.

    1.6.1-subtree[as it might have been] with B+Tree indices.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackCommitBuilder
    rich_root_data = True
    experimental = True
    supports_tree_reference = True
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = btree_index.BTreeBuilder
    index_class = btree_index.BTreeGraphIndex

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml7 import inventory_serializer_v7

        return inventory_serializer_v7

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("development5-subtree")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return (
            b"Bazaar development format 2 with subtree support "
            b"(needs bzr.dev from before 1.8)\n"
        )

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return (
            "Development repository format, currently the same as "
            "1.6.1-subtree with B+Tree indices.\n"
        )


class KnitPackStreamSource(StreamSource):
    """A StreamSource used to transfer data between same-format KnitPack repos.

    This source assumes:
        1) Same serialization format for all objects
        2) Same root information
        3) XML format inventories
        4) Atomic inserts (so we can stream inventory texts before text
           content)
        5) No chk_bytes
    """

    def __init__(self, from_repository, to_format):
        """Initialize a KnitPackStreamSource.

        Args:
            from_repository: The source repository.
            to_format: The target repository format.
        """
        super().__init__(from_repository, to_format)
        self._text_keys = None
        self._text_fetch_order = "unordered"

    def _get_filtered_inv_stream(self, revision_ids):
        from_repo = self.from_repository
        parent_ids = from_repo._find_parent_ids_of_revisions(revision_ids)
        parent_keys = [(p,) for p in parent_ids]
        find_text_keys = from_repo._inventory_serializer._find_text_key_references
        parent_text_keys = set(
            find_text_keys(from_repo._inventory_xml_lines_for_keys(parent_keys))
        )
        content_text_keys = set()
        knit = KnitVersionedFiles(None, None)
        factory = KnitPlainFactory()

        def find_text_keys_from_content(record):
            if record.storage_kind not in ("knit-delta-gz", "knit-ft-gz"):
                raise ValueError(
                    "Unknown content storage kind for"
                    f" inventory text: {record.storage_kind}"
                )
            # It's a knit record, it has a _raw_record field (even if it was
            # reconstituted from a network stream).
            raw_data = record._raw_record
            # read the entire thing
            revision_id = record.key[-1]
            content, _ = knit._parse_record(revision_id, raw_data)
            if record.storage_kind == "knit-delta-gz":
                line_iterator = factory.get_linedelta_content(content)
            elif record.storage_kind == "knit-ft-gz":
                line_iterator = factory.get_fulltext_content(content)
            content_text_keys.update(
                find_text_keys([(line, revision_id) for line in line_iterator])
            )

        revision_keys = [(r,) for r in revision_ids]

        def _filtered_inv_stream():
            source_vf = from_repo.inventories
            stream = source_vf.get_record_stream(revision_keys, "unordered", False)
            for record in stream:
                if record.storage_kind == "absent":
                    raise errors.NoSuchRevision(from_repo, record.key)
                find_text_keys_from_content(record)
                yield record
            self._text_keys = content_text_keys - parent_text_keys

        return ("inventories", _filtered_inv_stream())

    def _get_text_stream(self):
        # Note: We know we don't have to handle adding root keys, because both
        # the source and target are the identical network name.
        text_stream = self.from_repository.texts.get_record_stream(
            self._text_keys, self._text_fetch_order, False
        )
        return ("texts", text_stream)

    def get_stream(self, search):
        """Get a stream of records for the given search.

        Args:
            search: Search object specifying what records to retrieve.

        Yields:
            Tuples of (stream_type, record_stream) for different data types.
        """
        revision_ids = search.get_keys()
        yield from self._fetch_revision_texts(revision_ids)
        self._revision_keys = [(rev_id,) for rev_id in revision_ids]
        yield self._get_filtered_inv_stream(revision_ids)
        yield self._get_text_stream()


class KnitPacker(Packer):
    """Packer that works with knit packs."""

    def __init__(
        self, pack_collection, packs, suffix, revision_ids=None, reload_func=None
    ):
        """Initialize a KnitPacker.

        Args:
            pack_collection: The pack collection to operate on.
            packs: List of packs to process.
            suffix: Suffix for the new pack name.
            revision_ids: Optional list of revision IDs to pack.
            reload_func: Optional function to reload pack data.
        """
        super().__init__(
            pack_collection,
            packs,
            suffix,
            revision_ids=revision_ids,
            reload_func=reload_func,
        )

    def _pack_map_and_index_list(self, index_attribute):
        """Convert a list of packs to an index pack map and index list.

        :param index_attribute: The attribute that the desired index is found
            on.
        :return: A tuple (map, list) where map contains the dict from
            index:pack_tuple, and list contains the indices in the preferred
            access order.
        """
        indices = []
        pack_map = {}
        for pack_obj in self.packs:
            index = getattr(pack_obj, index_attribute)
            indices.append(index)
            pack_map[index] = pack_obj
        return pack_map, indices

    def _index_contents(self, indices, key_filter=None):
        """Get an iterable of the index contents from a pack_map.

        :param indices: The list of indices to query
        :param key_filter: An optional filter to limit the keys returned.
        """
        all_index = CombinedGraphIndex(indices)
        if key_filter is None:
            return all_index.iter_all_entries()
        else:
            return all_index.iter_entries(key_filter)

    def _copy_nodes(self, nodes, index_map, writer, write_index, output_lines=None):
        """Copy knit nodes between packs with no graph references.

        :param output_lines: Output full texts of copied items.
        """
        with ui.ui_factory.nested_progress_bar() as pb:
            return self._do_copy_nodes(
                nodes, index_map, writer, write_index, pb, output_lines=output_lines
            )

    def _do_copy_nodes(
        self, nodes, index_map, writer, write_index, pb, output_lines=None
    ):
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
        for index, items in request_groups.items():
            pack_readv_requests = []
            for key, value in items:
                # ---- KnitGraphIndex.get_position
                bits = value[1:].split(b" ")
                offset, length = int(bits[0]), int(bits[1])
                pack_readv_requests.append((offset, length, (key, value[0:1])))
            # linear scan up the pack
            pack_readv_requests.sort()
            # copy the data
            pack_obj = index_map[index]
            transport, path = pack_obj.access_tuple()
            try:
                reader = pack.make_readv_reader(
                    transport, path, [offset[0:2] for offset in pack_readv_requests]
                )
            except _mod_transport.NoSuchFile:
                if self._reload_func is not None:
                    self._reload_func()
                raise
            for (names, read_func), (_1, _2, (key, eol_flag)) in zip(
                reader.iter_records(), pack_readv_requests, strict=False
            ):
                raw_data = read_func(None)
                # check the header only
                if output_lines is not None:
                    output_lines(knit._parse_record(key[-1], raw_data)[0])
                else:
                    df, _ = knit._parse_record_header(key, raw_data)
                    df.close()
                pos, size = writer.add_bytes_record([raw_data], len(raw_data), names)
                write_index.add_node(key, eol_flag + b"%d %d" % (pos, size))
                pb.update("Copied record", record_index)
                record_index += 1

    def _copy_nodes_graph(
        self,
        index_map,
        writer,
        write_index,
        readv_group_iter,
        total_items,
        output_lines=False,
    ):
        """Copy knit nodes between packs.

        :param output_lines: Return lines present in the copied data as
            an iterator of line,version_id.
        """
        with ui.ui_factory.nested_progress_bar() as pb:
            yield from self._do_copy_nodes_graph(
                index_map,
                writer,
                write_index,
                output_lines,
                pb,
                readv_group_iter,
                total_items,
            )

    def _do_copy_nodes_graph(
        self,
        index_map,
        writer,
        write_index,
        output_lines,
        pb,
        readv_group_iter,
        total_items,
    ):
        # for record verification
        knit = KnitVersionedFiles(None, None)
        # for line extraction when requested (inventories only)
        if output_lines:
            factory = KnitPlainFactory()
        record_index = 0
        pb.update("Copied record", record_index, total_items)
        for index, readv_vector, node_vector in readv_group_iter:
            # copy the data
            pack_obj = index_map[index]
            transport, path = pack_obj.access_tuple()
            try:
                reader = pack.make_readv_reader(transport, path, readv_vector)
            except _mod_transport.NoSuchFile:
                if self._reload_func is not None:
                    self._reload_func()
                raise
            for (names, read_func), (key, eol_flag, references) in zip(
                reader.iter_records(), node_vector, strict=False
            ):
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
                pos, size = writer.add_bytes_record([raw_data], len(raw_data), names)
                write_index.add_node(key, eol_flag + b"%d %d" % (pos, size), references)
                pb.update("Copied record", record_index)
                record_index += 1

    def _process_inventory_lines(self, inv_lines):
        """Use up the inv_lines generator and setup a text key filter."""
        repo = self._pack_collection.repo
        fileid_revisions = repo._find_file_ids_from_xml_inventory_lines(
            inv_lines, self.revision_keys
        )
        text_filter = []
        for fileid, file_revids in fileid_revisions.items():
            text_filter.extend([(fileid, file_revid) for file_revid in file_revids])
        self._text_filter = text_filter

    def _copy_inventory_texts(self):
        # select inventory keys
        inv_keys = self._revision_keys  # currently the same keyspace, and note that
        # querying for keys here could introduce a bug where an inventory item
        # is missed, so do not change it to query separately without cross
        # checking like the text key check below.
        inventory_index_map, inventory_indices = self._pack_map_and_index_list(
            "inventory_index"
        )
        inv_nodes = self._index_contents(inventory_indices, inv_keys)
        # copy inventory keys and adjust values
        # XXX: Should be a helper function to allow different inv representation
        # at this point.
        self.pb.update("Copying inventory texts", 2)
        total_items, readv_group_iter = self._least_readv_node_readv(inv_nodes)
        # Only grab the output lines if we will be processing them
        output_lines = bool(self.revision_ids)
        inv_lines = self._copy_nodes_graph(
            inventory_index_map,
            self.new_pack._writer,
            self.new_pack.inventory_index,
            readv_group_iter,
            total_items,
            output_lines=output_lines,
        )
        if self.revision_ids:
            self._process_inventory_lines(inv_lines)
        else:
            # eat the iterator to cause it to execute.
            list(inv_lines)
            self._text_filter = None
        if debug.debug_flag_enabled("pack"):
            trace.mutter(
                "%s: create_pack: inventories copied: %s%s %d items t+%6.3fs",
                time.ctime(),
                self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.inventory_index.key_count(),
                time.time() - self.new_pack.start_time,
            )

    def _update_pack_order(self, entries, index_to_pack_map):
        """Determine how we want our packs to be ordered.

        This changes the sort order of the self.packs list so that packs unused
        by 'entries' will be at the end of the list, so that future requests
        can avoid probing them.  Used packs will be at the front of the
        self.packs list, in the order of their first use in 'entries'.

        :param entries: A list of (index, ...) tuples
        :param index_to_pack_map: A mapping from index objects to pack objects.
        """
        packs = []
        seen_indexes = set()
        for entry in entries:
            index = entry[0]
            if index not in seen_indexes:
                packs.append(index_to_pack_map[index])
                seen_indexes.add(index)
        if len(packs) == len(self.packs):
            if debug.debug_flag_enabled("pack"):
                trace.mutter("Not changing pack list, all packs used.")
            return
        seen_packs = set(packs)
        for pack in self.packs:
            if pack not in seen_packs:
                packs.append(pack)
                seen_packs.add(pack)
        if debug.debug_flag_enabled("pack"):
            old_names = [p.access_tuple()[1] for p in self.packs]
            new_names = [p.access_tuple()[1] for p in packs]
            trace.mutter("Reordering packs\nfrom: %s\n  to: %s", old_names, new_names)
        self.packs = packs

    def _copy_revision_texts(self):
        # select revisions
        if self.revision_ids:
            revision_keys = [(revision_id,) for revision_id in self.revision_ids]
        else:
            revision_keys = None
        # select revision keys
        revision_index_map, revision_indices = self._pack_map_and_index_list(
            "revision_index"
        )
        revision_nodes = self._index_contents(revision_indices, revision_keys)
        revision_nodes = list(revision_nodes)
        self._update_pack_order(revision_nodes, revision_index_map)
        # copy revision keys and adjust values
        self.pb.update("Copying revision texts", 1)
        total_items, readv_group_iter = self._revision_node_readv(revision_nodes)
        list(
            self._copy_nodes_graph(
                revision_index_map,
                self.new_pack._writer,
                self.new_pack.revision_index,
                readv_group_iter,
                total_items,
            )
        )
        if debug.debug_flag_enabled("pack"):
            trace.mutter(
                "%s: create_pack: revisions copied: %s%s %d items t+%6.3fs",
                time.ctime(),
                self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.revision_index.key_count(),
                time.time() - self.new_pack.start_time,
            )
        self._revision_keys = revision_keys

    def _get_text_nodes(self):
        text_index_map, text_indices = self._pack_map_and_index_list("text_index")
        return text_index_map, self._index_contents(text_indices, self._text_filter)

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
            present_text_keys = {_node[1] for _node in text_nodes}
            missing_text_keys = set(self._text_filter) - present_text_keys
            if missing_text_keys:
                # TODO: raise a specific error that can handle many missing
                # keys.
                trace.mutter("missing keys during fetch: %r", missing_text_keys)
                a_missing_key = missing_text_keys.pop()
                raise errors.RevisionNotPresent(a_missing_key[1], a_missing_key[0])
        # copy text keys and adjust values
        self.pb.update("Copying content texts", 3)
        total_items, readv_group_iter = self._least_readv_node_readv(text_nodes)
        list(
            self._copy_nodes_graph(
                text_index_map,
                self.new_pack._writer,
                self.new_pack.text_index,
                readv_group_iter,
                total_items,
            )
        )
        self._log_copied_texts()

    def _create_pack_from_packs(self):
        self.pb.update("Opening pack", 0, 5)
        self.new_pack = self.open_pack()
        new_pack = self.new_pack
        # buffer data - we won't be reading-back during the pack creation and
        # this makes a significant difference on sftp pushes.
        new_pack.set_write_cache_size(1024 * 1024)
        if debug.debug_flag_enabled("pack"):
            plain_pack_list = [
                f"{a_pack.pack_transport.base}{a_pack.name}" for a_pack in self.packs
            ]
            if self.revision_ids is not None:
                rev_count = len(self.revision_ids)
            else:
                rev_count = "all"
            trace.mutter(
                "%s: create_pack: creating pack from source packs: "
                "%s%s %s revisions wanted %s t=0",
                time.ctime(),
                self._pack_collection._upload_transport.base,
                new_pack.random_name,
                plain_pack_list,
                rev_count,
            )
        self._copy_revision_texts()
        self._copy_inventory_texts()
        self._copy_text_texts()
        # select signature keys
        signature_filter = self._revision_keys  # same keyspace
        signature_index_map, signature_indices = self._pack_map_and_index_list(
            "signature_index"
        )
        signature_nodes = self._index_contents(signature_indices, signature_filter)
        # copy signature keys and adjust values
        self.pb.update("Copying signature texts", 4)
        self._copy_nodes(
            signature_nodes,
            signature_index_map,
            new_pack._writer,
            new_pack.signature_index,
        )
        if debug.debug_flag_enabled("pack"):
            trace.mutter(
                "%s: create_pack: revision signatures copied: %s%s %d items t+%6.3fs",
                time.ctime(),
                self._pack_collection._upload_transport.base,
                new_pack.random_name,
                new_pack.signature_index.key_count(),
                time.time() - new_pack.start_time,
            )
        new_pack._check_references()
        if not self._use_pack(new_pack):
            new_pack.abort()
            return None
        self.pb.update("Finishing pack", 5)
        new_pack.finish()
        self._pack_collection.allocate(new_pack)
        return new_pack

    def _least_readv_node_readv(self, nodes):
        """Generate request groups for nodes using the least readv's.

        :param nodes: An iterable of graph index nodes.
        :return: Total node count and an iterator of the data needed to perform
            readvs to obtain the data for nodes. Each item yielded by the
            iterator is a tuple with:
            index, readv_vector, node_vector. readv_vector is a list ready to
            hand to the transport readv method, and node_vector is a list of
            (key, eol_flag, references) for the node retrieved by the
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
        for index, items in request_groups.items():
            pack_readv_requests = []
            for key, value, references in items:
                # ---- KnitGraphIndex.get_position
                bits = value[1:].split(b" ")
                offset, length = int(bits[0]), int(bits[1])
                pack_readv_requests.append(
                    ((offset, length), (key, value[0:1], references))
                )
            # linear scan up the pack to maximum range combining.
            pack_readv_requests.sort()
            # split out the readv and the node data.
            pack_readv = [readv for readv, node in pack_readv_requests]
            node_vector = [node for readv, node in pack_readv_requests]
            result.append((index, pack_readv, node_vector))
        return total, result

    def _revision_node_readv(self, revision_nodes):
        """Return the total revisions and the readv's to issue.

        :param revision_nodes: The revision index contents for the packs being
            incorporated into the new pack.
        :return: As per _least_readv_node_readv.
        """
        return self._least_readv_node_readv(revision_nodes)


class KnitReconcilePacker(KnitPacker):
    """A packer which regenerates indices etc as it copies.

    This is used by ``brz reconcile`` to cause parent text pointers to be
    regenerated.
    """

    def __init__(self, *args, **kwargs):
        """Initialize a KnitReconcilePacker.

        Args:
            *args: Arguments passed to parent class.
            **kwargs: Keyword arguments passed to parent class.
        """
        super().__init__(*args, **kwargs)
        self._data_changed = False

    def _process_inventory_lines(self, inv_lines):
        """Generate a text key reference map rather for reconciling with."""
        repo = self._pack_collection.repo
        refs = repo._inventory_serializer._find_text_key_references(inv_lines)
        self._text_refs = refs
        # during reconcile we:
        #  - convert unreferenced texts to full texts
        #  - correct texts which reference a text not copied to be full texts
        #  - copy all others as-is but with corrected parents.
        #  - so at this point we don't know enough to decide what becomes a full
        #    text.
        self._text_filter = None

    def _copy_text_texts(self):
        """Generate what texts we should have and then copy."""
        self.pb.update("Copying content texts", 3)
        # we have three major tasks here:
        # 1) generate the ideal index
        repo = self._pack_collection.repo
        ancestors = {
            key[0]: tuple(ref[0] for ref in refs[0])
            for _1, key, _2, refs in self.new_pack.revision_index.iter_all_entries()
        }
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
                    ok_nodes.append(
                        (node[0], node[1], node[2], (ideal_parents, node[3][1]))
                    )
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
        list(
            self._copy_nodes_graph(
                text_index_map,
                self.new_pack._writer,
                self.new_pack.text_index,
                readv_group_iter,
                total_items,
            )
        )
        # 4) adhoc copy all the other texts.
        # We have to topologically insert all texts otherwise we can fail to
        # reconcile when parts of a single delta chain are preserved intact,
        # and other parts are not. E.g. Discarded->d1->d2->d3. d1 will be
        # reinserted, and if d3 has incorrect parents it will also be
        # reinserted. If we insert d3 first, d2 is present (as it was bulk
        # copied), so we will try to delta, but d2 is not currently able to be
        # extracted because its basis d1 is not present. Topologically sorting
        # addresses this. The following generates a sort for all the texts that
        # are being inserted without having to reference the entire text key
        # space (we only topo sort the revisions, which is smaller).
        topo_order = tsort.topo_sort(ancestors)
        rev_order = dict(zip(topo_order, range(len(topo_order)), strict=False))
        bad_texts.sort(key=lambda key: rev_order.get(key[0][1], 0))
        repo.get_transaction()
        GraphIndexPrefixAdapter(
            self.new_pack.text_index,
            ("blank",),
            1,
            add_nodes_callback=self.new_pack.text_index.add_nodes,
        )
        data_access = _DirectPackAccess(
            {self.new_pack.text_index: self.new_pack.access_tuple()}
        )
        data_access.set_writer(
            self.new_pack._writer,
            self.new_pack.text_index,
            self.new_pack.access_tuple(),
        )
        output_texts = KnitVersionedFiles(
            _KnitGraphIndex(
                self.new_pack.text_index,
                add_callback=self.new_pack.text_index.add_nodes,
                deltas=True,
                parents=True,
                is_locked=repo.is_locked,
            ),
            data_access=data_access,
            max_delta_chain=200,
        )
        for key, parent_keys in bad_texts:
            # We refer to the new pack to delta data being output.
            # A possible improvement would be to catch errors on short reads
            # and only flush then.
            self.new_pack.flush()
            parents = []
            for parent_key in parent_keys:
                if parent_key[0] != key[0]:
                    # Graph parents must match the fileid
                    raise errors.BzrError(
                        f"Mismatched key parent {key!r}:{parent_keys!r}"
                    )
                parents.append(parent_key[1])
            text_lines = next(
                repo.texts.get_record_stream([key], "unordered", True)
            ).get_bytes_as("lines")
            output_texts.add_lines(
                key, parent_keys, text_lines, random_id=True, check_content=False
            )
        # 5) check that nothing inserted has a reference outside the keyspace.
        missing_text_keys = self.new_pack.text_index._external_references()
        if missing_text_keys:
            raise errors.BzrCheckError(
                f"Reference to missing compression parents {missing_text_keys!r}"
            )
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


class OptimisingKnitPacker(KnitPacker):
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
            bits = value[1:].split(b" ")
            offset, length = int(bits[0]), int(bits[1])
            requests.append(
                (index, [(offset, length)], [(key, value[0:1], references)])
            )
        # TODO: combine requests in the same index that are in ascending order.
        return total, requests

    def open_pack(self):
        """Open a pack for the pack we are creating."""
        new_pack = super().open_pack()
        # Turn on the optimization flags for all the index builders.
        new_pack.revision_index.set_optimize(for_size=True)
        new_pack.inventory_index.set_optimize(for_size=True)
        new_pack.text_index.set_optimize(for_size=True)
        new_pack.signature_index.set_optimize(for_size=True)
        return new_pack


class KnitRepositoryPackCollection(RepositoryPackCollection):
    """A knit pack collection."""

    pack_factory = NewPack
    resumed_pack_factory = ResumedPack
    normal_packer_class = KnitPacker
    optimising_packer_class = OptimisingKnitPacker

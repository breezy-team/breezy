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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    bzrdir,
    revision as _mod_revision,
    xml5,
    xml6,
    xml7,
    )
from bzrlib.knit import (
    _KnitGraphIndex,
    KnitPlainFactory,
    KnitVersionedFiles,
    )
""")

from bzrlib import (
    btree_index,
    )
from bzrlib.index import (
    GraphIndex,
    InMemoryGraphIndex,
    )
from bzrlib.repofmt.knitrepo import (
    KnitRepository,
    )
from bzrlib.repofmt.pack_repo import (
    RepositoryFormatPack,
    Packer,
    PackCommitBuilder,
    PackRepository,
    PackRootCommitBuilder,
    RepositoryPackCollection,
    )
from bzrlib.repository import (
    StreamSource,
    )


class KnitPackRepository(PackRepository):

    def __init__(self, _format, a_bzrdir, control_files, _commit_builder_class,
        _serializer):
        KnitRepository.__init__(self, _format, a_bzrdir, control_files,
            _commit_builder_class, _serializer)
        if self._format.supports_chks:
            raise AssertionError("chk not supported")
        index_transport = self._transport.clone('indices')
        self._pack_collection = RepositoryPackCollection(self, self._transport,
            index_transport,
            self._transport.clone('upload'),
            self._transport.clone('packs'),
            _format.index_builder_class,
            _format.index_class,
            use_chk_index=self._format.supports_chks,
            )
        self.inventories = KnitVersionedFiles(
            _KnitGraphIndex(self._pack_collection.inventory_index.combined_index,
                add_callback=self._pack_collection.inventory_index.add_callback,
                deltas=True, parents=True, is_locked=self.is_locked),
            data_access=self._pack_collection.inventory_index.data_access,
            max_delta_chain=200)
        self.revisions = KnitVersionedFiles(
            _KnitGraphIndex(self._pack_collection.revision_index.combined_index,
                add_callback=self._pack_collection.revision_index.add_callback,
                deltas=False, parents=True, is_locked=self.is_locked,
                track_external_parent_refs=True),
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
    def _serializer(self):
        return xml5.serializer_v5
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

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
    experimental = True
    supports_tree_reference = True
    @property
    def _serializer(self):
        return xml7.serializer_v7
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'pack-0.92-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

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
    @property
    def _serializer(self):
        return xml6.serializer_v6
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'rich-root-pack')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

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
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    @property
    def _serializer(self):
        return xml5.serializer_v5

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('1.6')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 5 (adds stacking support, requires bzr 1.6)"


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
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    @property
    def _serializer(self):
        return xml6.serializer_v6

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            '1.6.1-rich-root')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

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

    supports_external_lookups = True
    # What index classes to use
    index_builder_class = InMemoryGraphIndex
    index_class = GraphIndex

    @property
    def _serializer(self):
        return xml7.serializer_v7

    def _get_matching_bzrdir(self):
        matching = bzrdir.format_registry.make_bzrdir(
            '1.6.1-rich-root')
        matching.repository_format = self
        return matching

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n"

    def get_format_description(self):
        return ("Packs 5 rich-root (adds stacking support, requires bzr 1.6)"
                " (deprecated)")

    def is_deprecated(self):
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
    def _serializer(self):
        return xml5.serializer_v5

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('1.9')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack6 (bzr 1.9)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Packs 6 (uses btree indexes, requires bzr 1.9)"


class RepositoryFormatKnitPack6RichRoot(RepositoryFormatPack):
    """A repository with rich roots, no subtrees, stacking and btree indexes.

    1.6-rich-root with B+Tree indices.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    supports_tree_reference = False # no subtrees
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = btree_index.BTreeBuilder
    index_class = btree_index.BTreeGraphIndex

    @property
    def _serializer(self):
        return xml6.serializer_v6

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            '1.9-rich-root')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar RepositoryFormatKnitPack6RichRoot (bzr 1.9)\n"

    def get_format_description(self):
        return "Packs 6 rich-root (uses btree indexes, requires bzr 1.9)"


class RepositoryFormatPackDevelopment2Subtree(RepositoryFormatPack):
    """A subtrees development repository.

    This format should be retained in 2.3, to provide an upgrade path from this
    to RepositoryFormat2aSubtree.  It can be removed in later releases.

    1.6.1-subtree[as it might have been] with B+Tree indices.
    """

    repository_class = KnitPackRepository
    _commit_builder_class = PackRootCommitBuilder
    rich_root_data = True
    experimental = True
    supports_tree_reference = True
    supports_external_lookups = True
    # What index classes to use
    index_builder_class = btree_index.BTreeBuilder
    index_class = btree_index.BTreeGraphIndex

    @property
    def _serializer(self):
        return xml7.serializer_v7

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir(
            'development5-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return ("Bazaar development format 2 with subtree support "
            "(needs bzr.dev from before 1.8)\n")

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return ("Development repository format, currently the same as "
            "1.6.1-subtree with B+Tree indices.\n")


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
        super(KnitPackStreamSource, self).__init__(from_repository, to_format)
        self._text_keys = None
        self._text_fetch_order = 'unordered'

    def _get_filtered_inv_stream(self, revision_ids):
        from_repo = self.from_repository
        parent_ids = from_repo._find_parent_ids_of_revisions(revision_ids)
        parent_keys = [(p,) for p in parent_ids]
        find_text_keys = from_repo._serializer._find_text_key_references
        parent_text_keys = set(find_text_keys(
            from_repo._inventory_xml_lines_for_keys(parent_keys)))
        content_text_keys = set()
        knit = KnitVersionedFiles(None, None)
        factory = KnitPlainFactory()
        def find_text_keys_from_content(record):
            if record.storage_kind not in ('knit-delta-gz', 'knit-ft-gz'):
                raise ValueError("Unknown content storage kind for"
                    " inventory text: %s" % (record.storage_kind,))
            # It's a knit record, it has a _raw_record field (even if it was
            # reconstituted from a network stream).
            raw_data = record._raw_record
            # read the entire thing
            revision_id = record.key[-1]
            content, _ = knit._parse_record(revision_id, raw_data)
            if record.storage_kind == 'knit-delta-gz':
                line_iterator = factory.get_linedelta_content(content)
            elif record.storage_kind == 'knit-ft-gz':
                line_iterator = factory.get_fulltext_content(content)
            content_text_keys.update(find_text_keys(
                [(line, revision_id) for line in line_iterator]))
        revision_keys = [(r,) for r in revision_ids]
        def _filtered_inv_stream():
            source_vf = from_repo.inventories
            stream = source_vf.get_record_stream(revision_keys,
                                                 'unordered', False)
            for record in stream:
                if record.storage_kind == 'absent':
                    raise errors.NoSuchRevision(from_repo, record.key)
                find_text_keys_from_content(record)
                yield record
            self._text_keys = content_text_keys - parent_text_keys
        return ('inventories', _filtered_inv_stream())

    def _get_text_stream(self):
        # Note: We know we don't have to handle adding root keys, because both
        # the source and target are the identical network name.
        text_stream = self.from_repository.texts.get_record_stream(
                        self._text_keys, self._text_fetch_order, False)
        return ('texts', text_stream)

    def get_stream(self, search):
        revision_ids = search.get_keys()
        for stream_info in self._fetch_revision_texts(revision_ids):
            yield stream_info
        self._revision_keys = [(rev_id,) for rev_id in revision_ids]
        yield self._get_filtered_inv_stream(revision_ids)
        yield self._get_text_stream()


class KnitPacker(Packer):
    """Packer that works with knit packs."""

    def __init__(self, pack_collection, packs, suffix, revision_ids=None,
                 reload_func=None):
        super(KnitPacker, self).__init__(pack_collection, packs, suffix,
                                          revision_ids=revision_ids,
                                          reload_func=reload_func)


class KnitReconcilePacker(KnitPacker):
    """A packer which regenerates indices etc as it copies.

    This is used by ``bzr reconcile`` to cause parent text pointers to be
    regenerated.
    """

    def __init__(self, *args, **kwargs):
        super(KnitReconcilePacker, self).__init__(*args, **kwargs)
        self._data_changed = False

    def _process_inventory_lines(self, inv_lines):
        """Generate a text key reference map rather for reconciling with."""
        repo = self._pack_collection.repo
        refs = repo._serializer._find_text_key_references(inv_lines)
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
        # extracted because its basis d1 is not present. Topologically sorting
        # addresses this. The following generates a sort for all the texts that
        # are being inserted without having to reference the entire text key
        # space (we only topo sort the revisions, which is smaller).
        topo_order = tsort.topo_sort(ancestors)
        rev_order = dict(zip(topo_order, range(len(topo_order))))
        bad_texts.sort(key=lambda key:rev_order.get(key[0][1], 0))
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
            text_lines = osutils.split_lines(repo.texts.get_record_stream(
                [key], 'unordered', True).next().get_bytes_as('fulltext'))
            output_texts.add_lines(key, parent_keys, text_lines,
                random_id=True, check_content=False)
        # 5) check that nothing inserted has a reference outside the keyspace.
        missing_text_keys = self.new_pack.text_index._external_references()
        if missing_text_keys:
            raise errors.BzrCheckError('Reference to missing compression parents %r'
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




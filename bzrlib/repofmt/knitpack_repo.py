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
    xml5,
    xml6,
    xml7,
    )
from bzrlib.knit import (
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
from bzrlib.repofmt.pack_repo import (
    RepositoryFormatPack,
    PackCommitBuilder,
    PackRepository,
    PackRootCommitBuilder,
    )
from bzrlib.repository import (
    StreamSource,
    )


class KnitPackRepository(PackRepository):

    def _get_source(self, to_format):
        if to_format.network_name() == self._format.network_name():
            return KnitPackStreamSource(self, to_format)
        return PackRepository._get_source(self, to_format)


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


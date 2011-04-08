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
    KnitPackRepository,
    PackCommitBuilder,
    PackRootCommitBuilder,
    )


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

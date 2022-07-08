# Copyright (C) 2006-2010 Canonical Ltd
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

"""RevisionTree - a Tree implementation backed by repository data for a revision."""

from . import (
    lock,
    iterablefile,
    revision,
    tree,
    )


class RevisionTree(tree.Tree):
    """Tree viewing a previous revision.

    File text can be retrieved from the text store.
    """

    def __init__(self, repository, revision_id):
        self._repository = repository
        self._revision_id = revision_id
        self._rules_searcher = None

    def has_versioned_directories(self):
        """See `Tree.has_versioned_directories`."""
        return self._repository._format.supports_versioned_directories

    def supports_tree_reference(self):
        return getattr(self._repository._format, "supports_tree_reference",
                       False)

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        A RevisionTree's parents match the revision graph.
        """
        if self._revision_id in (None, revision.NULL_REVISION):
            parent_ids = []
        else:
            parent_ids = self._repository.get_revision(
                self._revision_id).parent_ids
        return parent_ids

    def get_revision_id(self):
        """Return the revision id associated with this tree."""
        return self._revision_id

    def get_file_revision(self, path):
        """Return the revision id in which a file was last changed."""
        raise NotImplementedError(self.get_file_revision)

    def get_file_text(self, path):
        for (identifier, content) in self.iter_files_bytes([(path, None)]):
            return b"".join(content)

    def get_file(self, path):
        for (identifier, content) in self.iter_files_bytes([(path, None)]):
            return iterablefile.IterableFile(content)

    def is_locked(self):
        return self._repository.is_locked()

    def lock_read(self):
        self._repository.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def __repr__(self):
        return '<%s instance at %x, rev_id=%r>' % (
            self.__class__.__name__, id(self), self._revision_id)

    def unlock(self):
        self._repository.unlock()

    def _get_rules_searcher(self, default_searcher):
        """See Tree._get_rules_searcher."""
        if self._rules_searcher is None:
            self._rules_searcher = super(RevisionTree,
                                         self)._get_rules_searcher(default_searcher)
        return self._rules_searcher

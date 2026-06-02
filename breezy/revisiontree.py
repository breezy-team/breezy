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

from . import lock, osutils, revision, tree


class RevisionTree(tree.Tree):
    """Tree viewing a previous revision.

    File text can be retrieved from the text store.
    """

    def __init__(self, repository, revision_id):
        """Initialize a RevisionTree.

        Args:
            repository: The repository containing the revision.
            revision_id: The ID of the revision to view.
        """
        self._repository = repository
        self._revision_id = revision_id
        self._rules_searcher = None

    def has_versioned_directories(self):
        """See `Tree.has_versioned_directories`."""
        return self._repository._format.supports_versioned_directories

    def supports_tree_reference(self):
        """Check if tree references are supported.

        Returns:
            True if tree references are supported, False otherwise.
        """
        return getattr(self._repository._format, "supports_tree_reference", False)

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        A RevisionTree's parents match the revision graph.
        """
        if self._revision_id in (None, revision.NULL_REVISION):
            parent_ids = []
        else:
            parent_ids = self._repository.get_revision(self._revision_id).parent_ids
        return parent_ids

    def get_revision_id(self):
        """Return the revision id associated with this tree."""
        return self._revision_id

    def get_file_revision(self, path):
        """Return the revision id in which a file was last changed."""
        raise NotImplementedError(self.get_file_revision)

    def get_file_text(self, path):
        """Get the text content of a file.

        Args:
            path: Path to the file.

        Returns:
            The file content as bytes.
        """
        for _identifier, content in self.iter_files_bytes([(path, None)]):
            return b"".join(content)

    def get_file(self, path):
        """Get a file-like object for the file content.

        Args:
            path: Path to the file.

        Returns:
            An IterableFile object containing the file content.
        """
        for _identifier, content in self.iter_files_bytes([(path, None)]):
            return osutils.IterableFile(content)

    def is_locked(self):
        """Check if the tree is locked.

        Returns:
            True if the underlying repository is locked, False otherwise.
        """
        return self._repository.is_locked()

    def lock_read(self):
        """Acquire a read lock on the tree.

        Returns:
            A LogicalLockResult that will unlock when used.
        """
        self._repository.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def __repr__(self):
        """Return string representation of the RevisionTree.

        Returns:
            String representation including class name, id, and revision id.
        """
        return "<{} instance at {:x}, rev_id={!r}>".format(
            self.__class__.__name__, id(self), self._revision_id
        )

    def unlock(self):
        """Release the lock on the tree."""
        self._repository.unlock()

    def _get_rules_searcher(self, default_searcher):
        """See Tree._get_rules_searcher."""
        if self._rules_searcher is None:
            self._rules_searcher = super()._get_rules_searcher(default_searcher)
        return self._rules_searcher

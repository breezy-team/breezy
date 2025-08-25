# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Basic push implementation."""

from ..push import PushResult
from .errors import GitSmartRemoteNotSupported


class GitPushResult(PushResult):
    """Push result for Git repositories.

    Extends the base PushResult class with Git-specific functionality
    for looking up revision numbers.
    """

    def _lookup_revno(self, revid):
        from .branch import _quick_lookup_revno

        try:
            return _quick_lookup_revno(self.source_branch, self.target_branch, revid)
        except GitSmartRemoteNotSupported:
            return None

    @property
    def old_revno(self):
        """Get the old revision number.

        Returns:
            The revision number of the old revision, or None if not available.
        """
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        """Get the new revision number.

        Returns:
            The revision number of the new revision, or None if not available.
        """
        return self._lookup_revno(self.new_revid)


class MissingObjectsIterator:
    """Iterate over git objects that are missing from a target repository."""

    def __init__(self, store, source, pb=None):
        """Create a new missing objects iterator."""
        self.source = source
        self._object_store = store
        self._pending = []
        self.pb = pb

    def import_revisions(self, revids, lossy):
        """Import a set of revisions into this git repository.

        :param revids: Revision ids of revisions to import
        :param lossy: Whether to not roundtrip bzr metadata
        """
        for i, revid in enumerate(revids):
            if self.pb:
                self.pb.update("pushing revisions", i, len(revids))
            git_commit = self.import_revision(revid, lossy)
            yield (revid, git_commit)

    def import_revision(self, revid, lossy):
        """Import a revision into this Git repository.

        :param revid: Revision id of the revision
        :param roundtrip: Whether to roundtrip bzr metadata
        """
        tree = self._object_store.tree_cache.revision_tree(revid)
        rev = self.source.get_revision(revid)
        commit = None
        for path, obj in self._object_store._revision_to_objects(rev, tree, lossy):
            if obj.type_name == b"commit":
                commit = obj
            self._pending.append((obj, path))
        if commit is None:
            raise AssertionError(f"no commit object generated for revision {revid}")
        return commit.id

    def __len__(self):
        """Return the number of pending objects."""
        return len(self._pending)

    def __iter__(self):
        """Return an iterator over pending objects."""
        return iter(self._pending)


class ObjectStoreParentsProvider:
    """Provides parent information for Git objects in a store."""

    def __init__(self, store):
        """Initialize the ObjectStoreParentsProvider.

        Args:
            store: Git object store to query for parent information.
        """
        self._store = store

    def get_parent_map(self, shas):
        """Get parent information for the specified SHAs.

        Args:
            shas: Sequence of Git object SHAs to get parents for.

        Returns:
            Dictionary mapping each SHA to its parent SHAs.
        """
        ret = {}
        for sha in shas:
            if sha is None:
                parents = []
            else:
                try:
                    parents = self._store[sha].parents
                except KeyError:
                    parents = None
            ret[sha] = parents
        return ret


def remote_divergence(old_sha, new_sha, store):
    """Check if the remote branch has diverged.

    Args:
        old_sha: The old SHA (can be None).
        new_sha: The new SHA.
        store: Git object store.

    Returns:
        True if the remote has diverged, False otherwise.

    Raises:
        TypeError: If SHA arguments are not bytes or None.
    """
    if old_sha is None:
        return False
    if not isinstance(old_sha, bytes):
        raise TypeError(old_sha)
    if not isinstance(new_sha, bytes):
        raise TypeError(new_sha)
    from ..graph import Graph

    graph = Graph(ObjectStoreParentsProvider(store))
    return not graph.is_ancestor(old_sha, new_sha)

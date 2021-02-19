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

from ..push import (
    PushResult,
    )
from .errors import (
    GitSmartRemoteNotSupported,
    )


class GitPushResult(PushResult):

    def _lookup_revno(self, revid):
        from .branch import _quick_lookup_revno
        try:
            return _quick_lookup_revno(self.source_branch, self.target_branch,
                                       revid)
        except GitSmartRemoteNotSupported:
            return None

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class MissingObjectsIterator(object):
    """Iterate over git objects that are missing from a target repository.

    """

    def __init__(self, store, source, pb=None):
        """Create a new missing objects iterator.

        """
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
        for path, obj in self._object_store._revision_to_objects(
                rev, tree, lossy):
            if obj.type_name == b"commit":
                commit = obj
            self._pending.append((obj, path))
        if commit is None:
            raise AssertionError("no commit object generated for revision %s" %
                                 revid)
        return commit.id

    def __len__(self):
        return len(self._pending)

    def __iter__(self):
        return iter(self._pending)


class ObjectStoreParentsProvider(object):

    def __init__(self, store):
        self._store = store

    def get_parent_map(self, shas):
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
    if old_sha is None:
        return False
    if not isinstance(old_sha, bytes):
        raise TypeError(old_sha)
    if not isinstance(new_sha, bytes):
        raise TypeError(new_sha)
    from breezy.graph import Graph
    graph = Graph(ObjectStoreParentsProvider(store))
    return not graph.is_ancestor(old_sha, new_sha)

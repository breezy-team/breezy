# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Annotate."""

from dulwich.object_store import tree_lookup_path

from .. import osutils
from ..bzr.versionedfile import UnavailableRepresentation
from ..errors import NoSuchRevision
from ..graph import Graph
from ..revision import NULL_REVISION
from .mapping import decode_git_path, encode_git_path


class GitBlobContentFactory:
    """Static data content factory.

    This takes a fulltext when created and just returns that during
    get_bytes_as('fulltext').

    :ivar sha1: None, or the sha1 of the content fulltext.
    :ivar storage_kind: The native storage kind of this factory. Always
        'fulltext'.
    :ivar key: The key of this content. Each key is a tuple with a single
        string in it.
    :ivar parents: A tuple of parent keys for self.key. If the object has
        no parent information, None (as opposed to () for an empty list of
        parents).
    """

    def __init__(self, store, path, revision, blob_id):
        """Create a ContentFactory."""
        self.store = store
        self.key = (path, revision)
        self.storage_kind = "git-blob"
        self.parents = None
        self.blob_id = blob_id
        self.size = None

    def get_bytes_as(self, storage_kind):
        if storage_kind == "fulltext":
            return self.store[self.blob_id].as_raw_string()
        elif storage_kind == "lines":
            return list(
                osutils.chunks_to_lines(self.store[self.blob_id].as_raw_chunks())
            )
        elif storage_kind == "chunked":
            return self.store[self.blob_id].as_raw_chunks()
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)

    def iter_bytes_as(self, storage_kind):
        if storage_kind == "lines":
            return iter(
                osutils.chunks_to_lines(self.store[self.blob_id].as_raw_chunks())
            )
        elif storage_kind == "chunked":
            return iter(self.store[self.blob_id].as_raw_chunks())
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)


class GitAbsentContentFactory:
    """Absent data content factory.

    :ivar sha1: None, or the sha1 of the content fulltext.
    :ivar storage_kind: The native storage kind of this factory. Always
        'fulltext'.
    :ivar key: The key of this content. Each key is a tuple with a single
        string in it.
    :ivar parents: A tuple of parent keys for self.key. If the object has
        no parent information, None (as opposed to () for an empty list of
        parents).
    """

    def __init__(self, store, path, revision):
        """Create a ContentFactory."""
        self.store = store
        self.key = (path, revision)
        self.storage_kind = "absent"
        self.parents = None
        self.size = None

    def get_bytes_as(self, storage_kind):
        raise ValueError

    def iter_bytes_as(self, storage_kind):
        raise ValueError


class AnnotateProvider:
    def __init__(self, change_scanner):
        self.change_scanner = change_scanner
        self.store = self.change_scanner.repository._git.object_store

    def _get_parents(self, path, text_revision):
        commit_id, _mapping = self.change_scanner.repository.lookup_bzr_revision_id(
            text_revision
        )
        text_parents = []
        path = encode_git_path(path)
        for commit_parent in self.store[commit_id].parents:
            try:
                (_store, path, text_parent) = (
                    self.change_scanner.find_last_change_revision(path, commit_parent)
                )
            except KeyError:
                continue
            if text_parent not in text_parents:
                text_parents.append(text_parent)
        return tuple(
            [
                (
                    decode_git_path(path),
                    self.change_scanner.repository.lookup_foreign_revision_id(p),
                )
                for p in text_parents
            ]
        )

    def get_parent_map(self, keys):
        ret = {}
        for key in keys:
            (path, text_revision) = key
            if text_revision == NULL_REVISION:
                ret[key] = ()
                continue
            try:
                ret[key] = self._get_parents(path, text_revision)
            except KeyError:
                pass
        return ret

    def get_record_stream(self, keys, ordering, include_delta_closure):
        if ordering == "topological":
            graph = Graph(self)
            keys = graph.iter_topo_order(keys)
        store = self.change_scanner.repository._git.object_store
        for path, text_revision in keys:
            try:
                commit_id, _mapping = (
                    self.change_scanner.repository.lookup_bzr_revision_id(text_revision)
                )
            except NoSuchRevision:
                yield GitAbsentContentFactory(store, path, text_revision)
                continue

            try:
                tree_id = store[commit_id].tree
            except KeyError:
                yield GitAbsentContentFactory(store, path, text_revision)
                continue
            try:
                (_mode, blob_sha) = tree_lookup_path(
                    store.__getitem__, tree_id, encode_git_path(path)
                )
            except KeyError:
                yield GitAbsentContentFactory(store, path, text_revision)
            else:
                yield GitBlobContentFactory(store, path, text_revision, blob_sha)

# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from dulwich.object_store import (
    tree_lookup_path,
    )
from dulwich.objects import (
    Blob,
    Commit,
    Tree,
    )

from bzrlib import (
    annotate,
    )

from bzrlib.versionedfile import (
    AbsentContentFactory,
    ChunkedContentFactory,
    VersionedFiles,
    )


class GitRevisions(VersionedFiles):

    def __init__(self, repository, object_store):
        self.repository = repository
        self.object_store = object_store

    def check(self, progressbar=None):
        return True

    def get_annotator(self):
        return annotate.Annotator(self)

    def iterkeys(self):
        for sha in self.object_store:
            if isinstance(self.object_store[sha], Commit):
                yield (sha,)

    def keys(self):
        return list(self.iterkeys())

    def add_mpdiffs(self, records):
        raise NotImplementedError(self.add_mpdiffs)

    def get_record_stream(self, keys, ordering, include_delta_closure):
        for key in keys:
            (revid,) = key
            (commit_id, mapping) = self.repository.lookup_bzr_revision_id(revid)
            try:
                commit = self.object_store[commit_id]
            except KeyError:
                yield AbsentContentFactory(key)
            else:
                yield ChunkedContentFactory(key, 
                    tuple([(self.repository.lookup_foreign_revision_id(p, mapping),) for p in commit.parents]), None, 
                    commit.as_raw_chunks())

    def get_parent_map(self, keys):
        ret = {}
        for (revid,) in keys:
            (commit_id, mapping) = self.repository.lookup_bzr_revision_id(revid)
            try:
                ret[(revid,)] = [(self.repository.lookup_foreign_revision_id(p, mapping),) for p in self.object_store[commit_id].parents]
            except KeyError:
                ret[(revid,)] = None
        return ret


class GitTexts(VersionedFiles):
    """A texts VersionedFiles instance that is backed onto a Git object store."""

    def __init__(self, repository):
        self.repository = repository
        self.object_store = self.repository._git.object_store

    def check(self, progressbar=None):
        return True

    def get_annotator(self):
        return annotate.Annotator(self)

    def add_mpdiffs(self, records):
        raise NotImplementedError(self.add_mpdiffs)

    def get_record_stream(self, keys, ordering, include_delta_closure):
        for key in keys:
            (fileid, revid) = key
            (commit_id, mapping) = self.repository.lookup_bzr_revision_id(revid)
            root_tree = self.object_store[commit_id].tree
            path = mapping.parse_file_id(fileid)
            try:
                obj = tree_lookup_path(
                    self.object_store.__getitem__, root_tree, path)
                if isinstance(obj, tuple):
                    (mode, item_id) = obj
                    obj = self.object_store[item_id]
            except KeyError:
                yield AbsentContentFactory(key)
            else:
                if isinstance(obj, Tree):
                    yield ChunkedContentFactory(key, None, None, [])
                elif isinstance(obj, Blob):
                    yield ChunkedContentFactory(key, None, None, obj.chunked)
                else:
                    raise AssertionError("file text resolved to %r" % obj)

    def get_parent_map(self, keys):
        raise NotImplementedError(self.get_parent_map)


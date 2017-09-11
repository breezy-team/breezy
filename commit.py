# Copyright (C) 2009-2010 Jelmer Vernooij <jelmer@samba.org>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Support for committing in native Git working trees."""

from __future__ import absolute_import

from dulwich.index import (
    commit_tree,
    )
import os
import stat

from ... import (
    revision as _mod_revision,
    )
from ...errors import (
    RootMissing,
    )
from ...repository import (
    CommitBuilder,
    )

from dulwich.objects import (
    S_IFGITLINK,
    Blob,
    Commit,
    )
from dulwich.repo import Repo


from .mapping import (
    entry_mode,
    )
from .roundtrip import (
    CommitSupplement,
    inject_bzr_metadata,
    )


class GitCommitBuilder(CommitBuilder):
    """Commit builder for Git repositories."""

    supports_record_entry_contents = False

    def __init__(self, *args, **kwargs):
        super(GitCommitBuilder, self).__init__(*args, **kwargs)
        self.random_revid = True
        self._validate_revprops(self._revprops)
        self.store = self.repository._git.object_store
        self._blobs = {}
        self._any_changes = False
        self._override_fileids = {}
        self._mapping = self.repository.get_mapping()

    def any_changes(self):
        return self._any_changes

    def record_iter_changes(self, workingtree, basis_revid, iter_changes):
        def link_sha1(path, file_id):
            blob = Blob()
            blob.data = workingtree.get_symlink_target(file_id, path).encode("utf-8")
            self.store.add_object(blob)
            return blob.id
        def text_sha1(path, file_id):
            blob = Blob()
            blob.data = workingtree.get_file_text(file_id, path)
            self.store.add_object(blob)
            return blob.id
        def treeref_sha1(path, file_id):
            return Repo.open(os.path.join(workingtree.basedir, path)).head()
        seen_root = False
        for (file_id, path, changed_content, versioned, parent, name, kind,
             executable) in iter_changes:
            self._any_changes = True
            if kind[1] in ("directory",):
                if kind[0] in ("file", "symlink"):
                    self._blobs[path[0].encode("utf-8")] = None
                if path[1] == "":
                    seen_root = True
                continue
            if path[1] is None:
                self._blobs[path[0].encode("utf-8")] = None
                continue
            if kind[1] == "file":
                mode = stat.S_IFREG
                sha = text_sha1(path[1], file_id)
            elif kind[1] == "symlink":
                mode = stat.S_IFLNK
                sha = link_sha1(path[1], file_id)
            elif kind[1] == "tree-reference":
                mode = S_IFGITLINK
                sha = treeref_sha1(path[1], file_id)
            else:
                raise AssertionError("Unknown kind %r" % kind[1])
            if executable[1]:
                mode |= 0111
            encoded_new_path = path[1].encode("utf-8")
            self._blobs[encoded_new_path] = (mode, sha)
            file_sha1 = workingtree.get_file_sha1(file_id, path[1])
            if file_sha1 is None:
                # File no longer exists
                if path[0] is not None:
                    self._blobs[path[0].encode("utf-8")] = None
                continue
            _, st = workingtree.get_file_with_stat(file_id, path[1])
            yield file_id, path[1], (file_sha1, st)
            self._override_fileids[encoded_new_path] = file_id
        if not seen_root and len(self.parents) == 0:
            raise RootMissing()
        if getattr(workingtree, "basis_tree", False):
            basis_tree = workingtree.basis_tree()
        else:
            if len(self.parents) == 0:
                basis_revid = _mod_revision.NULL_REVISION
            else:
                basis_revid = self.parents[0]
            basis_tree = self.repository.revision_tree(basis_revid)
        # Fill in entries that were not changed
        for path, entry in basis_tree.iter_entries_by_dir():
            if entry.kind not in ("file", "symlink", "tree-reference"):
                continue
            if not path in self._blobs:
                if entry.kind == "symlink":
                    blob = Blob()
                    blob.data = basis_tree.get_symlink_target(entry.file_id,
                        path)
                    self._blobs[path.encode("utf-8")] = (entry_mode(entry), blob.id)
                elif entry.kind == "file":
                    blob = Blob()
                    blob.data = basis_tree.get_file_text(entry.file_id, path)
                    self._blobs[path.encode("utf-8")] = (entry_mode(entry), blob.id)
                else:
                    (mode, sha) = workingtree._lookup_entry(path.encode("utf-8"), update_index=True)
                    self._blobs[path.encode("utf-8")] = (sha, mode)
        if not self._lossy and self._mapping.BZR_FILE_IDS_FILE is not None:
            try:
                fileid_map = dict(basis_tree._fileid_map.file_ids)
            except AttributeError:
                fileid_map = {}
            for path, file_id in self._override_fileids.iteritems():
                assert type(path) == str
                if file_id is None:
                    del fileid_map[path]
                else:
                    assert type(file_id) == str
                    fileid_map[path] = file_id
            if fileid_map:
                fileid_blob = self._mapping.export_fileid_map(fileid_map)
                self.store.add_object(fileid_blob)
                self._blobs[self._mapping.BZR_FILE_IDS_FILE] = (stat.S_IFREG | 0644, fileid_blob.id)
            else:
                self._blobs[self._mapping.BZR_FILE_IDS_FILE] = None
        self.new_inventory = None

    def update_basis(self, tree):
        # Nothing to do here
        pass

    def finish_inventory(self):
        # eliminate blobs that were removed
        for path, entry in iter(self._blobs.items()):
            if entry is None:
                del self._blobs[path]

    def _iterblobs(self):
        return ((path, sha, mode) for (path, (mode, sha)) in self._blobs.iteritems())

    def commit(self, message):
        self._validate_unicode_text(message, 'commit message')
        c = Commit()
        c.parents = [self.repository.lookup_bzr_revision_id(revid)[0] for revid in self.parents]
        c.tree = commit_tree(self.store, self._iterblobs())
        c.encoding = 'utf-8'
        c.committer = self._committer.encode(c.encoding)
        c.author = self._revprops.get('author', self._committer).encode(c.encoding)
        if c.author != c.committer:
            self._revprops.remove("author")
        c.commit_time = int(self._timestamp)
        c.author_time = int(self._timestamp)
        c.commit_timezone = self._timezone
        c.author_timezone = self._timezone
        c.message = message.encode(c.encoding)
        if not self._lossy:
            commit_supplement = CommitSupplement()
            commit_supplement.revision_id = None
            commit_supplement.properties = self._revprops
            commit_supplement.explicit_parent_ids = self.parents
            if commit_supplement:
                c.message = inject_bzr_metadata(c.message, commit_supplement, "utf-8")

        assert len(c.id) == 40
        self.store.add_object(c)
        self.repository.commit_write_group()
        self._new_revision_id = self._mapping.revision_id_foreign_to_bzr(c.id)
        return self._new_revision_id

    def abort(self):
        self.repository.abort_write_group()

    def revision_tree(self):
        return self.repository.revision_tree(self._new_revision_id)

    def get_basis_delta(self):
        # TODO(jelmer): This shouldn't be called, it's for inventory deltas.
        return []

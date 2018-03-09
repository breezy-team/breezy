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

from ...bzr.inventory import (
    entry_factory,
    )
from ... import (
    osutils,
    revision as _mod_revision,
    )
from ...errors import (
    BzrError,
    RootMissing,
    UnsupportedOperation,
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
    object_mode,
    fix_person_identifier,
    )


class SettingCustomFileIdsUnsupported(UnsupportedOperation):

    _fmt = "Unable to store addition of file with custom file ids: %(file_ids)r"

    def __init__(self, file_ids):
        BzrError.__init__(self)
        self.file_ids = file_ids


class GitCommitBuilder(CommitBuilder):
    """Commit builder for Git repositories."""

    supports_record_entry_contents = False

    def __init__(self, *args, **kwargs):
        super(GitCommitBuilder, self).__init__(*args, **kwargs)
        self.random_revid = True
        self._validate_revprops(self._revprops)
        self.store = self.repository._git.object_store
        self._blobs = {}
        self._inv_delta = []
        self._any_changes = False
        self._override_fileids = {}
        self._mapping = self.repository.get_mapping()

    def any_changes(self):
        return self._any_changes

    def record_iter_changes(self, workingtree, basis_revid, iter_changes):
        def treeref_sha1(path, file_id):
            return Repo.open(os.path.join(workingtree.basedir, path)).head()
        seen_root = False
        for (file_id, path, changed_content, versioned, parent, name, kind,
             executable) in iter_changes:
            if kind[1] in ("directory",):
                self._inv_delta.append((path[0], path[1], file_id, entry_factory[kind[1]](file_id, name[1], parent[1])))
                if kind[0] in ("file", "symlink"):
                    self._blobs[path[0].encode("utf-8")] = None
                    self._any_changes = True
                if path[1] == "":
                    seen_root = True
                continue
            self._any_changes = True
            if path[1] is None:
                self._inv_delta.append((path[0], path[1], file_id, None))
                self._blobs[path[0].encode("utf-8")] = None
                continue
            try:
                entry_kls = entry_factory[kind[1]]
            except KeyError:
                raise KeyError("unknown kind %s" % kind[1])
            entry = entry_kls(file_id, name[1], parent[1])
            if kind[1] == "file":
                entry.executable = executable[1]
                blob = Blob()
                f, st = workingtree.get_file_with_stat(path[1], file_id)
                try:
                    blob.data = f.read()
                finally:
                    f.close()
                entry.text_size = len(blob.data)
                entry.text_sha1 = osutils.sha_string(blob.data)
                self.store.add_object(blob)
                sha = blob.id
            elif kind[1] == "symlink":
                symlink_target = workingtree.get_symlink_target(path[1], file_id)
                blob = Blob()
                blob.data = symlink_target.encode("utf-8")
                self.store.add_object(blob)
                sha = blob.id
                entry.symlink_target = symlink_target
                st = None
            elif kind[1] == "tree-reference":
                sha = treeref_sha1(path[1], file_id)
                reference_revision = workingtree.get_reference_revision(path[1], file_id)
                entry.reference_revision = reference_revision
                st = None
            else:
                raise AssertionError("Unknown kind %r" % kind[1])
            mode = object_mode(kind[1], executable[1])
            self._inv_delta.append((path[0], path[1], file_id, entry))
            encoded_new_path = path[1].encode("utf-8")
            self._blobs[encoded_new_path] = (mode, sha)
            if st is not None:
                yield file_id, path[1], (entry.text_sha1, st)
            if self._mapping.generate_file_id(encoded_new_path) != file_id:
                self._override_fileids[encoded_new_path] = file_id
            else:
                self._override_fileids[encoded_new_path] = None
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
            assert isinstance(path, unicode)
            if entry.kind == 'directory':
                continue
            encoded_path = path.encode('utf-8')
            if encoded_path not in self._blobs:
                if entry.kind == "symlink":
                    blob = Blob()
                    blob.data = basis_tree.get_symlink_target(path, entry.file_id).encode('utf-8')
                    self._blobs[encoded_path] = (entry_mode(entry), blob.id)
                elif entry.kind == "file":
                    blob = Blob()
                    blob.data = basis_tree.get_file_text(path, entry.file_id)
                    self._blobs[encoded_path] = (entry_mode(entry), blob.id)
                else:
                    (mode, sha) = workingtree._lookup_entry(encoded_path, update_index=True)
                    self._blobs[encoded_path] = (mode, sha)
        if not self._lossy:
            try:
                fileid_map = dict(basis_tree._fileid_map.file_ids)
            except AttributeError:
                fileid_map = {}
            for path, file_id in self._override_fileids.iteritems():
                assert type(path) == str
                if file_id is None:
                    if path in fileid_map:
                        del fileid_map[path]
                else:
                    assert type(file_id) == str
                    fileid_map[path] = file_id
            if fileid_map:
                fileid_blob = self._mapping.export_fileid_map(fileid_map)
            else:
                fileid_blob = None
            if fileid_blob is not None:
                if self._mapping.BZR_FILE_IDS_FILE is None:
                    raise SettingCustomFileIdsUnsupported(fileid_map)
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
        c.encoding = self._revprops.pop('git-explicit-encoding', 'utf-8')
        c.committer = fix_person_identifier(self._committer.encode(c.encoding))
        c.author = fix_person_identifier(self._revprops.pop('author', self._committer).encode(c.encoding))
        if self._revprops:
            raise NotImplementedError(self._revprops)
        c.commit_time = int(self._timestamp)
        c.author_time = int(self._timestamp)
        c.commit_timezone = self._timezone
        c.author_timezone = self._timezone
        c.message = message.encode(c.encoding)
        assert len(c.id) == 40
        self.store.add_object(c)
        self.repository.commit_write_group()
        self._new_revision_id = self._mapping.revision_id_foreign_to_bzr(c.id)
        return self._new_revision_id

    def abort(self):
        if self.repository.is_in_write_group():
            self.repository.abort_write_group()

    def revision_tree(self):
        return self.repository.revision_tree(self._new_revision_id)

    def get_basis_delta(self):
        for (oldpath, newpath, file_id, entry) in self._inv_delta:
            if entry is not None:
                entry.revision = self._new_revision_id
        return self._inv_delta

    def update_basis_by_delta(self, revid, delta):
        pass

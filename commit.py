# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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


from dulwich.index import (
    commit_tree,
    )
import stat

from bzrlib.repository import (
    CommitBuilder,
    )

from dulwich.objects import (
    Blob,
    Commit,
    Tree,
    )


class GitCommitBuilder(CommitBuilder):

    def __init__(self, *args, **kwargs):
        super(GitCommitBuilder, self).__init__(*args, **kwargs)
        self._blobs = {}

    def record_delete(self, path, file_id):
        self._blobs[path] = None

    def record_iter_changes(self, workingtree, basis_revid, iter_changes):
        index = getattr(workingtree, "index", None)
        if index is not None:
            def index_sha1(path, file_id):
                return index.get_sha1(path.encode("utf-8"))
            text_sha1 = link_sha1 = index_sha1
        else:
            def link_sha1(path, file_id):
                blob = Blob()
                blob.data = workingtree.get_symlink_target(file_id)
                return blob.id
            def text_sha1(path, file_id):
                blob = Blob()
                blob.data = workingtree.get_file_text(file_id, path)
                return blob.id
        for (file_id, path, changed_content, versioned, parent, name, kind, 
             executable) in iter_changes:
            if kind[1] in ("directory",):
                if kind[0] in ("file", "symlink"):
                    self.record_delete(path[0], file_id)
                continue
            if kind == "file":
                mode = stat.S_IFREG
                sha = text_sha1(path[1], file_id)
            else:
                mode = stat.S_IFLNK
                sha = link_sha1(path[1], file_id)
            if executable:
                mode |= 0111
            self._blobs[path[1].encode("utf-8")] = (mode, sha))
            yield file_id, path, (None, None)
        # FIXME: Import all blobs not set yet, and eliminate blobs set to None

    def commit(self, message):
        c = Commit()
        c.tree = commit_tree(self.repository._git.object_store, self._blobs)
        c.committer = self._committer
        c.author = self._revprops.get('author', self._committer)
        c.commit_timestamp = self._timestamp
        c.author_timestamp = self._timestamp
        c.commit_timezone = self._timezone
        c.author_timezone = self._timezone
        c.message = message.encode("utf-8")
        self.repository._git.object_store.add_object(c)
        return self.repository.mapping.revision_id_foreign_to_bzr(c.id)

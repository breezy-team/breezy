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

from bzrlib.repository import (
    CommitBuilder,
    )

from dulwich.objects import (
    Commit,
    Tree,
    )


class GitCommitBuilder(CommitBuilder):

    def __init__(self, *args, **kwargs):
        super(GitCommitBuilder, self).__init__(*args, **kwargs)
        self._trees = {}

    def _add_tree(self, path):
        dirname, basename = osutils.split(path)
        t = self._add_tree(dirname)
        if not basename in t:
            t[basename] = Tree()
            # FIXME: Inherit children from the base revision
        return t[basename]

    def _change_blob(self, path, value):
        dirname, basename = osutils.split(path)
        t = self._add_tree(dirname)
        t[basename] = value

    def record_delete(self, path, file_id):
        dirname, basename = osutils.split(path)
        t = self._add_tree(dirname)
        del t[basename]

    def record_iter_changes(self, workingtree, basis_revid, iter_changes):
        for (file_id, path, changed_content, versioned, parent, name, kind, 
             executable) in iter_changes:
            if kind[1] in ("directory",):
                if kind[0] in ("file", "symlink"):
                    self.record_delete(path[0], file_id)
                continue
            if kind == "file":
                mode = stat.S_IFREG
            else:
                mode = stat.S_IFLNK
            if executable:
                mode |= 0111
            self._change_blob(path, (mode, workingtree.index.get_sha1(path)))
            yield file_id, path, None

    def commit(self, message):
        # FIXME: Eliminate any empty trees recursively
        # Write any tree objects to disk
        for path in sorted(self._trees.keys(), reverse=True):
            self.repository._git.object_store.add_object(self._trees[path])
        c = Commit()
        root_tree = self._add_tree("")
        c._tree = root_tree.id 
        c._committer = self._committer
        c._author = self._revprops.get('author', self._committer)
        c._commit_timestamp = self._timestamp
        c._author_timestamp = self._timestamp
        c._commit_timezone = self._timezone
        c._author_timezone = self._timezone
        c._message = message.encode("utf-8")
        self.repository._git.object_store.add_object(c)

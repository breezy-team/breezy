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


import stat

from bzrlib import (
    osutils,
    )
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

    def _new_tree(self, path):
        newtree = Tree()
        # FIXME: Inherit children from the base revision
        self._trees[path] = newtree
        return newtree

    def _add_tree(self, path):
        if path in self._trees:
            return self._trees[path]
        if path == "":
            return self._new_tree("")
        dirname, basename = osutils.split(path)
        t = self._add_tree(dirname)
        assert isinstance(basename, str)
        if not basename in t:
            newtree = self._new_tree(path)
            t[basename] = (stat.S_IFDIR, newtree.id)
            return newtree
        else:
            return self.repository._git.object_store[t[basename][1]]

    def _change_blob(self, path, value):
        assert isinstance(path, str)
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
            self._change_blob(path[1].encode("utf-8"), (mode, workingtree.index.get_sha1(path[1].encode("utf-8"))))
            yield file_id, path, (None, None)

    def commit(self, message):
        # FIXME: Eliminate any empty trees recursively
        # Write any tree objects to disk
        for path in sorted(self._trees.keys(), reverse=True):
            self.repository._git.object_store.add_object(self._trees[path])
        c = Commit()
        root_tree = self._add_tree("")
        c.tree = root_tree.id 
        c.committer = self._committer
        c.author = self._revprops.get('author', self._committer)
        c.commit_timestamp = self._timestamp
        c.author_timestamp = self._timestamp
        c.commit_timezone = self._timezone
        c.author_timezone = self._timezone
        c.message = message.encode("utf-8")
        self.repository._git.object_store.add_object(c)

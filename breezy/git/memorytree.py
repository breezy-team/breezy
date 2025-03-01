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


"""Git Memory Trees."""

import os
import posixpath
import stat

from dulwich.index import index_entry_from_stat
from dulwich.objects import Blob, Tree

from breezy import errors, lock, osutils, urlutils
from breezy import revision as _mod_revision
from breezy import tree as _mod_tree
from breezy.transport.memory import MemoryTransport

from .mapping import decode_git_path, encode_git_path
from .tree import MutableGitIndexTree


class GitMemoryTree(MutableGitIndexTree, _mod_tree.Tree):
    """A Git memory tree."""

    def __init__(self, branch, store, head):
        MutableGitIndexTree.__init__(self)
        self.branch = branch
        self.mapping = self.branch.repository.get_mapping()
        self.store = store
        self.index = {}
        self._locks = 0
        self._lock_mode = None
        self._populate_from_branch()

    def _supports_executable(self):
        return True

    @property
    def controldir(self):
        return self.branch.controldir

    def is_control_filename(self, path):
        return False

    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds."""
        with self.lock_tree_write():
            for pos, f in enumerate(files):
                if kinds[pos] is None:
                    kinds[pos] = self.kind(f)

    def put_file_bytes_non_atomic(self, path, bytes):
        """See MutableTree.put_file_bytes_non_atomic."""
        self._file_transport.put_bytes(path, bytes)

    def _populate_from_branch(self):
        """Populate the in-tree state from the branch."""
        if self.branch.head is None:
            self._parent_ids = []
        else:
            self._parent_ids = [self.last_revision()]
        self._file_transport = MemoryTransport()
        if self.branch.head is None:
            tree = Tree()
        else:
            tree_id = self.store[self.branch.head].tree
            tree = self.store[tree_id]

        trees = [("", tree)]
        while trees:
            (path, tree) = trees.pop()
            for name, mode, sha in tree.iteritems():
                subpath = posixpath.join(path, decode_git_path(name))
                if stat.S_ISDIR(mode):
                    self._file_transport.mkdir(subpath)
                    trees.append((subpath, self.store[sha]))
                elif stat.S_ISREG(mode):
                    self._file_transport.put_bytes(subpath, self.store[sha].data)
                    self._index_add_entry(subpath, "file")
                else:
                    raise NotImplementedError(self._populate_from_branch)

    def lock_read(self):
        """Lock the memory tree for reading.

        This triggers population of data from the branch for its revision.
        """
        self._locks += 1
        try:
            if self._locks == 1:
                self.branch.lock_read()
                self._lock_mode = "r"
                self._populate_from_branch()
            return lock.LogicalLockResult(self.unlock)
        except BaseException:
            self._locks -= 1
            raise

    def lock_tree_write(self):
        """See MutableTree.lock_tree_write()."""
        self._locks += 1
        try:
            if self._locks == 1:
                self.branch.lock_read()
                self._lock_mode = "w"
                self._populate_from_branch()
            elif self._lock_mode == "r":
                raise errors.ReadOnlyError(self)
        except BaseException:
            self._locks -= 1
            raise
        return lock.LogicalLockResult(self.unlock)

    def lock_write(self):
        """See MutableTree.lock_write()."""
        self._locks += 1
        try:
            if self._locks == 1:
                self.branch.lock_write()
                self._lock_mode = "w"
                self._populate_from_branch()
            elif self._lock_mode == "r":
                raise errors.ReadOnlyError(self)
            return lock.LogicalLockResult(self.unlock)
        except BaseException:
            self._locks -= 1
            raise

    def unlock(self):
        """Release a lock.

        This frees all cached state when the last lock context for the tree is
        left.
        """
        if self._locks == 1:
            self._parent_ids = []
            self.index = {}
            try:
                self.branch.unlock()
            finally:
                self._locks = 0
                self._lock_mode = None
        else:
            self._locks -= 1

    def _lstat(self, path):
        mem_stat = self._file_transport.stat(path)
        stat_val = os.stat_result(
            (mem_stat.st_mode, 0, 0, 0, 0, 0, mem_stat.st_size, 0, 0, 0)
        )
        return stat_val

    def _live_entry(self, path):
        path = urlutils.quote_from_bytes(path)
        stat_val = self._lstat(path)
        if stat.S_ISDIR(stat_val.st_mode):
            return None
        elif stat.S_ISLNK(stat_val.st_mode):
            blob = Blob.from_string(
                encode_git_path(self._file_transport.readlink(path))
            )
        elif stat.S_ISREG(stat_val.st_mode):
            blob = Blob.from_string(self._file_transport.get_bytes(path))
        else:
            raise AssertionError("unknown type %d" % stat_val.st_mode)
        return index_entry_from_stat(stat_val, blob.id, mode=stat_val.st_mode)

    def get_file_with_stat(self, path):
        return (self.get_file(path), self._lstat(path))

    def get_file(self, path):
        """See Tree.get_file."""
        return self._file_transport.get(path)

    def get_file_sha1(self, path, stat_value=None):
        """See Tree.get_file_sha1()."""
        stream = self._file_transport.get(path)
        return osutils.sha_file(stream)

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        This implementation returns the current cached value from
            self._parent_ids.
        """
        with self.lock_read():
            return list(self._parent_ids)

    def last_revision(self):
        """See MutableTree.last_revision."""
        with self.lock_read():
            if self.branch.head is None:
                return _mod_revision.NULL_REVISION
            return self.branch.repository.lookup_foreign_revision_id(self.branch.head)

    def basis_tree(self):
        """See Tree.basis_tree()."""
        return self.branch.repository.revision_tree(self.last_revision())

    def get_config_stack(self):
        return self.branch.get_config_stack()

    def has_filename(self, path):
        return self._file_transport.has(path)

    def _set_merges_from_parent_ids(self, rhs_parent_ids):
        if self.branch.head is None:
            self._parent_ids = []
        else:
            self._parent_ids = [self.last_revision()]
        self._parent_ids.extend(rhs_parent_ids)

    def set_parent_ids(self, parent_ids, allow_leftmost_as_ghost=False):
        if len(parent_ids) == 0:
            self._parent_ids = []
            self.branch.head = None
        else:
            self._parent_ids = parent_ids
            self.branch.head = self.branch.repository.lookup_bzr_revision_id(
                parent_ids[0]
            )[0]

    def mkdir(self, path, file_id=None):
        """See MutableTree.mkdir()."""
        self.add(path, "directory")
        self._file_transport.mkdir(path)

    def _rename_one(self, from_rel, to_rel):
        self._file_transport.rename(from_rel, to_rel)

    def kind(self, p):
        stat_value = self._file_transport.stat(p)
        return osutils.file_kind_from_stat_mode(stat_value.st_mode)

    def get_symlink_target(self, path):
        with self.lock_read():
            return self._file_transport.readlink(path)

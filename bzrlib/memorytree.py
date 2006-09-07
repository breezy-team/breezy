# Copyright (C) 2006 Canonical Ltd
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

"""MemoryTree object.

See MemoryTree for more details.
"""


from copy import deepcopy

from bzrlib import errors, mutabletree
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.osutils import sha_file
from bzrlib.transport.memory import MemoryTransport


class MemoryTree(mutabletree.MutableTree):
    """A MemoryTree is a specialisation of MutableTree.
    
    It maintains nearly no state outside of read_lock and write_lock
    transactions. (it keeps a reference to the branch, and its last-revision
    only).
    """

    def __init__(self, branch, revision_id):
        """Construct a MemoryTree for branch using revision_id."""
        self.branch = branch
        self.bzrdir = branch.bzrdir
        self._branch_revision_id = revision_id
        self._locks = 0
        self._lock_mode = None

    @needs_write_lock
    def _add(self, files, ids, kinds):
        """See MutableTree._add."""
        for f, file_id, kind in zip(files, ids, kinds):
            if kind is None:
                kind = 'file'
            if file_id is None:
                self._inventory.add_path(f, kind=kind)
            else:
                self._inventory.add_path(f, kind=kind, file_id=file_id)

    def basis_tree(self):
        """See Tree.basis_tree()."""
        return self._basis_tree

    @staticmethod
    def create_on_branch(branch):
        """Create a MemoryTree for branch, using the last-revision of branch."""
        return MemoryTree(branch, branch.last_revision())

    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds.
        
        This implementation does not care about the file kind of
        missing files, so is a no-op.
        """

    def get_file(self, file_id):
        """See Tree.get_file."""
        return self._file_transport.get(self.id2path(file_id))

    def get_file_sha1(self, file_id, path=None):
        """See Tree.get_file_sha1()."""
        if path is None:
            path = self.id2path(file_id)
        stream = self._file_transport.get(path)
        return sha_file(stream)

    @needs_read_lock
    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        This implementation returns the current cached value from
            self._parent_ids.
        """
        return list(self._parent_ids)

    def has_filename(self, filename):
        """See Tree.has_filename()."""
        return self._file_transport.has(filename)

    def is_executable(self, file_id, path=None):
        return self._inventory[file_id].executable

    def mkdir(self, path, file_id=None):
        """See MutableTree.mkdir()."""
        self.add(path, file_id, 'directory')
        if file_id is None:
            file_id = self.path2id(path)
        self._file_transport.mkdir(path)
        return file_id

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
        except:
            self._locks -= 1
            raise

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
        except:
            self._locks -= 1
            raise

    def _populate_from_branch(self):
        """Populate the in-tree state from the branch."""
        self._basis_tree = self.branch.repository.revision_tree(
            self._branch_revision_id)
        if self._branch_revision_id is None:
            self._parent_ids = []
        else:
            self._parent_ids = [self._branch_revision_id]
        self._inventory = deepcopy(self._basis_tree._inventory)
        self._file_transport = MemoryTransport()
        # TODO copy the revision trees content, or do it lazy, or something.
        inventory_entries = self._inventory.iter_entries()
        inventory_entries.next()
        for path, entry in inventory_entries:
            if entry.kind == 'directory':
                self._file_transport.mkdir(path)
            elif entry.kind == 'file':
                self._file_transport.put_file(path,
                    self._basis_tree.get_file(entry.file_id))
            else:
                raise NotImplementedError(self._populate_from_branch)

    def put_file_bytes_non_atomic(self, file_id, bytes):
        """See MutableTree.put_file_bytes_non_atomic."""
        self._file_transport.put_bytes(self.id2path(file_id), bytes)

    def unlock(self):
        """Release a lock.

        This frees all cached state when the last lock context for the tree is
        left.
        """
        if self._locks == 1:
            self._basis_tree = None
            self._parent_ids = []
            self._inventory = None
            try:
                self.branch.unlock()
            finally:
                self._locks = 0
                self._lock_mode = None
        else:
            self._locks -= 1

    @needs_write_lock
    def unversion(self, file_ids):
        """Remove the file ids in file_ids from the current versioned set.

        When a file_id is unversioned, all of its children are automatically
        unversioned.

        :param file_ids: The file ids to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        # XXX: This should be in mutabletree, but the inventory-save action
        # is not relevant to memory tree. Until that is done in unlock by
        # working tree, we cannot share the implementation.
        for file_id in file_ids:
            if self._inventory.has_id(file_id):
                self._inventory.remove_recursive_id(file_id)
            else:
                raise errors.NoSuchId(self, file_id)

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """See MutableTree.set_parent_trees()."""
        if len(parents_list) == 0:
            self._parent_ids = []
            self._basis_tree = self.branch.repository.revisiontree(None)
        else:
            if parents_list[0][1] is None and not allow_leftmost_as_ghost:
                # a ghost in the left most parent
                raise errors.GhostRevisionUnusableHere(parents_list[0][0])
            self._parent_ids = [parent_id for parent_id, tree in parents_list]
            if parents_list[0][1] is None:
                self._basis_tree = self.branch.repository.revisiontree(None)
            else:
                self._basis_tree = parents_list[0][1]

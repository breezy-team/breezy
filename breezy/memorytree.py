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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""MemoryTree object.

See MemoryTree for more details.
"""

import os
import stat

from . import errors, lock
from . import revision as _mod_revision
from . import transport as _mod_transport
from .bzr.inventory import Inventory
from .bzr.inventorytree import MutableInventoryTree
from .osutils import sha_file
from .transport.memory import MemoryTransport


class MemoryTree(MutableInventoryTree):
    """A MemoryTree is a specialisation of MutableTree.

    It maintains nearly no state outside of read_lock and write_lock
    transactions. (it keeps a reference to the branch, and its last-revision
    only).
    """

    def __init__(self, branch, revision_id):
        """Construct a MemoryTree for branch using revision_id."""
        self.branch = branch
        self.controldir = branch.controldir
        self._branch_revision_id = revision_id
        self._locks = 0
        self._lock_mode = None

    def supports_symlinks(self):
        """Check if this tree supports symbolic links.

        Returns:
            True, as MemoryTree supports symbolic links.
        """
        return True

    def supports_tree_reference(self):
        """Check if this tree supports tree references (nested trees).

        Returns:
            False, as MemoryTree does not support nested trees.
        """
        return False

    def get_config_stack(self):
        """Get the configuration stack for this tree.

        Returns:
            The configuration stack from the associated branch.
        """
        return self.branch.get_config_stack()

    def is_control_filename(self, filename):
        """Check if a filename is a control file.

        Args:
            filename: The filename to check.

        Returns:
            False, as MemoryTree has no control filenames.
        """
        # Memory tree doesn't have any control filenames
        return False

    def _add(self, files, kinds, ids):
        """See MutableTree._add."""
        with self.lock_tree_write():
            for f, file_id, kind in zip(files, ids, kinds):
                if kind is None:
                    st_mode = self._file_transport.stat(f).st_mode
                    if stat.S_ISREG(st_mode):
                        kind = "file"
                    elif stat.S_ISLNK(st_mode):
                        kind = "symlink"
                    elif stat.S_ISDIR(st_mode):
                        kind = "directory"
                    else:
                        raise AssertionError("Unknown file kind")
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

    def iter_child_entries(self, path):
        """Iterate over the child entries of a directory.

        Args:
            path: Path to the directory to iterate.

        Returns:
            Iterator over child inventory entries.

        Raises:
            NoSuchFile: If the path does not exist.
            NotADirectory: If the path is not a directory.
        """
        with self.lock_read():
            ie = self._inventory.get_entry_by_path(path)
            if ie is None:
                raise _mod_transport.NoSuchFile(path)
            if ie.kind != "directory":
                raise errors.NotADirectory(path)
            return ie.children.values()

    def get_file(self, path):
        """See Tree.get_file."""
        return self._file_transport.get(path)

    def get_file_sha1(self, path, stat_value=None):
        """See Tree.get_file_sha1()."""
        stream = self._file_transport.get(path)
        return sha_file(stream)

    def _comparison_data(self, entry, path):
        """See Tree._comparison_data."""
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def rename_one(self, from_rel, to_rel):
        """Rename a single file or directory.

        Args:
            from_rel: The relative path of the source.
            to_rel: The relative path of the destination.

        Returns:
            None
        """
        with self.lock_tree_write():
            file_id = self.path2id(from_rel)
            to_dir, to_tail = os.path.split(to_rel)
            to_parent_id = self.path2id(to_dir)
            self._file_transport.move(from_rel, to_rel)
            self._inventory.rename(file_id, to_parent_id, to_tail)

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        id = self.path2id(path)
        if id is None:
            return "missing", None, None, None
        kind = self.kind(path, id)
        if kind == "file":
            bytes = self._file_transport.get_bytes(path)
            size = len(bytes)
            executable = self._inventory[id].executable
            sha1 = None  # no stat cache
            return (kind, size, executable, sha1)
        elif kind == "directory":
            # memory tree does not support nested trees yet.
            return kind, None, None, None
        elif kind == "symlink":
            return kind, None, None, self._inventory[id].symlink_target
        else:
            raise NotImplementedError("unknown kind")

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        This implementation returns the current cached value from
            self._parent_ids.
        """
        with self.lock_read():
            return list(self._parent_ids)

    def has_filename(self, filename):
        """See Tree.has_filename()."""
        return self._file_transport.has(filename)

    def is_executable(self, path):
        """Check if a file is executable.

        Args:
            path: Path to the file to check.

        Returns:
            True if the file is executable, False otherwise.
        """
        return self._inventory.get_entry_by_path(path).executable

    def kind(self, path):
        """Return the kind of entry at the given path.

        Args:
            path: Path to check the kind of.

        Returns:
            String describing the kind (e.g., 'file', 'directory', 'symlink').
        """
        return self._inventory.get_entry_by_path(path).kind

    def mkdir(self, path, file_id=None):
        """See MutableTree.mkdir()."""
        self.add(path, "directory", file_id)
        if file_id is None:
            file_id = self.path2id(path)
        self._file_transport.mkdir(path)
        return file_id

    def last_revision(self):
        """See MutableTree.last_revision."""
        with self.lock_read():
            return self._branch_revision_id

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

    def _populate_from_branch(self):
        """Populate the in-tree state from the branch."""
        self._set_basis()
        if self._branch_revision_id == _mod_revision.NULL_REVISION:
            self._parent_ids = []
        else:
            self._parent_ids = [self._branch_revision_id]
        self._inventory = Inventory(None, self._basis_tree.get_revision_id())
        self._file_transport = MemoryTransport()
        # TODO copy the revision trees content, or do it lazy, or something.
        inventory_entries = self._basis_tree.iter_entries_by_dir()
        for path, entry in inventory_entries:
            self._inventory.add(entry.copy())
            if path == "":
                continue
            if entry.kind == "directory":
                self._file_transport.mkdir(path)
            elif entry.kind == "symlink":
                self._file_transport.symlink(entry.symlink_target, path)
            elif entry.kind == "file":
                self._file_transport.put_file(path, self._basis_tree.get_file(path))
            else:
                raise NotImplementedError(self._populate_from_branch)

    def put_file_bytes_non_atomic(self, path, bytes):
        """See MutableTree.put_file_bytes_non_atomic."""
        self._file_transport.put_bytes(path, bytes)

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

    def unversion(self, paths):
        """Remove the paths from the current versioned set.

        When a file_id is unversioned, all of its children are automatically
        unversioned.

        :param paths: The paths to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        with self.lock_tree_write():
            # XXX: This should be in mutabletree, but the inventory-save action
            # is not relevant to memory tree. Until that is done in unlock by
            # working tree, we cannot share the implementation.
            file_ids = set()
            for path in paths:
                file_id = self.path2id(path)
                if file_id is None:
                    raise _mod_transport.NoSuchFile(path)
                file_ids.add(file_id)
            for file_id in file_ids:
                if self._inventory.has_id(file_id):
                    self._inventory.remove_recursive_id(file_id)

    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """See MutableTree.set_parent_trees()."""
        for revision_id in revision_ids:
            _mod_revision.check_not_reserved_id(revision_id)
        if len(revision_ids) == 0:
            self._parent_ids = []
            self._branch_revision_id = _mod_revision.NULL_REVISION
        else:
            self._parent_ids = revision_ids
            self._branch_revision_id = revision_ids[0]
        self._allow_leftmost_as_ghost = allow_leftmost_as_ghost
        self._set_basis()

    def _set_basis(self):
        try:
            self._basis_tree = self.branch.repository.revision_tree(
                self._branch_revision_id
            )
        except errors.NoSuchRevision:
            if self._allow_leftmost_as_ghost:
                self._basis_tree = self.branch.repository.revision_tree(
                    _mod_revision.NULL_REVISION
                )
            else:
                raise

    def get_symlink_target(self, path):
        """Get the target of a symbolic link.

        Args:
            path: Path to the symbolic link.

        Returns:
            String target of the symbolic link.
        """
        with self.lock_read():
            return self._file_transport.readlink(path)

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """See MutableTree.set_parent_trees()."""
        if len(parents_list) == 0:
            self._parent_ids = []
            self._basis_tree = self.branch.repository.revision_tree(
                _mod_revision.NULL_REVISION
            )
        else:
            if parents_list[0][1] is None and not allow_leftmost_as_ghost:
                # a ghost in the left most parent
                raise errors.GhostRevisionUnusableHere(parents_list[0][0])
            self._parent_ids = [parent_id for parent_id, tree in parents_list]
            if parents_list[0][1] is None or parents_list[0][1] == b"null:":
                self._basis_tree = self.branch.repository.revision_tree(
                    _mod_revision.NULL_REVISION
                )
            else:
                self._basis_tree = parents_list[0][1]
            self._branch_revision_id = parents_list[0][0]

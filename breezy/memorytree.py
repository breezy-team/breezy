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

A format-independent in-memory mutable tree that does not use file ids
or inventories.
"""

import posixpath
import stat

from dromedary.errors import NoSuchFile
from dromedary.memory import MemoryTransport

from . import errors, lock, osutils
from . import revision as _mod_revision
from . import tree as tree_mod
from .mutabletree import MutableTree


class MemoryTree(MutableTree):
    """A MutableTree that stores all its content in memory.

    This tree does not use file ids or inventories. It tracks versioned
    paths directly, similar to how Git works.
    """

    def __init__(self, branch, revision_id):
        """Construct a MemoryTree for branch using revision_id."""
        super().__init__()
        self.branch = branch
        self.controldir = branch.controldir
        self._branch_revision_id = revision_id
        self._locks = 0
        self._lock_mode = None
        self._versioned = None
        self._file_transport = None
        self._parent_ids = []
        self._basis_tree = None
        self._allow_leftmost_as_ghost = False

    @property
    def supports_file_ids(self):
        """Return whether this tree supports file ids."""
        return False

    def supports_rename_tracking(self):
        """Return whether this tree supports rename tracking."""
        return False

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

    def has_versioned_directories(self):
        """Return whether this tree versions directories separately."""
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

    @staticmethod
    def create_on_branch(branch):
        """Create a MemoryTree for branch, using the last-revision of branch."""
        return MemoryTree(branch, branch.last_revision())

    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds.

        This implementation does not care about the file kind of
        missing files, so is a no-op.
        """

    # -- Locking --

    def lock_read(self):
        """Acquire a read lock on this tree."""
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
        """Acquire a tree-write lock on this tree."""
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
        """Acquire a write lock on this tree."""
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
        """Release a lock on this tree."""
        if self._locks == 1:
            self._basis_tree = None
            self._parent_ids = []
            self._versioned = None
            self._file_transport = None
            try:
                self.branch.unlock()
            finally:
                self._locks = 0
                self._lock_mode = None
        else:
            self._locks -= 1

    # -- Population --

    def _populate_from_branch(self):
        """Populate the in-tree state from the branch."""
        self._set_basis()
        if self._branch_revision_id == _mod_revision.NULL_REVISION:
            self._parent_ids = []
        else:
            self._parent_ids = [self._branch_revision_id]
        self._versioned = set()
        self._file_transport = MemoryTransport()

        with self._basis_tree.lock_read():
            for path, entry in self._basis_tree.iter_entries_by_dir():
                kind = entry.kind
                self._versioned.add(path)
                if path == "":
                    continue
                if kind == "directory":
                    self._file_transport.mkdir(path)
                elif kind == "symlink":
                    target = self._basis_tree.get_symlink_target(path)
                    self._file_transport.symlink(target, path)
                elif kind == "file":
                    self._file_transport.put_file(path, self._basis_tree.get_file(path))
                else:
                    raise NotImplementedError(f"Unsupported entry kind: {kind}")

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

    # -- Tree read interface --

    def basis_tree(self):
        """Return the basis tree for this tree."""
        return self._basis_tree

    def get_parent_ids(self):
        """Return the parent revision ids for this tree."""
        with self.lock_read():
            return list(self._parent_ids)

    def last_revision(self):
        """Return the revision id of the last commit."""
        with self.lock_read():
            return self._branch_revision_id

    def has_filename(self, filename):
        """Return whether the given filename exists in this tree."""
        return self._file_transport.has(filename)

    def is_versioned(self, path):
        """Return whether the given path is versioned."""
        path = path.rstrip("/")
        if self._versioned is None:
            return False
        return path in self._versioned

    def all_versioned_paths(self):
        """Return the set of all versioned paths in this tree."""
        return set(self._versioned)

    def kind(self, path):
        """Return the kind of entry at the given path."""
        st_mode = self._file_transport.stat(path).st_mode
        if stat.S_ISREG(st_mode):
            return "file"
        elif stat.S_ISLNK(st_mode):
            return "symlink"
        elif stat.S_ISDIR(st_mode):
            return "directory"
        else:
            raise AssertionError(f"Unknown file kind for {path}")

    def is_executable(self, path):
        """Return whether the file at the given path is executable."""
        st_mode = self._file_transport.stat(path).st_mode
        return bool(stat.S_ISREG(st_mode) and stat.S_IEXEC & st_mode)

    def get_file(self, path):
        """Return a file-like object for the given path."""
        return self._file_transport.get(path)

    def get_file_sha1(self, path, stat_value=None):
        """Return the SHA1 hash of the file at the given path."""
        stream = self._file_transport.get(path)
        return osutils.sha_file(stream)

    def get_file_mtime(self, path):
        """Return the modification time of the file at the given path."""
        return 0

    def get_file_size(self, path):
        """Return the size of the file at the given path."""
        try:
            content = self._file_transport.get_bytes(path)
        except NoSuchFile:
            return None
        return len(content)

    def get_symlink_target(self, path):
        """Get the target of a symbolic link.

        Args:
            path: Path to the symbolic link.

        Returns:
            String target of the symbolic link.
        """
        with self.lock_read():
            return self._file_transport.readlink(path)

    def path_content_summary(self, path):
        """Return a content summary tuple for the given path."""
        if not self.is_versioned(path):
            return "missing", None, None, None
        try:
            kind = self.kind(path)
        except NoSuchFile:
            return "missing", None, None, None
        if kind == "file":
            content = self._file_transport.get_bytes(path)
            size = len(content)
            executable = self.is_executable(path)
            return (kind, size, executable, None)
        elif kind == "directory":
            return kind, None, None, None
        elif kind == "symlink":
            target = self._file_transport.readlink(path)
            return kind, None, None, target
        else:
            raise NotImplementedError(f"unknown kind: {kind}")

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def annotate_iter(self, path, default_revision=_mod_revision.CURRENT_REVISION):
        """Return an iterator of (revision_id, line) tuples for the file."""
        with self.lock_read():
            text = self.get_file_text(path)
            return [(default_revision, line) for line in text.splitlines(True)]

    def walkdirs(self, prefix=""):
        """Walk the directories of this tree, yielding (dirpath, dirblock)."""
        with self.lock_read():
            pending = [prefix]
            while pending:
                dirpath = pending.pop()
                dirblock = []
                try:
                    children = sorted(self._file_transport.list_dir(dirpath))
                except NoSuchFile:
                    continue
                for child in children:
                    if dirpath:
                        child_path = dirpath + "/" + child
                    else:
                        child_path = child
                    if not self.is_versioned(child_path):
                        continue
                    try:
                        kind = self.kind(child_path)
                    except NoSuchFile:
                        continue
                    stat_val = self._file_transport.stat(child_path)
                    dirblock.append(
                        (child_path, child, kind, stat_val, child_path, kind)
                    )
                    if kind == "directory":
                        pending.append(child_path)
                yield dirpath, dirblock

    def iter_entries_by_dir(self, specific_files=None, recurse_nested=False):
        """Iterate over entries in directory order."""
        with self.lock_read():
            if specific_files is not None:
                specific_files = set(specific_files)
            from .tree import TreeDirectory, TreeFile, TreeLink

            entries = []
            for path in sorted(self._versioned):
                if specific_files is not None and path not in specific_files:
                    continue
                if path == "":
                    entries.append((path, TreeDirectory()))
                else:
                    try:
                        kind = self.kind(path)
                    except NoSuchFile:
                        continue
                    if kind == "file":
                        entries.append((path, TreeFile()))
                    elif kind == "directory":
                        entries.append((path, TreeDirectory()))
                    elif kind == "symlink":
                        entries.append((path, TreeLink()))
                    else:
                        raise NotImplementedError(f"unknown kind: {kind}")
            return iter(entries)

    def iter_child_entries(self, path):
        """Iterate over the direct child entries of the given path."""
        with self.lock_read():
            from .tree import TreeDirectory, TreeFile, TreeLink

            path = path.rstrip("/")
            prefix = path + "/" if path else ""
            for versioned_path in sorted(self._versioned):
                if not versioned_path.startswith(prefix):
                    continue
                remainder = versioned_path[len(prefix) :]
                if "/" in remainder:
                    continue
                if not remainder:
                    continue
                try:
                    kind = self.kind(versioned_path)
                except NoSuchFile:
                    continue
                if kind == "file":
                    yield TreeFile()
                elif kind == "directory":
                    yield TreeDirectory()
                elif kind == "symlink":
                    yield TreeLink()

    def list_files(
        self, include_root=False, from_dir=None, recursive=True, recurse_nested=False
    ):
        """List the files in this tree."""
        with self.lock_read():
            if from_dir is None or from_dir == ".":
                from_dir = ""
            prefix = from_dir + "/" if from_dir else ""
            from .tree import TreeDirectory, TreeFile, TreeLink

            for path in sorted(self._versioned):
                if path == "" and not include_root:
                    continue
                if from_dir and not path.startswith(prefix) and path != from_dir:
                    continue
                if not recursive and "/" in path[len(prefix) :]:
                    continue
                if not self.has_filename(path) and path != "":
                    continue
                try:
                    kind = self.kind(path)
                except NoSuchFile:
                    continue
                if kind == "file":
                    entry = TreeFile()
                elif kind == "directory":
                    entry = TreeDirectory()
                elif kind == "symlink":
                    entry = TreeLink()
                else:
                    continue
                yield (path, "V", kind, entry)

    def find_related_paths_across_trees(
        self, paths, trees=None, require_versioned=True
    ):
        """Find related paths across multiple trees."""
        if paths is None:
            return None
        if trees is None:
            trees = []
        if require_versioned:
            all_trees = [self] + list(trees)
            unversioned = set()
            for p in paths:
                for t in all_trees:
                    if t.is_versioned(p):
                        break
                else:
                    unversioned.add(p)
            if unversioned:
                raise errors.PathsNotVersionedError(unversioned)
        return [p for p in paths if self.is_versioned(p)]

    def get_nested_tree(self, path):
        """Return the nested tree at the given path."""
        raise errors.NotBranchError(path)

    def get_reference_revision(self, path):
        """Return the reference revision for a nested tree at path."""
        return None

    def preview_transform(self, pb=None):
        """Return a preview transform for this tree."""
        raise NotImplementedError(self.preview_transform)

    # -- Mutable interface --

    def add(self, files, kinds=None):
        """Add paths to be versioned."""
        if isinstance(files, str):
            if not (kinds is None or isinstance(kinds, str)):
                raise AssertionError()
            files = [files]
            if kinds is not None:
                kinds = [kinds]

        files = [path.strip("/") for path in files]

        if kinds is None:
            kinds = [None] * len(files)
        elif len(kinds) != len(files):
            raise AssertionError()

        with self.lock_tree_write():
            for f, kind in zip(files, kinds, strict=False):
                if kind is None:
                    if f == "":
                        kind = "directory"
                    else:
                        try:
                            st_mode = self._file_transport.stat(f).st_mode
                        except NoSuchFile:
                            # File doesn't exist yet in transport, accept
                            # the add anyway (kind will be determined later)
                            kind = "file"
                        else:
                            if stat.S_ISREG(st_mode):
                                kind = "file"
                            elif stat.S_ISLNK(st_mode):
                                kind = "symlink"
                            elif stat.S_ISDIR(st_mode):
                                kind = "directory"
                            else:
                                raise AssertionError(f"Unknown file kind for {f}")
                self._versioned.add(f)
                # Also version parent directories
                parent = posixpath.dirname(f)
                while parent and parent not in self._versioned:
                    self._versioned.add(parent)
                    parent = posixpath.dirname(parent)

    def mkdir(self, path):
        """Create a versioned directory at the given path."""
        self.add(path, "directory")
        self._file_transport.mkdir(path)

    def put_file_bytes_non_atomic(self, path, bytes):
        """Write bytes to a file non-atomically."""
        self._file_transport.put_bytes(path, bytes)

    def has_changes(self, _from_tree=None):
        """Return whether this tree has changes compared to the basis tree."""
        with self.lock_read():
            if _from_tree is None:
                _from_tree = self.basis_tree()
            changes = self.iter_changes(_from_tree)
            try:
                change = next(iter(changes))
            except StopIteration:
                return False
            else:
                if change.path == ("", ""):
                    try:
                        next(iter(changes))
                    except StopIteration:
                        return False
                return True

    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """Set the parent revision ids for this tree."""
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

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """Set the parent trees for this tree."""
        if len(parents_list) == 0:
            self._parent_ids = []
            self._basis_tree = self.branch.repository.revision_tree(
                _mod_revision.NULL_REVISION
            )
        else:
            if parents_list[0][1] is None and not allow_leftmost_as_ghost:
                raise errors.GhostRevisionUnusableHere(parents_list[0][0])
            self._parent_ids = [parent_id for parent_id, tree in parents_list]
            if parents_list[0][1] is None or parents_list[0][1] == b"null:":
                self._basis_tree = self.branch.repository.revision_tree(
                    _mod_revision.NULL_REVISION
                )
            else:
                self._basis_tree = parents_list[0][1]
            self._branch_revision_id = parents_list[0][0]

    def rename_one(self, from_rel, to_rel, after=False):
        """Rename a file from one path to another."""
        with self.lock_tree_write():
            self._file_transport.move(from_rel, to_rel)
            self._versioned.discard(from_rel)
            self._versioned.add(to_rel)

    def copy_one(self, from_rel, to_rel):
        """Copy a file from one path to another."""
        with self.lock_tree_write():
            content = self._file_transport.get_bytes(from_rel)
            self._file_transport.put_bytes(to_rel, content)
            self._versioned.add(to_rel)

    def unversion(self, paths):
        """Remove the given paths from the versioned set."""
        with self.lock_tree_write():
            for path in paths:
                if path not in self._versioned:
                    raise NoSuchFile(path)
                self._versioned.discard(path)
                # Also unversion children
                prefix = path + "/"
                children = {p for p in self._versioned if p.startswith(prefix)}
                self._versioned -= children

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        """Add files to the tree, skipping already-versioned paths."""
        with self.lock_tree_write():
            added = []
            ignored = {}
            for filepath in file_list:
                if self.is_versioned(filepath):
                    continue
                self.add(filepath)
                added.append(filepath)
            return len(added), ignored

    def update_basis_by_delta(self, revid, delta):
        """Update the basis tree using the given delta."""
        for old_path, new_path, _file_id, _ie in delta:
            if old_path is not None:
                self._versioned.discard(old_path)
            if new_path is not None:
                self._versioned.add(new_path)
        self._parent_ids = [revid]
        self._branch_revision_id = revid

    def transform(self, pb=None):
        """Return a tree transform for this tree."""
        raise NotImplementedError(self.transform)


class InterMemoryTree(tree_mod.InterTree):
    """InterTree implementation where the target is a MemoryTree."""

    @classmethod
    def is_compatible(cls, source, target):
        """Return whether this InterTree is compatible with the given trees."""
        return isinstance(target, MemoryTree)

    def iter_changes(
        self,
        include_unchanged=False,
        specific_files=None,
        pb=None,
        extra_trees=None,
        require_versioned=True,
        want_unversioned=False,
    ):
        """Iterate over changes between the source and target trees."""
        if extra_trees is None:
            extra_trees = []
        with self.lock_read():
            source_paths = self.source.all_versioned_paths()
            target_paths = self.target.all_versioned_paths()
            all_paths = source_paths | target_paths
            if specific_files is not None:
                specific_files = set(specific_files)
                # Include parents of specific files
                parents = set()
                for p in specific_files:
                    parts = p.split("/")
                    for i in range(len(parts)):
                        parents.add("/".join(parts[:i]))
                specific_files = specific_files | parents
                all_paths = {
                    p
                    for p in all_paths
                    if p in specific_files
                    or any(p.startswith(sf + "/") for sf in specific_files)
                }
            if require_versioned and specific_files:
                trees = [self.source, self.target] + list(extra_trees)
                for p in specific_files:
                    if not any(t.is_versioned(p) for t in trees):
                        raise errors.PathsNotVersionedError({p})
            for path in sorted(all_paths):
                in_source = path in source_paths
                in_target = path in target_paths
                source_kind = None
                target_kind = None
                source_executable = None
                target_executable = None
                if in_source:
                    try:
                        source_kind = self.source.kind(path)
                    except NoSuchFile:
                        in_source = False
                    else:
                        source_executable = (
                            self.source.is_executable(path)
                            if source_kind == "file"
                            else False
                        )
                if in_target:
                    try:
                        target_kind = self.target.kind(path)
                    except NoSuchFile:
                        in_target = False
                    else:
                        target_executable = (
                            self.target.is_executable(path)
                            if target_kind == "file"
                            else False
                        )
                if not in_source and not in_target:
                    continue
                source_name = osutils.basename(path) if in_source else None
                target_name = osutils.basename(path) if in_target else None
                source_path = path if in_source else None
                target_path = path if in_target else None
                changed_content = False
                if source_kind != target_kind:
                    changed_content = True
                elif source_kind == "file" and not self.file_content_matches(
                    path, path
                ):
                    changed_content = True
                elif source_kind == "symlink":
                    if self.source.get_symlink_target(
                        path
                    ) != self.target.get_symlink_target(path):
                        changed_content = True
                versioned = (in_source, in_target)
                if not include_unchanged and not changed_content:
                    if versioned == (True, True):
                        if source_executable == target_executable:
                            continue
                yield tree_mod.TreeChange(
                    (source_path, target_path),
                    changed_content,
                    versioned,
                    (source_name, target_name),
                    (source_kind, target_kind),
                    (source_executable, target_executable),
                )

    def find_target_path(self, path, recurse="none"):
        """Find the corresponding path in the target tree."""
        if not self.source.is_versioned(path):
            raise NoSuchFile(path)
        if self.target.is_versioned(path):
            return path
        return None

    def find_source_path(self, path, recurse="none"):
        """Find the corresponding path in the source tree."""
        if not self.target.is_versioned(path):
            raise NoSuchFile(path)
        if self.source.is_versioned(path):
            return path
        return None

    def find_target_paths(self, paths, recurse="none"):
        """Find corresponding paths in the target tree for multiple paths."""
        ret = {}
        for path in paths:
            ret[path] = self.find_target_path(path, recurse=recurse)
        return ret

    def find_source_paths(self, paths, recurse="none"):
        """Find corresponding paths in the source tree for multiple paths."""
        ret = {}
        for path in paths:
            ret[path] = self.find_source_path(path, recurse=recurse)
        return ret


tree_mod.InterTree.register_optimiser(InterMemoryTree)

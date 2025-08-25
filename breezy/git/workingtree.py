# Copyright (C) 2008-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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


"""Git working tree implementation for Breezy.

This module provides an adapter between Git indexes and Breezy working trees,
allowing Git repositories to be manipulated using the Breezy working tree API.
The module includes:

- GitWorkingTree: A working tree implementation that uses a Git index
- GitWorkingTreeFormat: Format class for Git working trees
- Conflict classes for handling Git-style merge conflicts (TextConflict, ContentsConflict)

The implementation bridges Git's index-based working tree model with Breezy's
working tree abstraction, handling differences in file tracking, conflict
resolution, and tree operations.
"""

import contextlib
import itertools
import os
import posixpath
import re
import stat
import sys
from collections import defaultdict

from dulwich.config import ConfigFile as GitConfigFile
from dulwich.file import FileLocked, GitFile
from dulwich.ignore import IgnoreFilterManager
from dulwich.index import (
    ConflictedIndexEntry,
    Index,
    IndexEntry,
    SHA1Writer,
    build_index_from_tree,
    index_entry_from_path,
    index_entry_from_stat,
    read_submodule_head,
    validate_path,
    write_index_dict,
)
from dulwich.object_store import iter_tree_contents
from dulwich.objects import S_ISGITLINK

from .. import branch as _mod_branch
from .. import conflicts as _mod_conflicts
from .. import controldir as _mod_controldir
from .. import errors, globbing, lock, osutils, trace, tree, urlutils, workingtree
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..decorators import only_raises
from ..mutabletree import BadReferenceTarget, MutableTree
from ..transport.local import file_kind
from .dir import BareLocalGitControlDirFormat, LocalGitDir
from .mapping import decode_git_path, encode_git_path, mode_kind
from .tree import MutableGitIndexTree

CONFLICT_SUFFIXES = [".BASE", ".OTHER", ".THIS"]


# TODO: There should be a base revid attribute to better inform the user about
# how the conflicts were generated.
class TextConflict(_mod_conflicts.Conflict):
    """The merge algorithm could not resolve all differences encountered."""

    has_files = True

    typestring = "text conflict"

    _conflict_re = re.compile(b"^(<{7}|={7}|>{7})")

    def __init__(self, path):
        """Initialize a TextConflict.

        Args:
            path: The path where the conflict occurred.
        """
        super().__init__(path)

    def associated_filenames(self):
        """Return the list of associated conflict files.

        Returns:
            List of filenames for the conflict files (.BASE, .OTHER, .THIS).
        """
        return [self.path + suffix for suffix in (".BASE", ".OTHER", ".THIS")]

    def _resolve(self, tt, winner_suffix):
        """Resolve the conflict by copying one of .THIS or .OTHER into file.

        :param tt: The TreeTransform where the conflict is resolved.
        :param winner_suffix: Either 'THIS' or 'OTHER'

        The resolution is symmetric, when taking THIS, item.THIS is renamed
        into item and vice-versa. This takes one of the files as a whole
        ignoring every difference that could have been merged cleanly.
        """
        # To avoid useless copies, we switch item and item.winner_suffix, only
        # item will exist after the conflict has been resolved anyway.
        item_tid = tt.trans_id_tree_path(self.path)
        item_parent_tid = tt.get_tree_parent(item_tid)
        winner_path = self.path + "." + winner_suffix
        winner_tid = tt.trans_id_tree_path(winner_path)
        winner_parent_tid = tt.get_tree_parent(winner_tid)
        # Switch the paths to preserve the content
        tt.adjust_path(osutils.basename(self.path), winner_parent_tid, winner_tid)
        tt.adjust_path(osutils.basename(winner_path), item_parent_tid, item_tid)
        tt.unversion_file(item_tid)
        tt.version_file(winner_tid)
        tt.apply()

    def action_auto(self, tree):
        """Attempt to automatically resolve the conflict.

        Args:
            tree: The working tree where the conflict exists.

        Raises:
            NotImplementedError: If the conflict cannot be auto-resolved.
        """
        # GZ 2012-07-27: Using NotImplementedError to signal that a conflict
        #                can't be auto resolved does not seem ideal.
        try:
            kind = tree.kind(self.path)
        except _mod_transport.NoSuchFile:
            return
        if kind != "file":
            raise NotImplementedError("Conflict is not a file")
        conflict_markers_in_line = self._conflict_re.search
        with tree.get_file(self.path) as f:
            for line in f:
                if conflict_markers_in_line(line):
                    raise NotImplementedError("Conflict markers present")

    def _resolve_with_cleanups(self, tree, *args, **kwargs):
        """Resolve the conflict with proper cleanup.

        Args:
            tree: The working tree where the conflict exists.
            *args: Arguments to pass to _resolve.
            **kwargs: Keyword arguments to pass to _resolve.
        """
        with tree.transform() as tt:
            self._resolve(tt, *args, **kwargs)

    def action_take_this(self, tree):
        """Resolve the conflict by taking the 'THIS' version.

        Args:
            tree: The working tree where the conflict exists.
        """
        self._resolve_with_cleanups(tree, "THIS")

    def action_take_other(self, tree):
        """Resolve the conflict by taking the 'OTHER' version.

        Args:
            tree: The working tree where the conflict exists.
        """
        self._resolve_with_cleanups(tree, "OTHER")

    def do(self, action, tree):
        """Apply the specified action to the conflict.

        :param action: The method name to call.

        :param tree: The tree passed as a parameter to the method.
        """
        meth = getattr(self, f"action_{action}", None)
        if meth is None:
            raise NotImplementedError(self.__class__.__name__ + "." + action)
        meth(tree)

    def action_done(self, tree):
        """Mark the conflict as solved once it has been handled."""
        # This method does nothing but simplifies the design of upper levels.
        pass

    def describe(self):
        """Return a human-readable description of the conflict.

        Returns:
            A string describing the conflict.
        """
        return f"Text conflict in {self.__dict__['path']}"

    def __str__(self):
        """Return string representation of the conflict.

        Returns:
            A string representation of the conflict.
        """
        return self.describe()

    def __repr__(self):
        """Return detailed string representation of the conflict.

        Returns:
            A detailed string representation for debugging.
        """
        return f"{type(self).__name__}({self.path!r})"

    @classmethod
    def from_index_entry(cls, path, entry):
        """Create a conflict from a Git index entry.

        Args:
            path: The path where the conflict occurred.
            entry: The Git index entry containing conflict information.

        Returns:
            A new TextConflict instance.
        """
        return cls(path)

    def to_index_entry(self, tree):
        """Convert the conflict to a Git index entry.

        Args:
            tree: The working tree containing the conflict.

        Returns:
            A ConflictedIndexEntry representing this conflict.
        """
        encoded_path = encode_git_path(tree.abspath(self.path))
        try:
            base = index_entry_from_path(encoded_path + b".BASE")
        except FileNotFoundError:
            base = None
        try:
            other = index_entry_from_path(encoded_path + b".OTHER")
        except FileNotFoundError:
            other = None
        try:
            this = index_entry_from_path(encoded_path + b".THIS")
        except FileNotFoundError:
            this = None
        return ConflictedIndexEntry(this=this, other=other, ancestor=base)


class ContentsConflict(_mod_conflicts.Conflict):
    """The files are of different types (or both binary), or not present."""

    has_files = True

    typestring = "contents conflict"

    format = "Contents conflict in %(path)s"

    def __init__(self, path, conflict_path=None):
        """Initialize a ContentsConflict.

        Args:
            path: The path where the conflict occurred.
            conflict_path: Optional path to the conflict file.
        """
        for suffix in (".BASE", ".THIS", ".OTHER"):
            if path.endswith(suffix):
                # Here is the raw path
                path = path[: -len(suffix)]
                break
        _mod_conflicts.Conflict.__init__(self, path)
        self.conflict_path = conflict_path

    def _revision_tree(self, tree, revid):
        """Get the revision tree for a given revision ID.

        Args:
            tree: The working tree.
            revid: The revision ID to get the tree for.

        Returns:
            The revision tree for the given revision ID.
        """
        return tree.branch.repository.revision_tree(revid)

    def associated_filenames(self):
        """Return the list of associated conflict files.

        Returns:
            List of filenames for the conflict files (.BASE, .OTHER, .THIS).
        """
        return [self.path + suffix for suffix in (".BASE", ".OTHER", ".THIS")]

    def _resolve(self, tt, suffix_to_remove):
        """Resolve the conflict.

        :param tt: The TreeTransform where the conflict is resolved.
        :param suffix_to_remove: Either 'THIS' or 'OTHER'

        The resolution is symmetric: when taking THIS, OTHER is deleted and
        item.THIS is renamed into item and vice-versa.
        """
        try:
            # Delete 'item.THIS' or 'item.OTHER' depending on
            # suffix_to_remove
            tt.delete_contents(
                tt.trans_id_tree_path(self.path + "." + suffix_to_remove)
            )
        except _mod_transport.NoSuchFile:
            # There are valid cases where 'item.suffix_to_remove' either
            # never existed or was already deleted (including the case
            # where the user deleted it)
            pass
        try:
            this_path = tt._tree.id2path(self.file_id)
        except errors.NoSuchId:
            # The file is not present anymore. This may happen if the user
            # deleted the file either manually or when resolving a conflict on
            # the parent.  We may raise some exception to indicate that the
            # conflict doesn't exist anymore and as such doesn't need to be
            # resolved ? -- vila 20110615
            this_tid = None
        else:
            this_tid = tt.trans_id_tree_path(this_path)
        if this_tid is not None:
            # Rename 'item.suffix_to_remove' (note that if
            # 'item.suffix_to_remove' has been deleted, this is a no-op)
            parent_tid = tt.get_tree_parent(this_tid)
            tt.adjust_path(osutils.basename(self.path), parent_tid, this_tid)
            tt.apply()

    def _resolve_with_cleanups(self, tree, *args, **kwargs):
        """Resolve the conflict with proper cleanup.

        Args:
            tree: The working tree where the conflict exists.
            *args: Arguments to pass to _resolve.
            **kwargs: Keyword arguments to pass to _resolve.
        """
        with tree.transform() as tt:
            self._resolve(tt, *args, **kwargs)

    def action_take_this(self, tree):
        """Resolve the conflict by taking the 'THIS' version.

        Args:
            tree: The working tree where the conflict exists.
        """
        self._resolve_with_cleanups(tree, "OTHER")

    def action_take_other(self, tree):
        """Resolve the conflict by taking the 'OTHER' version.

        Args:
            tree: The working tree where the conflict exists.
        """
        self._resolve_with_cleanups(tree, "THIS")

    @classmethod
    def from_index_entry(cls, entry):
        """Create a conflict from a Git index entry.

        Args:
            entry: The Git index entry containing conflict information.

        Returns:
            A new ContentsConflict instance.
        """
        return cls(entry.path)

    def describe(self):
        """Return a human-readable description of the conflict.

        Returns:
            A string describing the conflict.
        """
        return f"Contents conflict in {self.__dict__['path']}"

    def to_index_entry(self, tree):
        """Convert the conflict to a Git index entry.

        Args:
            tree: The working tree containing the conflict.

        Returns:
            A ConflictedIndexEntry representing this conflict.
        """
        encoded_path = encode_git_path(tree.abspath(self.path))
        try:
            base = index_entry_from_path(encoded_path + b".BASE")
        except FileNotFoundError:
            base = None
        try:
            other = index_entry_from_path(encoded_path + b".OTHER")
        except FileNotFoundError:
            other = None
        try:
            this = index_entry_from_path(encoded_path + b".THIS")
        except FileNotFoundError:
            this = None
        return ConflictedIndexEntry(this=this, other=other, ancestor=base)


class GitWorkingTree(MutableGitIndexTree, workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, controldir, repo, branch):
        """Initialize a Git working tree.

        Args:
            controldir: The control directory for this working tree.
            repo: The repository associated with this working tree.
            branch: The branch associated with this working tree.
        """
        MutableGitIndexTree.__init__(self)
        basedir = controldir.root_transport.local_abspath(".")
        self.basedir = osutils.realpath(basedir)
        self.controldir = controldir
        self.repository = repo
        self.store = self.repository._git.object_store
        self.mapping = self.repository.get_mapping()
        self._branch = branch
        self._transport = self.repository._git._controltransport
        self._format = GitWorkingTreeFormat()
        self.index = None
        self._index_file = None
        self.views = self._make_views()
        self._rules_searcher = None
        self._detect_case_handling()
        self._reset_data()

    def supports_tree_reference(self):
        """Return True if this tree supports tree references (submodules).

        Returns:
            True, as Git working trees support submodules.
        """
        return True

    def supports_rename_tracking(self):
        """Return True if this tree supports rename tracking.

        Returns:
            False, as Git working trees don't support rename tracking through this interface.
        """
        return False

    def _read_index(self):
        """Read the Git index file.

        This loads the index from disk and marks it as clean.
        """
        self.index = Index(self.control_transport.local_abspath("index"))
        self._index_dirty = False

    def _get_submodule_index(self, relpath):
        """Get the index for a submodule.

        Args:
            relpath: The relative path to the submodule (as bytes).

        Returns:
            The Index object for the submodule.

        Raises:
            TypeError: If relpath is not bytes.
            tree.MissingNestedTree: If the submodule is not found.
        """
        if not isinstance(relpath, bytes):
            raise TypeError(relpath)
        try:
            info = self._submodule_info()[relpath]
        except KeyError:
            submodule_transport = self.user_transport.clone(decode_git_path(relpath))
            try:
                submodule_dir = self._format._matchingcontroldir.open(
                    submodule_transport
                )
            except errors.NotBranchError as e:
                raise tree.MissingNestedTree(relpath) from e
        else:
            submodule_transport = self.control_transport.clone(
                posixpath.join("modules", decode_git_path(info[1]))
            )
            try:
                submodule_dir = BareLocalGitControlDirFormat().open(submodule_transport)
            except errors.NotBranchError as e:
                raise tree.MissingNestedTree(relpath) from e
        return Index(submodule_dir.control_transport.local_abspath("index"))

    def lock_read(self):
        """Lock the repository for read operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self._lock_mode:
            self._lock_mode = "r"
            self._lock_count = 1
            self._read_index()
        else:
            self._lock_count += 1
        self.branch.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def _lock_write_tree(self):
        """Acquire a write lock on the tree without locking the branch.

        This is an internal method that sets up the necessary locks for
        writing to the working tree index file.

        Raises:
            errors.LockContention: If the index file is already locked.
            errors.ReadOnlyError: If attempting to write lock when already read-locked.
        """
        if not self._lock_mode:
            self._lock_mode = "w"
            self._lock_count = 1
            try:
                self._index_file = GitFile(
                    self.control_transport.local_abspath("index"), "wb"
                )
            except FileLocked as err:
                raise errors.LockContention("index") from err
            self._read_index()
        elif self._lock_mode == "r":
            raise errors.ReadOnlyError(self)
        else:
            self._lock_count += 1

    def lock_tree_write(self):
        """Lock the working tree for writing.

        This locks the branch for reading and the tree for writing.

        Returns:
            A LogicalLockResult that can be used to unlock the tree.
        """
        self.branch.lock_read()
        try:
            self._lock_write_tree()
            return lock.LogicalLockResult(self.unlock)
        except BaseException:
            self.branch.unlock()
            raise

    def lock_write(self, token=None):
        """Lock the working tree and branch for writing.

        Args:
            token: Unused lock token parameter for compatibility.

        Returns:
            A LogicalLockResult that can be used to unlock the tree.
        """
        self.branch.lock_write()
        try:
            self._lock_write_tree()
            return lock.LogicalLockResult(self.unlock)
        except BaseException:
            self.branch.unlock()
            raise

    def is_locked(self):
        """Return True if this tree is locked.

        Returns:
            True if the tree is currently locked, False otherwise.
        """
        return self._lock_count >= 1

    def get_physical_lock_status(self):
        """Return the physical lock status.

        Returns:
            False, as Git working trees don't use physical locks.
        """
        return False

    def break_lock(self):
        """Break any locks on this working tree.

        This removes index.lock if it exists and breaks the branch lock.
        """
        with contextlib.suppress(_mod_transport.NoSuchFile):
            self.control_transport.delete("index.lock")
        self.branch.break_lock()

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        """Unlock the working tree.

        This decrements the lock count and releases locks when the count
        reaches zero. If the index was modified, it will be flushed to disk.

        Raises:
            errors.LockNotHeld: If the tree is not currently locked.
            errors.LockBroken: If the lock is in an inconsistent state.
        """
        if not self._lock_count:
            return lock.cant_unlock_not_held(self)
        try:
            self._cleanup()
            self._lock_count -= 1
            if self._lock_count > 0:
                return
            if self._index_file is not None:
                if self._index_dirty:
                    self._flush(self._index_file)
                    self._index_file.close()
                else:
                    # Something else already triggered a write of the index
                    # file by calling .flush()
                    self._index_file.abort()
                self._index_file = None
            self._lock_mode = None
            self.index = None
        finally:
            self.branch.unlock()

    def _cleanup(self):
        """Perform cleanup operations before unlocking.

        This is a hook for subclasses to perform cleanup operations.
        """
        pass

    def _detect_case_handling(self):
        """Detect whether the filesystem is case-sensitive.

        Sets self.case_sensitive based on whether we can stat a file
        with different casing than the actual file.
        """
        try:
            self._transport.stat(".git/cOnFiG")
        except _mod_transport.NoSuchFile:
            self.case_sensitive = True
        else:
            self.case_sensitive = False

    def merge_modified(self):
        """Return a dictionary of modified files during merge.

        Returns:
            Empty dict, as Git working trees don't track merge modifications this way.
        """
        return {}

    def set_merge_modified(self, modified_hashes):
        """Set the merge modified hashes.

        Args:
            modified_hashes: Dictionary of modified file hashes.

        Raises:
            errors.UnsupportedOperation: This operation is not supported.
        """
        raise errors.UnsupportedOperation(self.set_merge_modified, self)

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """Set the parent trees for this working tree.

        Args:
            parents_list: List of (revision_id, tree) tuples.
            allow_leftmost_as_ghost: Whether to allow the leftmost parent to be a ghost.
        """
        self.set_parent_ids([p for p, t in parents_list])

    def _set_merges_from_parent_ids(self, rhs_parent_ids):
        try:
            merges = [
                self.branch.lookup_bzr_revision_id(revid)[0] for revid in rhs_parent_ids
            ]
        except errors.NoSuchRevision as e:
            raise errors.GhostRevisionUnusableHere(e.revision) from e
        if merges:
            self.control_transport.put_bytes(
                "MERGE_HEAD", b"\n".join(merges), mode=self.controldir._get_file_mode()
            )
        else:
            with contextlib.suppress(_mod_transport.NoSuchFile):
                self.control_transport.delete("MERGE_HEAD")

    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """Set the parent ids to revision_ids.

        See also set_parent_trees. This api will try to retrieve the tree data
        for each element of revision_ids from the trees repository. If you have
        tree data already available, it is more efficient to use
        set_parent_trees rather than set_parent_ids. set_parent_ids is however
        an easier API to use.

        :param revision_ids: The revision_ids to set as the parent ids of this
            working tree. Any of these may be ghosts.
        """
        with self.lock_tree_write():
            self._check_parents_for_ghosts(
                revision_ids, allow_leftmost_as_ghost=allow_leftmost_as_ghost
            )
            for revision_id in revision_ids:
                _mod_revision.check_not_reserved_id(revision_id)

            revision_ids = self._filter_parent_ids_by_ancestry(revision_ids)

            if len(revision_ids) > 0:
                self.set_last_revision(revision_ids[0])
            else:
                self.set_last_revision(_mod_revision.NULL_REVISION)

            self._set_merges_from_parent_ids(revision_ids[1:])

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        This implementation reads the pending merges list and last_revision
        value and uses that to decide what the parents list should be.
        """
        last_rev = self._last_revision()
        parents = [] if last_rev == _mod_revision.NULL_REVISION else [last_rev]
        try:
            merges_bytes = self.control_transport.get_bytes("MERGE_HEAD")
        except _mod_transport.NoSuchFile:
            pass
        else:
            for l in osutils.split_lines(merges_bytes):
                revision_id = l.rstrip(b"\n")
                parents.append(self.branch.lookup_foreign_revision_id(revision_id))
        return parents

    def check_state(self):
        """Check that the working state is/isn't valid.

        This is a no-op for Git working trees as they are always in a valid state.
        """
        pass

    def remove(self, files, verbose=False, to_file=None, keep_files=True, force=False):
        """Remove nominated files from the working tree metadata.

        :param files: File paths relative to the basedir.
        :param keep_files: If true, the files will also be kept.
        :param force: Delete files and directories, even if they are changed
            and even if the directories are not empty.
        """
        if not isinstance(files, list):
            files = [files]

        if to_file is None:
            to_file = sys.stdout

        def backup(file_to_backup):
            abs_path = self.abspath(file_to_backup)
            backup_name = self.controldir._available_backup_name(file_to_backup)
            osutils.rename(abs_path, self.abspath(backup_name))
            return f"removed {file_to_backup} (but kept a copy: {backup_name})"

        # Sort needed to first handle directory content before the directory
        files_to_backup = []

        all_files = set()

        def recurse_directory_to_add_files(directory):
            # Recurse directory and add all files
            # so we can check if they have changed.
            for _parent_path, file_infos in self.walkdirs(directory):
                for relpath, _basename, _kind, _lstat, _kind in file_infos:
                    # Is it versioned or ignored?
                    if self.is_versioned(relpath):
                        # Add nested content for deletion.
                        all_files.add(relpath)
                    else:
                        # Files which are not versioned
                        # should be treated as unknown.
                        files_to_backup.append(relpath)

        with self.lock_tree_write():
            for filepath in files:
                # Get file name into canonical form.
                abspath = self.abspath(filepath)
                filepath = self.relpath(abspath)

                if filepath:
                    all_files.add(filepath)
                    recurse_directory_to_add_files(filepath)

            files = list(all_files)

            if len(files) == 0:
                return  # nothing to do

            # Sort needed to first handle directory content before the
            # directory
            files.sort(reverse=True)

            # Bail out if we are going to delete files we shouldn't
            if not keep_files and not force:
                for change in self.iter_changes(
                    self.basis_tree(),
                    include_unchanged=True,
                    require_versioned=False,
                    want_unversioned=True,
                    specific_files=files,
                ):
                    if change.versioned[0] is False:
                        # The record is unknown or newly added
                        files_to_backup.append(change.path[1])
                        files_to_backup.extend(
                            osutils.parent_directories(change.path[1])
                        )
                    elif (
                        change.changed_content
                        and (change.kind[1] is not None)
                        and osutils.is_inside_any(files, change.path[1])
                    ):
                        # Versioned and changed, but not deleted, and still
                        # in one of the dirs to be deleted.
                        files_to_backup.append(change.path[1])
                        files_to_backup.extend(
                            osutils.parent_directories(change.path[1])
                        )

            for f in files:
                if f == "":
                    continue

                try:
                    kind = self.kind(f)
                except _mod_transport.NoSuchFile:
                    kind = None

                abs_path = self.abspath(f)
                if verbose:
                    # having removed it, it must be either ignored or unknown
                    new_status = "I" if self.is_ignored(f) else "?"
                    kind_ch = osutils.kind_marker(kind)
                    to_file.write(new_status + "       " + f + kind_ch + "\n")
                if kind is None:
                    message = f"{f} does not exist"
                else:
                    if not keep_files:
                        if f in files_to_backup and not force:
                            message = backup(f)
                        else:
                            if kind == "directory":
                                osutils.rmtree(abs_path)
                            else:
                                osutils.delete_any(abs_path)
                            message = f"deleted {f}"
                    else:
                        message = f"removed {f}"
                self._unversion_path(f)

                # print only one message (if any) per file.
                if message is not None:
                    trace.note(message)
            self._versioned_dirs = None

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        """Add files to the working tree intelligently.

        This method adds files and directories to the index, recursively
        adding directory contents and ignoring files that match ignore patterns.

        Args:
            file_list: List of files/directories to add. Defaults to ["."] if empty.
            recurse: Whether to recursively add directory contents.
            action: Optional callback function for each file being added.
            save: Whether to save changes to the index immediately.

        Returns:
            A tuple of (added_files, ignored_files_dict) where ignored_files_dict
            maps ignore patterns to lists of ignored files.
        """
        if not file_list:
            file_list = ["."]

        # expand any symlinks in the directory part, while leaving the
        # filename alone
        # only expanding if symlinks are supported avoids windows path bugs
        if self.supports_symlinks():
            file_list = list(map(osutils.normalizepath, file_list))

        conflicts_related = set()
        for c in self.conflicts():
            conflicts_related.update(c.associated_filenames())

        added = []
        ignored = {}
        user_dirs = []

        def call_action(filepath, kind):
            if filepath == "":
                return
            if action is not None:
                parent_path = posixpath.dirname(filepath)
                parent_id = self.path2id(parent_path)
                parent_ie = self._get_dir_ie(parent_path, parent_id)
                file_id = action(self, parent_ie, filepath, kind)
                if file_id is not None:
                    raise workingtree.SettingFileIdUnsupported()

        with self.lock_tree_write():
            for filepath in osutils.canonical_relpaths(self.basedir, file_list):
                filepath, can_access = osutils.normalized_filename(filepath)
                if not can_access:
                    raise errors.InvalidNormalization(filepath)

                abspath = self.abspath(filepath)
                kind = file_kind(abspath)
                if kind in ("file", "symlink"):
                    (index, subpath) = self._lookup_index(encode_git_path(filepath))
                    if subpath in index:
                        # Already present
                        continue
                    call_action(filepath, kind)
                    if save:
                        self._index_add_entry(filepath, kind)
                    added.append(filepath)
                elif kind == "directory":
                    (index, subpath) = self._lookup_index(encode_git_path(filepath))
                    if subpath not in index:
                        call_action(filepath, kind)
                    if recurse:
                        user_dirs.append(filepath)
                else:
                    raise errors.BadFileKindError(filename=abspath, kind=kind)
            for user_dir in user_dirs:
                abs_user_dir = self.abspath(user_dir)
                if user_dir != "":
                    try:
                        transport = _mod_transport.get_transport_from_path(abs_user_dir)
                        _mod_controldir.ControlDirFormat.find_format(transport)
                        subtree = True
                    except errors.NotBranchError:
                        subtree = False
                    except errors.UnsupportedFormatError:
                        subtree = False
                else:
                    subtree = False
                if subtree:
                    trace.warning("skipping nested tree %r", abs_user_dir)
                    continue

                for name in os.listdir(abs_user_dir):
                    subp = os.path.join(user_dir, name)
                    if self.is_control_filename(subp) or self.mapping.is_special_file(
                        subp
                    ):
                        continue
                    ignore_glob = self.is_ignored(subp)
                    if ignore_glob is not None:
                        ignored.setdefault(ignore_glob, []).append(subp)
                        continue
                    abspath = self.abspath(subp)
                    kind = file_kind(abspath)
                    if kind == "directory":
                        user_dirs.append(subp)
                    else:
                        (index, subpath) = self._lookup_index(encode_git_path(subp))
                        if subpath in index:
                            # Already present
                            continue
                        if subp in conflicts_related:
                            continue
                        call_action(subp, kind)
                        if save:
                            self._index_add_entry(subp, kind)
                        added.append(subp)
            return added, ignored

    def has_filename(self, filename):
        """Check if a filename exists in the working tree.

        Args:
            filename: The relative path to check.

        Returns:
            True if the file exists, False otherwise.
        """
        return osutils.lexists(self.abspath(filename))

    def _iter_files_recursive(
        self, from_dir=None, include_dirs=False, recurse_nested=False
    ):
        if from_dir is None:
            from_dir = ""
        if not isinstance(from_dir, str):
            raise TypeError(from_dir)
        encoded_from_dir = os.fsencode(self.abspath(from_dir))
        for dirpath, dirnames, filenames in os.walk(encoded_from_dir):
            dir_relpath = dirpath[len(self.basedir) :].strip(b"/")
            if self.controldir.is_control_filename(os.fsdecode(dir_relpath)):
                continue
            for name in list(dirnames):
                if self.controldir.is_control_filename(os.fsdecode(name)):
                    dirnames.remove(name)
                    continue
                relpath = os.path.join(dir_relpath, name)
                if not recurse_nested and self._directory_is_tree_reference(
                    os.fsdecode(relpath)
                ):
                    dirnames.remove(name)
                if include_dirs:
                    yield os.fsdecode(relpath)
                    if not self.is_versioned(os.fsdecode(os.fsdecode(relpath))):
                        try:
                            dirnames.remove(name)
                        except ValueError:
                            pass  # removed earlier
            for name in filenames:
                if self.mapping.is_special_file(name):
                    continue
                if self.controldir.is_control_filename(os.fsdecode(name)):
                    continue
                yp = os.path.join(dir_relpath, name)
                yield os.fsdecode(yp)

    def extras(self):
        """Yield all unversioned files in this WorkingTree."""
        with self.lock_read():
            index_paths = {
                decode_git_path(p) for p, _entry in self._recurse_index_entries()
            }
            all_paths = set(self._iter_files_recursive(include_dirs=False))
            return iter(all_paths - index_paths)

    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds."""
        with self.lock_tree_write():
            for pos, f in enumerate(files):
                if kinds[pos] is None:
                    fullpath = osutils.normpath(self.abspath(f))
                    try:
                        kind = file_kind(fullpath)
                    except FileNotFoundError as err:
                        raise _mod_transport.NoSuchFile(fullpath) from err
                    if f != "" and self._directory_is_tree_reference(f):
                        kind = "tree-reference"
                    kinds[pos] = kind

    def flush(self):
        """Flush pending changes to the index file.

        Raises:
            errors.NotWriteLocked: If the tree is not write-locked.
        """
        if self._lock_mode != "w":
            raise errors.NotWriteLocked(self)
        # TODO(jelmer): This shouldn't be writing in-place, but index.lock is
        # already in use and GitFile doesn't allow overriding the lock file
        # name :(
        f = open(self.control_transport.local_abspath("index"), "wb")
        # Note that _flush will close the file
        self._flush(f)

    def _flush(self, f):
        """Flush the index to a file.

        Args:
            f: The file object to write to.
        """
        try:
            shaf = SHA1Writer(f)
            write_index_dict(shaf, self.index)
            shaf.close()
        except BaseException:
            f.abort()
            raise
        self._index_dirty = False

    def get_file_mtime(self, path):
        """See Tree.get_file_mtime."""
        try:
            return self._lstat(path).st_mtime
        except FileNotFoundError as err:
            raise _mod_transport.NoSuchFile(path) from err

    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired.
        """
        if getattr(self, "_global_ignoreglobster", None) is None:
            from breezy import ignores

            ignore_globs = set()
            ignore_globs.update(ignores.get_runtime_ignores())
            ignore_globs.update(ignores.get_user_ignores())
            self._global_ignoreglobster = globbing.ExceptionGlobster(ignore_globs)
        match = self._global_ignoreglobster.match(filename)
        if match is not None:
            return match
        try:
            if self.kind(filename) == "directory":
                filename += "/"
        except _mod_transport.NoSuchFile:
            pass
        filename = filename.lstrip("/")
        ignore_manager = self._get_ignore_manager()
        ps = list(ignore_manager.find_matching(filename))
        if not ps:
            return None
        if not ps[-1].is_exclude:
            return None
        return bytes(ps[-1])

    def _get_ignore_manager(self):
        ignoremanager = getattr(self, "_ignoremanager", None)
        if ignoremanager is not None:
            return ignoremanager

        ignore_manager = IgnoreFilterManager.from_repo(self.repository._git)
        self._ignoremanager = ignore_manager
        return ignore_manager

    def _flush_ignore_list_cache(self):
        """Clear the cached ignore manager.

        This forces the ignore patterns to be re-read from .gitignore files
        on the next access.
        """
        self._ignoremanager = None

    def set_last_revision(self, revid):
        """Set the last revision of the working tree.

        Args:
            revid: The revision ID to set as the last revision.

        Returns:
            False if the revision is null, otherwise generates revision history.

        Raises:
            errors.GhostRevisionUnusableHere: If the revision doesn't exist.
        """
        if _mod_revision.is_null(revid):
            self.branch.set_last_revision_info(0, revid)
            return False
        _mod_revision.check_not_reserved_id(revid)
        try:
            self.branch.generate_revision_history(revid)
        except errors.NoSuchRevision as err:
            raise errors.GhostRevisionUnusableHere(revid) from err

    def _reset_data(self):
        """Reset internal data structures.

        This is a hook for subclasses to reset any cached data when the
        working tree state changes.
        """
        pass

    def get_file_verifier(self, path, stat_value=None):
        """Get a verifier for the file at the given path.

        Args:
            path: The path to get a verifier for.
            stat_value: Unused stat value parameter.

        Returns:
            A tuple of ("GIT", sha_hash) for files, or ("GIT", None) for directories.

        Raises:
            NoSuchFile: If the path is not versioned.
        """
        with self.lock_read():
            (index, subpath) = self._lookup_index(encode_git_path(path))
            try:
                return ("GIT", index[subpath].sha)
            except KeyError as err:
                if self._has_dir(path):
                    return ("GIT", None)
                raise _mod_transport.NoSuchFile(path) from err

    def get_file_sha1(self, path, stat_value=None):
        """Get the SHA-1 hash of a file's current contents.

        Args:
            path: The path to get the SHA-1 for.
            stat_value: Unused stat value parameter.

        Returns:
            The SHA-1 hash of the file's contents, or None if the file doesn't exist.

        Raises:
            NoSuchFile: If the path is not versioned.
        """
        with self.lock_read():
            if not self.is_versioned(path):
                raise _mod_transport.NoSuchFile(path)
            abspath = self.abspath(path)
            try:
                return osutils.sha_file_by_name(abspath)
            except (NotADirectoryError, FileNotFoundError):
                return None

    def revision_tree(self, revid):
        """Get a revision tree for the specified revision ID.

        Args:
            revid: The revision ID to get the tree for.

        Returns:
            A revision tree for the specified revision.
        """
        return self.repository.revision_tree(revid)

    def _is_executable_from_path_and_stat_from_stat(self, path, stat_result):
        """Check if a file is executable based on its stat result.

        Args:
            path: The file path (unused).
            stat_result: The os.stat result for the file.

        Returns:
            True if the file is executable, False otherwise.
        """
        mode = stat_result.st_mode
        return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def _is_executable_from_path_and_stat_from_basis(self, path, stat_result):
        """Check if a file is executable based on the basis tree.

        This method checks executability from the basis tree when the
        filesystem doesn't support executable bits.

        Args:
            path: The file path to check.
            stat_result: The os.stat result (unused).

        Returns:
            True if the file is executable according to the basis tree.
        """
        return self.basis_tree().is_executable(path)

    def stored_kind(self, path):
        """Return the stored file kind for a path.

        This returns the kind of file as stored in the index, which may
        differ from the current kind on disk.

        Args:
            path: The path to check.

        Returns:
            The file kind ("file", "directory", "symlink", etc.).

        Raises:
            NoSuchFile: If the path is not in the index.
        """
        with self.lock_read():
            encoded_path = encode_git_path(path)
            (index, subpath) = self._lookup_index(encoded_path)
            try:
                entry = index[subpath]
            except KeyError as err:
                # Maybe it's a directory?
                if self._has_dir(encoded_path):
                    return "directory"
                raise _mod_transport.NoSuchFile(path) from err
            entry = getattr(entry, "this", entry)
            return mode_kind(entry.mode)

    def _lstat(self, path):
        """Get the lstat result for a path.

        Args:
            path: The relative path to stat.

        Returns:
            The os.lstat result for the file.
        """
        return os.lstat(self.abspath(path))

    def _live_entry(self, path):
        """Create an index entry from the current state of a file.

        Args:
            path: The Git-encoded path to create an entry for.

        Returns:
            An IndexEntry representing the current file state.
        """
        encoded_path = os.fsencode(self.abspath(decode_git_path(path)))
        return index_entry_from_path(encoded_path)

    def is_executable(self, path):
        """Check if a file is executable.

        Args:
            path: The path to check.

        Returns:
            True if the file is executable, False otherwise.
        """
        with self.lock_read():
            if self._supports_executable():
                mode = self._lstat(path).st_mode
            else:
                (index, subpath) = self._lookup_index(encode_git_path(path))
                try:
                    mode = index[subpath].mode
                except KeyError:
                    mode = 0
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def _is_executable_from_path_and_stat(self, path, stat_result):
        if self._supports_executable():
            return self._is_executable_from_path_and_stat_from_stat(path, stat_result)
        else:
            return self._is_executable_from_path_and_stat_from_basis(path, stat_result)

    def list_files(
        self, include_root=False, from_dir=None, recursive=True, recurse_nested=False
    ):
        """List files in the working tree.

        Args:
            include_root: Whether to include the root directory.
            from_dir: Directory to start listing from.
            recursive: Whether to list files recursively.
            recurse_nested: Whether to recurse into nested trees.

        Yields:
            Tuples of (path, status, kind, file_entry) for each file.
        """
        if from_dir is None or from_dir == ".":
            from_dir = ""
        dir_ids = {}
        fk_entries = {
            "directory": tree.TreeDirectory,
            "file": tree.TreeFile,
            "symlink": tree.TreeLink,
            "tree-reference": tree.TreeReference,
        }
        with self.lock_read():
            root_ie = self._get_dir_ie("", None)
            if include_root and not from_dir:
                yield "", "V", root_ie.kind, root_ie
            dir_ids[""] = root_ie.file_id
            if recursive:
                path_iterator = sorted(
                    self._iter_files_recursive(
                        from_dir, include_dirs=True, recurse_nested=recurse_nested
                    )
                )
            else:
                encoded_from_dir = os.fsencode(self.abspath(from_dir))
                path_iterator = sorted(
                    [
                        os.path.join(from_dir, os.fsdecode(name))
                        for name in os.listdir(encoded_from_dir)
                        if not self.controldir.is_control_filename(os.fsdecode(name))
                        and not self.mapping.is_special_file(os.fsdecode(name))
                    ]
                )
            for path in path_iterator:
                encoded_path = encode_git_path(path)
                (index, index_path) = self._lookup_index(encoded_path)
                try:
                    value = index[index_path]
                except KeyError:
                    value = None
                kind = self.kind(path)
                parent, name = posixpath.split(path)
                for _dir_path, _dir_ie in self._add_missing_parent_ids(parent, dir_ids):
                    pass
                if kind == "tree-reference" and recurse_nested:
                    ie = self._get_dir_ie(path, self.path2id(path))
                    yield (posixpath.relpath(path, from_dir), "V", "directory", ie)
                    continue
                if kind == "directory":
                    if path != from_dir:
                        if self._has_dir(encoded_path):
                            ie = self._get_dir_ie(path, self.path2id(path))
                            status = "V"
                        elif self.is_ignored(path):
                            status = "I"
                            ie = fk_entries[kind]()
                        else:
                            status = "?"
                            ie = fk_entries[kind]()
                        yield (posixpath.relpath(path, from_dir), status, kind, ie)
                    continue
                if value is not None:
                    ie = self._get_file_ie(name, path, value, dir_ids[parent])
                    yield (posixpath.relpath(path, from_dir), "V", ie.kind, ie)
                else:
                    try:
                        ie = fk_entries[kind]()
                    except KeyError:
                        # unsupported kind
                        continue
                    yield (
                        posixpath.relpath(path, from_dir),
                        ("I" if self.is_ignored(path) else "?"),
                        kind,
                        ie,
                    )

    def all_versioned_paths(self):
        """Return all paths that are versioned in this tree.

        Returns:
            A set of all versioned paths, including parent directories.
        """
        with self.lock_read():
            paths = {""}
            for path in self.index:
                if self.mapping.is_special_file(path):
                    continue
                path = decode_git_path(path)
                paths.add(path)
                while path != "":
                    path = posixpath.dirname(path).strip("/")
                    if path in paths:
                        break
                    paths.add(path)
            return paths

    def iter_child_entries(self, path):
        """Iterate over the child entries of a directory.

        Args:
            path: The directory path to get children for.

        Yields:
            InventoryEntry objects for each child.

        Raises:
            NoSuchFile: If the directory doesn't exist.
        """
        encode_git_path(path)
        with self.lock_read():
            parent_id = self.path2id(path)
            found_any = False
            for item_path, value in self.index.iteritems():
                decoded_item_path = decode_git_path(item_path)
                if self.mapping.is_special_file(item_path):
                    continue
                if not osutils.is_inside(path, decoded_item_path):
                    continue
                found_any = True
                subpath = posixpath.relpath(decoded_item_path, path)
                if "/" in subpath:
                    dirname = subpath.split("/", 1)[0]
                    file_ie = self._get_dir_ie(posixpath.join(path, dirname), parent_id)
                else:
                    (unused_parent, name) = posixpath.split(decoded_item_path)
                    file_ie = self._get_file_ie(
                        name, decoded_item_path, value, parent_id
                    )
                yield file_ie
            if not found_any and path != "":
                raise _mod_transport.NoSuchFile(path)

    def conflicts(self):
        """Return the current conflicts in the working tree.

        Returns:
            A ConflictList containing all current conflicts.
        """
        with self.lock_read():
            conflicts = _mod_conflicts.ConflictList()
            for item_path, value in self.index.iteritems():
                if isinstance(value, ConflictedIndexEntry):
                    conflicts.append(TextConflict(decode_git_path(item_path)))
            return conflicts

    def set_conflicts(self, conflicts):
        """Set the conflicts in the working tree.

        Args:
            conflicts: A list of conflict objects to set.

        Raises:
            UnsupportedOperation: If any conflict type is not supported.
        """
        by_path = {}
        for conflict in conflicts:
            if not isinstance(conflict, (TextConflict, ContentsConflict)):
                raise errors.UnsupportedOperation(self.set_conflicts, self)
            if conflict.typestring in ("text conflict", "contents conflict"):
                by_path[encode_git_path(conflict.path)] = conflict
            else:
                raise errors.UnsupportedOperation(self.set_conflicts, self)
        with self.lock_tree_write():
            to_delete = set()
            for path in self.index:
                self._index_dirty = True
                conflict = by_path.get(path)
                if conflict is not None:
                    self.index[path] = conflict.to_index_entry(self)
                else:
                    try:
                        if isinstance(self.index[path], ConflictedIndexEntry):
                            new = self.index[path].this
                            if new is None:
                                to_delete.add(path)
                            else:
                                self.index[path] = new
                    except KeyError:
                        pass
            for path in to_delete:
                del self.index[path]

    def add_conflicts(self, new_conflicts):
        """Add new conflicts to the working tree.

        Args:
            new_conflicts: A list of conflict objects to add.

        Raises:
            UnsupportedOperation: If any conflict type is not supported.
        """
        with self.lock_tree_write():
            for conflict in new_conflicts:
                if not isinstance(conflict, (TextConflict, ContentsConflict)):
                    raise errors.UnsupportedOperation(self.set_conflicts, self)

                if conflict.typestring in ("text conflict", "contents conflict"):
                    self._index_dirty = True
                    try:
                        entry = conflict.to_index_entry(self)
                        if (
                            entry.this is None
                            and entry.ancestor is None
                            and entry.other is None
                        ):
                            continue
                        self.index[encode_git_path(conflict.path)] = entry
                    except KeyError as err:
                        raise errors.UnsupportedOperation(
                            self.add_conflicts, self
                        ) from err
                else:
                    raise errors.UnsupportedOperation(self.add_conflicts, self)

    def walkdirs(self, prefix=""):
        """Walk the directories of this tree.

        returns a generator which yields items in the form:
                (current_directory_path,
                 [(file1_path, file1_name, file1_kind, (lstat),
                   file1_kind), ... ])

        This API returns a generator, which is only valid during the current
        tree transaction - within a single lock_read or lock_write duration.

        If the tree is not locked, it may cause an error to be raised,
        depending on the tree implementation.
        """
        import operator
        from bisect import bisect_left

        disk_top = self.abspath(prefix)
        if disk_top.endswith("/"):
            disk_top = disk_top[:-1]
        top_strip_len = len(disk_top) + 1
        inventory_iterator = self._walkdirs(prefix)
        disk_iterator = osutils.walkdirs(disk_top, prefix)
        try:
            current_disk = next(disk_iterator)
            disk_finished = False
        except FileNotFoundError:
            current_disk = None
            disk_finished = True
        try:
            current_inv = next(inventory_iterator)
            inv_finished = False
        except StopIteration:
            current_inv = None
            inv_finished = True
        while not inv_finished or not disk_finished:
            if current_disk:
                (
                    (cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content,
                ) = current_disk
            else:
                (
                    (cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content,
                ) = ((None, None), None)
            if not disk_finished:
                # strip out .bzr dirs
                if (
                    cur_disk_dir_path_from_top[top_strip_len:] == ""
                    and len(cur_disk_dir_content) > 0
                ):
                    # osutils.walkdirs can be made nicer -
                    # yield the path-from-prefix rather than the pathjoined
                    # value.
                    bzrdir_loc = bisect_left(cur_disk_dir_content, (".git", ".git"))
                    if bzrdir_loc < len(
                        cur_disk_dir_content
                    ) and self.controldir.is_control_filename(
                        cur_disk_dir_content[bzrdir_loc][0]
                    ):
                        # we dont yield the contents of, or, .bzr itself.
                        del cur_disk_dir_content[bzrdir_loc]
            if inv_finished:
                # everything is unknown
                direction = 1
            elif disk_finished:
                # everything is missing
                direction = -1
            else:
                direction = (current_inv[0][0] > cur_disk_dir_relpath) - (
                    current_inv[0][0] < cur_disk_dir_relpath
                )
            if direction > 0:
                # disk is before inventory - unknown
                dirblock = [
                    (relpath, basename, kind, stat, None)
                    for relpath, basename, kind, stat, top_path in cur_disk_dir_content
                ]
                yield cur_disk_dir_relpath, dirblock
                try:
                    current_disk = next(disk_iterator)
                except StopIteration:
                    disk_finished = True
            elif direction < 0:
                # inventory is before disk - missing.
                dirblock = [
                    (relpath, basename, "unknown", None, kind)
                    for relpath, basename, dkind, stat, fileid, kind in current_inv[1]
                ]
                yield current_inv[0][0], dirblock
                try:
                    current_inv = next(inventory_iterator)
                except StopIteration:
                    inv_finished = True
            else:
                # versioned present directory
                # merge the inventory and disk data together
                dirblock = []
                for _relpath, subiterator in itertools.groupby(
                    sorted(
                        current_inv[1] + cur_disk_dir_content,
                        key=operator.itemgetter(0),
                    ),
                    operator.itemgetter(1),
                ):
                    path_elements = list(subiterator)
                    if len(path_elements) == 2:
                        inv_row, disk_row = path_elements
                        # versioned, present file
                        dirblock.append(
                            (
                                inv_row[0],
                                inv_row[1],
                                disk_row[2],
                                disk_row[3],
                                inv_row[5],
                            )
                        )
                    elif len(path_elements[0]) == 5:
                        # unknown disk file
                        dirblock.append(
                            (
                                path_elements[0][0],
                                path_elements[0][1],
                                path_elements[0][2],
                                path_elements[0][3],
                                None,
                            )
                        )
                    elif len(path_elements[0]) == 6:
                        # versioned, absent file.
                        dirblock.append(
                            (
                                path_elements[0][0],
                                path_elements[0][1],
                                "unknown",
                                None,
                                path_elements[0][5],
                            )
                        )
                    else:
                        raise NotImplementedError("unreachable code")
                yield current_inv[0][0], dirblock
                try:
                    current_inv = next(inventory_iterator)
                except StopIteration:
                    inv_finished = True
                try:
                    current_disk = next(disk_iterator)
                except StopIteration:
                    disk_finished = True

    def _walkdirs(self, prefix=""):
        """Walk the versioned directories starting from prefix.

        Args:
            prefix: The directory prefix to start walking from.

        Yields:
            Tuples of ((dir_path, dir_file_id), list_of_entries) for each directory.
        """
        if prefix != "":
            prefix += "/"
        prefix = encode_git_path(prefix)
        per_dir = defaultdict(set)
        if prefix == b"":
            per_dir[("", self.path2id(""))] = set()

        def add_entry(path, kind):
            if path == b"" or not path.startswith(prefix):
                return
            (dirname, child_name) = posixpath.split(path)
            add_entry(dirname, "directory")
            dirname = decode_git_path(dirname)
            dir_file_id = self.path2id(dirname)
            if not isinstance(value, (tuple, IndexEntry)):
                raise ValueError(value)
            per_dir[(dirname, dir_file_id)].add(
                (
                    decode_git_path(path),
                    decode_git_path(child_name),
                    kind,
                    None,
                    self.path2id(decode_git_path(path)),
                    kind,
                )
            )

        with self.lock_read():
            for path, value in self.index.iteritems():
                if self.mapping.is_special_file(path):
                    continue
                if not path.startswith(prefix):
                    continue
                add_entry(path, mode_kind(value.mode))
        return ((k, sorted(v)) for (k, v) in sorted(per_dir.items()))

    def get_shelf_manager(self):
        """Return a shelf manager for this working tree.

        Raises:
            ShelvingUnsupported: Git working trees don't support shelving.
        """
        raise workingtree.ShelvingUnsupported()

    def store_uncommitted(self):
        """Store uncommitted changes.

        Raises:
            StoringUncommittedNotSupported: Git working trees don't support this operation.
        """
        raise errors.StoringUncommittedNotSupported(self)

    def annotate_iter(self, path, default_revision=_mod_revision.CURRENT_REVISION):
        """See Tree.annotate_iter.

        This implementation will use the basis tree implementation if possible.
        Lines not in the basis are attributed to CURRENT_REVISION

        If there are pending merges, lines added by those merges will be
        incorrectly attributed to CURRENT_REVISION (but after committing, the
        attribution will be correct).
        """
        with self.lock_read():
            maybe_file_parent_keys = []
            for parent_id in self.get_parent_ids():
                try:
                    parent_tree = self.revision_tree(parent_id)
                except errors.NoSuchRevisionInTree:
                    parent_tree = self.branch.repository.revision_tree(parent_id)
                with parent_tree.lock_read():
                    # TODO(jelmer): Use rename/copy tracker to find path name
                    # in parent
                    parent_path = path
                    try:
                        kind = parent_tree.kind(parent_path)
                    except _mod_transport.NoSuchFile:
                        continue
                    if kind != "file":
                        # Note: this is slightly unnecessary, because symlinks
                        # and directories have a "text" which is the empty
                        # text, and we know that won't mess up annotations. But
                        # it seems cleaner
                        continue
                    parent_text_key = (
                        parent_path,
                        parent_tree.get_file_revision(parent_path),
                    )
                    if parent_text_key not in maybe_file_parent_keys:
                        maybe_file_parent_keys.append(parent_text_key)
            # Now we have the parents of this content
            from ..bzr.annotate import VersionedFileAnnotator
            from .annotate import AnnotateProvider

            annotate_provider = AnnotateProvider(
                self.branch.repository._file_change_scanner
            )
            annotator = VersionedFileAnnotator(annotate_provider)

            from ..graph import Graph

            graph = Graph(annotate_provider)
            heads = graph.heads(maybe_file_parent_keys)
            file_parent_keys = []
            for key in maybe_file_parent_keys:
                if key in heads:
                    file_parent_keys.append(key)

            text = self.get_file_text(path)
            this_key = (path, default_revision)
            annotator.add_special_text(this_key, file_parent_keys, text)
            annotations = [
                (key[-1], line) for key, line in annotator.annotate_flat(this_key)
            ]
            return annotations

    def _rename_one(self, from_rel, to_rel):
        """Rename a single file or directory.

        Args:
            from_rel: The source path relative to the tree root.
            to_rel: The target path relative to the tree root.
        """
        os.rename(self.abspath(from_rel), self.abspath(to_rel))

    def _build_checkout_with_index(self):
        """Build a checkout with an index from the current branch head.

        This creates an index file that reflects the state of the tree
        at the branch head, used for initializing working trees.
        """
        build_index_from_tree(
            self.user_transport.local_abspath("."),
            self.control_transport.local_abspath("index"),
            self.store,
            None if self.branch.head is None else self.store[self.branch.head].tree,
            honor_filemode=self._supports_executable(),
        )

    def reset_state(self, revision_ids=None):
        """Reset the state of the working tree.

        This does a hard-reset to a last-known-good state. This is a way to
        fix if something got corrupted (like the .git/index file)
        """
        with self.lock_tree_write():
            if revision_ids is not None:
                self.set_parent_ids(revision_ids)
            self.index.clear()
            self._index_dirty = True
            if self.branch.head is not None:
                for entry in iter_tree_contents(
                    self.store, self.store[self.branch.head].tree
                ):
                    if not validate_path(entry.path):
                        continue

                    if S_ISGITLINK(entry.mode):
                        pass  # TODO(jelmer): record and return submodule paths
                    else:
                        # Let's at least try to use the working tree file:
                        try:
                            st = self._lstat(self.abspath(decode_git_path(entry.path)))
                        except OSError:
                            # But if it doesn't exist, we'll make something up.
                            obj = self.store[entry.sha]
                            st = os.stat_result(
                                (
                                    entry.mode,
                                    0,
                                    0,
                                    0,
                                    0,
                                    0,
                                    len(obj.as_raw_string()),
                                    0,
                                    0,
                                    0,
                                )
                            )
                    (index, subpath) = self._lookup_index(entry.path)
                    index[subpath] = index_entry_from_stat(
                        st, entry.sha, mode=entry.mode
                    )

    def _update_git_tree(
        self, old_revision, new_revision, change_reporter=None, show_base=False
    ):
        basis_tree = self.revision_tree(old_revision)
        if new_revision != old_revision:
            from ..merge import merge_inner

            with basis_tree.lock_read():
                new_basis_tree = self.branch.basis_tree()
                merge_inner(
                    self.branch,
                    new_basis_tree,
                    basis_tree,
                    this_tree=self,
                    change_reporter=change_reporter,
                    show_base=show_base,
                )

    def pull(
        self,
        source,
        overwrite=False,
        stop_revision=None,
        change_reporter=None,
        possible_transports=None,
        local=False,
        show_base=False,
        tag_selector=None,
    ):
        """Pull changes from a source branch into this working tree.

        Args:
            source: The source branch to pull from.
            overwrite: Whether to overwrite local changes.
            stop_revision: The revision to stop pulling at.
            change_reporter: Optional change reporter for progress.
            possible_transports: List of transports to try.
            local: Whether to pull locally only.
            show_base: Whether to show base text in conflicts.
            tag_selector: Function to select which tags to pull.

        Returns:
            The number of revisions pulled.
        """
        with self.lock_write(), source.lock_read():
            old_revision = self.branch.last_revision()
            count = self.branch.pull(
                source,
                overwrite=overwrite,
                stop_revision=stop_revision,
                possible_transports=possible_transports,
                local=local,
                tag_selector=tag_selector,
            )
            self._update_git_tree(
                old_revision=old_revision,
                new_revision=self.branch.last_revision(),
                change_reporter=change_reporter,
                show_base=show_base,
            )
            return count

    def add_reference(self, sub_tree):
        """Add a TreeReference to the tree, pointing at sub_tree.

        :param sub_tree: subtree to add.
        """
        with self.lock_tree_write():
            try:
                sub_tree_path = self.relpath(sub_tree.basedir)
            except errors.PathNotChild as err:
                raise BadReferenceTarget(
                    self, sub_tree, "Target not inside tree."
                ) from err

            path, can_access = osutils.normalized_filename(sub_tree_path)
            if not can_access:
                raise errors.InvalidNormalization(path)
            self._index_add_entry(sub_tree_path, "tree-reference")

    def _read_submodule_head(self, path):
        """Read the HEAD revision of a submodule.

        Args:
            path: The path to the submodule.

        Returns:
            The SHA-1 hash of the submodule's HEAD, or None if not found.
        """
        return read_submodule_head(self.abspath(path))

    def get_reference_revision(self, path):
        """Get the revision ID that a tree reference points to.

        Args:
            path: The path to the tree reference.

        Returns:
            The revision ID that the reference points to.
        """
        hexsha = self._read_submodule_head(path)
        if hexsha is None:
            (index, subpath) = self._lookup_index(encode_git_path(path))
            if subpath is None:
                raise _mod_transport.NoSuchFile(path)
            hexsha = index[subpath].sha
        return self.branch.lookup_foreign_revision_id(hexsha)

    def get_nested_tree(self, path):
        """Get the nested working tree at the given path.

        Args:
            path: The path to the nested tree.

        Returns:
            A WorkingTree object for the nested tree.

        Raises:
            MissingNestedTree: If no nested tree exists at the path.
        """
        try:
            return workingtree.WorkingTree.open(self.abspath(path))
        except errors.NotBranchError as e:
            raise tree.MissingNestedTree(path) from e

    def _directory_is_tree_reference(self, relpath):
        """Check if a directory is a tree reference (submodule).

        Args:
            relpath: The relative path to check.

        Returns:
            True if the directory contains a .git file/directory and is not
            the root of this tree.
        """
        # as a special case, if a directory contains control files then
        # it's a tree reference, except that the root of the tree is not
        return relpath and osutils.lexists(self.abspath(relpath) + "/.git")

    def extract(self, sub_path, format=None):
        """Extract a subtree from this tree.

        A new branch will be created, relative to the path for this tree.
        """

        def mkdirs(path):
            segments = osutils.splitpath(path)
            transport = self.branch.controldir.root_transport
            for name in segments:
                transport = transport.clone(name)
                transport.ensure_base()
            return transport

        with self.lock_tree_write():
            self.flush()
            branch_transport = mkdirs(sub_path)
            if format is None:
                format = self.controldir.cloning_metadir()
            branch_transport.ensure_base()
            branch_bzrdir = format.initialize_on_transport(branch_transport)
            try:
                repo = branch_bzrdir.find_repository()
            except errors.NoRepositoryPresent:
                repo = branch_bzrdir.create_repository()
            if not repo.supports_rich_root():
                raise errors.RootNotRich()
            new_branch = branch_bzrdir.create_branch()
            new_branch.pull(self.branch)
            for parent_id in self.get_parent_ids():
                new_branch.fetch(self.branch, parent_id)
            tree_transport = self.controldir.root_transport.clone(sub_path)
            if tree_transport.base != branch_transport.base:
                tree_bzrdir = format.initialize_on_transport(tree_transport)
                tree_bzrdir.set_branch_reference(new_branch)
            else:
                tree_bzrdir = branch_bzrdir
            wt = tree_bzrdir.create_workingtree(_mod_revision.NULL_REVISION)
            wt.set_parent_ids(self.get_parent_ids())
            return wt

    def _get_check_refs(self):
        """Return the references needed to perform a check of this tree.

        The default implementation returns no refs, and is only suitable for
        trees that have no local caching and can commit on ghosts at any time.

        :seealso: breezy.check for details about check_refs.
        """
        return []

    def copy_content_into(self, tree, revision_id=None):
        """Copy the current content and user files of this tree into tree."""
        from .. import merge

        with self.lock_read():
            if revision_id is None:
                merge.transform_tree(tree, self)
            else:
                # TODO now merge from tree.last_revision to revision (to
                # preserve user local changes)
                try:
                    other_tree = self.revision_tree(revision_id)
                except errors.NoSuchRevision:
                    other_tree = self.branch.repository.revision_tree(revision_id)

                merge.transform_tree(tree, other_tree)
                if revision_id == _mod_revision.NULL_REVISION:
                    new_parents = []
                else:
                    new_parents = [revision_id]
                tree.set_parent_ids(new_parents)

    def reference_parent(self, path, possible_transports=None):
        """Get the parent branch for a tree reference.

        Args:
            path: The path to the tree reference.
            possible_transports: List of transports to try.

        Returns:
            A Branch object for the parent, or None if not found.
        """
        remote_url = self.get_reference_info(path)
        if remote_url is None:
            trace.warning("Unable to find submodule info for %s", path)
            return None
        return _mod_branch.Branch.open(
            remote_url, possible_transports=possible_transports
        )

    def get_reference_info(self, path):
        """Get the reference information for a tree reference.

        Args:
            path: The path to the tree reference.

        Returns:
            The URL of the referenced repository, or None if not found.
        """
        submodule_info = self._submodule_info()
        info = submodule_info.get(encode_git_path(path))
        if info is None:
            return None
        return decode_git_path(info[0])

    def set_reference_info(self, tree_path, branch_location):
        """Set the reference information for a tree reference.

        This updates the .gitmodules file with the submodule information.

        Args:
            tree_path: The path where the tree reference is located.
            branch_location: The URL of the referenced repository, or None to remove.
        """
        path = self.abspath(".gitmodules")
        try:
            config = GitConfigFile.from_path(path)
        except FileNotFoundError:
            config = GitConfigFile()
        section = (b"submodule", encode_git_path(tree_path))
        if branch_location is None:
            with contextlib.suppress(KeyError):
                del config[section]
        else:
            branch_location = urlutils.join(
                urlutils.strip_segment_parameters(self.branch.user_url), branch_location
            )
            config.set(section, b"path", encode_git_path(tree_path))
            config.set(section, b"url", branch_location.encode("utf-8"))
        config.write_to_path(path)
        self.add(".gitmodules")

    _marker = object()

    def subsume(self, other_tree):
        """Subsume another working tree into this one.

        This operation merges another working tree's content and history
        into this tree as a subdirectory.

        Args:
            other_tree: The working tree to subsume.

        Raises:
            errors.BadSubsumeSource: If the other tree is not contained within this tree.
        """
        for parent_id in other_tree.get_parent_ids():
            self.branch.repository.fetch(other_tree.branch.repository, parent_id)
        self.set_parent_ids(self.get_parent_ids() + other_tree.get_parent_ids())
        with self.lock_tree_write(), other_tree.lock_tree_write():
            try:
                other_tree_path = self.relpath(other_tree.basedir)
            except errors.PathNotChild as err:
                raise errors.BadSubsumeSource(
                    self, other_tree, "Tree is not contained by the other"
                ) from err

            other_tree_bytes = encode_git_path(other_tree_path)

            ids = {}
            for p, e in other_tree.index.iteritems():
                newp = other_tree_bytes + b"/" + p
                self.index[newp] = e
                self._index_dirty = True
                ids[e.sha] = newp

            self.store.add_objects([(other_tree.store[i], p) for (i, p) in ids.items()])

        other_tree.controldir.retire_controldir()

    def update(
        self,
        change_reporter=None,
        possible_transports=None,
        revision=None,
        old_tip=_marker,
        show_base=False,
    ):
        """Update a working tree along its branch.

        This will update the branch if its bound too, which means we have
        multiple trees involved:

        - The new basis tree of the master.
        - The old basis tree of the branch.
        - The old basis tree of the working tree.
        - The current working tree state.

        Pathologically, all three may be different, and non-ancestors of each
        other.  Conceptually we want to:

        - Preserve the wt.basis->wt.state changes
        - Transform the wt.basis to the new master basis.
        - Apply a merge of the old branch basis to get any 'local' changes from
          it into the tree.
        - Restore the wt.basis->wt.state changes.

        There isn't a single operation at the moment to do that, so we:

        - Merge current state -> basis tree of the master w.r.t. the old tree
          basis.
        - Do a 'normal' merge of the old branch basis if it is relevant.

        :param revision: The target revision to update to. Must be in the
            revision history.
        :param old_tip: If branch.update() has already been run, the value it
            returned (old tip of the branch or None). _marker is used
            otherwise.
        """
        if self.branch.get_bound_location() is not None:
            self.lock_write()
            update_branch = old_tip is self._marker
        else:
            self.lock_tree_write()
            update_branch = False
        try:
            if update_branch:
                old_tip = self.branch.update(possible_transports)
            else:
                if old_tip is self._marker:
                    old_tip = None
            return self._update_tree(old_tip, change_reporter, revision, show_base)
        finally:
            self.unlock()

    def _update_tree(
        self, old_tip=None, change_reporter=None, revision=None, show_base=False
    ):
        """Update a tree to the master branch.

        :param old_tip: if supplied, the previous tip revision the branch,
            before it was changed to the master branch's tip.
        """
        # here if old_tip is not None, it is the old tip of the branch before
        # it was updated from the master branch. This should become a pending
        # merge in the working tree to preserve the user existing work.  we
        # cant set that until we update the working trees last revision to be
        # one from the new branch, because it will just get absorbed by the
        # parent de-duplication logic.
        #
        # We MUST save it even if an error occurs, because otherwise the users
        # local work is unreferenced and will appear to have been lost.
        #
        with self.lock_tree_write():
            from ..merge import merge_inner

            nb_conflicts = []
            try:
                last_rev = self.get_parent_ids()[0]
            except IndexError:
                last_rev = _mod_revision.NULL_REVISION
            if revision is None:
                revision = self.branch.last_revision()

            old_tip = old_tip or _mod_revision.NULL_REVISION

            if not _mod_revision.is_null(old_tip) and old_tip != last_rev:
                # the branch we are bound to was updated
                # merge those changes in first
                base_tree = self.basis_tree()
                other_tree = self.branch.repository.revision_tree(old_tip)
                nb_conflicts = merge_inner(
                    self.branch,
                    other_tree,
                    base_tree,
                    this_tree=self,
                    change_reporter=change_reporter,
                    show_base=show_base,
                )
                if nb_conflicts:
                    self.add_parent_tree((old_tip, other_tree))
                    return len(nb_conflicts)

            if last_rev != revision:
                to_tree = self.branch.repository.revision_tree(revision)

                # determine the branch point
                graph = self.branch.repository.get_graph()
                base_rev_id = graph.find_unique_lca(
                    self.branch.last_revision(), last_rev
                )
                base_tree = self.branch.repository.revision_tree(base_rev_id)

                nb_conflicts = merge_inner(
                    self.branch,
                    to_tree,
                    base_tree,
                    this_tree=self,
                    change_reporter=change_reporter,
                    show_base=show_base,
                )
                self.set_last_revision(revision)
                # TODO - dedup parents list with things merged by pull ?
                # reuse the tree we've updated to to set the basis:
                parent_trees = [(revision, to_tree)]
                merges = self.get_parent_ids()[1:]
                # Ideally we ask the tree for the trees here, that way the working
                # tree can decide whether to give us the entire tree or give us a
                # lazy initialised tree. dirstate for instance will have the trees
                # in ram already, whereas a last-revision + basis-inventory tree
                # will not, but also does not need them when setting parents.
                for parent in merges:
                    parent_trees.append(
                        (parent, self.branch.repository.revision_tree(parent))
                    )
                if not _mod_revision.is_null(old_tip):
                    parent_trees.append(
                        (old_tip, self.branch.repository.revision_tree(old_tip))
                    )
                self.set_parent_trees(parent_trees)
                last_rev = parent_trees[0][0]
            return len(nb_conflicts)


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):
    """Format for Git working trees.

    This format provides Git working tree functionality within the Breezy framework.
    It does not support versioned directories, file IDs, or storing uncommitted changes.
    """

    _tree_class = GitWorkingTree

    supports_versioned_directories = False

    supports_setting_file_ids = False

    supports_store_uncommitted = False

    supports_leftmost_parent_id_as_ghost = False

    supports_righthand_parent_id_as_ghost = False

    requires_normalized_unicode_filenames = True

    supports_merge_modified = False

    ignore_filename = ".gitignore"

    @property
    def _matchingcontroldir(self):
        """Return the control directory format that matches this working tree format.

        Returns:
            A LocalGitControlDirFormat instance.
        """
        from .dir import LocalGitControlDirFormat

        return LocalGitControlDirFormat()

    def get_format_description(self):
        """Return a human-readable description of this format.

        Returns:
            A string describing this format.
        """
        return "Git Working Tree"

    def initialize(
        self,
        a_controldir,
        revision_id=None,
        from_branch=None,
        accelerator_tree=None,
        hardlink=False,
    ):
        """Initialize a new Git working tree.

        Args:
            a_controldir: The control directory to initialize the working tree in.
            revision_id: The revision ID to set as the initial revision.
            from_branch: Unused for Git working trees.
            accelerator_tree: Unused for Git working trees.
            hardlink: Unused for Git working trees.

        Returns:
            A new GitWorkingTree instance.

        Raises:
            errors.IncompatibleFormat: If a_controldir is not a LocalGitDir.
        """
        if not isinstance(a_controldir, LocalGitDir):
            raise errors.IncompatibleFormat(self, a_controldir)
        branch = a_controldir.open_branch(nascent_ok=True)
        if revision_id is not None:
            branch.set_last_revision(revision_id)
        wt = GitWorkingTree(a_controldir, a_controldir.open_repository(), branch)
        for hook in MutableTree.hooks["post_build_tree"]:
            hook(wt)
        return wt

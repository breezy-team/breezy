# Copyright (C) 2018-2020 Jelmer Vernooij
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

"""Convenience functions for efficiently making changes to a working tree.

If possible, uses inotify to track changes in the tree - providing
high performance in large trees with a small number of changes.
"""

import errno
import os
import shutil
from contextlib import ExitStack
from typing import Optional

from .errors import BzrError, DependencyNotPresent
from .osutils import is_inside
from .trace import warning
from .transform import revert
from .transport import NoSuchFile
from .tree import Tree
from .workingtree import WorkingTree


class WorkspaceDirty(BzrError):
    """Raised when a workspace has uncommitted changes."""

    _fmt = "The directory %(path)s has pending changes."

    def __init__(self, tree, subpath):
        """Initialize WorkspaceDirty error.

        Args:
            tree: The working tree.
            subpath: The subpath within the tree that has changes.
        """
        self.tree = tree
        self.subpath = subpath
        BzrError.__init__(self, path=tree.abspath(subpath))


# TODO(jelmer): Move to .clean_tree?
def reset_tree(
    local_tree: WorkingTree,
    basis_tree: Optional[Tree] = None,
    subpath: str = "",
    dirty_tracker=None,
) -> None:
    """Reset a tree back to its basis tree.

    This will leave ignored and detritus files alone.

    Args:
      local_tree: tree to work on
      dirty_tracker: Optional dirty tracker
      subpath: Subpath to operate on
    """
    if dirty_tracker and not dirty_tracker.is_dirty():
        return
    if basis_tree is None:
        basis_tree = local_tree.branch.basis_tree()
    revert(local_tree, basis_tree, [subpath] if subpath else None)
    deletables: list[str] = []
    # TODO(jelmer): Use basis tree
    for p in local_tree.extras():
        if not is_inside(subpath, p):
            continue
        if not local_tree.is_ignored(p):
            deletables.append(local_tree.abspath(p))
    delete_items(deletables)


def delete_items(deletables, dry_run: bool = False):
    """Delete files in the deletables iterable.

    Args:
        deletables: Iterable of file paths to delete.
        dry_run: If True, don't actually delete files.
    """

    def onerror(function, path, excinfo):
        """Show warning for errors seen by rmtree."""
        # Handle only permission error while removing files.
        # Other errors are re-raised.
        if function is not os.remove or excinfo[1].errno != errno.EACCES:
            raise
        warning("unable to remove %s", path)

    for path in deletables:
        if os.path.isdir(path):
            shutil.rmtree(path, onerror=onerror)
        else:
            try:
                os.unlink(path)
            except PermissionError as e:
                warning('unable to remove "%s": %s.', path, e.strerror)


# TODO(jelmer): Move to .clean_tree?
def check_clean_tree(
    local_tree: WorkingTree, basis_tree: Optional[Tree] = None, subpath: str = ""
) -> None:
    """Check that a tree is clean and has no pending changes or unknown files.

    Args:
      local_tree: The tree to check
      basis_tree: Tree to check against
      subpath: Subpath of the tree to check
    Raises:
      PendingChanges: When there are pending changes
    """
    with ExitStack() as es:
        if basis_tree is None:
            es.enter_context(local_tree.lock_read())
            basis_tree = local_tree.basis_tree()
        # Just check there are no changes to begin with
        changes = local_tree.iter_changes(
            basis_tree,
            include_unchanged=False,
            require_versioned=False,
            want_unversioned=True,
            specific_files=[subpath],
        )

        def relevant(p, t):
            if not p:
                return False
            if not is_inside(subpath, p):
                return False
            if t.is_ignored(p):
                return False
            try:
                if not t.has_versioned_directories() and t.kind(p) == "directory":
                    return False
            except NoSuchFile:
                return True
            return True

        if any(
            change
            for change in changes
            if relevant(change.path[0], basis_tree)
            or relevant(change.path[1], local_tree)
        ):
            raise WorkspaceDirty(local_tree, subpath)


def get_dirty_tracker(local_tree, subpath="", use_inotify=None):
    """Create a dirty tracker object."""
    if use_inotify is True:
        from .dirty_tracker import DirtyTracker

        return DirtyTracker(local_tree, subpath)
    elif use_inotify is False:
        return None
    else:
        try:
            from .dirty_tracker import DirtyTracker
        except DependencyNotPresent:
            return None
        else:
            return DirtyTracker(local_tree, subpath)


class Workspace:
    """Create a workspace.

    :param tree: Tree to work in
    :param subpath: path under which to consider and commit changes
    :param use_inotify: whether to use inotify (default: yes, if available)
    """

    def __init__(self, tree, subpath="", use_inotify=None):
        """Initialize a Workspace.

        Args:
            tree: The working tree to operate on.
            subpath: Path under which to consider and commit changes.
            use_inotify: Whether to use inotify (default: yes, if available).
        """
        self.tree = tree
        self.subpath = subpath
        self.use_inotify = use_inotify
        self._dirty_tracker = None
        self._es = ExitStack()

    @classmethod
    def from_path(cls, path, use_inotify=None):
        """Create a Workspace from a filesystem path.

        Args:
            path: Filesystem path to open.
            use_inotify: Whether to use inotify (default: yes, if available).

        Returns:
            New Workspace instance.
        """
        tree, subpath = WorkingTree.open_containing(path)
        return cls(tree, subpath, use_inotify=use_inotify)

    def __enter__(self):
        """Enter the workspace context.

        Returns:
            The Workspace instance.

        Raises:
            WorkspaceDirty: If the tree has uncommitted changes.
        """
        check_clean_tree(self.tree)
        self._es.__enter__()
        self._dirty_tracker = get_dirty_tracker(
            self.tree, subpath=self.subpath, use_inotify=self.use_inotify
        )
        if self._dirty_tracker:
            from .dirty_tracker import TooManyOpenFiles

            try:
                self._es.enter_context(self._dirty_tracker)
            except TooManyOpenFiles:
                warning("Too many files open; not using inotify")
                self._dirty_tracker = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the workspace context.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.

        Returns:
            Result of the exit stack's __exit__ method.
        """
        return self._es.__exit__(exc_type, exc_val, exc_tb)

    def tree_path(self, path=""):
        """Return a path relative to the tree subpath used by this workspace."""
        return os.path.join(self.subpath, path)

    def abspath(self, path=""):
        """Return an absolute path for the tree."""
        return self.tree.abspath(self.tree_path(path))

    def reset(self):
        """Reset - revert local changes, revive deleted files, remove added."""
        if self._dirty_tracker and not self._dirty_tracker.is_dirty():
            return
        reset_tree(self.tree, subpath=self.subpath)
        if self._dirty_tracker is not None:
            self._dirty_tracker.mark_clean()

    def _stage(self) -> Optional[list[str]]:
        changed: Optional[list[str]]
        if self._dirty_tracker:
            relpaths = self._dirty_tracker.relpaths()
            # Sort paths so that directories get added before the files they
            # contain (on VCSes where it matters)
            self.tree.add(
                [
                    p
                    for p in sorted(relpaths)
                    if self.tree.has_filename(p) and not self.tree.is_ignored(p)
                ]
            )
            changed = [p for p in relpaths if self.tree.is_versioned(p)]
        else:
            self.tree.smart_add([self.tree.abspath(self.subpath)])
            changed = [self.subpath] if self.subpath else None

        if self.tree.supports_setting_file_ids():
            from .rename_map import RenameMap

            basis_tree = self.tree.basis_tree()
            RenameMap.guess_renames(basis_tree, self.tree, dry_run=False)
        return changed

    def iter_changes(self):
        """Iterate over changes in the workspace.

        Yields:
            Changes between the basis tree and working tree.
        """
        with self.tree.lock_write():
            specific_files = self._stage()
            basis_tree = self.tree.basis_tree()
            for change in self.tree.iter_changes(
                basis_tree,
                specific_files=specific_files,
                want_unversioned=False,
                require_versioned=True,
            ):
                if change.kind[1] is None and change.versioned[1]:
                    if change.path[0] is None:
                        continue
                    # "missing" path
                    change = change.discard_new()
                yield change

    def commit(self, **kwargs):
        """Create a commit.

        See WorkingTree.commit() for documentation.
        """
        if "specific_files" in kwargs:
            raise NotImplementedError(self.commit)

        with self.tree.lock_write():
            specific_files = self._stage()

            kwargs["specific_files"] = specific_files
            revid = self.tree.commit(**kwargs)
            if self._dirty_tracker:
                self._dirty_tracker.mark_clean()
            return revid

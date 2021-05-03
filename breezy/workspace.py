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

from __future__ import absolute_import

import errno
import os
import shutil


from .clean_tree import iter_deletables
from .errors import BzrError, DependencyNotPresent
from .trace import warning
from .transform import revert
from .workingtree import WorkingTree


class WorkspaceDirty(BzrError):
    _fmt = "The directory %(path)s has pending changes."

    def __init__(self, path):
        BzrError.__init__(self, path=path)


# TODO(jelmer): Move to .clean_tree?
def reset_tree(local_tree, subpath=''):
    """Reset a tree back to its basis tree.

    This will leave ignored and detritus files alone.

    Args:
      local_tree: tree to work on
      subpath: Subpath to operate on
    """
    revert(local_tree, local_tree.branch.basis_tree(),
           [subpath] if subpath else None)
    deletables = list(iter_deletables(
        local_tree, unknown=True, ignored=False, detritus=False))
    delete_items(deletables)


# TODO(jelmer): Move to .clean_tree?
def check_clean_tree(local_tree):
    """Check that a tree is clean and has no pending changes or unknown files.

    Args:
      local_tree: The tree to check
    Raises:
      PendingChanges: When there are pending changes
    """
    # Just check there are no changes to begin with
    if local_tree.has_changes():
        raise WorkspaceDirty(local_tree.abspath('.'))
    if list(local_tree.unknowns()):
        raise WorkspaceDirty(local_tree.abspath('.'))


def delete_items(deletables, dry_run=False):
    """Delete files in the deletables iterable"""
    def onerror(function, path, excinfo):
        """Show warning for errors seen by rmtree.
        """
        # Handle only permission error while removing files.
        # Other errors are re-raised.
        if function is not os.remove or excinfo[1].errno != errno.EACCES:
            raise
        warnings.warn('unable to remove %s' % path)
    for path, subp in deletables:
        if os.path.isdir(path):
            shutil.rmtree(path, onerror=onerror)
        else:
            try:
                os.unlink(path)
            except OSError as e:
                # We handle only permission error here
                if e.errno != errno.EACCES:
                    raise e
                warning('unable to remove "%s": %s.', path, e.strerror)


def get_dirty_tracker(local_tree, subpath='', use_inotify=None):
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


class Workspace(object):
    """Create a workspace.

    :param tree: Tree to work in
    :param subpath: path under which to consider and commit changes
    :param use_inotify: whether to use inotify (default: yes, if available)
    """

    def __init__(self, tree, subpath='', use_inotify=None):
        self.tree = tree
        self.subpath = subpath
        self.use_inotify = use_inotify
        self._dirty_tracker = None

    @classmethod
    def from_path(cls, path, use_inotify=None):
        tree, subpath = WorkingTree.open_containing(path)
        return cls(tree, subpath, use_inotify=use_inotify)

    def __enter__(self):
        check_clean_tree(self.tree)
        self._dirty_tracker = get_dirty_tracker(
            self.tree, subpath=self.subpath, use_inotify=self.use_inotify)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._dirty_tracker:
            del self._dirty_tracker
            self._dirty_tracker = None
        return False

    def tree_path(self, path=''):
        """Return a path relative to the tree subpath used by this workspace.
        """
        return os.path.join(self.subpath, path)

    def abspath(self, path=''):
        """Return an absolute path for the tree."""
        return self.tree.abspath(self.tree_path(path))

    def reset(self):
        """Reset - revert local changes, revive deleted files, remove added.
        """
        if self._dirty_tracker and not self._dirty_tracker.is_dirty():
            return
        reset_tree(self.tree, self.subpath)
        if self._dirty_tracker is not None:
            self._dirty_tracker.mark_clean()

    def _stage(self):
        if self._dirty_tracker:
            relpaths = self._dirty_tracker.relpaths()
            # Sort paths so that directories get added before the files they
            # contain (on VCSes where it matters)
            self.tree.add(
                [p for p in sorted(relpaths)
                 if self.tree.has_filename(p) and not
                    self.tree.is_ignored(p)])
            return [
                p for p in relpaths
                if self.tree.is_versioned(p)]
        else:
            self.tree.smart_add([self.tree.abspath(self.subpath)])
            return [self.subpath] if self.subpath else None

    def iter_changes(self):
        with self.tree.lock_write():
            specific_files = self._stage()
            basis_tree = self.tree.basis_tree()
            # TODO(jelmer): After Python 3.3, use 'yield from'
            for change in self.tree.iter_changes(
                    basis_tree, specific_files=specific_files,
                    want_unversioned=False, require_versioned=True):
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
        if 'specific_files' in kwargs:
            raise NotImplementedError(self.commit)

        with self.tree.lock_write():
            specific_files = self._stage()

            if self.tree.supports_setting_file_ids():
                from .rename_map import RenameMap
                basis_tree = self.tree.basis_tree()
                RenameMap.guess_renames(
                    basis_tree, self.tree, dry_run=False)

            kwargs['specific_files'] = specific_files
            revid = self.tree.commit(**kwargs)
            if self._dirty_tracker:
                self._dirty_tracker.mark_clean()
            return revid

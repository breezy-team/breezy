# Copyright (C) 2006-2011 Canonical Ltd
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

from __future__ import absolute_import

import os
import errno
from stat import S_ISREG, S_IEXEC
import time

from . import (
    config as _mod_config,
    errors,
    lazy_import,
    registry,
    trace,
    tree,
    )
lazy_import.lazy_import(globals(), """
from breezy import (
    annotate,
    bencode,
    controldir,
    commit,
    conflicts,
    delta,
    lock,
    multiparent,
    osutils,
    revision as _mod_revision,
    ui,
    urlutils,
    )
from breezy.bzr import (
    inventory,
    inventorytree,
    )
from breezy.i18n import gettext
""")
from .errors import (DuplicateKey, MalformedTransform,
                     ReusingTransform, CantMoveRoot,
                     ImmortalLimbo, NoFinalPath,
                     UnableCreateSymlink)
from .filters import filtered_output_bytes, ContentFilterContext
from .mutabletree import MutableTree
from .osutils import (
    delete_any,
    file_kind,
    has_symlinks,
    pathjoin,
    sha_file,
    splitpath,
    )
from .progress import ProgressPhase
from .sixish import (
    text_type,
    viewitems,
    viewvalues,
    )
from .tree import (
    find_previous_path,
    )


ROOT_PARENT = "root-parent"


def unique_add(map, key, value):
    if key in map:
        raise DuplicateKey(key=key)
    map[key] = value


class _TransformResults(object):
    def __init__(self, modified_paths, rename_count):
        object.__init__(self)
        self.modified_paths = modified_paths
        self.rename_count = rename_count


class TreeTransformBase(object):
    """The base class for TreeTransform and its kin."""

    def __init__(self, tree, pb=None, case_sensitive=True):
        """Constructor.

        :param tree: The tree that will be transformed, but not necessarily
            the output tree.
        :param pb: ignored
        :param case_sensitive: If True, the target of the transform is
            case sensitive, not just case preserving.
        """
        object.__init__(self)
        self._tree = tree
        self._id_number = 0
        # mapping of trans_id -> new basename
        self._new_name = {}
        # mapping of trans_id -> new parent trans_id
        self._new_parent = {}
        # mapping of trans_id with new contents -> new file_kind
        self._new_contents = {}
        # mapping of trans_id => (sha1 of content, stat_value)
        self._observed_sha1s = {}
        # Set of trans_ids whose contents will be removed
        self._removed_contents = set()
        # Mapping of trans_id -> new execute-bit value
        self._new_executability = {}
        # Mapping of trans_id -> new tree-reference value
        self._new_reference_revision = {}
        # Mapping of trans_id -> new file_id
        self._new_id = {}
        # Mapping of old file-id -> trans_id
        self._non_present_ids = {}
        # Mapping of new file_id -> trans_id
        self._r_new_id = {}
        # Set of trans_ids that will be removed
        self._removed_id = set()
        # Mapping of path in old tree -> trans_id
        self._tree_path_ids = {}
        # Mapping trans_id -> path in old tree
        self._tree_id_paths = {}
        # The trans_id that will be used as the tree root
        if tree.is_versioned(''):
            self._new_root = self.trans_id_tree_path('')
        else:
            self._new_root = None
        # Indicator of whether the transform has been applied
        self._done = False
        # A progress bar
        self._pb = pb
        # Whether the target is case sensitive
        self._case_sensitive_target = case_sensitive
        # A counter of how many files have been renamed
        self.rename_count = 0

    def __enter__(self):
        """Support Context Manager API."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support Context Manager API."""
        self.finalize()

    def finalize(self):
        """Release the working tree lock, if held.

        This is required if apply has not been invoked, but can be invoked
        even after apply.
        """
        if self._tree is None:
            return
        for hook in MutableTree.hooks['post_transform']:
            hook(self._tree, self)
        self._tree.unlock()
        self._tree = None

    def __get_root(self):
        return self._new_root

    root = property(__get_root)

    def _assign_id(self):
        """Produce a new tranform id"""
        new_id = "new-%s" % self._id_number
        self._id_number += 1
        return new_id

    def create_path(self, name, parent):
        """Assign a transaction id to a new path"""
        trans_id = self._assign_id()
        unique_add(self._new_name, trans_id, name)
        unique_add(self._new_parent, trans_id, parent)
        return trans_id

    def adjust_path(self, name, parent, trans_id):
        """Change the path that is assigned to a transaction id."""
        if parent is None:
            raise ValueError("Parent trans-id may not be None")
        if trans_id == self._new_root:
            raise CantMoveRoot
        self._new_name[trans_id] = name
        self._new_parent[trans_id] = parent

    def adjust_root_path(self, name, parent):
        """Emulate moving the root by moving all children, instead.

        We do this by undoing the association of root's transaction id with the
        current tree.  This allows us to create a new directory with that
        transaction id.  We unversion the root directory and version the
        physically new directory, and hope someone versions the tree root
        later.
        """
        old_root = self._new_root
        old_root_file_id = self.final_file_id(old_root)
        # force moving all children of root
        for child_id in self.iter_tree_children(old_root):
            if child_id != parent:
                self.adjust_path(self.final_name(child_id),
                                 self.final_parent(child_id), child_id)
            file_id = self.final_file_id(child_id)
            if file_id is not None:
                self.unversion_file(child_id)
            self.version_file(file_id, child_id)

        # the physical root needs a new transaction id
        self._tree_path_ids.pop("")
        self._tree_id_paths.pop(old_root)
        self._new_root = self.trans_id_tree_path('')
        if parent == old_root:
            parent = self._new_root
        self.adjust_path(name, parent, old_root)
        self.create_directory(old_root)
        self.version_file(old_root_file_id, old_root)
        self.unversion_file(self._new_root)

    def fixup_new_roots(self):
        """Reinterpret requests to change the root directory

        Instead of creating a root directory, or moving an existing directory,
        all the attributes and children of the new root are applied to the
        existing root directory.

        This means that the old root trans-id becomes obsolete, so it is
        recommended only to invoke this after the root trans-id has become
        irrelevant.

        """
        new_roots = [k for k, v in viewitems(self._new_parent)
                     if v == ROOT_PARENT]
        if len(new_roots) < 1:
            return
        if len(new_roots) != 1:
            raise ValueError('A tree cannot have two roots!')
        if self._new_root is None:
            self._new_root = new_roots[0]
            return
        old_new_root = new_roots[0]
        # unversion the new root's directory.
        if self.final_kind(self._new_root) is None:
            file_id = self.final_file_id(old_new_root)
        else:
            file_id = self.final_file_id(self._new_root)
        if old_new_root in self._new_id:
            self.cancel_versioning(old_new_root)
        else:
            self.unversion_file(old_new_root)
        # if, at this stage, root still has an old file_id, zap it so we can
        # stick a new one in.
        if (self.tree_file_id(self._new_root) is not None
                and self._new_root not in self._removed_id):
            self.unversion_file(self._new_root)
        if file_id is not None:
            self.version_file(file_id, self._new_root)

        # Now move children of new root into old root directory.
        # Ensure all children are registered with the transaction, but don't
        # use directly-- some tree children have new parents
        list(self.iter_tree_children(old_new_root))
        # Move all children of new root into old root directory.
        for child in self.by_parent().get(old_new_root, []):
            self.adjust_path(self.final_name(child), self._new_root, child)

        # Ensure old_new_root has no directory.
        if old_new_root in self._new_contents:
            self.cancel_creation(old_new_root)
        else:
            self.delete_contents(old_new_root)

        # prevent deletion of root directory.
        if self._new_root in self._removed_contents:
            self.cancel_deletion(self._new_root)

        # destroy path info for old_new_root.
        del self._new_parent[old_new_root]
        del self._new_name[old_new_root]

    def trans_id_file_id(self, file_id):
        """Determine or set the transaction id associated with a file ID.
        A new id is only created for file_ids that were never present.  If
        a transaction has been unversioned, it is deliberately still returned.
        (this will likely lead to an unversioned parent conflict.)
        """
        if file_id is None:
            raise ValueError('None is not a valid file id')
        if file_id in self._r_new_id and self._r_new_id[file_id] is not None:
            return self._r_new_id[file_id]
        else:
            try:
                path = self._tree.id2path(file_id)
            except errors.NoSuchId:
                if file_id in self._non_present_ids:
                    return self._non_present_ids[file_id]
                else:
                    trans_id = self._assign_id()
                    self._non_present_ids[file_id] = trans_id
                    return trans_id
            else:
                return self.trans_id_tree_path(path)

    def trans_id_tree_path(self, path):
        """Determine (and maybe set) the transaction ID for a tree path."""
        path = self.canonical_path(path)
        if path not in self._tree_path_ids:
            self._tree_path_ids[path] = self._assign_id()
            self._tree_id_paths[self._tree_path_ids[path]] = path
        return self._tree_path_ids[path]

    def get_tree_parent(self, trans_id):
        """Determine id of the parent in the tree."""
        path = self._tree_id_paths[trans_id]
        if path == "":
            return ROOT_PARENT
        return self.trans_id_tree_path(os.path.dirname(path))

    def delete_contents(self, trans_id):
        """Schedule the contents of a path entry for deletion"""
        kind = self.tree_kind(trans_id)
        if kind is not None:
            self._removed_contents.add(trans_id)

    def cancel_deletion(self, trans_id):
        """Cancel a scheduled deletion"""
        self._removed_contents.remove(trans_id)

    def unversion_file(self, trans_id):
        """Schedule a path entry to become unversioned"""
        self._removed_id.add(trans_id)

    def delete_versioned(self, trans_id):
        """Delete and unversion a versioned file"""
        self.delete_contents(trans_id)
        self.unversion_file(trans_id)

    def set_executability(self, executability, trans_id):
        """Schedule setting of the 'execute' bit
        To unschedule, set to None
        """
        if executability is None:
            del self._new_executability[trans_id]
        else:
            unique_add(self._new_executability, trans_id, executability)

    def set_tree_reference(self, revision_id, trans_id):
        """Set the reference associated with a directory"""
        unique_add(self._new_reference_revision, trans_id, revision_id)

    def version_file(self, file_id, trans_id):
        """Schedule a file to become versioned."""
        if file_id is None:
            raise ValueError()
        unique_add(self._new_id, trans_id, file_id)
        unique_add(self._r_new_id, file_id, trans_id)

    def cancel_versioning(self, trans_id):
        """Undo a previous versioning of a file"""
        file_id = self._new_id[trans_id]
        del self._new_id[trans_id]
        del self._r_new_id[file_id]

    def new_paths(self, filesystem_only=False):
        """Determine the paths of all new and changed files.

        :param filesystem_only: if True, only calculate values for files
            that require renames or execute bit changes.
        """
        new_ids = set()
        if filesystem_only:
            stale_ids = self._needs_rename.difference(self._new_name)
            stale_ids.difference_update(self._new_parent)
            stale_ids.difference_update(self._new_contents)
            stale_ids.difference_update(self._new_id)
            needs_rename = self._needs_rename.difference(stale_ids)
            id_sets = (needs_rename, self._new_executability)
        else:
            id_sets = (self._new_name, self._new_parent, self._new_contents,
                       self._new_id, self._new_executability)
        for id_set in id_sets:
            new_ids.update(id_set)
        return sorted(FinalPaths(self).get_paths(new_ids))

    def _inventory_altered(self):
        """Determine which trans_ids need new Inventory entries.

        An new entry is needed when anything that would be reflected by an
        inventory entry changes, including file name, file_id, parent file_id,
        file kind, and the execute bit.

        Some care is taken to return entries with real changes, not cases
        where the value is deleted and then restored to its original value,
        but some actually unchanged values may be returned.

        :returns: A list of (path, trans_id) for all items requiring an
            inventory change. Ordered by path.
        """
        changed_ids = set()
        # Find entries whose file_ids are new (or changed).
        new_file_id = set(t for t in self._new_id
                          if self._new_id[t] != self.tree_file_id(t))
        for id_set in [self._new_name, self._new_parent, new_file_id,
                       self._new_executability]:
            changed_ids.update(id_set)
        # removing implies a kind change
        changed_kind = set(self._removed_contents)
        # so does adding
        changed_kind.intersection_update(self._new_contents)
        # Ignore entries that are already known to have changed.
        changed_kind.difference_update(changed_ids)
        #  to keep only the truly changed ones
        changed_kind = (t for t in changed_kind
                        if self.tree_kind(t) != self.final_kind(t))
        # all kind changes will alter the inventory
        changed_ids.update(changed_kind)
        # To find entries with changed parent_ids, find parents which existed,
        # but changed file_id.
        # Now add all their children to the set.
        for parent_trans_id in new_file_id:
            changed_ids.update(self.iter_tree_children(parent_trans_id))
        return sorted(FinalPaths(self).get_paths(changed_ids))

    def final_kind(self, trans_id):
        """Determine the final file kind, after any changes applied.

        :return: None if the file does not exist/has no contents.  (It is
            conceivable that a path would be created without the corresponding
            contents insertion command)
        """
        if trans_id in self._new_contents:
            return self._new_contents[trans_id]
        elif trans_id in self._removed_contents:
            return None
        else:
            return self.tree_kind(trans_id)

    def tree_path(self, trans_id):
        """Determine the tree path associated with the trans_id."""
        return self._tree_id_paths.get(trans_id)

    def tree_file_id(self, trans_id):
        """Determine the file id associated with the trans_id in the tree"""
        path = self.tree_path(trans_id)
        if path is None:
            return None
        # the file is old; the old id is still valid
        if self._new_root == trans_id:
            return self._tree.get_root_id()
        return self._tree.path2id(path)

    def final_file_id(self, trans_id):
        """Determine the file id after any changes are applied, or None.

        None indicates that the file will not be versioned after changes are
        applied.
        """
        try:
            return self._new_id[trans_id]
        except KeyError:
            if trans_id in self._removed_id:
                return None
        return self.tree_file_id(trans_id)

    def inactive_file_id(self, trans_id):
        """Return the inactive file_id associated with a transaction id.
        That is, the one in the tree or in non_present_ids.
        The file_id may actually be active, too.
        """
        file_id = self.tree_file_id(trans_id)
        if file_id is not None:
            return file_id
        for key, value in viewitems(self._non_present_ids):
            if value == trans_id:
                return key

    def final_parent(self, trans_id):
        """Determine the parent file_id, after any changes are applied.

        ROOT_PARENT is returned for the tree root.
        """
        try:
            return self._new_parent[trans_id]
        except KeyError:
            return self.get_tree_parent(trans_id)

    def final_name(self, trans_id):
        """Determine the final filename, after all changes are applied."""
        try:
            return self._new_name[trans_id]
        except KeyError:
            try:
                return os.path.basename(self._tree_id_paths[trans_id])
            except KeyError:
                raise NoFinalPath(trans_id, self)

    def by_parent(self):
        """Return a map of parent: children for known parents.

        Only new paths and parents of tree files with assigned ids are used.
        """
        by_parent = {}
        items = list(viewitems(self._new_parent))
        items.extend((t, self.final_parent(t))
                     for t in list(self._tree_id_paths))
        for trans_id, parent_id in items:
            if parent_id not in by_parent:
                by_parent[parent_id] = set()
            by_parent[parent_id].add(trans_id)
        return by_parent

    def path_changed(self, trans_id):
        """Return True if a trans_id's path has changed."""
        return (trans_id in self._new_name) or (trans_id in self._new_parent)

    def new_contents(self, trans_id):
        return (trans_id in self._new_contents)

    def find_conflicts(self):
        """Find any violations of inventory or filesystem invariants"""
        if self._done is True:
            raise ReusingTransform()
        conflicts = []
        # ensure all children of all existent parents are known
        # all children of non-existent parents are known, by definition.
        self._add_tree_children()
        by_parent = self.by_parent()
        conflicts.extend(self._unversioned_parents(by_parent))
        conflicts.extend(self._parent_loops())
        conflicts.extend(self._duplicate_entries(by_parent))
        conflicts.extend(self._duplicate_ids())
        conflicts.extend(self._parent_type_conflicts(by_parent))
        conflicts.extend(self._improper_versioning())
        conflicts.extend(self._executability_conflicts())
        conflicts.extend(self._overwrite_conflicts())
        return conflicts

    def _check_malformed(self):
        conflicts = self.find_conflicts()
        if len(conflicts) != 0:
            raise MalformedTransform(conflicts=conflicts)

    def _add_tree_children(self):
        """Add all the children of all active parents to the known paths.

        Active parents are those which gain children, and those which are
        removed.  This is a necessary first step in detecting conflicts.
        """
        parents = list(self.by_parent())
        parents.extend([t for t in self._removed_contents if
                        self.tree_kind(t) == 'directory'])
        for trans_id in self._removed_id:
            path = self.tree_path(trans_id)
            if path is not None:
                if self._tree.stored_kind(path) == 'directory':
                    parents.append(trans_id)
            elif self.tree_kind(trans_id) == 'directory':
                parents.append(trans_id)

        for parent_id in parents:
            # ensure that all children are registered with the transaction
            list(self.iter_tree_children(parent_id))

    def _has_named_child(self, name, parent_id, known_children):
        """Does a parent already have a name child.

        :param name: The searched for name.

        :param parent_id: The parent for which the check is made.

        :param known_children: The already known children. This should have
            been recently obtained from `self.by_parent.get(parent_id)`
            (or will be if None is passed).
        """
        if known_children is None:
            known_children = self.by_parent().get(parent_id, [])
        for child in known_children:
            if self.final_name(child) == name:
                return True
        parent_path = self._tree_id_paths.get(parent_id, None)
        if parent_path is None:
            # No parent... no children
            return False
        child_path = joinpath(parent_path, name)
        child_id = self._tree_path_ids.get(child_path, None)
        if child_id is None:
            # Not known by the tree transform yet, check the filesystem
            return osutils.lexists(self._tree.abspath(child_path))
        else:
            raise AssertionError('child_id is missing: %s, %s, %s'
                                 % (name, parent_id, child_id))

    def _available_backup_name(self, name, target_id):
        """Find an available backup name.

        :param name: The basename of the file.

        :param target_id: The directory trans_id where the backup should
            be placed.
        """
        known_children = self.by_parent().get(target_id, [])
        return osutils.available_backup_name(
            name,
            lambda base: self._has_named_child(
                base, target_id, known_children))

    def _parent_loops(self):
        """No entry should be its own ancestor"""
        conflicts = []
        for trans_id in self._new_parent:
            seen = set()
            parent_id = trans_id
            while parent_id != ROOT_PARENT:
                seen.add(parent_id)
                try:
                    parent_id = self.final_parent(parent_id)
                except KeyError:
                    break
                if parent_id == trans_id:
                    conflicts.append(('parent loop', trans_id))
                if parent_id in seen:
                    break
        return conflicts

    def _unversioned_parents(self, by_parent):
        """If parent directories are versioned, children must be versioned."""
        conflicts = []
        for parent_id, children in viewitems(by_parent):
            if parent_id == ROOT_PARENT:
                continue
            if self.final_file_id(parent_id) is not None:
                continue
            for child_id in children:
                if self.final_file_id(child_id) is not None:
                    conflicts.append(('unversioned parent', parent_id))
                    break
        return conflicts

    def _improper_versioning(self):
        """Cannot version a file with no contents, or a bad type.

        However, existing entries with no contents are okay.
        """
        conflicts = []
        for trans_id in self._new_id:
            kind = self.final_kind(trans_id)
            if kind is None:
                conflicts.append(('versioning no contents', trans_id))
                continue
            if not self._tree.versionable_kind(kind):
                conflicts.append(('versioning bad kind', trans_id, kind))
        return conflicts

    def _executability_conflicts(self):
        """Check for bad executability changes.

        Only versioned files may have their executability set, because
        1. only versioned entries can have executability under windows
        2. only files can be executable.  (The execute bit on a directory
           does not indicate searchability)
        """
        conflicts = []
        for trans_id in self._new_executability:
            if self.final_file_id(trans_id) is None:
                conflicts.append(('unversioned executability', trans_id))
            else:
                if self.final_kind(trans_id) != "file":
                    conflicts.append(('non-file executability', trans_id))
        return conflicts

    def _overwrite_conflicts(self):
        """Check for overwrites (not permitted on Win32)"""
        conflicts = []
        for trans_id in self._new_contents:
            if self.tree_kind(trans_id) is None:
                continue
            if trans_id not in self._removed_contents:
                conflicts.append(('overwrite', trans_id,
                                  self.final_name(trans_id)))
        return conflicts

    def _duplicate_entries(self, by_parent):
        """No directory may have two entries with the same name."""
        conflicts = []
        if (self._new_name, self._new_parent) == ({}, {}):
            return conflicts
        for children in viewvalues(by_parent):
            name_ids = []
            for child_tid in children:
                name = self.final_name(child_tid)
                if name is not None:
                    # Keep children only if they still exist in the end
                    if not self._case_sensitive_target:
                        name = name.lower()
                    name_ids.append((name, child_tid))
            name_ids.sort()
            last_name = None
            last_trans_id = None
            for name, trans_id in name_ids:
                kind = self.final_kind(trans_id)
                file_id = self.final_file_id(trans_id)
                if kind is None and file_id is None:
                    continue
                if name == last_name:
                    conflicts.append(('duplicate', last_trans_id, trans_id,
                                      name))
                last_name = name
                last_trans_id = trans_id
        return conflicts

    def _duplicate_ids(self):
        """Each inventory id may only be used once"""
        conflicts = []
        try:
            all_ids = self._tree.all_file_ids()
        except errors.UnsupportedOperation:
            # it's okay for non-file-id trees to raise UnsupportedOperation.
            return []
        removed_tree_ids = set((self.tree_file_id(trans_id) for trans_id in
                                self._removed_id))
        active_tree_ids = all_ids.difference(removed_tree_ids)
        for trans_id, file_id in viewitems(self._new_id):
            if file_id in active_tree_ids:
                path = self._tree.id2path(file_id)
                old_trans_id = self.trans_id_tree_path(path)
                conflicts.append(('duplicate id', old_trans_id, trans_id))
        return conflicts

    def _parent_type_conflicts(self, by_parent):
        """Children must have a directory parent"""
        conflicts = []
        for parent_id, children in viewitems(by_parent):
            if parent_id == ROOT_PARENT:
                continue
            no_children = True
            for child_id in children:
                if self.final_kind(child_id) is not None:
                    no_children = False
                    break
            if no_children:
                continue
            # There is at least a child, so we need an existing directory to
            # contain it.
            kind = self.final_kind(parent_id)
            if kind is None:
                # The directory will be deleted
                conflicts.append(('missing parent', parent_id))
            elif kind != "directory":
                # Meh, we need a *directory* to put something in it
                conflicts.append(('non-directory parent', parent_id))
        return conflicts

    def _set_executability(self, path, trans_id):
        """Set the executability of versioned files """
        if self._tree._supports_executable():
            new_executability = self._new_executability[trans_id]
            abspath = self._tree.abspath(path)
            current_mode = os.stat(abspath).st_mode
            if new_executability:
                umask = os.umask(0)
                os.umask(umask)
                to_mode = current_mode | (0o100 & ~umask)
                # Enable x-bit for others only if they can read it.
                if current_mode & 0o004:
                    to_mode |= 0o001 & ~umask
                if current_mode & 0o040:
                    to_mode |= 0o010 & ~umask
            else:
                to_mode = current_mode & ~0o111
            osutils.chmod_if_possible(abspath, to_mode)

    def _new_entry(self, name, parent_id, file_id):
        """Helper function to create a new filesystem entry."""
        trans_id = self.create_path(name, parent_id)
        if file_id is not None:
            self.version_file(file_id, trans_id)
        return trans_id

    def new_file(self, name, parent_id, contents, file_id=None,
                 executable=None, sha1=None):
        """Convenience method to create files.

        name is the name of the file to create.
        parent_id is the transaction id of the parent directory of the file.
        contents is an iterator of bytestrings, which will be used to produce
        the file.
        :param file_id: The inventory ID of the file, if it is to be versioned.
        :param executable: Only valid when a file_id has been supplied.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        # TODO: rather than scheduling a set_executable call,
        # have create_file create the file with the right mode.
        self.create_file(contents, trans_id, sha1=sha1)
        if executable is not None:
            self.set_executability(executable, trans_id)
        return trans_id

    def new_directory(self, name, parent_id, file_id=None):
        """Convenience method to create directories.

        name is the name of the directory to create.
        parent_id is the transaction id of the parent directory of the
        directory.
        file_id is the inventory ID of the directory, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_directory(trans_id)
        return trans_id

    def new_symlink(self, name, parent_id, target, file_id=None):
        """Convenience method to create symbolic link.

        name is the name of the symlink to create.
        parent_id is the transaction id of the parent directory of the symlink.
        target is a bytestring of the target of the symlink.
        file_id is the inventory ID of the file, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_symlink(target, trans_id)
        return trans_id

    def new_orphan(self, trans_id, parent_id):
        """Schedule an item to be orphaned.

        When a directory is about to be removed, its children, if they are not
        versioned are moved out of the way: they don't have a parent anymore.

        :param trans_id: The trans_id of the existing item.
        :param parent_id: The parent trans_id of the item.
        """
        raise NotImplementedError(self.new_orphan)

    def _get_potential_orphans(self, dir_id):
        """Find the potential orphans in a directory.

        A directory can't be safely deleted if there are versioned files in it.
        If all the contained files are unversioned then they can be orphaned.

        The 'None' return value means that the directory contains at least one
        versioned file and should not be deleted.

        :param dir_id: The directory trans id.

        :return: A list of the orphan trans ids or None if at least one
             versioned file is present.
        """
        orphans = []
        # Find the potential orphans, stop if one item should be kept
        for child_tid in self.by_parent()[dir_id]:
            if child_tid in self._removed_contents:
                # The child is removed as part of the transform. Since it was
                # versioned before, it's not an orphan
                continue
            elif self.final_file_id(child_tid) is None:
                # The child is not versioned
                orphans.append(child_tid)
            else:
                # We have a versioned file here, searching for orphans is
                # meaningless.
                orphans = None
                break
        return orphans

    def _affected_ids(self):
        """Return the set of transform ids affected by the transform"""
        trans_ids = set(self._removed_id)
        trans_ids.update(self._new_id)
        trans_ids.update(self._removed_contents)
        trans_ids.update(self._new_contents)
        trans_ids.update(self._new_executability)
        trans_ids.update(self._new_name)
        trans_ids.update(self._new_parent)
        return trans_ids

    def _get_file_id_maps(self):
        """Return mapping of file_ids to trans_ids in the to and from states"""
        trans_ids = self._affected_ids()
        from_trans_ids = {}
        to_trans_ids = {}
        # Build up two dicts: trans_ids associated with file ids in the
        # FROM state, vs the TO state.
        for trans_id in trans_ids:
            from_file_id = self.tree_file_id(trans_id)
            if from_file_id is not None:
                from_trans_ids[from_file_id] = trans_id
            to_file_id = self.final_file_id(trans_id)
            if to_file_id is not None:
                to_trans_ids[to_file_id] = trans_id
        return from_trans_ids, to_trans_ids

    def _from_file_data(self, from_trans_id, from_versioned, from_path):
        """Get data about a file in the from (tree) state

        Return a (name, parent, kind, executable) tuple
        """
        from_path = self._tree_id_paths.get(from_trans_id)
        if from_versioned:
            # get data from working tree if versioned
            from_entry = next(self._tree.iter_entries_by_dir(
                specific_files=[from_path]))[1]
            from_name = from_entry.name
            from_parent = from_entry.parent_id
        else:
            from_entry = None
            if from_path is None:
                # File does not exist in FROM state
                from_name = None
                from_parent = None
            else:
                # File exists, but is not versioned.  Have to use path-
                # splitting stuff
                from_name = os.path.basename(from_path)
                tree_parent = self.get_tree_parent(from_trans_id)
                from_parent = self.tree_file_id(tree_parent)
        if from_path is not None:
            from_kind, from_executable, from_stats = \
                self._tree._comparison_data(from_entry, from_path)
        else:
            from_kind = None
            from_executable = False
        return from_name, from_parent, from_kind, from_executable

    def _to_file_data(self, to_trans_id, from_trans_id, from_executable):
        """Get data about a file in the to (target) state

        Return a (name, parent, kind, executable) tuple
        """
        to_name = self.final_name(to_trans_id)
        to_kind = self.final_kind(to_trans_id)
        to_parent = self.final_file_id(self.final_parent(to_trans_id))
        if to_trans_id in self._new_executability:
            to_executable = self._new_executability[to_trans_id]
        elif to_trans_id == from_trans_id:
            to_executable = from_executable
        else:
            to_executable = False
        return to_name, to_parent, to_kind, to_executable

    def iter_changes(self):
        """Produce output in the same format as Tree.iter_changes.

        Will produce nonsensical results if invoked while inventory/filesystem
        conflicts (as reported by TreeTransform.find_conflicts()) are present.

        This reads the Transform, but only reproduces changes involving a
        file_id.  Files that are not versioned in either of the FROM or TO
        states are not reflected.
        """
        final_paths = FinalPaths(self)
        from_trans_ids, to_trans_ids = self._get_file_id_maps()
        results = []
        # Now iterate through all active file_ids
        for file_id in set(from_trans_ids).union(to_trans_ids):
            modified = False
            from_trans_id = from_trans_ids.get(file_id)
            # find file ids, and determine versioning state
            if from_trans_id is None:
                from_versioned = False
                from_trans_id = to_trans_ids[file_id]
            else:
                from_versioned = True
            to_trans_id = to_trans_ids.get(file_id)
            if to_trans_id is None:
                to_versioned = False
                to_trans_id = from_trans_id
            else:
                to_versioned = True

            if not from_versioned:
                from_path = None
            else:
                from_path = self._tree_id_paths.get(from_trans_id)
            if not to_versioned:
                to_path = None
            else:
                to_path = final_paths.get_path(to_trans_id)

            from_name, from_parent, from_kind, from_executable = \
                self._from_file_data(from_trans_id, from_versioned, from_path)

            to_name, to_parent, to_kind, to_executable = \
                self._to_file_data(to_trans_id, from_trans_id, from_executable)

            if from_kind != to_kind:
                modified = True
            elif to_kind in ('file', 'symlink') and (
                    to_trans_id != from_trans_id
                    or to_trans_id in self._new_contents):
                modified = True
            if (not modified and from_versioned == to_versioned
                and from_parent == to_parent and from_name == to_name
                    and from_executable == to_executable):
                continue
            results.append((file_id, (from_path, to_path), modified,
                            (from_versioned, to_versioned),
                            (from_parent, to_parent),
                            (from_name, to_name),
                            (from_kind, to_kind),
                            (from_executable, to_executable)))

        def path_key(t):
            paths = t[1]
            return (paths[0] or '', paths[1] or '')
        return iter(sorted(results, key=path_key))

    def get_preview_tree(self):
        """Return a tree representing the result of the transform.

        The tree is a snapshot, and altering the TreeTransform will invalidate
        it.
        """
        return _PreviewTree(self)

    def commit(self, branch, message, merge_parents=None, strict=False,
               timestamp=None, timezone=None, committer=None, authors=None,
               revprops=None, revision_id=None):
        """Commit the result of this TreeTransform to a branch.

        :param branch: The branch to commit to.
        :param message: The message to attach to the commit.
        :param merge_parents: Additional parent revision-ids specified by
            pending merges.
        :param strict: If True, abort the commit if there are unversioned
            files.
        :param timestamp: if not None, seconds-since-epoch for the time and
            date.  (May be a float.)
        :param timezone: Optional timezone for timestamp, as an offset in
            seconds.
        :param committer: Optional committer in email-id format.
            (e.g. "J Random Hacker <jrandom@example.com>")
        :param authors: Optional list of authors in email-id format.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.  (Specifying a revision-id
            may reduce performance for some non-native formats.)
        :return: The revision_id of the revision committed.
        """
        self._check_malformed()
        if strict:
            unversioned = set(self._new_contents).difference(set(self._new_id))
            for trans_id in unversioned:
                if self.final_file_id(trans_id) is None:
                    raise errors.StrictCommitFailed()

        revno, last_rev_id = branch.last_revision_info()
        if last_rev_id == _mod_revision.NULL_REVISION:
            if merge_parents is not None:
                raise ValueError('Cannot supply merge parents for first'
                                 ' commit.')
            parent_ids = []
        else:
            parent_ids = [last_rev_id]
            if merge_parents is not None:
                parent_ids.extend(merge_parents)
        if self._tree.get_revision_id() != last_rev_id:
            raise ValueError('TreeTransform not based on branch basis: %s' %
                             self._tree.get_revision_id().decode('utf-8'))
        revprops = commit.Commit.update_revprops(revprops, branch, authors)
        builder = branch.get_commit_builder(parent_ids,
                                            timestamp=timestamp,
                                            timezone=timezone,
                                            committer=committer,
                                            revprops=revprops,
                                            revision_id=revision_id)
        preview = self.get_preview_tree()
        list(builder.record_iter_changes(preview, last_rev_id,
                                         self.iter_changes()))
        builder.finish_inventory()
        revision_id = builder.commit(message)
        branch.set_last_revision_info(revno + 1, revision_id)
        return revision_id

    def _text_parent(self, trans_id):
        path = self.tree_path(trans_id)
        try:
            if path is None or self._tree.kind(path) != 'file':
                return None
        except errors.NoSuchFile:
            return None
        return path

    def _get_parents_texts(self, trans_id):
        """Get texts for compression parents of this file."""
        path = self._text_parent(trans_id)
        if path is None:
            return ()
        return (self._tree.get_file_text(path),)

    def _get_parents_lines(self, trans_id):
        """Get lines for compression parents of this file."""
        path = self._text_parent(trans_id)
        if path is None:
            return ()
        return (self._tree.get_file_lines(path),)

    def serialize(self, serializer):
        """Serialize this TreeTransform.

        :param serializer: A Serialiser like pack.ContainerSerializer.
        """
        new_name = {k.encode('utf-8'): v.encode('utf-8')
                    for k, v in viewitems(self._new_name)}
        new_parent = {k.encode('utf-8'): v.encode('utf-8')
                      for k, v in viewitems(self._new_parent)}
        new_id = {k.encode('utf-8'): v
                  for k, v in viewitems(self._new_id)}
        new_executability = {k.encode('utf-8'): int(v)
                             for k, v in viewitems(self._new_executability)}
        tree_path_ids = {k.encode('utf-8'): v.encode('utf-8')
                         for k, v in viewitems(self._tree_path_ids)}
        non_present_ids = {k: v.encode('utf-8')
                           for k, v in viewitems(self._non_present_ids)}
        removed_contents = [trans_id.encode('utf-8')
                            for trans_id in self._removed_contents]
        removed_id = [trans_id.encode('utf-8')
                      for trans_id in self._removed_id]
        attribs = {
            b'_id_number': self._id_number,
            b'_new_name': new_name,
            b'_new_parent': new_parent,
            b'_new_executability': new_executability,
            b'_new_id': new_id,
            b'_tree_path_ids': tree_path_ids,
            b'_removed_id': removed_id,
            b'_removed_contents': removed_contents,
            b'_non_present_ids': non_present_ids,
            }
        yield serializer.bytes_record(bencode.bencode(attribs),
                                      ((b'attribs',),))
        for trans_id, kind in sorted(viewitems(self._new_contents)):
            if kind == 'file':
                with open(self._limbo_name(trans_id), 'rb') as cur_file:
                    lines = cur_file.readlines()
                parents = self._get_parents_lines(trans_id)
                mpdiff = multiparent.MultiParent.from_lines(lines, parents)
                content = b''.join(mpdiff.to_patch())
            if kind == 'directory':
                content = b''
            if kind == 'symlink':
                content = self._read_symlink_target(trans_id)
                if not isinstance(content, bytes):
                    content = content.encode('utf-8')
            yield serializer.bytes_record(
                content, ((trans_id.encode('utf-8'), kind.encode('ascii')),))

    def deserialize(self, records):
        """Deserialize a stored TreeTransform.

        :param records: An iterable of (names, content) tuples, as per
            pack.ContainerPushParser.
        """
        names, content = next(records)
        attribs = bencode.bdecode(content)
        self._id_number = attribs[b'_id_number']
        self._new_name = {k.decode('utf-8'): v.decode('utf-8')
                          for k, v in viewitems(attribs[b'_new_name'])}
        self._new_parent = {k.decode('utf-8'): v.decode('utf-8')
                            for k, v in viewitems(attribs[b'_new_parent'])}
        self._new_executability = {
            k.decode('utf-8'): bool(v)
            for k, v in viewitems(attribs[b'_new_executability'])}
        self._new_id = {k.decode('utf-8'): v
                        for k, v in viewitems(attribs[b'_new_id'])}
        self._r_new_id = {v: k for k, v in viewitems(self._new_id)}
        self._tree_path_ids = {}
        self._tree_id_paths = {}
        for bytepath, trans_id in viewitems(attribs[b'_tree_path_ids']):
            path = bytepath.decode('utf-8')
            trans_id = trans_id.decode('utf-8')
            self._tree_path_ids[path] = trans_id
            self._tree_id_paths[trans_id] = path
        self._removed_id = {trans_id.decode('utf-8')
                            for trans_id in attribs[b'_removed_id']}
        self._removed_contents = set(
            trans_id.decode('utf-8')
            for trans_id in attribs[b'_removed_contents'])
        self._non_present_ids = {
            k: v.decode('utf-8')
            for k, v in viewitems(attribs[b'_non_present_ids'])}
        for ((trans_id, kind),), content in records:
            trans_id = trans_id.decode('utf-8')
            kind = kind.decode('ascii')
            if kind == 'file':
                mpdiff = multiparent.MultiParent.from_patch(content)
                lines = mpdiff.to_lines(self._get_parents_texts(trans_id))
                self.create_file(lines, trans_id)
            if kind == 'directory':
                self.create_directory(trans_id)
            if kind == 'symlink':
                self.create_symlink(content.decode('utf-8'), trans_id)


class DiskTreeTransform(TreeTransformBase):
    """Tree transform storing its contents on disk."""

    def __init__(self, tree, limbodir, pb=None,
                 case_sensitive=True):
        """Constructor.
        :param tree: The tree that will be transformed, but not necessarily
            the output tree.
        :param limbodir: A directory where new files can be stored until
            they are installed in their proper places
        :param pb: ignored
        :param case_sensitive: If True, the target of the transform is
            case sensitive, not just case preserving.
        """
        TreeTransformBase.__init__(self, tree, pb, case_sensitive)
        self._limbodir = limbodir
        self._deletiondir = None
        # A mapping of transform ids to their limbo filename
        self._limbo_files = {}
        self._possibly_stale_limbo_files = set()
        # A mapping of transform ids to a set of the transform ids of children
        # that their limbo directory has
        self._limbo_children = {}
        # Map transform ids to maps of child filename to child transform id
        self._limbo_children_names = {}
        # List of transform ids that need to be renamed from limbo into place
        self._needs_rename = set()
        self._creation_mtime = None

    def finalize(self):
        """Release the working tree lock, if held, clean up limbo dir.

        This is required if apply has not been invoked, but can be invoked
        even after apply.
        """
        if self._tree is None:
            return
        try:
            limbo_paths = list(viewvalues(self._limbo_files))
            limbo_paths.extend(self._possibly_stale_limbo_files)
            limbo_paths.sort(reverse=True)
            for path in limbo_paths:
                try:
                    delete_any(path)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise
                    # XXX: warn? perhaps we just got interrupted at an
                    # inconvenient moment, but perhaps files are disappearing
                    # from under us?
            try:
                delete_any(self._limbodir)
            except OSError:
                # We don't especially care *why* the dir is immortal.
                raise ImmortalLimbo(self._limbodir)
            try:
                if self._deletiondir is not None:
                    delete_any(self._deletiondir)
            except OSError:
                raise errors.ImmortalPendingDeletion(self._deletiondir)
        finally:
            TreeTransformBase.finalize(self)

    def _limbo_supports_executable(self):
        """Check if the limbo path supports the executable bit."""
        # FIXME: Check actual file system capabilities of limbodir
        return osutils.supports_executable()

    def _limbo_name(self, trans_id):
        """Generate the limbo name of a file"""
        limbo_name = self._limbo_files.get(trans_id)
        if limbo_name is None:
            limbo_name = self._generate_limbo_path(trans_id)
            self._limbo_files[trans_id] = limbo_name
        return limbo_name

    def _generate_limbo_path(self, trans_id):
        """Generate a limbo path using the trans_id as the relative path.

        This is suitable as a fallback, and when the transform should not be
        sensitive to the path encoding of the limbo directory.
        """
        self._needs_rename.add(trans_id)
        return pathjoin(self._limbodir, trans_id)

    def adjust_path(self, name, parent, trans_id):
        previous_parent = self._new_parent.get(trans_id)
        previous_name = self._new_name.get(trans_id)
        TreeTransformBase.adjust_path(self, name, parent, trans_id)
        if (trans_id in self._limbo_files
                and trans_id not in self._needs_rename):
            self._rename_in_limbo([trans_id])
            if previous_parent != parent:
                self._limbo_children[previous_parent].remove(trans_id)
            if previous_parent != parent or previous_name != name:
                del self._limbo_children_names[previous_parent][previous_name]

    def _rename_in_limbo(self, trans_ids):
        """Fix limbo names so that the right final path is produced.

        This means we outsmarted ourselves-- we tried to avoid renaming
        these files later by creating them with their final names in their
        final parents.  But now the previous name or parent is no longer
        suitable, so we have to rename them.

        Even for trans_ids that have no new contents, we must remove their
        entries from _limbo_files, because they are now stale.
        """
        for trans_id in trans_ids:
            old_path = self._limbo_files[trans_id]
            self._possibly_stale_limbo_files.add(old_path)
            del self._limbo_files[trans_id]
            if trans_id not in self._new_contents:
                continue
            new_path = self._limbo_name(trans_id)
            os.rename(old_path, new_path)
            self._possibly_stale_limbo_files.remove(old_path)
            for descendant in self._limbo_descendants(trans_id):
                desc_path = self._limbo_files[descendant]
                desc_path = new_path + desc_path[len(old_path):]
                self._limbo_files[descendant] = desc_path

    def _limbo_descendants(self, trans_id):
        """Return the set of trans_ids whose limbo paths descend from this."""
        descendants = set(self._limbo_children.get(trans_id, []))
        for descendant in list(descendants):
            descendants.update(self._limbo_descendants(descendant))
        return descendants

    def create_file(self, contents, trans_id, mode_id=None, sha1=None):
        """Schedule creation of a new file.

        :seealso: new_file.

        :param contents: an iterator of strings, all of which will be written
            to the target destination.
        :param trans_id: TreeTransform handle
        :param mode_id: If not None, force the mode of the target file to match
            the mode of the object referenced by mode_id.
            Otherwise, we will try to preserve mode bits of an existing file.
        :param sha1: If the sha1 of this content is already known, pass it in.
            We can use it to prevent future sha1 computations.
        """
        name = self._limbo_name(trans_id)
        with open(name, 'wb') as f:
            unique_add(self._new_contents, trans_id, 'file')
            f.writelines(contents)
        self._set_mtime(name)
        self._set_mode(trans_id, mode_id, S_ISREG)
        # It is unfortunate we have to use lstat instead of fstat, but we just
        # used utime and chmod on the file, so we need the accurate final
        # details.
        if sha1 is not None:
            self._observed_sha1s[trans_id] = (sha1, osutils.lstat(name))

    def _read_symlink_target(self, trans_id):
        return os.readlink(self._limbo_name(trans_id))

    def _set_mtime(self, path):
        """All files that are created get the same mtime.

        This time is set by the first object to be created.
        """
        if self._creation_mtime is None:
            self._creation_mtime = time.time()
        os.utime(path, (self._creation_mtime, self._creation_mtime))

    def create_hardlink(self, path, trans_id):
        """Schedule creation of a hard link"""
        name = self._limbo_name(trans_id)
        try:
            os.link(path, name)
        except OSError as e:
            if e.errno != errno.EPERM:
                raise
            raise errors.HardLinkNotSupported(path)
        try:
            unique_add(self._new_contents, trans_id, 'file')
        except BaseException:
            # Clean up the file, it never got registered so
            # TreeTransform.finalize() won't clean it up.
            os.unlink(name)
            raise

    def create_directory(self, trans_id):
        """Schedule creation of a new directory.

        See also new_directory.
        """
        os.mkdir(self._limbo_name(trans_id))
        unique_add(self._new_contents, trans_id, 'directory')

    def create_symlink(self, target, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        if has_symlinks():
            os.symlink(target, self._limbo_name(trans_id))
            unique_add(self._new_contents, trans_id, 'symlink')
        else:
            try:
                path = FinalPaths(self).get_path(trans_id)
            except KeyError:
                path = None
            raise UnableCreateSymlink(path=path)

    def cancel_creation(self, trans_id):
        """Cancel the creation of new file contents."""
        del self._new_contents[trans_id]
        if trans_id in self._observed_sha1s:
            del self._observed_sha1s[trans_id]
        children = self._limbo_children.get(trans_id)
        # if this is a limbo directory with children, move them before removing
        # the directory
        if children is not None:
            self._rename_in_limbo(children)
            del self._limbo_children[trans_id]
            del self._limbo_children_names[trans_id]
        delete_any(self._limbo_name(trans_id))

    def new_orphan(self, trans_id, parent_id):
        conf = self._tree.get_config_stack()
        handle_orphan = conf.get('transform.orphan_policy')
        handle_orphan(self, trans_id, parent_id)


class OrphaningError(errors.BzrError):

    # Only bugs could lead to such exception being seen by the user
    internal_error = True
    _fmt = "Error while orphaning %s in %s directory"

    def __init__(self, orphan, parent):
        errors.BzrError.__init__(self)
        self.orphan = orphan
        self.parent = parent


class OrphaningForbidden(OrphaningError):

    _fmt = "Policy: %s doesn't allow creating orphans."

    def __init__(self, policy):
        errors.BzrError.__init__(self)
        self.policy = policy


def move_orphan(tt, orphan_id, parent_id):
    """See TreeTransformBase.new_orphan.

    This creates a new orphan in the `brz-orphans` dir at the root of the
    `TreeTransform`.

    :param tt: The TreeTransform orphaning `trans_id`.

    :param orphan_id: The trans id that should be orphaned.

    :param parent_id: The orphan parent trans id.
    """
    # Add the orphan dir if it doesn't exist
    orphan_dir_basename = 'brz-orphans'
    od_id = tt.trans_id_tree_path(orphan_dir_basename)
    if tt.final_kind(od_id) is None:
        tt.create_directory(od_id)
    parent_path = tt._tree_id_paths[parent_id]
    # Find a name that doesn't exist yet in the orphan dir
    actual_name = tt.final_name(orphan_id)
    new_name = tt._available_backup_name(actual_name, od_id)
    tt.adjust_path(new_name, od_id, orphan_id)
    trace.warning('%s has been orphaned in %s'
                  % (joinpath(parent_path, actual_name), orphan_dir_basename))


def refuse_orphan(tt, orphan_id, parent_id):
    """See TreeTransformBase.new_orphan.

    This refuses to create orphan, letting the caller handle the conflict.
    """
    raise OrphaningForbidden('never')


orphaning_registry = registry.Registry()
orphaning_registry.register(
    u'conflict', refuse_orphan,
    'Leave orphans in place and create a conflict on the directory.')
orphaning_registry.register(
    u'move', move_orphan,
    'Move orphans into the brz-orphans directory.')
orphaning_registry._set_default_key(u'conflict')


opt_transform_orphan = _mod_config.RegistryOption(
    'transform.orphan_policy', orphaning_registry,
    help='Policy for orphaned files during transform operations.',
    invalid='warning')


class TreeTransform(DiskTreeTransform):
    """Represent a tree transformation.

    This object is designed to support incremental generation of the transform,
    in any order.

    However, it gives optimum performance when parent directories are created
    before their contents.  The transform is then able to put child files
    directly in their parent directory, avoiding later renames.

    It is easy to produce malformed transforms, but they are generally
    harmless.  Attempting to apply a malformed transform will cause an
    exception to be raised before any modifications are made to the tree.

    Many kinds of malformed transforms can be corrected with the
    resolve_conflicts function.  The remaining ones indicate programming error,
    such as trying to create a file with no path.

    Two sets of file creation methods are supplied.  Convenience methods are:
     * new_file
     * new_directory
     * new_symlink

    These are composed of the low-level methods:
     * create_path
     * create_file or create_directory or create_symlink
     * version_file
     * set_executability

    Transform/Transaction ids
    -------------------------
    trans_ids are temporary ids assigned to all files involved in a transform.
    It's possible, even common, that not all files in the Tree have trans_ids.

    trans_ids are used because filenames and file_ids are not good enough
    identifiers; filenames change, and not all files have file_ids.  File-ids
    are also associated with trans-ids, so that moving a file moves its
    file-id.

    trans_ids are only valid for the TreeTransform that generated them.

    Limbo
    -----
    Limbo is a temporary directory use to hold new versions of files.
    Files are added to limbo by create_file, create_directory, create_symlink,
    and their convenience variants (new_*).  Files may be removed from limbo
    using cancel_creation.  Files are renamed from limbo into their final
    location as part of TreeTransform.apply

    Limbo must be cleaned up, by either calling TreeTransform.apply or
    calling TreeTransform.finalize.

    Files are placed into limbo inside their parent directories, where
    possible.  This reduces subsequent renames, and makes operations involving
    lots of files faster.  This optimization is only possible if the parent
    directory is created *before* creating any of its children, so avoid
    creating children before parents, where possible.

    Pending-deletion
    ----------------
    This temporary directory is used by _FileMover for storing files that are
    about to be deleted.  In case of rollback, the files will be restored.
    FileMover does not delete files until it is sure that a rollback will not
    happen.
    """

    def __init__(self, tree, pb=None):
        """Note: a tree_write lock is taken on the tree.

        Use TreeTransform.finalize() to release the lock (can be omitted if
        TreeTransform.apply() called).
        """
        tree.lock_tree_write()
        try:
            limbodir = urlutils.local_path_from_url(
                tree._transport.abspath('limbo'))
            osutils.ensure_empty_directory_exists(
                limbodir,
                errors.ExistingLimbo)
            deletiondir = urlutils.local_path_from_url(
                tree._transport.abspath('pending-deletion'))
            osutils.ensure_empty_directory_exists(
                deletiondir,
                errors.ExistingPendingDeletion)
        except BaseException:
            tree.unlock()
            raise

        # Cache of realpath results, to speed up canonical_path
        self._realpaths = {}
        # Cache of relpath results, to speed up canonical_path
        self._relpaths = {}
        DiskTreeTransform.__init__(self, tree, limbodir, pb,
                                   tree.case_sensitive)
        self._deletiondir = deletiondir

    def canonical_path(self, path):
        """Get the canonical tree-relative path"""
        # don't follow final symlinks
        abs = self._tree.abspath(path)
        if abs in self._relpaths:
            return self._relpaths[abs]
        dirname, basename = os.path.split(abs)
        if dirname not in self._realpaths:
            self._realpaths[dirname] = os.path.realpath(dirname)
        dirname = self._realpaths[dirname]
        abs = pathjoin(dirname, basename)
        if dirname in self._relpaths:
            relpath = pathjoin(self._relpaths[dirname], basename)
            relpath = relpath.rstrip('/\\')
        else:
            relpath = self._tree.relpath(abs)
        self._relpaths[abs] = relpath
        return relpath

    def tree_kind(self, trans_id):
        """Determine the file kind in the working tree.

        :returns: The file kind or None if the file does not exist
        """
        path = self._tree_id_paths.get(trans_id)
        if path is None:
            return None
        try:
            return file_kind(self._tree.abspath(path))
        except errors.NoSuchFile:
            return None

    def _set_mode(self, trans_id, mode_id, typefunc):
        """Set the mode of new file contents.
        The mode_id is the existing file to get the mode from (often the same
        as trans_id).  The operation is only performed if there's a mode match
        according to typefunc.
        """
        if mode_id is None:
            mode_id = trans_id
        try:
            old_path = self._tree_id_paths[mode_id]
        except KeyError:
            return
        try:
            mode = os.stat(self._tree.abspath(old_path)).st_mode
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                # Either old_path doesn't exist, or the parent of the
                # target is not a directory (but will be one eventually)
                # Either way, we know it doesn't exist *right now*
                # See also bug #248448
                return
            else:
                raise
        if typefunc(mode):
            osutils.chmod_if_possible(self._limbo_name(trans_id), mode)

    def iter_tree_children(self, parent_id):
        """Iterate through the entry's tree children, if any"""
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return
        try:
            children = os.listdir(self._tree.abspath(path))
        except OSError as e:
            if not (osutils._is_error_enotdir(e) or
                    e.errno in (errno.ENOENT, errno.ESRCH)):
                raise
            return

        for child in children:
            childpath = joinpath(path, child)
            if self._tree.is_control_filename(childpath):
                continue
            yield self.trans_id_tree_path(childpath)

    def _generate_limbo_path(self, trans_id):
        """Generate a limbo path using the final path if possible.

        This optimizes the performance of applying the tree transform by
        avoiding renames.  These renames can be avoided only when the parent
        directory is already scheduled for creation.

        If the final path cannot be used, falls back to using the trans_id as
        the relpath.
        """
        parent = self._new_parent.get(trans_id)
        # if the parent directory is already in limbo (e.g. when building a
        # tree), choose a limbo name inside the parent, to reduce further
        # renames.
        use_direct_path = False
        if self._new_contents.get(parent) == 'directory':
            filename = self._new_name.get(trans_id)
            if filename is not None:
                if parent not in self._limbo_children:
                    self._limbo_children[parent] = set()
                    self._limbo_children_names[parent] = {}
                    use_direct_path = True
                # the direct path can only be used if no other file has
                # already taken this pathname, i.e. if the name is unused, or
                # if it is already associated with this trans_id.
                elif self._case_sensitive_target:
                    if (self._limbo_children_names[parent].get(filename)
                            in (trans_id, None)):
                        use_direct_path = True
                else:
                    for l_filename, l_trans_id in viewitems(
                            self._limbo_children_names[parent]):
                        if l_trans_id == trans_id:
                            continue
                        if l_filename.lower() == filename.lower():
                            break
                    else:
                        use_direct_path = True

        if not use_direct_path:
            return DiskTreeTransform._generate_limbo_path(self, trans_id)

        limbo_name = pathjoin(self._limbo_files[parent], filename)
        self._limbo_children[parent].add(trans_id)
        self._limbo_children_names[parent][filename] = trans_id
        return limbo_name

    def apply(self, no_conflicts=False, precomputed_delta=None, _mover=None):
        """Apply all changes to the inventory and filesystem.

        If filesystem or inventory conflicts are present, MalformedTransform
        will be thrown.

        If apply succeeds, finalize is not necessary.

        :param no_conflicts: if True, the caller guarantees there are no
            conflicts, so no check is made.
        :param precomputed_delta: An inventory delta to use instead of
            calculating one.
        :param _mover: Supply an alternate FileMover, for testing
        """
        for hook in MutableTree.hooks['pre_transform']:
            hook(self._tree, self)
        if not no_conflicts:
            self._check_malformed()
        with ui.ui_factory.nested_progress_bar() as child_pb:
            if precomputed_delta is None:
                child_pb.update(gettext('Apply phase'), 0, 2)
                inventory_delta = self._generate_inventory_delta()
                offset = 1
            else:
                inventory_delta = precomputed_delta
                offset = 0
            if _mover is None:
                mover = _FileMover()
            else:
                mover = _mover
            try:
                child_pb.update(gettext('Apply phase'), 0 + offset, 2 + offset)
                self._apply_removals(mover)
                child_pb.update(gettext('Apply phase'), 1 + offset, 2 + offset)
                modified_paths = self._apply_insertions(mover)
            except BaseException:
                mover.rollback()
                raise
            else:
                mover.apply_deletions()
        if self.final_file_id(self.root) is None:
            inventory_delta = [e for e in inventory_delta if e[0] != '']
        self._tree.apply_inventory_delta(inventory_delta)
        self._apply_observed_sha1s()
        self._done = True
        self.finalize()
        return _TransformResults(modified_paths, self.rename_count)

    def _generate_inventory_delta(self):
        """Generate an inventory delta for the current transform."""
        inventory_delta = []
        new_paths = self._inventory_altered()
        total_entries = len(new_paths) + len(self._removed_id)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, trans_id in enumerate(self._removed_id):
                if (num % 10) == 0:
                    child_pb.update(gettext('removing file'),
                                    num, total_entries)
                if trans_id == self._new_root:
                    file_id = self._tree.get_root_id()
                else:
                    file_id = self.tree_file_id(trans_id)
                # File-id isn't really being deleted, just moved
                if file_id in self._r_new_id:
                    continue
                path = self._tree_id_paths[trans_id]
                inventory_delta.append((path, None, file_id, None))
            new_path_file_ids = dict((t, self.final_file_id(t)) for p, t in
                                     new_paths)
            for num, (path, trans_id) in enumerate(new_paths):
                if (num % 10) == 0:
                    child_pb.update(gettext('adding file'),
                                    num + len(self._removed_id), total_entries)
                file_id = new_path_file_ids[trans_id]
                if file_id is None:
                    continue
                kind = self.final_kind(trans_id)
                if kind is None:
                    kind = self._tree.stored_kind(self._tree.id2path(file_id))
                parent_trans_id = self.final_parent(trans_id)
                parent_file_id = new_path_file_ids.get(parent_trans_id)
                if parent_file_id is None:
                    parent_file_id = self.final_file_id(parent_trans_id)
                if trans_id in self._new_reference_revision:
                    new_entry = inventory.TreeReference(
                        file_id,
                        self._new_name[trans_id],
                        self.final_file_id(self._new_parent[trans_id]),
                        None, self._new_reference_revision[trans_id])
                else:
                    new_entry = inventory.make_entry(kind,
                                                     self.final_name(trans_id),
                                                     parent_file_id, file_id)
                try:
                    old_path = self._tree.id2path(new_entry.file_id)
                except errors.NoSuchId:
                    old_path = None
                new_executability = self._new_executability.get(trans_id)
                if new_executability is not None:
                    new_entry.executable = new_executability
                inventory_delta.append(
                    (old_path, path, new_entry.file_id, new_entry))
        return inventory_delta

    def _apply_removals(self, mover):
        """Perform tree operations that remove directory/inventory names.

        That is, delete files that are to be deleted, and put any files that
        need renaming into limbo.  This must be done in strict child-to-parent
        order.

        If inventory_delta is None, no inventory delta generation is performed.
        """
        tree_paths = sorted(viewitems(self._tree_path_ids), reverse=True)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, (path, trans_id) in enumerate(tree_paths):
                # do not attempt to move root into a subdirectory of itself.
                if path == '':
                    continue
                child_pb.update(gettext('removing file'), num, len(tree_paths))
                full_path = self._tree.abspath(path)
                if trans_id in self._removed_contents:
                    delete_path = os.path.join(self._deletiondir, trans_id)
                    mover.pre_delete(full_path, delete_path)
                elif (trans_id in self._new_name or
                      trans_id in self._new_parent):
                    try:
                        mover.rename(full_path, self._limbo_name(trans_id))
                    except errors.TransformRenameFailed as e:
                        if e.errno != errno.ENOENT:
                            raise
                    else:
                        self.rename_count += 1

    def _apply_insertions(self, mover):
        """Perform tree operations that insert directory/inventory names.

        That is, create any files that need to be created, and restore from
        limbo any files that needed renaming.  This must be done in strict
        parent-to-child order.

        If inventory_delta is None, no inventory delta is calculated, and
        no list of modified paths is returned.
        """
        new_paths = self.new_paths(filesystem_only=True)
        modified_paths = []
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, (path, trans_id) in enumerate(new_paths):
                if (num % 10) == 0:
                    child_pb.update(gettext('adding file'),
                                    num, len(new_paths))
                full_path = self._tree.abspath(path)
                if trans_id in self._needs_rename:
                    try:
                        mover.rename(self._limbo_name(trans_id), full_path)
                    except errors.TransformRenameFailed as e:
                        # We may be renaming a dangling inventory id
                        if e.errno != errno.ENOENT:
                            raise
                    else:
                        self.rename_count += 1
                    # TODO: if trans_id in self._observed_sha1s, we should
                    #       re-stat the final target, since ctime will be
                    #       updated by the change.
                if (trans_id in self._new_contents
                        or self.path_changed(trans_id)):
                    if trans_id in self._new_contents:
                        modified_paths.append(full_path)
                if trans_id in self._new_executability:
                    self._set_executability(path, trans_id)
                if trans_id in self._observed_sha1s:
                    o_sha1, o_st_val = self._observed_sha1s[trans_id]
                    st = osutils.lstat(full_path)
                    self._observed_sha1s[trans_id] = (o_sha1, st)
        for path, trans_id in new_paths:
            # new_paths includes stuff like workingtree conflicts. Only the
            # stuff in new_contents actually comes from limbo.
            if trans_id in self._limbo_files:
                del self._limbo_files[trans_id]
        self._new_contents.clear()
        return modified_paths

    def _apply_observed_sha1s(self):
        """After we have finished renaming everything, update observed sha1s

        This has to be done after self._tree.apply_inventory_delta, otherwise
        it doesn't know anything about the files we are updating. Also, we want
        to do this as late as possible, so that most entries end up cached.
        """
        # TODO: this doesn't update the stat information for directories. So
        #       the first 'bzr status' will still need to rewrite
        #       .bzr/checkout/dirstate. However, we at least don't need to
        #       re-read all of the files.
        # TODO: If the operation took a while, we could do a time.sleep(3) here
        #       to allow the clock to tick over and ensure we won't have any
        #       problems. (we could observe start time, and finish time, and if
        #       it is less than eg 10% overhead, add a sleep call.)
        paths = FinalPaths(self)
        for trans_id, observed in viewitems(self._observed_sha1s):
            path = paths.get_path(trans_id)
            self._tree._observed_sha1(path, observed)


class TransformPreview(DiskTreeTransform):
    """A TreeTransform for generating preview trees.

    Unlike TreeTransform, this version works when the input tree is a
    RevisionTree, rather than a WorkingTree.  As a result, it tends to ignore
    unversioned files in the input tree.
    """

    def __init__(self, tree, pb=None, case_sensitive=True):
        tree.lock_read()
        limbodir = osutils.mkdtemp(prefix='bzr-limbo-')
        DiskTreeTransform.__init__(self, tree, limbodir, pb, case_sensitive)

    def canonical_path(self, path):
        return path

    def tree_kind(self, trans_id):
        path = self._tree_id_paths.get(trans_id)
        if path is None:
            return None
        kind = self._tree.path_content_summary(path)[0]
        if kind == 'missing':
            kind = None
        return kind

    def _set_mode(self, trans_id, mode_id, typefunc):
        """Set the mode of new file contents.
        The mode_id is the existing file to get the mode from (often the same
        as trans_id).  The operation is only performed if there's a mode match
        according to typefunc.
        """
        # is it ok to ignore this?  probably
        pass

    def iter_tree_children(self, parent_id):
        """Iterate through the entry's tree children, if any"""
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return
        try:
            entry = next(self._tree.iter_entries_by_dir(
                specific_files=[path]))[1]
        except StopIteration:
            return
        children = getattr(entry, 'children', {})
        for child in children:
            childpath = joinpath(path, child)
            yield self.trans_id_tree_path(childpath)

    def new_orphan(self, trans_id, parent_id):
        raise NotImplementedError(self.new_orphan)


class _PreviewTree(inventorytree.InventoryTree):
    """Partial implementation of Tree to support show_diff_trees"""

    def __init__(self, transform):
        self._transform = transform
        self._final_paths = FinalPaths(transform)
        self.__by_parent = None
        self._parent_ids = []
        self._all_children_cache = {}
        self._path2trans_id_cache = {}
        self._final_name_cache = {}
        self._iter_changes_cache = dict((c[0], c) for c in
                                        self._transform.iter_changes())

    def _content_change(self, file_id):
        """Return True if the content of this file changed"""
        changes = self._iter_changes_cache.get(file_id)
        # changes[2] is true if the file content changed.  See
        # InterTree.iter_changes.
        return (changes is not None and changes[2])

    def _get_repository(self):
        repo = getattr(self._transform._tree, '_repository', None)
        if repo is None:
            repo = self._transform._tree.branch.repository
        return repo

    def _iter_parent_trees(self):
        for revision_id in self.get_parent_ids():
            try:
                yield self.revision_tree(revision_id)
            except errors.NoSuchRevisionInTree:
                yield self._get_repository().revision_tree(revision_id)

    def _get_file_revision(self, path, file_id, vf, tree_revision):
        parent_keys = [
            (file_id, t.get_file_revision(t.id2path(file_id)))
            for t in self._iter_parent_trees()]
        vf.add_lines((file_id, tree_revision), parent_keys,
                     self.get_file_lines(path))
        repo = self._get_repository()
        base_vf = repo.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return tree_revision

    def _stat_limbo_file(self, trans_id):
        name = self._transform._limbo_name(trans_id)
        return os.lstat(name)

    @property
    def _by_parent(self):
        if self.__by_parent is None:
            self.__by_parent = self._transform.by_parent()
        return self.__by_parent

    def _comparison_data(self, entry, path):
        kind, size, executable, link_or_sha1 = self.path_content_summary(path)
        if kind == 'missing':
            kind = None
            executable = False
        else:
            file_id = self._transform.final_file_id(self._path2trans_id(path))
            executable = self.is_executable(path)
        return kind, executable, None

    def is_locked(self):
        return False

    def lock_read(self):
        # Perhaps in theory, this should lock the TreeTransform?
        return lock.LogicalLockResult(self.unlock)

    def unlock(self):
        pass

    @property
    def root_inventory(self):
        """This Tree does not use inventory as its backing data."""
        raise NotImplementedError(_PreviewTree.root_inventory)

    def get_root_id(self):
        return self._transform.final_file_id(self._transform.root)

    def all_file_ids(self):
        tree_ids = set(self._transform._tree.all_file_ids())
        tree_ids.difference_update(self._transform.tree_file_id(t)
                                   for t in self._transform._removed_id)
        tree_ids.update(viewvalues(self._transform._new_id))
        return tree_ids

    def all_versioned_paths(self):
        tree_paths = set(self._transform._tree.all_versioned_paths())

        tree_paths.difference_update(
            self._transform.trans_id_tree_path(t)
            for t in self._transform._removed_id)

        tree_paths.update(
            self._final_paths._determine_path(t)
            for t in self._transform._new_id)

        return tree_paths

    def _has_id(self, file_id, fallback_check):
        if file_id in self._transform._r_new_id:
            return True
        elif file_id in {self._transform.tree_file_id(trans_id) for
                         trans_id in self._transform._removed_id}:
            return False
        else:
            return fallback_check(file_id)

    def has_id(self, file_id):
        return self._has_id(file_id, self._transform._tree.has_id)

    def has_or_had_id(self, file_id):
        return self._has_id(file_id, self._transform._tree.has_or_had_id)

    def _path2trans_id(self, path):
        # We must not use None here, because that is a valid value to store.
        trans_id = self._path2trans_id_cache.get(path, object)
        if trans_id is not object:
            return trans_id
        segments = splitpath(path)
        cur_parent = self._transform.root
        for cur_segment in segments:
            for child in self._all_children(cur_parent):
                final_name = self._final_name_cache.get(child)
                if final_name is None:
                    final_name = self._transform.final_name(child)
                    self._final_name_cache[child] = final_name
                if final_name == cur_segment:
                    cur_parent = child
                    break
            else:
                self._path2trans_id_cache[path] = None
                return None
        self._path2trans_id_cache[path] = cur_parent
        return cur_parent

    def path2id(self, path):
        if isinstance(path, list):
            if path == []:
                path = [""]
            path = osutils.pathjoin(*path)
        return self._transform.final_file_id(self._path2trans_id(path))

    def id2path(self, file_id):
        trans_id = self._transform.trans_id_file_id(file_id)
        try:
            return self._final_paths._determine_path(trans_id)
        except NoFinalPath:
            raise errors.NoSuchId(self, file_id)

    def _all_children(self, trans_id):
        children = self._all_children_cache.get(trans_id)
        if children is not None:
            return children
        children = set(self._transform.iter_tree_children(trans_id))
        # children in the _new_parent set are provided by _by_parent.
        children.difference_update(self._transform._new_parent)
        children.update(self._by_parent.get(trans_id, []))
        self._all_children_cache[trans_id] = children
        return children

    def _iter_children(self, file_id):
        trans_id = self._transform.trans_id_file_id(file_id)
        for child_trans_id in self._all_children(trans_id):
            yield self._transform.final_file_id(child_trans_id)

    def extras(self):
        possible_extras = set(self._transform.trans_id_tree_path(p) for p
                              in self._transform._tree.extras())
        possible_extras.update(self._transform._new_contents)
        possible_extras.update(self._transform._removed_id)
        for trans_id in possible_extras:
            if self._transform.final_file_id(trans_id) is None:
                yield self._final_paths._determine_path(trans_id)

    def _make_inv_entries(self, ordered_entries, specific_files=None):
        for trans_id, parent_file_id in ordered_entries:
            file_id = self._transform.final_file_id(trans_id)
            if file_id is None:
                continue
            if (specific_files is not None
                    and self._final_paths.get_path(trans_id) not in specific_files):
                continue
            kind = self._transform.final_kind(trans_id)
            if kind is None:
                kind = self._transform._tree.stored_kind(
                    self._transform._tree.id2path(file_id))
            new_entry = inventory.make_entry(
                kind,
                self._transform.final_name(trans_id),
                parent_file_id, file_id)
            yield new_entry, trans_id

    def _list_files_by_dir(self):
        todo = [ROOT_PARENT]
        ordered_ids = []
        while len(todo) > 0:
            parent = todo.pop()
            parent_file_id = self._transform.final_file_id(parent)
            children = list(self._all_children(parent))
            paths = dict(zip(children, self._final_paths.get_paths(children)))
            children.sort(key=paths.get)
            todo.extend(reversed(children))
            for trans_id in children:
                ordered_ids.append((trans_id, parent_file_id))
        return ordered_ids

    def iter_child_entries(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        todo = [(child_trans_id, trans_id) for child_trans_id in
                self._all_children(trans_id)]
        for entry, trans_id in self._make_inv_entries(todo):
            yield entry

    def iter_entries_by_dir(self, specific_files=None):
        # This may not be a maximally efficient implementation, but it is
        # reasonably straightforward.  An implementation that grafts the
        # TreeTransform changes onto the tree's iter_entries_by_dir results
        # might be more efficient, but requires tricky inferences about stack
        # position.
        ordered_ids = self._list_files_by_dir()
        for entry, trans_id in self._make_inv_entries(ordered_ids,
                                                      specific_files):
            yield self._final_paths.get_path(trans_id), entry

    def _iter_entries_for_dir(self, dir_path):
        """Return path, entry for items in a directory without recursing down."""
        ordered_ids = []
        dir_trans_id = self._path2trans_id(dir_path)
        dir_id = self._transform.final_file_id(dir_trans_id)
        for child_trans_id in self._all_children(dir_trans_id):
            ordered_ids.append((child_trans_id, dir_id))
        path_entries = []
        for entry, trans_id in self._make_inv_entries(ordered_ids):
            path_entries.append((self._final_paths.get_path(trans_id), entry))
        path_entries.sort()
        return path_entries

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        """See WorkingTree.list_files."""
        # XXX This should behave like WorkingTree.list_files, but is really
        # more like RevisionTree.list_files.
        if from_dir == '.':
            from_dir = None
        if recursive:
            prefix = None
            if from_dir:
                prefix = from_dir + '/'
            entries = self.iter_entries_by_dir()
            for path, entry in entries:
                if entry.name == '' and not include_root:
                    continue
                if prefix:
                    if not path.startswith(prefix):
                        continue
                    path = path[len(prefix):]
                yield path, 'V', entry.kind, entry
        else:
            if from_dir is None and include_root is True:
                root_entry = inventory.make_entry(
                    'directory', '', ROOT_PARENT, self.get_root_id())
                yield '', 'V', 'directory', root_entry
            entries = self._iter_entries_for_dir(from_dir or '')
            for path, entry in entries:
                yield path, 'V', entry.kind, entry

    def kind(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        return self._transform.final_kind(trans_id)

    def stored_kind(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        try:
            return self._transform._new_contents[trans_id]
        except KeyError:
            return self._transform._tree.stored_kind(path)

    def get_file_mtime(self, path):
        """See Tree.get_file_mtime"""
        file_id = self.path2id(path)
        if file_id is None:
            raise errors.NoSuchFile(path)
        if not self._content_change(file_id):
            return self._transform._tree.get_file_mtime(
                self._transform._tree.id2path(file_id))
        trans_id = self._path2trans_id(path)
        return self._stat_limbo_file(trans_id).st_mtime

    def get_file_size(self, path):
        """See Tree.get_file_size"""
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        kind = self._transform.final_kind(trans_id)
        if kind != 'file':
            return None
        if trans_id in self._transform._new_contents:
            return self._stat_limbo_file(trans_id).st_size
        if self.kind(path) == 'file':
            return self._transform._tree.get_file_size(path)
        else:
            return None

    def get_file_verifier(self, path, stat_value=None):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        kind = self._transform._new_contents.get(trans_id)
        if kind is None:
            return self._transform._tree.get_file_verifier(path)
        if kind == 'file':
            with self.get_file(path) as fileobj:
                return ("SHA1", sha_file(fileobj))

    def get_file_sha1(self, path, stat_value=None):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        kind = self._transform._new_contents.get(trans_id)
        if kind is None:
            return self._transform._tree.get_file_sha1(path)
        if kind == 'file':
            with self.get_file(path) as fileobj:
                return sha_file(fileobj)

    def is_executable(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            return False
        try:
            return self._transform._new_executability[trans_id]
        except KeyError:
            try:
                return self._transform._tree.is_executable(path)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    return False
                raise
            except errors.NoSuchFile:
                return False

    def has_filename(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id in self._transform._new_contents:
            return True
        elif trans_id in self._transform._removed_contents:
            return False
        else:
            return self._transform._tree.has_filename(path)

    def path_content_summary(self, path):
        trans_id = self._path2trans_id(path)
        tt = self._transform
        tree_path = tt._tree_id_paths.get(trans_id)
        kind = tt._new_contents.get(trans_id)
        if kind is None:
            if tree_path is None or trans_id in tt._removed_contents:
                return 'missing', None, None, None
            summary = tt._tree.path_content_summary(tree_path)
            kind, size, executable, link_or_sha1 = summary
        else:
            link_or_sha1 = None
            limbo_name = tt._limbo_name(trans_id)
            if trans_id in tt._new_reference_revision:
                kind = 'tree-reference'
            if kind == 'file':
                statval = os.lstat(limbo_name)
                size = statval.st_size
                if not tt._limbo_supports_executable():
                    executable = False
                else:
                    executable = statval.st_mode & S_IEXEC
            else:
                size = None
                executable = None
            if kind == 'symlink':
                link_or_sha1 = os.readlink(limbo_name)
                if not isinstance(link_or_sha1, text_type):
                    link_or_sha1 = link_or_sha1.decode(osutils._fs_enc)
        executable = tt._new_executability.get(trans_id, executable)
        return kind, size, executable, link_or_sha1

    def iter_changes(self, from_tree, include_unchanged=False,
                     specific_files=None, pb=None, extra_trees=None,
                     require_versioned=True, want_unversioned=False):
        """See InterTree.iter_changes.

        This has a fast path that is only used when the from_tree matches
        the transform tree, and no fancy options are supplied.
        """
        if (from_tree is not self._transform._tree or include_unchanged
                or specific_files or want_unversioned):
            return tree.InterTree(from_tree, self).iter_changes(
                include_unchanged=include_unchanged,
                specific_files=specific_files,
                pb=pb,
                extra_trees=extra_trees,
                require_versioned=require_versioned,
                want_unversioned=want_unversioned)
        if want_unversioned:
            raise ValueError('want_unversioned is not supported')
        return self._transform.iter_changes()

    def get_file(self, path):
        """See Tree.get_file"""
        file_id = self.path2id(path)
        if not self._content_change(file_id):
            return self._transform._tree.get_file(path)
        trans_id = self._path2trans_id(path)
        name = self._transform._limbo_name(trans_id)
        return open(name, 'rb')

    def get_file_with_stat(self, path):
        return self.get_file(path), None

    def annotate_iter(self, path,
                      default_revision=_mod_revision.CURRENT_REVISION):
        file_id = self.path2id(path)
        changes = self._iter_changes_cache.get(file_id)
        if changes is None:
            get_old = True
        else:
            changed_content, versioned, kind = (changes[2], changes[3],
                                                changes[6])
            if kind[1] is None:
                return None
            get_old = (kind[0] == 'file' and versioned[0])
        if get_old:
            old_annotation = self._transform._tree.annotate_iter(
                path, default_revision=default_revision)
        else:
            old_annotation = []
        if changes is None:
            return old_annotation
        if not changed_content:
            return old_annotation
        # TODO: This is doing something similar to what WT.annotate_iter is
        #       doing, however it fails slightly because it doesn't know what
        #       the *other* revision_id is, so it doesn't know how to give the
        #       other as the origin for some lines, they all get
        #       'default_revision'
        #       It would be nice to be able to use the new Annotator based
        #       approach, as well.
        return annotate.reannotate([old_annotation],
                                   self.get_file(path).readlines(),
                                   default_revision)

    def get_symlink_target(self, path):
        """See Tree.get_symlink_target"""
        file_id = self.path2id(path)
        if not self._content_change(file_id):
            return self._transform._tree.get_symlink_target(path)
        trans_id = self._path2trans_id(path)
        name = self._transform._limbo_name(trans_id)
        return osutils.readlink(name)

    def walkdirs(self, prefix=''):
        pending = [self._transform.root]
        while len(pending) > 0:
            parent_id = pending.pop()
            children = []
            subdirs = []
            prefix = prefix.rstrip('/')
            parent_path = self._final_paths.get_path(parent_id)
            parent_file_id = self._transform.final_file_id(parent_id)
            for child_id in self._all_children(parent_id):
                path_from_root = self._final_paths.get_path(child_id)
                basename = self._transform.final_name(child_id)
                file_id = self._transform.final_file_id(child_id)
                kind = self._transform.final_kind(child_id)
                if kind is not None:
                    versioned_kind = kind
                else:
                    kind = 'unknown'
                    versioned_kind = self._transform._tree.stored_kind(
                        self._transform._tree.id2path(file_id))
                if versioned_kind == 'directory':
                    subdirs.append(child_id)
                children.append((path_from_root, basename, kind, None,
                                 file_id, versioned_kind))
            children.sort()
            if parent_path.startswith(prefix):
                yield (parent_path, parent_file_id), children
            pending.extend(sorted(subdirs, key=self._final_paths.get_path,
                                  reverse=True))

    def get_parent_ids(self):
        return self._parent_ids

    def set_parent_ids(self, parent_ids):
        self._parent_ids = parent_ids

    def get_revision_tree(self, revision_id):
        return self._transform._tree.get_revision_tree(revision_id)


def joinpath(parent, child):
    """Join tree-relative paths, handling the tree root specially"""
    if parent is None or parent == "":
        return child
    else:
        return pathjoin(parent, child)


class FinalPaths(object):
    """Make path calculation cheap by memoizing paths.

    The underlying tree must not be manipulated between calls, or else
    the results will likely be incorrect.
    """

    def __init__(self, transform):
        object.__init__(self)
        self._known_paths = {}
        self.transform = transform

    def _determine_path(self, trans_id):
        if (trans_id == self.transform.root or trans_id == ROOT_PARENT):
            return u""
        name = self.transform.final_name(trans_id)
        parent_id = self.transform.final_parent(trans_id)
        if parent_id == self.transform.root:
            return name
        else:
            return pathjoin(self.get_path(parent_id), name)

    def get_path(self, trans_id):
        """Find the final path associated with a trans_id"""
        if trans_id not in self._known_paths:
            self._known_paths[trans_id] = self._determine_path(trans_id)
        return self._known_paths[trans_id]

    def get_paths(self, trans_ids):
        return [(self.get_path(t), t) for t in trans_ids]


def topology_sorted_ids(tree):
    """Determine the topological order of the ids in a tree"""
    file_ids = list(tree)
    file_ids.sort(key=tree.id2path)
    return file_ids


def build_tree(tree, wt, accelerator_tree=None, hardlink=False,
               delta_from_tree=False):
    """Create working tree for a branch, using a TreeTransform.

    This function should be used on empty trees, having a tree root at most.
    (see merge and revert functionality for working with existing trees)

    Existing files are handled like so:

    - Existing bzrdirs take precedence over creating new items.  They are
      created as '%s.diverted' % name.
    - Otherwise, if the content on disk matches the content we are building,
      it is silently replaced.
    - Otherwise, conflict resolution will move the old file to 'oldname.moved'.

    :param tree: The tree to convert wt into a copy of
    :param wt: The working tree that files will be placed into
    :param accelerator_tree: A tree which can be used for retrieving file
        contents more quickly than tree itself, i.e. a workingtree.  tree
        will be used for cases where accelerator_tree's content is different.
    :param hardlink: If true, hard-link files to accelerator_tree, where
        possible.  accelerator_tree must implement abspath, i.e. be a
        working tree.
    :param delta_from_tree: If true, build_tree may use the input Tree to
        generate the inventory delta.
    """
    with wt.lock_tree_write(), tree.lock_read():
        if accelerator_tree is not None:
            accelerator_tree.lock_read()
        try:
            return _build_tree(tree, wt, accelerator_tree, hardlink,
                               delta_from_tree)
        finally:
            if accelerator_tree is not None:
                accelerator_tree.unlock()


def _build_tree(tree, wt, accelerator_tree, hardlink, delta_from_tree):
    """See build_tree."""
    for num, _unused in enumerate(wt.all_versioned_paths()):
        if num > 0:  # more than just a root
            raise errors.WorkingTreeAlreadyPopulated(base=wt.basedir)
    file_trans_id = {}
    top_pb = ui.ui_factory.nested_progress_bar()
    pp = ProgressPhase("Build phase", 2, top_pb)
    if tree.get_root_id() is not None:
        # This is kind of a hack: we should be altering the root
        # as part of the regular tree shape diff logic.
        # The conditional test here is to avoid doing an
        # expensive operation (flush) every time the root id
        # is set within the tree, nor setting the root and thus
        # marking the tree as dirty, because we use two different
        # idioms here: tree interfaces and inventory interfaces.
        if wt.get_root_id() != tree.get_root_id():
            wt.set_root_id(tree.get_root_id())
            wt.flush()
    tt = TreeTransform(wt)
    divert = set()
    try:
        pp.next_phase()
        file_trans_id[wt.get_root_id()] = tt.trans_id_tree_path('')
        with ui.ui_factory.nested_progress_bar() as pb:
            deferred_contents = []
            num = 0
            total = len(tree.all_versioned_paths())
            if delta_from_tree:
                precomputed_delta = []
            else:
                precomputed_delta = None
            # Check if tree inventory has content. If so, we populate
            # existing_files with the directory content. If there are no
            # entries we skip populating existing_files as its not used.
            # This improves performance and unncessary work on large
            # directory trees. (#501307)
            if total > 0:
                existing_files = set()
                for dir, files in wt.walkdirs():
                    existing_files.update(f[0] for f in files)
            for num, (tree_path, entry) in \
                    enumerate(tree.iter_entries_by_dir()):
                pb.update(gettext("Building tree"), num
                          - len(deferred_contents), total)
                if entry.parent_id is None:
                    continue
                reparent = False
                file_id = entry.file_id
                if delta_from_tree:
                    precomputed_delta.append((None, tree_path, file_id, entry))
                if tree_path in existing_files:
                    target_path = wt.abspath(tree_path)
                    kind = file_kind(target_path)
                    if kind == "directory":
                        try:
                            controldir.ControlDir.open(target_path)
                        except errors.NotBranchError:
                            pass
                        else:
                            divert.add(file_id)
                    if (file_id not in divert
                        and _content_match(
                            tree, entry, tree_path, file_id, kind,
                            target_path)):
                        tt.delete_contents(tt.trans_id_tree_path(tree_path))
                        if kind == 'directory':
                            reparent = True
                parent_id = file_trans_id[entry.parent_id]
                if entry.kind == 'file':
                    # We *almost* replicate new_by_entry, so that we can defer
                    # getting the file text, and get them all at once.
                    trans_id = tt.create_path(entry.name, parent_id)
                    file_trans_id[file_id] = trans_id
                    tt.version_file(file_id, trans_id)
                    executable = tree.is_executable(tree_path)
                    if executable:
                        tt.set_executability(executable, trans_id)
                    trans_data = (trans_id, file_id,
                                  tree_path, entry.text_sha1)
                    deferred_contents.append((tree_path, trans_data))
                else:
                    file_trans_id[file_id] = new_by_entry(
                        tree_path, tt, entry, parent_id, tree)
                if reparent:
                    new_trans_id = file_trans_id[file_id]
                    old_parent = tt.trans_id_tree_path(tree_path)
                    _reparent_children(tt, old_parent, new_trans_id)
            offset = num + 1 - len(deferred_contents)
            _create_files(tt, tree, deferred_contents, pb, offset,
                          accelerator_tree, hardlink)
        pp.next_phase()
        divert_trans = set(file_trans_id[f] for f in divert)

        def resolver(t, c):
            return resolve_checkout(t, c, divert_trans)
        raw_conflicts = resolve_conflicts(tt, pass_func=resolver)
        if len(raw_conflicts) > 0:
            precomputed_delta = None
        conflicts = cook_conflicts(raw_conflicts, tt)
        for conflict in conflicts:
            trace.warning(text_type(conflict))
        try:
            wt.add_conflicts(conflicts)
        except errors.UnsupportedOperation:
            pass
        result = tt.apply(no_conflicts=True,
                          precomputed_delta=precomputed_delta)
    finally:
        tt.finalize()
        top_pb.finished()
    return result


def _create_files(tt, tree, desired_files, pb, offset, accelerator_tree,
                  hardlink):
    total = len(desired_files) + offset
    wt = tt._tree
    if accelerator_tree is None:
        new_desired_files = desired_files
    else:
        iter = accelerator_tree.iter_changes(tree, include_unchanged=True)
        unchanged = [(p[0], p[1]) for (f, p, c, v, d, n, k, e)
                     in iter if not (c or e[0] != e[1])]
        if accelerator_tree.supports_content_filtering():
            unchanged = [(tp, ap) for (tp, ap) in unchanged
                         if not next(accelerator_tree.iter_search_rules([ap]))]
        unchanged = dict(unchanged)
        new_desired_files = []
        count = 0
        for unused_tree_path, (trans_id, file_id, tree_path, text_sha1) in desired_files:
            accelerator_path = unchanged.get(tree_path)
            if accelerator_path is None:
                new_desired_files.append((tree_path,
                                          (trans_id, file_id, tree_path, text_sha1)))
                continue
            pb.update(gettext('Adding file contents'), count + offset, total)
            if hardlink:
                tt.create_hardlink(accelerator_tree.abspath(accelerator_path),
                                   trans_id)
            else:
                with accelerator_tree.get_file(accelerator_path) as f:
                    chunks = osutils.file_iterator(f)
                    if wt.supports_content_filtering():
                        filters = wt._content_filter_stack(tree_path)
                        chunks = filtered_output_bytes(chunks, filters,
                                                       ContentFilterContext(tree_path, tree))
                    tt.create_file(chunks, trans_id, sha1=text_sha1)
            count += 1
        offset += count
    for count, ((trans_id, file_id, tree_path, text_sha1), contents) in enumerate(
            tree.iter_files_bytes(new_desired_files)):
        if wt.supports_content_filtering():
            filters = wt._content_filter_stack(tree_path)
            contents = filtered_output_bytes(contents, filters,
                                             ContentFilterContext(tree_path, tree))
        tt.create_file(contents, trans_id, sha1=text_sha1)
        pb.update(gettext('Adding file contents'), count + offset, total)


def _reparent_children(tt, old_parent, new_parent):
    for child in tt.iter_tree_children(old_parent):
        tt.adjust_path(tt.final_name(child), new_parent, child)


def _reparent_transform_children(tt, old_parent, new_parent):
    by_parent = tt.by_parent()
    for child in by_parent[old_parent]:
        tt.adjust_path(tt.final_name(child), new_parent, child)
    return by_parent[old_parent]


def _content_match(tree, entry, tree_path, file_id, kind, target_path):
    if entry.kind != kind:
        return False
    if entry.kind == "directory":
        return True
    if entry.kind == "file":
        with open(target_path, 'rb') as f1, \
                tree.get_file(tree_path) as f2:
            if osutils.compare_files(f1, f2):
                return True
    elif entry.kind == "symlink":
        if tree.get_symlink_target(tree_path) == os.readlink(target_path):
            return True
    return False


def resolve_checkout(tt, conflicts, divert):
    new_conflicts = set()
    for c_type, conflict in ((c[0], c) for c in conflicts):
        # Anything but a 'duplicate' would indicate programmer error
        if c_type != 'duplicate':
            raise AssertionError(c_type)
        # Now figure out which is new and which is old
        if tt.new_contents(conflict[1]):
            new_file = conflict[1]
            old_file = conflict[2]
        else:
            new_file = conflict[2]
            old_file = conflict[1]

        # We should only get here if the conflict wasn't completely
        # resolved
        final_parent = tt.final_parent(old_file)
        if new_file in divert:
            new_name = tt.final_name(old_file) + '.diverted'
            tt.adjust_path(new_name, final_parent, new_file)
            new_conflicts.add((c_type, 'Diverted to',
                               new_file, old_file))
        else:
            new_name = tt.final_name(old_file) + '.moved'
            tt.adjust_path(new_name, final_parent, old_file)
            new_conflicts.add((c_type, 'Moved existing file to',
                               old_file, new_file))
    return new_conflicts


def new_by_entry(path, tt, entry, parent_id, tree):
    """Create a new file according to its inventory entry"""
    name = entry.name
    kind = entry.kind
    if kind == 'file':
        with tree.get_file(path) as f:
            executable = tree.is_executable(path)
            return tt.new_file(
                name, parent_id, osutils.file_iterator(f), entry.file_id,
                executable)
    elif kind in ('directory', 'tree-reference'):
        trans_id = tt.new_directory(name, parent_id, entry.file_id)
        if kind == 'tree-reference':
            tt.set_tree_reference(entry.reference_revision, trans_id)
        return trans_id
    elif kind == 'symlink':
        target = tree.get_symlink_target(path)
        return tt.new_symlink(name, parent_id, target, entry.file_id)
    else:
        raise errors.BadFileKindError(name, kind)


def create_from_tree(tt, trans_id, tree, path, file_id=None, chunks=None,
                     filter_tree_path=None):
    """Create new file contents according to tree contents.

    :param filter_tree_path: the tree path to use to lookup
      content filters to apply to the bytes output in the working tree.
      This only applies if the working tree supports content filtering.
    """
    kind = tree.kind(path)
    if kind == 'directory':
        tt.create_directory(trans_id)
    elif kind == "file":
        if chunks is None:
            f = tree.get_file(path)
            chunks = osutils.file_iterator(f)
        else:
            f = None
        try:
            wt = tt._tree
            if wt.supports_content_filtering() and filter_tree_path is not None:
                filters = wt._content_filter_stack(filter_tree_path)
                chunks = filtered_output_bytes(
                    chunks, filters,
                    ContentFilterContext(filter_tree_path, tree))
            tt.create_file(chunks, trans_id)
        finally:
            if f is not None:
                f.close()
    elif kind == "symlink":
        tt.create_symlink(tree.get_symlink_target(path), trans_id)
    else:
        raise AssertionError('Unknown kind %r' % kind)


def create_entry_executability(tt, entry, trans_id):
    """Set the executability of a trans_id according to an inventory entry"""
    if entry.kind == "file":
        tt.set_executability(entry.executable, trans_id)


def revert(working_tree, target_tree, filenames, backups=False,
           pb=None, change_reporter=None):
    """Revert a working tree's contents to those of a target tree."""
    pb = ui.ui_factory.nested_progress_bar()
    try:
        with target_tree.lock_read(), TreeTransform(working_tree, pb) as tt:
            pp = ProgressPhase("Revert phase", 3, pb)
            conflicts, merge_modified = _prepare_revert_transform(
                working_tree, target_tree, tt, filenames, backups, pp)
            if change_reporter:
                change_reporter = delta._ChangeReporter(
                    unversioned_filter=working_tree.is_ignored)
                delta.report_changes(tt.iter_changes(), change_reporter)
            for conflict in conflicts:
                trace.warning(text_type(conflict))
            pp.next_phase()
            tt.apply()
            if working_tree.supports_merge_modified():
                working_tree.set_merge_modified(merge_modified)
    finally:
        pb.clear()
    return conflicts


def _prepare_revert_transform(working_tree, target_tree, tt, filenames,
                              backups, pp, basis_tree=None,
                              merge_modified=None):
    with ui.ui_factory.nested_progress_bar() as child_pb:
        if merge_modified is None:
            merge_modified = working_tree.merge_modified()
        merge_modified = _alter_files(working_tree, target_tree, tt,
                                      child_pb, filenames, backups,
                                      merge_modified, basis_tree)
    with ui.ui_factory.nested_progress_bar() as child_pb:
        raw_conflicts = resolve_conflicts(
            tt, child_pb, lambda t, c: conflict_pass(t, c, target_tree))
    conflicts = cook_conflicts(raw_conflicts, tt)
    return conflicts, merge_modified


def _alter_files(working_tree, target_tree, tt, pb, specific_files,
                 backups, merge_modified, basis_tree=None):
    if basis_tree is not None:
        basis_tree.lock_read()
    # We ask the working_tree for its changes relative to the target, rather
    # than the target changes relative to the working tree. Because WT4 has an
    # optimizer to compare itself to a target, but no optimizer for the
    # reverse.
    change_list = working_tree.iter_changes(
        target_tree, specific_files=specific_files, pb=pb)
    if not target_tree.is_versioned(u''):
        skip_root = True
    else:
        skip_root = False
    try:
        deferred_files = []
        for id_num, (file_id, path, changed_content, versioned, parent, name,
                     kind, executable) in enumerate(change_list):
            target_path, wt_path = path
            target_versioned, wt_versioned = versioned
            target_parent, wt_parent = parent
            target_name, wt_name = name
            target_kind, wt_kind = kind
            target_executable, wt_executable = executable
            if skip_root and wt_parent is None:
                continue
            trans_id = tt.trans_id_file_id(file_id)
            mode_id = None
            if changed_content:
                keep_content = False
                if wt_kind == 'file' and (backups or target_kind is None):
                    wt_sha1 = working_tree.get_file_sha1(wt_path)
                    if merge_modified.get(file_id) != wt_sha1:
                        # acquire the basis tree lazily to prevent the
                        # expense of accessing it when it's not needed ?
                        # (Guessing, RBC, 200702)
                        if basis_tree is None:
                            basis_tree = working_tree.basis_tree()
                            basis_tree.lock_read()
                        basis_path = find_previous_path(
                            working_tree, basis_tree, wt_path)
                        if basis_path is None:
                            if target_kind is None and not target_versioned:
                                keep_content = True
                        else:
                            if wt_sha1 != basis_tree.get_file_sha1(basis_path):
                                keep_content = True
                if wt_kind is not None:
                    if not keep_content:
                        tt.delete_contents(trans_id)
                    elif target_kind is not None:
                        parent_trans_id = tt.trans_id_file_id(wt_parent)
                        backup_name = tt._available_backup_name(
                            wt_name, parent_trans_id)
                        tt.adjust_path(backup_name, parent_trans_id, trans_id)
                        new_trans_id = tt.create_path(wt_name, parent_trans_id)
                        if wt_versioned and target_versioned:
                            tt.unversion_file(trans_id)
                            tt.version_file(file_id, new_trans_id)
                        # New contents should have the same unix perms as old
                        # contents
                        mode_id = trans_id
                        trans_id = new_trans_id
                if target_kind in ('directory', 'tree-reference'):
                    tt.create_directory(trans_id)
                    if target_kind == 'tree-reference':
                        revision = target_tree.get_reference_revision(
                            target_path)
                        tt.set_tree_reference(revision, trans_id)
                elif target_kind == 'symlink':
                    tt.create_symlink(target_tree.get_symlink_target(
                        target_path), trans_id)
                elif target_kind == 'file':
                    deferred_files.append(
                        (target_path, (trans_id, mode_id, file_id)))
                    if basis_tree is None:
                        basis_tree = working_tree.basis_tree()
                        basis_tree.lock_read()
                    new_sha1 = target_tree.get_file_sha1(target_path)
                    basis_path = find_previous_path(target_tree, basis_tree, target_path)
                    if (basis_path is not None and
                            new_sha1 == basis_tree.get_file_sha1(basis_path)):
                        if file_id in merge_modified:
                            del merge_modified[file_id]
                    else:
                        merge_modified[file_id] = new_sha1

                    # preserve the execute bit when backing up
                    if keep_content and wt_executable == target_executable:
                        tt.set_executability(target_executable, trans_id)
                elif target_kind is not None:
                    raise AssertionError(target_kind)
            if not wt_versioned and target_versioned:
                tt.version_file(file_id, trans_id)
            if wt_versioned and not target_versioned:
                tt.unversion_file(trans_id)
            if (target_name is not None
                    and (wt_name != target_name or wt_parent != target_parent)):
                if target_name == '' and target_parent is None:
                    parent_trans = ROOT_PARENT
                else:
                    parent_trans = tt.trans_id_file_id(target_parent)
                if wt_parent is None and wt_versioned:
                    tt.adjust_root_path(target_name, parent_trans)
                else:
                    tt.adjust_path(target_name, parent_trans, trans_id)
            if wt_executable != target_executable and target_kind == "file":
                tt.set_executability(target_executable, trans_id)
        if working_tree.supports_content_filtering():
            for (trans_id, mode_id, file_id), bytes in (
                    target_tree.iter_files_bytes(deferred_files)):
                # We're reverting a tree to the target tree so using the
                # target tree to find the file path seems the best choice
                # here IMO - Ian C 27/Oct/2009
                filter_tree_path = target_tree.id2path(file_id)
                filters = working_tree._content_filter_stack(filter_tree_path)
                bytes = filtered_output_bytes(
                    bytes, filters,
                    ContentFilterContext(filter_tree_path, working_tree))
                tt.create_file(bytes, trans_id, mode_id)
        else:
            for (trans_id, mode_id, file_id), bytes in target_tree.iter_files_bytes(
                    deferred_files):
                tt.create_file(bytes, trans_id, mode_id)
        tt.fixup_new_roots()
    finally:
        if basis_tree is not None:
            basis_tree.unlock()
    return merge_modified


def resolve_conflicts(tt, pb=None, pass_func=None):
    """Make many conflict-resolution attempts, but die if they fail"""
    if pass_func is None:
        pass_func = conflict_pass
    new_conflicts = set()
    with ui.ui_factory.nested_progress_bar() as pb:
        for n in range(10):
            pb.update(gettext('Resolution pass'), n + 1, 10)
            conflicts = tt.find_conflicts()
            if len(conflicts) == 0:
                return new_conflicts
            new_conflicts.update(pass_func(tt, conflicts))
        raise MalformedTransform(conflicts=conflicts)


def conflict_pass(tt, conflicts, path_tree=None):
    """Resolve some classes of conflicts.

    :param tt: The transform to resolve conflicts in
    :param conflicts: The conflicts to resolve
    :param path_tree: A Tree to get supplemental paths from
    """
    new_conflicts = set()
    for c_type, conflict in ((c[0], c) for c in conflicts):
        if c_type == 'duplicate id':
            tt.unversion_file(conflict[1])
            new_conflicts.add((c_type, 'Unversioned existing file',
                               conflict[1], conflict[2], ))
        elif c_type == 'duplicate':
            # files that were renamed take precedence
            final_parent = tt.final_parent(conflict[1])
            if tt.path_changed(conflict[1]):
                existing_file, new_file = conflict[2], conflict[1]
            else:
                existing_file, new_file = conflict[1], conflict[2]
            new_name = tt.final_name(existing_file) + '.moved'
            tt.adjust_path(new_name, final_parent, existing_file)
            new_conflicts.add((c_type, 'Moved existing file to',
                               existing_file, new_file))
        elif c_type == 'parent loop':
            # break the loop by undoing one of the ops that caused the loop
            cur = conflict[1]
            while not tt.path_changed(cur):
                cur = tt.final_parent(cur)
            new_conflicts.add((c_type, 'Cancelled move', cur,
                               tt.final_parent(cur),))
            tt.adjust_path(tt.final_name(cur), tt.get_tree_parent(cur), cur)

        elif c_type == 'missing parent':
            trans_id = conflict[1]
            if trans_id in tt._removed_contents:
                cancel_deletion = True
                orphans = tt._get_potential_orphans(trans_id)
                if orphans:
                    cancel_deletion = False
                    # All children are orphans
                    for o in orphans:
                        try:
                            tt.new_orphan(o, trans_id)
                        except OrphaningError:
                            # Something bad happened so we cancel the directory
                            # deletion which will leave it in place with a
                            # conflict. The user can deal with it from there.
                            # Note that this also catch the case where we don't
                            # want to create orphans and leave the directory in
                            # place.
                            cancel_deletion = True
                            break
                if cancel_deletion:
                    # Cancel the directory deletion
                    tt.cancel_deletion(trans_id)
                    new_conflicts.add(('deleting parent', 'Not deleting',
                                       trans_id))
            else:
                create = True
                try:
                    tt.final_name(trans_id)
                except NoFinalPath:
                    if path_tree is not None:
                        file_id = tt.final_file_id(trans_id)
                        if file_id is None:
                            file_id = tt.inactive_file_id(trans_id)
                        _, entry = next(path_tree.iter_entries_by_dir(
                            specific_files=[path_tree.id2path(file_id)]))
                        # special-case the other tree root (move its
                        # children to current root)
                        if entry.parent_id is None:
                            create = False
                            moved = _reparent_transform_children(
                                tt, trans_id, tt.root)
                            for child in moved:
                                new_conflicts.add((c_type, 'Moved to root',
                                                   child))
                        else:
                            parent_trans_id = tt.trans_id_file_id(
                                entry.parent_id)
                            tt.adjust_path(entry.name, parent_trans_id,
                                           trans_id)
                if create:
                    tt.create_directory(trans_id)
                    new_conflicts.add((c_type, 'Created directory', trans_id))
        elif c_type == 'unversioned parent':
            file_id = tt.inactive_file_id(conflict[1])
            # special-case the other tree root (move its children instead)
            if path_tree and path_tree.path2id('') == file_id:
                # This is the root entry, skip it
                continue
            tt.version_file(file_id, conflict[1])
            new_conflicts.add((c_type, 'Versioned directory', conflict[1]))
        elif c_type == 'non-directory parent':
            parent_id = conflict[1]
            parent_parent = tt.final_parent(parent_id)
            parent_name = tt.final_name(parent_id)
            parent_file_id = tt.final_file_id(parent_id)
            new_parent_id = tt.new_directory(parent_name + '.new',
                                             parent_parent, parent_file_id)
            _reparent_transform_children(tt, parent_id, new_parent_id)
            if parent_file_id is not None:
                tt.unversion_file(parent_id)
            new_conflicts.add((c_type, 'Created directory', new_parent_id))
        elif c_type == 'versioning no contents':
            tt.cancel_versioning(conflict[1])
    return new_conflicts


def cook_conflicts(raw_conflicts, tt):
    """Generate a list of cooked conflicts, sorted by file path"""
    conflict_iter = iter_cook_conflicts(raw_conflicts, tt)
    return sorted(conflict_iter, key=conflicts.Conflict.sort_key)


def iter_cook_conflicts(raw_conflicts, tt):
    fp = FinalPaths(tt)
    for conflict in raw_conflicts:
        c_type = conflict[0]
        action = conflict[1]
        modified_path = fp.get_path(conflict[2])
        modified_id = tt.final_file_id(conflict[2])
        if len(conflict) == 3:
            yield conflicts.Conflict.factory(
                c_type, action=action, path=modified_path, file_id=modified_id)

        else:
            conflicting_path = fp.get_path(conflict[3])
            conflicting_id = tt.final_file_id(conflict[3])
            yield conflicts.Conflict.factory(
                c_type, action=action, path=modified_path,
                file_id=modified_id,
                conflict_path=conflicting_path,
                conflict_file_id=conflicting_id)


class _FileMover(object):
    """Moves and deletes files for TreeTransform, tracking operations"""

    def __init__(self):
        self.past_renames = []
        self.pending_deletions = []

    def rename(self, from_, to):
        """Rename a file from one path to another."""
        try:
            os.rename(from_, to)
        except OSError as e:
            if e.errno in (errno.EEXIST, errno.ENOTEMPTY):
                raise errors.FileExists(to, str(e))
            # normal OSError doesn't include filenames so it's hard to see where
            # the problem is, see https://bugs.launchpad.net/bzr/+bug/491763
            raise errors.TransformRenameFailed(from_, to, str(e), e.errno)
        self.past_renames.append((from_, to))

    def pre_delete(self, from_, to):
        """Rename a file out of the way and mark it for deletion.

        Unlike os.unlink, this works equally well for files and directories.
        :param from_: The current file path
        :param to: A temporary path for the file
        """
        self.rename(from_, to)
        self.pending_deletions.append(to)

    def rollback(self):
        """Reverse all renames that have been performed"""
        for from_, to in reversed(self.past_renames):
            try:
                os.rename(to, from_)
            except OSError as e:
                raise errors.TransformRenameFailed(to, from_, str(e), e.errno)
        # after rollback, don't reuse _FileMover
        self.past_renames = None
        self.pending_deletions = None

    def apply_deletions(self):
        """Apply all marked deletions"""
        for path in self.pending_deletions:
            delete_any(path)
        # after apply_deletions, don't reuse _FileMover
        self.past_renames = None
        self.pending_deletions = None


def link_tree(target_tree, source_tree):
    """Where possible, hard-link files in a tree to those in another tree.

    :param target_tree: Tree to change
    :param source_tree: Tree to hard-link from
    """
    tt = TreeTransform(target_tree)
    try:
        for (file_id, paths, changed_content, versioned, parent, name, kind,
             executable) in target_tree.iter_changes(source_tree,
                                                     include_unchanged=True):
            if changed_content:
                continue
            if kind != ('file', 'file'):
                continue
            if executable[0] != executable[1]:
                continue
            trans_id = tt.trans_id_tree_path(paths[1])
            tt.delete_contents(trans_id)
            tt.create_hardlink(source_tree.abspath(paths[0]), trans_id)
        tt.apply()
    finally:
        tt.finalize()

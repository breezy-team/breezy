# Copyright (C) 2006-2011 Canonical Ltd
# Copyright (C) 2020 Breezy Developers
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

import errno
import os

from .. import errors, ui
from ..i18n import gettext
from ..mutabletree import MutableTree
from ..sixish import viewitems
from ..transform import (
    TreeTransform,
    _TransformResults,
    _FileMover,
    FinalPaths,
    unique_add,
    TransformRenameFailed,
    )

from ..bzr import inventory
from ..bzr.transform import TransformPreview as GitTransformPreview


class GitTreeTransform(TreeTransform):
    """Tree transform for Bazaar trees."""

    def version_file(self, trans_id, file_id=None):
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
                changes = self._generate_transform_changes()
                offset = 1
            else:
                changes = [
                    (op, np, ie) for (op, np, fid, ie) in precomputed_delta]
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
            changes = [e for e in changes if e[0] != '']
        self._tree._apply_transform_delta(changes)
        self._done = True
        self.finalize()
        return _TransformResults(modified_paths, self.rename_count)

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
                    except TransformRenameFailed as e:
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
                    except TransformRenameFailed as e:
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

    def _generate_transform_changes(self):
        """Generate an inventory delta for the current transform."""
        changes = []
        new_paths = self._inventory_altered()
        total_entries = len(new_paths) + len(self._removed_id)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, trans_id in enumerate(self._removed_id):
                if (num % 10) == 0:
                    child_pb.update(gettext('removing file'),
                                    num, total_entries)
                if trans_id == self._new_root:
                    file_id = self._tree.path2id('')
                else:
                    file_id = self.tree_file_id(trans_id)
                # File-id isn't really being deleted, just moved
                if file_id in self._r_new_id:
                    continue
                path = self._tree_id_paths[trans_id]
                changes.append((path, None, None))
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
                changes.append(
                    (old_path, path, new_entry))
        return changes

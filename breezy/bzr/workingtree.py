# Copyright (C) 2005-2011 Canonical Ltd
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

"""InventoryWorkingTree object and friends.

A WorkingTree represents the editable working copy of a branch.
Operations which represent the WorkingTree are also done here,
such as renaming or adding files.  The WorkingTree has an inventory
which is updated by these operations.  A commit produces a
new revision based on the workingtree and its inventory.

At the moment every WorkingTree has its own branch.  Remote
WorkingTrees aren't supported.

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""


from __future__ import absolute_import

from bisect import bisect_left
import breezy
import collections
import errno
import itertools
import operator
import os
import stat
import sys

# Explicitly import breezy.bzrdir so that the BzrProber
# is guaranteed to be registered.
from . import bzrdir

from .. import lazy_import
lazy_import.lazy_import(globals(), """
from breezy import (
    cache_utf8,
    conflicts as _mod_conflicts,
    globbing,
    ignores,
    revision as _mod_revision,
    rio as _mod_rio,
    )
from breezy.bzr import (
    inventory,
    xml5,
    xml7,
    )
""")

from .. import (
    errors,
    osutils,
    )
from ..lock import LogicalLockResult
from .inventorytree import InventoryRevisionTree, MutableInventoryTree
from ..sixish import (
    BytesIO,
    text_type,
    )
from ..trace import mutter, note
from ..tree import (
    get_canonical_path,
    TreeDirectory,
    TreeEntry,
    TreeFile,
    TreeLink,
    )
from ..workingtree import (
    WorkingTree,
    WorkingTreeFormat,
    format_registry,
    )


MERGE_MODIFIED_HEADER_1 = b"BZR merge-modified list format 1"
# TODO: Modifying the conflict objects or their type is currently nearly
# impossible as there is no clear relationship between the working tree format
# and the conflict list file format.
CONFLICT_HEADER_1 = b"BZR conflict list format 1"


class InventoryWorkingTree(WorkingTree, MutableInventoryTree):
    """Base class for working trees that are inventory-oriented.

    The inventory is held in the `Branch` working-inventory, and the
    files are in a directory on disk.

    It is possible for a `WorkingTree` to have a filename which is
    not listed in the Inventory and vice versa.
    """

    def __init__(self, basedir='.',
                 branch=None,
                 _inventory=None,
                 _control_files=None,
                 _internal=False,
                 _format=None,
                 _controldir=None):
        """Construct a InventoryWorkingTree instance. This is not a public API.

        :param branch: A branch to override probing for the branch.
        """
        super(InventoryWorkingTree, self).__init__(
            basedir=basedir, branch=branch,
            _transport=_control_files._transport, _internal=_internal,
            _format=_format, _controldir=_controldir)

        self._control_files = _control_files
        self._detect_case_handling()

        if _inventory is None:
            # This will be acquired on lock_read() or lock_write()
            self._inventory_is_modified = False
            self._inventory = None
        else:
            # the caller of __init__ has provided an inventory,
            # we assume they know what they are doing - as its only
            # the Format factory and creation methods that are
            # permitted to do this.
            self._set_inventory(_inventory, dirty=False)

    def _set_inventory(self, inv, dirty):
        """Set the internal cached inventory.

        :param inv: The inventory to set.
        :param dirty: A boolean indicating whether the inventory is the same
            logical inventory as whats on disk. If True the inventory is not
            the same and should be written to disk or data will be lost, if
            False then the inventory is the same as that on disk and any
            serialisation would be unneeded overhead.
        """
        self._inventory = inv
        self._inventory_is_modified = dirty

    def _detect_case_handling(self):
        wt_trans = self.controldir.get_workingtree_transport(None)
        try:
            wt_trans.stat(self._format.case_sensitive_filename)
        except errors.NoSuchFile:
            self.case_sensitive = True
        else:
            self.case_sensitive = False

        self._setup_directory_is_tree_reference()

    def _serialize(self, inventory, out_file):
        xml5.serializer_v5.write_inventory(
            self._inventory, out_file, working=True)

    def _deserialize(selt, in_file):
        return xml5.serializer_v5.read_inventory(in_file)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        self._control_files.break_lock()
        self.branch.break_lock()

    def is_locked(self):
        return self._control_files.is_locked()

    def _must_be_locked(self):
        if not self.is_locked():
            raise errors.ObjectNotLocked(self)

    def lock_read(self):
        """Lock the tree for reading.

        This also locks the branch, and can be unlocked via self.unlock().

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self.is_locked():
            self._reset_data()
        self.branch.lock_read()
        try:
            self._control_files.lock_read()
            return LogicalLockResult(self.unlock)
        except BaseException:
            self.branch.unlock()
            raise

    def lock_tree_write(self):
        """See MutableTree.lock_tree_write, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self.is_locked():
            self._reset_data()
        self.branch.lock_read()
        try:
            self._control_files.lock_write()
            return LogicalLockResult(self.unlock)
        except BaseException:
            self.branch.unlock()
            raise

    def lock_write(self):
        """See MutableTree.lock_write, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self.is_locked():
            self._reset_data()
        self.branch.lock_write()
        try:
            self._control_files.lock_write()
            return LogicalLockResult(self.unlock)
        except BaseException:
            self.branch.unlock()
            raise

    def get_physical_lock_status(self):
        return self._control_files.get_physical_lock_status()

    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        with self.lock_tree_write():
            self._set_inventory(inv, dirty=True)
            self.flush()

    # XXX: This method should be deprecated in favour of taking in a proper
    # new Inventory object.
    def set_inventory(self, new_inventory_list):
        from .inventory import (
            Inventory,
            InventoryDirectory,
            InventoryFile,
            InventoryLink)
        with self.lock_tree_write():
            inv = Inventory(self.get_root_id())
            for path, file_id, parent, kind in new_inventory_list:
                name = os.path.basename(path)
                if name == "":
                    continue
                # fixme, there should be a factory function inv,add_??
                if kind == 'directory':
                    inv.add(InventoryDirectory(file_id, name, parent))
                elif kind == 'file':
                    inv.add(InventoryFile(file_id, name, parent))
                elif kind == 'symlink':
                    inv.add(InventoryLink(file_id, name, parent))
                else:
                    raise errors.BzrError("unknown kind %r" % kind)
            self._write_inventory(inv)

    def _write_basis_inventory(self, xml):
        """Write the basis inventory XML to the basis-inventory file"""
        path = self._basis_inventory_name()
        sio = BytesIO(xml)
        self._transport.put_file(path, sio,
                                 mode=self.controldir._get_file_mode())

    def _reset_data(self):
        """Reset transient data that cannot be revalidated."""
        self._inventory_is_modified = False
        with self._transport.get('inventory') as f:
            result = self._deserialize(f)
        self._set_inventory(result, dirty=False)

    def store_uncommitted(self):
        """Store uncommitted changes from the tree in the branch."""
        with self.lock_write():
            target_tree = self.basis_tree()
            from ..shelf import ShelfCreator
            shelf_creator = ShelfCreator(self, target_tree)
            try:
                if not shelf_creator.shelve_all():
                    return
                self.branch.store_uncommitted(shelf_creator)
                shelf_creator.transform()
            finally:
                shelf_creator.finalize()
            note('Uncommitted changes stored in branch "%s".',
                 self.branch.nick)

    def restore_uncommitted(self):
        """Restore uncommitted changes from the branch into the tree."""
        with self.lock_write():
            unshelver = self.branch.get_unshelver(self)
            if unshelver is None:
                return
            try:
                merger = unshelver.make_merger()
                merger.ignore_zero = True
                merger.do_merge()
                self.branch.store_uncommitted(None)
            finally:
                unshelver.finalize()

    def get_shelf_manager(self):
        """Return the ShelfManager for this WorkingTree."""
        from ..shelf import ShelfManager
        return ShelfManager(self, self._transport)

    def _set_root_id(self, file_id):
        """Set the root id for this tree, in a format specific manner.

        :param file_id: The file id to assign to the root. It must not be
            present in the current inventory or an error will occur. It must
            not be None, but rather a valid file id.
        """
        inv = self._inventory
        orig_root_id = inv.root.file_id
        # TODO: it might be nice to exit early if there was nothing
        # to do, saving us from trigger a sync on unlock.
        self._inventory_is_modified = True
        # we preserve the root inventory entry object, but
        # unlinkit from the byid index
        inv.delete(inv.root.file_id)
        inv.root.file_id = file_id
        # and link it into the index with the new changed id.
        inv._byid[inv.root.file_id] = inv.root
        # and finally update all children to reference the new id.
        # XXX: this should be safe to just look at the root.children
        # list, not the WHOLE INVENTORY.
        for fid in inv.iter_all_ids():
            entry = inv.get_entry(fid)
            if entry.parent_id == orig_root_id:
                entry.parent_id = inv.root.file_id

    def remove(self, files, verbose=False, to_file=None, keep_files=True,
               force=False):
        """Remove nominated files from the working tree metadata.

        :files: File paths relative to the basedir.
        :keep_files: If true, the files will also be kept.
        :force: Delete files and directories, even if they are changed and
            even if the directories are not empty.
        """
        if isinstance(files, (str, text_type)):
            files = [files]

        inv_delta = []

        all_files = set()  # specified and nested files
        if to_file is None:
            to_file = sys.stdout

        files_to_backup = []

        def recurse_directory_to_add_files(directory):
            # Recurse directory and add all files
            # so we can check if they have changed.
            for parent_info, file_infos in self.walkdirs(directory):
                for relpath, basename, kind, lstat, fileid, kind in file_infos:
                    # Is it versioned or ignored?
                    if self.is_versioned(relpath):
                        # Add nested content for deletion.
                        all_files.add(relpath)
                    else:
                        # Files which are not versioned
                        # should be treated as unknown.
                        files_to_backup.append(relpath)

        with self.lock_tree_write():

            for filename in files:
                # Get file name into canonical form.
                abspath = self.abspath(filename)
                filename = self.relpath(abspath)
                if len(filename) > 0:
                    all_files.add(filename)
                    recurse_directory_to_add_files(filename)

            files = list(all_files)

            if len(files) == 0:
                return  # nothing to do

            # Sort needed to first handle directory content before the
            # directory
            files.sort(reverse=True)

            # Bail out if we are going to delete files we shouldn't
            if not keep_files and not force:
                for (file_id, path, content_change, versioned, parent_id, name,
                     kind, executable) in self.iter_changes(
                         self.basis_tree(), include_unchanged=True,
                         require_versioned=False, want_unversioned=True,
                         specific_files=files):
                    if versioned[0] is False:
                        # The record is unknown or newly added
                        files_to_backup.append(path[1])
                    elif (content_change and (kind[1] is not None)
                            and osutils.is_inside_any(files, path[1])):
                        # Versioned and changed, but not deleted, and still
                        # in one of the dirs to be deleted.
                        files_to_backup.append(path[1])

            def backup(file_to_backup):
                backup_name = self.controldir._available_backup_name(
                    file_to_backup)
                osutils.rename(abs_path, self.abspath(backup_name))
                return "removed %s (but kept a copy: %s)" % (file_to_backup,
                                                             backup_name)

            # Build inv_delta and delete files where applicable,
            # do this before any modifications to meta data.
            for f in files:
                fid = self.path2id(f)
                message = None
                if not fid:
                    message = "%s is not versioned." % (f,)
                else:
                    if verbose:
                        # having removed it, it must be either ignored or
                        # unknown
                        if self.is_ignored(f):
                            new_status = 'I'
                        else:
                            new_status = '?'
                        # XXX: Really should be a more abstract reporter
                        # interface
                        kind_ch = osutils.kind_marker(self.kind(f))
                        to_file.write(
                            new_status + '       ' + f + kind_ch + '\n')
                    # Unversion file
                    inv_delta.append((f, None, fid, None))
                    message = "removed %s" % (f,)

                if not keep_files:
                    abs_path = self.abspath(f)
                    if osutils.lexists(abs_path):
                        if (osutils.isdir(abs_path)
                                and len(os.listdir(abs_path)) > 0):
                            if force:
                                osutils.rmtree(abs_path)
                                message = "deleted %s" % (f,)
                            else:
                                message = backup(f)
                        else:
                            if f in files_to_backup:
                                message = backup(f)
                            else:
                                osutils.delete_any(abs_path)
                                message = "deleted %s" % (f,)
                    elif message is not None:
                        # Only care if we haven't done anything yet.
                        message = "%s does not exist." % (f,)

                # Print only one message (if any) per file.
                if message is not None:
                    note(message)
            self.apply_inventory_delta(inv_delta)

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """See MutableTree.set_parent_trees."""
        parent_ids = [rev for (rev, tree) in parents_list]
        for revision_id in parent_ids:
            _mod_revision.check_not_reserved_id(revision_id)

        with self.lock_tree_write():
            self._check_parents_for_ghosts(parent_ids,
                                           allow_leftmost_as_ghost=allow_leftmost_as_ghost)

            parent_ids = self._filter_parent_ids_by_ancestry(parent_ids)

            if len(parent_ids) == 0:
                leftmost_parent_id = _mod_revision.NULL_REVISION
                leftmost_parent_tree = None
            else:
                leftmost_parent_id, leftmost_parent_tree = parents_list[0]

            if self._change_last_revision(leftmost_parent_id):
                if leftmost_parent_tree is None:
                    # If we don't have a tree, fall back to reading the
                    # parent tree from the repository.
                    self._cache_basis_inventory(leftmost_parent_id)
                else:
                    inv = leftmost_parent_tree.root_inventory
                    xml = self._create_basis_xml_from_inventory(
                        leftmost_parent_id, inv)
                    self._write_basis_inventory(xml)
            self._set_merges_from_parent_ids(parent_ids)

    def _cache_basis_inventory(self, new_revision):
        """Cache new_revision as the basis inventory."""
        # TODO: this should allow the ready-to-use inventory to be passed in,
        # as commit already has that ready-to-use [while the format is the
        # same, that is].
        try:
            # this double handles the inventory - unpack and repack -
            # but is easier to understand. We can/should put a conditional
            # in here based on whether the inventory is in the latest format
            # - perhaps we should repack all inventories on a repository
            # upgrade ?
            # the fast path is to copy the raw xml from the repository. If the
            # xml contains 'revision_id="', then we assume the right
            # revision_id is set. We must check for this full string, because a
            # root node id can legitimately look like 'revision_id' but cannot
            # contain a '"'.
            xml = self.branch.repository._get_inventory_xml(new_revision)
            firstline = xml.split(b'\n', 1)[0]
            if (b'revision_id="' not in firstline
                    or b'format="7"' not in firstline):
                inv = self.branch.repository._serializer.read_inventory_from_string(
                    xml, new_revision)
                xml = self._create_basis_xml_from_inventory(new_revision, inv)
            self._write_basis_inventory(xml)
        except (errors.NoSuchRevision, errors.RevisionNotPresent):
            pass

    def _basis_inventory_name(self):
        return 'basis-inventory-cache'

    def _create_basis_xml_from_inventory(self, revision_id, inventory):
        """Create the text that will be saved in basis-inventory"""
        inventory.revision_id = revision_id
        return xml7.serializer_v7.write_inventory_to_string(inventory)

    def set_conflicts(self, conflicts):
        with self.lock_tree_write():
            self._put_rio('conflicts', conflicts.to_stanzas(),
                          CONFLICT_HEADER_1)

    def add_conflicts(self, new_conflicts):
        with self.lock_tree_write():
            conflict_set = set(self.conflicts())
            conflict_set.update(set(list(new_conflicts)))
            self.set_conflicts(_mod_conflicts.ConflictList(
                sorted(conflict_set, key=_mod_conflicts.Conflict.sort_key)))

    def conflicts(self):
        with self.lock_read():
            try:
                confile = self._transport.get('conflicts')
            except errors.NoSuchFile:
                return _mod_conflicts.ConflictList()
            try:
                try:
                    if next(confile) != CONFLICT_HEADER_1 + b'\n':
                        raise errors.ConflictFormatError()
                except StopIteration:
                    raise errors.ConflictFormatError()
                reader = _mod_rio.RioReader(confile)
                return _mod_conflicts.ConflictList.from_stanzas(reader)
            finally:
                confile.close()

    def get_ignore_list(self):
        """Return list of ignore patterns.

        Cached in the Tree object after the first call.
        """
        ignoreset = getattr(self, '_ignoreset', None)
        if ignoreset is not None:
            return ignoreset

        ignore_globs = set()
        ignore_globs.update(ignores.get_runtime_ignores())
        ignore_globs.update(ignores.get_user_ignores())
        if self.has_filename(self._format.ignore_filename):
            with self.get_file(self._format.ignore_filename) as f:
                ignore_globs.update(ignores.parse_ignore_file(f))
        self._ignoreset = ignore_globs
        return ignore_globs

    def _cleanup(self):
        self._flush_ignore_list_cache()

    def _flush_ignore_list_cache(self):
        """Resets the cached ignore list to force a cache rebuild."""
        self._ignoreset = None
        self._ignoreglobster = None

    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        Patterns containing '/' or '\' need to match the whole path;
        others match against only the last component.  Patterns starting
        with '!' are ignore exceptions.  Exceptions take precedence
        over regular patterns and cause the filename to not be ignored.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired."""
        if getattr(self, '_ignoreglobster', None) is None:
            self._ignoreglobster = globbing.ExceptionGlobster(
                self.get_ignore_list())
        return self._ignoreglobster.match(filename)

    def read_basis_inventory(self):
        """Read the cached basis inventory."""
        path = self._basis_inventory_name()
        return self._transport.get_bytes(path)

    def read_working_inventory(self):
        """Read the working inventory.

        :raises errors.InventoryModified: read_working_inventory will fail
            when the current in memory inventory has been modified.
        """
        # conceptually this should be an implementation detail of the tree.
        # XXX: Deprecate this.
        # ElementTree does its own conversion from UTF-8, so open in
        # binary.
        with self.lock_read():
            if self._inventory_is_modified:
                raise errors.InventoryModified(self)
            with self._transport.get('inventory') as f:
                result = self._deserialize(f)
            self._set_inventory(result, dirty=False)
            return result

    def get_root_id(self):
        """Return the id of this trees root"""
        with self.lock_read():
            return self._inventory.root.file_id

    def has_id(self, file_id):
        # files that have been deleted are excluded
        inv, inv_file_id = self._unpack_file_id(file_id)
        if not inv.has_id(inv_file_id):
            return False
        path = inv.id2path(inv_file_id)
        return osutils.lexists(self.abspath(path))

    def has_or_had_id(self, file_id):
        if file_id == self.get_root_id():
            return True
        inv, inv_file_id = self._unpack_file_id(file_id)
        return inv.has_id(inv_file_id)

    def all_file_ids(self):
        """Iterate through file_ids for this tree.

        file_ids are in a WorkingTree if they are in the working inventory
        and the working file exists.
        """
        return {ie.file_id for path, ie in self.iter_entries_by_dir()}

    def all_versioned_paths(self):
        return {path for path, ie in self.iter_entries_by_dir()}

    def set_last_revision(self, new_revision):
        """Change the last revision in the working tree."""
        with self.lock_tree_write():
            if self._change_last_revision(new_revision):
                self._cache_basis_inventory(new_revision)

    def _get_check_refs(self):
        """Return the references needed to perform a check of this tree.

        The default implementation returns no refs, and is only suitable for
        trees that have no local caching and can commit on ghosts at any time.

        :seealso: breezy.check for details about check_refs.
        """
        return []

    def _check(self, references):
        """Check the tree for consistency.

        :param references: A dict with keys matching the items returned by
            self._get_check_refs(), and values from looking those keys up in
            the repository.
        """
        with self.lock_read():
            tree_basis = self.basis_tree()
            with tree_basis.lock_read():
                repo_basis = references[('trees', self.last_revision())]
                if len(list(repo_basis.iter_changes(tree_basis))) > 0:
                    raise errors.BzrCheckError(
                        "Mismatched basis inventory content.")
                self._validate()

    def check_state(self):
        """Check that the working state is/isn't valid."""
        with self.lock_read():
            check_refs = self._get_check_refs()
            refs = {}
            for ref in check_refs:
                kind, value = ref
                if kind == 'trees':
                    refs[ref] = self.branch.repository.revision_tree(value)
            self._check(refs)

    def reset_state(self, revision_ids=None):
        """Reset the state of the working tree.

        This does a hard-reset to a last-known-good state. This is a way to
        fix if something got corrupted (like the .bzr/checkout/dirstate file)
        """
        with self.lock_tree_write():
            if revision_ids is None:
                revision_ids = self.get_parent_ids()
            if not revision_ids:
                rt = self.branch.repository.revision_tree(
                    _mod_revision.NULL_REVISION)
            else:
                rt = self.branch.repository.revision_tree(revision_ids[0])
            self._write_inventory(rt.root_inventory)
            self.set_parent_ids(revision_ids)

    def flush(self):
        """Write the in memory inventory to disk."""
        # TODO: Maybe this should only write on dirty ?
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        sio = BytesIO()
        self._serialize(self._inventory, sio)
        sio.seek(0)
        self._transport.put_file('inventory', sio,
                                 mode=self.controldir._get_file_mode())
        self._inventory_is_modified = False

    def get_file_mtime(self, path):
        """See Tree.get_file_mtime."""
        try:
            return os.lstat(self.abspath(path)).st_mtime
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise errors.NoSuchFile(path)
            raise

    def _is_executable_from_path_and_stat_from_basis(self, path, stat_result):
        try:
            return self._path2ie(path).executable
        except errors.NoSuchFile:
            # For unversioned files on win32, we just assume they are not
            # executable
            return False

    def _is_executable_from_path_and_stat_from_stat(self, path, stat_result):
        mode = stat_result.st_mode
        return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def is_executable(self, path):
        if not self._supports_executable():
            ie = self._path2ie(path)
            return ie.executable
        else:
            mode = os.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def _is_executable_from_path_and_stat(self, path, stat_result):
        if not self._supports_executable():
            return self._is_executable_from_path_and_stat_from_basis(
                path, stat_result)
        else:
            return self._is_executable_from_path_and_stat_from_stat(
                path, stat_result)

    def _add(self, files, ids, kinds):
        """See MutableTree._add."""
        with self.lock_tree_write():
            # TODO: Re-adding a file that is removed in the working copy
            # should probably put it back with the previous ID.
            # the read and write working inventory should not occur in this
            # function - they should be part of lock_write and unlock.
            # FIXME: nested trees
            inv = self.root_inventory
            for f, file_id, kind in zip(files, ids, kinds):
                if file_id is None:
                    inv.add_path(f, kind=kind)
                else:
                    inv.add_path(f, kind=kind, file_id=file_id)
                self._inventory_is_modified = True

    def revision_tree(self, revision_id):
        """See WorkingTree.revision_id."""
        if revision_id == self.last_revision():
            try:
                xml = self.read_basis_inventory()
            except errors.NoSuchFile:
                pass
            else:
                try:
                    inv = xml7.serializer_v7.read_inventory_from_string(xml)
                    # dont use the repository revision_tree api because we want
                    # to supply the inventory.
                    if inv.revision_id == revision_id:
                        return InventoryRevisionTree(
                            self.branch.repository, inv, revision_id)
                except errors.BadInventoryFormat:
                    pass
        # raise if there was no inventory, or if we read the wrong inventory.
        raise errors.NoSuchRevisionInTree(self, revision_id)

    def annotate_iter(self, path,
                      default_revision=_mod_revision.CURRENT_REVISION):
        """See Tree.annotate_iter

        This implementation will use the basis tree implementation if possible.
        Lines not in the basis are attributed to CURRENT_REVISION

        If there are pending merges, lines added by those merges will be
        incorrectly attributed to CURRENT_REVISION (but after committing, the
        attribution will be correct).
        """
        with self.lock_read():
            file_id = self.path2id(path)
            if file_id is None:
                raise errors.NoSuchFile(path)
            maybe_file_parent_keys = []
            for parent_id in self.get_parent_ids():
                try:
                    parent_tree = self.revision_tree(parent_id)
                except errors.NoSuchRevisionInTree:
                    parent_tree = self.branch.repository.revision_tree(
                        parent_id)
                with parent_tree.lock_read():

                    try:
                        kind = parent_tree.kind(path)
                    except errors.NoSuchFile:
                        continue
                    if kind != 'file':
                        # Note: this is slightly unnecessary, because symlinks
                        # and directories have a "text" which is the empty
                        # text, and we know that won't mess up annotations. But
                        # it seems cleaner
                        continue
                    parent_path = parent_tree.id2path(file_id)
                    parent_text_key = (
                        file_id,
                        parent_tree.get_file_revision(parent_path))
                    if parent_text_key not in maybe_file_parent_keys:
                        maybe_file_parent_keys.append(parent_text_key)
            graph = self.branch.repository.get_file_graph()
            heads = graph.heads(maybe_file_parent_keys)
            file_parent_keys = []
            for key in maybe_file_parent_keys:
                if key in heads:
                    file_parent_keys.append(key)

            # Now we have the parents of this content
            annotator = self.branch.repository.texts.get_annotator()
            text = self.get_file_text(path)
            this_key = (file_id, default_revision)
            annotator.add_special_text(this_key, file_parent_keys, text)
            annotations = [(key[-1], line)
                           for key, line in annotator.annotate_flat(this_key)]
            return annotations

    def _put_rio(self, filename, stanzas, header):
        self._must_be_locked()
        my_file = _mod_rio.rio_file(stanzas, header)
        self._transport.put_file(filename, my_file,
                                 mode=self.controldir._get_file_mode())

    def set_merge_modified(self, modified_hashes):
        def iter_stanzas():
            for file_id in modified_hashes:
                yield _mod_rio.Stanza(file_id=file_id.decode('utf8'),
                                      hash=modified_hashes[file_id])
        with self.lock_tree_write():
            self._put_rio('merge-hashes', iter_stanzas(),
                          MERGE_MODIFIED_HEADER_1)

    def merge_modified(self):
        """Return a dictionary of files modified by a merge.

        The list is initialized by WorkingTree.set_merge_modified, which is
        typically called after we make some automatic updates to the tree
        because of a merge.

        This returns a map of file_id->sha1, containing only files which are
        still in the working inventory and have that text hash.
        """
        with self.lock_read():
            try:
                hashfile = self._transport.get('merge-hashes')
            except errors.NoSuchFile:
                return {}
            try:
                merge_hashes = {}
                try:
                    if next(hashfile) != MERGE_MODIFIED_HEADER_1 + b'\n':
                        raise errors.MergeModifiedFormatError()
                except StopIteration:
                    raise errors.MergeModifiedFormatError()
                for s in _mod_rio.RioReader(hashfile):
                    # RioReader reads in Unicode, so convert file_ids back to
                    # utf8
                    file_id = cache_utf8.encode(s.get("file_id"))
                    if not self.has_id(file_id):
                        continue
                    text_hash = s.get("hash").encode('ascii')
                    path = self.id2path(file_id)
                    if text_hash == self.get_file_sha1(path):
                        merge_hashes[file_id] = text_hash
                return merge_hashes
            finally:
                hashfile.close()

    def subsume(self, other_tree):
        def add_children(inventory, entry):
            for child_entry in entry.children.values():
                inventory._byid[child_entry.file_id] = child_entry
                if child_entry.kind == 'directory':
                    add_children(inventory, child_entry)
        with self.lock_write():
            if other_tree.get_root_id() == self.get_root_id():
                raise errors.BadSubsumeSource(self, other_tree,
                                              'Trees have the same root')
            try:
                other_tree_path = self.relpath(other_tree.basedir)
            except errors.PathNotChild:
                raise errors.BadSubsumeSource(
                    self, other_tree, 'Tree is not contained by the other')
            new_root_parent = self.path2id(osutils.dirname(other_tree_path))
            if new_root_parent is None:
                raise errors.BadSubsumeSource(
                    self, other_tree, 'Parent directory is not versioned.')
            # We need to ensure that the result of a fetch will have a
            # versionedfile for the other_tree root, and only fetching into
            # RepositoryKnit2 guarantees that.
            if not self.branch.repository.supports_rich_root():
                raise errors.SubsumeTargetNeedsUpgrade(other_tree)
            with other_tree.lock_tree_write():
                other_root = other_tree.root_inventory.root
                other_root.parent_id = new_root_parent
                other_root.name = osutils.basename(other_tree_path)
                self.root_inventory.add(other_root)
                add_children(self.root_inventory, other_root)
                self._write_inventory(self.root_inventory)
                # normally we don't want to fetch whole repositories, but i
                # think here we really do want to consolidate the whole thing.
                for parent_id in other_tree.get_parent_ids():
                    self.branch.fetch(other_tree.branch, parent_id)
                    self.add_parent_tree_id(parent_id)
            other_tree.controldir.retire_bzrdir()

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
            # FIXME: Support nested trees
            my_inv = self.root_inventory
            child_inv = inventory.Inventory(root_id=None)
            file_id = self.path2id(sub_path)
            new_root = my_inv.get_entry(file_id)
            my_inv.remove_recursive_id(file_id)
            new_root.parent_id = None
            child_inv.add(new_root)
            self._write_inventory(my_inv)
            wt._write_inventory(child_inv)
            return wt

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        """List all files as (path, class, kind, id, entry).

        Lists, but does not descend into unversioned directories.
        This does not include files that have been deleted in this
        tree. Skips the control directory.

        :param include_root: if True, return an entry for the root
        :param from_dir: start from this directory or None for the root
        :param recursive: whether to recurse into subdirectories or not
        """
        with self.lock_read():
            if from_dir is None and include_root is True:
                yield ('', 'V', 'directory', self.get_root_id(),
                       self.root_inventory.root)
            # Convert these into local objects to save lookup times
            pathjoin = osutils.pathjoin

            # transport.base ends in a slash, we want the piece
            # between the last two slashes
            transport_base_dir = self.controldir.transport.base.rsplit(
                '/', 2)[1]

            fk_entries = {
                'directory': TreeDirectory,
                'file': TreeFile,
                'symlink': TreeLink
                }

            # directory file_id, relative path, absolute path, reverse sorted
            # children
            if from_dir is not None:
                inv, from_dir_id = self._path2inv_file_id(from_dir)
                if from_dir_id is None:
                    # Directory not versioned
                    return
                from_dir_abspath = pathjoin(self.basedir, from_dir)
            else:
                inv = self.root_inventory
                from_dir_id = inv.root.file_id
                from_dir_abspath = self.basedir
            children = sorted(os.listdir(from_dir_abspath))
            # jam 20060527 The kernel sized tree seems equivalent whether we
            # use a deque and popleft to keep them sorted, or if we use a plain
            # list and just reverse() them.
            children = collections.deque(children)
            stack = [(from_dir_id, u'', from_dir_abspath, children)]
            while stack:
                (from_dir_id, from_dir_relpath, from_dir_abspath,
                 children) = stack[-1]

                while children:
                    f = children.popleft()
                    # TODO: If we find a subdirectory with its own .bzr
                    # directory, then that is a separate tree and we
                    # should exclude it.

                    # the bzrdir for this tree
                    if transport_base_dir == f:
                        continue

                    # we know that from_dir_relpath and from_dir_abspath never
                    # end in a slash and 'f' doesn't begin with one, we can do
                    # a string op, rather than the checks of pathjoin(), all
                    # relative paths will have an extra slash at the beginning
                    fp = from_dir_relpath + '/' + f

                    # absolute path
                    fap = from_dir_abspath + '/' + f

                    dir_ie = inv.get_entry(from_dir_id)
                    if dir_ie.kind == 'directory':
                        f_ie = dir_ie.children.get(f)
                    else:
                        f_ie = None
                    if f_ie:
                        c = 'V'
                    elif self.is_ignored(fp[1:]):
                        c = 'I'
                    else:
                        # we may not have found this file, because of a unicode
                        # issue, or because the directory was actually a
                        # symlink.
                        f_norm, can_access = osutils.normalized_filename(f)
                        if f == f_norm or not can_access:
                            # No change, so treat this file normally
                            c = '?'
                        else:
                            # this file can be accessed by a normalized path
                            # check again if it is versioned
                            # these lines are repeated here for performance
                            f = f_norm
                            fp = from_dir_relpath + '/' + f
                            fap = from_dir_abspath + '/' + f
                            f_ie = inv.get_child(from_dir_id, f)
                            if f_ie:
                                c = 'V'
                            elif self.is_ignored(fp[1:]):
                                c = 'I'
                            else:
                                c = '?'

                    fk = osutils.file_kind(fap)

                    # make a last minute entry
                    if f_ie:
                        yield fp[1:], c, fk, f_ie.file_id, f_ie
                    else:
                        try:
                            yield fp[1:], c, fk, None, fk_entries[fk]()
                        except KeyError:
                            yield fp[1:], c, fk, None, TreeEntry()
                        continue

                    if fk != 'directory':
                        continue

                    # But do this child first if recursing down
                    if recursive:
                        new_children = sorted(os.listdir(fap))
                        new_children = collections.deque(new_children)
                        stack.append((f_ie.file_id, fp, fap, new_children))
                        # Break out of inner loop,
                        # so that we start outer loop with child
                        break
                else:
                    # if we finished all children, pop it off the stack
                    stack.pop()

    def move(self, from_paths, to_dir=None, after=False):
        """Rename files.

        to_dir must exist in the inventory.

        If to_dir exists and is a directory, the files are moved into
        it, keeping their old names.

        Note that to_dir is only the last component of the new name;
        this doesn't change the directory.

        For each entry in from_paths the move mode will be determined
        independently.

        The first mode moves the file in the filesystem and updates the
        inventory. The second mode only updates the inventory without
        touching the file on the filesystem.

        move uses the second mode if 'after == True' and the target is
        either not versioned or newly added, and present in the working tree.

        move uses the second mode if 'after == False' and the source is
        versioned but no longer in the working tree, and the target is not
        versioned but present in the working tree.

        move uses the first mode if 'after == False' and the source is
        versioned and present in the working tree, and the target is not
        versioned and not present in the working tree.

        Everything else results in an error.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        rename_entries = []
        rename_tuples = []

        # check for deprecated use of signature
        if to_dir is None:
            raise TypeError('You must supply a target directory')
        # check destination directory
        if isinstance(from_paths, (str, text_type)):
            raise ValueError()
        with self.lock_tree_write():
            to_abs = self.abspath(to_dir)
            if not osutils.isdir(to_abs):
                raise errors.BzrMoveFailedError(
                    '', to_dir, errors.NotADirectory(to_abs))
            if not self.has_filename(to_dir):
                raise errors.BzrMoveFailedError(
                    '', to_dir, errors.NotInWorkingDirectory(to_dir))
            to_inv, to_dir_id = self._path2inv_file_id(to_dir)
            if to_dir_id is None:
                raise errors.BzrMoveFailedError(
                    '', to_dir, errors.NotVersionedError(path=to_dir))

            to_dir_ie = to_inv.get_entry(to_dir_id)
            if to_dir_ie.kind != 'directory':
                raise errors.BzrMoveFailedError(
                    '', to_dir, errors.NotADirectory(to_abs))

            # create rename entries and tuples
            for from_rel in from_paths:
                from_tail = osutils.splitpath(from_rel)[-1]
                from_inv, from_id = self._path2inv_file_id(from_rel)
                if from_id is None:
                    raise errors.BzrMoveFailedError(from_rel, to_dir,
                                                    errors.NotVersionedError(path=from_rel))

                from_entry = from_inv.get_entry(from_id)
                from_parent_id = from_entry.parent_id
                to_rel = osutils.pathjoin(to_dir, from_tail)
                rename_entry = InventoryWorkingTree._RenameEntry(
                    from_rel=from_rel,
                    from_id=from_id,
                    from_tail=from_tail,
                    from_parent_id=from_parent_id,
                    to_rel=to_rel, to_tail=from_tail,
                    to_parent_id=to_dir_id)
                rename_entries.append(rename_entry)
                rename_tuples.append((from_rel, to_rel))

            # determine which move mode to use. checks also for movability
            rename_entries = self._determine_mv_mode(rename_entries, after)

            original_modified = self._inventory_is_modified
            try:
                if len(from_paths):
                    self._inventory_is_modified = True
                self._move(rename_entries)
            except BaseException:
                # restore the inventory on error
                self._inventory_is_modified = original_modified
                raise
            # FIXME: Should potentially also write the from_invs
            self._write_inventory(to_inv)
            return rename_tuples

    def rename_one(self, from_rel, to_rel, after=False):
        """Rename one file.

        This can change the directory or the filename or both.

        rename_one has several 'modes' to work. First, it can rename a physical
        file and change the file_id. That is the normal mode. Second, it can
        only change the file_id without touching any physical file.

        rename_one uses the second mode if 'after == True' and 'to_rel' is not
        versioned but present in the working tree.

        rename_one uses the second mode if 'after == False' and 'from_rel' is
        versioned but no longer in the working tree, and 'to_rel' is not
        versioned but present in the working tree.

        rename_one uses the first mode if 'after == False' and 'from_rel' is
        versioned and present in the working tree, and 'to_rel' is not
        versioned and not present in the working tree.

        Everything else results in an error.
        """
        with self.lock_tree_write():
            rename_entries = []

            # create rename entries and tuples
            from_tail = osutils.splitpath(from_rel)[-1]
            from_inv, from_id = self._path2inv_file_id(from_rel)
            if from_id is None:
                # if file is missing in the inventory maybe it's in the
                # basis_tree
                basis_tree = self.branch.basis_tree()
                from_id = basis_tree.path2id(from_rel)
                if from_id is None:
                    raise errors.BzrRenameFailedError(
                        from_rel, to_rel,
                        errors.NotVersionedError(path=from_rel))
                # put entry back in the inventory so we can rename it
                from_entry = basis_tree.root_inventory.get_entry(
                    from_id).copy()
                from_inv.add(from_entry)
            else:
                from_inv, from_inv_id = self._unpack_file_id(from_id)
                from_entry = from_inv.get_entry(from_inv_id)
            from_parent_id = from_entry.parent_id
            to_dir, to_tail = os.path.split(to_rel)
            to_inv, to_dir_id = self._path2inv_file_id(to_dir)
            rename_entry = InventoryWorkingTree._RenameEntry(
                from_rel=from_rel,
                from_id=from_id,
                from_tail=from_tail,
                from_parent_id=from_parent_id,
                to_rel=to_rel, to_tail=to_tail,
                to_parent_id=to_dir_id)
            rename_entries.append(rename_entry)

            # determine which move mode to use. checks also for movability
            rename_entries = self._determine_mv_mode(rename_entries, after)

            # check if the target changed directory and if the target directory
            # is versioned
            if to_dir_id is None:
                raise errors.BzrMoveFailedError(
                    from_rel, to_rel, errors.NotVersionedError(path=to_dir))

            # all checks done. now we can continue with our actual work
            mutter('rename_one:\n'
                   '  from_id   {%s}\n'
                   '  from_rel: %r\n'
                   '  to_rel:   %r\n'
                   '  to_dir    %r\n'
                   '  to_dir_id {%s}\n',
                   from_id, from_rel, to_rel, to_dir, to_dir_id)

            self._move(rename_entries)
            self._write_inventory(to_inv)

    class _RenameEntry(object):
        def __init__(self, from_rel, from_id, from_tail, from_parent_id,
                     to_rel, to_tail, to_parent_id, only_change_inv=False,
                     change_id=False):
            self.from_rel = from_rel
            self.from_id = from_id
            self.from_tail = from_tail
            self.from_parent_id = from_parent_id
            self.to_rel = to_rel
            self.to_tail = to_tail
            self.to_parent_id = to_parent_id
            self.change_id = change_id
            self.only_change_inv = only_change_inv

    def _determine_mv_mode(self, rename_entries, after=False):
        """Determines for each from-to pair if both inventory and working tree
        or only the inventory has to be changed.

        Also does basic plausability tests.
        """
        # FIXME: Handling of nested trees
        inv = self.root_inventory

        for rename_entry in rename_entries:
            # store to local variables for easier reference
            from_rel = rename_entry.from_rel
            from_id = rename_entry.from_id
            to_rel = rename_entry.to_rel
            to_id = inv.path2id(to_rel)
            only_change_inv = False

            # check the inventory for source and destination
            if from_id is None:
                raise errors.BzrMoveFailedError(
                    from_rel, to_rel, errors.NotVersionedError(path=from_rel))
            if to_id is not None:
                allowed = False
                # allow it with --after but only if dest is newly added
                if after:
                    basis = self.basis_tree()
                    with basis.lock_read():
                        if not basis.has_id(to_id):
                            rename_entry.change_id = True
                            allowed = True
                if not allowed:
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel,
                        errors.AlreadyVersionedError(path=to_rel))

            # try to determine the mode for rename (only change inv or change
            # inv and file system)
            if after:
                if not self.has_filename(to_rel):
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel,
                        errors.NoSuchFile(
                            path=to_rel,
                            extra="New file has not been created yet"))
                only_change_inv = True
            elif not self.has_filename(from_rel) and self.has_filename(to_rel):
                only_change_inv = True
            elif self.has_filename(from_rel) and not self.has_filename(to_rel):
                only_change_inv = False
            elif (not self.case_sensitive and
                  from_rel.lower() == to_rel.lower() and
                  self.has_filename(from_rel)):
                only_change_inv = False
            else:
                # something is wrong, so lets determine what exactly
                if not self.has_filename(from_rel) and \
                   not self.has_filename(to_rel):
                    raise errors.BzrRenameFailedError(
                        from_rel, to_rel,
                        errors.PathsDoNotExist(paths=(from_rel, to_rel)))
                else:
                    raise errors.RenameFailedFilesExist(from_rel, to_rel)
            rename_entry.only_change_inv = only_change_inv
        return rename_entries

    def _move(self, rename_entries):
        """Moves a list of files.

        Depending on the value of the flag 'only_change_inv', the
        file will be moved on the file system or not.
        """
        moved = []

        for entry in rename_entries:
            try:
                self._move_entry(entry)
            except BaseException:
                self._rollback_move(moved)
                raise
            moved.append(entry)

    def _rollback_move(self, moved):
        """Try to rollback a previous move in case of an filesystem error."""
        for entry in moved:
            try:
                self._move_entry(WorkingTree._RenameEntry(
                    entry.to_rel, entry.from_id,
                    entry.to_tail, entry.to_parent_id, entry.from_rel,
                    entry.from_tail, entry.from_parent_id,
                    entry.only_change_inv))
            except errors.BzrMoveFailedError as e:
                raise errors.BzrMoveFailedError(
                    '', '', "Rollback failed."
                    " The working tree is in an inconsistent state."
                    " Please consider doing a 'bzr revert'."
                    " Error message is: %s" % e)

    def _move_entry(self, entry):
        inv = self.root_inventory
        from_rel_abs = self.abspath(entry.from_rel)
        to_rel_abs = self.abspath(entry.to_rel)
        if from_rel_abs == to_rel_abs:
            raise errors.BzrMoveFailedError(entry.from_rel, entry.to_rel,
                                            "Source and target are identical.")

        if not entry.only_change_inv:
            try:
                osutils.rename(from_rel_abs, to_rel_abs)
            except OSError as e:
                raise errors.BzrMoveFailedError(
                    entry.from_rel, entry.to_rel, e[1])
        if entry.change_id:
            to_id = inv.path2id(entry.to_rel)
            inv.remove_recursive_id(to_id)
        inv.rename(entry.from_id, entry.to_parent_id, entry.to_tail)

    def unversion(self, paths):
        """Remove the paths in paths from the current versioned set.

        When a path is unversioned, all of its children are automatically
        unversioned.

        :param paths: The paths to stop versioning.
        :raises NoSuchFile: if any path is not currently versioned.
        """
        with self.lock_tree_write():
            file_ids = set()
            for path in paths:
                file_id = self._inventory.path2id(path)
                if file_id is None:
                    raise errors.NoSuchFile(path, self)
                file_ids.add(file_id)
            for file_id in file_ids:
                if self._inventory.has_id(file_id):
                    self._inventory.remove_recursive_id(file_id)
            if len(file_ids):
                # in the future this should just set a dirty bit to wait for
                # the final unlock. However, until all methods of workingtree
                # start with the current in -memory inventory rather than
                # triggering a read, it is more complex - we need to teach
                # read_inventory to know when to read, and when to not read
                # first... and possibly to save first when the in memory one
                # may be corrupted.  so for now, we just only write it if it is
                # indeed dirty.  - RBC 20060907
                self._write_inventory(self._inventory)

    def stored_kind(self, path, file_id=None):
        """See Tree.stored_kind"""
        return self._path2ie(path).kind

    def extras(self):
        """Yield all unversioned files in this WorkingTree.

        If there are any unversioned directories then only the directory is
        returned, not all its children.  But if there are unversioned files
        under a versioned subdirectory, they are returned.

        Currently returned depth-first, sorted by name within directories.
        This is the same order used by 'osutils.walkdirs'.
        """
        # TODO: Work from given directory downwards
        for path, dir_entry in self.iter_entries_by_dir():
            if dir_entry.kind != 'directory':
                continue
            # mutter("search for unknowns in %r", path)
            dirabs = self.abspath(path)
            if not osutils.isdir(dirabs):
                # e.g. directory deleted
                continue

            fl = []
            for subf in os.listdir(dirabs.encode(osutils._fs_enc)):
                try:
                    subf = subf.decode(osutils._fs_enc)
                except UnicodeDecodeError:
                    path_os_enc = path.encode(osutils._fs_enc)
                    relpath = path_os_enc + b'/' + subf
                    raise errors.BadFilenameEncoding(relpath,
                                                     osutils._fs_enc)

                if self.controldir.is_control_filename(subf):
                    continue
                if subf not in dir_entry.children:
                    try:
                        (subf_norm,
                         can_access) = osutils.normalized_filename(subf)
                    except UnicodeDecodeError:
                        path_os_enc = path.encode(osutils._fs_enc)
                        relpath = path_os_enc + '/' + subf
                        raise errors.BadFilenameEncoding(relpath,
                                                         osutils._fs_enc)
                    if subf_norm != subf and can_access:
                        if subf_norm not in dir_entry.children:
                            fl.append(subf_norm)
                    else:
                        fl.append(subf)

            fl.sort()
            for subf in fl:
                subp = osutils.pathjoin(path, subf)
                yield subp

    def walkdirs(self, prefix=""):
        """Walk the directories of this tree.

        returns a generator which yields items in the form:
                ((curren_directory_path, fileid),
                 [(file1_path, file1_name, file1_kind, (lstat), file1_id,
                   file1_kind), ... ])

        This API returns a generator, which is only valid during the current
        tree transaction - within a single lock_read or lock_write duration.

        If the tree is not locked, it may cause an error to be raised,
        depending on the tree implementation.
        """
        disk_top = self.abspath(prefix)
        if disk_top.endswith('/'):
            disk_top = disk_top[:-1]
        top_strip_len = len(disk_top) + 1
        inventory_iterator = self._walkdirs(prefix)
        disk_iterator = osutils.walkdirs(disk_top, prefix)
        try:
            current_disk = next(disk_iterator)
            disk_finished = False
        except OSError as e:
            if not (e.errno == errno.ENOENT
                    or (sys.platform == 'win32' and e.errno == ERROR_PATH_NOT_FOUND)):
                raise
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
                ((cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content) = current_disk
            else:
                ((cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content) = ((None, None), None)
            if not disk_finished:
                # strip out .bzr dirs
                if (cur_disk_dir_path_from_top[top_strip_len:] == ''
                        and len(cur_disk_dir_content) > 0):
                    # osutils.walkdirs can be made nicer -
                    # yield the path-from-prefix rather than the pathjoined
                    # value.
                    bzrdir_loc = bisect_left(cur_disk_dir_content,
                                             ('.bzr', '.bzr'))
                    if (bzrdir_loc < len(cur_disk_dir_content) and
                        self.controldir.is_control_filename(
                            cur_disk_dir_content[bzrdir_loc][0])):
                        # we dont yield the contents of, or, .bzr itself.
                        del cur_disk_dir_content[bzrdir_loc]
            if inv_finished:
                # everything is unknown
                direction = 1
            elif disk_finished:
                # everything is missing
                direction = -1
            else:
                direction = ((current_inv[0][0] > cur_disk_dir_relpath)
                             - (current_inv[0][0] < cur_disk_dir_relpath))

            if direction > 0:
                # disk is before inventory - unknown
                dirblock = [(relpath, basename, kind, stat, None, None) for
                            relpath, basename, kind, stat, top_path in
                            cur_disk_dir_content]
                yield (cur_disk_dir_relpath, None), dirblock
                try:
                    current_disk = next(disk_iterator)
                except StopIteration:
                    disk_finished = True
            elif direction < 0:
                # inventory is before disk - missing.
                dirblock = [(relpath, basename, 'unknown', None, fileid, kind)
                            for relpath, basename, dkind, stat, fileid, kind in
                            current_inv[1]]
                yield (current_inv[0][0], current_inv[0][1]), dirblock
                try:
                    current_inv = next(inventory_iterator)
                except StopIteration:
                    inv_finished = True
            else:
                # versioned present directory
                # merge the inventory and disk data together
                dirblock = []
                for relpath, subiterator in itertools.groupby(sorted(
                        current_inv[1] + cur_disk_dir_content,
                        key=operator.itemgetter(0)), operator.itemgetter(1)):
                    path_elements = list(subiterator)
                    if len(path_elements) == 2:
                        inv_row, disk_row = path_elements
                        # versioned, present file
                        dirblock.append((inv_row[0],
                                         inv_row[1], disk_row[2],
                                         disk_row[3], inv_row[4],
                                         inv_row[5]))
                    elif len(path_elements[0]) == 5:
                        # unknown disk file
                        dirblock.append(
                            (path_elements[0][0], path_elements[0][1],
                             path_elements[0][2], path_elements[0][3], None,
                             None))
                    elif len(path_elements[0]) == 6:
                        # versioned, absent file.
                        dirblock.append(
                            (path_elements[0][0], path_elements[0][1],
                             'unknown', None, path_elements[0][4],
                             path_elements[0][5]))
                    else:
                        raise NotImplementedError('unreachable code')
                yield current_inv[0], dirblock
                try:
                    current_inv = next(inventory_iterator)
                except StopIteration:
                    inv_finished = True
                try:
                    current_disk = next(disk_iterator)
                except StopIteration:
                    disk_finished = True

    def _walkdirs(self, prefix=""):
        """Walk the directories of this tree.

        :param prefix: is used as the directrory to start with.
        :returns: a generator which yields items in the form::

            ((curren_directory_path, fileid),
             [(file1_path, file1_name, file1_kind, None, file1_id,
               file1_kind), ... ])
        """
        _directory = 'directory'
        # get the root in the inventory
        inv, top_id = self._path2inv_file_id(prefix)
        if top_id is None:
            pending = []
        else:
            pending = [(prefix, '', _directory, None, top_id, None)]
        while pending:
            dirblock = []
            currentdir = pending.pop()
            # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-id, 5-kind
            top_id = currentdir[4]
            if currentdir[0]:
                relroot = currentdir[0] + '/'
            else:
                relroot = ""
            # FIXME: stash the node in pending
            entry = inv.get_entry(top_id)
            if entry.kind == 'directory':
                for name, child in entry.sorted_children():
                    dirblock.append((relroot + name, name, child.kind, None,
                                     child.file_id, child.kind
                                     ))
            yield (currentdir[0], entry.file_id), dirblock
            # push the user specified dirs from dirblock
            for dir in reversed(dirblock):
                if dir[2] == _directory:
                    pending.append(dir)

    def update_feature_flags(self, updated_flags):
        """Update the feature flags for this branch.

        :param updated_flags: Dictionary mapping feature names to necessities
            A necessity can be None to indicate the feature should be removed
        """
        with self.lock_write():
            self._format._update_feature_flags(updated_flags)
            self.control_transport.put_bytes(
                'format', self._format.as_string())

    def _check_for_tree_references(self, iterator):
        """See if directories have become tree-references."""
        blocked_parent_ids = set()
        for path, ie in iterator:
            if ie.parent_id in blocked_parent_ids:
                # This entry was pruned because one of its parents became a
                # TreeReference. If this is a directory, mark it as blocked.
                if ie.kind == 'directory':
                    blocked_parent_ids.add(ie.file_id)
                continue
            if (ie.kind == 'directory' and
                    self._directory_is_tree_reference(path)):
                # This InventoryDirectory needs to be a TreeReference
                ie = inventory.TreeReference(ie.file_id, ie.name, ie.parent_id)
                blocked_parent_ids.add(ie.file_id)
            yield path, ie

    def iter_entries_by_dir(self, specific_files=None):
        """See Tree.iter_entries_by_dir()"""
        # The only trick here is that if we supports_tree_reference then we
        # need to detect if a directory becomes a tree-reference.
        iterator = super(WorkingTree, self).iter_entries_by_dir(
            specific_files=specific_files)
        if not self.supports_tree_reference():
            return iterator
        else:
            return self._check_for_tree_references(iterator)

    def get_canonical_paths(self, paths):
        """Look up canonical paths for multiple items.

        :param paths: A sequence of paths relative to the root of the tree.
        :return: A iterator over paths, with each item the corresponding input
            path adjusted to account for existing elements that match case
            insensitively.
        """
        with self.lock_read():
            if not self.case_sensitive:
                def normalize(x):
                    return x.lower()
            elif sys.platform == 'darwin':
                import unicodedata

                def normalize(x):
                    return unicodedata.normalize('NFC', x)
            else:
                normalize = None
            for path in paths:
                if normalize is None or self.is_versioned(path):
                    yield path
                else:
                    yield get_canonical_path(self, path, normalize)


class WorkingTreeFormatMetaDir(bzrdir.BzrFormat, WorkingTreeFormat):
    """Base class for working trees that live in bzr meta directories."""

    ignore_filename = '.bzrignore'

    def __init__(self):
        WorkingTreeFormat.__init__(self)
        bzrdir.BzrFormat.__init__(self)

    @classmethod
    def find_format_string(klass, controldir):
        """Return format name for the working tree object in controldir."""
        try:
            transport = controldir.get_workingtree_transport(None)
            return transport.get_bytes("format")
        except errors.NoSuchFile:
            raise errors.NoWorkingTree(base=transport.base)

    @classmethod
    def find_format(klass, controldir):
        """Return the format for the working tree object in controldir."""
        format_string = klass.find_format_string(controldir)
        return klass._find_format(format_registry, 'working tree',
                                  format_string)

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        WorkingTreeFormat.check_support_status(
            self, allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade, basedir=basedir)
        bzrdir.BzrFormat.check_support_status(
            self, allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade, basedir=basedir)

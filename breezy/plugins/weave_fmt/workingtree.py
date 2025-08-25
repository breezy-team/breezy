# Copyright (C) 2005-2010 Canonical Ltd
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

"""Weave-era working tree objects."""

from io import BytesIO

from ... import conflicts as _mod_conflicts
from ... import errors, lock
from ... import revision as _mod_revision
from ... import transport as _mod_transport
from ...bzr import conflicts as _mod_bzr_conflicts
from ...bzr import inventory, xml5
from ...bzr import transform as bzr_transform
from ...bzr.workingtree_3 import PreDirStateWorkingTree
from ...mutabletree import MutableTree
from ...transport.local import LocalTransport, file_kind
from ...workingtree import WorkingTreeFormat


def get_conflicted_stem(path):
    """Extract the base filename from a conflict file path.

    Conflict files have special suffixes like .THIS, .OTHER, .BASE etc.
    This function removes those suffixes to get the original filename.

    Args:
        path: File path that may have a conflict suffix

    Returns:
        str: The path without conflict suffix, or None if no suffix found

    Example:
        >>> get_conflicted_stem('file.txt.THIS')
        'file.txt'
        >>> get_conflicted_stem('file.txt')
        None
    """
    for suffix in _mod_bzr_conflicts.CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[: -len(suffix)]


class WorkingTreeFormat2(WorkingTreeFormat):
    """The second working tree format.

    This format modified the hash cache from the format 1 hash cache.
    """

    upgrade_recommended = True

    requires_normalized_unicode_filenames = True

    case_sensitive_filename = "Branch-FoRMaT"

    missing_parent_conflicts = False

    supports_versioned_directories = True

    ignore_filename = ".bzrignore"

    supports_setting_file_ids = True
    """If this format allows setting the file id."""

    def get_format_description(self):
        """Get a human-readable description of this format.

        Returns:
            str: "Working tree format 2"
        """
        return "Working tree format 2"

    def _stub_initialize_on_transport(self, transport, file_mode):
        """Create minimal control files for a remote working tree.

        This is a workaround that ensures remote directories can later be
        updated and dealt with locally, since BzrDirFormat6 and BzrDirFormat5
        cannot represent directories with no working tree. (See bug #43064).

        Creates an empty inventory and pending-merges file.

        Args:
            transport: Transport to create files on
            file_mode: Unix file mode for created files
        """
        sio = BytesIO()
        inv = inventory.Inventory()
        xml5.inventory_serializer_v5.write_inventory(inv, sio, working=True)
        sio.seek(0)
        transport.put_file("inventory", sio, file_mode)
        transport.put_bytes("pending-merges", b"", file_mode)

    def initialize(
        self,
        a_controldir,
        revision_id=None,
        from_branch=None,
        accelerator_tree=None,
        hardlink=False,
    ):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_controldir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_controldir.transport.base)
        branch = from_branch if from_branch is not None else a_controldir.open_branch()
        if revision_id is None:
            revision_id = branch.last_revision()
        with branch.lock_write():
            branch.generate_revision_history(revision_id)
        inv = inventory.Inventory()
        wt = WorkingTree2(
            a_controldir.root_transport.local_abspath("."),
            branch,
            inv,
            _internal=True,
            _format=self,
            _controldir=a_controldir,
            _control_files=branch.control_files,
        )
        basis_tree = branch.repository.revision_tree(revision_id)
        if basis_tree.path2id("") is not None:
            wt.set_root_id(basis_tree.path2id(""))
        # set the parent list and cache the basis tree.
        if _mod_revision.is_null(revision_id):
            parent_trees = []
        else:
            parent_trees = [(revision_id, basis_tree)]
        wt.set_parent_trees(parent_trees)
        bzr_transform.build_tree(basis_tree, wt)
        for hook in MutableTree.hooks["post_build_tree"]:
            hook(wt)
        return wt

    def __init__(self):
        """Initialize the working tree format.

        Sets up format 2 to work with BzrDirFormat6 control directories.
        """
        super().__init__()
        from .bzrdir import BzrDirFormat6

        self._matchingcontroldir = BzrDirFormat6()

    def open(self, a_controldir, _found=False):
        """Return the WorkingTree object for a_controldir.

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_controldir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_controldir.transport.base)
        wt = WorkingTree2(
            a_controldir.root_transport.local_abspath("."),
            _internal=True,
            _format=self,
            _controldir=a_controldir,
            _control_files=a_controldir.open_branch().control_files,
        )
        return wt


class WorkingTree2(PreDirStateWorkingTree):
    """This is the Format 2 working tree.

    This was the first weave based working tree.
     - uses os locks for locking.
     - uses the branch last-revision.
    """

    def __init__(self, basedir, *args, **kwargs):
        """Initialize a format 2 working tree.

        Format 2 working trees require that self._inventory always exists,
        so this constructor ensures the inventory is loaded if not already present.

        Args:
            basedir: Base directory of the working tree
            *args: Additional positional arguments for parent class
            **kwargs: Additional keyword arguments for parent class
        """
        super().__init__(basedir, *args, **kwargs)
        # WorkingTree2 has more of a constraint that self._inventory must
        # exist. Because this is an older format, we don't mind the overhead
        # caused by the extra computation here.

        # Newer WorkingTree's should only have self._inventory set when they
        # have a read lock.
        if self._inventory is None:
            self.read_working_inventory()

    def _get_check_refs(self):
        """Get references needed to check the integrity of this tree.

        Returns:
            list: A list of (ref_type, ref_id) tuples, where ref_type is 'trees'
                and ref_id is the last revision of this tree
        """
        return [("trees", self.last_revision())]

    def lock_tree_write(self):
        """See WorkingTree.lock_tree_write().

        In Format2 WorkingTrees we have a single lock for the branch and tree
        so lock_tree_write() degrades to lock_write().

        :return: An object with an unlock method which will release the lock
            obtained.
        """
        self.branch.lock_write()
        try:
            token = self._control_files.lock_write()
            return lock.LogicalLockResult(self.unlock, token)
        except:
            self.branch.unlock()
            raise

    def unlock(self):
        """Unlock the working tree.

        Since format 2 shares control files with the branch, this reverses
        the locking order used in lock_tree_write(). If this is the last
        lock reference, it also:
        - Performs implementation cleanup
        - Flushes any modified inventory
        - Writes dirty hash cache

        Returns:
            The result of unlocking the control files
        """
        # we share control files:
        if self._control_files._lock_count == 3:
            # do non-implementation specific cleanup
            self._cleanup()
            # _inventory_is_modified is always False during a read lock.
            if self._inventory_is_modified:
                self.flush()
            self._write_hashcache_if_dirty()

        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    def _iter_conflicts(self):
        """Iterate over files in conflict.

        Identifies files that have conflict markers by looking for files
        with conflict suffixes (.THIS, .OTHER, etc.).

        Yields:
            str: Base filenames (without suffixes) of conflicted files
        """
        conflicted = set()
        for path, _file_class, _file_kind, _entry in self.list_files():
            stem = get_conflicted_stem(path)
            if stem is None:
                continue
            if stem not in conflicted:
                conflicted.add(stem)
                yield stem

    def conflicts(self):
        """Get the list of conflicts in the working tree.

        Detects conflicts by looking for files with conflict suffixes.
        Determines whether each conflict is a text conflict (all files exist
        and are regular files) or a contents conflict.

        Returns:
            ConflictList: List of Conflict objects representing current conflicts
        """
        with self.lock_read():
            conflicts = _mod_conflicts.ConflictList()
            for conflicted in self._iter_conflicts():
                text = True
                try:
                    if file_kind(self.abspath(conflicted)) != "file":
                        text = False
                except _mod_transport.NoSuchFile:
                    text = False
                if text is True:
                    for suffix in (".THIS", ".OTHER"):
                        try:
                            kind = file_kind(self.abspath(conflicted + suffix))
                            if kind != "file":
                                text = False
                        except _mod_transport.NoSuchFile:
                            text = False
                        if text is False:
                            break
                ctype = {True: "text conflict", False: "contents conflict"}[text]
                conflicts.append(
                    _mod_bzr_conflicts.Conflict.factory(
                        ctype, path=conflicted, file_id=self.path2id(conflicted)
                    )
                )
            return conflicts

    def set_conflicts(self, arg):
        """Set the list of conflicts.

        Format 2 does not support explicitly setting conflicts - they are
        detected by the presence of conflict marker files.

        Args:
            arg: New conflict list (unused)

        Raises:
            UnsupportedOperation: Always raised as format 2 doesn't support this
        """
        raise errors.UnsupportedOperation(self.set_conflicts, self)

    def add_conflicts(self, arg):
        """Add conflicts to the working tree.

        Format 2 does not support explicitly adding conflicts - they are
        detected by the presence of conflict marker files.

        Args:
            arg: Conflicts to add (unused)

        Raises:
            UnsupportedOperation: Always raised as format 2 doesn't support this
        """
        raise errors.UnsupportedOperation(self.add_conflicts, self)

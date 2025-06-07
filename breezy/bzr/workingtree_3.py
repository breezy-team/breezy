# Copyright (C) 2007-2011 Canonical Ltd
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

"""WorkingTree3 format and implementation."""

import contextlib

from bzrformats import hashcache, inventory

from .. import errors, trace
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..lockdir import LockDir
from ..mutabletree import MutableTree
from ..transport.local import LocalTransport
from . import bzrdir
from . import transform as bzr_transform
from .lockable_files import LockableFiles
from .workingtree import InventoryWorkingTree, WorkingTreeFormatMetaDir


class PreDirStateWorkingTree(InventoryWorkingTree):
    def __init__(self, basedir=".", *args, **kwargs):
        super().__init__(basedir, *args, **kwargs)
        # update the whole cache up front and write to disk if anything changed;
        # in the future we might want to do this more selectively
        # two possible ways offer themselves : in self._unlock, write the cache
        # if needed, or, when the cache sees a change, append it to the hash
        # cache file, and have the parser take the most recent entry for a
        # given path only.
        wt_trans = self.controldir.get_workingtree_transport(None)
        cache_filename = wt_trans.local_abspath("stat-cache")
        self._hashcache = hashcache.HashCache(
            basedir,
            cache_filename,
            self.controldir._get_file_mode(),
            self._content_filter_stack_provider(),
        )
        hc = self._hashcache
        hc.read()
        # is this scan needed ? it makes things kinda slow.
        # hc.scan()

        if hc.needs_write:
            trace.mutter("write hc")
            hc.write()

    def _write_hashcache_if_dirty(self):
        """Write out the hashcache if it is dirty."""
        if self._hashcache.needs_write:
            try:
                self._hashcache.write()
            except PermissionError as e:
                # TODO: jam 20061219 Should this be a warning? A single line
                #       warning might be sufficient to let the user know what
                #       is going on.
                trace.mutter(
                    "Could not write hashcache for %s\nError: %s",
                    self._hashcache.cache_file_name(),
                    e.filename,
                )

    def get_file_sha1(self, path, stat_value=None):
        with self.lock_read():
            # To make sure NoSuchFile gets raised..
            if not self.is_versioned(path):
                raise _mod_transport.NoSuchFile(path)
            return self._hashcache.get_sha1(path, stat_value)


class WorkingTree3(PreDirStateWorkingTree):
    """This is the Format 3 working tree.

    This differs from the base WorkingTree by:
     - having its own file lock
     - having its own last-revision property.

    This is new in bzr 0.8
    """

    def _last_revision(self):
        """See Mutable.last_revision."""
        with self.lock_read():
            try:
                return self._transport.get_bytes("last-revision")
            except _mod_transport.NoSuchFile:
                return _mod_revision.NULL_REVISION

    def _change_last_revision(self, revision_id):
        """See WorkingTree._change_last_revision."""
        if revision_id is None or revision_id == _mod_revision.NULL_REVISION:
            with contextlib.suppress(_mod_transport.NoSuchFile):
                self._transport.delete("last-revision")
            return False
        else:
            self._transport.put_bytes(
                "last-revision", revision_id, mode=self.controldir._get_file_mode()
            )
            return True

    def _get_check_refs(self):
        """Return the references needed to perform a check of this tree."""
        return [("trees", self.last_revision())]

    def unlock(self):
        if self._control_files._lock_count == 1:
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


class WorkingTreeFormat3(WorkingTreeFormatMetaDir):
    """The second working tree format updated to record a format marker.

    This format:
        - exists within a metadir controlling .bzr
        - includes an explicit version marker for the workingtree control
          files, separate from the ControlDir format
        - modifies the hash cache format
        - is new in bzr 0.8
        - uses a LockDir to guard access for writes.
    """

    upgrade_recommended = True

    missing_parent_conflicts = True

    supports_versioned_directories = True

    @classmethod
    def get_format_string(cls):
        """See WorkingTreeFormat.get_format_string()."""
        return b"Bazaar-NG Working Tree format 3"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 3"

    _tree_class = WorkingTree3

    def __get_matchingcontroldir(self):
        return bzrdir.BzrDirMetaFormat1()

    _matchingcontroldir = property(__get_matchingcontroldir)

    def _open_control_files(self, a_controldir):
        transport = a_controldir.get_workingtree_transport(None)
        return LockableFiles(transport, "lock", LockDir)

    def initialize(
        self,
        a_controldir,
        revision_id=None,
        from_branch=None,
        accelerator_tree=None,
        hardlink=False,
    ):
        """See WorkingTreeFormat.initialize().

        :param revision_id: if supplied, create a working tree at a different
            revision than the branch is at.
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        :param hardlink: If true, hard-link files from accelerator_tree,
            where possible.
        """
        if not isinstance(a_controldir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_controldir.transport.base)
        transport = a_controldir.get_workingtree_transport(self)
        control_files = self._open_control_files(a_controldir)
        control_files.create_lock()
        control_files.lock_write()
        transport.put_bytes(
            "format", self.as_string(), mode=a_controldir._get_file_mode()
        )
        branch = from_branch if from_branch is not None else a_controldir.open_branch()
        if revision_id is None:
            revision_id = branch.last_revision()
        # WorkingTree3 can handle an inventory which has a unique root id.
        # as of bzr 0.12. However, bzr 0.11 and earlier fail to handle
        # those trees. And because there isn't a format bump inbetween, we
        # are maintaining compatibility with older clients.
        # inv = Inventory(root_id=gen_root_id())
        inv = self._initial_inventory()
        wt = self._tree_class(
            a_controldir.root_transport.local_abspath("."),
            branch,
            inv,
            _internal=True,
            _format=self,
            _controldir=a_controldir,
            _control_files=control_files,
        )
        wt.lock_tree_write()
        try:
            basis_tree = branch.repository.revision_tree(revision_id)
            # only set an explicit root id if there is one to set.
            if basis_tree.path2id("") is not None:
                wt.set_root_id(basis_tree.path2id(""))
            if revision_id == _mod_revision.NULL_REVISION:
                wt.set_parent_trees([])
            else:
                wt.set_parent_trees([(revision_id, basis_tree)])
            bzr_transform.build_tree(basis_tree, wt)
            for hook in MutableTree.hooks["post_build_tree"]:
                hook(wt)
        finally:
            # Unlock in this order so that the unlock-triggers-flush in
            # WorkingTree is given a chance to fire.
            control_files.unlock()
            wt.unlock()
        return wt

    def _initial_inventory(self):
        return inventory.Inventory()

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
        wt = self._open(a_controldir, self._open_control_files(a_controldir))
        return wt

    def _open(self, a_controldir, control_files):
        """Open the tree itself.

        :param a_controldir: the dir for the tree.
        :param control_files: the control files for the tree.
        """
        return self._tree_class(
            a_controldir.root_transport.local_abspath("."),
            _internal=True,
            _format=self,
            _controldir=a_controldir,
            _control_files=control_files,
        )

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

from __future__ import absolute_import

from cStringIO import StringIO

from bzrlib import (
    conflicts as _mod_conflicts,
    errors,
    inventory,
    osutils,
    revision as _mod_revision,
    transform,
    xml5,
    )
from bzrlib.decorators import needs_read_lock
from bzrlib.mutabletree import MutableTree
from bzrlib.transport.local import LocalTransport
from bzrlib.workingtree import (
    WorkingTreeFormat,
    )
from bzrlib.workingtree_3 import (
    PreDirStateWorkingTree,
    )


def get_conflicted_stem(path):
    for suffix in _mod_conflicts.CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]


class WorkingTreeFormat2(WorkingTreeFormat):
    """The second working tree format.

    This format modified the hash cache from the format 1 hash cache.
    """

    upgrade_recommended = True

    requires_normalized_unicode_filenames = True

    case_sensitive_filename = "Branch-FoRMaT"

    missing_parent_conflicts = False

    supports_versioned_directories = True

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 2"

    def _stub_initialize_on_transport(self, transport, file_mode):
        """Workaround: create control files for a remote working tree.

        This ensures that it can later be updated and dealt with locally,
        since BzrDirFormat6 and BzrDirFormat5 cannot represent dirs with
        no working tree.  (See bug #43064).
        """
        sio = StringIO()
        inv = inventory.Inventory()
        xml5.serializer_v5.write_inventory(inv, sio, working=True)
        sio.seek(0)
        transport.put_file('inventory', sio, file_mode)
        transport.put_bytes('pending-merges', '', file_mode)

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        if from_branch is not None:
            branch = from_branch
        else:
            branch = a_bzrdir.open_branch()
        if revision_id is None:
            revision_id = _mod_revision.ensure_null(branch.last_revision())
        branch.lock_write()
        try:
            branch.generate_revision_history(revision_id)
        finally:
            branch.unlock()
        inv = inventory.Inventory()
        wt = WorkingTree2(a_bzrdir.root_transport.local_abspath('.'),
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir,
                         _control_files=branch.control_files)
        basis_tree = branch.repository.revision_tree(revision_id)
        if basis_tree.get_root_id() is not None:
            wt.set_root_id(basis_tree.get_root_id())
        # set the parent list and cache the basis tree.
        if _mod_revision.is_null(revision_id):
            parent_trees = []
        else:
            parent_trees = [(revision_id, basis_tree)]
        wt.set_parent_trees(parent_trees)
        transform.build_tree(basis_tree, wt)
        for hook in MutableTree.hooks['post_build_tree']:
            hook(wt)
        return wt

    def __init__(self):
        super(WorkingTreeFormat2, self).__init__()
        from bzrlib.plugins.weave_fmt.bzrdir import BzrDirFormat6
        self._matchingbzrdir = BzrDirFormat6()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        wt = WorkingTree2(a_bzrdir.root_transport.local_abspath('.'),
                           _internal=True,
                           _format=self,
                           _bzrdir=a_bzrdir,
                           _control_files=a_bzrdir.open_branch().control_files)
        return wt


class WorkingTree2(PreDirStateWorkingTree):
    """This is the Format 2 working tree.

    This was the first weave based working tree.
     - uses os locks for locking.
     - uses the branch last-revision.
    """

    def __init__(self, basedir, *args, **kwargs):
        super(WorkingTree2, self).__init__(basedir, *args, **kwargs)
        # WorkingTree2 has more of a constraint that self._inventory must
        # exist. Because this is an older format, we don't mind the overhead
        # caused by the extra computation here.

        # Newer WorkingTree's should only have self._inventory set when they
        # have a read lock.
        if self._inventory is None:
            self.read_working_inventory()

    def _get_check_refs(self):
        """Return the references needed to perform a check of this tree."""
        return [('trees', self.last_revision())]


    def lock_tree_write(self):
        """See WorkingTree.lock_tree_write().

        In Format2 WorkingTrees we have a single lock for the branch and tree
        so lock_tree_write() degrades to lock_write().

        :return: An object with an unlock method which will release the lock
            obtained.
        """
        self.branch.lock_write()
        try:
            self._control_files.lock_write()
            return self
        except:
            self.branch.unlock()
            raise

    def unlock(self):
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
        conflicted = set()
        for info in self.list_files():
            path = info[0]
            stem = get_conflicted_stem(path)
            if stem is None:
                continue
            if stem not in conflicted:
                conflicted.add(stem)
                yield stem

    @needs_read_lock
    def conflicts(self):
        conflicts = _mod_conflicts.ConflictList()
        for conflicted in self._iter_conflicts():
            text = True
            try:
                if osutils.file_kind(self.abspath(conflicted)) != "file":
                    text = False
            except errors.NoSuchFile:
                text = False
            if text is True:
                for suffix in ('.THIS', '.OTHER'):
                    try:
                        kind = osutils.file_kind(self.abspath(conflicted+suffix))
                        if kind != "file":
                            text = False
                    except errors.NoSuchFile:
                        text = False
                    if text == False:
                        break
            ctype = {True: 'text conflict', False: 'contents conflict'}[text]
            conflicts.append(_mod_conflicts.Conflict.factory(ctype,
                             path=conflicted,
                             file_id=self.path2id(conflicted)))
        return conflicts

    def set_conflicts(self, arg):
        raise errors.UnsupportedOperation(self.set_conflicts, self)

    def add_conflicts(self, arg):
        raise errors.UnsupportedOperation(self.add_conflicts, self)

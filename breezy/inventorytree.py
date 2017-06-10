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

"""Tree classes, representing directory at point in time.
"""

from __future__ import absolute_import

import os

from . import (
    errors,
    inventory,
    osutils,
    )
from .decorators import needs_read_lock
from .sixish import (
    viewvalues,
    )
from .tree import Tree


class InventoryTree(Tree):
    """A tree that relies on an inventory for its metadata.

    Trees contain an `Inventory` object, and also know how to retrieve
    file texts mentioned in the inventory, either from a working
    directory or from a store.

    It is possible for trees to contain files that are not described
    in their inventory or vice versa; for this use `filenames()`.

    Subclasses should set the _inventory attribute, which is considered
    private to external API users.
    """

    def get_canonical_inventory_paths(self, paths):
        """Like get_canonical_inventory_path() but works on multiple items.

        :param paths: A sequence of paths relative to the root of the tree.
        :return: A list of paths, with each item the corresponding input path
        adjusted to account for existing elements that match case
        insensitively.
        """
        return list(self._yield_canonical_inventory_paths(paths))

    def get_canonical_inventory_path(self, path):
        """Returns the first inventory item that case-insensitively matches path.

        If a path matches exactly, it is returned. If no path matches exactly
        but more than one path matches case-insensitively, it is implementation
        defined which is returned.

        If no path matches case-insensitively, the input path is returned, but
        with as many path entries that do exist changed to their canonical
        form.

        If you need to resolve many names from the same tree, you should
        use get_canonical_inventory_paths() to avoid O(N) behaviour.

        :param path: A paths relative to the root of the tree.
        :return: The input path adjusted to account for existing elements
        that match case insensitively.
        """
        return next(self._yield_canonical_inventory_paths([path]))

    def _yield_canonical_inventory_paths(self, paths):
        for path in paths:
            # First, if the path as specified exists exactly, just use it.
            if self.path2id(path) is not None:
                yield path
                continue
            # go walkin...
            cur_id = self.get_root_id()
            cur_path = ''
            bit_iter = iter(path.split("/"))
            for elt in bit_iter:
                lelt = elt.lower()
                new_path = None
                for child in self.iter_children(cur_id):
                    try:
                        # XXX: it seem like if the child is known to be in the
                        # tree, we shouldn't need to go from its id back to
                        # its path -- mbp 2010-02-11
                        #
                        # XXX: it seems like we could be more efficient
                        # by just directly looking up the original name and
                        # only then searching all children; also by not
                        # chopping paths so much. -- mbp 2010-02-11
                        child_base = os.path.basename(self.id2path(child))
                        if (child_base == elt):
                            # if we found an exact match, we can stop now; if
                            # we found an approximate match we need to keep
                            # searching because there might be an exact match
                            # later.  
                            cur_id = child
                            new_path = osutils.pathjoin(cur_path, child_base)
                            break
                        elif child_base.lower() == lelt:
                            cur_id = child
                            new_path = osutils.pathjoin(cur_path, child_base)
                    except errors.NoSuchId:
                        # before a change is committed we can see this error...
                        continue
                if new_path:
                    cur_path = new_path
                else:
                    # got to the end of this directory and no entries matched.
                    # Return what matched so far, plus the rest as specified.
                    cur_path = osutils.pathjoin(cur_path, elt, *list(bit_iter))
                    break
            yield cur_path
        # all done.

    def _get_root_inventory(self):
        return self._inventory

    root_inventory = property(_get_root_inventory,
        doc="Root inventory of this tree")

    def _unpack_file_id(self, file_id):
        """Find the inventory and inventory file id for a tree file id.

        :param file_id: The tree file id, as bytestring or tuple
        :return: Inventory and inventory file id
        """
        if isinstance(file_id, tuple):
            if len(file_id) != 1:
                raise ValueError("nested trees not yet supported: %r" % file_id)
            file_id = file_id[0]
        return self.root_inventory, file_id

    @needs_read_lock
    def path2id(self, path):
        """Return the id for path in this tree."""
        return self._path2inv_file_id(path)[1]

    def _path2inv_file_id(self, path):
        """Lookup a inventory and inventory file id by path.

        :param path: Path to look up
        :return: tuple with inventory and inventory file id
        """
        # FIXME: Support nested trees
        return self.root_inventory, self.root_inventory.path2id(path)

    def id2path(self, file_id):
        """Return the path for a file id.

        :raises NoSuchId:
        """
        inventory, file_id = self._unpack_file_id(file_id)
        return inventory.id2path(file_id)

    def has_id(self, file_id):
        inventory, file_id = self._unpack_file_id(file_id)
        return inventory.has_id(file_id)

    def has_or_had_id(self, file_id):
        inventory, file_id = self._unpack_file_id(file_id)
        return inventory.has_id(file_id)

    def all_file_ids(self):
        return {entry.file_id for path, entry in self.iter_entries_by_dir()}

    def filter_unversioned_files(self, paths):
        """Filter out paths that are versioned.

        :return: set of paths.
        """
        # NB: we specifically *don't* call self.has_filename, because for
        # WorkingTrees that can indicate files that exist on disk but that
        # are not versioned.
        return set((p for p in paths if self.path2id(p) is None))

    @needs_read_lock
    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple.
        The order that they are yielded is:

        See Tree.iter_entries_by_dir for details.

        :param yield_parents: If True, yield the parents from the root leading
            down to specific_file_ids that have been requested. This has no
            impact if specific_file_ids is None.
        """
        if specific_file_ids is None:
            inventory_file_ids = None
        else:
            inventory_file_ids = []
            for tree_file_id in specific_file_ids:
                inventory, inv_file_id = self._unpack_file_id(tree_file_id)
                if not inventory is self.root_inventory: # for now
                    raise AssertionError("%r != %r" % (
                        inventory, self.root_inventory))
                inventory_file_ids.append(inv_file_id)
        # FIXME: Handle nested trees
        return self.root_inventory.iter_entries_by_dir(
            specific_file_ids=inventory_file_ids, yield_parents=yield_parents)

    @needs_read_lock
    def iter_child_entries(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        return iter(viewvalues(inv[inv_file_id].children))

    def iter_children(self, file_id, path=None):
        """See Tree.iter_children."""
        entry = self.iter_entries_by_dir([file_id]).next()[1]
        for child in viewvalues(getattr(entry, 'children', {})):
            yield child.file_id




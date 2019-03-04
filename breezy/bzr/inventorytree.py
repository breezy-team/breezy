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
import re

from .. import (
    errors,
    lazy_import,
    osutils,
    revision,
    )
from ..mutabletree import (
    MutableTree,
    )
from ..revisiontree import (
    RevisionTree,
    )
lazy_import.lazy_import(globals(), """
from breezy import (
    add,
    controldir,
    trace,
    transport as _mod_transport,
    )
from breezy.bzr import (
    inventory as _mod_inventory,
    )
""")
from ..sixish import (
    viewvalues,
    )
from ..tree import (
    FileTimestampUnavailable,
    InterTree,
    Tree,
    )


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
                raise ValueError(
                    "nested trees not yet supported: %r" % file_id)
            file_id = file_id[0]
        return self.root_inventory, file_id

    def find_related_paths_across_trees(self, paths, trees=[],
                                        require_versioned=True):
        """Find related paths in tree corresponding to specified filenames in any
        of `lookup_trees`.

        All matches in all trees will be used, and all children of matched
        directories will be used.

        :param paths: The filenames to find related paths for (if None, returns
            None)
        :param trees: The trees to find file_ids within
        :param require_versioned: if true, all specified filenames must occur in
            at least one tree.
        :return: a set of paths for the specified filenames and their children
            in `tree`
        """
        if paths is None:
            return None
        file_ids = self.paths2ids(
            paths, trees, require_versioned=require_versioned)
        ret = set()
        for file_id in file_ids:
            try:
                ret.add(self.id2path(file_id))
            except errors.NoSuchId:
                pass
        return ret

    def paths2ids(self, paths, trees=[], require_versioned=True):
        """Return all the ids that can be reached by walking from paths.

        Each path is looked up in this tree and any extras provided in
        trees, and this is repeated recursively: the children in an extra tree
        of a directory that has been renamed under a provided path in this tree
        are all returned, even if none exist under a provided path in this
        tree, and vice versa.

        :param paths: An iterable of paths to start converting to ids from.
            Alternatively, if paths is None, no ids should be calculated and None
            will be returned. This is offered to make calling the api unconditional
            for code that *might* take a list of files.
        :param trees: Additional trees to consider.
        :param require_versioned: If False, do not raise NotVersionedError if
            an element of paths is not versioned in this tree and all of trees.
        """
        return find_ids_across_trees(paths, [self] + list(trees), require_versioned)

    def path2id(self, path):
        """Return the id for path in this tree."""
        with self.lock_read():
            return self._path2inv_file_id(path)[1]

    def _path2ie(self, path):
        """Lookup an inventory entry by path.

        :param path: Path to look up
        :return: InventoryEntry
        """
        ie = self.root_inventory.get_entry_by_path(path)
        if ie is None:
            raise errors.NoSuchFile(path)
        return ie

    def _path2inv_file_id(self, path):
        """Lookup a inventory and inventory file id by path.

        :param path: Path to look up
        :return: tuple with inventory and inventory file id
        """
        # FIXME: Support nested trees
        inv = self.root_inventory
        inv_file_id = self.root_inventory.path2id(path)
        return inv, inv_file_id

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

    def all_versioned_paths(self):
        return {path for path, entry in self.iter_entries_by_dir()}

    def iter_entries_by_dir(self, specific_files=None):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple.
        The order that they are yielded is:

        See Tree.iter_entries_by_dir for details.
        """
        with self.lock_read():
            if specific_files is not None:
                inventory_file_ids = []
                for path in specific_files:
                    inventory, inv_file_id = self._path2inv_file_id(path)
                    if inventory is not self.root_inventory:  # for now
                        raise AssertionError("%r != %r" % (
                            inventory, self.root_inventory))
                    inventory_file_ids.append(inv_file_id)
            else:
                inventory_file_ids = None
            # FIXME: Handle nested trees
            return self.root_inventory.iter_entries_by_dir(
                specific_file_ids=inventory_file_ids)

    def iter_child_entries(self, path):
        with self.lock_read():
            ie = self._path2ie(path)
            if ie.kind != 'directory':
                raise errors.NotADirectory(path)
            return iter(viewvalues(ie.children))

    def _get_plan_merge_data(self, file_id, other, base):
        from . import versionedfile
        vf = versionedfile._PlanMergeVersionedFile(file_id)
        last_revision_a = self._get_file_revision(
            self.id2path(file_id), file_id, vf, b'this:')
        last_revision_b = other._get_file_revision(
            other.id2path(file_id), file_id, vf, b'other:')
        if base is None:
            last_revision_base = None
        else:
            last_revision_base = base._get_file_revision(
                base.id2path(file_id), file_id, vf, b'base:')
        return vf, last_revision_a, last_revision_b, last_revision_base

    def plan_file_merge(self, file_id, other, base=None):
        """Generate a merge plan based on annotations.

        If the file contains uncommitted changes in this tree, they will be
        attributed to the 'current:' pseudo-revision.  If the file contains
        uncommitted changes in the other tree, they will be assigned to the
        'other:' pseudo-revision.
        """
        data = self._get_plan_merge_data(file_id, other, base)
        vf, last_revision_a, last_revision_b, last_revision_base = data
        return vf.plan_merge(last_revision_a, last_revision_b,
                             last_revision_base)

    def plan_file_lca_merge(self, file_id, other, base=None):
        """Generate a merge plan based lca-newness.

        If the file contains uncommitted changes in this tree, they will be
        attributed to the 'current:' pseudo-revision.  If the file contains
        uncommitted changes in the other tree, they will be assigned to the
        'other:' pseudo-revision.
        """
        data = self._get_plan_merge_data(file_id, other, base)
        vf, last_revision_a, last_revision_b, last_revision_base = data
        return vf.plan_lca_merge(last_revision_a, last_revision_b,
                                 last_revision_base)

    def _get_file_revision(self, path, file_id, vf, tree_revision):
        """Ensure that file_id, tree_revision is in vf to plan the merge."""
        if getattr(self, '_repository', None) is None:
            last_revision = tree_revision
            parent_keys = [
                (file_id, t.get_file_revision(path)) for t in
                self._iter_parent_trees()]
            vf.add_lines((file_id, last_revision), parent_keys,
                         self.get_file_lines(path))
            repo = self.branch.repository
            base_vf = repo.texts
        else:
            last_revision = self.get_file_revision(path)
            base_vf = self._repository.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return last_revision


def find_ids_across_trees(filenames, trees, require_versioned=True):
    """Find the ids corresponding to specified filenames.

    All matches in all trees will be used, and all children of matched
    directories will be used.

    :param filenames: The filenames to find file_ids for (if None, returns
        None)
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
        at least one tree.
    :return: a set of file ids for the specified filenames and their children.
    """
    if not filenames:
        return None
    specified_path_ids = _find_ids_across_trees(filenames, trees,
                                                require_versioned)
    return _find_children_across_trees(specified_path_ids, trees)


def _find_ids_across_trees(filenames, trees, require_versioned):
    """Find the ids corresponding to specified filenames.

    All matches in all trees will be used, but subdirectories are not scanned.

    :param filenames: The filenames to find file_ids for
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
        at least one tree.
    :return: a set of file ids for the specified filenames
    """
    not_versioned = []
    interesting_ids = set()
    for tree_path in filenames:
        not_found = True
        for tree in trees:
            file_id = tree.path2id(tree_path)
            if file_id is not None:
                interesting_ids.add(file_id)
                not_found = False
        if not_found:
            not_versioned.append(tree_path)
    if len(not_versioned) > 0 and require_versioned:
        raise errors.PathsNotVersionedError(not_versioned)
    return interesting_ids


def _find_children_across_trees(specified_ids, trees):
    """Return a set including specified ids and their children.

    All matches in all trees will be used.

    :param trees: The trees to find file_ids within
    :return: a set containing all specified ids and their children
    """
    interesting_ids = set(specified_ids)
    pending = interesting_ids
    # now handle children of interesting ids
    # we loop so that we handle all children of each id in both trees
    while len(pending) > 0:
        new_pending = set()
        for file_id in pending:
            for tree in trees:
                try:
                    path = tree.id2path(file_id)
                except errors.NoSuchId:
                    continue
                try:
                    for child in tree.iter_child_entries(path):
                        if child.file_id not in interesting_ids:
                            new_pending.add(child.file_id)
                except errors.NotADirectory:
                    pass
        interesting_ids.update(new_pending)
        pending = new_pending
    return interesting_ids


class MutableInventoryTree(MutableTree, InventoryTree):

    def apply_inventory_delta(self, changes):
        """Apply changes to the inventory as an atomic operation.

        :param changes: An inventory delta to apply to the working tree's
            inventory.
        :return None:
        :seealso Inventory.apply_delta: For details on the changes parameter.
        """
        with self.lock_tree_write():
            self.flush()
            inv = self.root_inventory
            inv.apply_delta(changes)
            self._write_inventory(inv)

    def _fix_case_of_inventory_path(self, path):
        """If our tree isn't case sensitive, return the canonical path"""
        if not self.case_sensitive:
            path = self.get_canonical_path(path)
        return path

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        """Version file_list, optionally recursing into directories.

        This is designed more towards DWIM for humans than API clarity.
        For the specific behaviour see the help for cmd_add().

        :param file_list: List of zero or more paths.  *NB: these are
            interpreted relative to the process cwd, not relative to the
            tree.*  (Add and most other tree methods use tree-relative
            paths.)
        :param action: A reporter to be called with the inventory, parent_ie,
            path and kind of the path being added. It may return a file_id if
            a specific one should be used.
        :param save: Save the inventory after completing the adds. If False
            this provides dry-run functionality by doing the add and not saving
            the inventory.
        :return: A tuple - files_added, ignored_files. files_added is the count
            of added files, and ignored_files is a dict mapping files that were
            ignored to the rule that caused them to be ignored.
        """
        with self.lock_tree_write():
            # Not all mutable trees can have conflicts
            if getattr(self, 'conflicts', None) is not None:
                # Collect all related files without checking whether they exist or
                # are versioned. It's cheaper to do that once for all conflicts
                # than trying to find the relevant conflict for each added file.
                conflicts_related = set()
                for c in self.conflicts():
                    conflicts_related.update(c.associated_filenames())
            else:
                conflicts_related = None
            adder = _SmartAddHelper(self, action, conflicts_related)
            adder.add(file_list, recurse=recurse)
            if save:
                invdelta = adder.get_inventory_delta()
                self.apply_inventory_delta(invdelta)
            return adder.added, adder.ignored

    def update_basis_by_delta(self, new_revid, delta):
        """Update the parents of this tree after a commit.

        This gives the tree one parent, with revision id new_revid. The
        inventory delta is applied to the current basis tree to generate the
        inventory for the parent new_revid, and all other parent trees are
        discarded.

        All the changes in the delta should be changes synchronising the basis
        tree with some or all of the working tree, with a change to a directory
        requiring that its contents have been recursively included. That is,
        this is not a general purpose tree modification routine, but a helper
        for commit which is not required to handle situations that do not arise
        outside of commit.

        See the inventory developers documentation for the theory behind
        inventory deltas.

        :param new_revid: The new revision id for the trees parent.
        :param delta: An inventory delta (see apply_inventory_delta) describing
            the changes from the current left most parent revision to new_revid.
        """
        # if the tree is updated by a pull to the branch, as happens in
        # WorkingTree2, when there was no separation between branch and tree,
        # then just clear merges, efficiency is not a concern for now as this
        # is legacy environments only, and they are slow regardless.
        if self.last_revision() == new_revid:
            self.set_parent_ids([new_revid])
            return
        # generic implementation based on Inventory manipulation. See
        # WorkingTree classes for optimised versions for specific format trees.
        basis = self.basis_tree()
        with basis.lock_read():
            # TODO: Consider re-evaluating the need for this with CHKInventory
            # we don't strictly need to mutate an inventory for this
            # it only makes sense when apply_delta is cheaper than get_inventory()
            inventory = _mod_inventory.mutable_inventory_from_tree(basis)
        inventory.apply_delta(delta)
        rev_tree = InventoryRevisionTree(self.branch.repository,
                                         inventory, new_revid)
        self.set_parent_trees([(new_revid, rev_tree)])


class _SmartAddHelper(object):
    """Helper for MutableTree.smart_add."""

    def get_inventory_delta(self):
        # GZ 2016-06-05: Returning view would probably be fine but currently
        # Inventory.apply_delta is documented as requiring a list of changes.
        return list(viewvalues(self._invdelta))

    def _get_ie(self, inv_path):
        """Retrieve the most up to date inventory entry for a path.

        :param inv_path: Normalized inventory path
        :return: Inventory entry (with possibly invalid .children for
            directories)
        """
        entry = self._invdelta.get(inv_path)
        if entry is not None:
            return entry[3]
        # Find a 'best fit' match if the filesystem is case-insensitive
        inv_path = self.tree._fix_case_of_inventory_path(inv_path)
        try:
            return next(self.tree.iter_entries_by_dir(
                specific_files=[inv_path]))[1]
        except StopIteration:
            return None

    def _convert_to_directory(self, this_ie, inv_path):
        """Convert an entry to a directory.

        :param this_ie: Inventory entry
        :param inv_path: Normalized path for the inventory entry
        :return: The new inventory entry
        """
        # Same as in _add_one below, if the inventory doesn't
        # think this is a directory, update the inventory
        this_ie = _mod_inventory.InventoryDirectory(
            this_ie.file_id, this_ie.name, this_ie.parent_id)
        self._invdelta[inv_path] = (inv_path, inv_path, this_ie.file_id,
                                    this_ie)
        return this_ie

    def _add_one_and_parent(self, parent_ie, path, kind, inv_path):
        """Add a new entry to the inventory and automatically add unversioned parents.

        :param parent_ie: Parent inventory entry if known, or None.  If
            None, the parent is looked up by name and used if present, otherwise it
            is recursively added.
        :param path: Filesystem path to add
        :param kind: Kind of new entry (file, directory, etc)
        :param inv_path: Inventory path
        :return: Inventory entry for path and a list of paths which have been added.
        """
        # Nothing to do if path is already versioned.
        # This is safe from infinite recursion because the tree root is
        # always versioned.
        inv_dirname = osutils.dirname(inv_path)
        dirname, basename = osutils.split(path)
        if parent_ie is None:
            # slower but does not need parent_ie
            this_ie = self._get_ie(inv_path)
            if this_ie is not None:
                return this_ie
            # its really not there : add the parent
            # note that the dirname use leads to some extra str copying etc but as
            # there are a limited number of dirs we can be nested under, it should
            # generally find it very fast and not recurse after that.
            parent_ie = self._add_one_and_parent(None,
                                                 dirname, 'directory',
                                                 inv_dirname)
        # if the parent exists, but isn't a directory, we have to do the
        # kind change now -- really the inventory shouldn't pretend to know
        # the kind of wt files, but it does.
        if parent_ie.kind != 'directory':
            # nb: this relies on someone else checking that the path we're using
            # doesn't contain symlinks.
            parent_ie = self._convert_to_directory(parent_ie, inv_dirname)
        file_id = self.action(self.tree, parent_ie, path, kind)
        entry = _mod_inventory.make_entry(kind, basename, parent_ie.file_id,
                                          file_id=file_id)
        self._invdelta[inv_path] = (None, inv_path, entry.file_id, entry)
        self.added.append(inv_path)
        return entry

    def _gather_dirs_to_add(self, user_dirs):
        # only walk the minimal parents needed: we have user_dirs to override
        # ignores.
        prev_dir = None

        is_inside = osutils.is_inside_or_parent_of_any
        for path in sorted(user_dirs):
            if (prev_dir is None or not is_inside([prev_dir], path)):
                inv_path, this_ie = user_dirs[path]
                yield (path, inv_path, this_ie, None)
            prev_dir = path

    def __init__(self, tree, action, conflicts_related=None):
        self.tree = tree
        if action is None:
            self.action = add.AddAction()
        else:
            self.action = action
        self._invdelta = {}
        self.added = []
        self.ignored = {}
        if conflicts_related is None:
            self.conflicts_related = frozenset()
        else:
            self.conflicts_related = conflicts_related

    def add(self, file_list, recurse=True):
        if not file_list:
            # no paths supplied: add the entire tree.
            # FIXME: this assumes we are running in a working tree subdir :-/
            # -- vila 20100208
            file_list = [u'.']

        # expand any symlinks in the directory part, while leaving the
        # filename alone
        # only expanding if symlinks are supported avoids windows path bugs
        if osutils.has_symlinks():
            file_list = list(map(osutils.normalizepath, file_list))

        user_dirs = {}
        # validate user file paths and convert all paths to tree
        # relative : it's cheaper to make a tree relative path an abspath
        # than to convert an abspath to tree relative, and it's cheaper to
        # perform the canonicalization in bulk.
        for filepath in osutils.canonical_relpaths(self.tree.basedir, file_list):
            # validate user parameters. Our recursive code avoids adding new
            # files that need such validation
            if self.tree.is_control_filename(filepath):
                raise errors.ForbiddenControlFileError(filename=filepath)

            abspath = self.tree.abspath(filepath)
            kind = osutils.file_kind(abspath)
            # ensure the named path is added, so that ignore rules in the later
            # directory walk dont skip it.
            # we dont have a parent ie known yet.: use the relatively slower
            # inventory probing method
            inv_path, _ = osutils.normalized_filename(filepath)
            this_ie = self._get_ie(inv_path)
            if this_ie is None:
                this_ie = self._add_one_and_parent(
                    None, filepath, kind, inv_path)
            if kind == 'directory':
                # schedule the dir for scanning
                user_dirs[filepath] = (inv_path, this_ie)

        if not recurse:
            # no need to walk any directories at all.
            return

        things_to_add = list(self._gather_dirs_to_add(user_dirs))

        illegalpath_re = re.compile(r'[\r\n]')
        for directory, inv_path, this_ie, parent_ie in things_to_add:
            # directory is tree-relative
            abspath = self.tree.abspath(directory)

            # get the contents of this directory.

            # find the kind of the path being added, and save stat_value
            # for reuse
            stat_value = None
            if this_ie is None:
                stat_value = osutils.file_stat(abspath)
                kind = osutils.file_kind_from_stat_mode(stat_value.st_mode)
            else:
                kind = this_ie.kind

            # allow AddAction to skip this file
            if self.action.skip_file(self.tree, abspath, kind, stat_value):
                continue
            if not _mod_inventory.InventoryEntry.versionable_kind(kind):
                trace.warning("skipping %s (can't add file of kind '%s')",
                              abspath, kind)
                continue
            if illegalpath_re.search(directory):
                trace.warning("skipping %r (contains \\n or \\r)" % abspath)
                continue
            if directory in self.conflicts_related:
                # If the file looks like one generated for a conflict, don't
                # add it.
                trace.warning(
                    'skipping %s (generated to help resolve conflicts)',
                    abspath)
                continue

            if kind == 'directory' and directory != '':
                try:
                    transport = _mod_transport.get_transport_from_path(abspath)
                    controldir.ControlDirFormat.find_format(transport)
                    sub_tree = True
                except errors.NotBranchError:
                    sub_tree = False
                except errors.UnsupportedFormatError:
                    sub_tree = True
            else:
                sub_tree = False

            if this_ie is not None:
                pass
            elif sub_tree:
                # XXX: This is wrong; people *might* reasonably be trying to
                # add subtrees as subtrees.  This should probably only be done
                # in formats which can represent subtrees, and even then
                # perhaps only when the user asked to add subtrees.  At the
                # moment you can add them specially through 'join --reference',
                # which is perhaps reasonable: adding a new reference is a
                # special operation and can have a special behaviour.  mbp
                # 20070306
                trace.warning("skipping nested tree %r", abspath)
            else:
                this_ie = self._add_one_and_parent(parent_ie, directory, kind,
                                                   inv_path)

            if kind == 'directory' and not sub_tree:
                if this_ie.kind != 'directory':
                    this_ie = self._convert_to_directory(this_ie, inv_path)

                for subf in sorted(os.listdir(abspath)):
                    inv_f, _ = osutils.normalized_filename(subf)
                    # here we could use TreeDirectory rather than
                    # string concatenation.
                    subp = osutils.pathjoin(directory, subf)
                    # TODO: is_control_filename is very slow. Make it faster.
                    # TreeDirectory.is_control_filename could also make this
                    # faster - its impossible for a non root dir to have a
                    # control file.
                    if self.tree.is_control_filename(subp):
                        trace.mutter("skip control directory %r", subp)
                        continue
                    sub_invp = osutils.pathjoin(inv_path, inv_f)
                    entry = self._invdelta.get(sub_invp)
                    if entry is not None:
                        sub_ie = entry[3]
                    else:
                        sub_ie = this_ie.children.get(inv_f)
                    if sub_ie is not None:
                        # recurse into this already versioned subdir.
                        things_to_add.append((subp, sub_invp, sub_ie, this_ie))
                    else:
                        # user selection overrides ignores
                        # ignore while selecting files - if we globbed in the
                        # outer loop we would ignore user files.
                        ignore_glob = self.tree.is_ignored(subp)
                        if ignore_glob is not None:
                            self.ignored.setdefault(
                                ignore_glob, []).append(subp)
                        else:
                            things_to_add.append(
                                (subp, sub_invp, None, this_ie))


class InventoryRevisionTree(RevisionTree, InventoryTree):

    def __init__(self, repository, inv, revision_id):
        RevisionTree.__init__(self, repository, revision_id)
        self._inventory = inv

    def get_file_mtime(self, path):
        ie = self._path2ie(path)
        try:
            revision = self._repository.get_revision(ie.revision)
        except errors.NoSuchRevision:
            raise FileTimestampUnavailable(path)
        return revision.timestamp

    def get_file_size(self, path):
        return self._path2ie(path).text_size

    def get_file_sha1(self, path, stat_value=None):
        ie = self._path2ie(path)
        if ie.kind == "file":
            return ie.text_sha1
        return None

    def get_file_revision(self, path):
        return self._path2ie(path).revision

    def is_executable(self, path):
        ie = self._path2ie(path)
        if ie.kind != "file":
            return False
        return ie.executable

    def has_filename(self, filename):
        return bool(self.path2id(filename))

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        # The only files returned by this are those from the version
        if from_dir is None:
            from_dir_id = None
            inv = self.root_inventory
        else:
            inv, from_dir_id = self._path2inv_file_id(from_dir)
            if from_dir_id is None:
                # Directory not versioned
                return
        entries = inv.iter_entries(from_dir=from_dir_id, recursive=recursive)
        if inv.root is not None and not include_root and from_dir is None:
            # skip the root for compatibility with the current apis.
            next(entries)
        for path, entry in entries:
            yield path, 'V', entry.kind, entry

    def get_symlink_target(self, path):
        # Inventories store symlink targets in unicode
        return self._path2ie(path).symlink_target

    def get_reference_revision(self, path):
        return self._path2ie(path).reference_revision

    def get_root_id(self):
        if self.root_inventory.root:
            return self.root_inventory.root.file_id

    def kind(self, path):
        return self._path2ie(path).kind

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        try:
            entry = self._path2ie(path)
        except errors.NoSuchFile:
            return ('missing', None, None, None)
        kind = entry.kind
        if kind == 'file':
            return (kind, entry.text_size, entry.executable, entry.text_sha1)
        elif kind == 'symlink':
            return (kind, None, None, entry.symlink_target)
        else:
            return (kind, None, None, None)

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def walkdirs(self, prefix=""):
        _directory = 'directory'
        inv, top_id = self._path2inv_file_id(prefix)
        if top_id is None:
            pending = []
        else:
            pending = [(prefix, '', _directory, None, top_id, None)]
        while pending:
            dirblock = []
            currentdir = pending.pop()
            # 0 - relpath, 1- basename, 2- kind, 3- stat, id, v-kind
            if currentdir[0]:
                relroot = currentdir[0] + '/'
            else:
                relroot = ""
            # FIXME: stash the node in pending
            entry = inv.get_entry(currentdir[4])
            for name, child in entry.sorted_children():
                toppath = relroot + name
                dirblock.append((toppath, name, child.kind, None,
                                 child.file_id, child.kind
                                 ))
            yield (currentdir[0], entry.file_id), dirblock
            # push the user specified dirs from dirblock
            for dir in reversed(dirblock):
                if dir[2] == _directory:
                    pending.append(dir)

    def iter_files_bytes(self, desired_files):
        """See Tree.iter_files_bytes.

        This version is implemented on top of Repository.iter_files_bytes"""
        repo_desired_files = [(self.path2id(f), self.get_file_revision(f), i)
                              for f, i in desired_files]
        try:
            for result in self._repository.iter_files_bytes(repo_desired_files):
                yield result
        except errors.RevisionNotPresent as e:
            raise errors.NoSuchFile(e.file_id)

    def annotate_iter(self, path, default_revision=revision.CURRENT_REVISION):
        """See Tree.annotate_iter"""
        file_id = self.path2id(path)
        text_key = (file_id, self.get_file_revision(path))
        annotator = self._repository.texts.get_annotator()
        annotations = annotator.annotate_flat(text_key)
        return [(key[-1], line) for key, line in annotations]

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, InventoryRevisionTree):
            return (self.root_inventory == other.root_inventory)
        return False

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError('not hashable')


class InterCHKRevisionTree(InterTree):
    """Fast path optimiser for RevisionTrees with CHK inventories."""

    @staticmethod
    def is_compatible(source, target):
        if (isinstance(source, RevisionTree) and
                isinstance(target, RevisionTree)):
            try:
                # Only CHK inventories have id_to_entry attribute
                source.root_inventory.id_to_entry
                target.root_inventory.id_to_entry
                return True
            except AttributeError:
                pass
        return False

    def iter_changes(self, include_unchanged=False,
                     specific_files=None, pb=None, extra_trees=[],
                     require_versioned=True, want_unversioned=False):
        lookup_trees = [self.source]
        if extra_trees:
            lookup_trees.extend(extra_trees)
        # The ids of items we need to examine to insure delta consistency.
        precise_file_ids = set()
        discarded_changes = {}
        if specific_files == []:
            specific_file_ids = []
        else:
            specific_file_ids = self.target.paths2ids(specific_files,
                                                      lookup_trees, require_versioned=require_versioned)
        # FIXME: It should be possible to delegate include_unchanged handling
        # to CHKInventory.iter_changes and do a better job there -- vila
        # 20090304
        changed_file_ids = set()
        # FIXME: nested tree support
        for result in self.target.root_inventory.iter_changes(
                self.source.root_inventory):
            if specific_file_ids is not None:
                file_id = result[0]
                if file_id not in specific_file_ids:
                    # A change from the whole tree that we don't want to show yet.
                    # We may find that we need to show it for delta consistency, so
                    # stash it.
                    discarded_changes[result[0]] = result
                    continue
                new_parent_id = result[4][1]
                precise_file_ids.add(new_parent_id)
            yield result
            changed_file_ids.add(result[0])
        if specific_file_ids is not None:
            for result in self._handle_precise_ids(precise_file_ids,
                                                   changed_file_ids, discarded_changes=discarded_changes):
                yield result
        if include_unchanged:
            # CHKMap avoid being O(tree), so we go to O(tree) only if
            # required to.
            # Now walk the whole inventory, excluding the already yielded
            # file ids
            # FIXME: Support nested trees
            changed_file_ids = set(changed_file_ids)
            for relpath, entry in self.target.root_inventory.iter_entries():
                if (specific_file_ids is not None and
                        entry.file_id not in specific_file_ids):
                    continue
                if entry.file_id not in changed_file_ids:
                    yield (entry.file_id,
                           (relpath, relpath),  # Not renamed
                           False,  # Not modified
                           (True, True),  # Still  versioned
                           (entry.parent_id, entry.parent_id),
                           (entry.name, entry.name),
                           (entry.kind, entry.kind),
                           (entry.executable, entry.executable))


InterTree.register_optimiser(InterCHKRevisionTree)

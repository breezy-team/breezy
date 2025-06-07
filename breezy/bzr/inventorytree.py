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

"""Tree classes, representing directory at point in time."""

import os
import re
import stat
from collections import deque

from .. import branch as _mod_branch
from .. import controldir, debug, errors, lazy_import, osutils, revision, trace
from .. import transport as _mod_transport
from ..controldir import ControlDir
from ..mutabletree import MutableTree
from ..revisiontree import RevisionTree
from ..transport.local import file_kind, file_stat

lazy_import.lazy_import(
    globals(),
    """
from breezy import (
    add,
    )
from bzrformats import (
    inventory as _mod_inventory,
    )
""",
)
import contextlib

from ..tree import (
    FileTimestampUnavailable,
    InterTree,
    MissingNestedTree,
    Tree,
    TreeChange,
    TreeFile,
)


class InventoryTreeChange(TreeChange):
    __slots__ = TreeChange.__slots__ + ["file_id", "parent_id"]

    def __init__(
        self,
        file_id,
        path,
        changed_content,
        versioned,
        parent_id,
        name,
        kind,
        executable,
        copied=False,
    ):
        self.file_id = file_id
        self.parent_id = parent_id
        super().__init__(
            path=path,
            changed_content=changed_content,
            versioned=versioned,
            name=name,
            kind=kind,
            executable=executable,
            copied=copied,
        )

    def __repr__(self):
        return f"{self.__class__.__name__}{self._as_tuple()!r}"

    def _as_tuple(self):
        return (
            self.file_id,
            self.path,
            self.changed_content,
            self.versioned,
            self.parent_id,
            self.name,
            self.kind,
            self.executable,
            self.copied,
        )

    def __eq__(self, other):
        if isinstance(other, TreeChange):
            return self._as_tuple() == other._as_tuple()
        if isinstance(other, tuple):
            return self._as_tuple() == other
        return False

    def __lt__(self, other):
        return self._as_tuple() < other._as_tuple()

    def meta_modified(self):
        if self.versioned == (True, True):
            return self.executable[0] != self.executable[1]
        return False

    def is_reparented(self):
        return self.parent_id[0] != self.parent_id[1]

    @property
    def renamed(self):
        return (
            not self.copied
            and None not in self.name
            and None not in self.parent_id
            and (self.name[0] != self.name[1] or self.parent_id[0] != self.parent_id[1])
        )

    def discard_new(self):
        return self.__class__(
            self.file_id,
            (self.path[0], None),
            self.changed_content,
            (self.versioned[0], None),
            (self.parent_id[0], None),
            (self.name[0], None),
            (self.kind[0], None),
            (self.executable[0], None),
            copied=False,
        )


def _filesize(f) -> int:
    """Return size of given open file."""
    return os.fstat(f.fileno())[stat.ST_SIZE]


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

    def supports_symlinks(self):
        return True

    @classmethod
    def is_special_path(cls, path):
        return path.startswith(".bzr")

    def _get_root_inventory(self):
        return self._inventory

    root_inventory = property(_get_root_inventory, doc="Root inventory of this tree")

    supports_file_ids = True

    def _unpack_file_id(self, file_id):
        """Find the inventory and inventory file id for a tree file id.

        :param file_id: The tree file id, as bytestring or tuple
        :return: Inventory and inventory file id
        """
        if isinstance(file_id, tuple):
            if len(file_id) != 1:
                raise ValueError(f"nested trees not yet supported: {file_id!r}")
            file_id = file_id[0]
        return self.root_inventory, file_id

    def find_related_paths_across_trees(
        self, paths, trees=None, require_versioned=True
    ):
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
        if trees is None:
            trees = []
        if paths is None:
            return None
        file_ids = self.paths2ids(paths, trees, require_versioned=require_versioned)
        ret = set()
        for file_id in file_ids:
            with contextlib.suppress(errors.NoSuchId):
                ret.add(self.id2path(file_id))
        return ret

    def paths2ids(self, paths, trees=None, require_versioned=True):
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
        if trees is None:
            trees = []
        return find_ids_across_trees(paths, [self] + list(trees), require_versioned)

    def path2id(self, path):
        """Return the id for path in this tree."""
        with self.lock_read():
            return self._path2inv_file_id(path)[1]

    def is_versioned(self, path):
        return self.path2id(path) is not None

    def _path2ie(self, path):
        """Lookup an inventory entry by path.

        :param path: Path to look up
        :return: InventoryEntry
        """
        inv, ie = self._path2inv_ie(path)
        if ie is None:
            raise _mod_transport.NoSuchFile(path)
        return ie

    def _path2inv_ie(self, path):
        inv = self.root_inventory
        remaining = path if isinstance(path, list) else osutils.splitpath(path)
        ie = inv.root
        while remaining:
            ie, base, remaining = inv.get_entry_by_path_partial(remaining)
            if remaining:
                inv = self._get_nested_tree(
                    "/".join(base), ie.file_id, ie.reference_revision
                ).root_inventory
        if ie is None:
            return None, None
        return inv, ie

    def _path2inv_file_id(self, path):
        """Lookup a inventory and inventory file id by path.

        :param path: Path to look up
        :return: tuple with inventory and inventory file id
        """
        inv, ie = self._path2inv_ie(path)
        if ie is None:
            return None, None
        return inv, ie.file_id

    def id2path(self, file_id, recurse="down"):
        """Return the path for a file id.

        :raises NoSuchId:
        """
        inventory, file_id = self._unpack_file_id(file_id)
        try:
            return inventory.id2path(file_id)
        except errors.NoSuchId as e:
            if recurse == "down":
                if debug.debug_flag_enabled("evil"):
                    trace.mutter_callsite(
                        2, "id2path with nested trees scales with tree size."
                    )
                for path in self.iter_references():
                    subtree = self.get_nested_tree(path)
                    try:
                        return osutils.pathjoin(path, subtree.id2path(file_id))
                    except errors.NoSuchId:
                        pass
            raise errors.NoSuchId(self, file_id) from e

    def all_file_ids(self):
        return {entry.file_id for path, entry in self.iter_entries_by_dir()}

    def all_versioned_paths(self):
        return {path for path, entry in self.iter_entries_by_dir()}

    def iter_entries_by_dir(self, specific_files=None, recurse_nested=False):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple.
        The order that they are yielded is:

        See Tree.iter_entries_by_dir for details.
        """
        with self.lock_read():
            if specific_files is not None:
                inventory_file_ids = set()
                for path in specific_files:
                    inventory, inv_file_id = self._path2inv_file_id(path)
                    if inventory and inventory is not self.root_inventory:
                        raise AssertionError(
                            f"{inventory!r} != {self.root_inventory!r}"
                        )
                    if inv_file_id is not None:
                        # TODO(jelmer): Should we perhaps raise NoSuchFile here
                        # rather than silently skipping entries?
                        inventory_file_ids.add(inv_file_id)
            else:
                inventory_file_ids = None

            def iter_entries(inv):
                for p, e in inv.iter_entries_by_dir(
                    specific_file_ids=inventory_file_ids
                ):
                    if e.kind == "tree-reference" and recurse_nested:
                        try:
                            subtree = self._get_nested_tree(
                                p, e.file_id, e.reference_revision
                            )
                        except errors.NotBranchError:
                            yield p, e
                        else:
                            with subtree.lock_read():
                                subinv = subtree.root_inventory
                                for subp, e in iter_entries(subinv):
                                    yield (osutils.pathjoin(p, subp) if subp else p), e
                    else:
                        yield p, e

            return iter_entries(self.root_inventory)

    def _get_plan_merge_data(self, path, other, base):
        from bzrformats import versionedfile

        file_id = self.path2id(path)
        vf = versionedfile._PlanMergeVersionedFile(file_id)
        last_revision_a = self._get_file_revision(path, file_id, vf, b"this:")
        last_revision_b = other._get_file_revision(
            other.id2path(file_id), file_id, vf, b"other:"
        )
        if base is None:
            last_revision_base = None
        else:
            last_revision_base = base._get_file_revision(
                base.id2path(file_id), file_id, vf, b"base:"
            )
        return vf, last_revision_a, last_revision_b, last_revision_base

    def plan_file_merge(self, path, other, base=None):
        """Generate a merge plan based on annotations.

        If the file contains uncommitted changes in this tree, they will be
        attributed to the 'current:' pseudo-revision.  If the file contains
        uncommitted changes in the other tree, they will be assigned to the
        'other:' pseudo-revision.
        """
        data = self._get_plan_merge_data(path, other, base)
        vf, last_revision_a, last_revision_b, last_revision_base = data
        return vf.plan_merge(last_revision_a, last_revision_b, last_revision_base)

    def plan_file_lca_merge(self, path, other, base=None):
        """Generate a merge plan based lca-newness.

        If the file contains uncommitted changes in this tree, they will be
        attributed to the 'current:' pseudo-revision.  If the file contains
        uncommitted changes in the other tree, they will be assigned to the
        'other:' pseudo-revision.
        """
        data = self._get_plan_merge_data(path, other, base)
        vf, last_revision_a, last_revision_b, last_revision_base = data
        return vf.plan_lca_merge(last_revision_a, last_revision_b, last_revision_base)

    def _iter_parent_trees(self):
        """Iterate through parent trees, defaulting to Tree.revision_tree."""
        for revision_id in self.get_parent_ids():
            try:
                yield self.revision_tree(revision_id)
            except errors.NoSuchRevisionInTree:
                yield self.branch.repository.revision_tree(revision_id)

    def _get_file_revision(self, path, file_id, vf, tree_revision):
        """Ensure that file_id, tree_revision is in vf to plan the merge."""
        from bzrformats import versionedfile

        last_revision = tree_revision
        parent_keys = [
            (file_id, t.get_file_revision(path)) for t in self._iter_parent_trees()
        ]
        with self.get_file(path) as f:
            vf.add_content(
                versionedfile.FileContentFactory(
                    (file_id, last_revision), parent_keys, f, size=_filesize(f)
                )
            )
        repo = self.branch.repository
        base_vf = repo.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return last_revision

    def preview_transform(self, pb=None):
        from .transform import TransformPreview

        return TransformPreview(self, pb=pb)


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
    specified_path_ids = _find_ids_across_trees(filenames, trees, require_versioned)
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
        from bzrformats.inventory_delta import InventoryDelta

        with self.lock_tree_write():
            self.flush()
            inv = self.root_inventory
            inv.apply_delta(InventoryDelta(changes))
            self._write_inventory(inv)

    def has_changes(self, _from_tree=None):
        """Quickly check that the tree contains at least one commitable change.

        :param _from_tree: tree to compare against to find changes (default to
            the basis tree and is intended to be used by tests).

        :return: True if a change is found. False otherwise
        """
        with self.lock_read():
            # Check pending merges
            if len(self.get_parent_ids()) > 1:
                return True
            if _from_tree is None:
                _from_tree = self.basis_tree()
            changes = self.iter_changes(_from_tree)
            if self.supports_symlinks():
                # Fast path for has_changes.
                try:
                    change = next(changes)
                    # Exclude root (talk about black magic... --vila 20090629)
                    if change.parent_id == (None, None):
                        change = next(changes)
                    return True
                except StopIteration:
                    # No changes
                    return False
            else:
                # Slow path for has_changes.
                # Handle platforms that do not support symlinks in the
                # conditional below. This is slower than the try/except
                # approach below that but we don't have a choice as we
                # need to be sure that all symlinks are removed from the
                # entire changeset. This is because in platforms that
                # do not support symlinks, they show up as None in the
                # working copy as compared to the repository.
                # Also, exclude root as mention in the above fast path.
                changes = filter(
                    lambda c: c[6][0] != "symlink" and c[4] != (None, None), changes
                )
                try:
                    next(iter(changes))
                except StopIteration:
                    return False
                return True

    def _fix_case_of_inventory_path(self, path):
        """If our tree isn't case sensitive, return the canonical path."""
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
            if getattr(self, "conflicts", None) is not None:
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
        rev_tree = InventoryRevisionTree(self.branch.repository, inventory, new_revid)
        self.set_parent_trees([(new_revid, rev_tree)])

    def transform(self, pb=None):
        from .transform import InventoryTreeTransform

        return InventoryTreeTransform(self, pb=pb)

    def add(self, files, kinds=None, ids=None):
        """Add paths to the set of versioned paths.

        Note that the command line normally calls smart_add instead,
        which can automatically recurse.

        This adds the files to the tree, so that they will be
        recorded by the next commit.

        Args:
          files: List of paths to add, relative to the base of the tree.
          kinds: Optional parameter to specify the kinds to be used for
            each file.
          ids: If set, use these instead of automatically generated ids.
            Must be the same length as the list of files, but may
            contain None for ids that are to be autogenerated.

        TODO: Perhaps callback with the ids and paths as they're added.
        """
        if isinstance(files, str):
            # XXX: Passing a single string is inconsistent and should be
            # deprecated.
            if not (ids is None or isinstance(ids, bytes)):
                raise AssertionError()
            if not (kinds is None or isinstance(kinds, str)):
                raise AssertionError()
            files = [files]
            if ids is not None:
                ids = [ids]
            if kinds is not None:
                kinds = [kinds]

        files = [path.strip("/") for path in files]

        if ids is None:
            ids = [None] * len(files)
        else:
            if not (len(ids) == len(files)):
                raise AssertionError()
        if kinds is None:
            kinds = [None] * len(files)
        elif len(kinds) != len(files):
            raise AssertionError()
        with self.lock_tree_write():
            for f in files:
                # generic constraint checks:
                if self.is_control_filename(f):
                    raise errors.ForbiddenControlFileError(filename=f)
                osutils.splitpath(f)
            # fill out file kinds for all files [not needed when we stop
            # caring about the instantaneous file kind within a uncommmitted tree
            #
            self._gather_kinds(files, kinds)
            self._add(files, kinds, ids)

    def _gather_kinds(self, files, kinds):
        """Helper function for add - sets the entries of kinds."""
        raise NotImplementedError(self._gather_kinds)

    def _add(self, files, kinds, ids):
        """Helper function for add - updates the inventory.

        :param files: sequence of pathnames, relative to the tree root
        :param kinds: sequence of  inventory kinds of the files (i.e. may
            contain "tree-reference")
        :param ids: sequence of suggested ids for the files (may be None)
        """
        raise NotImplementedError(self._add)


class _SmartAddHelper:
    """Helper for MutableTree.smart_add."""

    def get_inventory_delta(self):
        # GZ 2016-06-05: Returning view would probably be fine but currently
        # Inventory.apply_delta is documented as requiring a list of changes.
        return list(self._invdelta.values())

    def _get_ie(self, inv_path):
        """Retrieve the most up to date inventory entry for a path.

        :param inv_path: Normalized inventory path
        :return: Inventory entry
        """
        entry = self._invdelta.get(inv_path)
        if entry is not None:
            return entry[3]
        # Find a 'best fit' match if the filesystem is case-insensitive
        inv_path = self.tree._fix_case_of_inventory_path(inv_path)
        try:
            return next(self.tree.iter_entries_by_dir(specific_files=[inv_path]))[1]
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
            this_ie.file_id, this_ie.name, this_ie.parent_id
        )
        self._invdelta[inv_path] = (inv_path, inv_path, this_ie.file_id, this_ie)
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
            parent_ie = self._add_one_and_parent(
                None, dirname, "directory", inv_dirname
            )
        # if the parent exists, but isn't a directory, we have to do the
        # kind change now -- really the inventory shouldn't pretend to know
        # the kind of wt files, but it does.
        if parent_ie.kind != "directory":
            # nb: this relies on someone else checking that the path we're using
            # doesn't contain symlinks.
            parent_ie = self._convert_to_directory(parent_ie, inv_dirname)
        file_id = self.action(self.tree, parent_ie, path, kind)
        entry = _mod_inventory.make_entry(
            kind, basename, parent_ie.file_id, file_id=file_id
        )
        self._invdelta[inv_path] = (None, inv_path, entry.file_id, entry)
        self.added.append(inv_path)
        return entry

    def _gather_dirs_to_add(self, user_dirs):
        # only walk the minimal parents needed: we have user_dirs to override
        # ignores.
        prev_dir = None

        is_inside = osutils.is_inside_or_parent_of_any
        for path in sorted(user_dirs):
            if prev_dir is None or not is_inside([prev_dir], path):
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
            file_list = ["."]

        # expand any symlinks in the directory part, while leaving the
        # filename alone
        # only expanding if symlinks are supported avoids windows path bugs
        if self.tree.supports_symlinks():
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
            kind = file_kind(abspath)
            # ensure the named path is added, so that ignore rules in the later
            # directory walk dont skip it.
            # we dont have a parent ie known yet.: use the relatively slower
            # inventory probing method
            inv_path, _ = osutils.normalized_filename(filepath)
            this_ie = self._get_ie(inv_path)
            if this_ie is None:
                this_ie = self._add_one_and_parent(None, filepath, kind, inv_path)
            if kind == "directory":
                # schedule the dir for scanning
                user_dirs[filepath] = (inv_path, this_ie)

        if not recurse:
            # no need to walk any directories at all.
            return

        things_to_add = list(self._gather_dirs_to_add(user_dirs))

        illegalpath_re = re.compile(r"[\r\n]")
        for directory, inv_path, this_ie, parent_ie in things_to_add:
            # directory is tree-relative
            abspath = self.tree.abspath(directory)

            # get the contents of this directory.

            # find the kind of the path being added, and save stat_value
            # for reuse
            stat_value = None
            if this_ie is None:
                stat_value = file_stat(abspath)
                kind = osutils.file_kind_from_stat_mode(stat_value.st_mode)
            else:
                kind = this_ie.kind

            # allow AddAction to skip this file
            if self.action.skip_file(self.tree, abspath, kind, stat_value):
                continue
            if not _mod_inventory.InventoryEntry.versionable_kind(kind):
                trace.warning(
                    "skipping %s (can't add file of kind '%s')", abspath, kind
                )
                continue
            if illegalpath_re.search(directory):
                trace.warning(f"skipping {abspath!r} (contains \\n or \\r)")
                continue
            if directory in self.conflicts_related:
                # If the file looks like one generated for a conflict, don't
                # add it.
                trace.warning(
                    "skipping %s (generated to help resolve conflicts)", abspath
                )
                continue

            if kind == "directory" and directory != "":
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
                this_ie = self._add_one_and_parent(parent_ie, directory, kind, inv_path)

            if kind == "directory" and not sub_tree:
                if this_ie.kind != "directory":
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
                        sub_ie = InterInventoryTree._get_entry(self.tree, sub_invp)
                    if sub_ie is not None:
                        # recurse into this already versioned subdir.
                        things_to_add.append((subp, sub_invp, sub_ie, this_ie))
                    else:
                        # user selection overrides ignores
                        # ignore while selecting files - if we globbed in the
                        # outer loop we would ignore user files.
                        ignore_glob = self.tree.is_ignored(subp)
                        if ignore_glob is not None:
                            self.ignored.setdefault(ignore_glob, []).append(subp)
                        else:
                            things_to_add.append((subp, sub_invp, None, this_ie))


class InventoryRevisionTree(RevisionTree, InventoryTree):
    def __init__(self, repository, inv, revision_id):
        RevisionTree.__init__(self, repository, revision_id)
        self._inventory = inv

    def _get_file_revision(self, path, file_id, vf, tree_revision):
        """Ensure that file_id, tree_revision is in vf to plan the merge."""
        last_revision = self.get_file_revision(path)
        base_vf = self._repository.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return last_revision

    def get_file_mtime(self, path):
        ie = self._path2ie(path)
        try:
            revision = self._repository.get_revision(ie.revision)
        except errors.NoSuchRevision as e:
            raise FileTimestampUnavailable(path) from e
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

    def reference_parent(self, path, branch=None, possible_transports=None):
        if branch is not None:
            file_id = self.path2id(path)
            parent_url = branch.get_reference_info(file_id)[0]
        else:
            subdir = ControlDir.open_from_transport(
                self._repository.user_transport.clone(path)
            )
            parent_url = subdir.open_branch().get_parent()
        if parent_url is None:
            return None
        return _mod_branch.Branch.open(
            parent_url, possible_transports=possible_transports
        )

    def get_reference_info(self, path, branch=None):
        return branch.get_reference_info(self.path2id(path))[0]

    def list_files(
        self, include_root=False, from_dir=None, recursive=True, recurse_nested=False
    ):
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
            if entry.kind == "tree-reference" and recurse_nested:
                subtree = self._get_nested_tree(
                    path, entry.file_id, entry.reference_revision
                )
                for subpath, status, kind, entry in subtree.list_files(
                    include_root=True,
                    recurse_nested=recurse_nested,
                    recursive=recursive,
                ):
                    full_subpath = osutils.pathjoin(path, subpath) if subpath else path
                    yield full_subpath, status, kind, entry
            else:
                yield path, "V", entry.kind, entry

    def iter_child_entries(self, path):
        inv, ie = self._path2inv_ie(path)
        if ie is None:
            raise _mod_transport.NoSuchFile(path)
        if ie.kind != "directory":
            raise errors.NotADirectory(path)
        return inv.iter_sorted_children(ie.file_id)

    def get_symlink_target(self, path):
        # Inventories store symlink targets in unicode
        ie = self._path2ie(path)
        if ie.kind != "symlink":
            return None
        return ie.symlink_target

    def get_reference_revision(self, path):
        return self._path2ie(path).reference_revision

    def _get_nested_tree(self, path, file_id, reference_revision):
        # Just a guess..
        try:
            subdir = ControlDir.open_from_transport(
                self._repository.user_transport.clone(path)
            )
        except errors.NotBranchError as e:
            raise MissingNestedTree(path) from e
        subrepo = subdir.find_repository()
        try:
            revtree = subrepo.revision_tree(reference_revision)
        except errors.NoSuchRevision as e:
            raise MissingNestedTree(path) from e
        if file_id is not None and file_id != revtree.path2id(""):
            raise AssertionError(
                "invalid root id: {!r} != {!r}".format(file_id, revtree.path2id(""))
            )
        return revtree

    def get_nested_tree(self, path):
        nested_revid = self.get_reference_revision(path)
        return self._get_nested_tree(path, None, nested_revid)

    def kind(self, path):
        return self._path2ie(path).kind

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        try:
            entry = self._path2ie(path)
        except _mod_transport.NoSuchFile:
            return ("missing", None, None, None)
        kind = entry.kind
        if kind == "file":
            return (kind, entry.text_size, entry.executable, entry.text_sha1)
        elif kind == "symlink":
            return (kind, None, None, entry.symlink_target)
        else:
            return (kind, None, None, None)

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def walkdirs(self, prefix=""):
        _directory = "directory"
        inv, top_id = self._path2inv_file_id(prefix)
        pending = [] if top_id is None else [(prefix, top_id)]
        while pending:
            dirblock = []
            root, file_id = pending.pop()
            relroot = root + "/" if root else ""
            # FIXME: stash the node in pending
            subdirs = []
            for child in inv.iter_sorted_children(file_id):
                toppath = relroot + child.name
                dirblock.append((toppath, child.name, child.kind, None, child.kind))
                if child.kind == _directory:
                    subdirs.append((toppath, child.file_id))
            yield root, dirblock
            # push the user specified dirs from dirblock
            pending.extend(reversed(subdirs))

    def iter_files_bytes(self, desired_files):
        """See Tree.iter_files_bytes.

        This version is implemented on top of Repository.iter_files_bytes
        """
        repo_desired_files = [
            (self.path2id(f), self.get_file_revision(f), i) for f, i in desired_files
        ]
        try:
            yield from self._repository.iter_files_bytes(repo_desired_files)
        except errors.RevisionNotPresent as e:
            raise _mod_transport.NoSuchFile(e.file_id) from e

    def annotate_iter(self, path, default_revision=revision.CURRENT_REVISION):
        """See Tree.annotate_iter."""
        file_id = self.path2id(path)
        text_key = (file_id, self.get_file_revision(path))
        annotator = self._repository.texts.get_annotator()
        annotations = annotator.annotate_flat(text_key)
        return [(key[-1], line) for key, line in annotations]

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, InventoryRevisionTree):
            return self.root_inventory == other.root_inventory
        return False

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError("not hashable")


class InterInventoryTree(InterTree):
    """InterTree implementation for InventoryTree objects."""

    @classmethod
    def is_compatible(kls, source, target):
        # The default implementation is naive and uses the public API, so
        # it works for all trees.
        return isinstance(source, InventoryTree) and isinstance(target, InventoryTree)

    def _changes_from_entries(
        self, source_entry, target_entry, source_path, target_path
    ):
        """Generate a iter_changes tuple between source_entry and target_entry.

        :param source_entry: An inventory entry from self.source, or None.
        :param target_entry: An inventory entry from self.target, or None.
        :param source_path: The path of source_entry.
        :param target_path: The path of target_entry.
        :return: A tuple, item 0 of which is an iter_changes result tuple, and
            item 1 is True if there are any changes in the result tuple.
        """
        if source_entry is None:
            if target_entry is None:
                return None
            file_id = target_entry.file_id
        else:
            file_id = source_entry.file_id
        if source_entry is not None:
            source_versioned = True
            source_name = source_entry.name
            source_parent = source_entry.parent_id
            source_kind, source_executable, source_stat = self.source._comparison_data(
                source_entry, source_path
            )
        else:
            source_versioned = False
            source_name = None
            source_parent = None
            source_kind = None
            source_executable = None
        if target_entry is not None:
            target_versioned = True
            target_name = target_entry.name
            target_parent = target_entry.parent_id
            target_kind, target_executable, target_stat = self.target._comparison_data(
                target_entry, target_path
            )
        else:
            target_versioned = False
            target_name = None
            target_parent = None
            target_kind = None
            target_executable = None
        versioned = (source_versioned, target_versioned)
        kind = (source_kind, target_kind)
        changed_content = False
        if source_kind != target_kind:
            changed_content = True
        elif source_kind == "file":
            if not self.file_content_matches(
                source_path, target_path, source_stat, target_stat
            ):
                changed_content = True
        elif source_kind == "symlink":
            if self.source.get_symlink_target(
                source_path
            ) != self.target.get_symlink_target(target_path):
                changed_content = True
        elif source_kind == "tree-reference" and self.source.get_reference_revision(
            source_path
        ) != self.target.get_reference_revision(target_path):
            changed_content = True
        parent = (source_parent, target_parent)
        name = (source_name, target_name)
        executable = (source_executable, target_executable)
        if (
            changed_content is not False
            or versioned[0] != versioned[1]
            or parent[0] != parent[1]
            or name[0] != name[1]
            or executable[0] != executable[1]
        ):
            changes = True
        else:
            changes = False
        return InventoryTreeChange(
            file_id,
            (source_path, target_path),
            changed_content,
            versioned,
            parent,
            name,
            kind,
            executable,
        ), changes

    def iter_changes(
        self,
        include_unchanged=False,
        specific_files=None,
        pb=None,
        extra_trees=None,
        require_versioned=True,
        want_unversioned=False,
    ):
        """Generate an iterator of changes between trees.

        A tuple is returned:
        (file_id, (path_in_source, path_in_target),
         changed_content, versioned, parent, name, kind,
         executable)

        Changed_content is True if the file's content has changed.  This
        includes changes to its kind, and to a symlink's target.

        versioned, parent, name, kind, executable are tuples of (from, to).
        If a file is missing in a tree, its kind is None.

        Iteration is done in parent-to-child order, relative to the target
        tree.

        There is no guarantee that all paths are in sorted order: the
        requirement to expand the search due to renames may result in children
        that should be found early being found late in the search, after
        lexically later results have been returned.
        :param require_versioned: Raise errors.PathsNotVersionedError if a
            path in the specific_files list is not versioned in one of
            source, target or extra_trees.
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children
            of matched directories are included. The parents in the target tree
            of the specific files up to and including the root of the tree are
            always evaluated for changes too.
        :param want_unversioned: Should unversioned files be returned in the
            output. An unversioned file is defined as one with (False, False)
            for the versioned pair.
        """
        extra_trees = [] if not extra_trees else list(extra_trees)
        # The ids of items we need to examine to insure delta consistency.
        precise_file_ids = set()
        changed_file_ids = []
        if specific_files == []:
            target_specific_files = []
            source_specific_files = []
        else:
            target_specific_files = self.target.find_related_paths_across_trees(
                specific_files,
                [self.source] + extra_trees,
                require_versioned=require_versioned,
            )
            source_specific_files = self.source.find_related_paths_across_trees(
                specific_files,
                [self.target] + extra_trees,
                require_versioned=require_versioned,
            )
        if specific_files is not None:
            # reparented or added entries must have their parents included
            # so that valid deltas can be created. The seen_parents set
            # tracks the parents that we need to have.
            # The seen_dirs set tracks directory entries we've yielded.
            # After outputting version object in to_entries we set difference
            # the two seen sets and start checking parents.
            seen_parents = set()
            seen_dirs = set()
        if want_unversioned:
            all_unversioned = sorted(
                [
                    (p.split("/"), p)
                    for p in self.target.extras()
                    if specific_files is None
                    or osutils.is_inside_any(specific_files, p)
                ]
            )
            all_unversioned = deque(all_unversioned)
        else:
            all_unversioned = deque()
        to_paths = {}
        from_entries_by_dir = list(
            self.source.iter_entries_by_dir(specific_files=source_specific_files)
        )
        from_data = dict(from_entries_by_dir)
        to_entries_by_dir = list(
            self.target.iter_entries_by_dir(specific_files=target_specific_files)
        )
        path_equivs = self.find_source_paths([p for p, e in to_entries_by_dir])
        num_entries = len(from_entries_by_dir) + len(to_entries_by_dir)
        entry_count = 0
        # the unversioned path lookup only occurs on real trees - where there
        # can be extras. So the fake_entry is solely used to look up
        # executable it values when execute is not supported.
        fake_entry = TreeFile()
        for target_path, target_entry in to_entries_by_dir:
            while all_unversioned and all_unversioned[0][0] < target_path.split("/"):
                unversioned_path = all_unversioned.popleft()
                (
                    target_kind,
                    target_executable,
                    target_stat,
                ) = self.target._comparison_data(fake_entry, unversioned_path[1])
                yield InventoryTreeChange(
                    None,
                    (None, unversioned_path[1]),
                    True,
                    (False, False),
                    (None, None),
                    (None, unversioned_path[0][-1]),
                    (None, target_kind),
                    (None, target_executable),
                )
            source_path = path_equivs[target_path]
            if source_path is not None:
                source_entry = from_data.get(source_path)
            else:
                source_entry = None
            result, changes = self._changes_from_entries(
                source_entry,
                target_entry,
                source_path=source_path,
                target_path=target_path,
            )
            to_paths[result.file_id] = result.path[1]
            entry_count += 1
            if result.versioned[0]:
                entry_count += 1
            if pb is not None:
                pb.update("comparing files", entry_count, num_entries)
            if changes or include_unchanged:
                if specific_files is not None:
                    precise_file_ids.add(result.parent_id[1])
                    changed_file_ids.append(result.file_id)
                yield result
            # Ensure correct behaviour for reparented/added specific files.
            if specific_files is not None:
                # Record output dirs
                if result.kind[1] == "directory":
                    seen_dirs.add(result.file_id)
                # Record parents of reparented/added entries.
                if not result.versioned[0] or result.is_reparented():
                    seen_parents.add(result.parent_id[1])
        while all_unversioned:
            # yield any trailing unversioned paths
            unversioned_path = all_unversioned.popleft()
            to_kind, to_executable, to_stat = self.target._comparison_data(
                fake_entry, unversioned_path[1]
            )
            yield InventoryTreeChange(
                None,
                (None, unversioned_path[1]),
                True,
                (False, False),
                (None, None),
                (None, unversioned_path[0][-1]),
                (None, to_kind),
                (None, to_executable),
            )
        # Yield all remaining source paths
        for path, from_entry in from_entries_by_dir:
            file_id = from_entry.file_id
            if file_id in to_paths:
                # already returned
                continue
            to_path = self.find_target_path(path)
            entry_count += 1
            if pb is not None:
                pb.update("comparing files", entry_count, num_entries)
            versioned = (True, False)
            parent = (from_entry.parent_id, None)
            name = (from_entry.name, None)
            from_kind, from_executable, stat_value = self.source._comparison_data(
                from_entry, path
            )
            kind = (from_kind, None)
            executable = (from_executable, None)
            changed_content = from_kind is not None
            # the parent's path is necessarily known at this point.
            changed_file_ids.append(file_id)
            yield InventoryTreeChange(
                file_id,
                (path, to_path),
                changed_content,
                versioned,
                parent,
                name,
                kind,
                executable,
            )
        changed_file_ids = set(changed_file_ids)
        if specific_files is not None:
            for result in self._handle_precise_ids(precise_file_ids, changed_file_ids):
                yield result

    @staticmethod
    def _get_entry(tree, path):
        """Get an inventory entry from a tree, with missing entries as None.

        If the tree raises NotImplementedError on accessing .inventory, then
        this is worked around using iter_entries_by_dir on just the file id
        desired.

        :param tree: The tree to lookup the entry in.
        :param path: The path to look up
        """
        # No inventory available.
        try:
            iterator = tree.iter_entries_by_dir(specific_files=[path])
            return next(iterator)[1]
        except StopIteration:
            return None

    def _handle_precise_ids(
        self, precise_file_ids, changed_file_ids, discarded_changes=None
    ):
        """Fill out a partial iter_changes to be consistent.

        :param precise_file_ids: The file ids of parents that were seen during
            the iter_changes.
        :param changed_file_ids: The file ids of already emitted items.
        :param discarded_changes: An optional dict of precalculated
            iter_changes items which the partial iter_changes had not output
            but had calculated.
        :return: A generator of iter_changes items to output.
        """
        # process parents of things that had changed under the users
        # requested paths to prevent incorrect paths or parent ids which
        # aren't in the tree.
        while precise_file_ids:
            precise_file_ids.discard(None)
            # Don't emit file_ids twice
            precise_file_ids.difference_update(changed_file_ids)
            if not precise_file_ids:
                break
            # If the there was something at a given output path in source, we
            # have to include the entry from source in the delta, or we would
            # be putting this entry into a used path.
            paths = []
            for parent_id in precise_file_ids:
                try:
                    paths.append(self.target.id2path(parent_id))
                except errors.NoSuchId:
                    # This id has been dragged in from the source by delta
                    # expansion and isn't present in target at all: we don't
                    # need to check for path collisions on it.
                    pass
            for path in paths:
                old_id = self.source.path2id(path)
                precise_file_ids.add(old_id)
            precise_file_ids.discard(None)
            current_ids = precise_file_ids
            precise_file_ids = set()
            # We have to emit all of precise_file_ids that have been altered.
            # We may have to output the children of some of those ids if any
            # directories have stopped being directories.
            for file_id in current_ids:
                # Examine file_id
                if discarded_changes:
                    result = discarded_changes.get(file_id)
                    source_entry = None
                else:
                    result = None
                if result is None:
                    try:
                        source_path = self.source.id2path(file_id)
                    except errors.NoSuchId:
                        source_path = None
                        source_entry = None
                    else:
                        source_entry = self._get_entry(self.source, source_path)
                    try:
                        target_path = self.target.id2path(file_id)
                    except errors.NoSuchId:
                        target_path = None
                        target_entry = None
                    else:
                        target_entry = self._get_entry(self.target, target_path)
                    result, changes = self._changes_from_entries(
                        source_entry, target_entry, source_path, target_path
                    )
                else:
                    changes = True
                # Get this parents parent to examine.
                new_parent_id = result.parent_id[1]
                precise_file_ids.add(new_parent_id)
                if changes:
                    if result.kind[0] == "directory" and result.kind[1] != "directory":
                        # This stopped being a directory, the old children have
                        # to be included.
                        if source_entry is None:
                            # Reusing a discarded change.
                            source_entry = self._get_entry(self.source, result.path[0])
                        precise_file_ids.update(
                            child.file_id
                            for child in self.source.iter_child_entries(result.path[0])
                        )
                    changed_file_ids.add(result.file_id)
                    yield result

    def find_target_path(self, path, recurse="none"):
        """Find target tree path.

        :param path: Path to search for (exists in source)
        :return: path in target, or None if there is no equivalent path.
        :raise NoSuchFile: If the path doesn't exist in source
        """
        file_id = self.source.path2id(path)
        if file_id is None:
            raise _mod_transport.NoSuchFile(path)
        try:
            return self.target.id2path(file_id, recurse=recurse)
        except errors.NoSuchId:
            return None

    def find_source_path(self, path, recurse="none"):
        """Find the source tree path.

        :param path: Path to search for (exists in target)
        :return: path in source, or None if there is no equivalent path.
        :raise NoSuchFile: if the path doesn't exist in target
        """
        file_id = self.target.path2id(path)
        if file_id is None:
            raise _mod_transport.NoSuchFile(path)
        try:
            return self.source.id2path(file_id, recurse=recurse)
        except errors.NoSuchId:
            return None


InterTree.register_optimiser(InterInventoryTree)


class InterCHKRevisionTree(InterInventoryTree):
    """Fast path optimiser for RevisionTrees with CHK inventories."""

    @staticmethod
    def is_compatible(source, target):
        if isinstance(source, RevisionTree) and isinstance(target, RevisionTree):
            try:
                # Only CHK inventories have id_to_entry attribute
                source.root_inventory.id_to_entry  # noqa: B018
                target.root_inventory.id_to_entry  # noqa: B018
                return True
            except AttributeError:
                pass
        return False

    def iter_changes(
        self,
        include_unchanged=False,
        specific_files=None,
        pb=None,
        extra_trees=None,
        require_versioned=True,
        want_unversioned=False,
    ):
        if extra_trees is None:
            extra_trees = []
        lookup_trees = [self.source]
        if extra_trees:
            lookup_trees.extend(extra_trees)
        # The ids of items we need to examine to insure delta consistency.
        precise_file_ids = set()
        discarded_changes = {}
        if specific_files == []:
            specific_file_ids = []
        else:
            specific_file_ids = self.target.paths2ids(
                specific_files, lookup_trees, require_versioned=require_versioned
            )
        # FIXME: It should be possible to delegate include_unchanged handling
        # to CHKInventory.iter_changes and do a better job there -- vila
        # 20090304
        changed_file_ids = set()
        # FIXME: nested tree support
        for result in self.target.root_inventory.iter_changes(
            self.source.root_inventory
        ):
            result = InventoryTreeChange(*result)
            if specific_file_ids is not None:
                if result.file_id not in specific_file_ids:
                    # A change from the whole tree that we don't want to show yet.
                    # We may find that we need to show it for delta consistency, so
                    # stash it.
                    discarded_changes[result.file_id] = result
                    continue
                precise_file_ids.add(result.parent_id[1])
            yield result
            changed_file_ids.add(result.file_id)
        if specific_file_ids is not None:
            for result in self._handle_precise_ids(
                precise_file_ids, changed_file_ids, discarded_changes=discarded_changes
            ):
                yield result
        if include_unchanged:
            # CHKMap avoid being O(tree), so we go to O(tree) only if
            # required to.
            # Now walk the whole inventory, excluding the already yielded
            # file ids
            # FIXME: Support nested trees
            changed_file_ids = set(changed_file_ids)
            for relpath, entry in self.target.root_inventory.iter_entries():
                if (
                    specific_file_ids is not None
                    and entry.file_id not in specific_file_ids
                ):
                    continue
                if entry.file_id not in changed_file_ids:
                    yield InventoryTreeChange(
                        entry.file_id,
                        (relpath, relpath),  # Not renamed
                        False,  # Not modified
                        (True, True),  # Still  versioned
                        (entry.parent_id, entry.parent_id),
                        (entry.name, entry.name),
                        (entry.kind, entry.kind),
                        (entry.executable, entry.executable),
                    )


InterTree.register_optimiser(InterCHKRevisionTree)

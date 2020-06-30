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
from stat import S_IEXEC

from .. import (
    annotate,
    errors,
    lock,
    osutils,
    revision as _mod_revision,
    tree,
    ui,
    )

from ..i18n import gettext
from ..mutabletree import MutableTree
from ..sixish import text_type, viewvalues
from ..transform import (
    ROOT_PARENT,
    TreeTransform,
    _FileMover,
    _TransformResults,
    DiskTreeTransform,
    joinpath,
    FinalPaths,
    )
from . import (
    inventory,
    inventorytree,
    )


class InventoryTreeTransform(TreeTransform):
    """Tree transform for Bazaar trees."""

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

    def get_preview_tree(self):
        """Return a tree representing the result of the transform.

        The tree is a snapshot, and altering the TreeTransform will invalidate
        it.
        """
        return _PreviewTree(self)

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
                    file_id = self._tree.path2id('')
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


class TransformPreview(InventoryTreeTransform):
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
        self._iter_changes_cache = {
            c.file_id: c for c in self._transform.iter_changes()}

    def supports_tree_reference(self):
        # TODO(jelmer): Support tree references in _PreviewTree.
        # return self._transform._tree.supports_tree_reference()
        return False

    def _content_change(self, file_id):
        """Return True if the content of this file changed"""
        changes = self._iter_changes_cache.get(file_id)
        return (changes is not None and changes.changed_content)

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

    def _path2trans_id(self, path):
        # We must not use None here, because that is a valid value to store.
        trans_id = self._path2trans_id_cache.get(path, object)
        if trans_id is not object:
            return trans_id
        segments = osutils.splitpath(path)
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

    def id2path(self, file_id, recurse='down'):
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

    def iter_entries_by_dir(self, specific_files=None, recurse_nested=False):
        if recurse_nested:
            raise NotImplementedError(
                'follow tree references not yet supported')

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

    def list_files(self, include_root=False, from_dir=None, recursive=True,
                   recurse_nested=False):
        """See WorkingTree.list_files."""
        if recurse_nested:
            raise NotImplementedError(
                'follow tree references not yet supported')

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
                    'directory', '', ROOT_PARENT, self.path2id(''))
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
                return ("SHA1", osutils.sha_file(fileobj))

    def get_file_sha1(self, path, stat_value=None):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        kind = self._transform._new_contents.get(trans_id)
        if kind is None:
            return self._transform._tree.get_file_sha1(path)
        if kind == 'file':
            with self.get_file(path) as fileobj:
                return osutils.sha_file(fileobj)

    def get_reference_revision(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise errors.NoSuchFile(path)
        reference_revision = self._transform._new_reference_revision.get(trans_id)
        if reference_revision is None:
            return self._transform._tree.get_reference_revision(path)
        return reference_revision

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
            changed_content, versioned, kind = (
                changes.changed_content, changes.versioned, changes.kind)
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




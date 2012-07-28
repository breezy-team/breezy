# Copyright (C) 2006-2010 Canonical Ltd
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

"""RevisionTree - a Tree implementation backed by repository data for a revision."""

from __future__ import absolute_import

from cStringIO import StringIO

from bzrlib import (
    errors,
    revision,
    tree,
    )


class RevisionTree(tree.Tree):
    """Tree viewing a previous revision.

    File text can be retrieved from the text store.
    """

    def __init__(self, repository, revision_id):
        self._repository = repository
        self._revision_id = revision_id
        self._rules_searcher = None

    def has_versioned_directories(self):
        """See `Tree.has_versioned_directories`."""
        return self._repository._format.supports_versioned_directories

    def supports_tree_reference(self):
        return getattr(self._repository._format, "supports_tree_reference",
            False)

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        A RevisionTree's parents match the revision graph.
        """
        if self._revision_id in (None, revision.NULL_REVISION):
            parent_ids = []
        else:
            parent_ids = self._repository.get_revision(
                self._revision_id).parent_ids
        return parent_ids

    def get_revision_id(self):
        """Return the revision id associated with this tree."""
        return self._revision_id

    def get_file_revision(self, file_id, path=None):
        """Return the revision id in which a file was last changed."""
        raise NotImplementedError(self.get_file_revision)

    def get_file_text(self, file_id, path=None):
        for (identifier, content) in self.iter_files_bytes([(file_id, None)]):
            ret = "".join(content)
        return ret

    def get_file(self, file_id, path=None):
        return StringIO(self.get_file_text(file_id))

    def is_locked(self):
        return self._repository.is_locked()

    def lock_read(self):
        self._repository.lock_read()
        return self

    def __repr__(self):
        return '<%s instance at %x, rev_id=%r>' % (
            self.__class__.__name__, id(self), self._revision_id)

    def unlock(self):
        self._repository.unlock()

    def _get_rules_searcher(self, default_searcher):
        """See Tree._get_rules_searcher."""
        if self._rules_searcher is None:
            self._rules_searcher = super(RevisionTree,
                self)._get_rules_searcher(default_searcher)
        return self._rules_searcher


class InventoryRevisionTree(RevisionTree,tree.InventoryTree):

    def __init__(self, repository, inv, revision_id):
        RevisionTree.__init__(self, repository, revision_id)
        self._inventory = inv

    def get_file_mtime(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        ie = inv[inv_file_id]
        try:
            revision = self._repository.get_revision(ie.revision)
        except errors.NoSuchRevision:
            raise errors.FileTimestampUnavailable(self.id2path(file_id))
        return revision.timestamp

    def get_file_size(self, file_id):
        inv, inv_file_id = self._unpack_file_id(file_id)
        return inv[inv_file_id].text_size

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        ie = inv[inv_file_id]
        if ie.kind == "file":
            return ie.text_sha1
        return None

    def get_file_revision(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        ie = inv[inv_file_id]
        return ie.revision

    def is_executable(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        ie = inv[inv_file_id]
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
            # skip the root for compatability with the current apis.
            entries.next()
        for path, entry in entries:
            yield path, 'V', entry.kind, entry.file_id, entry

    def get_symlink_target(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        ie = inv[inv_file_id]
        # Inventories store symlink targets in unicode
        return ie.symlink_target

    def get_reference_revision(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        return inv[inv_file_id].reference_revision

    def get_root_id(self):
        if self.root_inventory.root:
            return self.root_inventory.root.file_id

    def kind(self, file_id):
        inv, inv_file_id = self._unpack_file_id(file_id)
        return inv[inv_file_id].kind

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        inv, file_id = self._path2inv_file_id(path)
        if file_id is None:
            return ('missing', None, None, None)
        entry = inv[file_id]
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

    def _file_size(self, entry, stat_value):
        return entry.text_size

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
            entry = inv[currentdir[4]]
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
        repo_desired_files = [(f, self.get_file_revision(f), i)
                              for f, i in desired_files]
        try:
            for result in self._repository.iter_files_bytes(repo_desired_files):
                yield result
        except errors.RevisionNotPresent, e:
            raise errors.NoSuchFile(e.file_id)

    def annotate_iter(self, file_id,
                      default_revision=revision.CURRENT_REVISION):
        """See Tree.annotate_iter"""
        text_key = (file_id, self.get_file_revision(file_id))
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


class InterCHKRevisionTree(tree.InterTree):
    """Fast path optimiser for RevisionTrees with CHK inventories."""

    @staticmethod
    def is_compatible(source, target):
        if (isinstance(source, RevisionTree)
            and isinstance(target, RevisionTree)):
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
                if (specific_file_ids is not None
                    and not entry.file_id in specific_file_ids):
                    continue
                if not entry.file_id in changed_file_ids:
                    yield (entry.file_id,
                           (relpath, relpath), # Not renamed
                           False, # Not modified
                           (True, True), # Still  versioned
                           (entry.parent_id, entry.parent_id),
                           (entry.name, entry.name),
                           (entry.kind, entry.kind),
                           (entry.executable, entry.executable))


tree.InterTree.register_optimiser(InterCHKRevisionTree)

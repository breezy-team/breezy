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

import errno
import os
import tempfile
import time
from stat import S_IEXEC, S_ISREG

from dulwich.index import blob_from_path_and_stat, commit_tree
from dulwich.objects import Blob

from .. import annotate, errors, osutils, trace, ui, urlutils
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..i18n import gettext
from ..mutabletree import MutableTree
from ..transform import (
    ROOT_PARENT,
    FinalPaths,
    ImmortalLimbo,
    MalformedTransform,
    PreviewTree,
    ReusingTransform,
    TransformRenameFailed,
    TreeTransform,
    _FileMover,
    _TransformResults,
    joinpath,
    unique_add,
)
from ..tree import InterTree, TreeChange
from .mapping import (
    decode_git_path,
    encode_git_path,
    mode_is_executable,
    mode_kind,
    object_mode,
)
from .tree import GitTree, GitTreeDirectory, GitTreeFile, GitTreeSymlink


class TreeTransformBase(TreeTransform):
    """The base class for TreeTransform and its kin."""

    def __init__(self, tree, pb=None, case_sensitive=True):
        """Constructor.

        :param tree: The tree that will be transformed, but not necessarily
            the output tree.
        :param pb: ignored
        :param case_sensitive: If True, the target of the transform is
            case sensitive, not just case preserving.
        """
        super().__init__(tree, pb=pb)
        # mapping of trans_id => (sha1 of content, stat_value)
        self._observed_sha1s = {}
        # Set of versioned trans ids
        self._versioned = set()
        # The trans_id that will be used as the tree root
        self.root = self.trans_id_tree_path("")
        # Whether the target is case sensitive
        self._case_sensitive_target = case_sensitive
        self._symlink_target = {}

    @property
    def mapping(self):
        return self._tree.mapping

    def finalize(self):
        """Release the working tree lock, if held.

        This is required if apply has not been invoked, but can be invoked
        even after apply.
        """
        if self._tree is None:
            return
        for hook in MutableTree.hooks["post_transform"]:
            hook(self._tree, self)
        self._tree.unlock()
        self._tree = None

    def create_path(self, name, parent):
        """Assign a transaction id to a new path."""
        trans_id = self.assign_id()
        unique_add(self._new_name, trans_id, name)
        unique_add(self._new_parent, trans_id, parent)
        return trans_id

    def adjust_root_path(self, name, parent):
        """Emulate moving the root by moving all children, instead."""

    def fixup_new_roots(self):
        """Reinterpret requests to change the root directory.

        Instead of creating a root directory, or moving an existing directory,
        all the attributes and children of the new root are applied to the
        existing root directory.

        This means that the old root trans-id becomes obsolete, so it is
        recommended only to invoke this after the root trans-id has become
        irrelevant.

        """
        new_roots = [k for k, v in self._new_parent.items() if v == ROOT_PARENT]
        if len(new_roots) < 1:
            return
        if len(new_roots) != 1:
            raise ValueError("A tree cannot have two roots!")
        old_new_root = new_roots[0]
        # unversion the new root's directory.
        if old_new_root in self._versioned:
            self.cancel_versioning(old_new_root)
        else:
            self.unversion_file(old_new_root)

        # Now move children of new root into old root directory.
        # Ensure all children are registered with the transaction, but don't
        # use directly-- some tree children have new parents
        list(self.iter_tree_children(old_new_root))
        # Move all children of new root into old root directory.
        for child in self.by_parent().get(old_new_root, []):
            self.adjust_path(self.final_name(child), self.root, child)

        # Ensure old_new_root has no directory.
        if old_new_root in self._new_contents:
            self.cancel_creation(old_new_root)
        else:
            self.delete_contents(old_new_root)

        # prevent deletion of root directory.
        if self.root in self._removed_contents:
            self.cancel_deletion(self.root)

        # destroy path info for old_new_root.
        del self._new_parent[old_new_root]
        del self._new_name[old_new_root]

    def trans_id_file_id(self, file_id):
        """Determine or set the transaction id associated with a file ID.
        A new id is only created for file_ids that were never present.  If
        a transaction has been unversioned, it is deliberately still returned.
        (this will likely lead to an unversioned parent conflict.).
        """
        if file_id is None:
            raise ValueError("None is not a valid file id")
        path = self.mapping.parse_file_id(file_id)
        return self.trans_id_tree_path(path)

    def version_file(self, trans_id, file_id=None):
        """Schedule a file to become versioned."""
        if trans_id in self._versioned:
            raise errors.DuplicateKey(key=trans_id)
        self._versioned.add(trans_id)

    def cancel_versioning(self, trans_id):
        """Undo a previous versioning of a file."""
        raise NotImplementedError(self.cancel_versioning)

    def new_paths(self, filesystem_only=False):
        """Determine the paths of all new and changed files.

        :param filesystem_only: if True, only calculate values for files
            that require renames or execute bit changes.
        """
        new_ids = set()
        if filesystem_only:
            stale_ids = self._needs_rename.difference(self._new_name)
            stale_ids.difference_update(self._new_parent)
            stale_ids.difference_update(self._new_contents)
            stale_ids.difference_update(self._versioned)
            needs_rename = self._needs_rename.difference(stale_ids)
            id_sets = (needs_rename, self._new_executability)
        else:
            id_sets = (
                self._new_name,
                self._new_parent,
                self._new_contents,
                self._versioned,
                self._new_executability,
            )
        for id_set in id_sets:
            new_ids.update(id_set)
        return sorted(FinalPaths(self).get_paths(new_ids))

    def final_is_versioned(self, trans_id):
        if trans_id in self._versioned:
            return True
        if trans_id in self._removed_id:
            return False
        orig_path = self.tree_path(trans_id)
        if orig_path is None:
            return False
        return self._tree.is_versioned(orig_path)

    def find_raw_conflicts(self):
        """Find any violations of inventory or filesystem invariants."""
        if self._done is True:
            raise ReusingTransform()
        conflicts = []
        # ensure all children of all existent parents are known
        # all children of non-existent parents are known, by definition.
        self._add_tree_children()
        by_parent = self.by_parent()
        conflicts.extend(self._parent_loops())
        conflicts.extend(self._duplicate_entries(by_parent))
        conflicts.extend(self._parent_type_conflicts(by_parent))
        conflicts.extend(self._improper_versioning())
        conflicts.extend(self._executability_conflicts())
        conflicts.extend(self._overwrite_conflicts())
        return conflicts

    def _check_malformed(self):
        conflicts = self.find_raw_conflicts()
        if len(conflicts) != 0:
            raise MalformedTransform(conflicts=conflicts)

    def _add_tree_children(self):
        """Add all the children of all active parents to the known paths.

        Active parents are those which gain children, and those which are
        removed.  This is a necessary first step in detecting conflicts.
        """
        parents = list(self.by_parent())
        parents.extend(
            [t for t in self._removed_contents if self.tree_kind(t) == "directory"]
        )
        for trans_id in self._removed_id:
            path = self.tree_path(trans_id)
            if path is not None:
                try:
                    if self._tree.stored_kind(path) == "directory":
                        parents.append(trans_id)
                except _mod_transport.NoSuchFile:
                    pass
            elif self.tree_kind(trans_id) == "directory":
                parents.append(trans_id)

        for parent_id in parents:
            # ensure that all children are registered with the transaction
            list(self.iter_tree_children(parent_id))

    def _has_named_child(self, name, parent_id, known_children):
        """Does a parent already have a name child.

        :param name: The searched for name.

        :param parent_id: The parent for which the check is made.

        :param known_children: The already known children. This should have
            been recently obtained from `self.by_parent.get(parent_id)`
            (or will be if None is passed).
        """
        if known_children is None:
            known_children = self.by_parent().get(parent_id, [])
        for child in known_children:
            if self.final_name(child) == name:
                return True
        parent_path = self._tree_id_paths.get(parent_id, None)
        if parent_path is None:
            # No parent... no children
            return False
        child_path = joinpath(parent_path, name)
        child_id = self._tree_path_ids.get(child_path, None)
        if child_id is None:
            # Not known by the tree transform yet, check the filesystem
            return osutils.lexists(self._tree.abspath(child_path))
        else:
            raise AssertionError(
                "child_id is missing: {}, {}, {}".format(name, parent_id, child_id)
            )

    def _available_backup_name(self, name, target_id):
        """Find an available backup name.

        :param name: The basename of the file.

        :param target_id: The directory trans_id where the backup should
            be placed.
        """
        known_children = self.by_parent().get(target_id, [])
        return osutils.available_backup_name(
            name, lambda base: self._has_named_child(base, target_id, known_children)
        )

    def _parent_loops(self):
        """No entry should be its own ancestor."""
        for trans_id in self._new_parent:
            seen = set()
            parent_id = trans_id
            while parent_id != ROOT_PARENT:
                seen.add(parent_id)
                try:
                    parent_id = self.final_parent(parent_id)
                except KeyError:
                    break
                if parent_id == trans_id:
                    yield ("parent loop", trans_id)
                if parent_id in seen:
                    break

    def _improper_versioning(self):
        """Cannot version a file with no contents, or a bad type.

        However, existing entries with no contents are okay.
        """
        for trans_id in self._versioned:
            kind = self.final_kind(trans_id)
            if kind == "symlink" and not self._tree.supports_symlinks():
                # Ignore symlinks as they are not supported on this platform
                continue
            if kind is None:
                yield ("versioning no contents", trans_id)
                continue
            if not self._tree.versionable_kind(kind):
                yield ("versioning bad kind", trans_id, kind)

    def _executability_conflicts(self):
        """Check for bad executability changes.

        Only versioned files may have their executability set, because
        1. only versioned entries can have executability under windows
        2. only files can be executable.  (The execute bit on a directory
           does not indicate searchability)
        """
        for trans_id in self._new_executability:
            if not self.final_is_versioned(trans_id):
                yield ("unversioned executability", trans_id)
            else:
                if self.final_kind(trans_id) != "file":
                    yield ("non-file executability", trans_id)

    def _overwrite_conflicts(self):
        """Check for overwrites (not permitted on Win32)."""
        for trans_id in self._new_contents:
            if self.tree_kind(trans_id) is None:
                continue
            if trans_id not in self._removed_contents:
                yield ("overwrite", trans_id, self.final_name(trans_id))

    def _duplicate_entries(self, by_parent):
        """No directory may have two entries with the same name."""
        if (self._new_name, self._new_parent) == ({}, {}):
            return
        for children in by_parent.values():
            name_ids = []
            for child_tid in children:
                name = self.final_name(child_tid)
                if name is not None:
                    # Keep children only if they still exist in the end
                    if not self._case_sensitive_target:
                        name = name.lower()
                    name_ids.append((name, child_tid))
            name_ids.sort()
            last_name = None
            last_trans_id = None
            for name, trans_id in name_ids:
                kind = self.final_kind(trans_id)
                if kind is None and not self.final_is_versioned(trans_id):
                    continue
                if name == last_name:
                    yield ("duplicate", last_trans_id, trans_id, name)
                last_name = name
                last_trans_id = trans_id

    def _parent_type_conflicts(self, by_parent):
        """Children must have a directory parent."""
        for parent_id, children in by_parent.items():
            if parent_id == ROOT_PARENT:
                continue
            no_children = True
            for child_id in children:
                if self.final_kind(child_id) is not None:
                    no_children = False
                    break
            if no_children:
                continue
            # There is at least a child, so we need an existing directory to
            # contain it.
            kind = self.final_kind(parent_id)
            if kind is None:
                # The directory will be deleted
                yield ("missing parent", parent_id)
            elif kind != "directory":
                # Meh, we need a *directory* to put something in it
                yield ("non-directory parent", parent_id)

    def _set_executability(self, path, trans_id):
        """Set the executability of versioned files."""
        if self._tree._supports_executable():
            new_executability = self._new_executability[trans_id]
            abspath = self._tree.abspath(path)
            current_mode = os.stat(abspath).st_mode
            if new_executability:
                umask = os.umask(0)
                os.umask(umask)
                to_mode = current_mode | (0o100 & ~umask)
                # Enable x-bit for others only if they can read it.
                if current_mode & 0o004:
                    to_mode |= 0o001 & ~umask
                if current_mode & 0o040:
                    to_mode |= 0o010 & ~umask
            else:
                to_mode = current_mode & ~0o111
            osutils.chmod_if_possible(abspath, to_mode)

    def _new_entry(self, name, parent_id, file_id):
        """Helper function to create a new filesystem entry."""
        trans_id = self.create_path(name, parent_id)
        if file_id is not None:
            self.version_file(trans_id, file_id=file_id)
        return trans_id

    def new_file(
        self, name, parent_id, contents, file_id=None, executable=None, sha1=None
    ):
        """Convenience method to create files.

        name is the name of the file to create.
        parent_id is the transaction id of the parent directory of the file.
        contents is an iterator of bytestrings, which will be used to produce
        the file.
        :param file_id: The inventory ID of the file, if it is to be versioned.
        :param executable: Only valid when a file_id has been supplied.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        # TODO: rather than scheduling a set_executable call,
        # have create_file create the file with the right mode.
        self.create_file(contents, trans_id, sha1=sha1)
        if executable is not None:
            self.set_executability(executable, trans_id)
        return trans_id

    def new_directory(self, name, parent_id, file_id=None):
        """Convenience method to create directories.

        name is the name of the directory to create.
        parent_id is the transaction id of the parent directory of the
        directory.
        file_id is the inventory ID of the directory, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_directory(trans_id)
        return trans_id

    def new_symlink(self, name, parent_id, target, file_id=None):
        """Convenience method to create symbolic link.

        name is the name of the symlink to create.
        parent_id is the transaction id of the parent directory of the symlink.
        target is a bytestring of the target of the symlink.
        file_id is the inventory ID of the file, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_symlink(target, trans_id)
        return trans_id

    def new_orphan(self, trans_id, parent_id):
        """Schedule an item to be orphaned.

        When a directory is about to be removed, its children, if they are not
        versioned are moved out of the way: they don't have a parent anymore.

        :param trans_id: The trans_id of the existing item.
        :param parent_id: The parent trans_id of the item.
        """
        raise NotImplementedError(self.new_orphan)

    def _get_potential_orphans(self, dir_id):
        """Find the potential orphans in a directory.

        A directory can't be safely deleted if there are versioned files in it.
        If all the contained files are unversioned then they can be orphaned.

        The 'None' return value means that the directory contains at least one
        versioned file and should not be deleted.

        :param dir_id: The directory trans id.

        :return: A list of the orphan trans ids or None if at least one
             versioned file is present.
        """
        orphans = []
        # Find the potential orphans, stop if one item should be kept
        for child_tid in self.by_parent()[dir_id]:
            if child_tid in self._removed_contents:
                # The child is removed as part of the transform. Since it was
                # versioned before, it's not an orphan
                continue
            if not self.final_is_versioned(child_tid):
                # The child is not versioned
                orphans.append(child_tid)
            else:
                # We have a versioned file here, searching for orphans is
                # meaningless.
                orphans = None
                break
        return orphans

    def _affected_ids(self):
        """Return the set of transform ids affected by the transform."""
        trans_ids = set(self._removed_id)
        trans_ids.update(self._versioned)
        trans_ids.update(self._removed_contents)
        trans_ids.update(self._new_contents)
        trans_ids.update(self._new_executability)
        trans_ids.update(self._new_name)
        trans_ids.update(self._new_parent)
        return trans_ids

    def iter_changes(self, want_unversioned=False):
        """Produce output in the same format as Tree.iter_changes.

        Will produce nonsensical results if invoked while inventory/filesystem
        conflicts (as reported by TreeTransform.find_raw_conflicts()) are present.
        """
        final_paths = FinalPaths(self)
        trans_ids = self._affected_ids()
        results = []
        # Now iterate through all active paths
        for trans_id in trans_ids:
            from_path = self.tree_path(trans_id)
            modified = False
            # find file ids, and determine versioning state
            if from_path is None:
                from_versioned = False
            else:
                from_versioned = self._tree.is_versioned(from_path)
            if not want_unversioned and not from_versioned:
                from_path = None
            to_path = final_paths.get_path(trans_id)
            if to_path is None:
                to_versioned = False
            else:
                to_versioned = self.final_is_versioned(trans_id)
            if not want_unversioned and not to_versioned:
                to_path = None

            if from_versioned:
                # get data from working tree if versioned
                from_entry = next(
                    self._tree.iter_entries_by_dir(specific_files=[from_path])
                )[1]
                from_name = from_entry.name
            else:
                from_entry = None
                if from_path is None:
                    # File does not exist in FROM state
                    from_name = None
                else:
                    # File exists, but is not versioned.  Have to use path-
                    # splitting stuff
                    from_name = os.path.basename(from_path)
            if from_path is not None:
                from_kind, from_executable, from_stats = self._tree._comparison_data(
                    from_entry, from_path
                )
            else:
                from_kind = None
                from_executable = False

            to_name = self.final_name(trans_id)
            to_kind = self.final_kind(trans_id)
            to_executable = (
                self._new_executability[trans_id]
                if trans_id in self._new_executability
                else from_executable
            )
            if from_versioned and from_kind != to_kind:
                modified = True
            elif to_kind in ("file", "symlink") and (trans_id in self._new_contents):
                modified = True
            if (
                not modified
                and from_versioned == to_versioned
                and from_path == to_path
                and from_name == to_name
                and from_executable == to_executable
            ):
                continue
            if (from_path, to_path) == (None, None):
                continue
            results.append(
                TreeChange(
                    (from_path, to_path),
                    modified,
                    (from_versioned, to_versioned),
                    (from_name, to_name),
                    (from_kind, to_kind),
                    (from_executable, to_executable),
                )
            )

        def path_key(c):
            return (c.path[0] or "", c.path[1] or "")

        return iter(sorted(results, key=path_key))

    def get_preview_tree(self):
        """Return a tree representing the result of the transform.

        The tree is a snapshot, and altering the TreeTransform will invalidate
        it.
        """
        return GitPreviewTree(self)

    def commit(
        self,
        branch,
        message,
        merge_parents=None,
        strict=False,
        timestamp=None,
        timezone=None,
        committer=None,
        authors=None,
        revprops=None,
        revision_id=None,
    ):
        """Commit the result of this TreeTransform to a branch.

        :param branch: The branch to commit to.
        :param message: The message to attach to the commit.
        :param merge_parents: Additional parent revision-ids specified by
            pending merges.
        :param strict: If True, abort the commit if there are unversioned
            files.
        :param timestamp: if not None, seconds-since-epoch for the time and
            date.  (May be a float.)
        :param timezone: Optional timezone for timestamp, as an offset in
            seconds.
        :param committer: Optional committer in email-id format.
            (e.g. "J Random Hacker <jrandom@example.com>")
        :param authors: Optional list of authors in email-id format.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.  (Specifying a revision-id
            may reduce performance for some non-native formats.)
        :return: The revision_id of the revision committed.
        """
        self._check_malformed()
        if strict:
            unversioned = set(self._new_contents).difference(set(self._versioned))
            for trans_id in unversioned:
                if not self.final_is_versioned(trans_id):
                    raise errors.StrictCommitFailed()

        revno, last_rev_id = branch.last_revision_info()
        if last_rev_id == _mod_revision.NULL_REVISION:
            if merge_parents is not None:
                raise ValueError("Cannot supply merge parents for first commit.")
            parent_ids = []
        else:
            parent_ids = [last_rev_id]
            if merge_parents is not None:
                parent_ids.extend(merge_parents)
        if self._tree.get_revision_id() != last_rev_id:
            raise ValueError(
                "TreeTransform not based on branch basis: {}".format(
                    self._tree.get_revision_id().decode("utf-8")
                )
            )
        from .. import commit

        revprops = commit.Commit.update_revprops(revprops, branch, authors)
        builder = branch.get_commit_builder(
            parent_ids,
            timestamp=timestamp,
            timezone=timezone,
            committer=committer,
            revprops=revprops,
            revision_id=revision_id,
        )
        preview = self.get_preview_tree()
        list(builder.record_iter_changes(preview, last_rev_id, self.iter_changes()))
        builder.finish_inventory()
        revision_id = builder.commit(message)
        branch.set_last_revision_info(revno + 1, revision_id)
        return revision_id

    def _text_parent(self, trans_id):
        path = self.tree_path(trans_id)
        try:
            if path is None or self._tree.kind(path) != "file":
                return None
        except _mod_transport.NoSuchFile:
            return None
        return path

    def _get_parents_texts(self, trans_id):
        """Get texts for compression parents of this file."""
        path = self._text_parent(trans_id)
        if path is None:
            return ()
        return (self._tree.get_file_text(path),)

    def _get_parents_lines(self, trans_id):
        """Get lines for compression parents of this file."""
        path = self._text_parent(trans_id)
        if path is None:
            return ()
        return (self._tree.get_file_lines(path),)

    def create_file(self, contents, trans_id, mode_id=None, sha1=None):
        """Schedule creation of a new file.

        :seealso: new_file.

        :param contents: an iterator of strings, all of which will be written
            to the target destination.
        :param trans_id: TreeTransform handle
        :param mode_id: If not None, force the mode of the target file to match
            the mode of the object referenced by mode_id.
            Otherwise, we will try to preserve mode bits of an existing file.
        :param sha1: If the sha1 of this content is already known, pass it in.
            We can use it to prevent future sha1 computations.
        """
        raise NotImplementedError(self.create_file)

    def create_directory(self, trans_id):
        """Schedule creation of a new directory.

        See also new_directory.
        """
        raise NotImplementedError(self.create_directory)

    def create_symlink(self, target, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        raise NotImplementedError(self.create_symlink)

    def create_tree_reference(self, target, trans_id):
        raise NotImplementedError(self.create_tree_reference)

    def create_hardlink(self, path, trans_id):
        """Schedule creation of a hard link."""
        raise NotImplementedError(self.create_hardlink)

    def cancel_creation(self, trans_id):
        """Cancel the creation of new file contents."""
        raise NotImplementedError(self.cancel_creation)

    def apply(self, no_conflicts=False, _mover=None):
        """Apply all changes to the inventory and filesystem.

        If filesystem or inventory conflicts are present, MalformedTransform
        will be thrown.

        If apply succeeds, finalize is not necessary.

        :param no_conflicts: if True, the caller guarantees there are no
            conflicts, so no check is made.
        :param _mover: Supply an alternate FileMover, for testing
        """
        raise NotImplementedError(self.apply)

    def cook_conflicts(self, raw_conflicts):
        """Generate a list of cooked conflicts, sorted by file path."""
        if not raw_conflicts:
            return
        fp = FinalPaths(self)
        from .workingtree import ContentsConflict, TextConflict

        for c in raw_conflicts:
            if c[0] == "text conflict":
                yield TextConflict(fp.get_path(c[1]))
            elif c[0] == "contents conflict":
                yield ContentsConflict(fp.get_path(c[1][0]))
            elif c[0] == "duplicate":
                yield TextConflict(fp.get_path(c[2]))
            elif c[0] == "missing parent":
                pass
            elif c[0] == "non-directory parent":
                yield TextConflict(fp.get_path(c[2]))
            elif c[0] == "deleting parent":
                # TODO(jelmer): This should not make it to here
                yield TextConflict(fp.get_path(c[2]))
            elif c[0] == "parent loop":
                # TODO(jelmer): This should not make it to here
                yield TextConflict(fp.get_path(c[2]))
            else:
                raise AssertionError("unknown conflict {}".format(c[0]))


class DiskTreeTransform(TreeTransformBase):
    """Tree transform storing its contents on disk."""

    def __init__(self, tree, limbodir, pb=None, case_sensitive=True):
        """Constructor.
        :param tree: The tree that will be transformed, but not necessarily
            the output tree.
        :param limbodir: A directory where new files can be stored until
            they are installed in their proper places
        :param pb: ignored
        :param case_sensitive: If True, the target of the transform is
            case sensitive, not just case preserving.
        """
        TreeTransformBase.__init__(self, tree, pb, case_sensitive)
        self._limbodir = limbodir
        self._deletiondir = None
        # A mapping of transform ids to their limbo filename
        self._limbo_files = {}
        self._possibly_stale_limbo_files = set()
        # A mapping of transform ids to a set of the transform ids of children
        # that their limbo directory has
        self._limbo_children = {}
        # Map transform ids to maps of child filename to child transform id
        self._limbo_children_names = {}
        # List of transform ids that need to be renamed from limbo into place
        self._needs_rename = set()
        self._creation_mtime = None
        self._create_symlinks = osutils.supports_symlinks(self._limbodir)

    def finalize(self):
        """Release the working tree lock, if held, clean up limbo dir.

        This is required if apply has not been invoked, but can be invoked
        even after apply.
        """
        if self._tree is None:
            return
        try:
            limbo_paths = list(self._limbo_files.values())
            limbo_paths.extend(self._possibly_stale_limbo_files)
            limbo_paths.sort(reverse=True)
            for path in limbo_paths:
                try:
                    osutils.delete_any(path)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise
                    # XXX: warn? perhaps we just got interrupted at an
                    # inconvenient moment, but perhaps files are disappearing
                    # from under us?
            try:
                osutils.delete_any(self._limbodir)
            except OSError:
                # We don't especially care *why* the dir is immortal.
                raise ImmortalLimbo(self._limbodir)
            try:
                if self._deletiondir is not None:
                    osutils.delete_any(self._deletiondir)
            except OSError:
                raise errors.ImmortalPendingDeletion(self._deletiondir)
        finally:
            TreeTransformBase.finalize(self)

    def _limbo_supports_executable(self):
        """Check if the limbo path supports the executable bit."""
        return osutils.supports_executable(self._limbodir)

    def _limbo_name(self, trans_id):
        """Generate the limbo name of a file."""
        limbo_name = self._limbo_files.get(trans_id)
        if limbo_name is None:
            limbo_name = self._generate_limbo_path(trans_id)
            self._limbo_files[trans_id] = limbo_name
        return limbo_name

    def _generate_limbo_path(self, trans_id):
        """Generate a limbo path using the trans_id as the relative path.

        This is suitable as a fallback, and when the transform should not be
        sensitive to the path encoding of the limbo directory.
        """
        self._needs_rename.add(trans_id)
        return osutils.pathjoin(self._limbodir, trans_id)

    def adjust_path(self, name, parent, trans_id):
        previous_parent = self._new_parent.get(trans_id)
        previous_name = self._new_name.get(trans_id)
        super().adjust_path(name, parent, trans_id)
        if trans_id in self._limbo_files and trans_id not in self._needs_rename:
            self._rename_in_limbo([trans_id])
            if previous_parent != parent:
                self._limbo_children[previous_parent].remove(trans_id)
            if previous_parent != parent or previous_name != name:
                del self._limbo_children_names[previous_parent][previous_name]

    def _rename_in_limbo(self, trans_ids):
        """Fix limbo names so that the right final path is produced.

        This means we outsmarted ourselves-- we tried to avoid renaming
        these files later by creating them with their final names in their
        final parents.  But now the previous name or parent is no longer
        suitable, so we have to rename them.

        Even for trans_ids that have no new contents, we must remove their
        entries from _limbo_files, because they are now stale.
        """
        for trans_id in trans_ids:
            old_path = self._limbo_files[trans_id]
            self._possibly_stale_limbo_files.add(old_path)
            del self._limbo_files[trans_id]
            if trans_id not in self._new_contents:
                continue
            new_path = self._limbo_name(trans_id)
            os.rename(old_path, new_path)
            self._possibly_stale_limbo_files.remove(old_path)
            for descendant in self._limbo_descendants(trans_id):
                desc_path = self._limbo_files[descendant]
                desc_path = new_path + desc_path[len(old_path) :]
                self._limbo_files[descendant] = desc_path

    def _limbo_descendants(self, trans_id):
        """Return the set of trans_ids whose limbo paths descend from this."""
        descendants = set(self._limbo_children.get(trans_id, []))
        for descendant in list(descendants):
            descendants.update(self._limbo_descendants(descendant))
        return descendants

    def _set_mode(self, trans_id, mode_id, typefunc):
        raise NotImplementedError(self._set_mode)

    def create_file(self, contents, trans_id, mode_id=None, sha1=None):
        """Schedule creation of a new file.

        :seealso: new_file.

        :param contents: an iterator of strings, all of which will be written
            to the target destination.
        :param trans_id: TreeTransform handle
        :param mode_id: If not None, force the mode of the target file to match
            the mode of the object referenced by mode_id.
            Otherwise, we will try to preserve mode bits of an existing file.
        :param sha1: If the sha1 of this content is already known, pass it in.
            We can use it to prevent future sha1 computations.
        """
        name = self._limbo_name(trans_id)
        with open(name, "wb") as f:
            unique_add(self._new_contents, trans_id, "file")
            f.writelines(contents)
        self._set_mtime(name)
        self._set_mode(trans_id, mode_id, S_ISREG)
        # It is unfortunate we have to use lstat instead of fstat, but we just
        # used utime and chmod on the file, so we need the accurate final
        # details.
        if sha1 is not None:
            self._observed_sha1s[trans_id] = (sha1, osutils.lstat(name))

    def _read_symlink_target(self, trans_id):
        return os.readlink(self._limbo_name(trans_id))

    def _set_mtime(self, path):
        """All files that are created get the same mtime.

        This time is set by the first object to be created.
        """
        if self._creation_mtime is None:
            self._creation_mtime = time.time()
        os.utime(path, (self._creation_mtime, self._creation_mtime))

    def create_hardlink(self, path, trans_id):
        """Schedule creation of a hard link."""
        name = self._limbo_name(trans_id)
        try:
            os.link(path, name)
        except OSError as e:
            if e.errno != errno.EPERM:
                raise
            raise errors.HardLinkNotSupported(path)
        try:
            unique_add(self._new_contents, trans_id, "file")
        except BaseException:
            # Clean up the file, it never got registered so
            # TreeTransform.finalize() won't clean it up.
            os.unlink(name)
            raise

    def create_directory(self, trans_id):
        """Schedule creation of a new directory.

        See also new_directory.
        """
        os.mkdir(self._limbo_name(trans_id))
        unique_add(self._new_contents, trans_id, "directory")

    def create_symlink(self, target, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        if self._create_symlinks:
            os.symlink(target, self._limbo_name(trans_id))
        else:
            try:
                path = FinalPaths(self).get_path(trans_id)
            except KeyError:
                path = None
            trace.warning(
                'Unable to create symlink "{}" on this filesystem.'.format(path)
            )
            self._symlink_target[trans_id] = target
        # We add symlink to _new_contents even if they are unsupported
        # and not created. These entries are subsequently used to avoid
        # conflicts on platforms that don't support symlink
        unique_add(self._new_contents, trans_id, "symlink")

    def create_tree_reference(self, reference_revision, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        os.mkdir(self._limbo_name(trans_id))
        unique_add(self._new_reference_revision, trans_id, reference_revision)
        unique_add(self._new_contents, trans_id, "tree-reference")

    def cancel_creation(self, trans_id):
        """Cancel the creation of new file contents."""
        del self._new_contents[trans_id]
        if trans_id in self._observed_sha1s:
            del self._observed_sha1s[trans_id]
        children = self._limbo_children.get(trans_id)
        # if this is a limbo directory with children, move them before removing
        # the directory
        if children is not None:
            self._rename_in_limbo(children)
            del self._limbo_children[trans_id]
            del self._limbo_children_names[trans_id]
        osutils.delete_any(self._limbo_name(trans_id))

    def new_orphan(self, trans_id, parent_id):
        conf = self._tree.get_config_stack()
        handle_orphan = conf.get("transform.orphan_policy")
        handle_orphan(self, trans_id, parent_id)

    def final_entry(self, trans_id):
        is_versioned = self.final_is_versioned(trans_id)
        fp = FinalPaths(self)
        tree_path = fp.get_path(trans_id)
        if trans_id in self._new_contents:
            path = self._limbo_name(trans_id)
            st = os.lstat(path)
            kind = mode_kind(st.st_mode)
            name = self.final_name(trans_id)
            file_id = self._tree.mapping.generate_file_id(tree_path)
            parent_id = self._tree.mapping.generate_file_id(os.path.dirname(tree_path))
            if kind == "directory":
                return GitTreeDirectory(
                    file_id, self.final_name(trans_id), parent_id=parent_id
                ), is_versioned
            executable = mode_is_executable(st.st_mode)
            object_mode(kind, executable)
            blob = blob_from_path_and_stat(encode_git_path(path), st)
            if kind == "symlink":
                return GitTreeSymlink(
                    file_id, name, parent_id, decode_git_path(blob.data)
                ), is_versioned
            elif kind == "file":
                return GitTreeFile(
                    file_id,
                    name,
                    executable=executable,
                    parent_id=parent_id,
                    git_sha1=blob.id,
                    text_size=len(blob.data),
                ), is_versioned
            else:
                raise AssertionError(kind)
        elif trans_id in self._removed_contents:
            return None, None
        else:
            orig_path = self.tree_path(trans_id)
            if orig_path is None:
                return None, None
            file_id = self._tree.mapping.generate_file_id(tree_path)
            if tree_path == "":
                parent_id = None
            else:
                parent_id = self._tree.mapping.generate_file_id(
                    os.path.dirname(tree_path)
                )
            try:
                ie = next(self._tree.iter_entries_by_dir(specific_files=[orig_path]))[1]
                ie.file_id = file_id
                ie.parent_id = parent_id
                return ie, is_versioned
            except StopIteration:
                try:
                    if self.tree_kind(trans_id) == "directory":
                        return GitTreeDirectory(
                            file_id, self.final_name(trans_id), parent_id=parent_id
                        ), is_versioned
                except OSError as e:
                    if e.errno != errno.ENOTDIR:
                        raise
                return None, None

    def final_git_entry(self, trans_id):
        if trans_id in self._new_contents:
            path = self._limbo_name(trans_id)
            st = os.lstat(path)
            kind = mode_kind(st.st_mode)
            if kind == "directory":
                return None, None
            executable = mode_is_executable(st.st_mode)
            mode = object_mode(kind, executable)
            blob = blob_from_path_and_stat(encode_git_path(path), st)
        elif trans_id in self._removed_contents:
            return None, None
        else:
            orig_path = self.tree_path(trans_id)
            kind = self._tree.kind(orig_path)
            executable = self._tree.is_executable(orig_path)
            mode = object_mode(kind, executable)
            if kind == "symlink":
                contents = self._tree.get_symlink_target(orig_path)
            elif kind == "file":
                contents = self._tree.get_file_text(orig_path)
            elif kind == "directory":
                return None, None
            else:
                raise AssertionError(kind)
            blob = Blob.from_string(contents)
        return blob, mode


class GitTreeTransform(DiskTreeTransform):
    """Represent a tree transformation.

    This object is designed to support incremental generation of the transform,
    in any order.

    However, it gives optimum performance when parent directories are created
    before their contents.  The transform is then able to put child files
    directly in their parent directory, avoiding later renames.

    It is easy to produce malformed transforms, but they are generally
    harmless.  Attempting to apply a malformed transform will cause an
    exception to be raised before any modifications are made to the tree.

    Many kinds of malformed transforms can be corrected with the
    resolve_conflicts function.  The remaining ones indicate programming error,
    such as trying to create a file with no path.

    Two sets of file creation methods are supplied.  Convenience methods are:
     * new_file
     * new_directory
     * new_symlink

    These are composed of the low-level methods:
     * create_path
     * create_file or create_directory or create_symlink
     * version_file
     * set_executability

    Transform/Transaction ids
    -------------------------
    trans_ids are temporary ids assigned to all files involved in a transform.
    It's possible, even common, that not all files in the Tree have trans_ids.

    trans_ids are used because filenames and file_ids are not good enough
    identifiers; filenames change.

    trans_ids are only valid for the TreeTransform that generated them.

    Limbo
    -----
    Limbo is a temporary directory use to hold new versions of files.
    Files are added to limbo by create_file, create_directory, create_symlink,
    and their convenience variants (new_*).  Files may be removed from limbo
    using cancel_creation.  Files are renamed from limbo into their final
    location as part of TreeTransform.apply

    Limbo must be cleaned up, by either calling TreeTransform.apply or
    calling TreeTransform.finalize.

    Files are placed into limbo inside their parent directories, where
    possible.  This reduces subsequent renames, and makes operations involving
    lots of files faster.  This optimization is only possible if the parent
    directory is created *before* creating any of its children, so avoid
    creating children before parents, where possible.

    Pending-deletion
    ----------------
    This temporary directory is used by _FileMover for storing files that are
    about to be deleted.  In case of rollback, the files will be restored.
    FileMover does not delete files until it is sure that a rollback will not
    happen.
    """

    def __init__(self, tree, pb=None):
        """Note: a tree_write lock is taken on the tree.

        Use TreeTransform.finalize() to release the lock (can be omitted if
        TreeTransform.apply() called).
        """
        tree.lock_tree_write()
        try:
            limbodir = urlutils.local_path_from_url(tree._transport.abspath("limbo"))
            osutils.ensure_empty_directory_exists(limbodir, errors.ExistingLimbo)
            deletiondir = urlutils.local_path_from_url(
                tree._transport.abspath("pending-deletion")
            )
            osutils.ensure_empty_directory_exists(
                deletiondir, errors.ExistingPendingDeletion
            )
        except BaseException:
            tree.unlock()
            raise

        # Cache of realpath results, to speed up canonical_path
        self._realpaths = {}
        # Cache of relpath results, to speed up canonical_path
        self._relpaths = {}
        DiskTreeTransform.__init__(self, tree, limbodir, pb, tree.case_sensitive)
        self._deletiondir = deletiondir

    def canonical_path(self, path):
        """Get the canonical tree-relative path."""
        # don't follow final symlinks
        abs = self._tree.abspath(path)
        if abs in self._relpaths:
            return self._relpaths[abs]
        dirname, basename = os.path.split(abs)
        if dirname not in self._realpaths:
            self._realpaths[dirname] = os.path.realpath(dirname)
        dirname = self._realpaths[dirname]
        abs = osutils.pathjoin(dirname, basename)
        if dirname in self._relpaths:
            relpath = osutils.pathjoin(self._relpaths[dirname], basename)
            relpath = relpath.rstrip("/\\")
        else:
            relpath = self._tree.relpath(abs)
        self._relpaths[abs] = relpath
        return relpath

    def tree_kind(self, trans_id):
        """Determine the file kind in the working tree.

        :returns: The file kind or None if the file does not exist
        """
        path = self._tree_id_paths.get(trans_id)
        if path is None:
            return None
        try:
            return osutils.file_kind(self._tree.abspath(path))
        except _mod_transport.NoSuchFile:
            return None

    def _set_mode(self, trans_id, mode_id, typefunc):
        """Set the mode of new file contents.
        The mode_id is the existing file to get the mode from (often the same
        as trans_id).  The operation is only performed if there's a mode match
        according to typefunc.
        """
        if mode_id is None:
            mode_id = trans_id
        try:
            old_path = self._tree_id_paths[mode_id]
        except KeyError:
            return
        try:
            mode = os.stat(self._tree.abspath(old_path)).st_mode
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                # Either old_path doesn't exist, or the parent of the
                # target is not a directory (but will be one eventually)
                # Either way, we know it doesn't exist *right now*
                # See also bug #248448
                return
            else:
                raise
        if typefunc(mode):
            osutils.chmod_if_possible(self._limbo_name(trans_id), mode)

    def iter_tree_children(self, parent_id):
        """Iterate through the entry's tree children, if any."""
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return
        try:
            children = os.listdir(self._tree.abspath(path))
        except (NotADirectoryError, FileNotFoundError):
            return

        for child in children:
            childpath = joinpath(path, child)
            if self._tree.is_control_filename(childpath):
                continue
            yield self.trans_id_tree_path(childpath)

    def _generate_limbo_path(self, trans_id):
        """Generate a limbo path using the final path if possible.

        This optimizes the performance of applying the tree transform by
        avoiding renames.  These renames can be avoided only when the parent
        directory is already scheduled for creation.

        If the final path cannot be used, falls back to using the trans_id as
        the relpath.
        """
        parent = self._new_parent.get(trans_id)
        # if the parent directory is already in limbo (e.g. when building a
        # tree), choose a limbo name inside the parent, to reduce further
        # renames.
        use_direct_path = False
        if self._new_contents.get(parent) == "directory":
            filename = self._new_name.get(trans_id)
            if filename is not None:
                if parent not in self._limbo_children:
                    self._limbo_children[parent] = set()
                    self._limbo_children_names[parent] = {}
                    use_direct_path = True
                # the direct path can only be used if no other file has
                # already taken this pathname, i.e. if the name is unused, or
                # if it is already associated with this trans_id.
                elif self._case_sensitive_target:
                    if self._limbo_children_names[parent].get(filename) in (
                        trans_id,
                        None,
                    ):
                        use_direct_path = True
                else:
                    for l_filename, l_trans_id in self._limbo_children_names[
                        parent
                    ].items():
                        if l_trans_id == trans_id:
                            continue
                        if l_filename.lower() == filename.lower():
                            break
                    else:
                        use_direct_path = True

        if not use_direct_path:
            return DiskTreeTransform._generate_limbo_path(self, trans_id)

        limbo_name = osutils.pathjoin(self._limbo_files[parent], filename)
        self._limbo_children[parent].add(trans_id)
        self._limbo_children_names[parent][filename] = trans_id
        return limbo_name

    def cancel_versioning(self, trans_id):
        """Undo a previous versioning of a file."""
        self._versioned.remove(trans_id)

    def apply(self, no_conflicts=False, _mover=None):
        """Apply all changes to the inventory and filesystem.

        If filesystem or inventory conflicts are present, MalformedTransform
        will be thrown.

        If apply succeeds, finalize is not necessary.

        :param no_conflicts: if True, the caller guarantees there are no
            conflicts, so no check is made.
        :param _mover: Supply an alternate FileMover, for testing
        """
        for hook in MutableTree.hooks["pre_transform"]:
            hook(self._tree, self)
        if not no_conflicts:
            self._check_malformed()
        self.rename_count = 0
        with ui.ui_factory.nested_progress_bar() as child_pb:
            child_pb.update(gettext("Apply phase"), 0, 2)
            index_changes = self._generate_index_changes()
            offset = 1
            if _mover is None:
                mover = _FileMover()
            else:
                mover = _mover
            try:
                child_pb.update(gettext("Apply phase"), 0 + offset, 2 + offset)
                self._apply_removals(mover)
                child_pb.update(gettext("Apply phase"), 1 + offset, 2 + offset)
                modified_paths = self._apply_insertions(mover)
            except BaseException:
                mover.rollback()
                raise
            else:
                mover.apply_deletions()
        self._tree._apply_index_changes(index_changes)
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
        tree_paths = sorted(self._tree_path_ids.items(), reverse=True)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, (path, trans_id) in enumerate(tree_paths):
                # do not attempt to move root into a subdirectory of itself.
                if path == "":
                    continue
                child_pb.update(gettext("removing file"), num, len(tree_paths))
                full_path = self._tree.abspath(path)
                if trans_id in self._removed_contents:
                    delete_path = os.path.join(self._deletiondir, trans_id)
                    mover.pre_delete(full_path, delete_path)
                elif trans_id in self._new_name or trans_id in self._new_parent:
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
                    child_pb.update(gettext("adding file"), num, len(new_paths))
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
                if trans_id in self._new_contents or self.path_changed(trans_id):
                    if trans_id in self._new_contents:
                        modified_paths.append(full_path)
                if trans_id in self._new_executability:
                    self._set_executability(path, trans_id)
                if trans_id in self._observed_sha1s:
                    o_sha1, o_st_val = self._observed_sha1s[trans_id]
                    st = osutils.lstat(full_path)
                    self._observed_sha1s[trans_id] = (o_sha1, st)
                if trans_id in self._new_reference_revision:
                    for (
                        submodule_path,
                        _submodule_url,
                        _submodule_name,
                    ) in self._tree._submodule_config():
                        if decode_git_path(submodule_path) == path:
                            break
                    else:
                        trace.warning("unable to find submodule for path %s", path)
                        continue
                    submodule_transport = self._tree.controldir.control_transport.clone(
                        os.path.join("modules", submodule_name.decode("utf-8"))
                    )
                    submodule_transport.create_prefix()
                    from .dir import BareLocalGitControlDirFormat

                    BareLocalGitControlDirFormat().initialize_on_transport(
                        submodule_transport
                    )
                    with open(os.path.join(full_path, ".git"), "w") as f:
                        submodule_abspath = submodule_transport.local_abspath(".")
                        f.write(
                            "gitdir: {}\n".format(
                                os.path.relpath(submodule_abspath, full_path)
                            )
                        )
        for _path, trans_id in new_paths:
            # new_paths includes stuff like workingtree conflicts. Only the
            # stuff in new_contents actually comes from limbo.
            if trans_id in self._limbo_files:
                del self._limbo_files[trans_id]
        self._new_contents.clear()
        return modified_paths

    def _generate_index_changes(self):
        """Generate an inventory delta for the current transform."""
        removed_id = set(self._removed_id)
        removed_id.update(self._removed_contents)
        changes = {}
        changed_ids = set()
        for id_set in [
            self._new_name,
            self._new_parent,
            self._new_executability,
            self._new_contents,
        ]:
            changed_ids.update(id_set)
        for id_set in [self._new_name, self._new_parent]:
            removed_id.update(id_set)
        # so does adding
        changed_kind = set(self._new_contents)
        # Ignore entries that are already known to have changed.
        changed_kind.difference_update(changed_ids)
        #  to keep only the truly changed ones
        changed_kind = (
            t for t in changed_kind if self.tree_kind(t) != self.final_kind(t)
        )
        changed_ids.update(changed_kind)
        for t in changed_kind:
            if self.final_kind(t) == "directory":
                removed_id.add(t)
                changed_ids.remove(t)
        new_paths = sorted(FinalPaths(self).get_paths(changed_ids))
        total_entries = len(new_paths) + len(removed_id)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, trans_id in enumerate(removed_id):
                if (num % 10) == 0:
                    child_pb.update(gettext("removing file"), num, total_entries)
                try:
                    path = self._tree_id_paths[trans_id]
                except KeyError:
                    continue
                changes[path] = (None, None, None, None)
            for num, (path, trans_id) in enumerate(new_paths):
                if (num % 10) == 0:
                    child_pb.update(
                        gettext("adding file"), num + len(removed_id), total_entries
                    )

                kind = self.final_kind(trans_id)
                if kind is None:
                    continue
                versioned = self.final_is_versioned(trans_id)
                if not versioned:
                    continue
                executability = self._new_executability.get(trans_id)
                reference_revision = self._new_reference_revision.get(trans_id)
                symlink_target = self._symlink_target.get(trans_id)
                changes[path] = (
                    kind,
                    executability,
                    reference_revision,
                    symlink_target,
                )
        return [(p, k, e, rr, st) for (p, (k, e, rr, st)) in changes.items()]


class GitTransformPreview(GitTreeTransform):
    """A TreeTransform for generating preview trees.

    Unlike TreeTransform, this version works when the input tree is a
    RevisionTree, rather than a WorkingTree.  As a result, it tends to ignore
    unversioned files in the input tree.
    """

    def __init__(self, tree, pb=None, case_sensitive=True):
        tree.lock_read()
        limbodir = tempfile.mkdtemp(prefix="git-limbo-")
        DiskTreeTransform.__init__(self, tree, limbodir, pb, case_sensitive)

    def canonical_path(self, path):
        return path

    def tree_kind(self, trans_id):
        path = self.tree_path(trans_id)
        if path is None:
            return None
        kind = self._tree.path_content_summary(path)[0]
        if kind == "missing":
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
        """Iterate through the entry's tree children, if any."""
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return
        try:
            for child in self._tree.iter_child_entries(path):
                childpath = joinpath(path, child.name)
                yield self.trans_id_tree_path(childpath)
        except _mod_transport.NoSuchFile:
            return

    def new_orphan(self, trans_id, parent_id):
        raise NotImplementedError(self.new_orphan)


class GitPreviewTree(PreviewTree, GitTree):
    """Partial implementation of Tree to support show_diff_trees."""

    supports_file_ids = False

    def __init__(self, transform):
        PreviewTree.__init__(self, transform)
        self.store = transform._tree.store
        self.mapping = transform._tree.mapping
        self._final_paths = FinalPaths(transform)

    def supports_setting_file_ids(self):
        return False

    def supports_symlinks(self):
        return self._transform._create_symlinks

    def _supports_executable(self):
        return self._transform._limbo_supports_executable()

    def walkdirs(self, prefix=""):
        pending = [self._transform.root]
        while len(pending) > 0:
            parent_id = pending.pop()
            children = []
            subdirs = []
            prefix = prefix.rstrip("/")
            parent_path = self._final_paths.get_path(parent_id)
            for child_id in self._all_children(parent_id):
                path_from_root = self._final_paths.get_path(child_id)
                basename = self._transform.final_name(child_id)
                kind = self._transform.final_kind(child_id)
                if kind is not None:
                    versioned_kind = kind
                else:
                    kind = "unknown"
                    versioned_kind = self._transform._tree.stored_kind(path_from_root)
                if versioned_kind == "directory":
                    subdirs.append(child_id)
                children.append((path_from_root, basename, kind, None, versioned_kind))
            children.sort()
            if parent_path.startswith(prefix):
                yield parent_path, children
            pending.extend(
                sorted(subdirs, key=self._final_paths.get_path, reverse=True)
            )

    def iter_changes(
        self,
        from_tree,
        include_unchanged=False,
        specific_files=None,
        pb=None,
        extra_trees=None,
        require_versioned=True,
        want_unversioned=False,
    ):
        """See InterTree.iter_changes.

        This has a fast path that is only used when the from_tree matches
        the transform tree, and no fancy options are supplied.
        """
        return InterTree.get(from_tree, self).iter_changes(
            include_unchanged=include_unchanged,
            specific_files=specific_files,
            pb=pb,
            extra_trees=extra_trees,
            require_versioned=require_versioned,
            want_unversioned=want_unversioned,
        )

    def get_file(self, path):
        """See Tree.get_file."""
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise _mod_transport.NoSuchFile(path)
        if trans_id in self._transform._new_contents:
            name = self._transform._limbo_name(trans_id)
            return open(name, "rb")
        if trans_id in self._transform._removed_contents:
            raise _mod_transport.NoSuchFile(path)
        orig_path = self._transform.tree_path(trans_id)
        return self._transform._tree.get_file(orig_path)

    def get_symlink_target(self, path):
        """See Tree.get_symlink_target."""
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise _mod_transport.NoSuchFile(path)
        if trans_id not in self._transform._new_contents:
            orig_path = self._transform.tree_path(trans_id)
            return self._transform._tree.get_symlink_target(orig_path)
        name = self._transform._limbo_name(trans_id)
        return osutils.readlink(name)

    def annotate_iter(self, path, default_revision=_mod_revision.CURRENT_REVISION):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            return None
        orig_path = self._transform.tree_path(trans_id)
        if orig_path is not None:
            old_annotation = self._transform._tree.annotate_iter(
                orig_path, default_revision=default_revision
            )
        else:
            old_annotation = []
        try:
            lines = self.get_file_lines(path)
        except _mod_transport.NoSuchFile:
            return None
        return annotate.reannotate([old_annotation], lines, default_revision)

    def path2id(self, path):
        if isinstance(path, list):
            if path == []:
                path = [""]
            path = osutils.pathjoin(*path)
        if not self.is_versioned(path):
            return None
        return self._transform._tree.mapping.generate_file_id(path)

    def get_file_text(self, path):
        """Return the byte content of a file.

        :param path: The path of the file.

        :returns: A single byte string for the whole file.
        """
        with self.get_file(path) as my_file:
            return my_file.read()

    def get_file_lines(self, path):
        """Return the content of a file, as lines.

        :param path: The path of the file.
        """
        return osutils.split_lines(self.get_file_text(path))

    def extras(self):
        possible_extras = {
            self._transform.trans_id_tree_path(p)
            for p in self._transform._tree.extras()
        }
        possible_extras.update(self._transform._new_contents)
        possible_extras.update(self._transform._removed_id)
        for trans_id in possible_extras:
            if not self._transform.final_is_versioned(trans_id):
                yield self._final_paths._determine_path(trans_id)

    def path_content_summary(self, path):
        trans_id = self._path2trans_id(path)
        tt = self._transform
        tree_path = tt.tree_path(trans_id)
        kind = tt._new_contents.get(trans_id)
        if kind is None:
            if tree_path is None or trans_id in tt._removed_contents:
                return "missing", None, None, None
            summary = tt._tree.path_content_summary(tree_path)
            kind, size, executable, link_or_sha1 = summary
        else:
            link_or_sha1 = None
            limbo_name = tt._limbo_name(trans_id)
            if trans_id in tt._new_reference_revision:
                kind = "tree-reference"
            if kind == "file":
                statval = os.lstat(limbo_name)
                size = statval.st_size
                if not tt._limbo_supports_executable():
                    executable = False
                else:
                    executable = statval.st_mode & S_IEXEC
            else:
                size = None
                executable = None
            if kind == "symlink":
                link_or_sha1 = os.readlink(limbo_name)
                if not isinstance(link_or_sha1, str):
                    link_or_sha1 = os.fsdecode(link_or_sha1)
        executable = tt._new_executability.get(trans_id, executable)
        return kind, size, executable, link_or_sha1

    def get_file_mtime(self, path):
        """See Tree.get_file_mtime."""
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise _mod_transport.NoSuchFile(path)
        if trans_id not in self._transform._new_contents:
            return self._transform._tree.get_file_mtime(
                self._transform.tree_path(trans_id)
            )
        name = self._transform._limbo_name(trans_id)
        statval = os.lstat(name)
        return statval.st_mtime

    def is_versioned(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            # It doesn't exist, so it's not versioned.
            return False
        if trans_id in self._transform._versioned:
            return True
        if trans_id in self._transform._removed_id:
            return False
        orig_path = self._transform.tree_path(trans_id)
        return self._transform._tree.is_versioned(orig_path)

    def iter_entries_by_dir(self, specific_files=None, recurse_nested=False):
        if recurse_nested:
            raise NotImplementedError("follow tree references not yet supported")

        # This may not be a maximally efficient implementation, but it is
        # reasonably straightforward.  An implementation that grafts the
        # TreeTransform changes onto the tree's iter_entries_by_dir results
        # might be more efficient, but requires tricky inferences about stack
        # position.
        for trans_id, path in self._list_files_by_dir():
            entry, is_versioned = self._transform.final_entry(trans_id)
            if entry is None:
                continue
            if not is_versioned and entry.kind != "directory":
                continue
            if specific_files is not None and path not in specific_files:
                continue
            if entry is not None:
                yield path, entry

    def _list_files_by_dir(self):
        todo = [ROOT_PARENT]
        while len(todo) > 0:
            parent = todo.pop()
            children = list(self._all_children(parent))
            paths = dict(zip(children, self._final_paths.get_paths(children)))
            children.sort(key=paths.get)
            todo.extend(reversed(children))
            for trans_id in children:
                yield trans_id, paths[trans_id][0]

    def revision_tree(self, revision_id):
        return self._transform._tree.revision_tree(revision_id)

    def _stat_limbo_file(self, trans_id):
        name = self._transform._limbo_name(trans_id)
        return os.lstat(name)

    def git_snapshot(self, want_unversioned=False):
        extra = set()
        os = []
        for trans_id, path in self._list_files_by_dir():
            if not self._transform.final_is_versioned(trans_id):
                if not want_unversioned:
                    continue
                extra.add(path)
            o, mode = self._transform.final_git_entry(trans_id)
            if o is not None:
                self.store.add_object(o)
                os.append((encode_git_path(path), o.id, mode))
        if not os:
            return None, extra
        return commit_tree(self.store, os), extra

    def iter_child_entries(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise _mod_transport.NoSuchFile(path)
        for _child_trans_id in self._all_children(trans_id):
            entry, is_versioned = self._transform.final_entry(trans_id)
            if not is_versioned:
                continue
            if entry is not None:
                yield entry

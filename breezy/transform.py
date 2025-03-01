# Copyright (C) 2006-2011 Canonical Ltd
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

import contextlib
import errno
import os
from typing import Callable

from . import config as _mod_config
from . import errors, lazy_import, lock, osutils, registry, trace

lazy_import.lazy_import(
    globals(),
    """
from breezy import (
    ui,
    )
from breezy.i18n import gettext
""",
)

from .errors import BzrError, DuplicateKey, InternalBzrError
from .filters import ContentFilterContext, filtered_output_bytes
from .osutils import delete_any, pathjoin
from .progress import ProgressPhase
from .transport import FileExists, NoSuchFile
from .tree import InterTree

ROOT_PARENT = "root-parent"


class NoFinalPath(BzrError):
    _fmt = "No final name for trans_id %(trans_id)r\nroot trans-id: %(root_trans_id)r\n"

    def __init__(self, trans_id, transform):
        self.trans_id = trans_id
        self.root_trans_id = transform.root


class ReusingTransform(BzrError):
    _fmt = "Attempt to reuse a transform that has already been applied."


class MalformedTransform(InternalBzrError):
    _fmt = "Tree transform is malformed %(conflicts)r"


class CantMoveRoot(BzrError):
    _fmt = "Moving the root directory is not supported at this time"


class ImmortalLimbo(BzrError):
    _fmt = """Unable to delete transform temporary directory %(limbo_dir)s.
    Please examine %(limbo_dir)s to see if it contains any files you wish to
    keep, and delete it when you are done."""

    def __init__(self, limbo_dir):
        BzrError.__init__(self)
        self.limbo_dir = limbo_dir


class TransformRenameFailed(BzrError):
    _fmt = "Failed to rename %(from_path)s to %(to_path)s: %(why)s"

    def __init__(self, from_path, to_path, why, errno):
        self.from_path = from_path
        self.to_path = to_path
        self.why = why
        self.errno = errno


def unique_add(map, key, value):
    if key in map:
        raise DuplicateKey(key=key)
    map[key] = value


class _TransformResults:
    def __init__(self, modified_paths, rename_count):
        object.__init__(self)
        self.modified_paths = modified_paths
        self.rename_count = rename_count


class TreeTransform:
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

    trans_ids are only valid for the TreeTransform that generated them.
    """

    def __init__(self, tree, pb=None):
        self._tree = tree
        # A progress bar
        self._pb = pb
        self._id_number = 0
        # Mapping of path in old tree -> trans_id
        self._tree_path_ids = {}
        # Mapping trans_id -> path in old tree
        self._tree_id_paths = {}
        # mapping of trans_id -> new basename
        self._new_name = {}
        # mapping of trans_id -> new parent trans_id
        self._new_parent = {}
        # mapping of trans_id with new contents -> new file_kind
        self._new_contents = {}
        # Set of trans_ids whose contents will be removed
        self._removed_contents = set()
        # Mapping of trans_id -> new execute-bit value
        self._new_executability = {}
        # Mapping of trans_id -> new tree-reference value
        self._new_reference_revision = {}
        # Set of trans_ids that will be removed
        self._removed_id = set()
        # Indicator of whether the transform has been applied
        self._done = False

    def __enter__(self):
        """Support Context Manager API."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support Context Manager API."""
        self.finalize()

    def iter_tree_children(self, trans_id):
        """Iterate through the entry's tree children, if any.

        :param trans_id: trans id to iterate
        :returns: Iterator over paths
        """
        raise NotImplementedError(self.iter_tree_children)

    def canonical_path(self, path):
        return path

    def tree_kind(self, trans_id):
        raise NotImplementedError(self.tree_kind)

    def by_parent(self):
        """Return a map of parent: children for known parents.

        Only new paths and parents of tree files with assigned ids are used.
        """
        by_parent = {}
        items = list(self._new_parent.items())
        items.extend((t, self.final_parent(t)) for t in list(self._tree_id_paths))
        for trans_id, parent_id in items:
            if parent_id not in by_parent:
                by_parent[parent_id] = set()
            by_parent[parent_id].add(trans_id)
        return by_parent

    def finalize(self):
        """Release the working tree lock, if held.

        This is required if apply has not been invoked, but can be invoked
        even after apply.
        """
        raise NotImplementedError(self.finalize)

    def create_path(self, name, parent):
        """Assign a transaction id to a new path."""
        trans_id = self.assign_id()
        unique_add(self._new_name, trans_id, name)
        unique_add(self._new_parent, trans_id, parent)
        return trans_id

    def adjust_path(self, name, parent, trans_id):
        """Change the path that is assigned to a transaction id."""
        if parent is None:
            raise ValueError("Parent trans-id may not be None")
        if trans_id == self.root:
            raise CantMoveRoot
        self._new_name[trans_id] = name
        self._new_parent[trans_id] = parent

    def adjust_root_path(self, name, parent):
        """Emulate moving the root by moving all children, instead.

        We do this by undoing the association of root's transaction id with the
        current tree.  This allows us to create a new directory with that
        transaction id.  We unversion the root directory and version the
        physically new directory, and hope someone versions the tree root
        later.
        """
        raise NotImplementedError(self.adjust_root_path)

    def fixup_new_roots(self):
        """Reinterpret requests to change the root directory.

        Instead of creating a root directory, or moving an existing directory,
        all the attributes and children of the new root are applied to the
        existing root directory.

        This means that the old root trans-id becomes obsolete, so it is
        recommended only to invoke this after the root trans-id has become
        irrelevant.
        """
        raise NotImplementedError(self.fixup_new_roots)

    def assign_id(self):
        """Produce a new tranform id."""
        new_id = "new-{}".format(self._id_number)
        self._id_number += 1
        return new_id

    def trans_id_tree_path(self, path):
        """Determine (and maybe set) the transaction ID for a tree path."""
        path = self.canonical_path(path)
        if path not in self._tree_path_ids:
            self._tree_path_ids[path] = self.assign_id()
            self._tree_id_paths[self._tree_path_ids[path]] = path
        return self._tree_path_ids[path]

    def get_tree_parent(self, trans_id):
        """Determine id of the parent in the tree."""
        path = self._tree_id_paths[trans_id]
        if path == "":
            return ROOT_PARENT
        return self.trans_id_tree_path(os.path.dirname(path))

    def delete_contents(self, trans_id):
        """Schedule the contents of a path entry for deletion."""
        kind = self.tree_kind(trans_id)
        if kind is not None:
            self._removed_contents.add(trans_id)

    def cancel_deletion(self, trans_id):
        """Cancel a scheduled deletion."""
        self._removed_contents.remove(trans_id)

    def delete_versioned(self, trans_id):
        """Delete and unversion a versioned file."""
        self.delete_contents(trans_id)
        self.unversion_file(trans_id)

    def set_executability(self, executability, trans_id):
        """Schedule setting of the 'execute' bit
        To unschedule, set to None.
        """
        if executability is None:
            del self._new_executability[trans_id]
        else:
            unique_add(self._new_executability, trans_id, executability)

    def set_tree_reference(self, revision_id, trans_id):
        """Set the reference associated with a directory."""
        unique_add(self._new_reference_revision, trans_id, revision_id)

    def version_file(self, trans_id, file_id=None):
        """Schedule a file to become versioned."""
        raise NotImplementedError(self.version_file)

    def cancel_versioning(self, trans_id):
        """Undo a previous versioning of a file."""
        raise NotImplementedError(self.cancel_versioning)

    def unversion_file(self, trans_id):
        """Schedule a path entry to become unversioned."""
        self._removed_id.add(trans_id)

    def new_paths(self, filesystem_only=False):
        """Determine the paths of all new and changed files.

        :param filesystem_only: if True, only calculate values for files
            that require renames or execute bit changes.
        """
        raise NotImplementedError(self.new_paths)

    def final_kind(self, trans_id):
        """Determine the final file kind, after any changes applied.

        :return: None if the file does not exist/has no contents.  (It is
            conceivable that a path would be created without the corresponding
            contents insertion command)
        """
        if trans_id in self._new_contents:
            if trans_id in self._new_reference_revision:
                return "tree-reference"
            return self._new_contents[trans_id]
        elif trans_id in self._removed_contents:
            return None
        else:
            return self.tree_kind(trans_id)

    def tree_path(self, trans_id):
        """Determine the tree path associated with the trans_id."""
        return self._tree_id_paths.get(trans_id)

    def final_is_versioned(self, trans_id):
        raise NotImplementedError(self.final_is_versioned)

    def final_parent(self, trans_id):
        """Determine the parent file_id, after any changes are applied.

        ROOT_PARENT is returned for the tree root.
        """
        try:
            return self._new_parent[trans_id]
        except KeyError:
            return self.get_tree_parent(trans_id)

    def final_name(self, trans_id):
        """Determine the final filename, after all changes are applied."""
        try:
            return self._new_name[trans_id]
        except KeyError:
            try:
                return os.path.basename(self._tree_id_paths[trans_id])
            except KeyError:
                raise NoFinalPath(trans_id, self)

    def path_changed(self, trans_id):
        """Return True if a trans_id's path has changed."""
        return (trans_id in self._new_name) or (trans_id in self._new_parent)

    def new_contents(self, trans_id):
        return trans_id in self._new_contents

    def find_raw_conflicts(self):
        """Find any violations of inventory or filesystem invariants."""
        raise NotImplementedError(self.find_raw_conflicts)

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
        raise NotImplementedError(self.new_file)

    def new_directory(self, name, parent_id, file_id=None):
        """Convenience method to create directories.

        name is the name of the directory to create.
        parent_id is the transaction id of the parent directory of the
        directory.
        file_id is the inventory ID of the directory, if it is to be versioned.
        """
        raise NotImplementedError(self.new_directory)

    def new_symlink(self, name, parent_id, target, file_id=None):
        """Convenience method to create symbolic link.

        name is the name of the symlink to create.
        parent_id is the transaction id of the parent directory of the symlink.
        target is a bytestring of the target of the symlink.
        file_id is the inventory ID of the file, if it is to be versioned.
        """
        raise NotImplementedError(self.new_symlink)

    def new_orphan(self, trans_id, parent_id):
        """Schedule an item to be orphaned.

        When a directory is about to be removed, its children, if they are not
        versioned are moved out of the way: they don't have a parent anymore.

        :param trans_id: The trans_id of the existing item.
        :param parent_id: The parent trans_id of the item.
        """
        raise NotImplementedError(self.new_orphan)

    def iter_changes(self):
        """Produce output in the same format as Tree.iter_changes.

        Will produce nonsensical results if invoked while inventory/filesystem
        conflicts (as reported by TreeTransform.find_raw_conflicts()) are present.

        This reads the Transform, but only reproduces changes involving a
        file_id.  Files that are not versioned in either of the FROM or TO
        states are not reflected.
        """
        raise NotImplementedError(self.iter_changes)

    def get_preview_tree(self):
        """Return a tree representing the result of the transform.

        The tree is a snapshot, and altering the TreeTransform will invalidate
        it.
        """
        raise NotImplementedError(self.get_preview_tree)

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
        raise NotImplementedError(self.commit)

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

    def create_tree_reference(self, reference_revision, trans_id):
        raise NotImplementedError(self.create_tree_reference)

    def create_hardlink(self, path, trans_id):
        """Schedule creation of a hard link."""
        raise NotImplementedError(self.create_hardlink)

    def cancel_creation(self, trans_id):
        """Cancel the creation of new file contents."""
        raise NotImplementedError(self.cancel_creation)

    def cook_conflicts(self, raw_conflicts):
        """Cook conflicts."""
        raise NotImplementedError(self.cook_conflicts)


class OrphaningError(errors.BzrError):
    # Only bugs could lead to such exception being seen by the user
    internal_error = True
    _fmt = "Error while orphaning %s in %s directory"

    def __init__(self, orphan, parent):
        errors.BzrError.__init__(self)
        self.orphan = orphan
        self.parent = parent


class OrphaningForbidden(OrphaningError):
    _fmt = "Policy: %s doesn't allow creating orphans."

    def __init__(self, policy):
        errors.BzrError.__init__(self)
        self.policy = policy


def move_orphan(tt, orphan_id, parent_id):
    """See TreeTransformBase.new_orphan.

    This creates a new orphan in the `brz-orphans` dir at the root of the
    `TreeTransform`.

    :param tt: The TreeTransform orphaning `trans_id`.

    :param orphan_id: The trans id that should be orphaned.

    :param parent_id: The orphan parent trans id.
    """
    # Add the orphan dir if it doesn't exist
    orphan_dir_basename = "brz-orphans"
    od_id = tt.trans_id_tree_path(orphan_dir_basename)
    if tt.final_kind(od_id) is None:
        tt.create_directory(od_id)
    parent_path = tt._tree_id_paths[parent_id]
    # Find a name that doesn't exist yet in the orphan dir
    actual_name = tt.final_name(orphan_id)
    new_name = tt._available_backup_name(actual_name, od_id)
    tt.adjust_path(new_name, od_id, orphan_id)
    trace.warning(
        "{} has been orphaned in {}".format(joinpath(parent_path, actual_name), orphan_dir_basename)
    )


def refuse_orphan(tt, orphan_id, parent_id):
    """See TreeTransformBase.new_orphan.

    This refuses to create orphan, letting the caller handle the conflict.
    """
    raise OrphaningForbidden("never")


orphaning_registry = registry.Registry[
    str, Callable[[TreeTransform, bytes, bytes], None]
]()
orphaning_registry.register(
    "conflict",
    refuse_orphan,
    "Leave orphans in place and create a conflict on the directory.",
)
orphaning_registry.register(
    "move", move_orphan, "Move orphans into the brz-orphans directory."
)
orphaning_registry._set_default_key("conflict")


opt_transform_orphan = _mod_config.RegistryOption(
    "transform.orphan_policy",
    orphaning_registry,
    help="Policy for orphaned files during transform operations.",
    invalid="warning",
)


def joinpath(parent, child):
    """Join tree-relative paths, handling the tree root specially."""
    if parent is None or parent == "":
        return child
    else:
        return pathjoin(parent, child)


class FinalPaths:
    """Make path calculation cheap by memoizing paths.

    The underlying tree must not be manipulated between calls, or else
    the results will likely be incorrect.
    """

    def __init__(self, transform):
        object.__init__(self)
        self._known_paths = {}
        self.transform = transform

    def _determine_path(self, trans_id):
        if trans_id == self.transform.root or trans_id == ROOT_PARENT:
            return ""
        name = self.transform.final_name(trans_id)
        parent_id = self.transform.final_parent(trans_id)
        if parent_id == self.transform.root:
            return name
        else:
            return pathjoin(self.get_path(parent_id), name)

    def get_path(self, trans_id):
        """Find the final path associated with a trans_id."""
        if trans_id not in self._known_paths:
            self._known_paths[trans_id] = self._determine_path(trans_id)
        return self._known_paths[trans_id]

    def get_paths(self, trans_ids):
        return [(self.get_path(t), t) for t in trans_ids]


def _reparent_children(tt, old_parent, new_parent):
    for child in tt.iter_tree_children(old_parent):
        tt.adjust_path(tt.final_name(child), new_parent, child)


def _reparent_transform_children(tt, old_parent, new_parent):
    by_parent = tt.by_parent()
    for child in by_parent[old_parent]:
        tt.adjust_path(tt.final_name(child), new_parent, child)
    return by_parent[old_parent]


def new_by_entry(path, tt, entry, parent_id, tree):
    """Create a new file according to its inventory entry."""
    name = entry.name
    kind = entry.kind
    if kind == "file":
        with tree.get_file(path) as f:
            executable = tree.is_executable(path)
            return tt.new_file(
                name, parent_id, osutils.file_iterator(f), entry.file_id, executable
            )
    elif kind in ("directory", "tree-reference"):
        trans_id = tt.new_directory(name, parent_id, entry.file_id)
        if kind == "tree-reference":
            tt.set_tree_reference(entry.reference_revision, trans_id)
        return trans_id
    elif kind == "symlink":
        target = tree.get_symlink_target(path)
        return tt.new_symlink(name, parent_id, target, entry.file_id)
    else:
        raise errors.BadFileKindError(name, kind)


def create_from_tree(tt, trans_id, tree, path, chunks=None, filter_tree_path=None):
    """Create new file contents according to tree contents.

    :param filter_tree_path: the tree path to use to lookup
      content filters to apply to the bytes output in the working tree.
      This only applies if the working tree supports content filtering.
    """
    kind = tree.kind(path)
    if kind == "directory":
        tt.create_directory(trans_id)
    elif kind == "file":
        if chunks is None:
            f = tree.get_file(path)
            chunks = osutils.file_iterator(f)
        else:
            f = None
        try:
            wt = tt._tree
            if wt.supports_content_filtering() and filter_tree_path is not None:
                filters = wt._content_filter_stack(filter_tree_path)
                chunks = filtered_output_bytes(
                    chunks, filters, ContentFilterContext(filter_tree_path, tree)
                )
            tt.create_file(chunks, trans_id)
        finally:
            if f is not None:
                f.close()
    elif kind == "symlink":
        tt.create_symlink(tree.get_symlink_target(path), trans_id)
    elif kind == "tree-reference":
        tt.create_tree_reference(tree.get_reference_revision(path), trans_id)
    else:
        raise AssertionError("Unknown kind {!r}".format(kind))


def create_entry_executability(tt, entry, trans_id):
    """Set the executability of a trans_id according to an inventory entry."""
    if entry.kind == "file":
        tt.set_executability(entry.executable, trans_id)


def _prepare_revert_transform(
    es,
    working_tree,
    target_tree,
    tt,
    filenames,
    backups,
    pp,
    basis_tree=None,
    merge_modified=None,
):
    with ui.ui_factory.nested_progress_bar() as child_pb:
        if merge_modified is None:
            merge_modified = working_tree.merge_modified()
        merge_modified = _alter_files(
            es,
            working_tree,
            target_tree,
            tt,
            child_pb,
            filenames,
            backups,
            merge_modified,
            basis_tree,
        )
    with ui.ui_factory.nested_progress_bar() as child_pb:
        raw_conflicts = resolve_conflicts(
            tt, child_pb, lambda t, c: conflict_pass(t, c, target_tree)
        )
    conflicts = tt.cook_conflicts(raw_conflicts)
    return conflicts, merge_modified


def revert(
    working_tree,
    target_tree,
    filenames=None,
    backups=False,
    pb=None,
    change_reporter=None,
    merge_modified=None,
    basis_tree=None,
):
    """Revert a working tree's contents to those of a target tree."""
    with contextlib.ExitStack() as es:
        pb = es.enter_context(ui.ui_factory.nested_progress_bar())
        es.enter_context(target_tree.lock_read())
        tt = es.enter_context(working_tree.transform(pb))
        pp = ProgressPhase("Revert phase", 3, pb)
        conflicts, merge_modified = _prepare_revert_transform(
            es, working_tree, target_tree, tt, filenames, backups, pp
        )
        if change_reporter:
            from . import delta

            change_reporter = delta._ChangeReporter(
                unversioned_filter=working_tree.is_ignored
            )
            delta.report_changes(tt.iter_changes(), change_reporter)
        for conflict in conflicts:
            trace.warning(str(conflict))
        pp.next_phase()
        tt.apply()
        if working_tree.supports_merge_modified():
            working_tree.set_merge_modified(merge_modified)
    return conflicts


def _alter_files(
    es,
    working_tree,
    target_tree,
    tt,
    pb,
    specific_files,
    backups,
    merge_modified,
    basis_tree=None,
):
    if basis_tree is not None:
        es.enter_context(basis_tree.lock_read())
    # We ask the working_tree for its changes relative to the target, rather
    # than the target changes relative to the working tree. Because WT4 has an
    # optimizer to compare itself to a target, but no optimizer for the
    # reverse.
    change_list = working_tree.iter_changes(
        target_tree, specific_files=specific_files, pb=pb
    )
    if not target_tree.is_versioned(""):
        skip_root = True
    else:
        skip_root = False
    deferred_files = []
    for _id_num, change in enumerate(change_list):
        target_path, wt_path = change.path
        target_versioned, wt_versioned = change.versioned
        target_name, wt_name = change.name
        target_kind, wt_kind = change.kind
        target_executable, wt_executable = change.executable
        if skip_root and wt_path == "":
            continue
        mode_id = None
        if wt_path is not None:
            trans_id = tt.trans_id_tree_path(wt_path)
        else:
            trans_id = tt.assign_id()
        if change.changed_content:
            keep_content = False
            if wt_kind == "file" and (backups or target_kind is None):
                wt_sha1 = working_tree.get_file_sha1(wt_path)
                if merge_modified.get(wt_path) != wt_sha1:
                    # acquire the basis tree lazily to prevent the
                    # expense of accessing it when it's not needed ?
                    # (Guessing, RBC, 200702)
                    if basis_tree is None:
                        basis_tree = working_tree.basis_tree()
                        es.enter_context(basis_tree.lock_read())
                    basis_inter = InterTree.get(basis_tree, working_tree)
                    basis_path = basis_inter.find_source_path(wt_path)
                    if basis_path is None:
                        if target_kind is None and not target_versioned:
                            keep_content = True
                    else:
                        if wt_sha1 != basis_tree.get_file_sha1(basis_path):
                            keep_content = True
            if wt_kind is not None:
                if not keep_content:
                    tt.delete_contents(trans_id)
                elif target_kind is not None:
                    parent_trans_id = tt.trans_id_tree_path(osutils.dirname(wt_path))
                    backup_name = tt._available_backup_name(wt_name, parent_trans_id)
                    tt.adjust_path(backup_name, parent_trans_id, trans_id)
                    new_trans_id = tt.create_path(wt_name, parent_trans_id)
                    if wt_versioned and target_versioned:
                        tt.unversion_file(trans_id)
                        tt.version_file(
                            new_trans_id, file_id=getattr(change, "file_id", None)
                        )
                    # New contents should have the same unix perms as old
                    # contents
                    mode_id = trans_id
                    trans_id = new_trans_id
            if target_kind in ("directory", "tree-reference"):
                tt.create_directory(trans_id)
                if target_kind == "tree-reference":
                    revision = target_tree.get_reference_revision(target_path)
                    tt.set_tree_reference(revision, trans_id)
            elif target_kind == "symlink":
                tt.create_symlink(target_tree.get_symlink_target(target_path), trans_id)
            elif target_kind == "file":
                deferred_files.append((target_path, (trans_id, mode_id, target_path)))
                if basis_tree is None:
                    basis_tree = working_tree.basis_tree()
                    es.enter_context(basis_tree.lock_read())
                new_sha1 = target_tree.get_file_sha1(target_path)
                basis_inter = InterTree.get(basis_tree, target_tree)
                basis_path = basis_inter.find_source_path(target_path)
                if basis_path is not None and new_sha1 == basis_tree.get_file_sha1(
                    basis_path
                ):
                    # If the new contents of the file match what is in basis,
                    # then there is no need to store in merge_modified.
                    if basis_path in merge_modified:
                        del merge_modified[basis_path]
                else:
                    merge_modified[target_path] = new_sha1

                # preserve the execute bit when backing up
                if keep_content and wt_executable == target_executable:
                    tt.set_executability(target_executable, trans_id)
            elif target_kind is not None:
                raise AssertionError(target_kind)
        if not wt_versioned and target_versioned:
            tt.version_file(trans_id, file_id=getattr(change, "file_id", None))
        if wt_versioned and not target_versioned:
            tt.unversion_file(trans_id)
        if target_name is not None and (
            wt_name != target_name or change.is_reparented()
        ):
            if target_path == "":
                parent_trans = ROOT_PARENT
            else:
                target_parent = change.parent_id[0]
                parent_trans = tt.trans_id_file_id(target_parent)
            if wt_path == "" and wt_versioned:
                tt.adjust_root_path(target_name, parent_trans)
            else:
                tt.adjust_path(target_name, parent_trans, trans_id)
        if wt_executable != target_executable and target_kind == "file":
            tt.set_executability(target_executable, trans_id)
    if working_tree.supports_content_filtering():
        for (trans_id, mode_id, target_path), bytes in target_tree.iter_files_bytes(
            deferred_files
        ):
            # We're reverting a tree to the target tree so using the
            # target tree to find the file path seems the best choice
            # here IMO - Ian C 27/Oct/2009
            filters = working_tree._content_filter_stack(target_path)
            bytes = filtered_output_bytes(
                bytes, filters, ContentFilterContext(target_path, working_tree)
            )
            tt.create_file(bytes, trans_id, mode_id)
    else:
        for (trans_id, mode_id, target_path), bytes in target_tree.iter_files_bytes(
            deferred_files
        ):
            tt.create_file(bytes, trans_id, mode_id)
    tt.fixup_new_roots()
    return merge_modified


def resolve_conflicts(tt, pb=None, pass_func=None):
    """Make many conflict-resolution attempts, but die if they fail."""
    if pass_func is None:
        pass_func = conflict_pass
    new_conflicts = set()
    with ui.ui_factory.nested_progress_bar() as pb:
        for n in range(10):
            pb.update(gettext("Resolution pass"), n + 1, 10)
            conflicts = tt.find_raw_conflicts()
            if len(conflicts) == 0:
                return new_conflicts
            new_conflicts.update(pass_func(tt, conflicts))
        raise MalformedTransform(conflicts=conflicts)


def resolve_duplicate_id(tt, path_tree, c_type, old_trans_id, trans_id):
    tt.unversion_file(old_trans_id)
    yield (c_type, "Unversioned existing file", old_trans_id, trans_id)


def resolve_duplicate(tt, path_tree, c_type, last_trans_id, trans_id, name):
    # files that were renamed take precedence
    final_parent = tt.final_parent(last_trans_id)
    if tt.path_changed(last_trans_id):
        existing_file, new_file = trans_id, last_trans_id
    else:
        existing_file, new_file = last_trans_id, trans_id
    if (
        not tt._tree.has_versioned_directories()
        and tt.final_kind(trans_id) == "directory"
        and tt.final_kind(last_trans_id) == "directory"
    ):
        _reparent_transform_children(tt, existing_file, new_file)
        tt.delete_contents(existing_file)
        tt.unversion_file(existing_file)
        tt.cancel_creation(existing_file)
    else:
        new_name = tt.final_name(existing_file) + ".moved"
        tt.adjust_path(new_name, final_parent, existing_file)
        yield (c_type, "Moved existing file to", existing_file, new_file)


def resolve_parent_loop(tt, path_tree, c_type, cur):
    # break the loop by undoing one of the ops that caused the loop
    while not tt.path_changed(cur):
        cur = tt.final_parent(cur)
    yield (
        c_type,
        "Cancelled move",
        cur,
        tt.final_parent(cur),
    )
    tt.adjust_path(tt.final_name(cur), tt.get_tree_parent(cur), cur)


def resolve_missing_parent(tt, path_tree, c_type, trans_id):
    if trans_id in tt._removed_contents:
        cancel_deletion = True
        orphans = tt._get_potential_orphans(trans_id)
        if orphans:
            cancel_deletion = False
            # All children are orphans
            for o in orphans:
                try:
                    tt.new_orphan(o, trans_id)
                except OrphaningError:
                    # Something bad happened so we cancel the directory
                    # deletion which will leave it in place with a
                    # conflict. The user can deal with it from there.
                    # Note that this also catch the case where we don't
                    # want to create orphans and leave the directory in
                    # place.
                    cancel_deletion = True
                    break
        if cancel_deletion:
            # Cancel the directory deletion
            tt.cancel_deletion(trans_id)
            yield ("deleting parent", "Not deleting", trans_id)
    else:
        create = True
        try:
            tt.final_name(trans_id)
        except NoFinalPath:
            if path_tree is not None:
                file_id = tt.final_file_id(trans_id)
                if file_id is None:
                    file_id = tt.inactive_file_id(trans_id)
                _, entry = next(
                    path_tree.iter_entries_by_dir(
                        specific_files=[path_tree.id2path(file_id)]
                    )
                )
                # special-case the other tree root (move its
                # children to current root)
                if entry.parent_id is None:
                    create = False
                    moved = _reparent_transform_children(tt, trans_id, tt.root)
                    for child in moved:
                        yield (c_type, "Moved to root", child)
                else:
                    parent_trans_id = tt.trans_id_file_id(entry.parent_id)
                    tt.adjust_path(entry.name, parent_trans_id, trans_id)
        if create:
            tt.create_directory(trans_id)
            yield (c_type, "Created directory", trans_id)


def resolve_unversioned_parent(tt, path_tree, c_type, trans_id):
    file_id = tt.inactive_file_id(trans_id)
    # special-case the other tree root (move its children instead)
    if path_tree and path_tree.path2id("") == file_id:
        # This is the root entry, skip it
        return
    tt.version_file(trans_id, file_id=file_id)
    yield (c_type, "Versioned directory", trans_id)


def resolve_non_directory_parent(tt, path_tree, c_type, parent_id):
    parent_parent = tt.final_parent(parent_id)
    parent_name = tt.final_name(parent_id)
    # TODO(jelmer): Make this code transform-specific
    if tt._tree.supports_setting_file_ids():
        parent_file_id = tt.final_file_id(parent_id)
    else:
        parent_file_id = b"DUMMY"
    new_parent_id = tt.new_directory(
        parent_name + ".new", parent_parent, parent_file_id
    )
    _reparent_transform_children(tt, parent_id, new_parent_id)
    if parent_file_id is not None:
        tt.unversion_file(parent_id)
    yield (c_type, "Created directory", new_parent_id)


def resolve_versioning_no_contents(tt, path_tree, c_type, trans_id):
    tt.cancel_versioning(trans_id)
    return []


CONFLICT_RESOLVERS = {
    "duplicate id": resolve_duplicate_id,
    "duplicate": resolve_duplicate,
    "parent loop": resolve_parent_loop,
    "missing parent": resolve_missing_parent,
    "unversioned parent": resolve_unversioned_parent,
    "non-directory parent": resolve_non_directory_parent,
    "versioning no contents": resolve_versioning_no_contents,
}


def conflict_pass(tt, conflicts, path_tree=None):
    """Resolve some classes of conflicts.

    :param tt: The transform to resolve conflicts in
    :param conflicts: The conflicts to resolve
    :param path_tree: A Tree to get supplemental paths from
    """
    new_conflicts = set()
    for conflict in conflicts:
        resolver = CONFLICT_RESOLVERS.get(conflict[0])
        if resolver is None:
            continue
        new_conflicts.update(resolver(tt, path_tree, *conflict))
    return new_conflicts


class _FileMover:
    """Moves and deletes files for TreeTransform, tracking operations."""

    def __init__(self):
        self.past_renames = []
        self.pending_deletions = []

    def rename(self, from_, to):
        """Rename a file from one path to another."""
        try:
            os.rename(from_, to)
        except OSError as e:
            if e.errno in (errno.EEXIST, errno.ENOTEMPTY):
                raise FileExists(to, str(e))
            # normal OSError doesn't include filenames so it's hard to see where
            # the problem is, see https://bugs.launchpad.net/bzr/+bug/491763
            raise TransformRenameFailed(from_, to, str(e), e.errno)
        self.past_renames.append((from_, to))

    def pre_delete(self, from_, to):
        """Rename a file out of the way and mark it for deletion.

        Unlike os.unlink, this works equally well for files and directories.
        :param from_: The current file path
        :param to: A temporary path for the file
        """
        self.rename(from_, to)
        self.pending_deletions.append(to)

    def rollback(self):
        """Reverse all renames that have been performed."""
        for from_, to in reversed(self.past_renames):
            try:
                os.rename(to, from_)
            except OSError as e:
                raise TransformRenameFailed(to, from_, str(e), e.errno)
        # after rollback, don't reuse _FileMover
        self.past_renames = None
        self.pending_deletions = None

    def apply_deletions(self):
        """Apply all marked deletions."""
        for path in self.pending_deletions:
            delete_any(path)
        # after apply_deletions, don't reuse _FileMover
        self.past_renames = None
        self.pending_deletions = None


def link_tree(target_tree, source_tree):
    """Where possible, hard-link files in a tree to those in another tree.

    :param target_tree: Tree to change
    :param source_tree: Tree to hard-link from
    """
    with target_tree.transform() as tt:
        for change in target_tree.iter_changes(source_tree, include_unchanged=True):
            if change.changed_content:
                continue
            if change.kind != ("file", "file"):
                continue
            if change.executable[0] != change.executable[1]:
                continue
            trans_id = tt.trans_id_tree_path(change.path[1])
            tt.delete_contents(trans_id)
            tt.create_hardlink(source_tree.abspath(change.path[0]), trans_id)
        tt.apply()


class PreviewTree:
    """Preview tree."""

    def __init__(self, transform):
        self._transform = transform
        self._parent_ids = []
        self.__by_parent = None
        self._path2trans_id_cache = {}
        self._all_children_cache = {}
        self._final_name_cache = {}

    def supports_setting_file_ids(self):
        raise NotImplementedError(self.supports_setting_file_ids)

    def supports_symlinks(self):
        return self._transform._tree.supports_symlinks()

    @property
    def _by_parent(self):
        if self.__by_parent is None:
            self.__by_parent = self._transform.by_parent()
        return self.__by_parent

    def get_parent_ids(self):
        return self._parent_ids

    def set_parent_ids(self, parent_ids):
        self._parent_ids = parent_ids

    def get_revision_tree(self, revision_id):
        return self._transform._tree.get_revision_tree(revision_id)

    def is_locked(self):
        return False

    def lock_read(self):
        # Perhaps in theory, this should lock the TreeTransform?
        return lock.LogicalLockResult(self.unlock)

    def unlock(self):
        pass

    def _path2trans_id(self, path):
        """Look up the trans id associated with a path.

        :param path: path to look up, None when the path does not exist
        :return: trans_id
        """
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

    def get_file_with_stat(self, path):
        return self.get_file(path), None

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
            except NoSuchFile:
                return False

    def has_filename(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id in self._transform._new_contents:
            return True
        elif trans_id in self._transform._removed_contents:
            return False
        else:
            return self._transform._tree.has_filename(path)

    def get_file_sha1(self, path, stat_value=None):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise NoSuchFile(path)
        kind = self._transform._new_contents.get(trans_id)
        if kind is None:
            return self._transform._tree.get_file_sha1(path)
        if kind == "file":
            with self.get_file(path) as fileobj:
                return osutils.sha_file(fileobj)

    def get_file_verifier(self, path, stat_value=None):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise NoSuchFile(path)
        kind = self._transform._new_contents.get(trans_id)
        if kind is None:
            return self._transform._tree.get_file_verifier(path)
        if kind == "file":
            with self.get_file(path) as fileobj:
                return ("SHA1", osutils.sha_file(fileobj))

    def kind(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise NoSuchFile(path)
        return self._transform.final_kind(trans_id)

    def stored_kind(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise NoSuchFile(path)
        try:
            return self._transform._new_contents[trans_id]
        except KeyError:
            return self._transform._tree.stored_kind(path)

    def _get_repository(self):
        repo = getattr(self._transform._tree, "_repository", None)
        if repo is None:
            repo = self._transform._tree.branch.repository
        return repo

    def _iter_parent_trees(self):
        for revision_id in self.get_parent_ids():
            try:
                yield self.revision_tree(revision_id)
            except errors.NoSuchRevisionInTree:
                yield self._get_repository().revision_tree(revision_id)

    def get_file_size(self, path):
        """See Tree.get_file_size."""
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise NoSuchFile(path)
        kind = self._transform.final_kind(trans_id)
        if kind != "file":
            return None
        if trans_id in self._transform._new_contents:
            return self._stat_limbo_file(trans_id).st_size
        if self.kind(path) == "file":
            return self._transform._tree.get_file_size(path)
        else:
            return None

    def get_reference_revision(self, path):
        trans_id = self._path2trans_id(path)
        if trans_id is None:
            raise NoSuchFile(path)
        reference_revision = self._transform._new_reference_revision.get(trans_id)
        if reference_revision is None:
            return self._transform._tree.get_reference_revision(path)
        return reference_revision

    def tree_kind(self, trans_id):
        path = self._tree_id_paths.get(trans_id)
        if path is None:
            return None
        kind = self._tree.path_content_summary(path)[0]
        if kind == "missing":
            kind = None
        return kind

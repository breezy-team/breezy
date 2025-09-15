# Copyright (C) 2007-2012 Canonical Ltd
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

"""WorkingTree4 format and implementation.

WorkingTree4 provides the dirstate based working tree logic.

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""

import os
from io import BytesIO

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import contextlib
import stat

from breezy import (
    branch as _mod_branch,
    controldir,
    filters as _mod_filters,
    revisiontree,
    views,
    )
from breezy.bzr import (
    generate_ids,
    transform as bzr_transform,
    )
""",
)

import contextlib

from .. import cache_utf8, debug, errors, osutils, trace
from .. import revision as _mod_revision
from ..lock import LogicalLockResult
from ..lockdir import LockDir
from ..mutabletree import BadReferenceTarget, MutableTree
from ..osutils import isdir, pathjoin, realpath, safe_unicode
from ..transport import NoSuchFile, get_transport_from_path
from ..transport.local import file_kind
from ..tree import FileTimestampUnavailable, InterTree, MissingNestedTree
from ..workingtree import WorkingTree
from . import dirstate
from .inventory import (
    ROOT_ID,
    DuplicateFileId,
    Inventory,
    InventoryDirectory,
    InventoryEntry,
    InventoryFile,
    InventoryLink,
    TreeReference,
    _make_delta,
)
from .inventory_delta import InventoryDelta
from .inventorytree import InterInventoryTree, InventoryRevisionTree, InventoryTree
from .lockable_files import LockableFiles
from .workingtree import InventoryWorkingTree, WorkingTreeFormatMetaDir


class DirStateWorkingTree(InventoryWorkingTree):
    """A working tree that uses a dirstate for efficient state tracking.

    This implementation uses a dirstate file to track the state of files
    in the working tree, providing improved performance over earlier formats.
    """

    def __init__(
        self, basedir, branch, _control_files=None, _format=None, _controldir=None
    ):
        """Construct a WorkingTree for basedir.

        If the branch is not supplied, it is opened automatically.
        If the branch is supplied, it must be the branch for this basedir.
        (branch.base is not cross checked, because for remote branches that
        would be meaningless).
        """
        self._format = _format
        self.controldir = _controldir
        basedir = safe_unicode(basedir)
        trace.mutter("opening working tree %r", basedir)
        self._branch = branch
        self.basedir = realpath(basedir)
        # if branch is at our basedir and is a format 6 or less
        # assume all other formats have their own control files.
        self._control_files = _control_files
        self._transport = self._control_files._transport
        self._dirty = None
        # -------------
        # during a read or write lock these objects are set, and are
        # None the rest of the time.
        self._dirstate = None
        self._inventory = None
        # -------------
        self._setup_directory_is_tree_reference()
        self._detect_case_handling()
        self._rules_searcher = None
        self.views = self._make_views()
        # --- allow tests to select the dirstate iter_changes implementation
        self._iter_changes = dirstate._process_entry
        self._repo_supports_tree_reference = getattr(
            self._branch.repository._format, "supports_tree_reference", False
        )

    def _add(self, files, kinds, ids):
        """See MutableTree._add."""
        with self.lock_tree_write():
            state = self.current_dirstate()
            for f, file_id, kind in zip(files, ids, kinds):
                f = f.strip("/")
                if self.path2id(f):
                    # special case tree root handling.
                    if f == b"" and self.path2id(f) == ROOT_ID:
                        state.set_path_id(b"", generate_ids.gen_file_id(f))
                    continue
                if file_id is None:
                    file_id = generate_ids.gen_file_id(f)
                # deliberately add the file with no cached stat or sha1
                # - on the first access it will be gathered, and we can
                # always change this once tests are all passing.
                state.add(f, file_id, kind, None, b"")
            self._make_dirty(reset_inventory=True)

    def _get_check_refs(self):
        """Return the references needed to perform a check of this tree."""
        return [("trees", self.last_revision())]

    def _make_dirty(self, reset_inventory):
        """Make the tree state dirty.

        :param reset_inventory: True if the cached inventory should be removed
            (presuming there is one).
        """
        self._dirty = True
        if reset_inventory and self._inventory is not None:
            self._inventory = None

    def add_reference(self, sub_tree):
        """Add a tree reference to a subtree.

        Args:
            sub_tree: The working tree to add as a reference.

        Raises:
            BadReferenceTarget: If the subtree is not a valid reference target.
        """
        # use standard implementation, which calls back to self._add
        #
        # So we don't store the reference_revision in the working dirstate,
        # it's just recorded at the moment of commit.
        with self.lock_tree_write():
            try:
                sub_tree_path = self.relpath(sub_tree.basedir)
            except errors.PathNotChild as e:
                raise BadReferenceTarget(
                    self, sub_tree, "Target not inside tree."
                ) from e
            sub_tree_id = sub_tree.path2id("")
            if sub_tree_id == self.path2id(""):
                raise BadReferenceTarget(self, sub_tree, "Trees have the same root id.")
            try:
                self.id2path(sub_tree_id)
            except errors.NoSuchId:
                pass
            else:
                raise BadReferenceTarget(
                    self, sub_tree, "Root id already present in tree"
                )
            self._add([sub_tree_path], ["tree-reference"], [sub_tree_id])

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        # if the dirstate is locked by an active process, reject the break lock
        # call.
        try:
            clear = self._dirstate is None
            state = self._current_dirstate()
            if state._lock_token is not None:
                # we already have it locked. sheese, cant break our own lock.
                raise errors.LockActive(self.basedir)
            else:
                try:
                    # try for a write lock - need permission to get one anyhow
                    # to break locks.
                    state.lock_write()
                except errors.LockContention as err:
                    # oslocks fail when a process is still live: fail.
                    # TODO: get the locked lockdir info and give to the user to
                    # assist in debugging.
                    raise errors.LockActive(self.basedir) from err
                else:
                    state.unlock()
        finally:
            if clear:
                self._dirstate = None
        self._control_files.break_lock()
        self.branch.break_lock()

    def _comparison_data(self, entry, path):
        kind, executable, stat_value = WorkingTree._comparison_data(self, entry, path)
        # it looks like a plain directory, but it's really a reference -- see
        # also kind()
        if (
            self._repo_supports_tree_reference
            and kind == "directory"
            and entry is not None
            and entry.kind == "tree-reference"
        ):
            kind = "tree-reference"
        return kind, executable, stat_value

    def commit(self, message=None, revprops=None, *args, **kwargs):
        """Create a new revision for the working tree.

        Args:
            message: Commit message string.
            revprops: Dictionary of revision properties.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            The new revision ID.
        """
        with self.lock_write():
            # mark the tree as dirty post commit - commit
            # can change the current versioned list by doing deletes.
            result = WorkingTree.commit(self, message, revprops, *args, **kwargs)
            self._make_dirty(reset_inventory=True)
            return result

    def current_dirstate(self):
        """Return the current dirstate object.

        This is not part of the tree interface and only exposed for ease of
        testing.

        :raises errors.NotWriteLocked: when not in a lock.
        """
        self._must_be_locked()
        return self._current_dirstate()

    def _current_dirstate(self):
        """Internal function that does not check lock status.

        This is needed for break_lock which also needs the dirstate.
        """
        if self._dirstate is not None:
            return self._dirstate
        local_path = self.controldir.get_workingtree_transport(None).local_abspath(
            "dirstate"
        )
        self._dirstate = dirstate.DirState.on_file(
            local_path,
            self._sha1_provider(),
            self._worth_saving_limit(),
            self._supports_executable(),
        )
        return self._dirstate

    def _sha1_provider(self):
        """A function that returns a SHA1Provider suitable for this tree.

        :return: None if content filtering is not supported by this tree.
          Otherwise, a SHA1Provider is returned that sha's the canonical
          form of files, i.e. after read filters are applied.
        """
        if self.supports_content_filtering():
            return ContentFilterAwareSHA1Provider(self)
        else:
            return None

    def _worth_saving_limit(self):
        """How many hash changes are ok before we must save the dirstate.

        :return: an integer. -1 means never save.
        """
        conf = self.get_config_stack()
        return conf.get("bzr.workingtree.worth_saving_limit")

    def filter_unversioned_files(self, paths):
        """Filter out paths that are versioned.

        :return: set of paths.
        """
        # TODO: make a generic multi-bisect routine roughly that should list
        # the paths, then process one half at a time recursively, and feed the
        # results of each bisect in further still
        paths = sorted(paths)
        result = set()
        state = self.current_dirstate()
        # TODO we want a paths_to_dirblocks helper I think
        for path in paths:
            dirname, basename = os.path.split(path.encode("utf8"))
            _, _, _, path_is_versioned = state._get_block_entry_index(
                dirname, basename, 0
            )
            if not path_is_versioned:
                result.add(path)
        return result

    def flush(self):
        """Write all cached data to disk."""
        if self._control_files._lock_mode != "w":
            raise errors.NotWriteLocked(self)
        self.current_dirstate().save()
        self._inventory = None
        self._dirty = False

    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds."""
        with self.lock_tree_write():
            for pos, f in enumerate(files):
                if kinds[pos] is None:
                    kinds[pos] = self.kind(f)

    def _generate_inventory(self) -> None:
        """Create and set self.inventory from the dirstate object.

        This is relatively expensive: we have to walk the entire dirstate.
        Ideally we would not, and can deprecate this function.
        """
        #: uncomment to trap on inventory requests.
        # import pdb;pdb.set_trace()
        state = self.current_dirstate()
        state._read_dirblocks_if_needed()
        root_key, current_entry = self._get_entry(path="")
        current_id = root_key[2]
        if not (current_entry[0][0] == b"d"):  # directory
            raise AssertionError(current_entry)
        inv = Inventory(root_id=current_id)
        # Turn some things into local variables
        minikind_to_kind = dirstate.DirState._minikind_to_kind
        utf8_decode = cache_utf8._utf8_decode
        # we could do this straight out of the dirstate; it might be fast
        # and should be profiled - RBC 20070216
        parent_ies: dict[bytes, InventoryEntry] = {b"": inv.root}
        for block in state._dirblocks[1:]:  # skip the root
            dirname = block[0]
            try:
                parent_ie = parent_ies[dirname]
            except KeyError:
                # all the paths in this block are not versioned in this tree
                continue
            for key, entry in block[1]:
                minikind, link_or_sha1, _size, executable, _stat = entry[0]
                if minikind in (b"a", b"r"):  # absent, relocated
                    # a parent tree only entry
                    continue
                name = key[1]
                name_unicode = utf8_decode(name)[0]
                file_id = key[2]
                kind = minikind_to_kind[minikind]
                if kind == "file":
                    # The executable bit is only needed on win32, where this is the only way
                    # we know the executable bit.
                    # the text {sha1,size} fields are optional
                    inv_entry = InventoryFile(
                        file_id,
                        name_unicode,
                        parent_ie.file_id,
                        revision=None,
                        executable=(executable != 0),
                    )
                elif kind == "directory":
                    inv_entry = InventoryDirectory(
                        file_id, name_unicode, parent_ie.file_id, revision=None
                    )
                    # add this entry to the parent map.
                    parent_ies[(dirname + b"/" + name).strip(b"/")] = inv_entry
                elif kind == "tree-reference":
                    inv_entry = TreeReference(
                        file_id,
                        name_unicode,
                        parent_ie.file_id,
                        revision=None,
                        reference_revision=link_or_sha1 or None,
                    )
                elif kind == "symlink":
                    inv_entry = InventoryLink(
                        file_id,
                        name_unicode,
                        parent_ie.file_id,
                        revision=None,
                        symlink_target=utf8_decode(link_or_sha1)[0],
                    )
                else:
                    raise AssertionError(f"unknown kind {kind!r}")
                try:
                    inv.add(inv_entry)
                except DuplicateFileId as err:
                    raise AssertionError(
                        f"file_id {file_id} already in"
                        f" inventory as {inv.get_entry(file_id)}"
                    ) from err
                except errors.InconsistentDelta as err:
                    raise AssertionError(
                        f"name {name_unicode!r} already in parent"
                    ) from err
        self._inventory = inv

    def _get_entry(self, file_id=None, path=None):
        """Get the dirstate row for file_id or path.

        If either file_id or path is supplied, it is used as the key to lookup.
        If both are supplied, the fastest lookup is used, and an error is
        raised if they do not both point at the same row.

        :param file_id: An optional unicode file_id to be looked up.
        :param path: An optional unicode path to be looked up.
        :return: The dirstate row tuple for path/file_id, or (None, None)
        """
        if file_id is None and path is None:
            raise errors.BzrError("must supply file_id or path")
        state = self.current_dirstate()
        if path is not None:
            path = path.encode("utf8")
        return state._get_entry(0, fileid_utf8=file_id, path_utf8=path)

    def get_file_sha1(self, path, stat_value=None):
        """Get the SHA1 hash of a file in the working tree.

        Args:
            path: The path to the file relative to the tree root.
            stat_value: Optional stat value to avoid re-statting the file.

        Returns:
            The SHA1 hash as a hex string, or None if not a regular file.

        Raises:
            NoSuchFile: If the path does not exist in the tree.
        """
        # check file id is valid unconditionally.
        entry = self._get_entry(path=path)
        if entry[0] is None:
            raise NoSuchFile(self, path)
        if path is None:
            path = pathjoin(entry[0][0], entry[0][1]).decode("utf8")

        file_abspath = self.abspath(path)
        state = self.current_dirstate()
        if stat_value is None:
            try:
                stat_value = osutils.lstat(file_abspath)
            except FileNotFoundError:
                return None
        link_or_sha1 = dirstate.update_entry(
            state, entry, file_abspath, stat_value=stat_value
        )
        if entry[1][0][0] == b"f":
            if link_or_sha1 is None:
                file_obj, statvalue = self.get_file_with_stat(path)
                try:
                    sha1 = osutils.sha_file(file_obj)
                finally:
                    file_obj.close()
                self._observed_sha1(path, (sha1, statvalue))
                return sha1
            else:
                return link_or_sha1
        return None

    def _get_root_inventory(self):
        """Get the inventory for the tree. This is only valid within a lock."""
        if debug.debug_flag_enabled("evil"):
            trace.mutter_callsite(
                2, "accessing .inventory forces a size of tree translation."
            )
        if self._inventory is not None:
            return self._inventory
        self._must_be_locked()
        self._generate_inventory()
        return self._inventory

    root_inventory = property(_get_root_inventory, doc="Root inventory of this tree")

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        This implementation requests the ids list from the dirstate file.
        """
        with self.lock_read():
            return self.current_dirstate().get_parent_ids()

    def get_reference_revision(self, path):
        """Get the revision ID of a tree reference.

        Args:
            path: The path to the tree reference.

        Returns:
            The revision ID of the referenced tree, or None.
        """
        # referenced tree's revision is whatever's currently there
        try:
            return self.get_nested_tree(path).last_revision()
        except MissingNestedTree as err:
            entry = self._get_entry(path=path)
            if entry == (None, None):
                raise NoSuchFile(self, path) from err
            return entry[1][0][1]

    def get_nested_tree(self, path):
        """Get the nested tree at the given path.

        Args:
            path: The path to the nested tree.

        Returns:
            The WorkingTree at the specified path.

        Raises:
            MissingNestedTree: If no tree exists at the path.
        """
        try:
            return WorkingTree.open(self.abspath(path))
        except errors.NotBranchError as err:
            raise MissingNestedTree(path) from err

    def id2path(self, file_id, recurse="down"):
        """Convert a file-id to a path."""
        with self.lock_read():
            self.current_dirstate()
            entry = self._get_entry(file_id=file_id)
            if entry == (None, None):
                if recurse == "down":
                    if debug.debug_flag_enabled("evil"):
                        trace.mutter_callsite(2, "Tree.id2path scans all nested trees.")
                    for nested_path in self.iter_references():
                        nested_tree = self.get_nested_tree(nested_path)
                        try:
                            return osutils.pathjoin(
                                nested_path, nested_tree.id2path(file_id)
                            )
                        except errors.NoSuchId:
                            pass
                raise errors.NoSuchId(tree=self, file_id=file_id)
            return osutils.pathjoin(entry[0][0], entry[0][1]).decode(
                "utf-8", "surrogateescape"
            )

    def _is_executable_from_path_and_stat_from_basis(self, path, stat_result):
        entry = self._get_entry(path=path)
        if entry == (None, None):
            return False  # Missing entries are not executable
        return entry[1][0][3]  # Executable?

    def is_executable(self, path):
        """Test if a file is executable or not.

        Note: The caller is expected to take a read-lock before calling this.
        """
        if not self._supports_executable():
            entry = self._get_entry(path=path)
            if entry == (None, None):
                return False
            return entry[1][0][3]
        else:
            self._must_be_locked()
            mode = osutils.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def all_file_ids(self):
        """See Tree.iter_all_file_ids."""
        self._must_be_locked()
        result = set()
        for key, tree_details in self.current_dirstate()._iter_entries():
            if tree_details[0][0] in (b"a", b"r"):  # relocated
                continue
            result.add(key[2])
        return result

    def all_versioned_paths(self):
        """Get all paths that are versioned in this tree.

        Returns:
            A set of all versioned paths.
        """
        self._must_be_locked()
        return {
            path for path, entry in self.root_inventory.iter_entries(recursive=True)
        }

    def __iter__(self):
        """Iterate through file_ids for this tree.

        file_ids are in a WorkingTree if they are in the working inventory
        and the working file exists.
        """
        with self.lock_read():
            result = []
            for key, tree_details in self.current_dirstate()._iter_entries():
                if tree_details[0][0] in (b"a", b"r"):  # absent, relocated
                    # not relevant to the working tree
                    continue
                path = pathjoin(
                    self.basedir, key[0].decode("utf8"), key[1].decode("utf8")
                )
                if osutils.lexists(path):
                    result.append(key[2])
            return iter(result)

    def iter_references(self):
        """Iterate over all tree references in the working tree.

        Yields:
            Relative paths to tree references.
        """
        if not self._repo_supports_tree_reference:
            # When the repo doesn't support references, we will have nothing to
            # return
            return
        with self.lock_read():
            for key, tree_details in self.current_dirstate()._iter_entries():
                if tree_details[0][0] in (b"a", b"r"):  # absent, relocated
                    # not relevant to the working tree
                    continue
                if not key[1]:
                    # the root is not a reference.
                    continue
                relpath = pathjoin(key[0].decode("utf8"), key[1].decode("utf8"))
                try:
                    if self.kind(relpath) == "tree-reference":
                        yield relpath
                except NoSuchFile:
                    # path is missing on disk.
                    continue

    def _observed_sha1(self, path, sha_and_stat):
        """See MutableTree._observed_sha1."""
        state = self.current_dirstate()
        entry = self._get_entry(path=path)
        state._observed_sha1(entry, *sha_and_stat)

    def kind(self, relpath):
        """Get the file kind for the given path.

        Args:
            relpath: Path relative to the tree root.

        Returns:
            One of 'file', 'directory', 'symlink', or 'tree-reference'.
        """
        abspath = self.abspath(relpath)
        kind = file_kind(abspath)
        if self._repo_supports_tree_reference and kind == "directory":
            with self.lock_read():
                entry = self._get_entry(path=relpath)
                if entry[1] is not None and entry[1][0][0] == b"t":
                    kind = "tree-reference"
        return kind

    def _last_revision(self):
        """See Mutable.last_revision."""
        with self.lock_read():
            parent_ids = self.current_dirstate().get_parent_ids()
            if parent_ids:
                return parent_ids[0]
            else:
                return _mod_revision.NULL_REVISION

    def lock_read(self):
        """See Branch.lock_read, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        self.branch.lock_read()
        try:
            self._control_files.lock_read()
            try:
                state = self.current_dirstate()
                if not state._lock_token:
                    state.lock_read()
                # set our support for tree references from the repository in
                # use.
                self._repo_supports_tree_reference = getattr(
                    self.branch.repository._format, "supports_tree_reference", False
                )
            except BaseException:
                self._control_files.unlock()
                raise
        except BaseException:
            self.branch.unlock()
            raise
        return LogicalLockResult(self.unlock)

    def _lock_self_write(self):
        """This should be called after the branch is locked."""
        try:
            self._control_files.lock_write()
            try:
                state = self.current_dirstate()
                if not state._lock_token:
                    state.lock_write()
                # set our support for tree references from the repository in
                # use.
                self._repo_supports_tree_reference = getattr(
                    self.branch.repository._format, "supports_tree_reference", False
                )
            except BaseException:
                self._control_files.unlock()
                raise
        except BaseException:
            self.branch.unlock()
            raise
        return LogicalLockResult(self.unlock)

    def lock_tree_write(self):
        """See MutableTree.lock_tree_write, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        self.branch.lock_read()
        return self._lock_self_write()

    def lock_write(self):
        """See MutableTree.lock_write, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        self.branch.lock_write()
        return self._lock_self_write()

    def move(self, from_paths, to_dir, after=False):
        """See WorkingTree.move()."""
        result = []
        if not from_paths:
            return result
        with self.lock_tree_write():
            state = self.current_dirstate()
            if isinstance(from_paths, (str, bytes)):
                raise ValueError()
            to_dir_utf8 = to_dir.encode("utf8")
            to_entry_dirname, to_basename = os.path.split(to_dir_utf8)
            # check destination directory
            # get the details for it
            (
                to_entry_block_index,
                to_entry_entry_index,
                _dir_present,
                entry_present,
            ) = state._get_block_entry_index(to_entry_dirname, to_basename, 0)
            if not entry_present:
                raise errors.BzrMoveFailedError(
                    "", to_dir, errors.NotVersionedError(to_dir)
                )
            to_entry = state._dirblocks[to_entry_block_index][1][to_entry_entry_index]
            # get a handle on the block itself.
            to_block_index = state._ensure_block(
                to_entry_block_index, to_entry_entry_index, to_dir_utf8
            )
            to_block = state._dirblocks[to_block_index]
            to_abs = self.abspath(to_dir)
            if not isdir(to_abs):
                raise errors.BzrMoveFailedError(
                    "", to_dir, errors.NotADirectory(to_abs)
                )

            if to_entry[1][0][0] != b"d":
                raise errors.BzrMoveFailedError(
                    "", to_dir, errors.NotADirectory(to_abs)
                )

            if self._inventory is not None:
                update_inventory = True
                inv = self.root_inventory
                to_dir_id = to_entry[0][2]
            else:
                update_inventory = False

            # GZ 2017-03-28: The rollbacks variable was shadowed in the loop below
            # missing those added here, but there's also no test coverage for this.
            rollbacks = contextlib.ExitStack()

            def move_one(
                old_entry,
                from_path_utf8,
                minikind,
                executable,
                fingerprint,
                packed_stat,
                size,
                to_block,
                to_key,
                to_path_utf8,
            ):
                state._make_absent(old_entry)
                from_key = old_entry[0]
                rollbacks.callback(
                    state.update_minimal,
                    from_key,
                    minikind,
                    executable=executable,
                    fingerprint=fingerprint,
                    packed_stat=packed_stat,
                    size=size,
                    path_utf8=from_path_utf8,
                )
                state.update_minimal(
                    to_key,
                    minikind,
                    executable=executable,
                    fingerprint=fingerprint,
                    packed_stat=packed_stat,
                    size=size,
                    path_utf8=to_path_utf8,
                )
                added_entry_index, _ = state._find_entry_index(to_key, to_block[1])
                new_entry = to_block[1][added_entry_index]
                rollbacks.callback(state._make_absent, new_entry)

            for from_rel in from_paths:
                # from_rel is 'pathinroot/foo/bar'
                from_rel_utf8 = from_rel.encode("utf8")
                from_dirname, from_tail = osutils.split(from_rel)
                from_dirname, from_tail_utf8 = osutils.split(from_rel_utf8)
                from_entry = self._get_entry(path=from_rel)
                if from_entry == (None, None):
                    raise errors.BzrMoveFailedError(
                        from_rel, to_dir, errors.NotVersionedError(path=from_rel)
                    )

                from_id = from_entry[0][2]
                to_rel = pathjoin(to_dir, from_tail)
                to_rel_utf8 = pathjoin(to_dir_utf8, from_tail_utf8)
                item_to_entry = self._get_entry(path=to_rel)
                if item_to_entry != (None, None):
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel, "Target is already versioned."
                    )

                if from_rel == to_rel:
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel, "Source and target are identical."
                    )

                from_missing = not self.has_filename(from_rel)
                to_missing = not self.has_filename(to_rel)
                move_file = not after
                if to_missing:
                    if not move_file:
                        raise errors.BzrMoveFailedError(
                            from_rel,
                            to_rel,
                            NoSuchFile(
                                path=to_rel, extra="New file has not been created yet"
                            ),
                        )
                    elif from_missing:
                        # neither path exists
                        raise errors.BzrRenameFailedError(
                            from_rel,
                            to_rel,
                            errors.PathsDoNotExist(paths=(from_rel, to_rel)),
                        )
                else:
                    if from_missing:  # implicitly just update our path mapping
                        move_file = False
                    elif not after:
                        raise errors.RenameFailedFilesExist(from_rel, to_rel)

                # perform the disk move first - its the most likely failure point.
                if move_file:
                    from_rel_abs = self.abspath(from_rel)
                    to_rel_abs = self.abspath(to_rel)
                    try:
                        osutils.rename(from_rel_abs, to_rel_abs)
                    except OSError as e:
                        raise errors.BzrMoveFailedError(from_rel, to_rel, e[1]) from e
                    rollbacks.callback(osutils.rename, to_rel_abs, from_rel_abs)
                try:
                    # perform the rename in the inventory next if needed: its easy
                    # to rollback
                    if update_inventory:
                        # rename the entry
                        from_entry = inv.get_entry(from_id)
                        current_parent = from_entry.parent_id
                        inv.rename(from_id, to_dir_id, from_tail)
                        rollbacks.callback(
                            inv.rename, from_id, current_parent, from_tail
                        )
                    # finally do the rename in the dirstate, which is a little
                    # tricky to rollback, but least likely to need it.
                    (
                        old_block_index,
                        old_entry_index,
                        _dir_present,
                        _file_present,
                    ) = state._get_block_entry_index(from_dirname, from_tail_utf8, 0)
                    old_block = state._dirblocks[old_block_index][1]
                    old_entry = old_block[old_entry_index]
                    from_key, old_entry_details = old_entry
                    cur_details = old_entry_details[0]
                    # remove the old row
                    to_key = (to_block[0],) + from_key[1:3]
                    minikind = cur_details[0]
                    move_one(
                        old_entry,
                        from_path_utf8=from_rel_utf8,
                        minikind=minikind,
                        executable=cur_details[3],
                        fingerprint=cur_details[1],
                        packed_stat=cur_details[4],
                        size=cur_details[2],
                        to_block=to_block,
                        to_key=to_key,
                        to_path_utf8=to_rel_utf8,
                    )

                    if minikind == b"d":

                        def update_dirblock(from_dir, to_key, to_dir_utf8):
                            """Recursively update all entries in this dirblock."""
                            if from_dir == b"":
                                raise AssertionError("renaming root not supported")
                            from_key = (from_dir, "")
                            from_block_idx, present = state._find_block_index_from_key(
                                from_key
                            )
                            if not present:
                                # This is the old record, if it isn't present,
                                # then there is theoretically nothing to
                                # update.  (Unless it isn't present because of
                                # lazy loading, but we don't do that yet)
                                return
                            from_block = state._dirblocks[from_block_idx]
                            (
                                to_block_index,
                                to_entry_index,
                                _,
                                _,
                            ) = state._get_block_entry_index(to_key[0], to_key[1], 0)
                            to_block_index = state._ensure_block(
                                to_block_index, to_entry_index, to_dir_utf8
                            )
                            to_block = state._dirblocks[to_block_index]

                            # Grab a copy since move_one may update the list.
                            for entry in from_block[1][:]:
                                if not (entry[0][0] == from_dir):
                                    raise AssertionError()
                                cur_details = entry[1][0]
                                to_key = (to_dir_utf8, entry[0][1], entry[0][2])
                                from_path_utf8 = osutils.pathjoin(
                                    entry[0][0], entry[0][1]
                                )
                                to_path_utf8 = osutils.pathjoin(
                                    to_dir_utf8, entry[0][1]
                                )
                                minikind = cur_details[0]
                                if minikind in (b"a", b"r"):
                                    # Deleted children of a renamed directory
                                    # Do not need to be updated.  Children that
                                    # have been renamed out of this directory
                                    # should also not be updated
                                    continue
                                move_one(
                                    entry,
                                    from_path_utf8=from_path_utf8,
                                    minikind=minikind,
                                    executable=cur_details[3],
                                    fingerprint=cur_details[1],
                                    packed_stat=cur_details[4],
                                    size=cur_details[2],
                                    to_block=to_block,
                                    to_key=to_key,
                                    to_path_utf8=to_path_utf8,
                                )
                                if minikind == b"d":
                                    # We need to move all the children of this
                                    # entry
                                    update_dirblock(
                                        from_path_utf8, to_key, to_path_utf8
                                    )

                        update_dirblock(from_rel_utf8, to_key, to_rel_utf8)
                except BaseException:
                    rollbacks.close()
                    raise
                result.append((from_rel, to_rel))
                state._mark_modified()
                self._make_dirty(reset_inventory=False)

            return result

    def _must_be_locked(self):
        if not self._control_files._lock_count:
            raise errors.ObjectNotLocked(self)

    def _new_tree(self):
        """Initialize the state in this tree to be a new tree."""
        self._dirty = True

    def path2id(self, path):
        """Return the id for path in this tree."""
        with self.lock_read():
            if isinstance(path, list):
                if path == []:
                    path = [""]
                path = osutils.pathjoin(*path)
            path = path.strip("/")
            entry = self._get_entry(path=path)
            if entry == (None, None):
                nested_tree, subpath = self.get_containing_nested_tree(path)
                if nested_tree is not None:
                    return nested_tree.path2id(subpath)
                return None
            return entry[0][2]

    def paths2ids(self, paths, trees=None, require_versioned=True):
        """See Tree.paths2ids().

        This specialisation fast-paths the case where all the trees are in the
        dirstate.
        """
        if trees is None:
            trees = []
        if paths is None:
            return None
        parents = self.get_parent_ids()
        for tree in trees:
            if not (
                isinstance(tree, DirStateRevisionTree) and tree._revision_id in parents
            ):
                return super().paths2ids(paths, trees, require_versioned)
        search_indexes = [0] + [1 + parents.index(tree._revision_id) for tree in trees]
        paths_utf8 = set()
        for path in paths:
            paths_utf8.add(path.encode("utf8"))
        # -- get the state object and prepare it.
        self.current_dirstate()
        paths2ids = self._paths2ids_using_bisect if False else self._paths2ids_in_memory
        return paths2ids(
            paths_utf8, search_indexes, require_versioned=require_versioned
        )

    def _paths2ids_in_memory(self, paths, search_indexes, require_versioned=True):
        state = self.current_dirstate()
        state._read_dirblocks_if_needed()

        def _entries_for_path(path):
            """Return a list with all the entries that match path for all ids."""
            dirname, basename = os.path.split(path)
            key = (dirname, basename, b"")
            block_index, present = state._find_block_index_from_key(key)
            if not present:
                # the block which should contain path is absent.
                return []
            result = []
            block = state._dirblocks[block_index][1]
            entry_index, _ = state._find_entry_index(key, block)
            # we may need to look at multiple entries at this path: walk while
            # the paths match.
            while entry_index < len(block) and block[entry_index][0][0:2] == key[0:2]:
                result.append(block[entry_index])
                entry_index += 1
            return result

        if require_versioned:
            # -- check all supplied paths are versioned in a search tree. --
            all_versioned = True
            for path in paths:
                path_entries = _entries_for_path(path)
                if not path_entries:
                    # this specified path is not present at all: error
                    all_versioned = False
                    break
                found_versioned = False
                # for each id at this path
                for entry in path_entries:
                    # for each tree.
                    for index in search_indexes:
                        if entry[1][index][0] != b"a":  # absent
                            found_versioned = True
                            # all good: found a versioned cell
                            break
                if not found_versioned:
                    # none of the indexes was not 'absent' at all ids for this
                    # path.
                    all_versioned = False
                    break
            if not all_versioned:
                raise errors.PathsNotVersionedError([p.decode("utf-8") for p in paths])
        # -- remove redundancy in supplied paths to prevent over-scanning --
        search_paths = {
            p.encode("utf-8") for p in osutils.minimum_path_selection(paths)
        }
        # sketch:
        # for all search_indexs in each path at or under each element of
        # search_paths, if the detail is relocated: add the id, and add the
        # relocated path as one to search if its not searched already. If the
        # detail is not relocated, add the id.
        searched_paths = set()
        found_ids = set()

        def _process_entry(entry):
            """Look at search_indexes within entry.

            If a specific tree's details are relocated, add the relocation
            target to search_paths if not searched already. If it is absent, do
            nothing. Otherwise add the id to found_ids.
            """
            for index in search_indexes:
                if entry[1][index][0] == b"r":  # relocated
                    if not osutils.is_inside_any(searched_paths, entry[1][index][1]):
                        search_paths.add(entry[1][index][1])
                elif entry[1][index][0] != b"a":  # absent
                    found_ids.add(entry[0][2])

        while search_paths:
            current_root = search_paths.pop()
            searched_paths.add(current_root)
            # process the entries for this containing directory: the rest will
            # be found by their parents recursively.
            root_entries = _entries_for_path(current_root)
            if not root_entries:
                # this specified path is not present at all, skip it.
                continue
            for entry in root_entries:
                _process_entry(entry)
            initial_key = (current_root, b"", b"")
            block_index, _ = state._find_block_index_from_key(initial_key)
            while block_index < len(state._dirblocks) and osutils.is_inside(
                current_root, state._dirblocks[block_index][0]
            ):
                for entry in state._dirblocks[block_index][1]:
                    _process_entry(entry)
                block_index += 1
        return found_ids

    def _paths2ids_using_bisect(self, paths, search_indexes, require_versioned=True):
        state = self.current_dirstate()
        found_ids = set()

        split_paths = sorted(osutils.split(p) for p in paths)
        found = state._bisect_recursive(split_paths)

        if require_versioned:
            found_dir_names = {dir_name_id[:2] for dir_name_id in found}
            for dir_name in split_paths:
                if dir_name not in found_dir_names:
                    raise errors.PathsNotVersionedError(
                        [p.decode("utf-8") for p in paths]
                    )

        for dir_name_id, trees_info in found.items():
            for index in search_indexes:
                if trees_info[index][0] not in (b"r", b"a"):
                    found_ids.add(dir_name_id[2])
        return found_ids

    def read_working_inventory(self):
        """Read the working inventory.

        This is a meaningless operation for dirstate, but we obey it anyhow.
        """
        return self.root_inventory

    def revision_tree(self, revision_id):
        """See Tree.revision_tree.

        WorkingTree4 supplies revision_trees for any basis tree.
        """
        with self.lock_read():
            dirstate = self.current_dirstate()
            parent_ids = dirstate.get_parent_ids()
            if revision_id not in parent_ids:
                raise errors.NoSuchRevisionInTree(self, revision_id)
            if revision_id in dirstate.get_ghosts():
                raise errors.NoSuchRevisionInTree(self, revision_id)
            return DirStateRevisionTree(
                dirstate,
                revision_id,
                self.branch.repository,
                get_transport_from_path(self.basedir),
            )

    def set_last_revision(self, new_revision):
        """Change the last revision in the working tree."""
        with self.lock_tree_write():
            parents = self.get_parent_ids()
            if new_revision in (_mod_revision.NULL_REVISION, None):
                if len(parents) >= 2:
                    raise AssertionError(
                        "setting the last parent to none with a pending merge "
                        "is unsupported."
                    )
                self.set_parent_ids([])
            else:
                self.set_parent_ids(
                    [new_revision] + parents[1:], allow_leftmost_as_ghost=True
                )

    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """Set the parent ids to revision_ids.

        See also set_parent_trees. This api will try to retrieve the tree data
        for each element of revision_ids from the trees repository. If you have
        tree data already available, it is more efficient to use
        set_parent_trees rather than set_parent_ids. set_parent_ids is however
        an easier API to use.

        :param revision_ids: The revision_ids to set as the parent ids of this
            working tree. Any of these may be ghosts.
        """
        with self.lock_tree_write():
            trees = []
            for revision_id in revision_ids:
                try:
                    revtree = self.branch.repository.revision_tree(revision_id)
                    # TODO: jam 20070213 KnitVersionedFile raises
                    # RevisionNotPresent rather than NoSuchRevision if a given
                    # revision_id is not present. Should Repository be catching
                    # it and re-raising NoSuchRevision?
                except (errors.NoSuchRevision, errors.RevisionNotPresent):
                    revtree = None
                trees.append((revision_id, revtree))
            self.set_parent_trees(
                trees, allow_leftmost_as_ghost=allow_leftmost_as_ghost
            )

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """Set the parents of the working tree.

        :param parents_list: A list of (revision_id, tree) tuples.
            If tree is None, then that element is treated as an unreachable
            parent tree - i.e. a ghost.
        """
        with self.lock_tree_write():
            dirstate = self.current_dirstate()
            if len(parents_list) > 0:
                if not allow_leftmost_as_ghost and parents_list[0][1] is None:
                    raise errors.GhostRevisionUnusableHere(parents_list[0][0])
            real_trees = []
            ghosts = []

            parent_ids = [rev_id for rev_id, tree in parents_list]
            graph = self.branch.repository.get_graph()
            heads = graph.heads(parent_ids)
            accepted_revisions = set()

            # convert absent trees to the null tree, which we convert back to
            # missing on access.
            for rev_id, tree in parents_list:
                if len(accepted_revisions) > 0:
                    # we always accept the first tree
                    if rev_id in accepted_revisions or rev_id not in heads:
                        # We have already included either this tree, or its
                        # descendent, so we skip it.
                        continue
                _mod_revision.check_not_reserved_id(rev_id)
                if tree is not None:
                    real_trees.append((rev_id, tree))
                else:
                    real_trees.append(
                        (
                            rev_id,
                            self.branch.repository.revision_tree(
                                _mod_revision.NULL_REVISION
                            ),
                        )
                    )
                    ghosts.append(rev_id)
                accepted_revisions.add(rev_id)
            updated = False
            if (
                len(real_trees) == 1
                and not ghosts
                and self.branch.repository._format.fast_deltas
                and isinstance(real_trees[0][1], InventoryRevisionTree)
                and self.get_parent_ids()
            ):
                rev_id, rev_tree = real_trees[0]
                basis_id = self.get_parent_ids()[0]
                # There are times when basis_tree won't be in
                # self.branch.repository, (switch, for example)
                try:
                    basis_tree = self.branch.repository.revision_tree(basis_id)
                except errors.NoSuchRevision:
                    # Fall back to the set_parent_trees(), since we can't use
                    # _make_delta if we can't get the RevisionTree
                    pass
                else:
                    delta = _make_delta(
                        rev_tree.root_inventory, basis_tree.root_inventory
                    )
                    dirstate.update_basis_by_delta(delta, rev_id)
                    updated = True
            if not updated:
                dirstate.set_parent_trees(real_trees, ghosts=ghosts)
            self._make_dirty(reset_inventory=False)

    def _set_root_id(self, file_id):
        """See WorkingTree.set_root_id."""
        state = self.current_dirstate()
        state.set_path_id(b"", file_id)
        if state._dirblock_state == dirstate.DirState.IN_MEMORY_MODIFIED:
            self._make_dirty(reset_inventory=True)

    def _sha_from_stat(self, path, stat_result):
        """Get a sha digest from the tree's stat cache.

        The default implementation assumes no stat cache is present.

        :param path: The path.
        :param stat_result: The stat result being looked up.
        """
        return self.current_dirstate().sha1_from_stat(path, stat_result)

    def supports_tree_reference(self):
        """Check if this tree supports tree references.

        Returns:
            True if tree references are supported, False otherwise.
        """
        return self._repo_supports_tree_reference

    def unlock(self):
        """Unlock in format 4 trees needs to write the entire dirstate."""
        if self._control_files._lock_count == 1:
            # do non-implementation specific cleanup
            self._cleanup()

            # eventually we should do signature checking during read locks for
            # dirstate updates.
            if self._control_files._lock_mode == "w" and self._dirty:
                self.flush()
            if self._dirstate is not None:
                # This is a no-op if there are no modifications.
                self._dirstate.save()
                self._dirstate.unlock()
            # TODO: jam 20070301 We shouldn't have to wipe the dirstate at this
            #       point. Instead, it could check if the header has been
            #       modified when it is locked, and if not, it can hang on to
            #       the data it has in memory.
            self._dirstate = None
            self._inventory = None
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    def unversion(self, paths):
        """Remove the file ids in paths from the current versioned set.

        When a directory is unversioned, all of its children are automatically
        unversioned.

        :param paths: The file ids to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        with self.lock_tree_write():
            if not paths:
                return
            state = self.current_dirstate()
            state._read_dirblocks_if_needed()
            file_ids = set()
            for path in paths:
                file_id = self.path2id(path)
                if file_id is None:
                    raise NoSuchFile(self, path)
                file_ids.add(file_id)
            ids_to_unversion = set(file_ids)
            paths_to_unversion = set()
            # sketch:
            # check if the root is to be unversioned, if so, assert for now.
            # walk the state marking unversioned things as absent.
            # if there are any un-unversioned ids at the end, raise
            for key, details in state._dirblocks[0][1]:
                if (
                    details[0][0] not in (b"a", b"r")  # absent or relocated
                    and key[2] in ids_to_unversion
                ):
                    # I haven't written the code to unversion / yet - it should
                    # be supported.
                    raise errors.BzrError(
                        "Unversioning the / is not currently supported"
                    )
            block_index = 0
            while block_index < len(state._dirblocks):
                # process one directory at a time.
                block = state._dirblocks[block_index]
                # first check: is the path one to remove - it or its children
                delete_block = False
                for path in paths_to_unversion:
                    if block[0].startswith(path) and (
                        len(block[0]) == len(path) or block[0][len(path)] == "/"
                    ):
                        # this entire block should be deleted - its the block for a
                        # path to unversion; or the child of one
                        delete_block = True
                        break
                # TODO: trim paths_to_unversion as we pass by paths
                if delete_block:
                    # this block is to be deleted: process it.
                    # TODO: we can special case the no-parents case and
                    # just forget the whole block.
                    entry_index = 0
                    while entry_index < len(block[1]):
                        entry = block[1][entry_index]
                        if entry[1][0][0] in (b"a", b"r"):
                            # don't remove absent or renamed entries
                            entry_index += 1
                        else:
                            # Mark this file id as having been removed
                            ids_to_unversion.discard(entry[0][2])
                            if not state._make_absent(entry):
                                # The block has not shrunk.
                                entry_index += 1
                    # go to the next block. (At the moment we dont delete empty
                    # dirblocks)
                    block_index += 1
                    continue
                entry_index = 0
                while entry_index < len(block[1]):
                    entry = block[1][entry_index]
                    if (
                        entry[1][0][0] in (b"a", b"r")  # absent, relocated
                        or
                        # ^ some parent row.
                        entry[0][2] not in ids_to_unversion
                    ):
                        # ^ not an id to unversion
                        entry_index += 1
                        continue
                    if entry[1][0][0] == b"d":
                        paths_to_unversion.add(pathjoin(entry[0][0], entry[0][1]))
                    if not state._make_absent(entry):
                        entry_index += 1
                    # we have unversioned this id
                    ids_to_unversion.remove(entry[0][2])
                block_index += 1
            if ids_to_unversion:
                raise errors.NoSuchId(self, next(iter(ids_to_unversion)))
            self._make_dirty(reset_inventory=False)
            # have to change the legacy inventory too.
            if self._inventory is not None:
                for file_id in file_ids:
                    if self._inventory.has_id(file_id):
                        self._inventory.remove_recursive_id(file_id)

    def rename_one(self, from_rel, to_rel, after=False):
        """See WorkingTree.rename_one."""
        with self.lock_tree_write():
            self.flush()
            super().rename_one(from_rel, to_rel, after)

    def apply_inventory_delta(self, changes):
        """See MutableTree.apply_inventory_delta."""
        with self.lock_tree_write():
            state = self.current_dirstate()
            state.update_by_delta(InventoryDelta(changes))
            self._make_dirty(reset_inventory=True)

    def update_basis_by_delta(self, new_revid, delta):
        """See MutableTree.update_basis_by_delta."""
        if self.last_revision() == new_revid:
            raise AssertionError()
        self.current_dirstate().update_basis_by_delta(delta, new_revid)

    def _validate(self):
        with self.lock_read():
            self._dirstate._validate()

    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        if self._dirty:
            raise AssertionError(
                "attempting to write an inventory when the "
                "dirstate is dirty will lose pending changes"
            )
        with self.lock_tree_write():
            had_inventory = self._inventory is not None
            # Setting self._inventory = None forces the dirstate to regenerate the
            # working inventory. We do this because self.inventory may be inv, or
            # may have been modified, and either case would prevent a clean delta
            # being created.
            self._inventory = None
            # generate a delta,
            delta = _make_delta(inv, self.root_inventory)
            # and apply it.
            self.apply_inventory_delta(delta)
            if had_inventory:
                self._inventory = inv
            self.flush()

    def reset_state(self, revision_ids=None):
        """Reset the state of the working tree.

        This does a hard-reset to a last-known-good state. This is a way to
        fix if something got corrupted (like the .bzr/checkout/dirstate file)
        """
        with self.lock_tree_write():
            if revision_ids is None:
                revision_ids = self.get_parent_ids()
            if not revision_ids:
                base_tree = self.branch.repository.revision_tree(
                    _mod_revision.NULL_REVISION
                )
                trees = []
            else:
                trees = list(
                    zip(
                        revision_ids,
                        self.branch.repository.revision_trees(revision_ids),
                    )
                )
                base_tree = trees[0][1]
            state = self.current_dirstate()
            # We don't support ghosts yet
            state.set_state_from_scratch(base_tree.root_inventory, trees, [])


class ContentFilterAwareSHA1Provider(dirstate.SHA1Provider):
    """SHA1 provider that applies content filters before hashing."""

    def __init__(self, tree):
        """Initialize the SHA1 provider.

        Args:
            tree: The working tree to use for content filtering.
        """
        self.tree = tree

    def sha1(self, abspath):
        """See dirstate.SHA1Provider.sha1()."""
        filters = self.tree._content_filter_stack(
            self.tree.relpath(osutils.safe_unicode(abspath))
        )
        return _mod_filters.internal_size_sha_file_byname(abspath, filters)[1]

    def stat_and_sha1(self, abspath):
        """See dirstate.SHA1Provider.stat_and_sha1()."""
        filters = self.tree._content_filter_stack(
            self.tree.relpath(osutils.safe_unicode(abspath))
        )
        with open(abspath, "rb", 65000) as file_obj:
            statvalue = os.fstat(file_obj.fileno())
            if filters:
                file_obj, size = _mod_filters.filtered_input_file(file_obj, filters)
                statvalue = _mod_filters.FilteredStat(statvalue, size)
            sha1 = osutils.size_sha_file(file_obj)[1]
        return statvalue, sha1


class ContentFilteringDirStateWorkingTree(DirStateWorkingTree):
    """Dirstate working tree that supports content filtering.

    The dirstate holds the hash and size of the canonical form of the file,
    and most methods must return that.
    """

    def _file_content_summary(self, path, stat_result):
        # This is to support the somewhat obsolete path_content_summary method
        # with content filtering: see
        # <https://bugs.launchpad.net/bzr/+bug/415508>.
        #
        # If the dirstate cache is up to date and knows the hash and size,
        # return that.
        # Otherwise if there are no content filters, return the on-disk size
        # and leave the hash blank.
        # Otherwise, read and filter the on-disk file and use its size and
        # hash.
        #
        # The dirstate doesn't store the size of the canonical form so we
        # can't trust it for content-filtered trees.  We just return None.
        dirstate_sha1 = self._dirstate.sha1_from_stat(path, stat_result)
        executable = self._is_executable_from_path_and_stat(path, stat_result)
        return ("file", None, executable, dirstate_sha1)


class WorkingTree4(DirStateWorkingTree):
    """This is the Format 4 working tree.

    This differs from WorkingTree by:
     - Having a consolidated internal dirstate, stored in a
       randomly-accessible sorted file on disk.
     - Not having a regular inventory attribute.  One can be synthesized
       on demand but this is expensive and should be avoided.

    This is new in bzr 0.15.
    """


class WorkingTree5(ContentFilteringDirStateWorkingTree):
    """This is the Format 5 working tree.

    This differs from WorkingTree4 by:
     - Supporting content filtering.

    This is new in bzr 1.11.
    """


class WorkingTree6(ContentFilteringDirStateWorkingTree):
    """This is the Format 6 working tree.

    This differs from WorkingTree5 by:
     - Supporting a current view that may mask the set of files in a tree
       impacted by most user operations.

    This is new in bzr 1.14.
    """

    def _make_views(self):
        return views.PathBasedViews(self)


class DirStateWorkingTreeFormat(WorkingTreeFormatMetaDir):
    """Base format for working trees that use dirstate for storage."""

    missing_parent_conflicts = True

    supports_versioned_directories = True

    _lock_class = LockDir
    _lock_file_name = "lock"

    def _open_control_files(self, a_controldir):
        transport = a_controldir.get_workingtree_transport(None)
        return LockableFiles(transport, self._lock_file_name, self._lock_class)

    def initialize(
        self,
        a_controldir,
        revision_id=None,
        from_branch=None,
        accelerator_tree=None,
        hardlink=False,
    ):
        """See WorkingTreeFormat.initialize().

        :param revision_id: allows creating a working tree at a different
            revision than the branch is at.
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        :param hardlink: If true, hard-link files from accelerator_tree,
            where possible.

        These trees get an initial random root id, if their repository supports
        rich root data, TREE_ROOT otherwise.
        """
        a_controldir.transport.local_abspath(".")
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
        local_path = transport.local_abspath("dirstate")
        # write out new dirstate (must exist when we create the tree)
        state = dirstate.DirState.initialize(local_path)
        state.unlock()
        del state
        wt = self._tree_class(
            a_controldir.root_transport.local_abspath("."),
            branch,
            _format=self,
            _controldir=a_controldir,
            _control_files=control_files,
        )
        wt._new_tree()
        wt.lock_tree_write()
        try:
            self._init_custom_control_files(wt)
            if revision_id in (None, _mod_revision.NULL_REVISION):
                if branch.repository.supports_rich_root():
                    wt._set_root_id(generate_ids.gen_root_id())
                else:
                    wt._set_root_id(ROOT_ID)
                wt.flush()
            basis = None
            # frequently, we will get here due to branching.  The accelerator
            # tree will be the tree from the branch, so the desired basis
            # tree will often be a parent of the accelerator tree.
            if accelerator_tree is not None:
                with contextlib.suppress(errors.NoSuchRevision):
                    basis = accelerator_tree.revision_tree(revision_id)
            if basis is None:
                basis = branch.repository.revision_tree(revision_id)
            if revision_id == _mod_revision.NULL_REVISION:
                parents_list = []
            else:
                parents_list = [(revision_id, basis)]
            with basis.lock_read():
                wt.set_parent_trees(parents_list, allow_leftmost_as_ghost=True)
                wt.flush()
                # if the basis has a root id we have to use that; otherwise we
                # use a new random one
                basis_root_id = basis.path2id("")
                if basis_root_id is not None:
                    wt._set_root_id(basis_root_id)
                    wt.flush()
                if wt.supports_content_filtering():
                    # The original tree may not have the same content filters
                    # applied so we can't safely build the inventory delta from
                    # the source tree.
                    delta_from_tree = False
                else:
                    delta_from_tree = True
                # delta_from_tree is safe even for DirStateRevisionTrees,
                # because wt4.apply_inventory_delta does not mutate the input
                # inventory entries.
                bzr_transform.build_tree(
                    basis,
                    wt,
                    accelerator_tree,
                    hardlink=hardlink,
                    delta_from_tree=delta_from_tree,
                )
                for hook in MutableTree.hooks["post_build_tree"]:
                    hook(wt)
        finally:
            control_files.unlock()
            wt.unlock()
        return wt

    def _init_custom_control_files(self, wt):
        """Subclasses with custom control files should override this method.

        The working tree and control files are locked for writing when this
        method is called.

        :param wt: the WorkingTree object
        """

    def open(self, a_controldir, _found=False):
        """Return the WorkingTree object for a_controldir.

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        a_controldir.transport.local_abspath(".")
        wt = self._open(a_controldir, self._open_control_files(a_controldir))
        return wt

    def _open(self, a_controldir, control_files):
        """Open the tree itself.

        :param a_controldir: the dir for the tree.
        :param control_files: the control files for the tree.
        """
        return self._tree_class(
            a_controldir.root_transport.local_abspath("."),
            branch=a_controldir.open_branch(),
            _format=self,
            _controldir=a_controldir,
            _control_files=control_files,
        )

    def __get_matchingcontroldir(self):
        return self._get_matchingcontroldir()

    def _get_matchingcontroldir(self):
        """Overrideable method to get a bzrdir for testing."""
        # please test against something that will let us do tree references
        return controldir.format_registry.make_controldir("development-subtree")

    _matchingcontroldir = property(__get_matchingcontroldir)


class WorkingTreeFormat4(DirStateWorkingTreeFormat):
    """The first consolidated dirstate working tree format.

    This format:
        - exists within a metadir controlling .bzr
        - includes an explicit version marker for the workingtree control
          files, separate from the ControlDir format
        - modifies the hash cache format
        - is new in bzr 0.15
        - uses a LockDir to guard access to it.
    """

    upgrade_recommended = False

    _tree_class = WorkingTree4

    @classmethod
    def get_format_string(cls):
        """See WorkingTreeFormat.get_format_string()."""
        return b"Bazaar Working Tree Format 4 (bzr 0.15)\n"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 4"


class WorkingTreeFormat5(DirStateWorkingTreeFormat):
    """WorkingTree format supporting content filtering."""

    upgrade_recommended = False

    _tree_class = WorkingTree5

    @classmethod
    def get_format_string(cls):
        """See WorkingTreeFormat.get_format_string()."""
        return b"Bazaar Working Tree Format 5 (bzr 1.11)\n"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 5"

    def supports_content_filtering(self):
        """Check if this format supports content filtering.

        Returns:
            True, indicating this format supports content filtering.
        """
        return True


class WorkingTreeFormat6(DirStateWorkingTreeFormat):
    """WorkingTree format supporting views."""

    upgrade_recommended = False

    _tree_class = WorkingTree6

    @classmethod
    def get_format_string(cls):
        """See WorkingTreeFormat.get_format_string()."""
        return b"Bazaar Working Tree Format 6 (bzr 1.14)\n"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 6"

    def _init_custom_control_files(self, wt):
        """Subclasses with custom control files should override this method."""
        wt._transport.put_bytes("views", b"", mode=wt.controldir._get_file_mode())

    def supports_content_filtering(self):
        """Check if this format supports content filtering.

        Returns:
            True, indicating this format supports content filtering.
        """
        return True

    def supports_views(self):
        """Check if this format supports views.

        Returns:
            True, indicating this format supports views.
        """
        return True

    def _get_matchingcontroldir(self):
        """Overrideable method to get a bzrdir for testing."""
        # We use 'development-subtree' instead of '2a', because we have a
        # few tests that want to test tree references
        return controldir.format_registry.make_controldir("development-subtree")


class DirStateRevisionTree(InventoryTree):
    """A revision tree pulling the inventory from a dirstate.

    Note that this is one of the historical (ie revision) trees cached in the
    dirstate for easy access, not the workingtree.
    """

    def __init__(self, dirstate, revision_id, repository, nested_tree_transport):
        """Initialize a DirStateRevisionTree.

        Args:
            dirstate: The dirstate object containing the tree data.
            revision_id: The revision ID this tree represents.
            repository: The repository containing the revision.
            nested_tree_transport: Transport for accessing nested trees.
        """
        self._dirstate = dirstate
        self._revision_id = revision_id
        self._repository = repository
        self._inventory = None
        self._locked = 0
        self._dirstate_locked = False
        self._nested_tree_transport = nested_tree_transport
        self._repo_supports_tree_reference = getattr(
            repository._format, "supports_tree_reference", False
        )

    def __repr__(self):
        """Return a string representation of this revision tree.

        Returns:
            A string showing the class name, revision ID, and dirstate.
        """
        return f"<{self.__class__.__name__} of {self._revision_id} in {self._dirstate}>"

    def annotate_iter(self, path, default_revision=_mod_revision.CURRENT_REVISION):
        """See Tree.annotate_iter."""
        file_id = self.path2id(path)
        text_key = (file_id, self.get_file_revision(path))
        annotations = self._repository.texts.annotate(text_key)
        return [(key[-1], line) for (key, line) in annotations]

    def iter_child_entries(self, path):
        """Iterate over child entries of a directory.

        Args:
            path: Path to the directory.

        Returns:
            An iterator of child inventory entries.

        Raises:
            NoSuchFile: If the path does not exist.
            NotADirectory: If the path is not a directory.
        """
        with self.lock_read():
            inv, inv_file_id = self._path2inv_file_id(path)
            if inv is None:
                raise NoSuchFile(path)
            ie = inv.get_entry(inv_file_id)
            if ie.kind != "directory":
                raise errors.NotADirectory(path)
            return inv.iter_sorted_children(inv_file_id)

    def _comparison_data(self, entry, path):
        """See Tree._comparison_data."""
        if entry is None:
            return None, False, None
        # trust the entry as RevisionTree does, but this may not be
        # sensible: the entry might not have come from us?
        return entry.kind, entry.executable, None

    def _get_file_revision(self, path, file_id, vf, tree_revision):
        """Ensure that file_id, tree_revision is in vf to plan the merge."""
        last_revision = self.get_file_revision(path)
        base_vf = self._repository.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return last_revision

    def filter_unversioned_files(self, paths):
        """Filter out paths that are not versioned.

        :return: set of paths.
        """
        pred = self.has_filename
        return {p for p in paths if not pred(p)}

    def id2path(self, file_id, recurse="down"):
        """Convert a file-id to a path."""
        with self.lock_read():
            entry = self._get_entry(file_id=file_id)
            if entry == (None, None):
                if recurse == "down":
                    if debug.debug_flag_enabled("evil"):
                        trace.mutter_callsite(2, "Tree.id2path scans all nested trees.")

                    for nested_path in self.iter_references():
                        nested_tree = self.get_nested_tree(nested_path)
                        try:
                            return osutils.pathjoin(
                                nested_path, nested_tree.id2path(file_id)
                            )
                        except errors.NoSuchId:
                            pass
                raise errors.NoSuchId(tree=self, file_id=file_id)
            path_utf8 = osutils.pathjoin(entry[0][0], entry[0][1])
            return path_utf8.decode("utf8")

    def get_nested_tree(self, path):
        """Get the nested tree at the given path.

        Args:
            path: The path to the nested tree.

        Returns:
            The nested revision tree.

        Raises:
            MissingNestedTree: If the nested tree cannot be loaded.
        """
        with self.lock_read():
            nested_revid = self.get_reference_revision(path)
            return self._get_nested_tree(path, None, nested_revid)

    def _get_nested_tree(self, path, file_id, reference_revision):
        try:
            branch = _mod_branch.Branch.open_from_transport(
                self._nested_tree_transport.clone(path)
            )
        except errors.NotBranchError as e:
            raise MissingNestedTree(path) from e
        try:
            revtree = branch.repository.revision_tree(reference_revision)
        except errors.NoSuchRevision as e:
            raise MissingNestedTree(path) from e
        if file_id is not None and revtree.path2id("") != file_id:
            raise AssertionError(
                "mismatching file id: {!r} != {!r}".format(revtree.path2id(""), file_id)
            )
        return revtree

    def iter_references(self):
        """Iterate over tree references in this revision tree.

        Yields:
            Paths to tree references.
        """
        if not self._repo_supports_tree_reference:
            # When the repo doesn't support references, we will have nothing to
            # return
            return iter([])
        # Otherwise, fall back to the default implementation
        return super().iter_references()

    def _get_parent_index(self):
        """Return the index in the dirstate referenced by this tree."""
        return self._dirstate.get_parent_ids().index(self._revision_id) + 1

    def _get_entry(self, file_id=None, path=None):
        """Get the dirstate row for file_id or path.

        If either file_id or path is supplied, it is used as the key to lookup.
        If both are supplied, the fastest lookup is used, and an error is
        raised if they do not both point at the same row.

        :param file_id: An optional unicode file_id to be looked up.
        :param path: An optional unicode path to be looked up.
        :return: The dirstate row tuple for path/file_id, or (None, None)
        """
        if file_id is None and path is None:
            raise errors.BzrError("must supply file_id or path")
        if path is not None:
            path = path.encode("utf8")
        try:
            parent_index = self._get_parent_index()
        except ValueError as err:
            raise errors.NoSuchRevisionInTree(
                self._dirstate, self._revision_id
            ) from err
        return self._dirstate._get_entry(
            parent_index, fileid_utf8=file_id, path_utf8=path
        )

    def _generate_inventory(self):
        """Create and set self.inventory from the dirstate object.

        (So this is only called the first time the inventory is requested for
        this tree; it then remains in memory until it's out of date.)

        This is relatively expensive: we have to walk the entire dirstate.
        """
        if not self._locked:
            raise AssertionError(
                "cannot generate inventory of an unlocked dirstate revision tree"
            )
        # separate call for profiling - makes it clear where the costs are.
        self._dirstate._read_dirblocks_if_needed()
        if self._revision_id not in self._dirstate.get_parent_ids():
            raise AssertionError(
                "parent {} has disappeared from {}".format(
                    self._revision_id, self._dirstate.get_parent_ids()
                )
            )
        parent_index = self._dirstate.get_parent_ids().index(self._revision_id) + 1
        # This is identical now to the WorkingTree _generate_inventory except
        # for the tree index use.
        root_key, current_entry = self._dirstate._get_entry(parent_index, path_utf8=b"")
        current_id = root_key[2]
        if current_entry[parent_index][0] != b"d":
            raise AssertionError()
        if current_entry[parent_index][4] == b"":
            root_revision = None
        else:
            root_revision = current_entry[parent_index][4]
        inv = Inventory(revision_id=self._revision_id, root_id=None)
        root = InventoryDirectory(current_id, "", None, root_revision)
        inv.add(root)
        # Turn some things into local variables
        minikind_to_kind = dirstate.DirState._minikind_to_kind
        utf8_decode = cache_utf8._utf8_decode
        # we could do this straight out of the dirstate; it might be fast
        # and should be profiled - RBC 20070216
        parent_ies = {b"": inv.root}
        for block in self._dirstate._dirblocks[1:]:  # skip root
            dirname = block[0]
            try:
                parent_ie = parent_ies[dirname]
            except KeyError:
                # all the paths in this block are not versioned in this tree
                continue
            for key, entry in block[1]:
                (minikind, fingerprint, size, executable, revid) = entry[parent_index]
                if minikind in (b"a", b"r"):  # absent, relocated
                    # not this tree
                    continue
                name = key[1]
                name_unicode = utf8_decode(name)[0]
                file_id = key[2]
                kind = minikind_to_kind[minikind]
                if kind == "file":
                    inv_entry = InventoryFile(
                        file_id,
                        name_unicode,
                        parent_ie.file_id,
                        revision=revid,
                        executable=bool(executable),
                        text_size=size,
                        text_sha1=fingerprint,
                    )
                elif kind == "directory":
                    inv_entry = InventoryDirectory(
                        file_id, name_unicode, parent_ie.file_id, revision=revid
                    )

                    parent_ies[(dirname + b"/" + name).strip(b"/")] = inv_entry
                elif kind == "symlink":
                    inv_entry = InventoryLink(
                        file_id,
                        name_unicode,
                        parent_ie.file_id,
                        revision=revid,
                        symlink_target=utf8_decode(fingerprint)[0],
                    )
                elif kind == "tree-reference":
                    inv_entry = TreeReference(
                        file_id,
                        name_unicode,
                        parent_ie.file_id,
                        revision=revid,
                        reference_revision=fingerprint or None,
                    )
                else:
                    raise AssertionError(
                        f"cannot convert entry {entry!r} into an InventoryEntry"
                    )
                try:
                    inv.add(inv_entry)
                except DuplicateFileId as err:
                    raise AssertionError(
                        f"file_id {file_id} already in"
                        f" inventory as {inv.get_entry(file_id)}"
                    ) from err
                except errors.InconsistentDelta as err:
                    raise AssertionError(
                        f"name {name_unicode!r} already in parent"
                    ) from err
        self._inventory = inv

    def get_file_mtime(self, path):
        """Return the modification time for this record.

        We return the timestamp of the last-changed revision.
        """
        # Make sure the file exists
        entry = self._get_entry(path=path)
        if entry == (None, None):  # do we raise?
            nested_tree, subpath = self.get_containing_nested_tree(path)
            if nested_tree is not None:
                return nested_tree.get_file_mtime(subpath)
            raise NoSuchFile(path)
        parent_index = self._get_parent_index()
        last_changed_revision = entry[1][parent_index][4]
        try:
            rev = self._repository.get_revision(last_changed_revision)
        except errors.NoSuchRevision as err:
            raise FileTimestampUnavailable(path) from err
        return rev.timestamp

    def get_file_sha1(self, path, stat_value=None):
        """Get the SHA1 hash of a file in this revision tree.

        Args:
            path: The path to the file.
            stat_value: Ignored for revision trees.

        Returns:
            The SHA1 hash as a hex string, or None if not a regular file.
        """
        entry = self._get_entry(path=path)
        parent_index = self._get_parent_index()
        parent_details = entry[1][parent_index]
        if parent_details[0] == b"f":
            return parent_details[1]
        return None

    def get_file_revision(self, path):
        """Get the revision ID that last modified the file at path.

        Args:
            path: The path to the file.

        Returns:
            The revision ID that last modified the file.
        """
        with self.lock_read():
            inv, inv_file_id = self._path2inv_file_id(path)
            return inv.get_entry(inv_file_id).revision

    def get_file(self, path):
        """Get a file-like object for the file at path.

        Args:
            path: The path to the file.

        Returns:
            A BytesIO object containing the file contents.
        """
        return BytesIO(self.get_file_text(path))

    def get_file_size(self, path):
        """Get the size of the file at path.

        Args:
            path: The path to the file.

        Returns:
            The size of the file in bytes.
        """
        inv, inv_file_id = self._path2inv_file_id(path)
        return inv.get_entry(inv_file_id).text_size

    def get_file_text(self, path):
        """Get the text content of the file at path.

        Args:
            path: The path to the file.

        Returns:
            The file contents as bytes.
        """
        content = None
        for _, content_iter in self.iter_files_bytes([(path, None)]):
            if content is not None:
                raise AssertionError("iter_files_bytes returned too many entries")
            # For each entry returned by iter_files_bytes, we must consume the
            # content_iter before we step the files iterator.
            content = b"".join(content_iter)
        if content is None:
            raise AssertionError("iter_files_bytes did not return the requested data")
        return content

    def get_reference_revision(self, path):
        """Get the revision ID of a tree reference.

        Args:
            path: The path to the tree reference.

        Returns:
            The revision ID of the referenced tree.
        """
        inv, inv_file_id = self._path2inv_file_id(path)
        return inv.get_entry(inv_file_id).reference_revision

    def iter_files_bytes(self, desired_files):
        """Iterate over the contents of multiple files.

        This version is implemented on top of Repository.iter_files_bytes.

        Args:
            desired_files: An iterable of (path, identifier) tuples.

        Yields:
            (identifier, content_iterator) tuples where content_iterator
            yields the bytes content of the file.
        """
        parent_index = self._get_parent_index()
        repo_desired_files = []
        for path, identifier in desired_files:
            entry = self._get_entry(path=path)
            if entry == (None, None):
                raise NoSuchFile(path)
            repo_desired_files.append(
                (entry[0][2], entry[1][parent_index][4], identifier)
            )
        return self._repository.iter_files_bytes(repo_desired_files)

    def get_symlink_target(self, path):
        """Get the target of a symlink.

        Args:
            path: The path to the symlink.

        Returns:
            The target path of the symlink as a string, or None if not a symlink.
        """
        entry = self._get_entry(path=path)
        if entry is None:
            raise NoSuchFile(tree=self, path=path)
        parent_index = self._get_parent_index()
        if entry[1][parent_index][0] != b"l":
            return None
        else:
            target = entry[1][parent_index][1]
            target = target.decode("utf8")
            return target

    def get_revision_id(self):
        """Return the revision ID for this tree.

        Returns:
            The revision ID this tree represents.
        """
        return self._revision_id

    def _get_root_inventory(self):
        if self._inventory is not None:
            return self._inventory
        self._must_be_locked()
        self._generate_inventory()
        return self._inventory

    root_inventory = property(_get_root_inventory, doc="Inventory of this Tree")

    def get_parent_ids(self):
        """Get the parent revision IDs for this tree.

        The parents of a tree in the dirstate are not cached.

        Returns:
            A list of parent revision IDs.
        """
        return self._repository.get_revision(self._revision_id).parent_ids

    def has_filename(self, filename):
        """Check if a file exists in this tree.

        Args:
            filename: The path to check.

        Returns:
            True if the file exists in the tree, False otherwise.
        """
        return bool(self.path2id(filename))

    def kind(self, path):
        """Get the file kind for the given path.

        Args:
            path: Path relative to the tree root.

        Returns:
            One of 'file', 'directory', 'symlink', or 'tree-reference'.

        Raises:
            NoSuchFile: If the path does not exist in the tree.
        """
        entry = self._get_entry(path=path)[1]
        if entry is None:
            raise NoSuchFile(path)
        parent_index = self._get_parent_index()
        return dirstate.DirState._minikind_to_kind[entry[parent_index][0]]

    def stored_kind(self, path):
        """Get the stored kind for the given path.

        For revision trees, this is the same as kind().

        Args:
            path: Path relative to the tree root.

        Returns:
            The file kind as stored in the tree.
        """
        return self.kind(path)

    def path_content_summary(self, path):
        """Get a summary of the content at the given path.

        Args:
            path: Path relative to the tree root.

        Returns:
            A tuple of (kind, size, executable, link_or_sha1).
        """
        inv, inv_file_id = self._path2inv_file_id(path)
        if inv_file_id is None:
            return ("missing", None, None, None)
        entry = inv.get_entry(inv_file_id)
        kind = entry.kind
        if kind == "file":
            return (kind, entry.text_size, entry.executable, entry.text_sha1)
        elif kind == "symlink":
            return (kind, None, None, entry.symlink_target)
        else:
            return (kind, None, None, None)

    def is_executable(self, path):
        """Check if the file at path is executable.

        Args:
            path: Path relative to the tree root.

        Returns:
            True if the file is executable, False otherwise.

        Raises:
            NoSuchFile: If the path does not exist in the tree.
        """
        inv, inv_file_id = self._path2inv_file_id(path)
        if inv_file_id is None:
            raise NoSuchFile(path)
        ie = inv.get_entry(inv_file_id)
        if ie.kind != "file":
            return False
        return ie.executable

    def is_locked(self):
        """Check if this tree is locked.

        Returns:
            True if the tree is locked, False otherwise.
        """
        return self._locked

    def list_files(
        self, include_root=False, from_dir=None, recursive=True, recurse_nested=False
    ):
        """List files in the tree.

        Args:
            include_root: Whether to include the root directory.
            from_dir: Directory to start listing from.
            recursive: Whether to recurse into subdirectories.
            recurse_nested: Whether to recurse into nested trees.

        Yields:
            (path, status, kind, entry) tuples for each file.
        """
        # The only files returned by this are those from the version
        if from_dir is None:
            from_dir_id = None
            inv = self.root_inventory
        else:
            inv, from_dir_id = self._path2inv_file_id(from_dir)
            if from_dir_id is None:
                # Directory not versioned
                return iter([])

        def iter_entries(inv):
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
                        recursive=recursive,
                        recurse_nested=recurse_nested,
                    ):
                        if subpath:
                            full_subpath = osutils.pathjoin(path, subpath)
                        else:
                            full_subpath = path
                        yield full_subpath, status, kind, entry
                else:
                    yield path, "V", entry.kind, entry

        return iter_entries(inv)

    def lock_read(self):
        """Lock the tree for a set of operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self._locked:
            self._repository.lock_read()
            if self._dirstate._lock_token is None:
                self._dirstate.lock_read()
                self._dirstate_locked = True
        self._locked += 1
        return LogicalLockResult(self.unlock)

    def _must_be_locked(self):
        if not self._locked:
            raise errors.ObjectNotLocked(self)

    def path2id(self, path):
        """Return the file ID for path in this tree.

        Args:
            path: The path to look up, as a string or list of path components.

        Returns:
            The file ID for the path, or None if not found.
        """
        # lookup by path: faster than splitting and walking the ivnentory.
        if isinstance(path, list):
            if path == []:
                path = [""]
            path = osutils.pathjoin(*path)
        with self.lock_read():
            entry = self._get_entry(path=path)
            if entry == (None, None):
                nested_tree, subpath = self.get_containing_nested_tree(path)
                if nested_tree is not None:
                    return nested_tree.path2id(subpath)
                return None
            return entry[0][2]

    def unlock(self):
        """Unlock the tree, freeing any cache memory used during the lock."""
        # outside of a lock, the inventory is suspect: release it.
        self._locked -= 1
        if not self._locked:
            self._inventory = None
            self._locked = 0
            if self._dirstate_locked:
                self._dirstate.unlock()
                self._dirstate_locked = False
            self._repository.unlock()

    def supports_tree_reference(self):
        """Check if this tree supports tree references.

        Returns:
            True if tree references are supported, False otherwise.
        """
        with self.lock_read():
            return self._repo_supports_tree_reference

    def walkdirs(self, prefix=""):
        """Walk through directories in the tree.

        Args:
            prefix: The directory path to start from.

        Yields:
            (relpath, dirblock) tuples where dirblock is a list of
            (relpath, name, kind, stat, kind) tuples.
        """
        # TODO: jam 20070215 This is the lazy way by using the RevisionTree
        # implementation based on an inventory.
        # This should be cleaned up to use the much faster Dirstate code
        # So for now, we just build up the parent inventory, and extract
        # it the same way RevisionTree does.
        _directory = "directory"
        inv = self._get_root_inventory()
        top_id = inv.path2id(prefix)
        pending = [] if top_id is None else [(prefix, top_id)]
        while pending:
            dirblock = []
            relpath, file_id = pending.pop()
            # 0 - relpath, 1- file-id
            relroot = relpath + "/" if relpath else ""
            # FIXME: stash the node in pending
            subdirs = []
            for child in inv.iter_sorted_children(file_id):
                toppath = relroot + child.name
                dirblock.append((toppath, child.name, child.kind, None, child.kind))
                if child.kind == _directory:
                    subdirs.append((toppath, child.file_id))
            yield relpath, dirblock
            # push the user specified dirs from dirblock
            pending.extend(reversed(subdirs))


class InterDirStateTree(InterInventoryTree):
    """Fast path optimiser for changes_from with dirstate trees.

    This is used only when both trees are in the dirstate working file, and
    the source is any parent within the dirstate, and the destination is
    the current working tree of the same dirstate.
    """

    # this could be generalized to allow comparisons between any trees in the
    # dirstate, and possibly between trees stored in different dirstates.

    def __init__(self, source, target):
        """Initialize InterDirStateTree.

        Args:
            source: The source tree to compare from.
            target: The target tree to compare to.

        Raises:
            Exception: If the trees are not compatible for comparison.
        """
        super().__init__(source, target)
        if not InterDirStateTree.is_compatible(source, target):
            raise Exception(f"invalid source {source!r} and target {target!r}")

    @staticmethod
    def make_source_parent_tree(source, target):
        """Change the source tree into a parent of the target."""
        revid = source.commit("record tree")
        target.branch.fetch(source.branch, revid)
        target.set_parent_ids([revid])
        return target.basis_tree(), target

    @classmethod
    def make_source_parent_tree_python_dirstate(klass, test_case, source, target):
        """Create parent tree using Python dirstate implementation.

        Args:
            test_case: The test case instance.
            source: The source tree.
            target: The target tree.

        Returns:
            A tuple of (basis_tree, target).
        """
        result = klass.make_source_parent_tree(source, target)
        result[1]._iter_changes = dirstate.ProcessEntryPython
        return result

    @classmethod
    def make_source_parent_tree_compiled_dirstate(klass, test_case, source, target):
        """Create parent tree using compiled dirstate implementation.

        Args:
            test_case: The test case instance.
            source: The source tree.
            target: The target tree.

        Returns:
            A tuple of (basis_tree, target).
        """
        from .tests.test__dirstate_helpers import compiled_dirstate_helpers_feature

        test_case.requireFeature(compiled_dirstate_helpers_feature)
        from ._dirstate_helpers_pyx import ProcessEntryC

        result = klass.make_source_parent_tree(source, target)
        result[1]._iter_changes = ProcessEntryC
        return result

    _matching_from_tree_format = WorkingTreeFormat4()
    _matching_to_tree_format = WorkingTreeFormat4()

    @classmethod
    def _test_mutable_trees_to_test_trees(klass, test_case, source, target):
        # This method shouldn't be called, because we have python and C
        # specific flavours.
        raise NotImplementedError

    def iter_changes(
        self,
        include_unchanged=False,
        specific_files=None,
        pb=None,
        extra_trees=None,
        require_versioned=True,
        want_unversioned=False,
    ):
        """Return the changes from source to target.

        :return: An iterator that yields tuples. See InterTree.iter_changes
            for details.
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children of
            matched directories are included.
        :param include_unchanged: An optional boolean requesting the inclusion of
            unchanged entries in the result.
        :param extra_trees: An optional list of additional trees to use when
            mapping the contents of specific_files (paths) to file_ids.
        :param require_versioned: If True, all files in specific_files must be
            versioned in one of source, target, extra_trees or
            PathsNotVersionedError is raised.
        :param want_unversioned: Should unversioned files be returned in the
            output. An unversioned file is defined as one with (False, False)
            for the versioned pair.
        """
        if extra_trees is None:
            extra_trees = []
        # TODO: handle extra trees in the dirstate.
        if extra_trees or specific_files == []:
            # we can't fast-path these cases (yet)
            return super().iter_changes(
                include_unchanged,
                specific_files,
                pb,
                extra_trees,
                require_versioned,
                want_unversioned=want_unversioned,
            )
        parent_ids = self.target.get_parent_ids()
        if not (
            self.source._revision_id in parent_ids
            or self.source._revision_id == _mod_revision.NULL_REVISION
        ):
            raise AssertionError(
                f"revision {{{self.source._revision_id}}} is not stored in {{{self.target}}}, but {self.iter_changes} "
                "can only be used for trees stored in the dirstate"
            )
        target_index = 0
        if self.source._revision_id == _mod_revision.NULL_REVISION:
            source_index = None
            indices = (target_index,)
        else:
            if self.source._revision_id not in parent_ids:
                raise AssertionError(
                    "Failure: source._revision_id: {} not in target.parent_ids({})".format(
                        self.source._revision_id, parent_ids
                    )
                )
            source_index = 1 + parent_ids.index(self.source._revision_id)
            indices = (source_index, target_index)

        if specific_files is None:
            specific_files = {""}

        # -- get the state object and prepare it.
        state = self.target.current_dirstate()
        state._read_dirblocks_if_needed()
        if require_versioned:
            # -- check all supplied paths are versioned in a search tree. --
            not_versioned = []
            for path in specific_files:
                path_entries = state._entries_for_path(path.encode("utf-8"))
                if not path_entries:
                    # this specified path is not present at all: error
                    not_versioned.append(path)
                    continue
                found_versioned = False
                # for each id at this path
                for entry in path_entries:
                    # for each tree.
                    for index in indices:
                        if entry[1][index][0] != b"a":  # absent
                            found_versioned = True
                            # all good: found a versioned cell
                            break
                if not found_versioned:
                    # none of the indexes was not 'absent' at all ids for this
                    # path.
                    not_versioned.append(path)
            if len(not_versioned) > 0:
                raise errors.PathsNotVersionedError(not_versioned)

        # remove redundancy in supplied specific_files to prevent over-scanning
        # make all specific_files utf8
        search_specific_files_utf8 = set()
        for path in osutils.minimum_path_selection(specific_files):
            # Note, if there are many specific files, using cache_utf8
            # would be good here.
            search_specific_files_utf8.add(path.encode("utf8"))

        iter_changes = self.target._iter_changes(
            include_unchanged,
            self.target._supports_executable(),
            search_specific_files_utf8,
            state,
            source_index,
            target_index,
            want_unversioned,
            self.target,
        )
        return iter_changes.iter_changes()

    @staticmethod
    def is_compatible(source, target):
        """Check if source and target trees are compatible for optimized comparison.

        Args:
            source: The source tree.
            target: The target tree.

        Returns:
            True if the trees can use the optimized InterDirStateTree comparison.
        """
        # the target must be a dirstate working tree
        if not isinstance(target, DirStateWorkingTree):
            return False
        # the source must be a revtree or dirstate rev tree.
        if not isinstance(source, (revisiontree.RevisionTree, DirStateRevisionTree)):
            return False
        # the source revid must be in the target dirstate
        if not (  # noqa: SIM103
            source._revision_id == _mod_revision.NULL_REVISION
            or source._revision_id in target.get_parent_ids()
        ):
            # TODO: what about ghosts? it may well need to
            # check for them explicitly.
            return False
        return True


InterTree.register_optimiser(InterDirStateTree)


class Converter3to4:
    """Perform an in-place upgrade of format 3 to format 4 trees."""

    def __init__(self):
        """Initialize the format converter."""
        self.target_format = WorkingTreeFormat4()

    def convert(self, tree):
        """Convert a format 3 tree to format 4.

        Args:
            tree: The working tree to convert.
        """
        # lock the control files not the tree, so that we dont get tree
        # on-unlock behaviours, and so that noone else diddles with the
        # tree during upgrade.
        tree._control_files.lock_write()
        try:
            tree.read_working_inventory()
            self.create_dirstate_data(tree)
            self.update_format(tree)
            self.remove_xml_files(tree)
        finally:
            tree._control_files.unlock()

    def create_dirstate_data(self, tree):
        """Create the dirstate based data for tree."""
        local_path = tree.controldir.get_workingtree_transport(None).local_abspath(
            "dirstate"
        )
        state = dirstate.DirState.from_tree(tree, local_path)
        state.save()
        state.unlock()

    def remove_xml_files(self, tree):
        """Remove the oldformat 3 data."""
        transport = tree.controldir.get_workingtree_transport(None)
        for path in [
            "basis-inventory-cache",
            "inventory",
            "last-revision",
            "pending-merges",
            "stat-cache",
        ]:
            try:
                transport.delete(path)
            except NoSuchFile:
                # some files are optional - just deal.
                pass

    def update_format(self, tree):
        """Change the format marker."""
        tree._transport.put_bytes(
            "format",
            self.target_format.as_string(),
            mode=tree.controldir._get_file_mode(),
        )


class Converter4to5:
    """Perform an in-place upgrade of format 4 to format 5 trees."""

    def __init__(self):
        """Initialize the format converter."""
        self.target_format = WorkingTreeFormat5()

    def convert(self, tree):
        """Convert a format 4 tree to format 5.

        Args:
            tree: The working tree to convert.
        """
        # lock the control files not the tree, so that we don't get tree
        # on-unlock behaviours, and so that no-one else diddles with the
        # tree during upgrade.
        tree._control_files.lock_write()
        try:
            self.update_format(tree)
        finally:
            tree._control_files.unlock()

    def update_format(self, tree):
        """Change the format marker."""
        tree._transport.put_bytes(
            "format",
            self.target_format.as_string(),
            mode=tree.controldir._get_file_mode(),
        )


class Converter4or5to6:
    """Perform an in-place upgrade of format 4 or 5 to format 6 trees."""

    def __init__(self):
        """Initialize the format converter."""
        self.target_format = WorkingTreeFormat6()

    def convert(self, tree):
        """Convert a format 4 or 5 tree to format 6.

        Args:
            tree: The working tree to convert.
        """
        # lock the control files not the tree, so that we don't get tree
        # on-unlock behaviours, and so that no-one else diddles with the
        # tree during upgrade.
        tree._control_files.lock_write()
        try:
            self.init_custom_control_files(tree)
            self.update_format(tree)
        finally:
            tree._control_files.unlock()

    def init_custom_control_files(self, tree):
        """Initialize custom control files."""
        tree._transport.put_bytes("views", b"", mode=tree.controldir._get_file_mode())

    def update_format(self, tree):
        """Change the format marker."""
        tree._transport.put_bytes(
            "format",
            self.target_format.as_string(),
            mode=tree.controldir._get_file_mode(),
        )

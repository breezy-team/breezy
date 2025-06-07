# Copyright (C) 2008 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""CommitHandlers that build and save revisions & their inventories."""

import contextlib
from typing import Optional

from fastimport import processor

from bzrformats import generate_ids, inventory, serializer
from bzrformats.inventory_delta import InventoryDelta

from ... import debug, errors, osutils, revision
from ...trace import mutter, note, warning
from .helpers import escape_commit_message, mode_to_kind

_serializer_handles_escaping = hasattr(
    serializer.RevisionSerializer, "squashes_xml_invalid_characters"
)


def copy_inventory(inv: inventory.Inventory) -> inventory.Inventory:
    entries = inv.iter_entries_by_dir()
    inv = inventory.Inventory(None, inv.revision_id)
    for _path, inv_entry in entries:
        inv.add(inv_entry.copy())
    return inv


class CommitHandler(processor.CommitHandler):
    """Base class for Bazaar CommitHandlers."""

    def __init__(
        self,
        command,
        cache_mgr,
        rev_store,
        verbose: bool = False,
        prune_empty_dirs: bool = True,
    ) -> None:
        super().__init__(command)
        self.cache_mgr = cache_mgr
        self.rev_store = rev_store
        self.verbose = verbose
        self.branch_ref = command.ref
        self.prune_empty_dirs = prune_empty_dirs
        # This tracks path->file-id for things we're creating this commit.
        # If the same path is created multiple times, we need to warn the
        # user and add it just once.
        # If a path is added then renamed or copied, we need to handle that.
        self._new_file_ids: dict[str, inventory.FileId] = {}
        # This tracks path->file-id for things we're modifying this commit.
        # If a path is modified then renamed or copied, we need the make
        # sure we grab the new content.
        self._modified_file_ids: dict[str, inventory.FileId] = {}
        # This tracks the paths for things we're deleting this commit.
        # If the same path is added or the destination of a rename say,
        # then a fresh file-id is required.
        self._paths_deleted_this_commit: set[str] = set()

    def mutter(self, msg, *args):
        """Output a mutter but add context."""
        msg = f"{msg} ({self.command.id})"
        mutter(msg, *args)

    def debug(self, msg, *args):
        """Output a mutter if the appropriate -D option was given."""
        if debug.debug_flag_enabled("fast-import"):
            msg = f"{msg} ({self.command.id})"
            mutter(msg, *args)

    def note(self, msg, *args):
        """Output a note but add context."""
        msg = f"{msg} ({self.command.id})"
        note(msg, *args)

    def warning(self, msg, *args) -> None:
        """Output a warning but add context."""
        msg = f"{msg} ({self.command.id})"
        warning(msg, *args)

    def pre_process_files(self) -> None:
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        # cache of texts for this commit, indexed by file-id
        self.data_for_commit: dict[bytes, bytes] = {}
        # if self.rev_store.expects_rich_root():
        self.data_for_commit[inventory.ROOT_ID] = b""

        # Track the heads and get the real parent list
        parents = self.cache_mgr.reftracker.track_heads(self.command)

        # Convert the parent commit-ids to bzr revision-ids
        if parents:
            self.parents = [self.cache_mgr.lookup_committish(p) for p in parents]
        else:
            self.parents = []
        self.debug(
            "%s id: %s, parents: %s",
            self.command.id,
            self.revision_id,
            str(self.parents),
        )

        # Tell the RevisionStore we're starting a new commit
        self.revision = self.build_revision()
        self.parent_invs = [self.get_inventory(p) for p in self.parents]
        self.rev_store.start_new_revision(self.revision, self.parents, self.parent_invs)

        # cache of per-file parents for this commit, indexed by file-id
        self.per_file_parents_for_commit: dict[
            inventory.FileId, list[inventory.FileId]
        ] = {}
        if self.rev_store.expects_rich_root():
            self.per_file_parents_for_commit[inventory.ROOT_ID] = []

        # Keep the basis inventory. This needs to be treated as read-only.
        if len(self.parents) == 0:
            self.basis_inventory = self._init_inventory()
        else:
            self.basis_inventory = self.get_inventory(self.parents[0])
        if hasattr(self.basis_inventory, "root_id"):
            self.inventory_root_id = self.basis_inventory.root_id
        else:
            self.inventory_root_id = self.basis_inventory.root.file_id

        # directory-path -> inventory-entry for current inventory
        self.directory_entries: dict[str, inventory.InventoryEntry] = {}

        self._dirs_that_might_become_empty: set[str] = set()

        # A given file-id can only appear once so we accumulate
        # the entries in a dict then build the actual delta at the end
        self._delta_entries_by_fileid: dict[
            inventory.FileId,
            tuple[
                Optional[str], Optional[str], inventory.FileId, inventory.InventoryEntry
            ],
        ] = {}
        if len(self.parents) == 0 or not self.rev_store.expects_rich_root():
            old_path = "" if self.parents else None
            # Need to explicitly add the root entry for the first revision
            # and for non rich-root inventories
            root_id = inventory.ROOT_ID
            root_ie = inventory.InventoryDirectory(root_id, "", None, self.revision_id)
            self._add_entry((old_path, "", root_id, root_ie))

    def _init_inventory(self) -> inventory.Inventory:
        return self.rev_store.init_inventory(self.revision_id)

    def get_inventory(self, revision_id: revision.RevisionID) -> inventory.Inventory:
        """Get the inventory for a revision id."""
        try:
            inv = self.cache_mgr.inventories[revision_id]
        except KeyError:
            if self.verbose:
                self.mutter("get_inventory cache miss for %s", revision_id)
            # Not cached so reconstruct from the RevisionStore
            inv = self.rev_store.get_inventory(revision_id)
            self.cache_mgr.inventories[revision_id] = inv
        return inv

    def _get_data(self, file_id: inventory.FileId) -> bytes:
        """Get the data bytes for a file-id."""
        return self.data_for_commit[file_id]

    def _get_lines(self, file_id: inventory.FileId) -> None:
        """Get the lines for a file-id."""
        return osutils.split_lines(self._get_data(file_id))

    def _get_per_file_parents(
        self, file_id: inventory.FileId
    ) -> list[inventory.FileId]:
        """Get the lines for a file-id."""
        return self.per_file_parents_for_commit[file_id]

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.

        This is a callback used by the RepositoryStore to
        speed up inventory reconstruction.
        """
        present = []
        inventories = []
        # If an inventory is in the cache, we assume it was
        # successfully loaded into the revision store
        for revision_id in revision_ids:
            try:
                inv = self.cache_mgr.inventories[revision_id]
                present.append(revision_id)
            except KeyError:
                if self.verbose:
                    self.note("get_inventories cache miss for %s", revision_id)
                # Not cached so reconstruct from the revision store
                try:
                    inv = self.get_inventory(revision_id)
                    present.append(revision_id)
                except BaseException:
                    inv = self._init_inventory()
                self.cache_mgr.inventories[revision_id] = inv
            inventories.append(inv)
        return present, inventories

    def bzr_file_id_and_new(self, path: str) -> tuple[inventory.FileId, bool]:
        """Get a Bazaar file identifier and new flag for a path.

        :return: file_id, is_new where
          is_new = True if the file_id is newly created
        """
        if path not in self._paths_deleted_this_commit:
            # Try file-ids renamed in this commit
            id = self._modified_file_ids.get(path)
            if id is not None:
                return id, False

            # Try the basis inventory
            id = self.basis_inventory.path2id(path)
            if id is not None:
                return id, False

            # Try the other inventories
            if len(self.parents) > 1:
                for _inv in self.parent_invs[1:]:
                    id = self.basis_inventory.path2id(path)
                    if id is not None:
                        return id, False

        # Doesn't exist yet so create it
        basename = osutils.basename(path)
        file_id = generate_ids.gen_file_id(basename)
        self.debug(
            "Generated new file id %s for '%s' in revision-id '%s'",
            file_id,
            path,
            self.revision_id,
        )
        self._new_file_ids[path] = file_id
        return file_id, True

    def bzr_file_id(self, path) -> inventory.FileId:
        """Get a Bazaar file identifier for a path."""
        return self.bzr_file_id_and_new(path)[0]

    def _utf8_decode(self, field, value) -> str:
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            # The spec says fields are *typically* utf8 encoded
            # but that isn't enforced by git-fast-export (at least)
            self.warning(f"{field} not in utf8 - replacing unknown characters")
            return value.decode("utf-8", "replace")

    def _decode_path(self, path) -> str:
        try:
            return path.decode("utf-8")
        except UnicodeDecodeError:
            # The spec says fields are *typically* utf8 encoded
            # but that isn't enforced by git-fast-export (at least)
            self.warning(f"path {path!r} not in utf8 - replacing unknown characters")
            return path.decode("utf-8", "replace")

    def _format_name_email(self, section: str, name: str, email: str) -> str:
        """Format name & email as a string."""
        name = self._utf8_decode(f"{section} name", name)
        email = self._utf8_decode(f"{section} email", email)

        if email:
            return f"{name} <{email}>"
        else:
            return name

    def gen_revision_id(self) -> revision.RevisionID:
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        # Perhaps 'who' being the person running the import is ok? If so,
        # it might be a bit quicker and give slightly better compression?
        who = self._format_name_email("committer", committer[0], committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def build_revision(self):
        rev_props = self._legal_revision_properties(self.command.properties)
        if "branch-nick" not in rev_props:
            rev_props["branch-nick"] = self.cache_mgr.branch_mapper.git_to_bzr(
                self.branch_ref
            )
        self._save_author_info(rev_props)
        committer = self.command.committer
        who = self._format_name_email("committer", committer[0], committer[1])
        try:
            message = self.command.message.decode("utf-8")

        except UnicodeDecodeError:
            self.warning("commit message not in utf8 - replacing unknown characters")
            message = self.command.message.decode("utf-8", "replace")
        if not _serializer_handles_escaping:
            # We need to assume the bad ol' days
            message = escape_commit_message(message)
        return revision.Revision(
            timestamp=committer[2],
            timezone=committer[3],
            committer=who,
            message=message,
            revision_id=self.revision_id,
            properties=rev_props,
            inventory_sha1=None,
            parent_ids=self.parents,
        )

    def _legal_revision_properties(self, props: dict[str, str]) -> dict[str, str]:
        """Clean-up any revision properties we can't handle."""
        # For now, we just check for None because that's not allowed in 2.0rc1
        result = {}
        if props is not None:
            for name, value in props.items():
                if value is None:
                    self.warning(f"converting None to empty string for property {name}")
                    result[name] = ""
                else:
                    result[name] = value
        return result

    def _save_author_info(self, rev_props: dict[str, str]) -> None:
        author = self.command.author
        if author is None:
            return
        if self.command.more_authors:
            authors = [author] + self.command.more_authors
            author_ids = [
                self._format_name_email("author", a[0], a[1]) for a in authors
            ]
        elif author != self.command.committer:
            author_ids = [self._format_name_email("author", author[0], author[1])]
        else:
            return
        # If we reach here, there are authors worth storing
        rev_props["authors"] = "\n".join(author_ids)

    def _modify_item(
        self,
        path: str,
        kind: str,
        is_executable: bool,
        data: Optional[bytes],
        inv: inventory.Inventory,
    ) -> None:
        """Add to or change an item in the inventory."""
        # If we've already added this, warn the user that we're ignoring it.
        # In the future, it might be nice to double check that the new data
        # is the same as the old but, frankly, exporters should be fixed
        # not to produce bad data streams in the first place ...
        existing = self._new_file_ids.get(path)
        if existing:
            # We don't warn about directories because it's fine for them
            # to be created already by a previous rename
            if kind != "directory":
                self.warning(f"{path} already added in this commit - ignoring")
            return

        # Create the new InventoryEntry
        basename, parent_id = self._ensure_directory(path, inv)
        file_id = self.bzr_file_id(path)
        if kind == "file":
            if data is None:
                raise AssertionError
            ie = inventory.InventoryFile(
                file_id,
                basename,
                parent_id,
                self.revision_id,
                executable=is_executable,
                text_sha1=osutils.sha_string(data),
                text_size=len(data),
            )
            # lines = osutils.split_lines(data)
            self.data_for_commit[file_id] = data
        elif kind == "directory":
            ie = inventory.InventoryDirectory(
                file_id, basename, parent_id, self.revision_id
            )
            self.directory_entries[path] = ie
            # There are no lines stored for a directory so
            # make sure the cache used by get_lines knows that
            self.data_for_commit[file_id] = b""
        elif kind == "symlink":
            ie = inventory.InventoryLink(
                file_id,
                basename,
                parent_id,
                self.revision_id,
                symlink_target=self._decode_path(data),
            )
            # There are no lines stored for a symlink so
            # make sure the cache used by get_lines knows that
            self.data_for_commit[file_id] = b""
        else:
            self.warning(
                f"Cannot import items of kind '{kind}' yet - ignoring '{path}'"
            )
            return
        # Record it
        try:
            old_ie = inv.get_entry(file_id)
        except errors.NoSuchId:
            try:
                self.record_new(path, ie)
            except:
                print(
                    f"failed to add path '{path}' with entry '{ie}' in command {self.command.id}"
                )
                print(f"parent's children are:\n{inv.get_children(ie.parent_id)!r}\n")
                raise
        else:
            if old_ie.kind == "directory":
                self.record_delete(path, old_ie)
            self.record_changed(path, ie)

    def _ensure_directory(
        self, path: str, inv: inventory.Inventory
    ) -> tuple[str, inventory.FileId]:
        """Ensure that the containing directory exists for 'path'."""
        dirname, basename = osutils.split(path)
        if dirname == "":
            # the root node doesn't get updated
            return basename, self.inventory_root_id
        try:
            ie = self._get_directory_entry(inv, dirname)
        except KeyError:
            # We will create this entry, since it doesn't exist
            pass
        else:
            return basename, ie.file_id

        # No directory existed, we will just create one, first, make sure
        # the parent exists
        dir_basename, parent_id = self._ensure_directory(dirname, inv)
        dir_file_id = self.bzr_file_id(dirname)
        ie = inventory.InventoryDirectory(
            dir_file_id, dir_basename, parent_id, self.revision_id
        )
        self.directory_entries[dirname] = ie
        # There are no lines stored for a directory so
        # make sure the cache used by get_lines knows that
        self.data_for_commit[dir_file_id] = b""

        # It's possible that a file or symlink with that file-id
        # already exists. If it does, we need to delete it.
        if inv.has_id(dir_file_id):
            self.record_delete(dirname, ie)
        self.record_new(dirname, ie)
        return basename, ie.file_id

    def _get_directory_entry(
        self, inv: inventory.Inventory, dirname: str
    ) -> inventory.InventoryEntry:
        """Get the inventory entry for a directory.

        Raises KeyError if dirname is not a directory in inv.
        """
        result = self.directory_entries.get(dirname)
        if result is None:
            if dirname in self._paths_deleted_this_commit:
                raise KeyError
            try:
                file_id = inv.path2id(dirname)
            except errors.NoSuchId as e:
                # In a CHKInventory, this is raised if there's no root yet
                raise KeyError from e
            if file_id is None:
                raise KeyError
            result = inv.get_entry(file_id)
            # dirname must be a directory for us to return it
            if result.kind == "directory":
                self.directory_entries[dirname] = result
            else:
                raise KeyError
        return result

    def _delete_item(self, path: str, inv: inventory.Inventory) -> None:
        newly_added = self._new_file_ids.get(path)
        if newly_added:
            # We've only just added this path earlier in this commit.
            file_id = newly_added
            # note: delta entries look like (old, new, file-id, ie)
            ie = self._delta_entries_by_fileid[file_id][3]
        else:
            file_id = inv.path2id(path)
            if file_id is None:
                self.mutter("ignoring delete of %s as not in inventory", path)
                return
            try:
                ie = inv.get_entry(file_id)
            except errors.NoSuchId:
                self.mutter("ignoring delete of %s as not in inventory", path)
                return
        self.record_delete(path, ie)

    def _copy_item(
        self, src_path: str, dest_path: str, inv: inventory.Inventory
    ) -> None:
        newly_changed = self._new_file_ids.get(src_path) or self._modified_file_ids.get(
            src_path
        )
        if newly_changed:
            # We've only just added/changed this path earlier in this commit.
            file_id = newly_changed
            # note: delta entries look like (old, new, file-id, ie)
            ie = self._delta_entries_by_fileid[file_id][3]
        else:
            file_id = inv.path2id(src_path)
            if file_id is None:
                self.warning(
                    "ignoring copy of %s to %s - source does not exist",
                    src_path,
                    dest_path,
                )
                return
            ie = inv.get_entry(file_id)
        if ie is None:
            raise AssertionError
        kind = ie.kind
        if kind == "file":
            if newly_changed:
                content = self.data_for_commit[file_id]
            else:
                revtree = self.rev_store.repo.revision_tree(self.parents[0])
                content = revtree.get_file_text(src_path)
            self._modify_item(dest_path, kind, ie.executable, content, inv)
        elif kind == "symlink":
            self._modify_item(
                dest_path, kind, False, ie.symlink_target.encode("utf-8"), inv
            )
        else:
            self.warning(
                "ignoring copy of %s %s - feature not yet supported", kind, dest_path
            )

    def _rename_item(
        self, old_path: str, new_path: str, inv: inventory.Inventory
    ) -> None:
        existing = self._new_file_ids.get(old_path) or self._modified_file_ids.get(
            old_path
        )
        if existing:
            # We've only just added/modified this path earlier in this commit.
            # Change the add/modify of old_path to an add of new_path
            self._rename_pending_change(old_path, new_path, existing)
            return

        file_id = inv.path2id(old_path)
        if file_id is None:
            self.warning(
                f"ignoring rename of {old_path} to {new_path} - old path does not exist"
            )
            return
        ie = inv.get_entry(file_id)
        rev_id = ie.revision
        new_file_id = inv.path2id(new_path)
        if new_file_id is not None:
            self.record_delete(new_path, inv.get_entry(new_file_id))
        self.record_rename(old_path, new_path, file_id, ie)

        # The revision-id for this entry will be/has been updated and
        # that means the loader then needs to know what the "new" text is.
        # We therefore must go back to the revision store to get it.
        lines = self.rev_store.get_file_lines(rev_id, old_path)
        self.data_for_commit[file_id] = b"".join(lines)

    def _delete_all_items(self, inv: inventory.Inventory) -> None:
        if len(inv) == 0:
            return
        for path, ie in inv.iter_entries_by_dir():
            if path != "":
                self.record_delete(path, ie)

    def _warn_unless_in_merges(self, fileid: inventory.FileId, path: str) -> None:
        if len(self.parents) <= 1:
            return
        for parent in self.parents[1:]:
            if self.get_inventory(parent).has_id(fileid):
                return
        self.warning("ignoring delete of %s as not in parent inventories", path)

    def post_process_files(self) -> None:
        """Save the revision."""
        delta = self._get_final_delta()
        inv = self.rev_store.load_using_delta(
            self.revision,
            self.basis_inventory,
            delta,
            None,
            self._get_data,
            self._get_per_file_parents,
            self._get_inventories,
        )
        self.cache_mgr.inventories[self.revision_id] = inv
        # print "committed %s" % self.revision_id

    def _get_final_delta(self):
        """Generate the final delta.

        Smart post-processing of changes, e.g. pruning of directories
        that would become empty, goes here.
        """
        delta: list[
            tuple[
                Optional[str], Optional[str], inventory.FileId, inventory.InventoryEntry
            ]
        ] = list(self._delta_entries_by_fileid.values())
        if self.prune_empty_dirs and self._dirs_that_might_become_empty:
            candidates = self._dirs_that_might_become_empty
            while candidates:
                never_born = set()
                parent_dirs_that_might_become_empty = set()
                for path, file_id in self._empty_after_delta(
                    InventoryDelta(delta), candidates
                ):
                    newly_added = self._new_file_ids.get(path)
                    if newly_added:
                        never_born.add(newly_added)
                    else:
                        delta.append((path, None, file_id, None))
                    parent_dir = osutils.dirname(path)
                    if parent_dir:
                        parent_dirs_that_might_become_empty.add(parent_dir)
                candidates = parent_dirs_that_might_become_empty
                # Clean up entries that got deleted before they were ever added
                if never_born:
                    delta = [de for de in delta if de[2] not in never_born]
        return InventoryDelta(delta)

    def _empty_after_delta(
        self, delta, candidates
    ) -> list[tuple[str, inventory.FileId]]:
        # self.mutter("delta so far is:\n%s" % "\n".join([str(de) for de in delta]))
        # self.mutter("candidates for deletion are:\n%s" % "\n".join([c for c in candidates]))
        new_inv = self._get_proposed_inventory(delta)
        result = []
        for dir in candidates:
            file_id = new_inv.path2id(dir)
            if file_id is None:
                continue
            ie = new_inv.get_entry(file_id)
            if ie.kind != "directory":
                continue
            if len(new_inv.get_children(ie.file_id)) == 0:
                result.append((dir, file_id))
                if self.verbose:
                    self.note(f"pruning empty directory {dir}")
        return result

    def _get_proposed_inventory(self, delta) -> inventory.Inventory:
        if len(self.parents):
            # new_inv = self.basis_inventory._get_mutable_inventory()
            # Note that this will create unreferenced chk pages if we end up
            # deleting entries, because this 'test' inventory won't end up
            # used. However, it is cheaper than having to create a full copy of
            # the inventory for every commit.
            new_inv = self.basis_inventory.create_by_apply_delta(
                delta, b"not-a-valid-revision-id:"
            )
        else:
            new_inv = inventory.Inventory(revision_id=self.revision_id)
            # This is set in the delta so remove it to prevent a duplicate
            new_inv.remove_recursive_id(inventory.ROOT_ID)
            new_inv.apply_delta(delta)
        return new_inv

    def _add_entry(
        self,
        entry: tuple[
            Optional[str], Optional[str], inventory.FileId, inventory.InventoryEntry
        ],
    ) -> None:
        # We need to combine the data if multiple entries have the same file-id.
        # For example, a rename followed by a modification looks like:
        #
        # (x, y, f, e) & (y, y, f, g) => (x, y, f, g)
        #
        # Likewise, a modification followed by a rename looks like:
        #
        # (x, x, f, e) & (x, y, f, g) => (x, y, f, g)
        #
        # Here's a rename followed by a delete and a modification followed by
        # a delete:
        #
        # (x, y, f, e) & (y, None, f, None) => (x, None, f, None)
        # (x, x, f, e) & (x, None, f, None) => (x, None, f, None)
        #
        # In summary, we use the original old-path, new new-path and new ie
        # when combining entries.
        old_path = entry[0]
        new_path = entry[1]
        file_id = entry[2]
        ie = entry[3]
        existing = self._delta_entries_by_fileid.get(file_id, None)
        if existing is not None:
            old_path = existing[0]
            entry = (old_path, new_path, file_id, ie)
        if new_path is None and old_path is None:
            # This is a delete cancelling a previous add
            del self._delta_entries_by_fileid[file_id]
            if existing is None or existing[1] is None:
                raise AssertionError
            parent_dir = osutils.dirname(existing[1])
            self.mutter("cancelling add of %s with parent %s", existing[1], parent_dir)
            if parent_dir:
                self._dirs_that_might_become_empty.add(parent_dir)
            return
        else:
            self._delta_entries_by_fileid[file_id] = entry

        # Collect parent directories that might become empty
        if new_path is None:
            if old_path is None:
                raise AssertionError
            # delete
            parent_dir = osutils.dirname(old_path)
            # note: no need to check the root
            if parent_dir:
                self._dirs_that_might_become_empty.add(parent_dir)
        elif old_path is not None and old_path != new_path:
            # rename
            old_parent_dir = osutils.dirname(old_path)
            new_parent_dir = osutils.dirname(new_path)
            if old_parent_dir and old_parent_dir != new_parent_dir:
                self._dirs_that_might_become_empty.add(old_parent_dir)

        # Calculate the per-file parents, if not already done
        if file_id in self.per_file_parents_for_commit:
            return
        if old_path is None:
            # add
            # If this is a merge, the file was most likely added already.
            # The per-file parent(s) must therefore be calculated and
            # we can't assume there are none.
            (
                per_file_parents,
                revision,
            ) = self.rev_store.get_parents_and_revision_for_entry(ie)
            entry = (entry[0], entry[1], entry[2], ie.derive(revision=revision))
            self.per_file_parents_for_commit[file_id] = per_file_parents
        elif new_path is None:
            # delete
            pass
        elif old_path != new_path:
            # rename
            per_file_parents, _ = self.rev_store.get_parents_and_revision_for_entry(ie)
            self.per_file_parents_for_commit[file_id] = per_file_parents
        else:
            # modify
            (
                per_file_parents,
                revision,
            ) = self.rev_store.get_parents_and_revision_for_entry(ie)
            entry = (entry[0], entry[1], entry[2], ie.derive(revision=revision))
            self.per_file_parents_for_commit[file_id] = per_file_parents

    def record_new(self, path: str, ie: inventory.InventoryEntry) -> None:
        self._add_entry((None, path, ie.file_id, ie))

    def record_changed(self, path: str, ie: inventory.InventoryEntry) -> None:
        self._add_entry((path, path, ie.file_id, ie))
        self._modified_file_ids[path] = ie.file_id

    def record_delete(self, path: str, ie: inventory.InventoryEntry) -> None:
        self._add_entry((path, None, ie.file_id, None))
        self._paths_deleted_this_commit.add(path)
        if ie.kind == "directory":
            with contextlib.suppress(KeyError):
                del self.directory_entries[path]
            if self.basis_inventory.get_entry(ie.file_id).kind == "directory":
                for child_relpath, entry in self.basis_inventory.iter_entries_by_dir(
                    from_dir=ie.file_id
                ):
                    child_path = osutils.pathjoin(path, child_relpath)
                    self._add_entry((child_path, None, entry.file_id, None))
                    self._paths_deleted_this_commit.add(child_path)
                    if entry.kind == "directory":
                        with contextlib.suppress(KeyError):
                            del self.directory_entries[child_path]

    def record_rename(
        self,
        old_path: str,
        new_path: str,
        file_id: inventory.FileId,
        old_ie: inventory.InventoryEntry,
    ) -> None:
        new_basename, new_parent_id = self._ensure_directory(
            new_path, self.basis_inventory
        )
        new_ie = old_ie.derive(
            name=new_basename, parent_id=new_parent_id, revision=self.revision_id
        )
        self._add_entry((old_path, new_path, file_id, new_ie))
        self._modified_file_ids[new_path] = file_id
        self._paths_deleted_this_commit.discard(new_path)
        if new_ie.kind == "directory":
            self.directory_entries[new_path] = new_ie

    def _rename_pending_change(
        self, old_path: str, new_path: str, file_id: inventory.FileId
    ) -> None:
        """Instead of adding/modifying old-path, add new-path instead."""
        # note: delta entries look like (old, new, file-id, ie)
        old_ie = self._delta_entries_by_fileid[file_id][3]

        # Delete the old path. Note that this might trigger implicit
        # deletion of newly created parents that could now become empty.
        self.record_delete(old_path, old_ie)

        # Update the dictionaries used for tracking new file-ids
        if old_path in self._new_file_ids:
            del self._new_file_ids[old_path]
        else:
            del self._modified_file_ids[old_path]
        self._new_file_ids[new_path] = file_id

        # Create the new InventoryEntry
        kind = old_ie.kind
        basename, parent_id = self._ensure_directory(new_path, self.basis_inventory)
        if kind == "file":
            ie = inventory.InventoryFile(
                file_id,
                basename,
                parent_id,
                self.revision_id,
                executable=old_ie.executable,
                text_sha1=old_ie.text_sha1,
                text_size=old_ie.text_size,
            )
        elif kind == "symlink":
            ie = inventory.InventoryLink(
                file_id,
                basename,
                parent_id,
                self.revision_id,
                symlink_target=old_ie.symlink_target,
            )
        else:
            raise AssertionError("unknown kind: {}".format(kind))

        # Record it
        self.record_new(new_path, ie)

    def modify_handler(self, filecmd) -> None:
        (kind, executable) = mode_to_kind(filecmd.mode)
        if filecmd.dataref is not None:
            if kind == "directory":
                data = None
            elif kind == "tree-reference":
                data = filecmd.dataref
            else:
                data = self.cache_mgr.fetch_blob(filecmd.dataref)
        else:
            data = filecmd.data
        self.debug("modifying %s", filecmd.path)
        decoded_path = self._decode_path(filecmd.path)
        self._modify_item(decoded_path, kind, executable, data, self.basis_inventory)

    def delete_handler(self, filecmd) -> None:
        self.debug("deleting %s", filecmd.path)
        self._delete_item(self._decode_path(filecmd.path), self.basis_inventory)

    def copy_handler(self, filecmd) -> None:
        src_path = self._decode_path(filecmd.src_path)
        dest_path = self._decode_path(filecmd.dest_path)
        self.debug("copying %s to %s", src_path, dest_path)
        self._copy_item(src_path, dest_path, self.basis_inventory)

    def rename_handler(self, filecmd) -> None:
        old_path = self._decode_path(filecmd.old_path)
        new_path = self._decode_path(filecmd.new_path)
        self.debug("renaming %s to %s", old_path, new_path)
        self._rename_item(old_path, new_path, self.basis_inventory)

    def deleteall_handler(self, filecmd) -> None:
        self.debug("deleting all files (and also all directories)")
        self._delete_all_items(self.basis_inventory)

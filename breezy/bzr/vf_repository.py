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

"""Repository formats built around versioned files."""

from io import BytesIO

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import itertools

from breezy import (
    config as _mod_config,
    debug,
    fifo_cache,
    gpg,
    graph,
    lru_cache,
    osutils,
    revision as _mod_revision,
    tsort,
    ui,
    )
from breezy.bzr import (
    fetch as _mod_fetch,
    check,
    generate_ids,
    inventory_delta,
    inventorytree,
    static_tuple,
    versionedfile,
    vf_search,
    )
from breezy.bzr.bundle import serializer

from breezy.i18n import gettext
from breezy.bzr.testament import Testament
""",
)

from .. import errors
from ..decorators import only_raises
from ..repository import (
    CommitBuilder,
    FetchResult,
    InterRepository,
    Repository,
    RepositoryFormat,
    WriteGroup,
)
from ..trace import mutter, note
from .inventory import Inventory, entry_factory
from .inventorytree import InventoryTreeChange
from .repository import MetaDirRepository, RepositoryFormatMetaDir


class VersionedFileRepositoryFormat(RepositoryFormat):
    """Base class for all repository formats that are VersionedFiles-based."""

    supports_full_versioned_files = True
    supports_versioned_directories = True
    supports_unreferenced_revisions = True

    # Should commit add an inventory, or an inventory delta to the repository.
    _commit_inv_deltas = True
    # What order should fetch operations request streams in?
    # The default is unordered as that is the cheapest for an origin to
    # provide.
    _fetch_order = "unordered"
    # Does this repository format use deltas that can be fetched as-deltas ?
    # (E.g. knits, where the knit deltas can be transplanted intact.
    # We default to False, which will ensure that enough data to get
    # a full text out of any fetch stream will be grabbed.
    _fetch_uses_deltas = False


class VersionedFileCommitBuilder(CommitBuilder):
    """Commit builder implementation for versioned files based repositories."""

    def __init__(
        self,
        repository,
        parents,
        config_stack,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
        owns_transaction=True,
    ):
        super().__init__(
            repository,
            parents,
            config_stack,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy,
        )
        try:
            basis_id = self.parents[0]
        except IndexError:
            basis_id = _mod_revision.NULL_REVISION
        self.basis_delta_revision = basis_id
        self._new_inventory = None
        self._basis_delta = []
        self.__heads = graph.HeadsCache(repository.get_graph()).heads
        # memo'd check for no-op commits.
        self._any_changes = False
        self._owns_transaction = owns_transaction

    def any_changes(self):
        """Return True if any entries were changed.

        This includes merge-only changes. It is the core for the --unchanged
        detection in commit.

        :return: True if any changes have occured.
        """
        return self._any_changes

    def _ensure_fallback_inventories(self):
        """Ensure that appropriate inventories are available.

        This only applies to repositories that are stacked, and is about
        enusring the stacking invariants. Namely, that for any revision that is
        present, we either have all of the file content, or we have the parent
        inventory and the delta file content.
        """
        if not self.repository._fallback_repositories:
            return
        if not self.repository._format.supports_chks:
            raise errors.BzrError(
                "Cannot commit directly to a stacked branch"
                " in pre-2a formats. See "
                "https://bugs.launchpad.net/bzr/+bug/375013 for details."
            )
        # This is a stacked repo, we need to make sure we have the parent
        # inventories for the parents.
        parent_keys = [(p,) for p in self.parents]
        parent_map = self.repository.inventories._index.get_parent_map(parent_keys)
        missing_parent_keys = {pk for pk in parent_keys if pk not in parent_map}
        fallback_repos = list(reversed(self.repository._fallback_repositories))
        missing_keys = [("inventories", pk[0]) for pk in missing_parent_keys]
        while missing_keys and fallback_repos:
            fallback_repo = fallback_repos.pop()
            source = fallback_repo._get_source(self.repository._format)
            sink = self.repository._get_sink()
            missing_keys = sink.insert_missing_keys(source, missing_keys)
        if missing_keys:
            raise errors.BzrError(
                "Unable to fill in parent inventories for a stacked branch"
            )

    def commit(self, message):
        """Make the actual commit.

        :return: The revision id of the recorded revision.
        """
        self._validate_unicode_text(message, "commit message")
        rev = _mod_revision.Revision(
            timestamp=self._timestamp,
            timezone=self._timezone,
            committer=self._committer,
            message=message,
            inventory_sha1=self.inv_sha1,
            revision_id=self._new_revision_id,
            properties=self._revprops,
        )
        rev.parent_ids = self.parents
        create_signatures = self._config_stack.get("create_signatures")
        if create_signatures in (
            _mod_config.SIGN_ALWAYS,
            _mod_config.SIGN_WHEN_POSSIBLE,
        ):
            testament = Testament(rev, self.revision_tree())
            plaintext = testament.as_short_text()
            try:
                self.repository.store_revision_signature(
                    gpg.GPGStrategy(self._config_stack),
                    plaintext,
                    self._new_revision_id,
                )
            except gpg.GpgNotInstalled as e:
                if create_signatures == _mod_config.SIGN_WHEN_POSSIBLE:
                    note("skipping commit signature: %s", e)
                else:
                    raise
            except gpg.SigningFailed as e:
                if create_signatures == _mod_config.SIGN_WHEN_POSSIBLE:
                    note("commit signature failed: %s", e)
                else:
                    raise
        self.repository._add_revision(rev)
        self._ensure_fallback_inventories()
        if self._owns_transaction:
            self.repository.commit_write_group()
        return self._new_revision_id

    def abort(self):
        """Abort the commit that is being built."""
        if self._owns_transaction:
            self.repository.abort_write_group()

    def revision_tree(self):
        """Return the tree that was just committed.

        After calling commit() this can be called to get a
        RevisionTree representing the newly committed tree. This is
        preferred to calling Repository.revision_tree() because that may
        require deserializing the inventory, while we already have a copy in
        memory.
        """
        if self._new_inventory is None:
            self._new_inventory = self.repository.get_inventory(self._new_revision_id)
        return inventorytree.InventoryRevisionTree(
            self.repository, self._new_inventory, self._new_revision_id
        )

    def finish_inventory(self):
        """Tell the builder that the inventory is finished.

        :return: The inventory id in the repository, which can be used with
            repository.get_inventory.
        """
        # an inventory delta was accumulated without creating a new
        # inventory.
        basis_id = self.basis_delta_revision
        self.inv_sha1, self._new_inventory = self.repository.add_inventory_by_delta(
            basis_id, self._basis_delta, self._new_revision_id, self.parents
        )
        return self._new_revision_id

    def _gen_revision_id(self):
        """Return new revision-id."""
        return generate_ids.gen_revision_id(self._committer, self._timestamp)

    def _require_root_change(self, tree):
        """Enforce an appropriate root object change.

        This is called once when record_iter_changes is called, if and only if
        the root was not in the delta calculated by record_iter_changes.

        :param tree: The tree which is being committed.
        """
        if self.repository.supports_rich_root():
            return
        if len(self.parents) == 0:
            raise errors.RootMissing()
        entry = entry_factory["directory"](tree.path2id(""), "", None)
        entry.revision = self._new_revision_id
        self._basis_delta.append(("", "", entry.file_id, entry))

    def _get_delta(self, ie, basis_inv, path):
        """Get a delta against the basis inventory for ie."""
        if not basis_inv.has_id(ie.file_id):
            # add
            result = (None, path, ie.file_id, ie)
            self._basis_delta.append(result)
            return result
        elif ie != basis_inv.get_entry(ie.file_id):
            # common but altered
            # TODO: avoid tis id2path call.
            result = (basis_inv.id2path(ie.file_id), path, ie.file_id, ie)
            self._basis_delta.append(result)
            return result
        else:
            # common, unaltered
            return None

    def _heads(self, file_id, revision_ids):
        """Calculate the graph heads for revision_ids in the graph of file_id.

        This can use either a per-file graph or a global revision graph as we
        have an identity relationship between the two graphs.
        """
        return self.__heads(revision_ids)

    def get_basis_delta(self):
        """Return the complete inventory delta versus the basis inventory.

        :return: An inventory delta, suitable for use with apply_delta, or
            Repository.add_inventory_by_delta, etc.
        """
        return self._basis_delta

    def record_iter_changes(
        self, tree, basis_revision_id, iter_changes, _entry_factory=entry_factory
    ):
        """Record a new tree via iter_changes.

        :param tree: The tree to obtain text contents from for changed objects.
        :param basis_revision_id: The revision id of the tree the iter_changes
            has been generated against. Currently assumed to be the same
            as self.parents[0] - if it is not, errors may occur.
        :param iter_changes: An iter_changes iterator with the changes to apply
            to basis_revision_id. The iterator must not include any items with
            a current kind of None - missing items must be either filtered out
            or errored-on before record_iter_changes sees the item.
        :param _entry_factory: Private method to bind entry_factory locally for
            performance.
        :return: A generator of (relpath, fs_hash) tuples for use with
            tree._observed_sha1.
        """
        # Create an inventory delta based on deltas between all the parents and
        # deltas between all the parent inventories. We use inventory delta's
        # between the inventory objects because iter_changes masks
        # last-changed-field only changes.
        # Working data:
        # file_id -> change map, change is fileid, paths, changed, versioneds,
        # parents, names, kinds, executables
        merged_ids = {}
        # {file_id -> revision_id -> inventory entry, for entries in parent
        # trees that are not parents[0]
        parent_entries = {}
        ghost_basis = False
        try:
            revtrees = list(self.repository.revision_trees(self.parents))
        except errors.NoSuchRevision:
            # one or more ghosts, slow path.
            revtrees = []
            for revision_id in self.parents:
                try:
                    revtrees.append(self.repository.revision_tree(revision_id))
                except errors.NoSuchRevision:
                    if not revtrees:
                        basis_revision_id = _mod_revision.NULL_REVISION
                        ghost_basis = True
                    revtrees.append(
                        self.repository.revision_tree(_mod_revision.NULL_REVISION)
                    )
        # The basis inventory from a repository
        if revtrees:
            basis_tree = revtrees[0]
        else:
            basis_tree = self.repository.revision_tree(_mod_revision.NULL_REVISION)
        basis_inv = basis_tree.root_inventory
        if len(self.parents) > 0:
            if basis_revision_id != self.parents[0] and not ghost_basis:
                raise Exception("arbitrary basis parents not yet supported with merges")
            for revtree in revtrees[1:]:
                for change in revtree.root_inventory._make_delta(basis_inv):
                    if change[1] is None:
                        # Not present in this parent.
                        continue
                    if change[2] not in merged_ids:
                        if change[0] is not None:
                            basis_entry = basis_inv.get_entry(change[2])
                            merged_ids[change[2]] = [
                                # basis revid
                                basis_entry.revision,
                                # new tree revid
                                change[3].revision,
                            ]
                            parent_entries[change[2]] = {
                                # basis parent
                                basis_entry.revision: basis_entry,
                                # this parent
                                change[3].revision: change[3],
                            }
                        else:
                            merged_ids[change[2]] = [change[3].revision]
                            parent_entries[change[2]] = {change[3].revision: change[3]}
                    else:
                        merged_ids[change[2]].append(change[3].revision)
                        parent_entries[change[2]][change[3].revision] = change[3]
        else:
            merged_ids = {}
        # Setup the changes from the tree:
        # changes maps file_id -> (change, [parent revision_ids])
        changes = {}
        for change in iter_changes:
            # This probably looks up in basis_inv way to much.
            if change.path[0] is not None:
                head_candidate = [basis_inv.get_entry(change.file_id).revision]
            else:
                head_candidate = []
            changes[change.file_id] = (
                change,
                merged_ids.get(change.file_id, head_candidate),
            )
        unchanged_merged = set(merged_ids) - set(changes)
        # Extend the changes dict with synthetic changes to record merges of
        # texts.
        for file_id in unchanged_merged:
            # Record a merged version of these items that did not change vs the
            # basis. This can be either identical parallel changes, or a revert
            # of a specific file after a merge. The recorded content will be
            # that of the current tree (which is the same as the basis), but
            # the per-file graph will reflect a merge.
            # NB:XXX: We are reconstructing path information we had, this
            # should be preserved instead.
            # inv delta  change: (file_id, (path_in_source, path_in_target),
            #   changed_content, versioned, parent, name, kind,
            #   executable)
            try:
                basis_entry = basis_inv.get_entry(file_id)
            except errors.NoSuchId:
                # a change from basis->some_parents but file_id isn't in basis
                # so was new in the merge, which means it must have changed
                # from basis -> current, and as it hasn't the add was reverted
                # by the user. So we discard this change.
                pass
            else:
                change = InventoryTreeChange(
                    file_id,
                    (basis_inv.id2path(file_id), tree.id2path(file_id)),
                    False,
                    (True, True),
                    (basis_entry.parent_id, basis_entry.parent_id),
                    (basis_entry.name, basis_entry.name),
                    (basis_entry.kind, basis_entry.kind),
                    (basis_entry.executable, basis_entry.executable),
                )
                changes[file_id] = (change, merged_ids[file_id])
        # changes contains tuples with the change and a set of inventory
        # candidates for the file.
        # inv delta is:
        # old_path, new_path, file_id, new_inventory_entry
        seen_root = False  # Is the root in the basis delta?
        inv_delta = self._basis_delta
        modified_rev = self._new_revision_id
        for change, head_candidates in changes.values():
            if change.versioned[1]:  # versioned in target.
                # Several things may be happening here:
                # We may have a fork in the per-file graph
                #  - record a change with the content from tree
                # We may have a change against < all trees
                #  - carry over the tree that hasn't changed
                # We may have a change against all trees
                #  - record the change with the content from tree
                kind = change.kind[1]
                file_id = change.file_id
                entry = _entry_factory[kind](
                    file_id, change.name[1], change.parent_id[1]
                )
                head_set = self._heads(change.file_id, set(head_candidates))
                heads = []
                # Preserve ordering.
                for head_candidate in head_candidates:
                    if head_candidate in head_set:
                        heads.append(head_candidate)
                        head_set.remove(head_candidate)
                carried_over = False
                if len(heads) == 1:
                    # Could be a carry-over situation:
                    parent_entry_revs = parent_entries.get(file_id)
                    if parent_entry_revs:
                        parent_entry = parent_entry_revs.get(heads[0], None)
                    else:
                        parent_entry = None
                    if parent_entry is None:
                        # The parent iter_changes was called against is the one
                        # that is the per-file head, so any change is relevant
                        # iter_changes is valid.
                        carry_over_possible = False
                    else:
                        # could be a carry over situation
                        # A change against the basis may just indicate a merge,
                        # we need to check the content against the source of the
                        # merge to determine if it was changed after the merge
                        # or carried over.
                        if (
                            parent_entry.kind != entry.kind
                            or parent_entry.parent_id != entry.parent_id
                            or parent_entry.name != entry.name
                        ):
                            # Metadata common to all entries has changed
                            # against per-file parent
                            carry_over_possible = False
                        else:
                            carry_over_possible = True
                        # per-type checks for changes against the parent_entry
                        # are done below.
                else:
                    # Cannot be a carry-over situation
                    carry_over_possible = False
                # Populate the entry in the delta
                if kind == "file":
                    # XXX: There is still a small race here: If someone reverts
                    # the content of a file after iter_changes examines and
                    # decides it has changed, we will unconditionally record a
                    # new version even if some other process reverts it while
                    # commit is running (with the revert happening after
                    # iter_changes did its examination).
                    if change.executable[1]:
                        entry.executable = True
                    else:
                        entry.executable = False
                    if (
                        carry_over_possible
                        and parent_entry.executable == entry.executable
                    ):
                        # Check the file length, content hash after reading
                        # the file.
                        nostore_sha = parent_entry.text_sha1
                    else:
                        nostore_sha = None
                    file_obj, stat_value = tree.get_file_with_stat(change.path[1])
                    try:
                        entry.text_sha1, entry.text_size = self._add_file_to_weave(
                            file_id,
                            file_obj,
                            heads,
                            nostore_sha,
                            size=(stat_value.st_size if stat_value else None),
                        )
                        yield change.path[1], (entry.text_sha1, stat_value)
                    except versionedfile.ExistingContent:
                        # No content change against a carry_over parent
                        # Perhaps this should also yield a fs hash update?
                        carried_over = True
                        entry.text_size = parent_entry.text_size
                        entry.text_sha1 = parent_entry.text_sha1
                    finally:
                        file_obj.close()
                elif kind == "symlink":
                    # Wants a path hint?
                    entry.symlink_target = tree.get_symlink_target(change.path[1])
                    if (
                        carry_over_possible
                        and parent_entry.symlink_target == entry.symlink_target
                    ):
                        carried_over = True
                    else:
                        self._add_file_to_weave(
                            change.file_id, BytesIO(), heads, None, size=0
                        )
                elif kind == "directory":
                    if carry_over_possible:
                        carried_over = True
                    else:
                        # Nothing to set on the entry.
                        # XXX: split into the Root and nonRoot versions.
                        if change.path[1] != "" or self.repository.supports_rich_root():
                            self._add_file_to_weave(
                                change.file_id, BytesIO(), heads, None, size=0
                            )
                elif kind == "tree-reference":
                    if not self.repository._format.supports_tree_reference:
                        # This isn't quite sane as an error, but we shouldn't
                        # ever see this code path in practice: tree's don't
                        # permit references when the repo doesn't support tree
                        # references.
                        raise errors.UnsupportedOperation(
                            tree.add_reference, self.repository
                        )
                    reference_revision = tree.get_reference_revision(change.path[1])
                    entry.reference_revision = reference_revision
                    if (
                        carry_over_possible
                        and parent_entry.reference_revision == reference_revision
                    ):
                        carried_over = True
                    else:
                        self._add_file_to_weave(
                            change.file_id, BytesIO(), heads, None, size=0
                        )
                else:
                    raise AssertionError("unknown kind {!r}".format(kind))
                if not carried_over:
                    entry.revision = modified_rev
                else:
                    entry.revision = parent_entry.revision
            else:
                entry = None
            new_path = change.path[1]
            inv_delta.append((change.path[0], new_path, change.file_id, entry))
            if new_path == "":
                seen_root = True
        # The initial commit adds a root directory, but this in itself is not
        # a worthwhile commit.
        if (
            len(inv_delta) > 0 and basis_revision_id != _mod_revision.NULL_REVISION
        ) or (len(inv_delta) > 1 and basis_revision_id == _mod_revision.NULL_REVISION):
            # This should perhaps be guarded by a check that the basis we
            # commit against is the basis for the commit and if not do a delta
            # against the basis.
            self._any_changes = True
        if not seen_root:
            # housekeeping root entry changes do not affect no-change commits.
            self._require_root_change(tree)
        self.basis_delta_revision = basis_revision_id

    def _add_file_to_weave(self, file_id, fileobj, parents, nostore_sha, size):
        parent_keys = tuple([(file_id, parent) for parent in parents])
        return self.repository.texts.add_content(
            versionedfile.FileContentFactory(
                (file_id, self._new_revision_id), parent_keys, fileobj, size=size
            ),
            nostore_sha=nostore_sha,
            random_id=self.random_revid,
        )[0:2]


class VersionedFileRepository(Repository):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    The Repository builds on top of some byte storage facilies (the revisions,
    signatures, inventories, texts and chk_bytes attributes) and a Transport,
    which respectively provide byte storage and a means to access the (possibly
    remote) disk.

    The byte storage facilities are addressed via tuples, which we refer to
    as 'keys' throughout the code base. Revision_keys, inventory_keys and
    signature_keys are all 1-tuples: (revision_id,). text_keys are two-tuples:
    (file_id, revision_id). chk_bytes uses CHK keys - a 1-tuple with a single
    byte string made up of a hash identifier and a hash value.
    We use this interface because it allows low friction with the underlying
    code that implements disk indices, network encoding and other parts of
    breezy.

    :ivar revisions: A breezy.versionedfile.VersionedFiles instance containing
        the serialised revisions for the repository. This can be used to obtain
        revision graph information or to access raw serialised revisions.
        The result of trying to insert data into the repository via this store
        is undefined: it should be considered read-only except for implementors
        of repositories.
    :ivar signatures: A breezy.versionedfile.VersionedFiles instance containing
        the serialised signatures for the repository. This can be used to
        obtain access to raw serialised signatures.  The result of trying to
        insert data into the repository via this store is undefined: it should
        be considered read-only except for implementors of repositories.
    :ivar inventories: A breezy.versionedfile.VersionedFiles instance containing
        the serialised inventories for the repository. This can be used to
        obtain unserialised inventories.  The result of trying to insert data
        into the repository via this store is undefined: it should be
        considered read-only except for implementors of repositories.
    :ivar texts: A breezy.versionedfile.VersionedFiles instance containing the
        texts of files and directories for the repository. This can be used to
        obtain file texts or file graphs. Note that Repository.iter_file_bytes
        is usually a better interface for accessing file texts.
        The result of trying to insert data into the repository via this store
        is undefined: it should be considered read-only except for implementors
        of repositories.
    :ivar chk_bytes: A breezy.versionedfile.VersionedFiles instance containing
        any data the repository chooses to store or have indexed by its hash.
        The result of trying to insert data into the repository via this store
        is undefined: it should be considered read-only except for implementors
        of repositories.
    :ivar _transport: Transport for file access to repository, typically
        pointing to .bzr/repository.
    """

    # What class to use for a CommitBuilder. Often it's simpler to change this
    # in a Repository class subclass rather than to override
    # get_commit_builder.
    _commit_builder_class = VersionedFileCommitBuilder

    def add_fallback_repository(self, repository):
        """Add a repository to use for looking up data not held locally.

        :param repository: A repository.
        """
        if not self._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(self._format, self.base)
        # This can raise an exception, so should be done before we lock the
        # fallback repository.
        self._check_fallback_repository(repository)
        if self.is_locked():
            # This repository will call fallback.unlock() when we transition to
            # the unlocked state, so we make sure to increment the lock count
            repository.lock_read()
        self._fallback_repositories.append(repository)
        self.texts.add_fallback_versioned_files(repository.texts)
        self.inventories.add_fallback_versioned_files(repository.inventories)
        self.revisions.add_fallback_versioned_files(repository.revisions)
        self.signatures.add_fallback_versioned_files(repository.signatures)
        if self.chk_bytes is not None:
            self.chk_bytes.add_fallback_versioned_files(repository.chk_bytes)

    def create_bundle(self, target, base, fileobj, format=None):
        return serializer.write_bundle(self, target, base, fileobj, format)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        super().unlock()
        if self.control_files._lock_count == 0:
            self._inventory_entry_cache.clear()

    def add_inventory(self, revision_id, inv, parents):
        """Add the inventory inv to the repository as revision_id.

        :param parents: The revision ids of the parents that revision_id
                        is known to have and are in the repository already.

        :returns: The validator(which is a sha1 digest, though what is sha'd is
            repository format specific) of the serialized inventory.
        """
        if not self.is_in_write_group():
            raise AssertionError("{!r} not in write group".format(self))
        _mod_revision.check_not_reserved_id(revision_id)
        if not (inv.revision_id is None or inv.revision_id == revision_id):
            raise AssertionError(
                "Mismatch between inventory revision"
                " id and insertion revid ({!r}, {!r})".format(inv.revision_id, revision_id)
            )
        if inv.root is None:
            raise errors.RootMissing()
        return self._add_inventory_checked(revision_id, inv, parents)

    def _add_inventory_checked(self, revision_id, inv, parents):
        """Add inv to the repository after checking the inputs.

        This function can be overridden to allow different inventory styles.

        :seealso: add_inventory, for the contract.
        """
        inv_lines = self._serializer.write_inventory_to_lines(inv)
        return self._inventory_add_lines(
            revision_id, parents, inv_lines, check_content=False
        )

    def add_inventory_by_delta(
        self,
        basis_revision_id,
        delta,
        new_revision_id,
        parents,
        basis_inv=None,
        propagate_caches=False,
    ):
        """Add a new inventory expressed as a delta against another revision.

        See the inventory developers documentation for the theory behind
        inventory deltas.

        :param basis_revision_id: The inventory id the delta was created
            against. (This does not have to be a direct parent.)
        :param delta: The inventory delta (see Inventory.apply_delta for
            details).
        :param new_revision_id: The revision id that the inventory is being
            added for.
        :param parents: The revision ids of the parents that revision_id is
            known to have and are in the repository already. These are supplied
            for repositories that depend on the inventory graph for revision
            graph access, as well as for those that pun ancestry with delta
            compression.
        :param basis_inv: The basis inventory if it is already known,
            otherwise None.
        :param propagate_caches: If True, the caches for this inventory are
          copied to and updated for the result if possible.

        :returns: (validator, new_inv)
            The validator(which is a sha1 digest, though what is sha'd is
            repository format specific) of the serialized inventory, and the
            resulting inventory.
        """
        if not self.is_in_write_group():
            raise AssertionError("{!r} not in write group".format(self))
        _mod_revision.check_not_reserved_id(new_revision_id)
        basis_tree = self.revision_tree(basis_revision_id)
        with basis_tree.lock_read():
            # Note that this mutates the inventory of basis_tree, which not all
            # inventory implementations may support: A better idiom would be to
            # return a new inventory, but as there is no revision tree cache in
            # repository this is safe for now - RBC 20081013
            if basis_inv is None:
                basis_inv = basis_tree.root_inventory
            basis_inv.apply_delta(delta)
            basis_inv.revision_id = new_revision_id
            return (self.add_inventory(new_revision_id, basis_inv, parents), basis_inv)

    def _inventory_add_lines(self, revision_id, parents, lines, check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory."""
        parents = [(parent,) for parent in parents]
        result = self.inventories.add_lines(
            (revision_id,), parents, lines, check_content=check_content
        )[0]
        self.inventories._access.flush()
        return result

    def add_revision(self, revision_id, rev, inv=None):
        """Add rev to the revision store as revision_id.

        :param revision_id: the revision id to use.
        :param rev: The revision object.
        :param inv: The inventory for the revision. if None, it will be looked
                    up in the inventory storer
        """
        # TODO: jam 20070210 Shouldn't we check rev.revision_id and
        #       rev.parent_ids?
        _mod_revision.check_not_reserved_id(revision_id)
        # check inventory present
        if not self.inventories.get_parent_map([(revision_id,)]):
            if inv is None:
                raise errors.WeaveRevisionNotPresent(revision_id, self.inventories)
            else:
                # yes, this is not suitable for adding with ghosts.
                rev.inventory_sha1 = self.add_inventory(
                    revision_id, inv, rev.parent_ids
                )
        else:
            key = (revision_id,)
            rev.inventory_sha1 = self.inventories.get_sha1s([key])[key]
        self._add_revision(rev)

    def _add_revision(self, revision):
        lines = self._serializer.write_revision_to_lines(revision)
        key = (revision.revision_id,)
        parents = tuple((parent,) for parent in revision.parent_ids)
        self.revisions.add_lines(key, parents, lines)

    def _check_inventories(self, checker):
        """Check the inventories found from the revision scan.

        This is responsible for verifying the sha1 of inventories and
        creating a pending_keys set that covers data referenced by inventories.
        """
        with ui.ui_factory.nested_progress_bar() as bar:
            self._do_check_inventories(checker, bar)

    def _do_check_inventories(self, checker, bar):
        """Helper for _check_inventories."""
        keys = {"chk_bytes": set(), "inventories": set(), "texts": set()}
        kinds = ["chk_bytes", "texts"]
        len(checker.pending_keys)
        bar.update(gettext("inventories"), 0, 2)
        current_keys = checker.pending_keys
        checker.pending_keys = {}
        # Accumulate current checks.
        for key in current_keys:
            if key[0] != "inventories" and key[0] not in kinds:
                checker._report_items.append("unknown key type {!r}".format(key))
            keys[key[0]].add(key[1:])
        if keys["inventories"]:
            # NB: output order *should* be roughly sorted - topo or
            # inverse topo depending on repository - either way decent
            # to just delta against. However, pre-CHK formats didn't
            # try to optimise inventory layout on disk. As such the
            # pre-CHK code path does not use inventory deltas.
            last_object = None
            for record in self.inventories.check(keys=keys["inventories"]):
                if record.storage_kind == "absent":
                    checker._report_items.append(
                        "Missing inventory {{{}}}".format(record.key)
                    )
                else:
                    last_object = self._check_record(
                        "inventories",
                        record,
                        checker,
                        last_object,
                        current_keys[("inventories",) + record.key],
                    )
            del keys["inventories"]
        else:
            return
        bar.update(gettext("texts"), 1)
        while checker.pending_keys or keys["chk_bytes"] or keys["texts"]:
            # Something to check.
            current_keys = checker.pending_keys
            checker.pending_keys = {}
            # Accumulate current checks.
            for key in current_keys:
                if key[0] not in kinds:
                    checker._report_items.append("unknown key type {!r}".format(key))
                keys[key[0]].add(key[1:])
            # Check the outermost kind only - inventories || chk_bytes || texts
            for kind in kinds:
                if keys[kind]:
                    last_object = None
                    for record in getattr(self, kind).check(keys=keys[kind]):
                        if record.storage_kind == "absent":
                            checker._report_items.append(
                                "Missing {} {{{}}}".format(kind, record.key)
                            )
                        else:
                            last_object = self._check_record(
                                kind,
                                record,
                                checker,
                                last_object,
                                current_keys[(kind,) + record.key],
                            )
                    keys[kind] = set()
                    break

    def _check_record(self, kind, record, checker, last_object, item_data):
        """Check a single text from this repository."""
        if kind == "inventories":
            rev_id = record.key[0]
            inv = self._deserialise_inventory(rev_id, record.get_bytes_as("lines"))
            if last_object is not None:
                delta = inv._make_delta(last_object)
                for _old_path, _path, _file_id, ie in delta:
                    if ie is None:
                        continue
                    ie.check(checker, rev_id, inv)
            else:
                for _path, ie in inv.iter_entries():
                    ie.check(checker, rev_id, inv)
            if self._format.fast_deltas:
                return inv
        elif kind == "chk_bytes":
            # No code written to check chk_bytes for this repo format.
            checker._report_items.append(
                "unsupported key type chk_bytes for {}".format(record.key)
            )
        elif kind == "texts":
            self._check_text(record, checker, item_data)
        else:
            checker._report_items.append(
                "unknown key type {} for {}".format(kind, record.key)
            )

    def _check_text(self, record, checker, item_data):
        """Check a single text."""
        # Check it is extractable.
        # TODO: check length.
        chunks = record.get_bytes_as("chunked")
        sha1 = osutils.sha_strings(chunks)
        sum(map(len, chunks))
        if item_data and sha1 != item_data[1]:
            checker._report_items.append(
                "sha1 mismatch: {} has sha1 {} expected {} referenced by {}".format(record.key, sha1, item_data[1], item_data[2])
            )

    def _eliminate_revisions_not_present(self, revision_ids):
        """Check every revision id in revision_ids to see if we have it.

        Returns a set of the present revisions.
        """
        with self.lock_read():
            graph = self.get_graph()
            parent_map = graph.get_parent_map(revision_ids)
            # The old API returned a list, should this actually be a set?
            return list(parent_map)

    def __init__(self, _format, a_controldir, control_files):
        """Instantiate a VersionedFileRepository.

        :param _format: The format of the repository on disk.
        :param controldir: The ControlDir of the repository.
        :param control_files: Control files to use for locking, etc.
        """
        # In the future we will have a single api for all stores for
        # getting file texts, inventories and revisions, then
        # this construct will accept instances of those things.
        super().__init__(_format, a_controldir, control_files)
        self._transport = control_files._transport
        self.base = self._transport.base
        # for tests
        self._reconcile_does_inventory_gc = True
        self._reconcile_fixes_text_parents = False
        self._reconcile_backsup_inventory = True
        # An InventoryEntry cache, used during deserialization
        self._inventory_entry_cache = fifo_cache.FIFOCache(10 * 1024)
        # Is it safe to return inventory entries directly from the entry cache,
        # rather copying them?
        self._safe_to_return_from_cache = False

    def fetch(
        self, source, revision_id=None, find_ghosts=False, fetch_spec=None, lossy=False
    ):
        """Fetch the content required to construct revision_id from source.

        If revision_id is None and fetch_spec is None, then all content is
        copied.

        fetch() may not be used when the repository is in a write group -
        either finish the current write group before using fetch, or use
        fetch before starting the write group.

        :param find_ghosts: Find and copy revisions in the source that are
            ghosts in the target (and not reachable directly by walking out to
            the first-present revision in target from revision_id).
        :param revision_id: If specified, all the content needed for this
            revision ID will be copied to the target.  Fetch will determine for
            itself which content needs to be copied.
        :param fetch_spec: If specified, a SearchResult or
            PendingAncestryResult that describes which revisions to copy.  This
            allows copying multiple heads at once.  Mutually exclusive with
            revision_id.
        """
        if fetch_spec is not None and revision_id is not None:
            raise AssertionError("fetch_spec and revision_id are mutually exclusive.")
        if self.is_in_write_group():
            raise errors.InternalBzrError("May not fetch while in a write group.")
        # fast path same-url fetch operations
        # TODO: lift out to somewhere common with RemoteRepository
        # <https://bugs.launchpad.net/bzr/+bug/401646>
        if (
            self.has_same_location(source)
            and fetch_spec is None
            and self._has_same_fallbacks(source)
        ):
            # check that last_revision is in 'from' and then return a
            # no-operation.
            if revision_id is not None and not _mod_revision.is_null(revision_id):
                self.get_revision(revision_id)
            return FetchResult(0)
        inter = InterRepository.get(source, self)
        if fetch_spec is not None and not getattr(inter, "supports_fetch_spec", False):
            raise errors.UnsupportedOperation("fetch_spec not supported for {!r}".format(inter))
        return inter.fetch(
            revision_id=revision_id,
            find_ghosts=find_ghosts,
            fetch_spec=fetch_spec,
            lossy=lossy,
        )

    def gather_stats(self, revid=None, committers=None):
        """See Repository.gather_stats()."""
        with self.lock_read():
            result = super().gather_stats(revid, committers)
            # now gather global repository information
            # XXX: This is available for many repos regardless of listability.
            if self.user_transport.listable():
                # XXX: do we want to __define len__() ?
                # Maybe the versionedfiles object should provide a different
                # method to get the number of keys.
                result["revisions"] = len(self.revisions.keys())
                # result['size'] = t
            return result

    def get_commit_builder(
        self,
        branch,
        parents,
        config_stack,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this repository.

        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config_stack: Configuration stack to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        if self._fallback_repositories and not self._format.supports_chks:
            raise errors.BzrError(
                "Cannot commit directly to a stacked branch"
                " in pre-2a formats. See "
                "https://bugs.launchpad.net/bzr/+bug/375013 for details."
            )
        in_transaction = self.is_in_write_group()
        result = self._commit_builder_class(
            self,
            parents,
            config_stack,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy,
            owns_transaction=not in_transaction,
        )
        if not in_transaction:
            self.start_write_group()
        return result

    def get_missing_parent_inventories(self, check_for_missing_texts=True):
        """Return the keys of missing inventory parents for revisions added in
        this write group.

        A revision is not complete if the inventory delta for that revision
        cannot be calculated.  Therefore if the parent inventories of a
        revision are not present, the revision is incomplete, and e.g. cannot
        be streamed by a smart server.  This method finds missing inventory
        parents for revisions added in this write group.
        """
        if not self._format.supports_external_lookups:
            # This is only an issue for stacked repositories
            return set()
        if not self.is_in_write_group():
            raise AssertionError("not in a write group")

        # XXX: We assume that every added revision already has its
        # corresponding inventory, so we only check for parent inventories that
        # might be missing, rather than all inventories.
        parents = set(self.revisions._index.get_missing_parents())
        parents.discard(_mod_revision.NULL_REVISION)
        unstacked_inventories = self.inventories._index
        present_inventories = unstacked_inventories.get_parent_map(
            key[-1:] for key in parents
        )
        parents.difference_update(present_inventories)
        if len(parents) == 0:
            # No missing parent inventories.
            return set()
        if not check_for_missing_texts:
            return {("inventories", rev_id) for (rev_id,) in parents}
        # Ok, now we have a list of missing inventories.  But these only matter
        # if the inventories that reference them are missing some texts they
        # appear to introduce.
        # XXX: Texts referenced by all added inventories need to be present,
        # but at the moment we're only checking for texts referenced by
        # inventories at the graph's edge.
        key_deps = self.revisions._index._key_dependencies
        key_deps.satisfy_refs_for_keys(present_inventories)
        referrers = frozenset(r[0] for r in key_deps.get_referrers())
        file_ids = self.fileids_altered_by_revision_ids(referrers)
        missing_texts = set()
        for file_id, version_ids in file_ids.items():
            missing_texts.update((file_id, version_id) for version_id in version_ids)
        present_texts = self.texts.get_parent_map(missing_texts)
        missing_texts.difference_update(present_texts)
        if not missing_texts:
            # No texts are missing, so all revisions and their deltas are
            # reconstructable.
            return set()
        # Alternatively the text versions could be returned as the missing
        # keys, but this is likely to be less data.
        missing_keys = {("inventories", rev_id) for (rev_id,) in parents}
        return missing_keys

    def has_revisions(self, revision_ids):
        """Probe to find out the presence of multiple revisions.

        :param revision_ids: An iterable of revision_ids.
        :return: A set of the revision_ids that were present.
        """
        with self.lock_read():
            parent_map = self.revisions.get_parent_map(
                [(rev_id,) for rev_id in revision_ids]
            )
            result = set()
            if _mod_revision.NULL_REVISION in revision_ids:
                result.add(_mod_revision.NULL_REVISION)
            result.update([key[0] for key in parent_map])
            return result

    def get_revision_reconcile(self, revision_id):
        """'reconcile' helper routine that allows access to a revision always.

        This variant of get_revision does not cross check the weave graph
        against the revision one as get_revision does: but it should only
        be used by reconcile, or reconcile-alike commands that are correcting
        or testing the revision graph.
        """
        with self.lock_read():
            return self.get_revisions([revision_id])[0]

    def iter_revisions(self, revision_ids):
        """Iterate over revision objects.

        :param revision_ids: An iterable of revisions to examine. None may be
            passed to request all revisions known to the repository. Note that
            not all repositories can find unreferenced revisions; for those
            repositories only referenced ones will be returned.
        :return: An iterator of (revid, revision) tuples. Absent revisions (
            those asked for but not available) are returned as (revid, None).
        """
        with self.lock_read():
            for rev_id in revision_ids:
                if not rev_id or not isinstance(rev_id, bytes):
                    raise errors.InvalidRevisionId(revision_id=rev_id, branch=self)
            keys = [(key,) for key in revision_ids]
            stream = self.revisions.get_record_stream(keys, "unordered", True)
            for record in stream:
                revid = record.key[0]
                if record.storage_kind == "absent":
                    yield (revid, None)
                else:
                    text = record.get_bytes_as("fulltext")
                    rev = self._serializer.read_revision_from_string(text)
                    yield (revid, rev)

    def add_signature_text(self, revision_id, signature):
        """Store a signature text for a revision.

        :param revision_id: Revision id of the revision
        :param signature: Signature text.
        """
        with self.lock_write():
            self.signatures.add_lines(
                (revision_id,), (), osutils.split_lines(signature)
            )

    def sign_revision(self, revision_id, gpg_strategy):
        with self.lock_write():
            testament = Testament.from_revision(self, revision_id)
            plaintext = testament.as_short_text()
            self.store_revision_signature(gpg_strategy, plaintext, revision_id)

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        with self.lock_write():
            signature = gpg_strategy.sign(plaintext, gpg.MODE_CLEAR)
            self.add_signature_text(revision_id, signature)

    def verify_revision_signature(self, revision_id, gpg_strategy):
        """Verify the signature on a revision.

        :param revision_id: the revision to verify
        :gpg_strategy: the GPGStrategy object to used

        :return: gpg.SIGNATURE_VALID or a failed SIGNATURE_ value
        """
        with self.lock_read():
            if not self.has_signature_for_revision_id(revision_id):
                return gpg.SIGNATURE_NOT_SIGNED, None
            signature = self.get_signature_text(revision_id)

            testament = Testament.from_revision(self, revision_id)

            (status, key, signed_plaintext) = gpg_strategy.verify(signature)
            if testament.as_short_text() != signed_plaintext:
                return gpg.SIGNATURE_NOT_VALID, None
            return (status, key)

    def find_text_key_references(self):
        """Find the text key references within the repository.

        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. The inventory texts from all present
            revision ids are assessed to generate this report.
        """
        revision_keys = self.revisions.keys()
        w = self.inventories
        with ui.ui_factory.nested_progress_bar() as pb:
            return self._serializer._find_text_key_references(
                w.iter_lines_added_or_present_in_keys(revision_keys, pb=pb)
            )

    def _inventory_xml_lines_for_keys(self, keys):
        """Get a line iterator of the sort needed for findind references.

        Not relevant for non-xml inventory repositories.

        Ghosts in revision_keys are ignored.

        :param revision_keys: The revision keys for the inventories to inspect.
        :return: An iterator over (inventory line, revid) for the fulltexts of
            all of the xml inventories specified by revision_keys.
        """
        stream = self.inventories.get_record_stream(keys, "unordered", True)
        for record in stream:
            if record.storage_kind != "absent":
                revid = record.key[-1]
                for line in record.get_bytes_as("lines"):
                    yield line, revid

    def _find_file_ids_from_xml_inventory_lines(self, line_iterator, revision_keys):
        """Helper routine for fileids_altered_by_revision_ids.

        This performs the translation of xml lines to revision ids.

        :param line_iterator: An iterator of lines, origin_version_id
        :param revision_keys: The revision ids to filter for. This should be a
            set or other type which supports efficient __contains__ lookups, as
            the revision key from each parsed line will be looked up in the
            revision_keys filter.
        :return: a dictionary mapping altered file-ids to an iterable of
            revision_ids. Each altered file-ids has the exact revision_ids that
            altered it listed explicitly.
        """
        seen = set(self._serializer._find_text_key_references(line_iterator))
        parent_keys = self._find_parent_keys_of_revisions(revision_keys)
        parent_seen = set(
            self._serializer._find_text_key_references(
                self._inventory_xml_lines_for_keys(parent_keys)
            )
        )
        new_keys = seen - parent_seen
        result = {}
        setdefault = result.setdefault
        for key in new_keys:
            setdefault(key[0], set()).add(key[-1])
        return result

    def _find_parent_keys_of_revisions(self, revision_keys):
        """Similar to _find_parent_ids_of_revisions, but used with keys.

        :param revision_keys: An iterable of revision_keys.
        :return: The parents of all revision_keys that are not already in
            revision_keys
        """
        parent_map = self.revisions.get_parent_map(revision_keys)
        parent_keys = set(itertools.chain.from_iterable(parent_map.values()))
        parent_keys.difference_update(revision_keys)
        parent_keys.discard(_mod_revision.NULL_REVISION)
        return parent_keys

    def fileids_altered_by_revision_ids(self, revision_ids, _inv_weave=None):
        """Find the file ids and versions affected by revisions.

        :param revisions: an iterable containing revision ids.
        :param _inv_weave: The inventory weave from this repository or None.
            If None, the inventory weave will be opened automatically.
        :return: a dictionary mapping altered file-ids to an iterable of
            revision_ids. Each altered file-ids has the exact revision_ids that
            altered it listed explicitly.
        """
        selected_keys = {(revid,) for revid in revision_ids}
        w = _inv_weave or self.inventories
        return self._find_file_ids_from_xml_inventory_lines(
            w.iter_lines_added_or_present_in_keys(selected_keys, pb=None), selected_keys
        )

    def iter_files_bytes(self, desired_files):
        """Iterate through file versions.

        Files will not necessarily be returned in the order they occur in
        desired_files.  No specific order is guaranteed.

        Yields pairs of identifier, bytes_iterator.  identifier is an opaque
        value supplied by the caller as part of desired_files.  It should
        uniquely identify the file version in the caller's context.  (Examples:
        an index number or a TreeTransform trans_id.)

        bytes_iterator is an iterable of bytestrings for the file.  The
        kind of iterable and length of the bytestrings are unspecified, but for
        this implementation, it is a list of bytes produced by
        VersionedFile.get_record_stream().

        :param desired_files: a list of (file_id, revision_id, identifier)
            triples
        """
        text_keys = {}
        for file_id, revision_id, callable_data in desired_files:
            text_keys[(file_id, revision_id)] = callable_data
        for record in self.texts.get_record_stream(text_keys, "unordered", True):
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent(record.key[1], record.key[0])
            yield text_keys[record.key], record.iter_bytes_as("chunked")

    def _generate_text_key_index(self, text_key_references=None, ancestors=None):
        """Generate a new text key index for the repository.

        This is an expensive function that will take considerable time to run.

        :return: A dict mapping text keys ((file_id, revision_id) tuples) to a
            list of parents, also text keys. When a given key has no parents,
            the parents list will be [NULL_REVISION].
        """
        # All revisions, to find inventory parents.
        if ancestors is None:
            graph = self.get_graph()
            ancestors = graph.get_parent_map(self.all_revision_ids())
        if text_key_references is None:
            text_key_references = self.find_text_key_references()
        with ui.ui_factory.nested_progress_bar() as pb:
            return self._do_generate_text_key_index(ancestors, text_key_references, pb)

    def _do_generate_text_key_index(self, ancestors, text_key_references, pb):
        """Helper for _generate_text_key_index to avoid deep nesting."""
        revision_order = tsort.topo_sort(ancestors)
        invalid_keys = set()
        revision_keys = {}
        for revision_id in revision_order:
            revision_keys[revision_id] = set()
        text_count = len(text_key_references)
        # a cache of the text keys to allow reuse; costs a dict of all the
        # keys, but saves a 2-tuple for every child of a given key.
        text_key_cache = {}
        for text_key, valid in text_key_references.items():
            if not valid:
                invalid_keys.add(text_key)
            else:
                revision_keys[text_key[1]].add(text_key)
            text_key_cache[text_key] = text_key
        del text_key_references
        text_index = {}
        text_graph = graph.Graph(graph.DictParentsProvider(text_index))
        NULL_REVISION = _mod_revision.NULL_REVISION
        # Set a cache with a size of 10 - this suffices for bzr.dev but may be
        # too small for large or very branchy trees. However, for 55K path
        # trees, it would be easy to use too much memory trivially. Ideally we
        # could gauge this by looking at available real memory etc, but this is
        # always a tricky proposition.
        inventory_cache = lru_cache.LRUCache(10)
        batch_size = 10  # should be ~150MB on a 55K path tree
        batch_count = len(revision_order) // batch_size + 1
        processed_texts = 0
        pb.update(gettext("Calculating text parents"), processed_texts, text_count)
        for offset in range(batch_count):
            to_query = revision_order[offset * batch_size : (offset + 1) * batch_size]
            if not to_query:
                break
            for revision_id in to_query:
                parent_ids = ancestors[revision_id]
                for text_key in revision_keys[revision_id]:
                    pb.update(gettext("Calculating text parents"), processed_texts)
                    processed_texts += 1
                    candidate_parents = []
                    for parent_id in parent_ids:
                        parent_text_key = (text_key[0], parent_id)
                        try:
                            check_parent = (
                                parent_text_key not in revision_keys[parent_id]
                            )
                        except KeyError:
                            # the parent parent_id is a ghost:
                            check_parent = False
                            # truncate the derived graph against this ghost.
                            parent_text_key = None
                        if check_parent:
                            # look at the parent commit details inventories to
                            # determine possible candidates in the per file graph.
                            # TODO: cache here.
                            try:
                                inv = inventory_cache[parent_id]
                            except KeyError:
                                inv = self.revision_tree(parent_id).root_inventory
                                inventory_cache[parent_id] = inv
                            try:
                                parent_entry = inv.get_entry(text_key[0])
                            except (KeyError, errors.NoSuchId):
                                parent_entry = None
                            if parent_entry is not None:
                                parent_text_key = (text_key[0], parent_entry.revision)
                            else:
                                parent_text_key = None
                        if parent_text_key is not None:
                            candidate_parents.append(text_key_cache[parent_text_key])
                    parent_heads = text_graph.heads(candidate_parents)
                    new_parents = list(parent_heads)
                    new_parents.sort(key=lambda x: candidate_parents.index(x))
                    if new_parents == []:
                        new_parents = [NULL_REVISION]
                    text_index[text_key] = new_parents

        for text_key in invalid_keys:
            text_index[text_key] = [NULL_REVISION]
        return text_index

    def item_keys_introduced_by(self, revision_ids, _files_pb=None):
        """Get an iterable listing the keys of all the data introduced by a set
        of revision IDs.

        The keys will be ordered so that the corresponding items can be safely
        fetched and inserted in that order.

        :returns: An iterable producing tuples of (knit-kind, file-id,
            versions).  knit-kind is one of 'file', 'inventory', 'signatures',
            'revisions'.  file-id is None unless knit-kind is 'file'.
        """
        yield from self._find_file_keys_to_fetch(revision_ids, _files_pb)
        del _files_pb
        yield from self._find_non_file_keys_to_fetch(revision_ids)

    def _find_file_keys_to_fetch(self, revision_ids, pb):
        # XXX: it's a bit weird to control the inventory weave caching in this
        # generator.  Ideally the caching would be done in fetch.py I think.  Or
        # maybe this generator should explicitly have the contract that it
        # should not be iterated until the previously yielded item has been
        # processed?
        inv_w = self.inventories

        # file ids that changed
        file_ids = self.fileids_altered_by_revision_ids(revision_ids, inv_w)
        count = 0
        num_file_ids = len(file_ids)
        for file_id, altered_versions in file_ids.items():
            if pb is not None:
                pb.update(gettext("Fetch texts"), count, num_file_ids)
            count += 1
            yield ("file", file_id, altered_versions)

    def _find_non_file_keys_to_fetch(self, revision_ids):
        # inventory
        yield ("inventory", None, revision_ids)

        # signatures
        # XXX: Note ATM no callers actually pay attention to this return
        #      instead they just use the list of revision ids and ignore
        #      missing sigs. Consider removing this work entirely
        revisions_with_signatures = set(
            self.signatures.get_parent_map([(r,) for r in revision_ids])
        )
        revisions_with_signatures = {r for (r,) in revisions_with_signatures}
        revisions_with_signatures.intersection_update(revision_ids)
        yield ("signatures", None, revisions_with_signatures)

        # revisions
        yield ("revisions", None, revision_ids)

    def get_inventory(self, revision_id):
        """Get Inventory object by revision id."""
        with self.lock_read():
            return next(self.iter_inventories([revision_id]))

    def iter_inventories(self, revision_ids, ordering=None):
        """Get many inventories by revision_ids.

        This will buffer some or all of the texts used in constructing the
        inventories in memory, but will only parse a single inventory at a
        time.

        :param revision_ids: The expected revision ids of the inventories.
        :param ordering: optional ordering, e.g. 'topological'.  If not
            specified, the order of revision_ids will be preserved (by
            buffering if necessary).
        :return: An iterator of inventories.
        """
        if (None in revision_ids) or (_mod_revision.NULL_REVISION in revision_ids):
            raise ValueError("cannot get null revision inventory")
        for inv, revid in self._iter_inventories(revision_ids, ordering):
            if inv is None:
                raise errors.NoSuchRevision(self, revid)
            yield inv

    def _iter_inventories(self, revision_ids, ordering):
        """single-document based inventory iteration."""
        inv_xmls = self._iter_inventory_xmls(revision_ids, ordering)
        for lines, revision_id in inv_xmls:
            if lines is None:
                yield None, revision_id
            else:
                yield self._deserialise_inventory(revision_id, lines), revision_id

    def _iter_inventory_xmls(self, revision_ids, ordering):
        if ordering is None:
            order_as_requested = True
            ordering = "unordered"
        else:
            order_as_requested = False
        keys = [(revision_id,) for revision_id in revision_ids]
        if not keys:
            return
        if order_as_requested:
            key_iter = iter(keys)
            next_key = next(key_iter)
        stream = self.inventories.get_record_stream(keys, ordering, True)
        text_lines = {}
        for record in stream:
            if record.storage_kind != "absent":
                lines = record.get_bytes_as("lines")
                if order_as_requested:
                    text_lines[record.key] = lines
                else:
                    yield lines, record.key[-1]
            else:
                yield None, record.key[-1]
            if order_as_requested:
                # Yield as many results as we can while preserving order.
                while next_key in text_lines:
                    lines = text_lines.pop(next_key)
                    yield lines, next_key[-1]
                    try:
                        next_key = next(key_iter)
                    except StopIteration:
                        # We still want to fully consume the get_record_stream,
                        # just in case it is not actually finished at this point
                        next_key = None
                        break

    def _deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object.

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        result = self._serializer.read_inventory_from_lines(
            xml,
            revision_id,
            entry_cache=self._inventory_entry_cache,
            return_from_cache=self._safe_to_return_from_cache,
        )
        if result.revision_id != revision_id:
            raise AssertionError(
                "revision id mismatch {} != {}".format(result.revision_id, revision_id)
            )
        return result

    def get_serializer_format(self):
        return self._serializer.format_num

    def _get_inventory_xml(self, revision_id):
        """Get serialized inventory as a string."""
        with self.lock_read():
            texts = self._iter_inventory_xmls([revision_id], "unordered")
            lines, revision_id = next(texts)
            if lines is None:
                raise errors.NoSuchRevision(self, revision_id)
            return lines

    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be NULL_REVISION for the empty tree revision.
        """
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id == _mod_revision.NULL_REVISION:
            return inventorytree.InventoryRevisionTree(
                self, Inventory(root_id=None), _mod_revision.NULL_REVISION
            )
        else:
            with self.lock_read():
                inv = self.get_inventory(revision_id)
                return inventorytree.InventoryRevisionTree(self, inv, revision_id)

    def revision_trees(self, revision_ids):
        """Return Trees for revisions in this repository.

        :param revision_ids: a sequence of revision-ids;
          a revision-id may not be None or b'null:'
        """
        inventories = self.iter_inventories(revision_ids)
        for inv in inventories:
            yield inventorytree.InventoryRevisionTree(self, inv, inv.revision_id)

    def get_parent_map(self, revision_ids):
        """See graph.StackedParentsProvider.get_parent_map."""
        # revisions index works in keys; this just works in revisions
        # therefore wrap and unwrap
        query_keys = []
        result = {}
        for revision_id in revision_ids:
            if revision_id == _mod_revision.NULL_REVISION:
                result[revision_id] = ()
            elif revision_id is None:
                raise ValueError("get_parent_map(None) is not valid")
            else:
                query_keys.append((revision_id,))
        for (revision_id,), parent_keys in (
            self.revisions.get_parent_map(query_keys)
        ).items():
            if parent_keys:
                result[revision_id] = tuple(
                    [parent_revid for (parent_revid,) in parent_keys]
                )
            else:
                result[revision_id] = (_mod_revision.NULL_REVISION,)
        return result

    def get_known_graph_ancestry(self, revision_ids):
        """Return the known graph for a set of revision ids and their ancestors."""
        st = static_tuple.StaticTuple
        revision_keys = [st(r_id).intern() for r_id in revision_ids]
        with self.lock_read():
            known_graph = self.revisions.get_known_graph_ancestry(revision_keys)
            return graph.GraphThunkIdsToKeys(known_graph)

    def get_file_graph(self):
        """Return the graph walker for text revisions."""
        with self.lock_read():
            return graph.Graph(self.texts)

    def revision_ids_to_search_result(self, result_set):
        """Convert a set of revision ids to a graph SearchResult."""
        result_parents = set(
            itertools.chain.from_iterable(
                self.get_graph().get_parent_map(result_set).values()
            )
        )
        included_keys = result_set.intersection(result_parents)
        start_keys = result_set.difference(included_keys)
        exclude_keys = result_parents.difference(result_set)
        result = vf_search.SearchResult(
            start_keys, exclude_keys, len(result_set), result_set
        )
        return result

    def _get_versioned_file_checker(self, text_key_references=None, ancestors=None):
        """Return an object suitable for checking versioned files.

        :param text_key_references: if non-None, an already built
            dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. If None, this will be
            calculated.
        :param ancestors: Optional result from
            self.get_graph().get_parent_map(self.all_revision_ids()) if already
            available.
        """
        return _VersionedFileChecker(
            self, text_key_references=text_key_references, ancestors=ancestors
        )

    def has_signature_for_revision_id(self, revision_id):
        """Query for a revision signature for revision_id in the repository."""
        with self.lock_read():
            if not self.has_revision(revision_id):
                raise errors.NoSuchRevision(self, revision_id)
            sig_present = len(self.signatures.get_parent_map([(revision_id,)])) == 1
            return sig_present

    def get_signature_text(self, revision_id):
        """Return the text for a signature."""
        with self.lock_read():
            stream = self.signatures.get_record_stream(
                [(revision_id,)], "unordered", True
            )
            record = next(stream)
            if record.storage_kind == "absent":
                raise errors.NoSuchRevision(self, revision_id)
            return record.get_bytes_as("fulltext")

    def _check(self, revision_ids, callback_refs, check_repo):
        with self.lock_read():
            result = check.VersionedFileCheck(self, check_repo=check_repo)
            result.check(callback_refs)
            return result

    def _find_inconsistent_revision_parents(self, revisions_iterator=None):
        """Find revisions with different parent lists in the revision object
        and in the index graph.

        :param revisions_iterator: None, or an iterator of (revid,
            Revision-or-None). This iterator controls the revisions checked.
        :returns: an iterator yielding tuples of (revison-id, parents-in-index,
            parents-in-revision).
        """
        if not self.is_locked():
            raise AssertionError()
        vf = self.revisions
        if revisions_iterator is None:
            revisions_iterator = self.iter_revisions(self.all_revision_ids())
        for revid, revision in revisions_iterator:
            if revision is None:
                pass
            parent_map = vf.get_parent_map([(revid,)])
            parents_according_to_index = tuple(
                parent[-1] for parent in parent_map[(revid,)]
            )
            parents_according_to_revision = tuple(revision.parent_ids)
            if parents_according_to_index != parents_according_to_revision:
                yield (revid, parents_according_to_index, parents_according_to_revision)

    def _check_for_inconsistent_revision_parents(self):
        inconsistencies = list(self._find_inconsistent_revision_parents())
        if inconsistencies:
            raise errors.BzrCheckError("Revision knit has inconsistent parents.")

    def _get_sink(self):
        """Return a sink for streaming into this repository."""
        return StreamSink(self)

    def _get_source(self, to_format):
        """Return a source for streaming from this repository."""
        return StreamSource(self, to_format)

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from .reconcile import VersionedFileRepoReconciler

        with self.lock_write():
            reconciler = VersionedFileRepoReconciler(self, thorough=thorough)
            return reconciler.reconcile()


class MetaDirVersionedFileRepository(MetaDirRepository, VersionedFileRepository):
    """Repositories in a meta-dir, that work via versioned file objects."""

    def __init__(self, _format, a_controldir, control_files):
        super().__init__(_format, a_controldir, control_files)


class MetaDirVersionedFileRepositoryFormat(
    RepositoryFormatMetaDir, VersionedFileRepositoryFormat
):
    """Base class for repository formats using versioned files in metadirs."""


class StreamSink:
    """An object that can insert a stream into a repository.

    This interface handles the complexity of reserialising inventories and
    revisions from different formats, and allows unidirectional insertion into
    stacked repositories without looking for the missing basis parents
    beforehand.
    """

    def __init__(self, target_repo):
        self.target_repo = target_repo

    def insert_missing_keys(self, source, missing_keys):
        """Insert missing keys from another source.

        :param source: StreamSource to stream from
        :param missing_keys: Keys to insert
        :return: keys still missing
        """
        stream = source.get_stream_for_missing_keys(missing_keys)
        return self.insert_stream_without_locking(stream, self.target_repo._format)

    def insert_stream(self, stream, src_format, resume_tokens):
        """Insert a stream's content into the target repository.

        :param src_format: a bzr repository format.

        :return: a list of resume tokens and an  iterable of keys additional
            items required before the insertion can be completed.
        """
        with self.target_repo.lock_write():
            if resume_tokens:
                self.target_repo.resume_write_group(resume_tokens)
                is_resume = True
            else:
                self.target_repo.start_write_group()
                is_resume = False
            try:
                # locked_insert_stream performs a commit|suspend.
                missing_keys = self.insert_stream_without_locking(
                    stream, src_format, is_resume
                )
                if missing_keys:
                    # suspend the write group and tell the caller what we is
                    # missing. We know we can suspend or else we would not have
                    # entered this code path. (All repositories that can handle
                    # missing keys can handle suspending a write group).
                    write_group_tokens = self.target_repo.suspend_write_group()
                    return write_group_tokens, missing_keys
                hint = self.target_repo.commit_write_group()
                to_serializer = self.target_repo._format._serializer
                src_serializer = src_format._serializer
                if (
                    to_serializer != src_serializer
                    and self.target_repo._format.pack_compresses
                ):
                    self.target_repo.pack(hint=hint)
                return [], set()
            except:
                self.target_repo.abort_write_group(suppress_errors=True)
                raise

    def insert_stream_without_locking(self, stream, src_format, is_resume=False):
        """Insert a stream's content into the target repository.

        This assumes that you already have a locked repository and an active
        write group.

        :param src_format: a bzr repository format.
        :param is_resume: Passed down to get_missing_parent_inventories to
            indicate if we should be checking for missing texts at the same
            time.

        :return: A set of keys that are missing.
        """
        if not self.target_repo.is_write_locked():
            raise errors.ObjectNotLocked(self)
        if not self.target_repo.is_in_write_group():
            raise errors.BzrError("you must already be in a write group")
        to_serializer = self.target_repo._format._serializer
        src_serializer = src_format._serializer
        new_pack = None
        if to_serializer == src_serializer:
            # If serializers match and the target is a pack repository, set the
            # write cache size on the new pack.  This avoids poor performance
            # on transports where append is unbuffered (such as
            # RemoteTransport).  This is safe to do because nothing should read
            # back from the target repository while a stream with matching
            # serialization is being inserted.
            # The exception is that a delta record from the source that should
            # be a fulltext may need to be expanded by the target (see
            # test_fetch_revisions_with_deltas_into_pack); but we take care to
            # explicitly flush any buffered writes first in that rare case.
            try:
                new_pack = self.target_repo._pack_collection._new_pack
            except AttributeError:
                # Not a pack repository
                pass
            else:
                new_pack.set_write_cache_size(1024 * 1024)
        for substream_type, substream in stream:
            if "stream" in debug.debug_flags:
                mutter("inserting substream: %s", substream_type)
            if substream_type == "texts":
                self.target_repo.texts.insert_record_stream(substream)
            elif substream_type == "inventories":
                if src_serializer == to_serializer:
                    self.target_repo.inventories.insert_record_stream(substream)
                else:
                    self._extract_and_insert_inventories(substream, src_serializer)
            elif substream_type == "inventory-deltas":
                self._extract_and_insert_inventory_deltas(substream, src_serializer)
            elif substream_type == "chk_bytes":
                # XXX: This doesn't support conversions, as it assumes the
                #      conversion was done in the fetch code.
                self.target_repo.chk_bytes.insert_record_stream(substream)
            elif substream_type == "revisions":
                # This may fallback to extract-and-insert more often than
                # required if the serializers are different only in terms of
                # the inventory.
                if src_serializer == to_serializer:
                    self.target_repo.revisions.insert_record_stream(substream)
                else:
                    self._extract_and_insert_revisions(substream, src_serializer)
            elif substream_type == "signatures":
                self.target_repo.signatures.insert_record_stream(substream)
            else:
                raise AssertionError("kaboom! {}".format(substream_type))
        # Done inserting data, and the missing_keys calculations will try to
        # read back from the inserted data, so flush the writes to the new pack
        # (if this is pack format).
        if new_pack is not None:
            new_pack._write_data(b"", flush=True)
        # Find all the new revisions (including ones from resume_tokens)
        missing_keys = self.target_repo.get_missing_parent_inventories(
            check_for_missing_texts=is_resume
        )
        try:
            for prefix, versioned_file in (
                ("texts", self.target_repo.texts),
                ("inventories", self.target_repo.inventories),
                ("revisions", self.target_repo.revisions),
                ("signatures", self.target_repo.signatures),
                ("chk_bytes", self.target_repo.chk_bytes),
            ):
                if versioned_file is None:
                    continue
                # TODO: key is often going to be a StaticTuple object
                #       I don't believe we can define a method by which
                #       (prefix,) + StaticTuple will work, though we could
                #       define a StaticTuple.sq_concat that would allow you to
                #       pass in either a tuple or a StaticTuple as the second
                #       object, so instead we could have:
                #       StaticTuple(prefix) + key here...
                missing_keys.update(
                    (prefix,) + key
                    for key in versioned_file.get_missing_compression_parent_keys()
                )
        except NotImplementedError:
            # cannot even attempt suspending, and missing would have failed
            # during stream insertion.
            missing_keys = set()
        return missing_keys

    def _extract_and_insert_inventory_deltas(self, substream, serializer):
        for record in substream:
            # Insert the delta directly
            inventory_delta_bytes = record.get_bytes_as("lines")
            deserialiser = inventory_delta.InventoryDeltaDeserializer()
            try:
                parse_result = deserialiser.parse_text_bytes(inventory_delta_bytes)
            except inventory_delta.IncompatibleInventoryDelta as err:
                mutter("Incompatible delta: %s", err.msg)
                raise errors.IncompatibleRevision(self.target_repo._format)
            basis_id, new_id, rich_root, tree_refs, inv_delta = parse_result
            revision_id = new_id
            parents = [key[0] for key in record.parents]
            self.target_repo.add_inventory_by_delta(
                basis_id, inv_delta, revision_id, parents
            )

    def _extract_and_insert_inventories(self, substream, serializer, parse_delta=None):
        """Generate a new inventory versionedfile in target, converting data.

        The inventory is retrieved from the source, (deserializing it), and
        stored in the target (reserializing it in a different format).
        """
        for record in substream:
            # It's not a delta, so it must be a fulltext in the source
            # serializer's format.
            lines = record.get_bytes_as("lines")
            revision_id = record.key[0]
            inv = serializer.read_inventory_from_lines(lines, revision_id)
            parents = [key[0] for key in record.parents]
            self.target_repo.add_inventory(revision_id, inv, parents)
            # No need to keep holding this full inv in memory when the rest of
            # the substream is likely to be all deltas.
            del inv

    def _extract_and_insert_revisions(self, substream, serializer):
        for record in substream:
            bytes = record.get_bytes_as("fulltext")
            revision_id = record.key[0]
            rev = serializer.read_revision_from_string(bytes)
            if rev.revision_id != revision_id:
                raise AssertionError("wtf: {} != {}".format(rev, revision_id))
            self.target_repo.add_revision(revision_id, rev)

    def finished(self):
        if self.target_repo._format._fetch_reconcile:
            self.target_repo.reconcile()


class StreamSource:
    """A source of a stream for fetching between repositories."""

    def __init__(self, from_repository, to_format):
        """Create a StreamSource streaming from from_repository."""
        self.from_repository = from_repository
        self.to_format = to_format
        from .recordcounter import RecordCounter

        self._record_counter = RecordCounter()

    def delta_on_metadata(self):
        """Return True if delta's are permitted on metadata streams.

        That is on revisions and signatures.
        """
        src_serializer = self.from_repository._format._serializer
        target_serializer = self.to_format._serializer
        return self.to_format._fetch_uses_deltas and src_serializer == target_serializer

    def _fetch_revision_texts(self, revs):
        # fetch signatures first and then the revision texts
        # may need to be a InterRevisionStore call here.
        from_sf = self.from_repository.signatures
        # A missing signature is just skipped.
        keys = [(rev_id,) for rev_id in revs]
        signatures = versionedfile.filter_absent(
            from_sf.get_record_stream(
                keys, self.to_format._fetch_order, not self.to_format._fetch_uses_deltas
            )
        )
        # If a revision has a delta, this is actually expanded inside the
        # insert_record_stream code now, which is an alternate fix for
        # bug #261339
        from_rf = self.from_repository.revisions
        revisions = from_rf.get_record_stream(
            keys, self.to_format._fetch_order, not self.delta_on_metadata()
        )
        return [("signatures", signatures), ("revisions", revisions)]

    def _generate_root_texts(self, revs):
        """This will be called by get_stream between fetching weave texts and
        fetching the inventory weave.
        """
        if self._rich_root_upgrade():
            return _mod_fetch.Inter1and2Helper(
                self.from_repository
            ).generate_root_texts(revs)
        else:
            return []

    def get_stream(self, search):
        phase = "file"
        revs = search.get_keys()
        graph = self.from_repository.get_graph()
        revs = tsort.topo_sort(graph.get_parent_map(revs))
        data_to_fetch = self.from_repository.item_keys_introduced_by(revs)
        text_keys = []
        for knit_kind, file_id, revisions in data_to_fetch:
            if knit_kind != phase:
                phase = knit_kind
                # Make a new progress bar for this phase
            if knit_kind == "file":
                # Accumulate file texts
                text_keys.extend([(file_id, revision) for revision in revisions])
            elif knit_kind == "inventory":
                # Now copy the file texts.
                from_texts = self.from_repository.texts
                yield (
                    "texts",
                    from_texts.get_record_stream(
                        text_keys,
                        self.to_format._fetch_order,
                        not self.to_format._fetch_uses_deltas,
                    ),
                )
                # Cause an error if a text occurs after we have done the
                # copy.
                text_keys = None
                # Before we process the inventory we generate the root
                # texts (if necessary) so that the inventories references
                # will be valid.
                yield from self._generate_root_texts(revs)
                # we fetch only the referenced inventories because we do not
                # know for unselected inventories whether all their required
                # texts are present in the other repository - it could be
                # corrupt.
                yield from self._get_inventory_stream(revs)
            elif knit_kind == "signatures":
                # Nothing to do here; this will be taken care of when
                # _fetch_revision_texts happens.
                pass
            elif knit_kind == "revisions":
                yield from self._fetch_revision_texts(revs)
            else:
                raise AssertionError("Unknown knit kind {!r}".format(knit_kind))

    def get_stream_for_missing_keys(self, missing_keys):
        # missing keys can only occur when we are byte copying and not
        # translating (because translation means we don't send
        # unreconstructable deltas ever).
        keys = {}
        keys["texts"] = set()
        keys["revisions"] = set()
        keys["inventories"] = set()
        keys["chk_bytes"] = set()
        keys["signatures"] = set()
        for key in missing_keys:
            keys[key[0]].add(key[1:])
        if len(keys["revisions"]):
            # If we allowed copying revisions at this point, we could end up
            # copying a revision without copying its required texts: a
            # violation of the requirements for repository integrity.
            raise AssertionError(
                "cannot copy revisions to fill in missing deltas {}".format(
                    keys["revisions"]
                )
            )
        for substream_kind, keys in keys.items():
            vf = getattr(self.from_repository, substream_kind)
            if vf is None and keys:
                raise AssertionError(
                    "cannot fill in keys for a versioned file we don't"
                    " have: {} needs {}".format(substream_kind, keys)
                )
            if not keys:
                # No need to stream something we don't have
                continue
            if substream_kind == "inventories":
                # Some missing keys are genuinely ghosts, filter those out.
                present = self.from_repository.inventories.get_parent_map(keys)
                revs = [key[0] for key in present]
                # Get the inventory stream more-or-less as we do for the
                # original stream; there's no reason to assume that records
                # direct from the source will be suitable for the sink.  (Think
                # e.g. 2a -> 1.9-rich-root).
                yield from self._get_inventory_stream(revs, missing=True)
                continue

            # Ask for full texts always so that we don't need more round trips
            # after this stream.
            # Some of the missing keys are genuinely ghosts, so filter absent
            # records. The Sink is responsible for doing another check to
            # ensure that ghosts don't introduce missing data for future
            # fetches.
            stream = versionedfile.filter_absent(
                vf.get_record_stream(keys, self.to_format._fetch_order, True)
            )
            yield substream_kind, stream

    def inventory_fetch_order(self):
        if self._rich_root_upgrade():
            return "topological"
        else:
            return self.to_format._fetch_order

    def _rich_root_upgrade(self):
        return (
            not self.from_repository._format.rich_root_data
            and self.to_format.rich_root_data
        )

    def _get_inventory_stream(self, revision_ids, missing=False):
        from_format = self.from_repository._format
        if (
            from_format.supports_chks
            and self.to_format.supports_chks
            and from_format.network_name() == self.to_format.network_name()
        ):
            raise AssertionError("this case should be handled by GroupCHKStreamSource")
        elif "forceinvdeltas" in debug.debug_flags:
            return self._get_convertable_inventory_stream(
                revision_ids, delta_versus_null=missing
            )
        elif from_format.network_name() == self.to_format.network_name():
            # Same format.
            return self._get_simple_inventory_stream(revision_ids, missing=missing)
        elif (
            not from_format.supports_chks
            and not self.to_format.supports_chks
            and from_format._serializer == self.to_format._serializer
        ):
            # Essentially the same format.
            return self._get_simple_inventory_stream(revision_ids, missing=missing)
        else:
            # Any time we switch serializations, we want to use an
            # inventory-delta based approach.
            return self._get_convertable_inventory_stream(
                revision_ids, delta_versus_null=missing
            )

    def _get_simple_inventory_stream(self, revision_ids, missing=False):
        # NB: This currently reopens the inventory weave in source;
        # using a single stream interface instead would avoid this.
        from_weave = self.from_repository.inventories
        if missing:
            delta_closure = True
        else:
            delta_closure = not self.delta_on_metadata()
        yield (
            "inventories",
            from_weave.get_record_stream(
                [(rev_id,) for rev_id in revision_ids],
                self.inventory_fetch_order(),
                delta_closure,
            ),
        )

    def _get_convertable_inventory_stream(self, revision_ids, delta_versus_null=False):
        # The two formats are sufficiently different that there is no fast
        # path, so we need to send just inventorydeltas, which any
        # sufficiently modern client can insert into any repository.
        # The StreamSink code expects to be able to
        # convert on the target, so we need to put bytes-on-the-wire that can
        # be converted.  That means inventory deltas (if the remote is <1.19,
        # RemoteStreamSink will fallback to VFS to insert the deltas).
        yield (
            "inventory-deltas",
            self._stream_invs_as_deltas(
                revision_ids, delta_versus_null=delta_versus_null
            ),
        )

    def _stream_invs_as_deltas(self, revision_ids, delta_versus_null=False):
        """Return a stream of inventory-deltas for the given rev ids.

        :param revision_ids: The list of inventories to transmit
        :param delta_versus_null: Don't try to find a minimal delta for this
            entry, instead compute the delta versus the NULL_REVISION. This
            effectively streams a complete inventory. Used for stuff like
            filling in missing parents, etc.
        """
        from_repo = self.from_repository
        revision_keys = [(rev_id,) for rev_id in revision_ids]
        parent_map = from_repo.inventories.get_parent_map(revision_keys)
        # XXX: possibly repos could implement a more efficient iter_inv_deltas
        # method...
        inventories = self.from_repository.iter_inventories(revision_ids, "topological")
        format = from_repo._format
        invs_sent_so_far = {_mod_revision.NULL_REVISION}
        inventory_cache = lru_cache.LRUCache(50)
        null_inventory = from_repo.revision_tree(
            _mod_revision.NULL_REVISION
        ).root_inventory
        # XXX: ideally the rich-root/tree-refs flags would be per-revision, not
        # per-repo (e.g.  streaming a non-rich-root revision out of a rich-root
        # repo back into a non-rich-root repo ought to be allowed)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=format.rich_root_data,
            tree_references=format.supports_tree_reference,
        )
        for inv in inventories:
            key = (inv.revision_id,)
            parent_keys = parent_map.get(key, ())
            delta = None
            if not delta_versus_null and parent_keys:
                # The caller did not ask for complete inventories and we have
                # some parents that we can delta against.  Make a delta against
                # each parent so that we can find the smallest.
                parent_ids = [parent_key[0] for parent_key in parent_keys]
                for parent_id in parent_ids:
                    if parent_id not in invs_sent_so_far:
                        # We don't know that the remote side has this basis, so
                        # we can't use it.
                        continue
                    if parent_id == _mod_revision.NULL_REVISION:
                        parent_inv = null_inventory
                    else:
                        parent_inv = inventory_cache.get(parent_id, None)
                        if parent_inv is None:
                            parent_inv = from_repo.get_inventory(parent_id)
                    candidate_delta = inv._make_delta(parent_inv)
                    if delta is None or len(delta) > len(candidate_delta):
                        delta = candidate_delta
                        basis_id = parent_id
            if delta is None:
                # Either none of the parents ended up being suitable, or we
                # were asked to delta against NULL
                basis_id = _mod_revision.NULL_REVISION
                delta = inv._make_delta(null_inventory)
            invs_sent_so_far.add(inv.revision_id)
            inventory_cache[inv.revision_id] = inv
            delta_serialized = serializer.delta_to_lines(basis_id, key[-1], delta)
            yield versionedfile.ChunkedContentFactory(
                key, parent_keys, None, delta_serialized, chunks_are_lines=True
            )


class _VersionedFileChecker:
    def __init__(self, repository, text_key_references=None, ancestors=None):
        self.repository = repository
        self.text_index = self.repository._generate_text_key_index(
            text_key_references=text_key_references, ancestors=ancestors
        )

    def calculate_file_version_parents(self, text_key):
        """Calculate the correct parents for a file version according to
        the inventories.
        """
        parent_keys = self.text_index[text_key]
        if parent_keys == [_mod_revision.NULL_REVISION]:
            return ()
        return tuple(parent_keys)

    def check_file_version_parents(self, texts, progress_bar=None):
        """Check the parents stored in a versioned file are correct.

        It also detects file versions that are not referenced by their
        corresponding revision's inventory.

        :returns: A tuple of (wrong_parents, dangling_file_versions).
            wrong_parents is a dict mapping {revision_id: (stored_parents,
            correct_parents)} for each revision_id where the stored parents
            are not correct.  dangling_file_versions is a set of (file_id,
            revision_id) tuples for versions that are present in this versioned
            file, but not used by the corresponding inventory.
        """
        local_progress = None
        if progress_bar is None:
            local_progress = ui.ui_factory.nested_progress_bar()
            progress_bar = local_progress
        try:
            return self._check_file_version_parents(texts, progress_bar)
        finally:
            if local_progress:
                local_progress.finished()

    def _check_file_version_parents(self, texts, progress_bar):
        """See check_file_version_parents."""
        wrong_parents = {}
        self.file_ids = {file_id for file_id, _ in self.text_index}
        # text keys is now grouped by file_id
        n_versions = len(self.text_index)
        progress_bar.update(gettext("loading text store"), 0, n_versions)
        parent_map = self.repository.texts.get_parent_map(self.text_index)
        # On unlistable transports this could well be empty/error...
        text_keys = self.repository.texts.keys()
        unused_keys = frozenset(text_keys) - set(self.text_index)
        for num, key in enumerate(self.text_index):
            progress_bar.update(gettext("checking text graph"), num, n_versions)
            correct_parents = self.calculate_file_version_parents(key)
            try:
                knit_parents = parent_map[key]
            except errors.RevisionNotPresent:
                # Missing text!
                knit_parents = None
            if correct_parents != knit_parents:
                wrong_parents[key] = (knit_parents, correct_parents)
        return wrong_parents, unused_keys


class InterVersionedFileRepository(InterRepository):
    _walk_to_common_revisions_batch_size = 50

    supports_fetch_spec = True

    def fetch(self, revision_id=None, find_ghosts=False, fetch_spec=None, lossy=False):
        """Fetch the content required to construct revision_id.

        The content is copied from self.source to self.target.

        :param revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        :return: None.
        """
        if lossy:
            raise errors.LossyPushToSameVCS(self.source, self.target)
        if self.target._format.experimental:
            ui.ui_factory.show_user_warning(
                "experimental_format_fetch",
                from_format=self.source._format,
                to_format=self.target._format,
            )
        from breezy.bzr.fetch import RepoFetcher

        # See <https://launchpad.net/bugs/456077> asking for a warning here
        if self.source._format.network_name() != self.target._format.network_name():
            ui.ui_factory.show_user_warning(
                "cross_format_fetch",
                from_format=self.source._format,
                to_format=self.target._format,
            )
        with self.lock_write():
            RepoFetcher(
                to_repository=self.target,
                from_repository=self.source,
                last_revision=revision_id,
                fetch_spec=fetch_spec,
                find_ghosts=find_ghosts,
            )
            return FetchResult()

    def _walk_to_common_revisions(self, revision_ids, if_present_ids=None):
        """Walk out from revision_ids in source to revisions target has.

        :param revision_ids: The start point for the search.
        :return: A set of revision ids.
        """
        target_graph = self.target.get_graph()
        revision_ids = frozenset(revision_ids)
        if if_present_ids:
            all_wanted_revs = revision_ids.union(if_present_ids)
        else:
            all_wanted_revs = revision_ids
        missing_revs = set()
        source_graph = self.source.get_graph()
        # ensure we don't pay silly lookup costs.
        searcher = source_graph._make_breadth_first_searcher(all_wanted_revs)
        null_set = frozenset([_mod_revision.NULL_REVISION])
        searcher_exhausted = False
        while True:
            next_revs = set()
            ghosts = set()
            # Iterate the searcher until we have enough next_revs
            while len(next_revs) < self._walk_to_common_revisions_batch_size:
                try:
                    next_revs_part, ghosts_part = searcher.next_with_ghosts()
                    next_revs.update(next_revs_part)
                    ghosts.update(ghosts_part)
                except StopIteration:
                    searcher_exhausted = True
                    break
            # If there are ghosts in the source graph, and the caller asked for
            # them, make sure that they are present in the target.
            # We don't care about other ghosts as we can't fetch them and
            # haven't been asked to.
            ghosts_to_check = set(revision_ids.intersection(ghosts))
            revs_to_get = set(next_revs).union(ghosts_to_check)
            if revs_to_get:
                have_revs = set(target_graph.get_parent_map(revs_to_get))
                # we always have NULL_REVISION present.
                have_revs = have_revs.union(null_set)
                # Check if the target is missing any ghosts we need.
                ghosts_to_check.difference_update(have_revs)
                if ghosts_to_check:
                    # One of the caller's revision_ids is a ghost in both the
                    # source and the target.
                    raise errors.NoSuchRevision(self.source, ghosts_to_check.pop())
                missing_revs.update(next_revs - have_revs)
                # Because we may have walked past the original stop point, make
                # sure everything is stopped
                stop_revs = searcher.find_seen_ancestors(have_revs)
                searcher.stop_searching_any(stop_revs)
            if searcher_exhausted:
                break
        (started_keys, excludes, included_keys) = searcher.get_state()
        return vf_search.SearchResult(
            started_keys, excludes, len(included_keys), included_keys
        )

    def search_missing_revision_ids(
        self, find_ghosts=True, revision_ids=None, if_present_ids=None, limit=None
    ):
        """Return the revision ids that source has that target does not.

        :param revision_ids: return revision ids included by these
            revision_ids.  NoSuchRevision will be raised if any of these
            revisions are not present.
        :param if_present_ids: like revision_ids, but will not cause
            NoSuchRevision if any of these are absent, instead they will simply
            not be in the result.  This is useful for e.g. finding revisions
            to fetch for tags, which may reference absent revisions.
        :param find_ghosts: If True find missing revisions in deep history
            rather than just finding the surface difference.
        :return: A breezy.graph.SearchResult.
        """
        with self.lock_read():
            # stop searching at found target revisions.
            if not find_ghosts and (
                revision_ids is not None or if_present_ids is not None
            ):
                result = self._walk_to_common_revisions(
                    revision_ids, if_present_ids=if_present_ids
                )
                if limit is None:
                    return result
                result_set = result.get_keys()
            else:
                # generic, possibly worst case, slow code path.
                target_ids = set(self.target.all_revision_ids())
                source_ids = self._present_source_revisions_for(
                    revision_ids, if_present_ids
                )
                result_set = set(source_ids).difference(target_ids)
            if limit is not None:
                topo_ordered = self.source.get_graph().iter_topo_order(result_set)
                result_set = set(itertools.islice(topo_ordered, limit))
            return self.source.revision_ids_to_search_result(result_set)

    def _present_source_revisions_for(self, revision_ids, if_present_ids=None):
        """Returns set of all revisions in ancestry of revision_ids present in
        the source repo.

        :param revision_ids: if None, all revisions in source are returned.
        :param if_present_ids: like revision_ids, but if any/all of these are
            absent no error is raised.
        """
        if revision_ids is not None or if_present_ids is not None:
            # First, ensure all specified revisions exist.  Callers expect
            # NoSuchRevision when they pass absent revision_ids here.
            if revision_ids is None:
                revision_ids = set()
            if if_present_ids is None:
                if_present_ids = set()
            revision_ids = set(revision_ids)
            if_present_ids = set(if_present_ids)
            all_wanted_ids = revision_ids.union(if_present_ids)
            graph = self.source.get_graph()
            present_revs = set(graph.get_parent_map(all_wanted_ids))
            missing = revision_ids.difference(present_revs)
            if missing:
                raise errors.NoSuchRevision(self.source, missing.pop())
            found_ids = all_wanted_ids.intersection(present_revs)
            source_ids = [
                rev_id
                for (rev_id, parents) in graph.iter_ancestry(found_ids)
                if rev_id != _mod_revision.NULL_REVISION and parents is not None
            ]
        else:
            source_ids = self.source.all_revision_ids()
        return set(source_ids)

    @classmethod
    def _get_repo_format_to_test(self):
        return None

    @classmethod
    def is_compatible(cls, source, target):
        # The default implementation is compatible with everything
        return (
            source._format.supports_full_versioned_files
            and target._format.supports_full_versioned_files
        )


class InterDifferingSerializer(InterVersionedFileRepository):
    @classmethod
    def _get_repo_format_to_test(self):
        return None

    @staticmethod
    def is_compatible(source, target):
        if not source._format.supports_full_versioned_files:
            return False
        if not target._format.supports_full_versioned_files:
            return False
        # This is redundant with format.check_conversion_target(), however that
        # raises an exception, and we just want to say "False" as in we won't
        # support converting between these formats.
        if "IDS_never" in debug.debug_flags:
            return False
        if source.supports_rich_root() and not target.supports_rich_root():
            return False
        if (
            source._format.supports_tree_reference
            and not target._format.supports_tree_reference
        ):
            return False
        if target._fallback_repositories and target._format.supports_chks:
            # IDS doesn't know how to copy CHKs for the parent inventories it
            # adds to stacked repos.
            return False
        if "IDS_always" in debug.debug_flags:
            return True
        # Only use this code path for local source and target.  IDS does far
        # too much IO (both bandwidth and roundtrips) over a network.
        if not source.controldir.transport.base.startswith("file:///"):
            return False
        return target.controldir.transport.base.startswith("file:///")

    def _get_trees(self, revision_ids, cache):
        possible_trees = []
        for rev_id in revision_ids:
            if rev_id in cache:
                possible_trees.append((rev_id, cache[rev_id]))
            else:
                # Not cached, but inventory might be present anyway.
                try:
                    tree = self.source.revision_tree(rev_id)
                except errors.NoSuchRevision:
                    # Nope, parent is ghost.
                    pass
                else:
                    cache[rev_id] = tree
                    possible_trees.append((rev_id, tree))
        return possible_trees

    def _get_delta_for_revision(self, tree, parent_ids, possible_trees):
        """Get the best delta and base for this revision.

        :return: (basis_id, delta)
        """
        deltas = []
        # Generate deltas against each tree, to find the shortest.
        # FIXME: Support nested trees
        texts_possibly_new_in_tree = set()
        for basis_id, basis_tree in possible_trees:
            delta = tree.root_inventory._make_delta(basis_tree.root_inventory)
            for _old_path, new_path, file_id, new_entry in delta:
                if new_path is None:
                    # This file_id isn't present in the new rev, so we don't
                    # care about it.
                    continue
                if not new_path:
                    # Rich roots are handled elsewhere...
                    continue
                kind = new_entry.kind
                if kind != "directory" and kind != "file":
                    # No text record associated with this inventory entry.
                    continue
                # This is a directory or file that has changed somehow.
                texts_possibly_new_in_tree.add((file_id, new_entry.revision))
            deltas.append((len(delta), basis_id, delta))
        deltas.sort()
        return deltas[0][1:]

    def _fetch_parent_invs_for_stacking(self, parent_map, cache):
        """Find all parent revisions that are absent, but for which the
        inventory is present, and copy those inventories.

        This is necessary to preserve correctness when the source is stacked
        without fallbacks configured.  (Note that in cases like upgrade the
        source may be not have _fallback_repositories even though it is
        stacked.)
        """
        parent_revs = set(itertools.chain.from_iterable(parent_map.values()))
        present_parents = self.source.get_parent_map(parent_revs)
        absent_parents = parent_revs.difference(present_parents)
        parent_invs_keys_for_stacking = self.source.inventories.get_parent_map(
            (rev_id,) for rev_id in absent_parents
        )
        parent_inv_ids = [key[-1] for key in parent_invs_keys_for_stacking]
        for parent_tree in self.source.revision_trees(parent_inv_ids):
            current_revision_id = parent_tree.get_revision_id()
            parents_parents_keys = parent_invs_keys_for_stacking[(current_revision_id,)]
            parents_parents = [key[-1] for key in parents_parents_keys]
            basis_id = _mod_revision.NULL_REVISION
            basis_tree = self.source.revision_tree(basis_id)
            delta = parent_tree.root_inventory._make_delta(basis_tree.root_inventory)
            self.target.add_inventory_by_delta(
                basis_id, delta, current_revision_id, parents_parents
            )
            cache[current_revision_id] = parent_tree

    def _fetch_batch(self, revision_ids, basis_id, cache):
        """Fetch across a few revisions.

        :param revision_ids: The revisions to copy
        :param basis_id: The revision_id of a tree that must be in cache, used
            as a basis for delta when no other base is available
        :param cache: A cache of RevisionTrees that we can use.
        :return: The revision_id of the last converted tree. The RevisionTree
            for it will be in cache
        """
        # Walk though all revisions; get inventory deltas, copy referenced
        # texts that delta references, insert the delta, revision and
        # signature.
        root_keys_to_create = set()
        text_keys = set()
        pending_deltas = []
        pending_revisions = []
        parent_map = self.source.get_parent_map(revision_ids)
        self._fetch_parent_invs_for_stacking(parent_map, cache)
        self.source._safe_to_return_from_cache = True
        for tree in self.source.revision_trees(revision_ids):
            # Find a inventory delta for this revision.
            # Find text entries that need to be copied, too.
            current_revision_id = tree.get_revision_id()
            parent_ids = parent_map.get(current_revision_id, ())
            parent_trees = self._get_trees(parent_ids, cache)
            possible_trees = list(parent_trees)
            if len(possible_trees) == 0:
                # There either aren't any parents, or the parents are ghosts,
                # so just use the last converted tree.
                possible_trees.append((basis_id, cache[basis_id]))
            basis_id, delta = self._get_delta_for_revision(
                tree, parent_ids, possible_trees
            )
            revision = self.source.get_revision(current_revision_id)
            pending_deltas.append(
                (basis_id, delta, current_revision_id, revision.parent_ids)
            )
            if self._converting_to_rich_root:
                self._revision_id_to_root_id[current_revision_id] = tree.path2id("")
            # Determine which texts are in present in this revision but not in
            # any of the available parents.
            texts_possibly_new_in_tree = set()
            for _old_path, new_path, file_id, entry in delta:
                if new_path is None:
                    # This file_id isn't present in the new rev
                    continue
                if not new_path:
                    # This is the root
                    if not self.target.supports_rich_root():
                        # The target doesn't support rich root, so we don't
                        # copy
                        continue
                    if self._converting_to_rich_root:
                        # This can't be copied normally, we have to insert
                        # it specially
                        root_keys_to_create.add((file_id, entry.revision))
                        continue
                texts_possibly_new_in_tree.add((file_id, entry.revision))
            for basis_id, basis_tree in possible_trees:
                basis_inv = basis_tree.root_inventory
                for file_key in list(texts_possibly_new_in_tree):
                    file_id, file_revision = file_key
                    try:
                        entry = basis_inv.get_entry(file_id)
                    except errors.NoSuchId:
                        continue
                    if entry.revision == file_revision:
                        texts_possibly_new_in_tree.remove(file_key)
            text_keys.update(texts_possibly_new_in_tree)
            pending_revisions.append(revision)
            cache[current_revision_id] = tree
            basis_id = current_revision_id
        self.source._safe_to_return_from_cache = False
        # Copy file texts
        from_texts = self.source.texts
        to_texts = self.target.texts
        if root_keys_to_create:
            root_stream = _mod_fetch._new_root_data_stream(
                root_keys_to_create,
                self._revision_id_to_root_id,
                parent_map,
                self.source,
            )
            to_texts.insert_record_stream(root_stream)
        to_texts.insert_record_stream(
            from_texts.get_record_stream(
                text_keys,
                self.target._format._fetch_order,
                not self.target._format._fetch_uses_deltas,
            )
        )
        # insert inventory deltas
        for delta in pending_deltas:
            self.target.add_inventory_by_delta(*delta)
        if self.target._fallback_repositories:
            # Make sure this stacked repository has all the parent inventories
            # for the new revisions that we are about to insert.  We do this
            # before adding the revisions so that no revision is added until
            # all the inventories it may depend on are added.
            # Note that this is overzealous, as we may have fetched these in an
            # earlier batch.
            parent_ids = set()
            revision_ids = set()
            for revision in pending_revisions:
                revision_ids.add(revision.revision_id)
                parent_ids.update(revision.parent_ids)
            parent_ids.difference_update(revision_ids)
            parent_ids.discard(_mod_revision.NULL_REVISION)
            parent_map = self.source.get_parent_map(parent_ids)
            # we iterate over parent_map and not parent_ids because we don't
            # want to try copying any revision which is a ghost
            for parent_tree in self.source.revision_trees(parent_map):
                current_revision_id = parent_tree.get_revision_id()
                parents_parents = parent_map[current_revision_id]
                possible_trees = self._get_trees(parents_parents, cache)
                if len(possible_trees) == 0:
                    # There either aren't any parents, or the parents are
                    # ghosts, so just use the last converted tree.
                    possible_trees.append((basis_id, cache[basis_id]))
                basis_id, delta = self._get_delta_for_revision(
                    parent_tree, parents_parents, possible_trees
                )
                self.target.add_inventory_by_delta(
                    basis_id, delta, current_revision_id, parents_parents
                )
        # insert signatures and revisions
        for revision in pending_revisions:
            try:
                signature = self.source.get_signature_text(revision.revision_id)
                self.target.add_signature_text(revision.revision_id, signature)
            except errors.NoSuchRevision:
                pass
            self.target.add_revision(revision.revision_id, revision)
        return basis_id

    def _fetch_all_revisions(self, revision_ids, pb):
        """Fetch everything for the list of revisions.

        :param revision_ids: The list of revisions to fetch. Must be in
            topological order.
        :param pb: A ProgressTask
        :return: None
        """
        basis_id, basis_tree = self._get_basis(revision_ids[0])
        batch_size = 100
        cache = lru_cache.LRUCache(100)
        cache[basis_id] = basis_tree
        del basis_tree  # We don't want to hang on to it here
        hints = []

        for offset in range(0, len(revision_ids), batch_size):
            self.target.start_write_group()
            try:
                pb.update(gettext("Transferring revisions"), offset, len(revision_ids))
                batch = revision_ids[offset : offset + batch_size]
                basis_id = self._fetch_batch(batch, basis_id, cache)
            except:
                self.source._safe_to_return_from_cache = False
                self.target.abort_write_group()
                raise
            else:
                hint = self.target.commit_write_group()
                if hint:
                    hints.extend(hint)
        if hints and self.target._format.pack_compresses:
            self.target.pack(hint=hints)
        pb.update(
            gettext("Transferring revisions"), len(revision_ids), len(revision_ids)
        )

    def fetch(self, revision_id=None, find_ghosts=False, fetch_spec=None, lossy=False):
        """See InterRepository.fetch()."""
        if lossy:
            raise errors.LossyPushToSameVCS(self.source, self.target)
        if fetch_spec is not None:
            revision_ids = fetch_spec.get_keys()
        else:
            revision_ids = None
        if self.source._format.experimental:
            ui.ui_factory.show_user_warning(
                "experimental_format_fetch",
                from_format=self.source._format,
                to_format=self.target._format,
            )
        if not self.source.supports_rich_root() and self.target.supports_rich_root():
            self._converting_to_rich_root = True
            self._revision_id_to_root_id = {}
        else:
            self._converting_to_rich_root = False
        # See <https://launchpad.net/bugs/456077> asking for a warning here
        if self.source._format.network_name() != self.target._format.network_name():
            ui.ui_factory.show_user_warning(
                "cross_format_fetch",
                from_format=self.source._format,
                to_format=self.target._format,
            )
        with self.lock_write():
            if revision_ids is None:
                if revision_id:
                    search_revision_ids = [revision_id]
                else:
                    search_revision_ids = None
                revision_ids = self.target.search_missing_revision_ids(
                    self.source,
                    revision_ids=search_revision_ids,
                    find_ghosts=find_ghosts,
                ).get_keys()
            if not revision_ids:
                return FetchResult(0)
            revision_ids = tsort.topo_sort(
                self.source.get_graph().get_parent_map(revision_ids)
            )
            if not revision_ids:
                return FetchResult(0)
            # Walk though all revisions; get inventory deltas, copy referenced
            # texts that delta references, insert the delta, revision and
            # signature.
            with ui.ui_factory.nested_progress_bar() as pb:
                self._fetch_all_revisions(revision_ids, pb)
            return FetchResult(len(revision_ids))

    def _get_basis(self, first_revision_id):
        """Get a revision and tree which exists in the target.

        This assumes that first_revision_id is selected for transmission
        because all other ancestors are already present. If we can't find an
        ancestor we fall back to NULL_REVISION since we know that is safe.

        :return: (basis_id, basis_tree)
        """
        first_rev = self.source.get_revision(first_revision_id)
        try:
            basis_id = first_rev.parent_ids[0]
            # only valid as a basis if the target has it
            self.target.get_revision(basis_id)
            # Try to get a basis tree - if it's a ghost it will hit the
            # NoSuchRevision case.
            basis_tree = self.source.revision_tree(basis_id)
        except (IndexError, errors.NoSuchRevision):
            basis_id = _mod_revision.NULL_REVISION
            basis_tree = self.source.revision_tree(basis_id)
        return basis_id, basis_tree


class InterSameDataRepository(InterVersionedFileRepository):
    """Code for converting between repositories that represent the same data.

    Data format and model must match for this to work.
    """

    @classmethod
    def _get_repo_format_to_test(self):
        """Repository format for testing with.

        InterSameData can pull from subtree to subtree and from non-subtree to
        non-subtree, so we test this with the richest repository format.
        """
        from breezy.bzr import knitrepo

        return knitrepo.RepositoryFormatKnit3()

    @staticmethod
    def is_compatible(source, target):
        return (
            InterRepository._same_model(source, target)
            and source._format.supports_full_versioned_files
            and target._format.supports_full_versioned_files
        )


InterRepository.register_optimiser(InterVersionedFileRepository)
InterRepository.register_optimiser(InterDifferingSerializer)
InterRepository.register_optimiser(InterSameDataRepository)


def install_revisions(repository, iterable, num_revisions=None, pb=None):
    """Install all revision data into a repository.

    Accepts an iterable of revision, tree, signature tuples.  The signature
    may be None.
    """
    with WriteGroup(repository):
        inventory_cache = lru_cache.LRUCache(10)
        for n, (revision, revision_tree, signature) in enumerate(iterable):
            _install_revision(
                repository, revision, revision_tree, signature, inventory_cache
            )
            if pb is not None:
                pb.update(gettext("Transferring revisions"), n + 1, num_revisions)


def _install_revision(repository, rev, revision_tree, signature, inventory_cache):
    """Install all revision data into a repository."""
    present_parents = []
    parent_trees = {}
    for p_id in rev.parent_ids:
        if repository.has_revision(p_id):
            present_parents.append(p_id)
            parent_trees[p_id] = repository.revision_tree(p_id)
        else:
            parent_trees[p_id] = repository.revision_tree(_mod_revision.NULL_REVISION)

    # FIXME: Support nested trees
    inv = revision_tree.root_inventory
    entries = inv.iter_entries()
    # backwards compatibility hack: skip the root id.
    if not repository.supports_rich_root():
        path, root = next(entries)
        if root.revision != rev.revision_id:
            raise errors.IncompatibleRevision(repr(repository))
    text_keys = {}
    for path, ie in entries:
        text_keys[(ie.file_id, ie.revision)] = ie
    text_parent_map = repository.texts.get_parent_map(text_keys)
    missing_texts = set(text_keys) - set(text_parent_map)
    # Add the texts that are not already present
    for text_key in missing_texts:
        ie = text_keys[text_key]
        text_parents = []
        # FIXME: TODO: The following loop overlaps/duplicates that done by
        # commit to determine parents. There is a latent/real bug here where
        # the parents inserted are not those commit would do - in particular
        # they are not filtered by heads(). RBC, AB
        for _revision, tree in parent_trees.items():
            try:
                path = tree.id2path(ie.file_id)
            except errors.NoSuchId:
                continue
            parent_id = tree.get_file_revision(path)
            if parent_id in text_parents:
                continue
            text_parents.append((ie.file_id, parent_id))
        revision_tree_path = revision_tree.id2path(ie.file_id)
        with revision_tree.get_file(revision_tree_path) as f:
            lines = f.readlines()
        repository.texts.add_lines(text_key, text_parents, lines)
    try:
        # install the inventory
        if repository._format._commit_inv_deltas and len(rev.parent_ids):
            # Cache this inventory
            inventory_cache[rev.revision_id] = inv
            try:
                basis_inv = inventory_cache[rev.parent_ids[0]]
            except KeyError:
                repository.add_inventory(rev.revision_id, inv, present_parents)
            else:
                delta = inv._make_delta(basis_inv)
                repository.add_inventory_by_delta(
                    rev.parent_ids[0], delta, rev.revision_id, present_parents
                )
        else:
            repository.add_inventory(rev.revision_id, inv, present_parents)
    except errors.RevisionAlreadyPresent:
        pass
    if signature is not None:
        repository.add_signature_text(rev.revision_id, signature)
    repository.add_revision(rev.revision_id, rev, inv)


def install_revision(repository, rev, revision_tree):
    """Install all revision data into a repository."""
    install_revisions(repository, [(rev, revision_tree, None)])

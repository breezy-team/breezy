# Copyright (C) 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import cStringIO
import re
import time

from bzrlib import (
    bzrdir,
    check,
    chk_map,
    debug,
    errors,
    fifo_cache,
    generate_ids,
    gpg,
    graph,
    inventory,
    inventory_delta,
    lazy_regex,
    lockable_files,
    lockdir,
    lru_cache,
    osutils,
    revision as _mod_revision,
    symbol_versioning,
    tsort,
    ui,
    versionedfile,
    )
from bzrlib.bundle import serializer
from bzrlib.revisiontree import RevisionTree
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.testament import Testament
""")

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.inter import InterObject
from bzrlib.inventory import (
    Inventory,
    InventoryDirectory,
    ROOT_ID,
    entry_factory,
    )
from bzrlib import registry
from bzrlib.trace import (
    log_exception_quietly, note, mutter, mutter_callsite, warning)


# Old formats display a warning, but only once
_deprecation_warning_done = False


class CommitBuilder(object):
    """Provides an interface to build up a commit.

    This allows describing a tree to be committed without needing to
    know the internals of the format of the repository.
    """

    # all clients should supply tree roots.
    record_root_entry = True
    # the default CommitBuilder does not manage trees whose root is versioned.
    _versioned_root = False

    def __init__(self, repository, parents, config, timestamp=None,
                 timezone=None, committer=None, revprops=None,
                 revision_id=None):
        """Initiate a CommitBuilder.

        :param repository: Repository to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        """
        self._config = config

        if committer is None:
            self._committer = self._config.username()
        else:
            self._committer = committer

        self.new_inventory = Inventory(None)
        self._new_revision_id = revision_id
        self.parents = parents
        self.repository = repository

        self._revprops = {}
        if revprops is not None:
            self._validate_revprops(revprops)
            self._revprops.update(revprops)

        if timestamp is None:
            timestamp = time.time()
        # Restrict resolution to 1ms
        self._timestamp = round(timestamp, 3)

        if timezone is None:
            self._timezone = osutils.local_time_offset()
        else:
            self._timezone = int(timezone)

        self._generate_revision_if_needed()
        self.__heads = graph.HeadsCache(repository.get_graph()).heads
        self._basis_delta = []
        # API compatibility, older code that used CommitBuilder did not call
        # .record_delete(), which means the delta that is computed would not be
        # valid. Callers that will call record_delete() should call
        # .will_record_deletes() to indicate that.
        self._recording_deletes = False
        # memo'd check for no-op commits.
        self._any_changes = False

    def any_changes(self):
        """Return True if any entries were changed.
        
        This includes merge-only changes. It is the core for the --unchanged
        detection in commit.

        :return: True if any changes have occured.
        """
        return self._any_changes

    def _validate_unicode_text(self, text, context):
        """Verify things like commit messages don't have bogus characters."""
        if '\r' in text:
            raise ValueError('Invalid value for %s: %r' % (context, text))

    def _validate_revprops(self, revprops):
        for key, value in revprops.iteritems():
            # We know that the XML serializers do not round trip '\r'
            # correctly, so refuse to accept them
            if not isinstance(value, basestring):
                raise ValueError('revision property (%s) is not a valid'
                                 ' (unicode) string: %r' % (key, value))
            self._validate_unicode_text(value,
                                        'revision property (%s)' % (key,))

    def commit(self, message):
        """Make the actual commit.

        :return: The revision id of the recorded revision.
        """
        self._validate_unicode_text(message, 'commit message')
        rev = _mod_revision.Revision(
                       timestamp=self._timestamp,
                       timezone=self._timezone,
                       committer=self._committer,
                       message=message,
                       inventory_sha1=self.inv_sha1,
                       revision_id=self._new_revision_id,
                       properties=self._revprops)
        rev.parent_ids = self.parents
        self.repository.add_revision(self._new_revision_id, rev,
            self.new_inventory, self._config)
        self.repository.commit_write_group()
        return self._new_revision_id

    def abort(self):
        """Abort the commit that is being built.
        """
        self.repository.abort_write_group()

    def revision_tree(self):
        """Return the tree that was just committed.

        After calling commit() this can be called to get a RevisionTree
        representing the newly committed tree. This is preferred to
        calling Repository.revision_tree() because that may require
        deserializing the inventory, while we already have a copy in
        memory.
        """
        if self.new_inventory is None:
            self.new_inventory = self.repository.get_inventory(
                self._new_revision_id)
        return RevisionTree(self.repository, self.new_inventory,
            self._new_revision_id)

    def finish_inventory(self):
        """Tell the builder that the inventory is finished.

        :return: The inventory id in the repository, which can be used with
            repository.get_inventory.
        """
        if self.new_inventory is None:
            # an inventory delta was accumulated without creating a new
            # inventory.
            basis_id = self.basis_delta_revision
            self.inv_sha1 = self.repository.add_inventory_by_delta(
                basis_id, self._basis_delta, self._new_revision_id,
                self.parents)
        else:
            if self.new_inventory.root is None:
                raise AssertionError('Root entry should be supplied to'
                    ' record_entry_contents, as of bzr 0.10.')
                self.new_inventory.add(InventoryDirectory(ROOT_ID, '', None))
            self.new_inventory.revision_id = self._new_revision_id
            self.inv_sha1 = self.repository.add_inventory(
                self._new_revision_id,
                self.new_inventory,
                self.parents
                )
        return self._new_revision_id

    def _gen_revision_id(self):
        """Return new revision-id."""
        return generate_ids.gen_revision_id(self._config.username(),
                                            self._timestamp)

    def _generate_revision_if_needed(self):
        """Create a revision id if None was supplied.

        If the repository can not support user-specified revision ids
        they should override this function and raise CannotSetRevisionId
        if _new_revision_id is not None.

        :raises: CannotSetRevisionId
        """
        if self._new_revision_id is None:
            self._new_revision_id = self._gen_revision_id()
            self.random_revid = True
        else:
            self.random_revid = False

    def _heads(self, file_id, revision_ids):
        """Calculate the graph heads for revision_ids in the graph of file_id.

        This can use either a per-file graph or a global revision graph as we
        have an identity relationship between the two graphs.
        """
        return self.__heads(revision_ids)

    def _check_root(self, ie, parent_invs, tree):
        """Helper for record_entry_contents.

        :param ie: An entry being added.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param tree: The tree that is being committed.
        """
        # In this revision format, root entries have no knit or weave When
        # serializing out to disk and back in root.revision is always
        # _new_revision_id
        ie.revision = self._new_revision_id

    def _require_root_change(self, tree):
        """Enforce an appropriate root object change.

        This is called once when record_iter_changes is called, if and only if
        the root was not in the delta calculated by record_iter_changes.

        :param tree: The tree which is being committed.
        """
        # NB: if there are no parents then this method is not called, so no
        # need to guard on parents having length.
        entry = entry_factory['directory'](tree.path2id(''), '',
            None)
        entry.revision = self._new_revision_id
        self._basis_delta.append(('', '', entry.file_id, entry))

    def _get_delta(self, ie, basis_inv, path):
        """Get a delta against the basis inventory for ie."""
        if ie.file_id not in basis_inv:
            # add
            result = (None, path, ie.file_id, ie)
            self._basis_delta.append(result)
            return result
        elif ie != basis_inv[ie.file_id]:
            # common but altered
            # TODO: avoid tis id2path call.
            result = (basis_inv.id2path(ie.file_id), path, ie.file_id, ie)
            self._basis_delta.append(result)
            return result
        else:
            # common, unaltered
            return None

    def get_basis_delta(self):
        """Return the complete inventory delta versus the basis inventory.

        This has been built up with the calls to record_delete and
        record_entry_contents. The client must have already called
        will_record_deletes() to indicate that they will be generating a
        complete delta.

        :return: An inventory delta, suitable for use with apply_delta, or
            Repository.add_inventory_by_delta, etc.
        """
        if not self._recording_deletes:
            raise AssertionError("recording deletes not activated.")
        return self._basis_delta

    def record_delete(self, path, file_id):
        """Record that a delete occured against a basis tree.

        This is an optional API - when used it adds items to the basis_delta
        being accumulated by the commit builder. It cannot be called unless the
        method will_record_deletes() has been called to inform the builder that
        a delta is being supplied.

        :param path: The path of the thing deleted.
        :param file_id: The file id that was deleted.
        """
        if not self._recording_deletes:
            raise AssertionError("recording deletes not activated.")
        delta = (path, None, file_id, None)
        self._basis_delta.append(delta)
        self._any_changes = True
        return delta

    def will_record_deletes(self):
        """Tell the commit builder that deletes are being notified.

        This enables the accumulation of an inventory delta; for the resulting
        commit to be valid, deletes against the basis MUST be recorded via
        builder.record_delete().
        """
        self._recording_deletes = True
        try:
            basis_id = self.parents[0]
        except IndexError:
            basis_id = _mod_revision.NULL_REVISION
        self.basis_delta_revision = basis_id

    def record_entry_contents(self, ie, parent_invs, path, tree,
        content_summary):
        """Record the content of ie from tree into the commit if needed.

        Side effect: sets ie.revision when unchanged

        :param ie: An inventory entry present in the commit.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param path: The path the entry is at in the tree.
        :param tree: The tree which contains this entry and should be used to
            obtain content.
        :param content_summary: Summary data from the tree about the paths
            content - stat, length, exec, sha/link target. This is only
            accessed when the entry has a revision of None - that is when it is
            a candidate to commit.
        :return: A tuple (change_delta, version_recorded, fs_hash).
            change_delta is an inventory_delta change for this entry against
            the basis tree of the commit, or None if no change occured against
            the basis tree.
            version_recorded is True if a new version of the entry has been
            recorded. For instance, committing a merge where a file was only
            changed on the other side will return (delta, False).
            fs_hash is either None, or the hash details for the path (currently
            a tuple of the contents sha1 and the statvalue returned by
            tree.get_file_with_stat()).
        """
        if self.new_inventory.root is None:
            if ie.parent_id is not None:
                raise errors.RootMissing()
            self._check_root(ie, parent_invs, tree)
        if ie.revision is None:
            kind = content_summary[0]
        else:
            # ie is carried over from a prior commit
            kind = ie.kind
        # XXX: repository specific check for nested tree support goes here - if
        # the repo doesn't want nested trees we skip it ?
        if (kind == 'tree-reference' and
            not self.repository._format.supports_tree_reference):
            # mismatch between commit builder logic and repository:
            # this needs the entry creation pushed down into the builder.
            raise NotImplementedError('Missing repository subtree support.')
        self.new_inventory.add(ie)

        # TODO: slow, take it out of the inner loop.
        try:
            basis_inv = parent_invs[0]
        except IndexError:
            basis_inv = Inventory(root_id=None)

        # ie.revision is always None if the InventoryEntry is considered
        # for committing. We may record the previous parents revision if the
        # content is actually unchanged against a sole head.
        if ie.revision is not None:
            if not self._versioned_root and path == '':
                # repositories that do not version the root set the root's
                # revision to the new commit even when no change occurs (more
                # specifically, they do not record a revision on the root; and
                # the rev id is assigned to the root during deserialisation -
                # this masks when a change may have occurred against the basis.
                # To match this we always issue a delta, because the revision
                # of the root will always be changing.
                if ie.file_id in basis_inv:
                    delta = (basis_inv.id2path(ie.file_id), path,
                        ie.file_id, ie)
                else:
                    # add
                    delta = (None, path, ie.file_id, ie)
                self._basis_delta.append(delta)
                return delta, False, None
            else:
                # we don't need to commit this, because the caller already
                # determined that an existing revision of this file is
                # appropriate. If its not being considered for committing then
                # it and all its parents to the root must be unaltered so
                # no-change against the basis.
                if ie.revision == self._new_revision_id:
                    raise AssertionError("Impossible situation, a skipped "
                        "inventory entry (%r) claims to be modified in this "
                        "commit (%r).", (ie, self._new_revision_id))
                return None, False, None
        # XXX: Friction: parent_candidates should return a list not a dict
        #      so that we don't have to walk the inventories again.
        parent_candiate_entries = ie.parent_candidates(parent_invs)
        head_set = self._heads(ie.file_id, parent_candiate_entries.keys())
        heads = []
        for inv in parent_invs:
            if ie.file_id in inv:
                old_rev = inv[ie.file_id].revision
                if old_rev in head_set:
                    heads.append(inv[ie.file_id].revision)
                    head_set.remove(inv[ie.file_id].revision)

        store = False
        # now we check to see if we need to write a new record to the
        # file-graph.
        # We write a new entry unless there is one head to the ancestors, and
        # the kind-derived content is unchanged.

        # Cheapest check first: no ancestors, or more the one head in the
        # ancestors, we write a new node.
        if len(heads) != 1:
            store = True
        if not store:
            # There is a single head, look it up for comparison
            parent_entry = parent_candiate_entries[heads[0]]
            # if the non-content specific data has changed, we'll be writing a
            # node:
            if (parent_entry.parent_id != ie.parent_id or
                parent_entry.name != ie.name):
                store = True
        # now we need to do content specific checks:
        if not store:
            # if the kind changed the content obviously has
            if kind != parent_entry.kind:
                store = True
        # Stat cache fingerprint feedback for the caller - None as we usually
        # don't generate one.
        fingerprint = None
        if kind == 'file':
            if content_summary[2] is None:
                raise ValueError("Files must not have executable = None")
            if not store:
                # We can't trust a check of the file length because of content
                # filtering...
                if (# if the exec bit has changed we have to store:
                    parent_entry.executable != content_summary[2]):
                    store = True
                elif parent_entry.text_sha1 == content_summary[3]:
                    # all meta and content is unchanged (using a hash cache
                    # hit to check the sha)
                    ie.revision = parent_entry.revision
                    ie.text_size = parent_entry.text_size
                    ie.text_sha1 = parent_entry.text_sha1
                    ie.executable = parent_entry.executable
                    return self._get_delta(ie, basis_inv, path), False, None
                else:
                    # Either there is only a hash change(no hash cache entry,
                    # or same size content change), or there is no change on
                    # this file at all.
                    # Provide the parent's hash to the store layer, so that the
                    # content is unchanged we will not store a new node.
                    nostore_sha = parent_entry.text_sha1
            if store:
                # We want to record a new node regardless of the presence or
                # absence of a content change in the file.
                nostore_sha = None
            ie.executable = content_summary[2]
            file_obj, stat_value = tree.get_file_with_stat(ie.file_id, path)
            try:
                text = file_obj.read()
            finally:
                file_obj.close()
            try:
                ie.text_sha1, ie.text_size = self._add_text_to_weave(
                    ie.file_id, text, heads, nostore_sha)
                # Let the caller know we generated a stat fingerprint.
                fingerprint = (ie.text_sha1, stat_value)
            except errors.ExistingContent:
                # Turns out that the file content was unchanged, and we were
                # only going to store a new node if it was changed. Carry over
                # the entry.
                ie.revision = parent_entry.revision
                ie.text_size = parent_entry.text_size
                ie.text_sha1 = parent_entry.text_sha1
                ie.executable = parent_entry.executable
                return self._get_delta(ie, basis_inv, path), False, None
        elif kind == 'directory':
            if not store:
                # all data is meta here, nothing specific to directory, so
                # carry over:
                ie.revision = parent_entry.revision
                return self._get_delta(ie, basis_inv, path), False, None
            self._add_text_to_weave(ie.file_id, '', heads, None)
        elif kind == 'symlink':
            current_link_target = content_summary[3]
            if not store:
                # symlink target is not generic metadata, check if it has
                # changed.
                if current_link_target != parent_entry.symlink_target:
                    store = True
            if not store:
                # unchanged, carry over.
                ie.revision = parent_entry.revision
                ie.symlink_target = parent_entry.symlink_target
                return self._get_delta(ie, basis_inv, path), False, None
            ie.symlink_target = current_link_target
            self._add_text_to_weave(ie.file_id, '', heads, None)
        elif kind == 'tree-reference':
            if not store:
                if content_summary[3] != parent_entry.reference_revision:
                    store = True
            if not store:
                # unchanged, carry over.
                ie.reference_revision = parent_entry.reference_revision
                ie.revision = parent_entry.revision
                return self._get_delta(ie, basis_inv, path), False, None
            ie.reference_revision = content_summary[3]
            if ie.reference_revision is None:
                raise AssertionError("invalid content_summary for nested tree: %r"
                    % (content_summary,))
            self._add_text_to_weave(ie.file_id, '', heads, None)
        else:
            raise NotImplementedError('unknown kind')
        ie.revision = self._new_revision_id
        self._any_changes = True
        return self._get_delta(ie, basis_inv, path), True, fingerprint

    def record_iter_changes(self, tree, basis_revision_id, iter_changes,
        _entry_factory=entry_factory):
        """Record a new tree via iter_changes.

        :param tree: The tree to obtain text contents from for changed objects.
        :param basis_revision_id: The revision id of the tree the iter_changes
            has been generated against. Currently assumed to be the same
            as self.parents[0] - if it is not, errors may occur.
        :param iter_changes: An iter_changes iterator with the changes to apply
            to basis_revision_id. The iterator must not include any items with
            a current kind of None - missing items must be either filtered out
            or errored-on beefore record_iter_changes sees the item.
        :param _entry_factory: Private method to bind entry_factory locally for
            performance.
        :return: A generator of (file_id, relpath, fs_hash) tuples for use with
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
                    revtrees.append(self.repository.revision_tree(
                        _mod_revision.NULL_REVISION))
        # The basis inventory from a repository 
        if revtrees:
            basis_inv = revtrees[0].inventory
        else:
            basis_inv = self.repository.revision_tree(
                _mod_revision.NULL_REVISION).inventory
        if len(self.parents) > 0:
            if basis_revision_id != self.parents[0] and not ghost_basis:
                raise Exception(
                    "arbitrary basis parents not yet supported with merges")
            for revtree in revtrees[1:]:
                for change in revtree.inventory._make_delta(basis_inv):
                    if change[1] is None:
                        # Not present in this parent.
                        continue
                    if change[2] not in merged_ids:
                        if change[0] is not None:
                            basis_entry = basis_inv[change[2]]
                            merged_ids[change[2]] = [
                                # basis revid
                                basis_entry.revision,
                                # new tree revid
                                change[3].revision]
                            parent_entries[change[2]] = {
                                # basis parent
                                basis_entry.revision:basis_entry,
                                # this parent 
                                change[3].revision:change[3],
                                }
                        else:
                            merged_ids[change[2]] = [change[3].revision]
                            parent_entries[change[2]] = {change[3].revision:change[3]}
                    else:
                        merged_ids[change[2]].append(change[3].revision)
                        parent_entries[change[2]][change[3].revision] = change[3]
        else:
            merged_ids = {}
        # Setup the changes from the tree:
        # changes maps file_id -> (change, [parent revision_ids])
        changes= {}
        for change in iter_changes:
            # This probably looks up in basis_inv way to much.
            if change[1][0] is not None:
                head_candidate = [basis_inv[change[0]].revision]
            else:
                head_candidate = []
            changes[change[0]] = change, merged_ids.get(change[0],
                head_candidate)
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
                basis_entry = basis_inv[file_id]
            except errors.NoSuchId:
                # a change from basis->some_parents but file_id isn't in basis
                # so was new in the merge, which means it must have changed
                # from basis -> current, and as it hasn't the add was reverted
                # by the user. So we discard this change.
                pass
            else:
                change = (file_id,
                    (basis_inv.id2path(file_id), tree.id2path(file_id)),
                    False, (True, True),
                    (basis_entry.parent_id, basis_entry.parent_id),
                    (basis_entry.name, basis_entry.name),
                    (basis_entry.kind, basis_entry.kind),
                    (basis_entry.executable, basis_entry.executable))
                changes[file_id] = (change, merged_ids[file_id])
        # changes contains tuples with the change and a set of inventory
        # candidates for the file.
        # inv delta is:
        # old_path, new_path, file_id, new_inventory_entry
        seen_root = False # Is the root in the basis delta?
        inv_delta = self._basis_delta
        modified_rev = self._new_revision_id
        for change, head_candidates in changes.values():
            if change[3][1]: # versioned in target.
                # Several things may be happening here:
                # We may have a fork in the per-file graph
                #  - record a change with the content from tree
                # We may have a change against < all trees  
                #  - carry over the tree that hasn't changed
                # We may have a change against all trees
                #  - record the change with the content from tree
                kind = change[6][1]
                file_id = change[0]
                entry = _entry_factory[kind](file_id, change[5][1],
                    change[4][1])
                head_set = self._heads(change[0], set(head_candidates))
                heads = []
                # Preserve ordering.
                for head_candidate in head_candidates:
                    if head_candidate in head_set:
                        heads.append(head_candidate)
                        head_set.remove(head_candidate)
                carried_over = False
                if len(heads) == 1:
                    # Could be a carry-over situation:
                    parent_entry_revs = parent_entries.get(file_id, None)
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
                        if (parent_entry.kind != entry.kind or
                            parent_entry.parent_id != entry.parent_id or
                            parent_entry.name != entry.name):
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
                if kind == 'file':
                    # XXX: There is still a small race here: If someone reverts the content of a file
                    # after iter_changes examines and decides it has changed,
                    # we will unconditionally record a new version even if some
                    # other process reverts it while commit is running (with
                    # the revert happening after iter_changes did it's
                    # examination).
                    if change[7][1]:
                        entry.executable = True
                    else:
                        entry.executable = False
                    if (carry_over_possible and
                        parent_entry.executable == entry.executable):
                            # Check the file length, content hash after reading
                            # the file.
                            nostore_sha = parent_entry.text_sha1
                    else:
                        nostore_sha = None
                    file_obj, stat_value = tree.get_file_with_stat(file_id, change[1][1])
                    try:
                        text = file_obj.read()
                    finally:
                        file_obj.close()
                    try:
                        entry.text_sha1, entry.text_size = self._add_text_to_weave(
                            file_id, text, heads, nostore_sha)
                        yield file_id, change[1][1], (entry.text_sha1, stat_value)
                    except errors.ExistingContent:
                        # No content change against a carry_over parent
                        # Perhaps this should also yield a fs hash update?
                        carried_over = True
                        entry.text_size = parent_entry.text_size
                        entry.text_sha1 = parent_entry.text_sha1
                elif kind == 'symlink':
                    # Wants a path hint?
                    entry.symlink_target = tree.get_symlink_target(file_id)
                    if (carry_over_possible and
                        parent_entry.symlink_target == entry.symlink_target):
                        carried_over = True
                    else:
                        self._add_text_to_weave(change[0], '', heads, None)
                elif kind == 'directory':
                    if carry_over_possible:
                        carried_over = True
                    else:
                        # Nothing to set on the entry.
                        # XXX: split into the Root and nonRoot versions.
                        if change[1][1] != '' or self.repository.supports_rich_root():
                            self._add_text_to_weave(change[0], '', heads, None)
                elif kind == 'tree-reference':
                    if not self.repository._format.supports_tree_reference:
                        # This isn't quite sane as an error, but we shouldn't
                        # ever see this code path in practice: tree's don't
                        # permit references when the repo doesn't support tree
                        # references.
                        raise errors.UnsupportedOperation(tree.add_reference,
                            self.repository)
                    reference_revision = tree.get_reference_revision(change[0])
                    entry.reference_revision = reference_revision
                    if (carry_over_possible and
                        parent_entry.reference_revision == reference_revision):
                        carried_over = True
                    else:
                        self._add_text_to_weave(change[0], '', heads, None)
                else:
                    raise AssertionError('unknown kind %r' % kind)
                if not carried_over:
                    entry.revision = modified_rev
                else:
                    entry.revision = parent_entry.revision
            else:
                entry = None
            new_path = change[1][1]
            inv_delta.append((change[1][0], new_path, change[0], entry))
            if new_path == '':
                seen_root = True
        self.new_inventory = None
        if len(inv_delta):
            # This should perhaps be guarded by a check that the basis we
            # commit against is the basis for the commit and if not do a delta
            # against the basis.
            self._any_changes = True
        if not seen_root:
            # housekeeping root entry changes do not affect no-change commits.
            self._require_root_change(tree)
        self.basis_delta_revision = basis_revision_id

    def _add_text_to_weave(self, file_id, new_text, parents, nostore_sha):
        parent_keys = tuple([(file_id, parent) for parent in parents])
        return self.repository.texts._add_text(
            (file_id, self._new_revision_id), parent_keys, new_text,
            nostore_sha=nostore_sha, random_id=self.random_revid)[0:2]


class RootCommitBuilder(CommitBuilder):
    """This commitbuilder actually records the root id"""

    # the root entry gets versioned properly by this builder.
    _versioned_root = True

    def _check_root(self, ie, parent_invs, tree):
        """Helper for record_entry_contents.

        :param ie: An entry being added.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param tree: The tree that is being committed.
        """

    def _require_root_change(self, tree):
        """Enforce an appropriate root object change.

        This is called once when record_iter_changes is called, if and only if
        the root was not in the delta calculated by record_iter_changes.

        :param tree: The tree which is being committed.
        """
        # versioned roots do not change unless the tree found a change.


######################################################################
# Repositories


class Repository(object):
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
    bzrlib.

    :ivar revisions: A bzrlib.versionedfile.VersionedFiles instance containing
        the serialised revisions for the repository. This can be used to obtain
        revision graph information or to access raw serialised revisions.
        The result of trying to insert data into the repository via this store
        is undefined: it should be considered read-only except for implementors
        of repositories.
    :ivar signatures: A bzrlib.versionedfile.VersionedFiles instance containing
        the serialised signatures for the repository. This can be used to
        obtain access to raw serialised signatures.  The result of trying to
        insert data into the repository via this store is undefined: it should
        be considered read-only except for implementors of repositories.
    :ivar inventories: A bzrlib.versionedfile.VersionedFiles instance containing
        the serialised inventories for the repository. This can be used to
        obtain unserialised inventories.  The result of trying to insert data
        into the repository via this store is undefined: it should be
        considered read-only except for implementors of repositories.
    :ivar texts: A bzrlib.versionedfile.VersionedFiles instance containing the
        texts of files and directories for the repository. This can be used to
        obtain file texts or file graphs. Note that Repository.iter_file_bytes
        is usually a better interface for accessing file texts.
        The result of trying to insert data into the repository via this store
        is undefined: it should be considered read-only except for implementors
        of repositories.
    :ivar chk_bytes: A bzrlib.versionedfile.VersionedFiles instance containing
        any data the repository chooses to store or have indexed by its hash.
        The result of trying to insert data into the repository via this store
        is undefined: it should be considered read-only except for implementors
        of repositories.
    :ivar _transport: Transport for file access to repository, typically
        pointing to .bzr/repository.
    """

    # What class to use for a CommitBuilder. Often its simpler to change this
    # in a Repository class subclass rather than to override
    # get_commit_builder.
    _commit_builder_class = CommitBuilder
    # The search regex used by xml based repositories to determine what things
    # where changed in a single commit.
    _file_ids_altered_regex = lazy_regex.lazy_compile(
        r'file_id="(?P<file_id>[^"]+)"'
        r'.* revision="(?P<revision_id>[^"]+)"'
        )

    def abort_write_group(self, suppress_errors=False):
        """Commit the contents accrued within the current write group.

        :param suppress_errors: if true, abort_write_group will catch and log
            unexpected errors that happen during the abort, rather than
            allowing them to propagate.  Defaults to False.

        :seealso: start_write_group.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            if suppress_errors:
                mutter(
                '(suppressed) mismatched lock context and write group. %r, %r',
                self._write_group, self.get_transaction())
                return
            raise errors.BzrError(
                'mismatched lock context and write group. %r, %r' %
                (self._write_group, self.get_transaction()))
        try:
            self._abort_write_group()
        except Exception, exc:
            self._write_group = None
            if not suppress_errors:
                raise
            mutter('abort_write_group failed')
            log_exception_quietly()
            note('bzr: ERROR (ignored): %s', exc)
        self._write_group = None

    def _abort_write_group(self):
        """Template method for per-repository write group cleanup.

        This is called during abort before the write group is considered to be
        finished and should cleanup any internal state accrued during the write
        group. There is no requirement that data handed to the repository be
        *not* made available - this is not a rollback - but neither should any
        attempt be made to ensure that data added is fully commited. Abort is
        invoked when an error has occured so futher disk or network operations
        may not be possible or may error and if possible should not be
        attempted.
        """

    def add_fallback_repository(self, repository):
        """Add a repository to use for looking up data not held locally.

        :param repository: A repository.
        """
        if not self._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(self._format, self.base)
        if self.is_locked():
            # This repository will call fallback.unlock() when we transition to
            # the unlocked state, so we make sure to increment the lock count
            repository.lock_read()
        self._check_fallback_repository(repository)
        self._fallback_repositories.append(repository)
        self.texts.add_fallback_versioned_files(repository.texts)
        self.inventories.add_fallback_versioned_files(repository.inventories)
        self.revisions.add_fallback_versioned_files(repository.revisions)
        self.signatures.add_fallback_versioned_files(repository.signatures)
        if self.chk_bytes is not None:
            self.chk_bytes.add_fallback_versioned_files(repository.chk_bytes)

    def _check_fallback_repository(self, repository):
        """Check that this repository can fallback to repository safely.

        Raise an error if not.

        :param repository: A repository to fallback to.
        """
        return InterRepository._assert_same_model(self, repository)

    def add_inventory(self, revision_id, inv, parents):
        """Add the inventory inv to the repository as revision_id.

        :param parents: The revision ids of the parents that revision_id
                        is known to have and are in the repository already.

        :returns: The validator(which is a sha1 digest, though what is sha'd is
            repository format specific) of the serialized inventory.
        """
        if not self.is_in_write_group():
            raise AssertionError("%r not in write group" % (self,))
        _mod_revision.check_not_reserved_id(revision_id)
        if not (inv.revision_id is None or inv.revision_id == revision_id):
            raise AssertionError(
                "Mismatch between inventory revision"
                " id and insertion revid (%r, %r)"
                % (inv.revision_id, revision_id))
        if inv.root is None:
            raise AssertionError()
        return self._add_inventory_checked(revision_id, inv, parents)

    def _add_inventory_checked(self, revision_id, inv, parents):
        """Add inv to the repository after checking the inputs.

        This function can be overridden to allow different inventory styles.

        :seealso: add_inventory, for the contract.
        """
        inv_lines = self._serialise_inventory_to_lines(inv)
        return self._inventory_add_lines(revision_id, parents,
            inv_lines, check_content=False)

    def add_inventory_by_delta(self, basis_revision_id, delta, new_revision_id,
                               parents, basis_inv=None, propagate_caches=False):
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
            raise AssertionError("%r not in write group" % (self,))
        _mod_revision.check_not_reserved_id(new_revision_id)
        basis_tree = self.revision_tree(basis_revision_id)
        basis_tree.lock_read()
        try:
            # Note that this mutates the inventory of basis_tree, which not all
            # inventory implementations may support: A better idiom would be to
            # return a new inventory, but as there is no revision tree cache in
            # repository this is safe for now - RBC 20081013
            if basis_inv is None:
                basis_inv = basis_tree.inventory
            basis_inv.apply_delta(delta)
            basis_inv.revision_id = new_revision_id
            return (self.add_inventory(new_revision_id, basis_inv, parents),
                    basis_inv)
        finally:
            basis_tree.unlock()

    def _inventory_add_lines(self, revision_id, parents, lines,
        check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory."""
        parents = [(parent,) for parent in parents]
        result = self.inventories.add_lines((revision_id,), parents, lines,
            check_content=check_content)[0]
        self.inventories._access.flush()
        return result

    def add_revision(self, revision_id, rev, inv=None, config=None):
        """Add rev to the revision store as revision_id.

        :param revision_id: the revision id to use.
        :param rev: The revision object.
        :param inv: The inventory for the revision. if None, it will be looked
                    up in the inventory storer
        :param config: If None no digital signature will be created.
                       If supplied its signature_needed method will be used
                       to determine if a signature should be made.
        """
        # TODO: jam 20070210 Shouldn't we check rev.revision_id and
        #       rev.parent_ids?
        _mod_revision.check_not_reserved_id(revision_id)
        if config is not None and config.signature_needed():
            if inv is None:
                inv = self.get_inventory(revision_id)
            plaintext = Testament(rev, inv).as_short_text()
            self.store_revision_signature(
                gpg.GPGStrategy(config), plaintext, revision_id)
        # check inventory present
        if not self.inventories.get_parent_map([(revision_id,)]):
            if inv is None:
                raise errors.WeaveRevisionNotPresent(revision_id,
                                                     self.inventories)
            else:
                # yes, this is not suitable for adding with ghosts.
                rev.inventory_sha1 = self.add_inventory(revision_id, inv,
                                                        rev.parent_ids)
        else:
            key = (revision_id,)
            rev.inventory_sha1 = self.inventories.get_sha1s([key])[key]
        self._add_revision(rev)

    def _add_revision(self, revision):
        text = self._serializer.write_revision_to_string(revision)
        key = (revision.revision_id,)
        parents = tuple((parent,) for parent in revision.parent_ids)
        self.revisions.add_lines(key, parents, osutils.split_lines(text))

    def all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        This is conceptually deprecated because code should generally work on
        the graph reachable from a particular revision, and ignore any other
        revisions that might be present.  There is no direct replacement
        method.
        """
        if 'evil' in debug.debug_flags:
            mutter_callsite(2, "all_revision_ids is linear with history.")
        return self._all_revision_ids()

    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        These are in as much topological order as the underlying store can
        present.
        """
        raise NotImplementedError(self._all_revision_ids)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.
        """
        self.control_files.break_lock()

    @needs_read_lock
    def _eliminate_revisions_not_present(self, revision_ids):
        """Check every revision id in revision_ids to see if we have it.

        Returns a set of the present revisions.
        """
        result = []
        graph = self.get_graph()
        parent_map = graph.get_parent_map(revision_ids)
        # The old API returned a list, should this actually be a set?
        return parent_map.keys()

    def _check_inventories(self, checker):
        """Check the inventories found from the revision scan.
        
        This is responsible for verifying the sha1 of inventories and
        creating a pending_keys set that covers data referenced by inventories.
        """
        bar = ui.ui_factory.nested_progress_bar()
        try:
            self._do_check_inventories(checker, bar)
        finally:
            bar.finished()

    def _do_check_inventories(self, checker, bar):
        """Helper for _check_inventories."""
        revno = 0
        keys = {'chk_bytes':set(), 'inventories':set(), 'texts':set()}
        kinds = ['chk_bytes', 'texts']
        count = len(checker.pending_keys)
        bar.update("inventories", 0, 2)
        current_keys = checker.pending_keys
        checker.pending_keys = {}
        # Accumulate current checks.
        for key in current_keys:
            if key[0] != 'inventories' and key[0] not in kinds:
                checker._report_items.append('unknown key type %r' % (key,))
            keys[key[0]].add(key[1:])
        if keys['inventories']:
            # NB: output order *should* be roughly sorted - topo or
            # inverse topo depending on repository - either way decent
            # to just delta against. However, pre-CHK formats didn't
            # try to optimise inventory layout on disk. As such the
            # pre-CHK code path does not use inventory deltas.
            last_object = None
            for record in self.inventories.check(keys=keys['inventories']):
                if record.storage_kind == 'absent':
                    checker._report_items.append(
                        'Missing inventory {%s}' % (record.key,))
                else:
                    last_object = self._check_record('inventories', record,
                        checker, last_object,
                        current_keys[('inventories',) + record.key])
            del keys['inventories']
        else:
            return
        bar.update("texts", 1)
        while (checker.pending_keys or keys['chk_bytes']
            or keys['texts']):
            # Something to check.
            current_keys = checker.pending_keys
            checker.pending_keys = {}
            # Accumulate current checks.
            for key in current_keys:
                if key[0] not in kinds:
                    checker._report_items.append('unknown key type %r' % (key,))
                keys[key[0]].add(key[1:])
            # Check the outermost kind only - inventories || chk_bytes || texts
            for kind in kinds:
                if keys[kind]:
                    last_object = None
                    for record in getattr(self, kind).check(keys=keys[kind]):
                        if record.storage_kind == 'absent':
                            checker._report_items.append(
                                'Missing %s {%s}' % (kind, record.key,))
                        else:
                            last_object = self._check_record(kind, record,
                                checker, last_object, current_keys[(kind,) + record.key])
                    keys[kind] = set()
                    break

    def _check_record(self, kind, record, checker, last_object, item_data):
        """Check a single text from this repository."""
        if kind == 'inventories':
            rev_id = record.key[0]
            inv = self.deserialise_inventory(rev_id,
                record.get_bytes_as('fulltext'))
            if last_object is not None:
                delta = inv._make_delta(last_object)
                for old_path, path, file_id, ie in delta:
                    if ie is None:
                        continue
                    ie.check(checker, rev_id, inv)
            else:
                for path, ie in inv.iter_entries():
                    ie.check(checker, rev_id, inv)
            if self._format.fast_deltas:
                return inv
        elif kind == 'chk_bytes':
            # No code written to check chk_bytes for this repo format.
            checker._report_items.append(
                'unsupported key type chk_bytes for %s' % (record.key,))
        elif kind == 'texts':
            self._check_text(record, checker, item_data)
        else:
            checker._report_items.append(
                'unknown key type %s for %s' % (kind, record.key))

    def _check_text(self, record, checker, item_data):
        """Check a single text."""
        # Check it is extractable.
        # TODO: check length.
        if record.storage_kind == 'chunked':
            chunks = record.get_bytes_as(record.storage_kind)
            sha1 = osutils.sha_strings(chunks)
            length = sum(map(len, chunks))
        else:
            content = record.get_bytes_as('fulltext')
            sha1 = osutils.sha_string(content)
            length = len(content)
        if item_data and sha1 != item_data[1]:
            checker._report_items.append(
                'sha1 mismatch: %s has sha1 %s expected %s referenced by %s' %
                (record.key, sha1, item_data[1], item_data[2]))

    @staticmethod
    def create(a_bzrdir):
        """Construct the current default format repository in a_bzrdir."""
        return RepositoryFormat.get_default_format().initialize(a_bzrdir)

    def __init__(self, _format, a_bzrdir, control_files):
        """instantiate a Repository.

        :param _format: The format of the repository on disk.
        :param a_bzrdir: The BzrDir of the repository.

        In the future we will have a single api for all stores for
        getting file texts, inventories and revisions, then
        this construct will accept instances of those things.
        """
        super(Repository, self).__init__()
        self._format = _format
        # the following are part of the public API for Repository:
        self.bzrdir = a_bzrdir
        self.control_files = control_files
        self._transport = control_files._transport
        self.base = self._transport.base
        # for tests
        self._reconcile_does_inventory_gc = True
        self._reconcile_fixes_text_parents = False
        self._reconcile_backsup_inventory = True
        # not right yet - should be more semantically clear ?
        #
        # TODO: make sure to construct the right store classes, etc, depending
        # on whether escaping is required.
        self._warn_if_deprecated()
        self._write_group = None
        # Additional places to query for data.
        self._fallback_repositories = []
        # An InventoryEntry cache, used during deserialization
        self._inventory_entry_cache = fifo_cache.FIFOCache(10*1024)

    def __repr__(self):
        if self._fallback_repositories:
            return '%s(%r, fallback_repositories=%r)' % (
                self.__class__.__name__,
                self.base,
                self._fallback_repositories)
        else:
            return '%s(%r)' % (self.__class__.__name__,
                               self.base)

    def _has_same_fallbacks(self, other_repo):
        """Returns true if the repositories have the same fallbacks."""
        my_fb = self._fallback_repositories
        other_fb = other_repo._fallback_repositories
        if len(my_fb) != len(other_fb):
            return False
        for f, g in zip(my_fb, other_fb):
            if not f.has_same_location(g):
                return False
        return True

    def has_same_location(self, other):
        """Returns a boolean indicating if this repository is at the same
        location as another repository.

        This might return False even when two repository objects are accessing
        the same physical repository via different URLs.
        """
        if self.__class__ is not other.__class__:
            return False
        return (self._transport.base == other._transport.base)

    def is_in_write_group(self):
        """Return True if there is an open write group.

        :seealso: start_write_group.
        """
        return self._write_group is not None

    def is_locked(self):
        return self.control_files.is_locked()

    def is_write_locked(self):
        """Return True if this object is write locked."""
        return self.is_locked() and self.control_files._lock_mode == 'w'

    def lock_write(self, token=None):
        """Lock this repository for writing.

        This causes caching within the repository obejct to start accumlating
        data during reads, and allows a 'write_group' to be obtained. Write
        groups must be used for actual data insertion.

        :param token: if this is already locked, then lock_write will fail
            unless the token matches the existing lock.
        :returns: a token if this instance supports tokens, otherwise None.
        :raises TokenLockingNotSupported: when a token is given but this
            instance doesn't support using token locks.
        :raises MismatchedToken: if the specified token doesn't match the token
            of the existing lock.
        :seealso: start_write_group.

        A token should be passed in if you know that you have locked the object
        some other way, and need to synchronise this object's state with that
        fact.

        XXX: this docstring is duplicated in many places, e.g. lockable_files.py
        """
        locked = self.is_locked()
        result = self.control_files.lock_write(token=token)
        if not locked:
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
            self._refresh_data()
        return result

    def lock_read(self):
        locked = self.is_locked()
        self.control_files.lock_read()
        if not locked:
            for repo in self._fallback_repositories:
                repo.lock_read()
            self._refresh_data()

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    def leave_lock_in_place(self):
        """Tell this repository not to release the physical lock when this
        object is unlocked.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.leave_in_place()

    def dont_leave_lock_in_place(self):
        """Tell this repository to release the physical lock when this
        object is unlocked, even if it didn't originally acquire it.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.dont_leave_in_place()

    @needs_read_lock
    def gather_stats(self, revid=None, committers=None):
        """Gather statistics from a revision id.

        :param revid: The revision id to gather statistics from, if None, then
            no revision specific statistics are gathered.
        :param committers: Optional parameter controlling whether to grab
            a count of committers from the revision specific statistics.
        :return: A dictionary of statistics. Currently this contains:
            committers: The number of committers if requested.
            firstrev: A tuple with timestamp, timezone for the penultimate left
                most ancestor of revid, if revid is not the NULL_REVISION.
            latestrev: A tuple with timestamp, timezone for revid, if revid is
                not the NULL_REVISION.
            revisions: The total revision count in the repository.
            size: An estimate disk size of the repository in bytes.
        """
        result = {}
        if revid and committers:
            result['committers'] = 0
        if revid and revid != _mod_revision.NULL_REVISION:
            if committers:
                all_committers = set()
            revisions = self.get_ancestry(revid)
            # pop the leading None
            revisions.pop(0)
            first_revision = None
            if not committers:
                # ignore the revisions in the middle - just grab first and last
                revisions = revisions[0], revisions[-1]
            for revision in self.get_revisions(revisions):
                if not first_revision:
                    first_revision = revision
                if committers:
                    all_committers.add(revision.committer)
            last_revision = revision
            if committers:
                result['committers'] = len(all_committers)
            result['firstrev'] = (first_revision.timestamp,
                first_revision.timezone)
            result['latestrev'] = (last_revision.timestamp,
                last_revision.timezone)

        # now gather global repository information
        # XXX: This is available for many repos regardless of listability.
        if self.bzrdir.root_transport.listable():
            # XXX: do we want to __define len__() ?
            # Maybe the versionedfiles object should provide a different
            # method to get the number of keys.
            result['revisions'] = len(self.revisions.keys())
            # result['size'] = t
        return result

    def find_branches(self, using=False):
        """Find branches underneath this repository.

        This will include branches inside other branches.

        :param using: If True, list only branches using this repository.
        """
        if using and not self.is_shared():
            try:
                return [self.bzrdir.open_branch()]
            except errors.NotBranchError:
                return []
        class Evaluator(object):

            def __init__(self):
                self.first_call = True

            def __call__(self, bzrdir):
                # On the first call, the parameter is always the bzrdir
                # containing the current repo.
                if not self.first_call:
                    try:
                        repository = bzrdir.open_repository()
                    except errors.NoRepositoryPresent:
                        pass
                    else:
                        return False, (None, repository)
                self.first_call = False
                try:
                    value = (bzrdir.open_branch(), None)
                except errors.NotBranchError:
                    value = (None, None)
                return True, value

        branches = []
        for branch, repository in bzrdir.BzrDir.find_bzrdirs(
                self.bzrdir.root_transport, evaluate=Evaluator()):
            if branch is not None:
                branches.append(branch)
            if not using and repository is not None:
                branches.extend(repository.find_branches())
        return branches

    @needs_read_lock
    def search_missing_revision_ids(self, other, revision_id=None, find_ghosts=True):
        """Return the revision ids that other has that this does not.

        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        return InterRepository.get(other, self).search_missing_revision_ids(
            revision_id, find_ghosts)

    @staticmethod
    def open(base):
        """Open the repository rooted at base.

        For instance, if the repository is at URL/.bzr/repository,
        Repository.open(URL) -> a Repository instance.
        """
        control = bzrdir.BzrDir.open(base)
        return control.open_repository()

    def copy_content_into(self, destination, revision_id=None):
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.
        """
        return InterRepository.get(self, destination).copy_content(revision_id)

    def commit_write_group(self):
        """Commit the contents accrued within the current write group.

        :seealso: start_write_group.
        
        :return: it may return an opaque hint that can be passed to 'pack'.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            raise errors.BzrError('mismatched lock context %r and '
                'write group %r.' %
                (self.get_transaction(), self._write_group))
        result = self._commit_write_group()
        self._write_group = None
        return result

    def _commit_write_group(self):
        """Template method for per-repository write group cleanup.

        This is called before the write group is considered to be
        finished and should ensure that all data handed to the repository
        for writing during the write group is safely committed (to the
        extent possible considering file system caching etc).
        """

    def suspend_write_group(self):
        raise errors.UnsuspendableWriteGroup(self)

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
            raise AssertionError('not in a write group')

        # XXX: We assume that every added revision already has its
        # corresponding inventory, so we only check for parent inventories that
        # might be missing, rather than all inventories.
        parents = set(self.revisions._index.get_missing_parents())
        parents.discard(_mod_revision.NULL_REVISION)
        unstacked_inventories = self.inventories._index
        present_inventories = unstacked_inventories.get_parent_map(
            key[-1:] for key in parents)
        parents.difference_update(present_inventories)
        if len(parents) == 0:
            # No missing parent inventories.
            return set()
        if not check_for_missing_texts:
            return set(('inventories', rev_id) for (rev_id,) in parents)
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
        for file_id, version_ids in file_ids.iteritems():
            missing_texts.update(
                (file_id, version_id) for version_id in version_ids)
        present_texts = self.texts.get_parent_map(missing_texts)
        missing_texts.difference_update(present_texts)
        if not missing_texts:
            # No texts are missing, so all revisions and their deltas are
            # reconstructable.
            return set()
        # Alternatively the text versions could be returned as the missing
        # keys, but this is likely to be less data.
        missing_keys = set(('inventories', rev_id) for (rev_id,) in parents)
        return missing_keys

    def refresh_data(self):
        """Re-read any data needed to to synchronise with disk.

        This method is intended to be called after another repository instance
        (such as one used by a smart server) has inserted data into the
        repository. It may not be called during a write group, but may be
        called at any other time.
        """
        if self.is_in_write_group():
            raise errors.InternalBzrError(
                "May not refresh_data while in a write group.")
        self._refresh_data()

    def resume_write_group(self, tokens):
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group:
            raise errors.BzrError('already in a write group')
        self._resume_write_group(tokens)
        # so we can detect unlock/relock - the write group is now entered.
        self._write_group = self.get_transaction()

    def _resume_write_group(self, tokens):
        raise errors.UnsuspendableWriteGroup(self)

    def fetch(self, source, revision_id=None, pb=None, find_ghosts=False,
            fetch_spec=None):
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
            raise AssertionError(
                "fetch_spec and revision_id are mutually exclusive.")
        if self.is_in_write_group():
            raise errors.InternalBzrError(
                "May not fetch while in a write group.")
        # fast path same-url fetch operations
        # TODO: lift out to somewhere common with RemoteRepository
        # <https://bugs.edge.launchpad.net/bzr/+bug/401646>
        if (self.has_same_location(source)
            and fetch_spec is None
            and self._has_same_fallbacks(source)):
            # check that last_revision is in 'from' and then return a
            # no-operation.
            if (revision_id is not None and
                not _mod_revision.is_null(revision_id)):
                self.get_revision(revision_id)
            return 0, []
        # if there is no specific appropriate InterRepository, this will get
        # the InterRepository base class, which raises an
        # IncompatibleRepositories when asked to fetch.
        inter = InterRepository.get(source, self)
        return inter.fetch(revision_id=revision_id, pb=pb,
            find_ghosts=find_ghosts, fetch_spec=fetch_spec)

    def create_bundle(self, target, base, fileobj, format=None):
        return serializer.write_bundle(self, target, base, fileobj, format)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        """Obtain a CommitBuilder for this repository.

        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        """
        if self._fallback_repositories:
            raise errors.BzrError("Cannot commit from a lightweight checkout "
                "to a stacked branch. See "
                "https://bugs.launchpad.net/bzr/+bug/375013 for details.")
        result = self._commit_builder_class(self, parents, config,
            timestamp, timezone, committer, revprops, revision_id)
        self.start_write_group()
        return result

    def unlock(self):
        if (self.control_files._lock_count == 1 and
            self.control_files._lock_mode == 'w'):
            if self._write_group is not None:
                self.abort_write_group()
                self.control_files.unlock()
                raise errors.BzrError(
                    'Must end write groups before releasing write locks.')
        self.control_files.unlock()
        if self.control_files._lock_count == 0:
            self._inventory_entry_cache.clear()
            for repo in self._fallback_repositories:
                repo.unlock()

    @needs_read_lock
    def clone(self, a_bzrdir, revision_id=None):
        """Clone this repository into a_bzrdir using the current format.

        Currently no check is made that the format of this repository and
        the bzrdir format are compatible. FIXME RBC 20060201.

        :return: The newly created destination repository.
        """
        # TODO: deprecate after 0.16; cloning this with all its settings is
        # probably not very useful -- mbp 20070423
        dest_repo = self._create_sprouting_repo(a_bzrdir, shared=self.is_shared())
        self.copy_content_into(dest_repo, revision_id)
        return dest_repo

    def start_write_group(self):
        """Start a write group in the repository.

        Write groups are used by repositories which do not have a 1:1 mapping
        between file ids and backend store to manage the insertion of data from
        both fetch and commit operations.

        A write lock is required around the start_write_group/commit_write_group
        for the support of lock-requiring repository formats.

        One can only insert data into a repository inside a write group.

        :return: None.
        """
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group:
            raise errors.BzrError('already in a write group')
        self._start_write_group()
        # so we can detect unlock/relock - the write group is now entered.
        self._write_group = self.get_transaction()

    def _start_write_group(self):
        """Template method for per-repository write group startup.

        This is called before the write group is considered to be
        entered.
        """

    @needs_read_lock
    def sprout(self, to_bzrdir, revision_id=None):
        """Create a descendent repository for new development.

        Unlike clone, this does not copy the settings of the repository.
        """
        dest_repo = self._create_sprouting_repo(to_bzrdir, shared=False)
        dest_repo.fetch(self, revision_id=revision_id)
        return dest_repo

    def _create_sprouting_repo(self, a_bzrdir, shared):
        if not isinstance(a_bzrdir._format, self.bzrdir._format.__class__):
            # use target default format.
            dest_repo = a_bzrdir.create_repository()
        else:
            # Most control formats need the repository to be specifically
            # created, but on some old all-in-one formats it's not needed
            try:
                dest_repo = self._format.initialize(a_bzrdir, shared=shared)
            except errors.UninitializableFormat:
                dest_repo = a_bzrdir.open_repository()
        return dest_repo

    def _get_sink(self):
        """Return a sink for streaming into this repository."""
        return StreamSink(self)

    def _get_source(self, to_format):
        """Return a source for streaming from this repository."""
        return StreamSource(self, to_format)

    @needs_read_lock
    def has_revision(self, revision_id):
        """True if this repository has a copy of the revision."""
        return revision_id in self.has_revisions((revision_id,))

    @needs_read_lock
    def has_revisions(self, revision_ids):
        """Probe to find out the presence of multiple revisions.

        :param revision_ids: An iterable of revision_ids.
        :return: A set of the revision_ids that were present.
        """
        parent_map = self.revisions.get_parent_map(
            [(rev_id,) for rev_id in revision_ids])
        result = set()
        if _mod_revision.NULL_REVISION in revision_ids:
            result.add(_mod_revision.NULL_REVISION)
        result.update([key[0] for key in parent_map])
        return result

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision."""
        return self.get_revisions([revision_id])[0]

    @needs_read_lock
    def get_revision_reconcile(self, revision_id):
        """'reconcile' helper routine that allows access to a revision always.

        This variant of get_revision does not cross check the weave graph
        against the revision one as get_revision does: but it should only
        be used by reconcile, or reconcile-alike commands that are correcting
        or testing the revision graph.
        """
        return self._get_revisions([revision_id])[0]

    @needs_read_lock
    def get_revisions(self, revision_ids):
        """Get many revisions at once.
        
        Repositories that need to check data on every revision read should 
        subclass this method.
        """
        return self._get_revisions(revision_ids)

    @needs_read_lock
    def _get_revisions(self, revision_ids):
        """Core work logic to get many revisions without sanity checks."""
        revs = {}
        for revid, rev in self._iter_revisions(revision_ids):
            if rev is None:
                raise errors.NoSuchRevision(self, revid)
            revs[revid] = rev
        return [revs[revid] for revid in revision_ids]

    def _iter_revisions(self, revision_ids):
        """Iterate over revision objects.

        :param revision_ids: An iterable of revisions to examine. None may be
            passed to request all revisions known to the repository. Note that
            not all repositories can find unreferenced revisions; for those
            repositories only referenced ones will be returned.
        :return: An iterator of (revid, revision) tuples. Absent revisions (
            those asked for but not available) are returned as (revid, None).
        """
        if revision_ids is None:
            revision_ids = self.all_revision_ids()
        else:
            for rev_id in revision_ids:
                if not rev_id or not isinstance(rev_id, basestring):
                    raise errors.InvalidRevisionId(revision_id=rev_id, branch=self)
        keys = [(key,) for key in revision_ids]
        stream = self.revisions.get_record_stream(keys, 'unordered', True)
        for record in stream:
            revid = record.key[0]
            if record.storage_kind == 'absent':
                yield (revid, None)
            else:
                text = record.get_bytes_as('fulltext')
                rev = self._serializer.read_revision_from_string(text)
                yield (revid, rev)

    @needs_read_lock
    def get_revision_xml(self, revision_id):
        # TODO: jam 20070210 This shouldn't be necessary since get_revision
        #       would have already do it.
        # TODO: jam 20070210 Just use _serializer.write_revision_to_string()
        # TODO: this can't just be replaced by:
        # return self._serializer.write_revision_to_string(
        #     self.get_revision(revision_id))
        # as cStringIO preservers the encoding unlike write_revision_to_string
        # or some other call down the path.
        rev = self.get_revision(revision_id)
        rev_tmp = cStringIO.StringIO()
        # the current serializer..
        self._serializer.write_revision(rev, rev_tmp)
        rev_tmp.seek(0)
        return rev_tmp.getvalue()

    def get_deltas_for_revisions(self, revisions, specific_fileids=None):
        """Produce a generator of revision deltas.

        Note that the input is a sequence of REVISIONS, not revision_ids.
        Trees will be held in memory until the generator exits.
        Each delta is relative to the revision's lefthand predecessor.

        :param specific_fileids: if not None, the result is filtered
          so that only those file-ids, their parents and their
          children are included.
        """
        # Get the revision-ids of interest
        required_trees = set()
        for revision in revisions:
            required_trees.add(revision.revision_id)
            required_trees.update(revision.parent_ids[:1])

        # Get the matching filtered trees. Note that it's more
        # efficient to pass filtered trees to changes_from() rather
        # than doing the filtering afterwards. changes_from() could
        # arguably do the filtering itself but it's path-based, not
        # file-id based, so filtering before or afterwards is
        # currently easier.
        if specific_fileids is None:
            trees = dict((t.get_revision_id(), t) for
                t in self.revision_trees(required_trees))
        else:
            trees = dict((t.get_revision_id(), t) for
                t in self._filtered_revision_trees(required_trees,
                specific_fileids))

        # Calculate the deltas
        for revision in revisions:
            if not revision.parent_ids:
                old_tree = self.revision_tree(_mod_revision.NULL_REVISION)
            else:
                old_tree = trees[revision.parent_ids[0]]
            yield trees[revision.revision_id].changes_from(old_tree)

    @needs_read_lock
    def get_revision_delta(self, revision_id, specific_fileids=None):
        """Return the delta for one revision.

        The delta is relative to the left-hand predecessor of the
        revision.

        :param specific_fileids: if not None, the result is filtered
          so that only those file-ids, their parents and their
          children are included.
        """
        r = self.get_revision(revision_id)
        return list(self.get_deltas_for_revisions([r],
            specific_fileids=specific_fileids))[0]

    @needs_write_lock
    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        signature = gpg_strategy.sign(plaintext)
        self.add_signature_text(revision_id, signature)

    @needs_write_lock
    def add_signature_text(self, revision_id, signature):
        self.signatures.add_lines((revision_id,), (),
            osutils.split_lines(signature))

    def find_text_key_references(self):
        """Find the text key references within the repository.

        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. The inventory texts from all present
            revision ids are assessed to generate this report.
        """
        revision_keys = self.revisions.keys()
        w = self.inventories
        pb = ui.ui_factory.nested_progress_bar()
        try:
            return self._find_text_key_references_from_xml_inventory_lines(
                w.iter_lines_added_or_present_in_keys(revision_keys, pb=pb))
        finally:
            pb.finished()

    def _find_text_key_references_from_xml_inventory_lines(self,
        line_iterator):
        """Core routine for extracting references to texts from inventories.

        This performs the translation of xml lines to revision ids.

        :param line_iterator: An iterator of lines, origin_version_id
        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. Note that if that revision_id was
            not part of the line_iterator's output then False will be given -
            even though it may actually refer to that key.
        """
        if not self._serializer.support_altered_by_hack:
            raise AssertionError(
                "_find_text_key_references_from_xml_inventory_lines only "
                "supported for branches which store inventory as unnested xml"
                ", not on %r" % self)
        result = {}

        # this code needs to read every new line in every inventory for the
        # inventories [revision_ids]. Seeing a line twice is ok. Seeing a line
        # not present in one of those inventories is unnecessary but not
        # harmful because we are filtering by the revision id marker in the
        # inventory lines : we only select file ids altered in one of those
        # revisions. We don't need to see all lines in the inventory because
        # only those added in an inventory in rev X can contain a revision=X
        # line.
        unescape_revid_cache = {}
        unescape_fileid_cache = {}

        # jam 20061218 In a big fetch, this handles hundreds of thousands
        # of lines, so it has had a lot of inlining and optimizing done.
        # Sorry that it is a little bit messy.
        # Move several functions to be local variables, since this is a long
        # running loop.
        search = self._file_ids_altered_regex.search
        unescape = _unescape_xml
        setdefault = result.setdefault
        for line, line_key in line_iterator:
            match = search(line)
            if match is None:
                continue
            # One call to match.group() returning multiple items is quite a
            # bit faster than 2 calls to match.group() each returning 1
            file_id, revision_id = match.group('file_id', 'revision_id')

            # Inlining the cache lookups helps a lot when you make 170,000
            # lines and 350k ids, versus 8.4 unique ids.
            # Using a cache helps in 2 ways:
            #   1) Avoids unnecessary decoding calls
            #   2) Re-uses cached strings, which helps in future set and
            #      equality checks.
            # (2) is enough that removing encoding entirely along with
            # the cache (so we are using plain strings) results in no
            # performance improvement.
            try:
                revision_id = unescape_revid_cache[revision_id]
            except KeyError:
                unescaped = unescape(revision_id)
                unescape_revid_cache[revision_id] = unescaped
                revision_id = unescaped

            # Note that unconditionally unescaping means that we deserialise
            # every fileid, which for general 'pull' is not great, but we don't
            # really want to have some many fulltexts that this matters anyway.
            # RBC 20071114.
            try:
                file_id = unescape_fileid_cache[file_id]
            except KeyError:
                unescaped = unescape(file_id)
                unescape_fileid_cache[file_id] = unescaped
                file_id = unescaped

            key = (file_id, revision_id)
            setdefault(key, False)
            if revision_id == line_key[-1]:
                result[key] = True
        return result

    def _inventory_xml_lines_for_keys(self, keys):
        """Get a line iterator of the sort needed for findind references.

        Not relevant for non-xml inventory repositories.

        Ghosts in revision_keys are ignored.

        :param revision_keys: The revision keys for the inventories to inspect.
        :return: An iterator over (inventory line, revid) for the fulltexts of
            all of the xml inventories specified by revision_keys.
        """
        stream = self.inventories.get_record_stream(keys, 'unordered', True)
        for record in stream:
            if record.storage_kind != 'absent':
                chunks = record.get_bytes_as('chunked')
                revid = record.key[-1]
                lines = osutils.chunks_to_lines(chunks)
                for line in lines:
                    yield line, revid

    def _find_file_ids_from_xml_inventory_lines(self, line_iterator,
        revision_keys):
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
        seen = set(self._find_text_key_references_from_xml_inventory_lines(
                line_iterator).iterkeys())
        parent_keys = self._find_parent_keys_of_revisions(revision_keys)
        parent_seen = set(self._find_text_key_references_from_xml_inventory_lines(
            self._inventory_xml_lines_for_keys(parent_keys)))
        new_keys = seen - parent_seen
        result = {}
        setdefault = result.setdefault
        for key in new_keys:
            setdefault(key[0], set()).add(key[-1])
        return result

    def _find_parent_ids_of_revisions(self, revision_ids):
        """Find all parent ids that are mentioned in the revision graph.

        :return: set of revisions that are parents of revision_ids which are
            not part of revision_ids themselves
        """
        parent_map = self.get_parent_map(revision_ids)
        parent_ids = set()
        map(parent_ids.update, parent_map.itervalues())
        parent_ids.difference_update(revision_ids)
        parent_ids.discard(_mod_revision.NULL_REVISION)
        return parent_ids

    def _find_parent_keys_of_revisions(self, revision_keys):
        """Similar to _find_parent_ids_of_revisions, but used with keys.

        :param revision_keys: An iterable of revision_keys.
        :return: The parents of all revision_keys that are not already in
            revision_keys
        """
        parent_map = self.revisions.get_parent_map(revision_keys)
        parent_keys = set()
        map(parent_keys.update, parent_map.itervalues())
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
        selected_keys = set((revid,) for revid in revision_ids)
        w = _inv_weave or self.inventories
        pb = ui.ui_factory.nested_progress_bar()
        try:
            return self._find_file_ids_from_xml_inventory_lines(
                w.iter_lines_added_or_present_in_keys(
                    selected_keys, pb=pb),
                selected_keys)
        finally:
            pb.finished()

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
        for record in self.texts.get_record_stream(text_keys, 'unordered', True):
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self)
            yield text_keys[record.key], record.get_bytes_as('chunked')

    def _generate_text_key_index(self, text_key_references=None,
        ancestors=None):
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
        pb = ui.ui_factory.nested_progress_bar()
        try:
            return self._do_generate_text_key_index(ancestors,
                text_key_references, pb)
        finally:
            pb.finished()

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
        for text_key, valid in text_key_references.iteritems():
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
        batch_size = 10 # should be ~150MB on a 55K path tree
        batch_count = len(revision_order) / batch_size + 1
        processed_texts = 0
        pb.update("Calculating text parents", processed_texts, text_count)
        for offset in xrange(batch_count):
            to_query = revision_order[offset * batch_size:(offset + 1) *
                batch_size]
            if not to_query:
                break
            for revision_id in to_query:
                parent_ids = ancestors[revision_id]
                for text_key in revision_keys[revision_id]:
                    pb.update("Calculating text parents", processed_texts)
                    processed_texts += 1
                    candidate_parents = []
                    for parent_id in parent_ids:
                        parent_text_key = (text_key[0], parent_id)
                        try:
                            check_parent = parent_text_key not in \
                                revision_keys[parent_id]
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
                                inv = self.revision_tree(parent_id).inventory
                                inventory_cache[parent_id] = inv
                            try:
                                parent_entry = inv[text_key[0]]
                            except (KeyError, errors.NoSuchId):
                                parent_entry = None
                            if parent_entry is not None:
                                parent_text_key = (
                                    text_key[0], parent_entry.revision)
                            else:
                                parent_text_key = None
                        if parent_text_key is not None:
                            candidate_parents.append(
                                text_key_cache[parent_text_key])
                    parent_heads = text_graph.heads(candidate_parents)
                    new_parents = list(parent_heads)
                    new_parents.sort(key=lambda x:candidate_parents.index(x))
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
        for result in self._find_file_keys_to_fetch(revision_ids, _files_pb):
            yield result
        del _files_pb
        for result in self._find_non_file_keys_to_fetch(revision_ids):
            yield result

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
        for file_id, altered_versions in file_ids.iteritems():
            if pb is not None:
                pb.update("fetch texts", count, num_file_ids)
            count += 1
            yield ("file", file_id, altered_versions)

    def _find_non_file_keys_to_fetch(self, revision_ids):
        # inventory
        yield ("inventory", None, revision_ids)

        # signatures
        # XXX: Note ATM no callers actually pay attention to this return
        #      instead they just use the list of revision ids and ignore
        #      missing sigs. Consider removing this work entirely
        revisions_with_signatures = set(self.signatures.get_parent_map(
            [(r,) for r in revision_ids]))
        revisions_with_signatures = set(
            [r for (r,) in revisions_with_signatures])
        revisions_with_signatures.intersection_update(revision_ids)
        yield ("signatures", None, revisions_with_signatures)

        # revisions
        yield ("revisions", None, revision_ids)

    @needs_read_lock
    def get_inventory(self, revision_id):
        """Get Inventory object by revision id."""
        return self.iter_inventories([revision_id]).next()

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
        if ((None in revision_ids)
            or (_mod_revision.NULL_REVISION in revision_ids)):
            raise ValueError('cannot get null revision inventory')
        return self._iter_inventories(revision_ids, ordering)

    def _iter_inventories(self, revision_ids, ordering):
        """single-document based inventory iteration."""
        inv_xmls = self._iter_inventory_xmls(revision_ids, ordering)
        for text, revision_id in inv_xmls:
            yield self.deserialise_inventory(revision_id, text)

    def _iter_inventory_xmls(self, revision_ids, ordering):
        if ordering is None:
            order_as_requested = True
            ordering = 'unordered'
        else:
            order_as_requested = False
        keys = [(revision_id,) for revision_id in revision_ids]
        if not keys:
            return
        if order_as_requested:
            key_iter = iter(keys)
            next_key = key_iter.next()
        stream = self.inventories.get_record_stream(keys, ordering, True)
        text_chunks = {}
        for record in stream:
            if record.storage_kind != 'absent':
                chunks = record.get_bytes_as('chunked')
                if order_as_requested:
                    text_chunks[record.key] = chunks
                else:
                    yield ''.join(chunks), record.key[-1]
            else:
                raise errors.NoSuchRevision(self, record.key)
            if order_as_requested:
                # Yield as many results as we can while preserving order.
                while next_key in text_chunks:
                    chunks = text_chunks.pop(next_key)
                    yield ''.join(chunks), next_key[-1]
                    try:
                        next_key = key_iter.next()
                    except StopIteration:
                        # We still want to fully consume the get_record_stream,
                        # just in case it is not actually finished at this point
                        next_key = None
                        break

    def deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object.

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        result = self._serializer.read_inventory_from_string(xml, revision_id,
                    entry_cache=self._inventory_entry_cache)
        if result.revision_id != revision_id:
            raise AssertionError('revision id mismatch %s != %s' % (
                result.revision_id, revision_id))
        return result

    def serialise_inventory(self, inv):
        return self._serializer.write_inventory_to_string(inv)

    def _serialise_inventory_to_lines(self, inv):
        return self._serializer.write_inventory_to_lines(inv)

    def get_serializer_format(self):
        return self._serializer.format_num

    @needs_read_lock
    def get_inventory_xml(self, revision_id):
        """Get inventory XML as a file object."""
        texts = self._iter_inventory_xmls([revision_id], 'unordered')
        try:
            text, revision_id = texts.next()
        except StopIteration:
            raise errors.HistoryMissing(self, 'inventory', revision_id)
        return text

    @needs_read_lock
    def get_inventory_sha1(self, revision_id):
        """Return the sha1 hash of the inventory entry
        """
        return self.get_revision(revision_id).inventory_sha1

    def get_rev_id_for_revno(self, revno, known_pair):
        """Return the revision id of a revno, given a later (revno, revid)
        pair in the same history.

        :return: if found (True, revid).  If the available history ran out
            before reaching the revno, then this returns
            (False, (closest_revno, closest_revid)).
        """
        known_revno, known_revid = known_pair
        partial_history = [known_revid]
        distance_from_known = known_revno - revno
        if distance_from_known < 0:
            raise ValueError(
                'requested revno (%d) is later than given known revno (%d)'
                % (revno, known_revno))
        try:
            _iter_for_revno(
                self, partial_history, stop_index=distance_from_known)
        except errors.RevisionNotPresent, err:
            if err.revision_id == known_revid:
                # The start revision (known_revid) wasn't found.
                raise
            # This is a stacked repository with no fallbacks, or a there's a
            # left-hand ghost.  Either way, even though the revision named in
            # the error isn't in this repo, we know it's the next step in this
            # left-hand history.
            partial_history.append(err.revision_id)
        if len(partial_history) <= distance_from_known:
            # Didn't find enough history to get a revid for the revno.
            earliest_revno = known_revno - len(partial_history) + 1
            return (False, (earliest_revno, partial_history[-1]))
        if len(partial_history) - 1 > distance_from_known:
            raise AssertionError('_iter_for_revno returned too much history')
        return (True, partial_history[-1])

    def iter_reverse_revision_history(self, revision_id):
        """Iterate backwards through revision ids in the lefthand history

        :param revision_id: The revision id to start with.  All its lefthand
            ancestors will be traversed.
        """
        graph = self.get_graph()
        next_id = revision_id
        while True:
            if next_id in (None, _mod_revision.NULL_REVISION):
                return
            try:
                parents = graph.get_parent_map([next_id])[next_id]
            except KeyError:
                raise errors.RevisionNotPresent(next_id, self)
            yield next_id
            if len(parents) == 0:
                return
            else:
                next_id = parents[0]

    @needs_read_lock
    def get_revision_inventory(self, revision_id):
        """Return inventory of a past revision."""
        # TODO: Unify this with get_inventory()
        # bzr 0.0.6 and later imposes the constraint that the inventory_id
        # must be the same as its revision, so this is trivial.
        if revision_id is None:
            # This does not make sense: if there is no revision,
            # then it is the current tree inventory surely ?!
            # and thus get_root_id() is something that looks at the last
            # commit on the branch, and the get_root_id is an inventory check.
            raise NotImplementedError
            # return Inventory(self.get_root_id())
        else:
            return self.get_inventory(revision_id)

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        raise NotImplementedError(self.is_shared)

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import RepoReconciler
        reconciler = RepoReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler

    def _refresh_data(self):
        """Helper called from lock_* to ensure coherency with disk.

        The default implementation does nothing; it is however possible
        for repositories to maintain loaded indices across multiple locks
        by checking inside their implementation of this method to see
        whether their indices are still valid. This depends of course on
        the disk format being validatable in this manner. This method is
        also called by the refresh_data() public interface to cause a refresh
        to occur while in a write lock so that data inserted by a smart server
        push operation is visible on the client's instance of the physical
        repository.
        """

    @needs_read_lock
    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be NULL_REVISION for the empty tree revision.
        """
        revision_id = _mod_revision.ensure_null(revision_id)
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id == _mod_revision.NULL_REVISION:
            return RevisionTree(self, Inventory(root_id=None),
                                _mod_revision.NULL_REVISION)
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self, inv, revision_id)

    def revision_trees(self, revision_ids):
        """Return Trees for revisions in this repository.

        :param revision_ids: a sequence of revision-ids;
          a revision-id may not be None or 'null:'
        """
        inventories = self.iter_inventories(revision_ids)
        for inv in inventories:
            yield RevisionTree(self, inv, inv.revision_id)

    def _filtered_revision_trees(self, revision_ids, file_ids):
        """Return Tree for a revision on this branch with only some files.

        :param revision_ids: a sequence of revision-ids;
          a revision-id may not be None or 'null:'
        :param file_ids: if not None, the result is filtered
          so that only those file-ids, their parents and their
          children are included.
        """
        inventories = self.iter_inventories(revision_ids)
        for inv in inventories:
            # Should we introduce a FilteredRevisionTree class rather
            # than pre-filter the inventory here?
            filtered_inv = inv.filter(file_ids)
            yield RevisionTree(self, filtered_inv, filtered_inv.revision_id)

    @needs_read_lock
    def get_ancestry(self, revision_id, topo_sorted=True):
        """Return a list of revision-ids integrated by a revision.

        The first element of the list is always None, indicating the origin
        revision.  This might change when we have history horizons, or
        perhaps we should have a new API.

        This is topologically sorted.
        """
        if _mod_revision.is_null(revision_id):
            return [None]
        if not self.has_revision(revision_id):
            raise errors.NoSuchRevision(self, revision_id)
        graph = self.get_graph()
        keys = set()
        search = graph._make_breadth_first_searcher([revision_id])
        while True:
            try:
                found, ghosts = search.next_with_ghosts()
            except StopIteration:
                break
            keys.update(found)
        if _mod_revision.NULL_REVISION in keys:
            keys.remove(_mod_revision.NULL_REVISION)
        if topo_sorted:
            parent_map = graph.get_parent_map(keys)
            keys = tsort.topo_sort(parent_map)
        return [None] + list(keys)

    def pack(self, hint=None):
        """Compress the data within the repository.

        This operation only makes sense for some repository types. For other
        types it should be a no-op that just returns.

        This stub method does not require a lock, but subclasses should use
        @needs_write_lock as this is a long running call its reasonable to
        implicitly lock for the user.

        :param hint: If not supplied, the whole repository is packed.
            If supplied, the repository may use the hint parameter as a
            hint for the parts of the repository to pack. A hint can be
            obtained from the result of commit_write_group(). Out of
            date hints are simply ignored, because concurrent operations
            can obsolete them rapidly.
        """

    def get_transaction(self):
        return self.control_files.get_transaction()

    def get_parent_map(self, revision_ids):
        """See graph.StackedParentsProvider.get_parent_map"""
        # revisions index works in keys; this just works in revisions
        # therefore wrap and unwrap
        query_keys = []
        result = {}
        for revision_id in revision_ids:
            if revision_id == _mod_revision.NULL_REVISION:
                result[revision_id] = ()
            elif revision_id is None:
                raise ValueError('get_parent_map(None) is not valid')
            else:
                query_keys.append((revision_id ,))
        for ((revision_id,), parent_keys) in \
                self.revisions.get_parent_map(query_keys).iteritems():
            if parent_keys:
                result[revision_id] = tuple(parent_revid
                    for (parent_revid,) in parent_keys)
            else:
                result[revision_id] = (_mod_revision.NULL_REVISION,)
        return result

    def _make_parents_provider(self):
        return self

    def get_graph(self, other_repository=None):
        """Return the graph walker for this repository format"""
        parents_provider = self._make_parents_provider()
        if (other_repository is not None and
            not self.has_same_location(other_repository)):
            parents_provider = graph.StackedParentsProvider(
                [parents_provider, other_repository._make_parents_provider()])
        return graph.Graph(parents_provider)

    def _get_versioned_file_checker(self, text_key_references=None,
        ancestors=None):
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
        return _VersionedFileChecker(self,
            text_key_references=text_key_references, ancestors=ancestors)

    def revision_ids_to_search_result(self, result_set):
        """Convert a set of revision ids to a graph SearchResult."""
        result_parents = set()
        for parents in self.get_graph().get_parent_map(
            result_set).itervalues():
            result_parents.update(parents)
        included_keys = result_set.intersection(result_parents)
        start_keys = result_set.difference(included_keys)
        exclude_keys = result_parents.difference(result_set)
        result = graph.SearchResult(start_keys, exclude_keys,
            len(result_set), result_set)
        return result

    @needs_write_lock
    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.
        :param new_value: True to restore the default, False to disable making
                          working trees.
        """
        raise NotImplementedError(self.set_make_working_trees)

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        raise NotImplementedError(self.make_working_trees)

    @needs_write_lock
    def sign_revision(self, revision_id, gpg_strategy):
        plaintext = Testament.from_revision(self, revision_id).as_short_text()
        self.store_revision_signature(gpg_strategy, plaintext, revision_id)

    @needs_read_lock
    def has_signature_for_revision_id(self, revision_id):
        """Query for a revision signature for revision_id in the repository."""
        if not self.has_revision(revision_id):
            raise errors.NoSuchRevision(self, revision_id)
        sig_present = (1 == len(
            self.signatures.get_parent_map([(revision_id,)])))
        return sig_present

    @needs_read_lock
    def get_signature_text(self, revision_id):
        """Return the text for a signature."""
        stream = self.signatures.get_record_stream([(revision_id,)],
            'unordered', True)
        record = stream.next()
        if record.storage_kind == 'absent':
            raise errors.NoSuchRevision(self, revision_id)
        return record.get_bytes_as('fulltext')

    @needs_read_lock
    def check(self, revision_ids=None, callback_refs=None, check_repo=True):
        """Check consistency of all history of given revision_ids.

        Different repository implementations should override _check().

        :param revision_ids: A non-empty list of revision_ids whose ancestry
             will be checked.  Typically the last revision_id of a branch.
        :param callback_refs: A dict of check-refs to resolve and callback
            the check/_check method on the items listed as wanting the ref.
            see bzrlib.check.
        :param check_repo: If False do not check the repository contents, just 
            calculate the data callback_refs requires and call them back.
        """
        return self._check(revision_ids, callback_refs=callback_refs,
            check_repo=check_repo)

    def _check(self, revision_ids, callback_refs, check_repo):
        result = check.Check(self, check_repo=check_repo)
        result.check(callback_refs)
        return result

    def _warn_if_deprecated(self):
        global _deprecation_warning_done
        if _deprecation_warning_done:
            return
        _deprecation_warning_done = True
        warning("Format %s for %s is deprecated - please use 'bzr upgrade' to get better performance"
                % (self._format, self.bzrdir.transport.base))

    def supports_rich_root(self):
        return self._format.rich_root_data

    def _check_ascii_revisionid(self, revision_id, method):
        """Private helper for ascii-only repositories."""
        # weave repositories refuse to store revisionids that are non-ascii.
        if revision_id is not None:
            # weaves require ascii revision ids.
            if isinstance(revision_id, unicode):
                try:
                    revision_id.encode('ascii')
                except UnicodeEncodeError:
                    raise errors.NonAsciiRevisionId(method, self)
            else:
                try:
                    revision_id.decode('ascii')
                except UnicodeDecodeError:
                    raise errors.NonAsciiRevisionId(method, self)

    def revision_graph_can_have_wrong_parents(self):
        """Is it possible for this repository to have a revision graph with
        incorrect parents?

        If True, then this repository must also implement
        _find_inconsistent_revision_parents so that check and reconcile can
        check for inconsistencies before proceeding with other checks that may
        depend on the revision index being consistent.
        """
        raise NotImplementedError(self.revision_graph_can_have_wrong_parents)


# remove these delegates a while after bzr 0.15
def __make_delegated(name, from_module):
    def _deprecated_repository_forwarder():
        symbol_versioning.warn('%s moved to %s in bzr 0.15'
            % (name, from_module),
            DeprecationWarning,
            stacklevel=2)
        m = __import__(from_module, globals(), locals(), [name])
        try:
            return getattr(m, name)
        except AttributeError:
            raise AttributeError('module %s has no name %s'
                    % (m, name))
    globals()[name] = _deprecated_repository_forwarder

for _name in [
        'AllInOneRepository',
        'WeaveMetaDirRepository',
        'PreSplitOutRepositoryFormat',
        'RepositoryFormat4',
        'RepositoryFormat5',
        'RepositoryFormat6',
        'RepositoryFormat7',
        ]:
    __make_delegated(_name, 'bzrlib.repofmt.weaverepo')

for _name in [
        'KnitRepository',
        'RepositoryFormatKnit',
        'RepositoryFormatKnit1',
        ]:
    __make_delegated(_name, 'bzrlib.repofmt.knitrepo')


def install_revision(repository, rev, revision_tree):
    """Install all revision data into a repository."""
    install_revisions(repository, [(rev, revision_tree, None)])


def install_revisions(repository, iterable, num_revisions=None, pb=None):
    """Install all revision data into a repository.

    Accepts an iterable of revision, tree, signature tuples.  The signature
    may be None.
    """
    repository.start_write_group()
    try:
        inventory_cache = lru_cache.LRUCache(10)
        for n, (revision, revision_tree, signature) in enumerate(iterable):
            _install_revision(repository, revision, revision_tree, signature,
                inventory_cache)
            if pb is not None:
                pb.update('Transferring revisions', n + 1, num_revisions)
    except:
        repository.abort_write_group()
        raise
    else:
        repository.commit_write_group()


def _install_revision(repository, rev, revision_tree, signature,
    inventory_cache):
    """Install all revision data into a repository."""
    present_parents = []
    parent_trees = {}
    for p_id in rev.parent_ids:
        if repository.has_revision(p_id):
            present_parents.append(p_id)
            parent_trees[p_id] = repository.revision_tree(p_id)
        else:
            parent_trees[p_id] = repository.revision_tree(
                                     _mod_revision.NULL_REVISION)

    inv = revision_tree.inventory
    entries = inv.iter_entries()
    # backwards compatibility hack: skip the root id.
    if not repository.supports_rich_root():
        path, root = entries.next()
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
        for revision, tree in parent_trees.iteritems():
            if ie.file_id not in tree:
                continue
            parent_id = tree.inventory[ie.file_id].revision
            if parent_id in text_parents:
                continue
            text_parents.append((ie.file_id, parent_id))
        lines = revision_tree.get_file(ie.file_id).readlines()
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
                repository.add_inventory_by_delta(rev.parent_ids[0], delta,
                    rev.revision_id, present_parents)
        else:
            repository.add_inventory(rev.revision_id, inv, present_parents)
    except errors.RevisionAlreadyPresent:
        pass
    if signature is not None:
        repository.add_signature_text(rev.revision_id, signature)
    repository.add_revision(rev.revision_id, rev, inv)


class MetaDirRepository(Repository):
    """Repositories in the new meta-dir layout.

    :ivar _transport: Transport for access to repository control files,
        typically pointing to .bzr/repository.
    """

    def __init__(self, _format, a_bzrdir, control_files):
        super(MetaDirRepository, self).__init__(_format, a_bzrdir, control_files)
        self._transport = control_files._transport

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return self._transport.has('shared-storage')

    @needs_write_lock
    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.
        :param new_value: True to restore the default, False to disable making
                          working trees.
        """
        if new_value:
            try:
                self._transport.delete('no-working-trees')
            except errors.NoSuchFile:
                pass
        else:
            self._transport.put_bytes('no-working-trees', '',
                mode=self.bzrdir._get_file_mode())

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        return not self._transport.has('no-working-trees')


class MetaDirVersionedFileRepository(MetaDirRepository):
    """Repositories in a meta-dir, that work via versioned file objects."""

    def __init__(self, _format, a_bzrdir, control_files):
        super(MetaDirVersionedFileRepository, self).__init__(_format, a_bzrdir,
            control_files)


network_format_registry = registry.FormatRegistry()
"""Registry of formats indexed by their network name.

The network name for a repository format is an identifier that can be used when
referring to formats with smart server operations. See
RepositoryFormat.network_name() for more detail.
"""


format_registry = registry.FormatRegistry(network_format_registry)
"""Registry of formats, indexed by their BzrDirMetaFormat format string.

This can contain either format instances themselves, or classes/factories that
can be called to obtain one.
"""


#####################################################################
# Repository Formats

class RepositoryFormat(object):
    """A repository format.

    Formats provide four things:
     * An initialization routine to construct repository data on disk.
     * a optional format string which is used when the BzrDir supports
       versioned children.
     * an open routine which returns a Repository instance.
     * A network name for referring to the format in smart server RPC
       methods.

    There is one and only one Format subclass for each on-disk format. But
    there can be one Repository subclass that is used for several different
    formats. The _format attribute on a Repository instance can be used to
    determine the disk format.

    Formats are placed in a registry by their format string for reference
    during opening. These should be subclasses of RepositoryFormat for
    consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object may be created even when a repository instance hasn't been
    created.

    Common instance attributes:
    _matchingbzrdir - the bzrdir format that the repository format was
    originally written to work with. This can be used if manually
    constructing a bzrdir and repository, or more commonly for test suite
    parameterization.
    """

    # Set to True or False in derived classes. True indicates that the format
    # supports ghosts gracefully.
    supports_ghosts = None
    # Can this repository be given external locations to lookup additional
    # data. Set to True or False in derived classes.
    supports_external_lookups = None
    # Does this format support CHK bytestring lookups. Set to True or False in
    # derived classes.
    supports_chks = None
    # Should commit add an inventory, or an inventory delta to the repository.
    _commit_inv_deltas = True
    # What order should fetch operations request streams in?
    # The default is unordered as that is the cheapest for an origin to
    # provide.
    _fetch_order = 'unordered'
    # Does this repository format use deltas that can be fetched as-deltas ?
    # (E.g. knits, where the knit deltas can be transplanted intact.
    # We default to False, which will ensure that enough data to get
    # a full text out of any fetch stream will be grabbed.
    _fetch_uses_deltas = False
    # Should fetch trigger a reconcile after the fetch? Only needed for
    # some repository formats that can suffer internal inconsistencies.
    _fetch_reconcile = False
    # Does this format have < O(tree_size) delta generation. Used to hint what
    # code path for commit, amongst other things.
    fast_deltas = None
    # Does doing a pack operation compress data? Useful for the pack UI command
    # (so if there is one pack, the operation can still proceed because it may
    # help), and for fetching when data won't have come from the same
    # compressor.
    pack_compresses = False
    # Does the repository inventory storage understand references to trees?
    supports_tree_reference = None

    def __str__(self):
        return "<%s>" % self.__class__.__name__

    def __eq__(self, other):
        # format objects are generally stateless
        return isinstance(other, self.__class__)

    def __ne__(self, other):
        return not self == other

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the repository object in a_bzrdir.

        This is used by bzr native formats that have a "format" file in
        the repository.  Other methods may be used by different types of
        control directory.
        """
        try:
            transport = a_bzrdir.get_repository_transport(None)
            format_string = transport.get("format").read()
            return format_registry.get(format_string)
        except errors.NoSuchFile:
            raise errors.NoRepositoryPresent(a_bzrdir)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string,
                                            kind='repository')

    @classmethod
    def register_format(klass, format):
        format_registry.register(format.get_format_string(), format)

    @classmethod
    def unregister_format(klass, format):
        format_registry.remove(format.get_format_string())

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        from bzrlib import bzrdir
        return bzrdir.format_registry.make_bzrdir('default').repository_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format.

        Note that in pre format ?? repositories the format string is
        not permitted nor written to disk.
        """
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    # TODO: this shouldn't be in the base class, it's specific to things that
    # use weaves or knits -- mbp 20070207
    def _get_versioned_file_store(self,
                                  name,
                                  transport,
                                  control_files,
                                  prefixed=True,
                                  versionedfile_class=None,
                                  versionedfile_kwargs={},
                                  escaped=False):
        if versionedfile_class is None:
            versionedfile_class = self._versionedfile_class
        weave_transport = control_files._transport.clone(name)
        dir_mode = control_files._dir_mode
        file_mode = control_files._file_mode
        return VersionedFileStore(weave_transport, prefixed=prefixed,
                                  dir_mode=dir_mode,
                                  file_mode=file_mode,
                                  versionedfile_class=versionedfile_class,
                                  versionedfile_kwargs=versionedfile_kwargs,
                                  escaped=escaped)

    def initialize(self, a_bzrdir, shared=False):
        """Initialize a repository of this format in a_bzrdir.

        :param a_bzrdir: The bzrdir to put the new repository in it.
        :param shared: The repository should be initialized as a sharable one.
        :returns: The new repository object.

        This may raise UninitializableFormat if shared repository are not
        compatible the a_bzrdir.
        """
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def network_name(self):
        """A simple byte string uniquely identifying this format for RPC calls.

        MetaDir repository formats use their disk format string to identify the
        repository over the wire. All in one formats such as bzr < 0.8, and
        foreign formats like svn/git and hg should use some marker which is
        unique and immutable.
        """
        raise NotImplementedError(self.network_name)

    def check_conversion_target(self, target_format):
        if self.rich_root_data and not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format,
                from_format=self)
        if (self.supports_tree_reference and 
            not getattr(target_format, 'supports_tree_reference', False)):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format,
                from_format=self)

    def open(self, a_bzrdir, _found=False):
        """Return an instance of this format for the bzrdir a_bzrdir.

        _found is a private parameter, do not use it.
        """
        raise NotImplementedError(self.open)


class MetaDirRepositoryFormat(RepositoryFormat):
    """Common base class for the new repositories using the metadir layout."""

    rich_root_data = False
    supports_tree_reference = False
    supports_external_lookups = False

    @property
    def _matchingbzrdir(self):
        matching = bzrdir.BzrDirMetaFormat1()
        matching.repository_format = self
        return matching

    def __init__(self):
        super(MetaDirRepositoryFormat, self).__init__()

    def _create_control_files(self, a_bzrdir):
        """Create the required files and the initial control_files object."""
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        repository_transport = a_bzrdir.get_repository_transport(self)
        control_files = lockable_files.LockableFiles(repository_transport,
                                'lock', lockdir.LockDir)
        control_files.create_lock()
        return control_files

    def _upload_blank_content(self, a_bzrdir, dirs, files, utf8_files, shared):
        """Upload the initial blank content."""
        control_files = self._create_control_files(a_bzrdir)
        control_files.lock_write()
        transport = control_files._transport
        if shared == True:
            utf8_files += [('shared-storage', '')]
        try:
            transport.mkdir_multi(dirs, mode=a_bzrdir._get_dir_mode())
            for (filename, content_stream) in files:
                transport.put_file(filename, content_stream,
                    mode=a_bzrdir._get_file_mode())
            for (filename, content_bytes) in utf8_files:
                transport.put_bytes_non_atomic(filename, content_bytes,
                    mode=a_bzrdir._get_file_mode())
        finally:
            control_files.unlock()

    def network_name(self):
        """Metadir formats have matching disk and network format strings."""
        return self.get_format_string()


# Pre-0.8 formats that don't have a disk format string (because they are
# versioned by the matching control directory). We use the control directories
# disk format string as a key for the network_name because they meet the
# constraints (simple string, unique, immutable).
network_format_registry.register_lazy(
    "Bazaar-NG branch, format 5\n",
    'bzrlib.repofmt.weaverepo',
    'RepositoryFormat5',
)
network_format_registry.register_lazy(
    "Bazaar-NG branch, format 6\n",
    'bzrlib.repofmt.weaverepo',
    'RepositoryFormat6',
)

# formats which have no format string are not discoverable or independently
# creatable on disk, so are not registered in format_registry.  They're
# all in bzrlib.repofmt.weaverepo now.  When an instance of one of these is
# needed, it's constructed directly by the BzrDir.  Non-native formats where
# the repository is not separately opened are similar.

format_registry.register_lazy(
    'Bazaar-NG Repository format 7',
    'bzrlib.repofmt.weaverepo',
    'RepositoryFormat7'
    )

format_registry.register_lazy(
    'Bazaar-NG Knit Repository Format 1',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit1',
    )

format_registry.register_lazy(
    'Bazaar Knit Repository Format 3 (bzr 0.15)\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit3',
    )

format_registry.register_lazy(
    'Bazaar Knit Repository Format 4 (bzr 1.0)\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit4',
    )

# Pack-based formats. There is one format for pre-subtrees, and one for
# post-subtrees to allow ease of testing.
# NOTE: These are experimental in 0.92. Stable in 1.0 and above
format_registry.register_lazy(
    'Bazaar pack repository format 1 (needs bzr 0.92)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack1',
    )
format_registry.register_lazy(
    'Bazaar pack repository format 1 with subtree support (needs bzr 0.92)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack3',
    )
format_registry.register_lazy(
    'Bazaar pack repository format 1 with rich root (needs bzr 1.0)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack4',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack5',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack5RichRoot',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack5RichRootBroken',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack6 (bzr 1.9)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack6',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack6RichRoot (bzr 1.9)\n',
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatKnitPack6RichRoot',
    )

# Development formats.
# Obsolete but kept pending a CHK based subtree format.
format_registry.register_lazy(
    ("Bazaar development format 2 with subtree support "
        "(needs bzr.dev from before 1.8)\n"),
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatPackDevelopment2Subtree',
    )

# 1.14->1.16 go below here
format_registry.register_lazy(
    'Bazaar development format - group compression and chk inventory'
        ' (needs bzr.dev from 1.14)\n',
    'bzrlib.repofmt.groupcompress_repo',
    'RepositoryFormatCHK1',
    )

format_registry.register_lazy(
    'Bazaar development format - chk repository with bencode revision '
        'serialization (needs bzr.dev from 1.16)\n',
    'bzrlib.repofmt.groupcompress_repo',
    'RepositoryFormatCHK2',
    )
format_registry.register_lazy(
    'Bazaar repository format 2a (needs bzr 1.16 or later)\n',
    'bzrlib.repofmt.groupcompress_repo',
    'RepositoryFormat2a',
    )


class InterRepository(InterObject):
    """This class represents operations taking place between two repositories.

    Its instances have methods like copy_content and fetch, and contain
    references to the source and target repositories these operations can be
    carried out on.

    Often we will provide convenience methods on 'repository' which carry out
    operations with another repository - they will always forward to
    InterRepository.get(other).method_name(parameters).
    """

    _walk_to_common_revisions_batch_size = 50
    _optimisers = []
    """The available optimised InterRepository types."""

    @needs_write_lock
    def copy_content(self, revision_id=None):
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.

        :param revision_id: Only copy the content needed to construct
                            revision_id and its parents.
        """
        try:
            self.target.set_make_working_trees(self.source.make_working_trees())
        except NotImplementedError:
            pass
        self.target.fetch(self.source, revision_id=revision_id)

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
            fetch_spec=None):
        """Fetch the content required to construct revision_id.

        The content is copied from self.source to self.target.

        :param revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        :param pb: optional progress bar to use for progress reports. If not
                   provided a default one will be created.
        :return: None.
        """
        from bzrlib.fetch import RepoFetcher
        f = RepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               fetch_spec=fetch_spec,
                               pb=pb, find_ghosts=find_ghosts)

    def _walk_to_common_revisions(self, revision_ids):
        """Walk out from revision_ids in source to revisions target has.

        :param revision_ids: The start point for the search.
        :return: A set of revision ids.
        """
        target_graph = self.target.get_graph()
        revision_ids = frozenset(revision_ids)
        missing_revs = set()
        source_graph = self.source.get_graph()
        # ensure we don't pay silly lookup costs.
        searcher = source_graph._make_breadth_first_searcher(revision_ids)
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
                    raise errors.NoSuchRevision(
                        self.source, ghosts_to_check.pop())
                missing_revs.update(next_revs - have_revs)
                # Because we may have walked past the original stop point, make
                # sure everything is stopped
                stop_revs = searcher.find_seen_ancestors(have_revs)
                searcher.stop_searching_any(stop_revs)
            if searcher_exhausted:
                break
        return searcher.get_result()

    @needs_read_lock
    def search_missing_revision_ids(self, revision_id=None, find_ghosts=True):
        """Return the revision ids that source has that target does not.

        :param revision_id: only return revision ids included by this
                            revision_id.
        :param find_ghosts: If True find missing revisions in deep history
            rather than just finding the surface difference.
        :return: A bzrlib.graph.SearchResult.
        """
        # stop searching at found target revisions.
        if not find_ghosts and revision_id is not None:
            return self._walk_to_common_revisions([revision_id])
        # generic, possibly worst case, slow code path.
        target_ids = set(self.target.all_revision_ids())
        if revision_id is not None:
            source_ids = self.source.get_ancestry(revision_id)
            if source_ids[0] is not None:
                raise AssertionError()
            source_ids.pop(0)
        else:
            source_ids = self.source.all_revision_ids()
        result_set = set(source_ids).difference(target_ids)
        return self.source.revision_ids_to_search_result(result_set)

    @staticmethod
    def _same_model(source, target):
        """True if source and target have the same data representation.

        Note: this is always called on the base class; overriding it in a
        subclass will have no effect.
        """
        try:
            InterRepository._assert_same_model(source, target)
            return True
        except errors.IncompatibleRepositories, e:
            return False

    @staticmethod
    def _assert_same_model(source, target):
        """Raise an exception if two repositories do not use the same model.
        """
        if source.supports_rich_root() != target.supports_rich_root():
            raise errors.IncompatibleRepositories(source, target,
                "different rich-root support")
        if source._serializer != target._serializer:
            raise errors.IncompatibleRepositories(source, target,
                "different serializers")


class InterSameDataRepository(InterRepository):
    """Code for converting between repositories that represent the same data.

    Data format and model must match for this to work.
    """

    @classmethod
    def _get_repo_format_to_test(self):
        """Repository format for testing with.

        InterSameData can pull from subtree to subtree and from non-subtree to
        non-subtree, so we test this with the richest repository format.
        """
        from bzrlib.repofmt import knitrepo
        return knitrepo.RepositoryFormatKnit3()

    @staticmethod
    def is_compatible(source, target):
        return InterRepository._same_model(source, target)


class InterWeaveRepo(InterSameDataRepository):
    """Optimised code paths between Weave based repositories.

    This should be in bzrlib/repofmt/weaverepo.py but we have not yet
    implemented lazy inter-object optimisation.
    """

    @classmethod
    def _get_repo_format_to_test(self):
        from bzrlib.repofmt import weaverepo
        return weaverepo.RepositoryFormat7()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Weave formats.

        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be
        overly general.
        """
        from bzrlib.repofmt.weaverepo import (
                RepositoryFormat5,
                RepositoryFormat6,
                RepositoryFormat7,
                )
        try:
            return (isinstance(source._format, (RepositoryFormat5,
                                                RepositoryFormat6,
                                                RepositoryFormat7)) and
                    isinstance(target._format, (RepositoryFormat5,
                                                RepositoryFormat6,
                                                RepositoryFormat7)))
        except AttributeError:
            return False

    @needs_write_lock
    def copy_content(self, revision_id=None):
        """See InterRepository.copy_content()."""
        # weave specific optimised path:
        try:
            self.target.set_make_working_trees(self.source.make_working_trees())
        except (errors.RepositoryUpgradeRequired, NotImplemented):
            pass
        # FIXME do not peek!
        if self.source._transport.listable():
            pb = ui.ui_factory.nested_progress_bar()
            try:
                self.target.texts.insert_record_stream(
                    self.source.texts.get_record_stream(
                        self.source.texts.keys(), 'topological', False))
                pb.update('copying inventory', 0, 1)
                self.target.inventories.insert_record_stream(
                    self.source.inventories.get_record_stream(
                        self.source.inventories.keys(), 'topological', False))
                self.target.signatures.insert_record_stream(
                    self.source.signatures.get_record_stream(
                        self.source.signatures.keys(),
                        'unordered', True))
                self.target.revisions.insert_record_stream(
                    self.source.revisions.get_record_stream(
                        self.source.revisions.keys(),
                        'topological', True))
            finally:
                pb.finished()
        else:
            self.target.fetch(self.source, revision_id=revision_id)

    @needs_read_lock
    def search_missing_revision_ids(self, revision_id=None, find_ghosts=True):
        """See InterRepository.missing_revision_ids()."""
        # we want all revisions to satisfy revision_id in source.
        # but we don't want to stat every file here and there.
        # we want then, all revisions other needs to satisfy revision_id
        # checked, but not those that we have locally.
        # so the first thing is to get a subset of the revisions to
        # satisfy revision_id in source, and then eliminate those that
        # we do already have.
        # this is slow on high latency connection to self, but as this
        # disk format scales terribly for push anyway due to rewriting
        # inventory.weave, this is considered acceptable.
        # - RBC 20060209
        if revision_id is not None:
            source_ids = self.source.get_ancestry(revision_id)
            if source_ids[0] is not None:
                raise AssertionError()
            source_ids.pop(0)
        else:
            source_ids = self.source._all_possible_ids()
        source_ids_set = set(source_ids)
        # source_ids is the worst possible case we may need to pull.
        # now we want to filter source_ids against what we actually
        # have in target, but don't try to check for existence where we know
        # we do not have a revision as that would be pointless.
        target_ids = set(self.target._all_possible_ids())
        possibly_present_revisions = target_ids.intersection(source_ids_set)
        actually_present_revisions = set(
            self.target._eliminate_revisions_not_present(possibly_present_revisions))
        required_revisions = source_ids_set.difference(actually_present_revisions)
        if revision_id is not None:
            # we used get_ancestry to determine source_ids then we are assured all
            # revisions referenced are present as they are installed in topological order.
            # and the tip revision was validated by get_ancestry.
            result_set = required_revisions
        else:
            # if we just grabbed the possibly available ids, then
            # we only have an estimate of whats available and need to validate
            # that against the revision records.
            result_set = set(
                self.source._eliminate_revisions_not_present(required_revisions))
        return self.source.revision_ids_to_search_result(result_set)


class InterKnitRepo(InterSameDataRepository):
    """Optimised code paths between Knit based repositories."""

    @classmethod
    def _get_repo_format_to_test(self):
        from bzrlib.repofmt import knitrepo
        return knitrepo.RepositoryFormatKnit1()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Knit formats.

        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be
        overly general.
        """
        from bzrlib.repofmt.knitrepo import RepositoryFormatKnit
        try:
            are_knits = (isinstance(source._format, RepositoryFormatKnit) and
                isinstance(target._format, RepositoryFormatKnit))
        except AttributeError:
            return False
        return are_knits and InterRepository._same_model(source, target)

    @needs_read_lock
    def search_missing_revision_ids(self, revision_id=None, find_ghosts=True):
        """See InterRepository.missing_revision_ids()."""
        if revision_id is not None:
            source_ids = self.source.get_ancestry(revision_id)
            if source_ids[0] is not None:
                raise AssertionError()
            source_ids.pop(0)
        else:
            source_ids = self.source.all_revision_ids()
        source_ids_set = set(source_ids)
        # source_ids is the worst possible case we may need to pull.
        # now we want to filter source_ids against what we actually
        # have in target, but don't try to check for existence where we know
        # we do not have a revision as that would be pointless.
        target_ids = set(self.target.all_revision_ids())
        possibly_present_revisions = target_ids.intersection(source_ids_set)
        actually_present_revisions = set(
            self.target._eliminate_revisions_not_present(possibly_present_revisions))
        required_revisions = source_ids_set.difference(actually_present_revisions)
        if revision_id is not None:
            # we used get_ancestry to determine source_ids then we are assured all
            # revisions referenced are present as they are installed in topological order.
            # and the tip revision was validated by get_ancestry.
            result_set = required_revisions
        else:
            # if we just grabbed the possibly available ids, then
            # we only have an estimate of whats available and need to validate
            # that against the revision records.
            result_set = set(
                self.source._eliminate_revisions_not_present(required_revisions))
        return self.source.revision_ids_to_search_result(result_set)


class InterDifferingSerializer(InterRepository):

    @classmethod
    def _get_repo_format_to_test(self):
        return None

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with Knit2 source and Knit3 target"""
        # This is redundant with format.check_conversion_target(), however that
        # raises an exception, and we just want to say "False" as in we won't
        # support converting between these formats.
        if 'IDS_never' in debug.debug_flags:
            return False
        if source.supports_rich_root() and not target.supports_rich_root():
            return False
        if (source._format.supports_tree_reference
            and not target._format.supports_tree_reference):
            return False
        if target._fallback_repositories and target._format.supports_chks:
            # IDS doesn't know how to copy CHKs for the parent inventories it
            # adds to stacked repos.
            return False
        if 'IDS_always' in debug.debug_flags:
            return True
        # Only use this code path for local source and target.  IDS does far
        # too much IO (both bandwidth and roundtrips) over a network.
        if not source.bzrdir.transport.base.startswith('file:///'):
            return False
        if not target.bzrdir.transport.base.startswith('file:///'):
            return False
        return True

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
        texts_possibly_new_in_tree = set()
        for basis_id, basis_tree in possible_trees:
            delta = tree.inventory._make_delta(basis_tree.inventory)
            for old_path, new_path, file_id, new_entry in delta:
                if new_path is None:
                    # This file_id isn't present in the new rev, so we don't
                    # care about it.
                    continue
                if not new_path:
                    # Rich roots are handled elsewhere...
                    continue
                kind = new_entry.kind
                if kind != 'directory' and kind != 'file':
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
        parent_revs = set()
        for parents in parent_map.values():
            parent_revs.update(parents)
        present_parents = self.source.get_parent_map(parent_revs)
        absent_parents = set(parent_revs).difference(present_parents)
        parent_invs_keys_for_stacking = self.source.inventories.get_parent_map(
            (rev_id,) for rev_id in absent_parents)
        parent_inv_ids = [key[-1] for key in parent_invs_keys_for_stacking]
        for parent_tree in self.source.revision_trees(parent_inv_ids):
            current_revision_id = parent_tree.get_revision_id()
            parents_parents_keys = parent_invs_keys_for_stacking[
                (current_revision_id,)]
            parents_parents = [key[-1] for key in parents_parents_keys]
            basis_id = _mod_revision.NULL_REVISION
            basis_tree = self.source.revision_tree(basis_id)
            delta = parent_tree.inventory._make_delta(basis_tree.inventory)
            self.target.add_inventory_by_delta(
                basis_id, delta, current_revision_id, parents_parents)
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
            basis_id, delta = self._get_delta_for_revision(tree, parent_ids,
                                                           possible_trees)
            revision = self.source.get_revision(current_revision_id)
            pending_deltas.append((basis_id, delta,
                current_revision_id, revision.parent_ids))
            if self._converting_to_rich_root:
                self._revision_id_to_root_id[current_revision_id] = \
                    tree.get_root_id()
            # Determine which texts are in present in this revision but not in
            # any of the available parents.
            texts_possibly_new_in_tree = set()
            for old_path, new_path, file_id, entry in delta:
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
                kind = entry.kind
                texts_possibly_new_in_tree.add((file_id, entry.revision))
            for basis_id, basis_tree in possible_trees:
                basis_inv = basis_tree.inventory
                for file_key in list(texts_possibly_new_in_tree):
                    file_id, file_revision = file_key
                    try:
                        entry = basis_inv[file_id]
                    except errors.NoSuchId:
                        continue
                    if entry.revision == file_revision:
                        texts_possibly_new_in_tree.remove(file_key)
            text_keys.update(texts_possibly_new_in_tree)
            pending_revisions.append(revision)
            cache[current_revision_id] = tree
            basis_id = current_revision_id
        # Copy file texts
        from_texts = self.source.texts
        to_texts = self.target.texts
        if root_keys_to_create:
            from bzrlib.fetch import _new_root_data_stream
            root_stream = _new_root_data_stream(
                root_keys_to_create, self._revision_id_to_root_id, parent_map,
                self.source)
            to_texts.insert_record_stream(root_stream)
        to_texts.insert_record_stream(from_texts.get_record_stream(
            text_keys, self.target._format._fetch_order,
            not self.target._format._fetch_uses_deltas))
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
                basis_id, delta = self._get_delta_for_revision(parent_tree,
                    parents_parents, possible_trees)
                self.target.add_inventory_by_delta(
                    basis_id, delta, current_revision_id, parents_parents)
        # insert signatures and revisions
        for revision in pending_revisions:
            try:
                signature = self.source.get_signature_text(
                    revision.revision_id)
                self.target.add_signature_text(revision.revision_id,
                    signature)
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
        del basis_tree # We don't want to hang on to it here
        hints = []
        for offset in range(0, len(revision_ids), batch_size):
            self.target.start_write_group()
            try:
                pb.update('Transferring revisions', offset,
                          len(revision_ids))
                batch = revision_ids[offset:offset+batch_size]
                basis_id = self._fetch_batch(batch, basis_id, cache)
            except:
                self.target.abort_write_group()
                raise
            else:
                hint = self.target.commit_write_group()
                if hint:
                    hints.extend(hint)
        if hints and self.target._format.pack_compresses:
            self.target.pack(hint=hints)
        pb.update('Transferring revisions', len(revision_ids),
                  len(revision_ids))

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
            fetch_spec=None):
        """See InterRepository.fetch()."""
        if fetch_spec is not None:
            raise AssertionError("Not implemented yet...")
        if (not self.source.supports_rich_root()
            and self.target.supports_rich_root()):
            self._converting_to_rich_root = True
            self._revision_id_to_root_id = {}
        else:
            self._converting_to_rich_root = False
        revision_ids = self.target.search_missing_revision_ids(self.source,
            revision_id, find_ghosts=find_ghosts).get_keys()
        if not revision_ids:
            return 0, 0
        revision_ids = tsort.topo_sort(
            self.source.get_graph().get_parent_map(revision_ids))
        if not revision_ids:
            return 0, 0
        # Walk though all revisions; get inventory deltas, copy referenced
        # texts that delta references, insert the delta, revision and
        # signature.
        if pb is None:
            my_pb = ui.ui_factory.nested_progress_bar()
            pb = my_pb
        else:
            symbol_versioning.warn(
                symbol_versioning.deprecated_in((1, 14, 0))
                % "pb parameter to fetch()")
            my_pb = None
        try:
            self._fetch_all_revisions(revision_ids, pb)
        finally:
            if my_pb is not None:
                my_pb.finished()
        return len(revision_ids), 0

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
            # Try to get a basis tree - if its a ghost it will hit the
            # NoSuchRevision case.
            basis_tree = self.source.revision_tree(basis_id)
        except (IndexError, errors.NoSuchRevision):
            basis_id = _mod_revision.NULL_REVISION
            basis_tree = self.source.revision_tree(basis_id)
        return basis_id, basis_tree


InterRepository.register_optimiser(InterDifferingSerializer)
InterRepository.register_optimiser(InterSameDataRepository)
InterRepository.register_optimiser(InterWeaveRepo)
InterRepository.register_optimiser(InterKnitRepo)


class CopyConverter(object):
    """A repository conversion tool which just performs a copy of the content.

    This is slow but quite reliable.
    """

    def __init__(self, target_format):
        """Create a CopyConverter.

        :param target_format: The format the resulting repository should be.
        """
        self.target_format = target_format

    def convert(self, repo, pb):
        """Perform the conversion of to_convert, giving feedback via pb.

        :param to_convert: The disk object to convert.
        :param pb: a progress bar to use for progress information.
        """
        self.pb = pb
        self.count = 0
        self.total = 4
        # this is only useful with metadir layouts - separated repo content.
        # trigger an assertion if not such
        repo._format.get_format_string()
        self.repo_dir = repo.bzrdir
        self.step('Moving repository to repository.backup')
        self.repo_dir.transport.move('repository', 'repository.backup')
        backup_transport =  self.repo_dir.transport.clone('repository.backup')
        repo._format.check_conversion_target(self.target_format)
        self.source_repo = repo._format.open(self.repo_dir,
            _found=True,
            _override_transport=backup_transport)
        self.step('Creating new repository')
        converted = self.target_format.initialize(self.repo_dir,
                                                  self.source_repo.is_shared())
        converted.lock_write()
        try:
            self.step('Copying content into repository.')
            self.source_repo.copy_content_into(converted)
        finally:
            converted.unlock()
        self.step('Deleting old repository content.')
        self.repo_dir.transport.delete_tree('repository.backup')
        self.pb.note('repository converted')

    def step(self, message):
        """Update the pb by a step."""
        self.count +=1
        self.pb.update(message, self.count, self.total)


_unescape_map = {
    'apos':"'",
    'quot':'"',
    'amp':'&',
    'lt':'<',
    'gt':'>'
}


def _unescaper(match, _map=_unescape_map):
    code = match.group(1)
    try:
        return _map[code]
    except KeyError:
        if not code.startswith('#'):
            raise
        return unichr(int(code[1:])).encode('utf8')


_unescape_re = None


def _unescape_xml(data):
    """Unescape predefined XML entities in a string of data."""
    global _unescape_re
    if _unescape_re is None:
        _unescape_re = re.compile('\&([^;]*);')
    return _unescape_re.sub(_unescaper, data)


class _VersionedFileChecker(object):

    def __init__(self, repository, text_key_references=None, ancestors=None):
        self.repository = repository
        self.text_index = self.repository._generate_text_key_index(
            text_key_references=text_key_references, ancestors=ancestors)

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
        self.file_ids = set([file_id for file_id, _ in
            self.text_index.iterkeys()])
        # text keys is now grouped by file_id
        n_versions = len(self.text_index)
        progress_bar.update('loading text store', 0, n_versions)
        parent_map = self.repository.texts.get_parent_map(self.text_index)
        # On unlistable transports this could well be empty/error...
        text_keys = self.repository.texts.keys()
        unused_keys = frozenset(text_keys) - set(self.text_index)
        for num, key in enumerate(self.text_index.iterkeys()):
            progress_bar.update('checking text graph', num, n_versions)
            correct_parents = self.calculate_file_version_parents(key)
            try:
                knit_parents = parent_map[key]
            except errors.RevisionNotPresent:
                # Missing text!
                knit_parents = None
            if correct_parents != knit_parents:
                wrong_parents[key] = (knit_parents, correct_parents)
        return wrong_parents, unused_keys


def _old_get_graph(repository, revision_id):
    """DO NOT USE. That is all. I'm serious."""
    graph = repository.get_graph()
    revision_graph = dict(((key, value) for key, value in
        graph.iter_ancestry([revision_id]) if value is not None))
    return _strip_NULL_ghosts(revision_graph)


def _strip_NULL_ghosts(revision_graph):
    """Also don't use this. more compatibility code for unmigrated clients."""
    # Filter ghosts, and null:
    if _mod_revision.NULL_REVISION in revision_graph:
        del revision_graph[_mod_revision.NULL_REVISION]
    for key, parents in revision_graph.items():
        revision_graph[key] = tuple(parent for parent in parents if parent
            in revision_graph)
    return revision_graph


class StreamSink(object):
    """An object that can insert a stream into a repository.

    This interface handles the complexity of reserialising inventories and
    revisions from different formats, and allows unidirectional insertion into
    stacked repositories without looking for the missing basis parents
    beforehand.
    """

    def __init__(self, target_repo):
        self.target_repo = target_repo

    def insert_stream(self, stream, src_format, resume_tokens):
        """Insert a stream's content into the target repository.

        :param src_format: a bzr repository format.

        :return: a list of resume tokens and an  iterable of keys additional
            items required before the insertion can be completed.
        """
        self.target_repo.lock_write()
        try:
            if resume_tokens:
                self.target_repo.resume_write_group(resume_tokens)
                is_resume = True
            else:
                self.target_repo.start_write_group()
                is_resume = False
            try:
                # locked_insert_stream performs a commit|suspend.
                return self._locked_insert_stream(stream, src_format, is_resume)
            except:
                self.target_repo.abort_write_group(suppress_errors=True)
                raise
        finally:
            self.target_repo.unlock()

    def _locked_insert_stream(self, stream, src_format, is_resume):
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
                new_pack.set_write_cache_size(1024*1024)
        for substream_type, substream in stream:
            if 'stream' in debug.debug_flags:
                mutter('inserting substream: %s', substream_type)
            if substream_type == 'texts':
                self.target_repo.texts.insert_record_stream(substream)
            elif substream_type == 'inventories':
                if src_serializer == to_serializer:
                    self.target_repo.inventories.insert_record_stream(
                        substream)
                else:
                    self._extract_and_insert_inventories(
                        substream, src_serializer)
            elif substream_type == 'inventory-deltas':
                self._extract_and_insert_inventory_deltas(
                    substream, src_serializer)
            elif substream_type == 'chk_bytes':
                # XXX: This doesn't support conversions, as it assumes the
                #      conversion was done in the fetch code.
                self.target_repo.chk_bytes.insert_record_stream(substream)
            elif substream_type == 'revisions':
                # This may fallback to extract-and-insert more often than
                # required if the serializers are different only in terms of
                # the inventory.
                if src_serializer == to_serializer:
                    self.target_repo.revisions.insert_record_stream(
                        substream)
                else:
                    self._extract_and_insert_revisions(substream,
                        src_serializer)
            elif substream_type == 'signatures':
                self.target_repo.signatures.insert_record_stream(substream)
            else:
                raise AssertionError('kaboom! %s' % (substream_type,))
        # Done inserting data, and the missing_keys calculations will try to
        # read back from the inserted data, so flush the writes to the new pack
        # (if this is pack format).
        if new_pack is not None:
            new_pack._write_data('', flush=True)
        # Find all the new revisions (including ones from resume_tokens)
        missing_keys = self.target_repo.get_missing_parent_inventories(
            check_for_missing_texts=is_resume)
        try:
            for prefix, versioned_file in (
                ('texts', self.target_repo.texts),
                ('inventories', self.target_repo.inventories),
                ('revisions', self.target_repo.revisions),
                ('signatures', self.target_repo.signatures),
                ('chk_bytes', self.target_repo.chk_bytes),
                ):
                if versioned_file is None:
                    continue
                missing_keys.update((prefix,) + key for key in
                    versioned_file.get_missing_compression_parent_keys())
        except NotImplementedError:
            # cannot even attempt suspending, and missing would have failed
            # during stream insertion.
            missing_keys = set()
        else:
            if missing_keys:
                # suspend the write group and tell the caller what we is
                # missing. We know we can suspend or else we would not have
                # entered this code path. (All repositories that can handle
                # missing keys can handle suspending a write group).
                write_group_tokens = self.target_repo.suspend_write_group()
                return write_group_tokens, missing_keys
        hint = self.target_repo.commit_write_group()
        if (to_serializer != src_serializer and
            self.target_repo._format.pack_compresses):
            self.target_repo.pack(hint=hint)
        return [], set()

    def _extract_and_insert_inventory_deltas(self, substream, serializer):
        target_rich_root = self.target_repo._format.rich_root_data
        target_tree_refs = self.target_repo._format.supports_tree_reference
        for record in substream:
            # Insert the delta directly
            inventory_delta_bytes = record.get_bytes_as('fulltext')
            deserialiser = inventory_delta.InventoryDeltaDeserializer()
            try:
                parse_result = deserialiser.parse_text_bytes(
                    inventory_delta_bytes)
            except inventory_delta.IncompatibleInventoryDelta, err:
                trace.mutter("Incompatible delta: %s", err.msg)
                raise errors.IncompatibleRevision(self.target_repo._format)
            basis_id, new_id, rich_root, tree_refs, inv_delta = parse_result
            revision_id = new_id
            parents = [key[0] for key in record.parents]
            self.target_repo.add_inventory_by_delta(
                basis_id, inv_delta, revision_id, parents)

    def _extract_and_insert_inventories(self, substream, serializer,
            parse_delta=None):
        """Generate a new inventory versionedfile in target, converting data.

        The inventory is retrieved from the source, (deserializing it), and
        stored in the target (reserializing it in a different format).
        """
        target_rich_root = self.target_repo._format.rich_root_data
        target_tree_refs = self.target_repo._format.supports_tree_reference
        for record in substream:
            # It's not a delta, so it must be a fulltext in the source
            # serializer's format.
            bytes = record.get_bytes_as('fulltext')
            revision_id = record.key[0]
            inv = serializer.read_inventory_from_string(bytes, revision_id)
            parents = [key[0] for key in record.parents]
            self.target_repo.add_inventory(revision_id, inv, parents)
            # No need to keep holding this full inv in memory when the rest of
            # the substream is likely to be all deltas.
            del inv

    def _extract_and_insert_revisions(self, substream, serializer):
        for record in substream:
            bytes = record.get_bytes_as('fulltext')
            revision_id = record.key[0]
            rev = serializer.read_revision_from_string(bytes)
            if rev.revision_id != revision_id:
                raise AssertionError('wtf: %s != %s' % (rev, revision_id))
            self.target_repo.add_revision(revision_id, rev)

    def finished(self):
        if self.target_repo._format._fetch_reconcile:
            self.target_repo.reconcile()


class StreamSource(object):
    """A source of a stream for fetching between repositories."""

    def __init__(self, from_repository, to_format):
        """Create a StreamSource streaming from from_repository."""
        self.from_repository = from_repository
        self.to_format = to_format

    def delta_on_metadata(self):
        """Return True if delta's are permitted on metadata streams.

        That is on revisions and signatures.
        """
        src_serializer = self.from_repository._format._serializer
        target_serializer = self.to_format._serializer
        return (self.to_format._fetch_uses_deltas and
            src_serializer == target_serializer)

    def _fetch_revision_texts(self, revs):
        # fetch signatures first and then the revision texts
        # may need to be a InterRevisionStore call here.
        from_sf = self.from_repository.signatures
        # A missing signature is just skipped.
        keys = [(rev_id,) for rev_id in revs]
        signatures = versionedfile.filter_absent(from_sf.get_record_stream(
            keys,
            self.to_format._fetch_order,
            not self.to_format._fetch_uses_deltas))
        # If a revision has a delta, this is actually expanded inside the
        # insert_record_stream code now, which is an alternate fix for
        # bug #261339
        from_rf = self.from_repository.revisions
        revisions = from_rf.get_record_stream(
            keys,
            self.to_format._fetch_order,
            not self.delta_on_metadata())
        return [('signatures', signatures), ('revisions', revisions)]

    def _generate_root_texts(self, revs):
        """This will be called by get_stream between fetching weave texts and
        fetching the inventory weave.
        """
        if self._rich_root_upgrade():
            import bzrlib.fetch
            return bzrlib.fetch.Inter1and2Helper(
                self.from_repository).generate_root_texts(revs)
        else:
            return []

    def get_stream(self, search):
        phase = 'file'
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
                text_keys.extend([(file_id, revision) for revision in
                    revisions])
            elif knit_kind == "inventory":
                # Now copy the file texts.
                from_texts = self.from_repository.texts
                yield ('texts', from_texts.get_record_stream(
                    text_keys, self.to_format._fetch_order,
                    not self.to_format._fetch_uses_deltas))
                # Cause an error if a text occurs after we have done the
                # copy.
                text_keys = None
                # Before we process the inventory we generate the root
                # texts (if necessary) so that the inventories references
                # will be valid.
                for _ in self._generate_root_texts(revs):
                    yield _
                # we fetch only the referenced inventories because we do not
                # know for unselected inventories whether all their required
                # texts are present in the other repository - it could be
                # corrupt.
                for info in self._get_inventory_stream(revs):
                    yield info
            elif knit_kind == "signatures":
                # Nothing to do here; this will be taken care of when
                # _fetch_revision_texts happens.
                pass
            elif knit_kind == "revisions":
                for record in self._fetch_revision_texts(revs):
                    yield record
            else:
                raise AssertionError("Unknown knit kind %r" % knit_kind)

    def get_stream_for_missing_keys(self, missing_keys):
        # missing keys can only occur when we are byte copying and not
        # translating (because translation means we don't send
        # unreconstructable deltas ever).
        keys = {}
        keys['texts'] = set()
        keys['revisions'] = set()
        keys['inventories'] = set()
        keys['chk_bytes'] = set()
        keys['signatures'] = set()
        for key in missing_keys:
            keys[key[0]].add(key[1:])
        if len(keys['revisions']):
            # If we allowed copying revisions at this point, we could end up
            # copying a revision without copying its required texts: a
            # violation of the requirements for repository integrity.
            raise AssertionError(
                'cannot copy revisions to fill in missing deltas %s' % (
                    keys['revisions'],))
        for substream_kind, keys in keys.iteritems():
            vf = getattr(self.from_repository, substream_kind)
            if vf is None and keys:
                    raise AssertionError(
                        "cannot fill in keys for a versioned file we don't"
                        " have: %s needs %s" % (substream_kind, keys))
            if not keys:
                # No need to stream something we don't have
                continue
            if substream_kind == 'inventories':
                # Some missing keys are genuinely ghosts, filter those out.
                present = self.from_repository.inventories.get_parent_map(keys)
                revs = [key[0] for key in present]
                # Get the inventory stream more-or-less as we do for the
                # original stream; there's no reason to assume that records
                # direct from the source will be suitable for the sink.  (Think
                # e.g. 2a -> 1.9-rich-root).
                for info in self._get_inventory_stream(revs, missing=True):
                    yield info
                continue

            # Ask for full texts always so that we don't need more round trips
            # after this stream.
            # Some of the missing keys are genuinely ghosts, so filter absent
            # records. The Sink is responsible for doing another check to
            # ensure that ghosts don't introduce missing data for future
            # fetches.
            stream = versionedfile.filter_absent(vf.get_record_stream(keys,
                self.to_format._fetch_order, True))
            yield substream_kind, stream

    def inventory_fetch_order(self):
        if self._rich_root_upgrade():
            return 'topological'
        else:
            return self.to_format._fetch_order

    def _rich_root_upgrade(self):
        return (not self.from_repository._format.rich_root_data and
            self.to_format.rich_root_data)

    def _get_inventory_stream(self, revision_ids, missing=False):
        from_format = self.from_repository._format
        if (from_format.supports_chks and self.to_format.supports_chks and
            from_format.network_name() == self.to_format.network_name()):
            raise AssertionError(
                "this case should be handled by GroupCHKStreamSource")
        elif 'forceinvdeltas' in debug.debug_flags:
            return self._get_convertable_inventory_stream(revision_ids,
                    delta_versus_null=missing)
        elif from_format.network_name() == self.to_format.network_name():
            # Same format.
            return self._get_simple_inventory_stream(revision_ids,
                    missing=missing)
        elif (not from_format.supports_chks and not self.to_format.supports_chks
                and from_format._serializer == self.to_format._serializer):
            # Essentially the same format.
            return self._get_simple_inventory_stream(revision_ids,
                    missing=missing)
        else:
            # Any time we switch serializations, we want to use an
            # inventory-delta based approach.
            return self._get_convertable_inventory_stream(revision_ids,
                    delta_versus_null=missing)

    def _get_simple_inventory_stream(self, revision_ids, missing=False):
        # NB: This currently reopens the inventory weave in source;
        # using a single stream interface instead would avoid this.
        from_weave = self.from_repository.inventories
        if missing:
            delta_closure = True
        else:
            delta_closure = not self.delta_on_metadata()
        yield ('inventories', from_weave.get_record_stream(
            [(rev_id,) for rev_id in revision_ids],
            self.inventory_fetch_order(), delta_closure))

    def _get_convertable_inventory_stream(self, revision_ids,
                                          delta_versus_null=False):
        # The source is using CHKs, but the target either doesn't or it has a
        # different serializer.  The StreamSink code expects to be able to
        # convert on the target, so we need to put bytes-on-the-wire that can
        # be converted.  That means inventory deltas (if the remote is <1.19,
        # RemoteStreamSink will fallback to VFS to insert the deltas).
        yield ('inventory-deltas',
           self._stream_invs_as_deltas(revision_ids,
                                       delta_versus_null=delta_versus_null))

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
        inventories = self.from_repository.iter_inventories(
            revision_ids, 'topological')
        format = from_repo._format
        invs_sent_so_far = set([_mod_revision.NULL_REVISION])
        inventory_cache = lru_cache.LRUCache(50)
        null_inventory = from_repo.revision_tree(
            _mod_revision.NULL_REVISION).inventory
        # XXX: ideally the rich-root/tree-refs flags would be per-revision, not
        # per-repo (e.g.  streaming a non-rich-root revision out of a rich-root
        # repo back into a non-rich-root repo ought to be allowed)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=format.rich_root_data,
            tree_references=format.supports_tree_reference)
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
                    if (delta is None or
                        len(delta) > len(candidate_delta)):
                        delta = candidate_delta
                        basis_id = parent_id
            if delta is None:
                # Either none of the parents ended up being suitable, or we
                # were asked to delta against NULL
                basis_id = _mod_revision.NULL_REVISION
                delta = inv._make_delta(null_inventory)
            invs_sent_so_far.add(inv.revision_id)
            inventory_cache[inv.revision_id] = inv
            delta_serialized = ''.join(
                serializer.delta_to_lines(basis_id, key[-1], delta))
            yield versionedfile.FulltextContentFactory(
                key, parent_keys, None, delta_serialized)


def _iter_for_revno(repo, partial_history_cache, stop_index=None,
                    stop_revision=None):
    """Extend the partial history to include a given index

    If a stop_index is supplied, stop when that index has been reached.
    If a stop_revision is supplied, stop when that revision is
    encountered.  Otherwise, stop when the beginning of history is
    reached.

    :param stop_index: The index which should be present.  When it is
        present, history extension will stop.
    :param stop_revision: The revision id which should be present.  When
        it is encountered, history extension will stop.
    """
    start_revision = partial_history_cache[-1]
    iterator = repo.iter_reverse_revision_history(start_revision)
    try:
        #skip the last revision in the list
        iterator.next()
        while True:
            if (stop_index is not None and
                len(partial_history_cache) > stop_index):
                break
            if partial_history_cache[-1] == stop_revision:
                break
            revision_id = iterator.next()
            partial_history_cache.append(revision_id)
    except StopIteration:
        # No more history
        return


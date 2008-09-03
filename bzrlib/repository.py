# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from cStringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import re
import time

from bzrlib import (
    bzrdir,
    check,
    debug,
    errors,
    generate_ids,
    gpg,
    graph,
    lazy_regex,
    lockable_files,
    lockdir,
    lru_cache,
    osutils,
    registry,
    remote,
    revision as _mod_revision,
    symbol_versioning,
    transactions,
    tsort,
    ui,
    )
from bzrlib.bundle import serializer
from bzrlib.revisiontree import RevisionTree
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.store.text import TextStore
from bzrlib.testament import Testament
from bzrlib.util import bencode
""")

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.inter import InterObject
from bzrlib.inventory import Inventory, InventoryDirectory, ROOT_ID
from bzrlib.symbol_versioning import (
        deprecated_method,
        one_one,
        one_two,
        one_three,
        one_six,
        )
from bzrlib.trace import mutter, mutter_callsite, note, warning


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

    def commit(self, message):
        """Make the actual commit.

        :return: The revision id of the recorded revision.
        """
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
        return RevisionTree(self.repository, self.new_inventory,
                            self._new_revision_id)

    def finish_inventory(self):
        """Tell the builder that the inventory is finished."""
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

    def _get_delta(self, ie, basis_inv, path):
        """Get a delta against the basis inventory for ie."""
        if ie.file_id not in basis_inv:
            # add
            return (None, path, ie.file_id, ie)
        elif ie != basis_inv[ie.file_id]:
            # common but altered
            # TODO: avoid tis id2path call.
            return (basis_inv.id2path(ie.file_id), path, ie.file_id, ie)
        else:
            # common, unaltered
            return None

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
        :return: A tuple (change_delta, version_recorded). change_delta is 
            an inventory_delta change for this entry against the basis tree of
            the commit, or None if no change occured against the basis tree.
            version_recorded is True if a new version of the entry has been
            recorded. For instance, committing a merge where a file was only
            changed on the other side will return (delta, False).
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
                # revision to the new commit even when no change occurs, and
                # this masks when a change may have occurred against the basis,
                # so calculate if one happened.
                if ie.file_id in basis_inv:
                    delta = (basis_inv.id2path(ie.file_id), path,
                        ie.file_id, ie)
                else:
                    # add
                    delta = (None, path, ie.file_id, ie)
                return delta, False
            else:
                # we don't need to commit this, because the caller already
                # determined that an existing revision of this file is
                # appropriate.
                return None, (ie.revision == self._new_revision_id)
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
        if kind == 'file':
            if content_summary[2] is None:
                raise ValueError("Files must not have executable = None")
            if not store:
                if (# if the file length changed we have to store:
                    parent_entry.text_size != content_summary[1] or
                    # if the exec bit has changed we have to store:
                    parent_entry.executable != content_summary[2]):
                    store = True
                elif parent_entry.text_sha1 == content_summary[3]:
                    # all meta and content is unchanged (using a hash cache
                    # hit to check the sha)
                    ie.revision = parent_entry.revision
                    ie.text_size = parent_entry.text_size
                    ie.text_sha1 = parent_entry.text_sha1
                    ie.executable = parent_entry.executable
                    return self._get_delta(ie, basis_inv, path), False
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
            lines = tree.get_file(ie.file_id, path).readlines()
            try:
                ie.text_sha1, ie.text_size = self._add_text_to_weave(
                    ie.file_id, lines, heads, nostore_sha)
            except errors.ExistingContent:
                # Turns out that the file content was unchanged, and we were
                # only going to store a new node if it was changed. Carry over
                # the entry.
                ie.revision = parent_entry.revision
                ie.text_size = parent_entry.text_size
                ie.text_sha1 = parent_entry.text_sha1
                ie.executable = parent_entry.executable
                return self._get_delta(ie, basis_inv, path), False
        elif kind == 'directory':
            if not store:
                # all data is meta here, nothing specific to directory, so
                # carry over:
                ie.revision = parent_entry.revision
                return self._get_delta(ie, basis_inv, path), False
            lines = []
            self._add_text_to_weave(ie.file_id, lines, heads, None)
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
                return self._get_delta(ie, basis_inv, path), False
            ie.symlink_target = current_link_target
            lines = []
            self._add_text_to_weave(ie.file_id, lines, heads, None)
        elif kind == 'tree-reference':
            if not store:
                if content_summary[3] != parent_entry.reference_revision:
                    store = True
            if not store:
                # unchanged, carry over.
                ie.reference_revision = parent_entry.reference_revision
                ie.revision = parent_entry.revision
                return self._get_delta(ie, basis_inv, path), False
            ie.reference_revision = content_summary[3]
            lines = []
            self._add_text_to_weave(ie.file_id, lines, heads, None)
        else:
            raise NotImplementedError('unknown kind')
        ie.revision = self._new_revision_id
        return self._get_delta(ie, basis_inv, path), True

    def _add_text_to_weave(self, file_id, new_lines, parents, nostore_sha):
        # Note: as we read the content directly from the tree, we know its not
        # been turned into unicode or badly split - but a broken tree
        # implementation could give us bad output from readlines() so this is
        # not a guarantee of safety. What would be better is always checking
        # the content during test suite execution. RBC 20070912
        parent_keys = tuple((file_id, parent) for parent in parents)
        return self.repository.texts.add_lines(
            (file_id, self._new_revision_id), parent_keys, new_lines,
            nostore_sha=nostore_sha, random_id=self.random_revid,
            check_content=False)[0:2]


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


######################################################################
# Repositories

class Repository(object):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    The Repository builds on top of some byte storage facilies (the revisions,
    signatures, inventories and texts attributes) and a Transport, which
    respectively provide byte storage and a means to access the (possibly
    remote) disk.

    The byte storage facilities are addressed via tuples, which we refer to
    as 'keys' throughout the code base. Revision_keys, inventory_keys and
    signature_keys are all 1-tuples: (revision_id,). text_keys are two-tuples:
    (file_id, revision_id). We use this interface because it allows low
    friction with the underlying code that implements disk indices, network
    encoding and other parts of bzrlib.

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

    def abort_write_group(self):
        """Commit the contents accrued within the current write group.

        :seealso: start_write_group.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            raise errors.BzrError('mismatched lock context and write group.')
        self._abort_write_group()
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
        self._check_fallback_repository(repository)
        self._fallback_repositories.append(repository)
        self.texts.add_fallback_versioned_files(repository.texts)
        self.inventories.add_fallback_versioned_files(repository.inventories)
        self.revisions.add_fallback_versioned_files(repository.revisions)
        self.signatures.add_fallback_versioned_files(repository.signatures)

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
        inv_lines = self._serialise_inventory_to_lines(inv)
        return self._inventory_add_lines(revision_id, parents,
            inv_lines, check_content=False)

    def _inventory_add_lines(self, revision_id, parents, lines,
        check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory."""
        parents = [(parent,) for parent in parents]
        return self.inventories.add_lines((revision_id,), parents, lines,
            check_content=check_content)[0]

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
        # What order should fetch operations request streams in?
        # The default is unordered as that is the cheapest for an origin to
        # provide.
        self._fetch_order = 'unordered'
        # Does this repository use deltas that can be fetched as-deltas ?
        # (E.g. knits, where the knit deltas can be transplanted intact.
        # We default to False, which will ensure that enough data to get
        # a full text out of any fetch stream will be grabbed.
        self._fetch_uses_deltas = False
        # Should fetch trigger a reconcile after the fetch? Only needed for
        # some repository formats that can suffer internal inconsistencies.
        self._fetch_reconcile = False

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__,
                           self.base)

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
        result = self.control_files.lock_write(token=token)
        for repo in self._fallback_repositories:
            # Writes don't affect fallback repos
            repo.lock_read()
        self._refresh_data()
        return result

    def lock_read(self):
        self.control_files.lock_read()
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

    @deprecated_method(one_two)
    @needs_read_lock
    def missing_revision_ids(self, other, revision_id=None, find_ghosts=True):
        """Return the revision ids that other has that this does not.
        
        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        keys =  self.search_missing_revision_ids(
            other, revision_id, find_ghosts).get_keys()
        other.lock_read()
        try:
            parents = other.get_graph().get_parent_map(keys)
        finally:
            other.unlock()
        return tsort.topo_sort(parents)

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
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            raise errors.BzrError('mismatched lock context %r and '
                'write group %r.' %
                (self.get_transaction(), self._write_group))
        self._commit_write_group()
        self._write_group = None

    def _commit_write_group(self):
        """Template method for per-repository write group cleanup.
        
        This is called before the write group is considered to be 
        finished and should ensure that all data handed to the repository
        for writing during the write group is safely committed (to the 
        extent possible considering file system caching etc).
        """

    def fetch(self, source, revision_id=None, pb=None, find_ghosts=False):
        """Fetch the content required to construct revision_id from source.

        If revision_id is None all content is copied.
        :param find_ghosts: Find and copy revisions in the source that are
            ghosts in the target (and not reachable directly by walking out to
            the first-present revision in target from revision_id).
        """
        # fast path same-url fetch operations
        if self.has_same_location(source):
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
            find_ghosts=find_ghosts)

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
        """Get many revisions at once."""
        return self._get_revisions(revision_ids)

    @needs_read_lock
    def _get_revisions(self, revision_ids):
        """Core work logic to get many revisions without sanity checks."""
        for rev_id in revision_ids:
            if not rev_id or not isinstance(rev_id, basestring):
                raise errors.InvalidRevisionId(revision_id=rev_id, branch=self)
        keys = [(key,) for key in revision_ids]
        stream = self.revisions.get_record_stream(keys, 'unordered', True)
        revs = {}
        for record in stream:
            if record.storage_kind == 'absent':
                raise errors.NoSuchRevision(self, record.key[0])
            text = record.get_bytes_as('fulltext')
            rev = self._serializer.read_revision_from_string(text)
            revs[record.key[0]] = rev
        return [revs[revid] for revid in revision_ids]

    @needs_read_lock
    def get_revision_xml(self, revision_id):
        # TODO: jam 20070210 This shouldn't be necessary since get_revision
        #       would have already do it.
        # TODO: jam 20070210 Just use _serializer.write_revision_to_string()
        rev = self.get_revision(revision_id)
        rev_tmp = StringIO()
        # the current serializer..
        self._serializer.write_revision(rev, rev_tmp)
        rev_tmp.seek(0)
        return rev_tmp.getvalue()

    def get_deltas_for_revisions(self, revisions):
        """Produce a generator of revision deltas.
        
        Note that the input is a sequence of REVISIONS, not revision_ids.
        Trees will be held in memory until the generator exits.
        Each delta is relative to the revision's lefthand predecessor.
        """
        required_trees = set()
        for revision in revisions:
            required_trees.add(revision.revision_id)
            required_trees.update(revision.parent_ids[:1])
        trees = dict((t.get_revision_id(), t) for 
                     t in self.revision_trees(required_trees))
        for revision in revisions:
            if not revision.parent_ids:
                old_tree = self.revision_tree(None)
            else:
                old_tree = trees[revision.parent_ids[0]]
            yield trees[revision.revision_id].changes_from(old_tree)

    @needs_read_lock
    def get_revision_delta(self, revision_id):
        """Return the delta for one revision.

        The delta is relative to the left-hand predecessor of the
        revision.
        """
        r = self.get_revision(revision_id)
        return list(self.get_deltas_for_revisions([r]))[0]

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

        :return: a dictionary mapping (file_id, revision_id) tuples to altered file-ids to an iterable of
        revision_ids. Each altered file-ids has the exact revision_ids that
        altered it listed explicitly.
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

    def _find_file_ids_from_xml_inventory_lines(self, line_iterator,
        revision_ids):
        """Helper routine for fileids_altered_by_revision_ids.

        This performs the translation of xml lines to revision ids.

        :param line_iterator: An iterator of lines, origin_version_id
        :param revision_ids: The revision ids to filter for. This should be a
            set or other type which supports efficient __contains__ lookups, as
            the revision id from each parsed line will be looked up in the
            revision_ids filter.
        :return: a dictionary mapping altered file-ids to an iterable of
        revision_ids. Each altered file-ids has the exact revision_ids that
        altered it listed explicitly.
        """
        result = {}
        setdefault = result.setdefault
        for key in \
            self._find_text_key_references_from_xml_inventory_lines(
                line_iterator).iterkeys():
            # once data is all ensured-consistent; then this is
            # if revision_id == version_id
            if key[-1:] in revision_ids:
                setdefault(key[0], set()).add(key[-1])
        return result

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
        transaction = self.get_transaction()
        text_keys = {}
        for file_id, revision_id, callable_data in desired_files:
            text_keys[(file_id, revision_id)] = callable_data
        for record in self.texts.get_record_stream(text_keys, 'unordered', True):
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self)
            yield text_keys[record.key], record.get_bytes_as('fulltext')

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
        pb.update("Calculating text parents.", processed_texts, text_count)
        for offset in xrange(batch_count):
            to_query = revision_order[offset * batch_size:(offset + 1) *
                batch_size]
            if not to_query:
                break
            for rev_tree in self.revision_trees(to_query):
                revision_id = rev_tree.get_revision_id()
                parent_ids = ancestors[revision_id]
                for text_key in revision_keys[revision_id]:
                    pb.update("Calculating text parents.", processed_texts)
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
                            parent_entry = inv._byid.get(text_key[0], None)
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
            if _files_pb is not None:
                _files_pb.update("fetch texts", count, num_file_ids)
            count += 1
            yield ("file", file_id, altered_versions)
        # We're done with the files_pb.  Note that it finished by the caller,
        # just as it was created by the caller.
        del _files_pb

        # inventory
        yield ("inventory", None, revision_ids)

        # signatures
        revisions_with_signatures = set()
        for rev_id in revision_ids:
            try:
                self.get_signature_text(rev_id)
            except errors.NoSuchRevision:
                # not signed.
                pass
            else:
                revisions_with_signatures.add(rev_id)
        yield ("signatures", None, revisions_with_signatures)

        # revisions
        yield ("revisions", None, revision_ids)

    @needs_read_lock
    def get_inventory(self, revision_id):
        """Get Inventory object by revision id."""
        return self.iter_inventories([revision_id]).next()

    def iter_inventories(self, revision_ids):
        """Get many inventories by revision_ids.

        This will buffer some or all of the texts used in constructing the
        inventories in memory, but will only parse a single inventory at a
        time.

        :return: An iterator of inventories.
        """
        if ((None in revision_ids)
            or (_mod_revision.NULL_REVISION in revision_ids)):
            raise ValueError('cannot get null revision inventory')
        return self._iter_inventories(revision_ids)

    def _iter_inventories(self, revision_ids):
        """single-document based inventory iteration."""
        for text, revision_id in self._iter_inventory_xmls(revision_ids):
            yield self.deserialise_inventory(revision_id, text)

    def _iter_inventory_xmls(self, revision_ids):
        keys = [(revision_id,) for revision_id in revision_ids]
        stream = self.inventories.get_record_stream(keys, 'unordered', True)
        texts = {}
        for record in stream:
            if record.storage_kind != 'absent':
                texts[record.key] = record.get_bytes_as('fulltext')
            else:
                raise errors.NoSuchRevision(self, record.key)
        for key in keys:
            yield texts[key], key[-1]

    def deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object. 

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        result = self._serializer.read_inventory_from_string(xml, revision_id)
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
        texts = self._iter_inventory_xmls([revision_id])
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
            yield next_id
            # Note: The following line may raise KeyError in the event of
            # truncated history. We decided not to have a try:except:raise
            # RevisionNotPresent here until we see a use for it, because of the
            # cost in an inner loop that is by its very nature O(history).
            # Robert Collins 20080326
            parents = graph.get_parent_map([next_id])[next_id]
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
        the disk format being validatable in this manner.
        """

    @needs_read_lock
    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the empty tree revision.
        """
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id is None or revision_id == _mod_revision.NULL_REVISION:
            return RevisionTree(self, Inventory(root_id=None), 
                                _mod_revision.NULL_REVISION)
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self, inv, revision_id)

    def revision_trees(self, revision_ids):
        """Return Tree for a revision on this branch.

        `revision_id` may not be None or 'null:'"""
        inventories = self.iter_inventories(revision_ids)
        for inv in inventories:
            yield RevisionTree(self, inv, inv.revision_id)

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

    def pack(self):
        """Compress the data within the repository.

        This operation only makes sense for some repository types. For other
        types it should be a no-op that just returns.

        This stub method does not require a lock, but subclasses should use
        @needs_write_lock as this is a long running call its reasonable to 
        implicitly lock for the user.
        """

    @needs_read_lock
    @deprecated_method(one_six)
    def print_file(self, file, revision_id):
        """Print `file` to stdout.
        
        FIXME RBC 20060125 as John Meinel points out this is a bad api
        - it writes to stdout, it assumes that that is valid etc. Fix
        by creating a new more flexible convenience function.
        """
        tree = self.revision_tree(revision_id)
        # use inventory as it was in that revision
        file_id = tree.inventory.path2id(file)
        if not file_id:
            # TODO: jam 20060427 Write a test for this code path
            #       it had a bug in it, and was raising the wrong
            #       exception.
            raise errors.BzrError("%r is not present in revision %s" % (file, revision_id))
        tree.print_file(file_id)

    def get_transaction(self):
        return self.control_files.get_transaction()

    @deprecated_method(one_one)
    def get_parents(self, revision_ids):
        """See StackedParentsProvider.get_parents"""
        parent_map = self.get_parent_map(revision_ids)
        return [parent_map.get(r, None) for r in revision_ids]

    def get_parent_map(self, revision_ids):
        """See graph._StackedParentsProvider.get_parent_map"""
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
            parents_provider = graph._StackedParentsProvider(
                [parents_provider, other_repository._make_parents_provider()])
        return graph.Graph(parents_provider)

    def _get_versioned_file_checker(self):
        """Return an object suitable for checking versioned files."""
        return _VersionedFileChecker(self)

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
    def check(self, revision_ids=None):
        """Check consistency of all history of given revision_ids.

        Different repository implementations should override _check().

        :param revision_ids: A non-empty list of revision_ids whose ancestry
             will be checked.  Typically the last revision_id of a branch.
        """
        return self._check(revision_ids)

    def _check(self, revision_ids):
        result = check.Check(self)
        result.check()
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
        for n, (revision, revision_tree, signature) in enumerate(iterable):
            _install_revision(repository, revision, revision_tree, signature)
            if pb is not None:
                pb.update('Transferring revisions', n + 1, num_revisions)
    except:
        repository.abort_write_group()
        raise
    else:
        repository.commit_write_group()


def _install_revision(repository, rev, revision_tree, signature):
    """Install all revision data into a repository."""
    present_parents = []
    parent_trees = {}
    for p_id in rev.parent_ids:
        if repository.has_revision(p_id):
            present_parents.append(p_id)
            parent_trees[p_id] = repository.revision_tree(p_id)
        else:
            parent_trees[p_id] = repository.revision_tree(None)

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


class RepositoryFormatRegistry(registry.Registry):
    """Registry of RepositoryFormats."""

    def get(self, format_string):
        r = registry.Registry.get(self, format_string)
        if callable(r):
            r = r()
        return r
    

format_registry = RepositoryFormatRegistry()
"""Registry of formats, indexed by their identifying format string.

This can contain either format instances themselves, or classes/factories that
can be called to obtain one.
"""


#####################################################################
# Repository Formats

class RepositoryFormat(object):
    """A repository format.

    Formats provide three things:
     * An initialization routine to construct repository data on disk.
     * a format string which is used when the BzrDir supports versioned
       children.
     * an open routine which returns a Repository instance.

    There is one and only one Format subclass for each on-disk format. But
    there can be one Repository subclass that is used for several different
    formats. The _format attribute on a Repository instance can be used to
    determine the disk format.

    Formats are placed in an dict by their format string for reference 
    during opening. These should be subclasses of RepositoryFormat
    for consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every system load.

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

    def check_conversion_target(self, target_format):
        raise NotImplementedError(self.check_conversion_target)

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
    _matchingbzrdir = bzrdir.BzrDirMetaFormat1()

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


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.  They're 
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

# Development formats. 
# 1.2->1.3
# development 0 - stub to introduce development versioning scheme.
format_registry.register_lazy(
    "Bazaar development format 0 (needs bzr.dev from before 1.3)\n",
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatPackDevelopment0',
    )
format_registry.register_lazy(
    ("Bazaar development format 0 with subtree support "
        "(needs bzr.dev from before 1.3)\n"),
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatPackDevelopment0Subtree',
    )
format_registry.register_lazy(
    "Bazaar development format 1 (needs bzr.dev from before 1.6)\n",
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatPackDevelopment1',
    )
format_registry.register_lazy(
    ("Bazaar development format 1 with subtree support "
        "(needs bzr.dev from before 1.6)\n"),
    'bzrlib.repofmt.pack_repo',
    'RepositoryFormatPackDevelopment1Subtree',
    )
# 1.3->1.4 go below here


class InterRepository(InterObject):
    """This class represents operations taking place between two repositories.

    Its instances have methods like copy_content and fetch, and contain
    references to the source and target repositories these operations can be 
    carried out on.

    Often we will provide convenience methods on 'repository' which carry out
    operations with another repository - they will always forward to
    InterRepository.get(other).method_name(parameters).
    """

    _optimisers = []
    """The available optimised InterRepository types."""

    def copy_content(self, revision_id=None):
        raise NotImplementedError(self.copy_content)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """Fetch the content required to construct revision_id.

        The content is copied from self.source to self.target.

        :param revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        :param pb: optional progress bar to use for progress reports. If not
                   provided a default one will be created.

        :returns: (copied_revision_count, failures).
        """
        # Normally we should find a specific InterRepository subclass to do
        # the fetch; if nothing else then at least InterSameDataRepository.
        # If none of them is suitable it looks like fetching is not possible;
        # we try to give a good message why.  _assert_same_model will probably
        # give a helpful message; otherwise a generic one.
        self._assert_same_model(self.source, self.target)
        raise errors.IncompatibleRepositories(self.source, self.target,
            "no suitableInterRepository found")

    def _walk_to_common_revisions(self, revision_ids):
        """Walk out from revision_ids in source to revisions target has.

        :param revision_ids: The start point for the search.
        :return: A set of revision ids.
        """
        target_graph = self.target.get_graph()
        revision_ids = frozenset(revision_ids)
        if set(target_graph.get_parent_map(revision_ids)) == revision_ids:
            return graph.SearchResult(revision_ids, set(), 0, set())
        missing_revs = set()
        source_graph = self.source.get_graph()
        # ensure we don't pay silly lookup costs.
        searcher = source_graph._make_breadth_first_searcher(revision_ids)
        null_set = frozenset([_mod_revision.NULL_REVISION])
        while True:
            try:
                next_revs, ghosts = searcher.next_with_ghosts()
            except StopIteration:
                break
            if revision_ids.intersection(ghosts):
                absent_ids = set(revision_ids.intersection(ghosts))
                # If all absent_ids are present in target, no error is needed.
                absent_ids.difference_update(
                    set(target_graph.get_parent_map(absent_ids)))
                if absent_ids:
                    raise errors.NoSuchRevision(self.source, absent_ids.pop())
            # we don't care about other ghosts as we can't fetch them and
            # haven't been asked to.
            next_revs = set(next_revs)
            # we always have NULL_REVISION present.
            have_revs = set(target_graph.get_parent_map(next_revs)).union(null_set)
            missing_revs.update(next_revs - have_revs)
            searcher.stop_searching_any(have_revs)
        return searcher.get_result()
   
    @deprecated_method(one_two)
    @needs_read_lock
    def missing_revision_ids(self, revision_id=None, find_ghosts=True):
        """Return the revision ids that source has that target does not.
        
        These are returned in topological order.

        :param revision_id: only return revision ids included by this
                            revision_id.
        :param find_ghosts: If True find missing revisions in deep history
            rather than just finding the surface difference.
        """
        return list(self.search_missing_revision_ids(
            revision_id, find_ghosts).get_keys())

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

    @needs_write_lock
    def copy_content(self, revision_id=None):
        """Make a complete copy of the content in self into destination.

        This copies both the repository's revision data, and configuration information
        such as the make_working_trees setting.
        
        This is a destructive operation! Do not use it on existing 
        repositories.

        :param revision_id: Only copy the content needed to construct
                            revision_id and its parents.
        """
        try:
            self.target.set_make_working_trees(self.source.make_working_trees())
        except NotImplementedError:
            pass
        # but don't bother fetching if we have the needed data now.
        if (revision_id not in (None, _mod_revision.NULL_REVISION) and 
            self.target.has_revision(revision_id)):
            return
        self.target.fetch(self.source, revision_id=revision_id)

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import RepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target,
               self.target._format)
        f = RepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               pb=pb, find_ghosts=find_ghosts)
        return f.count_copied, f.failed_revisions


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

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import RepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, self.target._format)
        f = RepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               pb=pb, find_ghosts=find_ghosts)
        return f.count_copied, f.failed_revisions

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
        # this is slow on high latency connection to self, but as as this
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

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import RepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, self.target._format)
        f = RepoFetcher(to_repository=self.target,
                            from_repository=self.source,
                            last_revision=revision_id,
                            pb=pb, find_ghosts=find_ghosts)
        return f.count_copied, f.failed_revisions

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


class InterPackRepo(InterSameDataRepository):
    """Optimised code paths between Pack based repositories."""

    @classmethod
    def _get_repo_format_to_test(self):
        from bzrlib.repofmt import pack_repo
        return pack_repo.RepositoryFormatKnitPack1()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Pack formats.
        
        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be 
        overly general.
        """
        from bzrlib.repofmt.pack_repo import RepositoryFormatPack
        try:
            are_packs = (isinstance(source._format, RepositoryFormatPack) and
                isinstance(target._format, RepositoryFormatPack))
        except AttributeError:
            return False
        return are_packs and InterRepository._same_model(source, target)

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        if (len(self.source._fallback_repositories) > 0 or
            len(self.target._fallback_repositories) > 0):
            # The pack layer is not aware of fallback repositories, so when
            # fetching from a stacked repository or into a stacked repository
            # we use the generic fetch logic which uses the VersionedFiles
            # attributes on repository.
            from bzrlib.fetch import RepoFetcher
            fetcher = RepoFetcher(self.target, self.source, revision_id,
                                  pb, find_ghosts)
            return fetcher.count_copied, fetcher.failed_revisions
        from bzrlib.repofmt.pack_repo import Packer
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, self.target._format)
        self.count_copied = 0
        if revision_id is None:
            # TODO:
            # everything to do - use pack logic
            # to fetch from all packs to one without
            # inventory parsing etc, IFF nothing to be copied is in the target.
            # till then:
            source_revision_ids = frozenset(self.source.all_revision_ids())
            revision_ids = source_revision_ids - \
                frozenset(self.target.get_parent_map(source_revision_ids))
            revision_keys = [(revid,) for revid in revision_ids]
            index = self.target._pack_collection.revision_index.combined_index
            present_revision_ids = set(item[1][0] for item in
                index.iter_entries(revision_keys))
            revision_ids = set(revision_ids) - present_revision_ids
            # implementing the TODO will involve:
            # - detecting when all of a pack is selected
            # - avoiding as much as possible pre-selection, so the
            # more-core routines such as create_pack_from_packs can filter in
            # a just-in-time fashion. (though having a HEADS list on a
            # repository might make this a lot easier, because we could
            # sensibly detect 'new revisions' without doing a full index scan.
        elif _mod_revision.is_null(revision_id):
            # nothing to do:
            return (0, [])
        else:
            try:
                revision_ids = self.search_missing_revision_ids(revision_id,
                    find_ghosts=find_ghosts).get_keys()
            except errors.NoSuchRevision:
                raise errors.InstallFailed([revision_id])
            if len(revision_ids) == 0:
                return (0, [])
        packs = self.source._pack_collection.all_packs()
        pack = Packer(self.target._pack_collection, packs, '.fetch',
            revision_ids).pack()
        if pack is not None:
            self.target._pack_collection._save_pack_names()
            # Trigger an autopack. This may duplicate effort as we've just done
            # a pack creation, but for now it is simpler to think about as
            # 'upload data, then repack if needed'.
            self.target._pack_collection.autopack()
            return (pack.get_revision_count(), [])
        else:
            return (0, [])

    @needs_read_lock
    def search_missing_revision_ids(self, revision_id=None, find_ghosts=True):
        """See InterRepository.missing_revision_ids().
        
        :param find_ghosts: Find ghosts throughout the ancestry of
            revision_id.
        """
        if not find_ghosts and revision_id is not None:
            return self._walk_to_common_revisions([revision_id])
        elif revision_id is not None:
            # Find ghosts: search for revisions pointing from one repository to
            # the other, and vice versa, anywhere in the history of revision_id.
            graph = self.target.get_graph(other_repository=self.source)
            searcher = graph._make_breadth_first_searcher([revision_id])
            found_ids = set()
            while True:
                try:
                    next_revs, ghosts = searcher.next_with_ghosts()
                except StopIteration:
                    break
                if revision_id in ghosts:
                    raise errors.NoSuchRevision(self.source, revision_id)
                found_ids.update(next_revs)
                found_ids.update(ghosts)
            found_ids = frozenset(found_ids)
            # Double query here: should be able to avoid this by changing the
            # graph api further.
            result_set = found_ids - frozenset(
                self.target.get_parent_map(found_ids))
        else:
            source_ids = self.source.all_revision_ids()
            # source_ids is the worst possible case we may need to pull.
            # now we want to filter source_ids against what we actually
            # have in target, but don't try to check for existence where we know
            # we do not have a revision as that would be pointless.
            target_ids = set(self.target.all_revision_ids())
            result_set = set(source_ids).difference(target_ids)
        return self.source.revision_ids_to_search_result(result_set)


class InterModel1and2(InterRepository):

    @classmethod
    def _get_repo_format_to_test(self):
        return None

    @staticmethod
    def is_compatible(source, target):
        if not source.supports_rich_root() and target.supports_rich_root():
            return True
        else:
            return False

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import Model1toKnit2Fetcher
        f = Model1toKnit2Fetcher(to_repository=self.target,
                                 from_repository=self.source,
                                 last_revision=revision_id,
                                 pb=pb, find_ghosts=find_ghosts)
        return f.count_copied, f.failed_revisions

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
        # but don't bother fetching if we have the needed data now.
        if (revision_id not in (None, _mod_revision.NULL_REVISION) and 
            self.target.has_revision(revision_id)):
            return
        self.target.fetch(self.source, revision_id=revision_id)


class InterKnit1and2(InterKnitRepo):

    @classmethod
    def _get_repo_format_to_test(self):
        return None

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with Knit1 source and Knit3 target"""
        try:
            from bzrlib.repofmt.knitrepo import (
                RepositoryFormatKnit1,
                RepositoryFormatKnit3,
                )
            from bzrlib.repofmt.pack_repo import (
                RepositoryFormatKnitPack1,
                RepositoryFormatKnitPack3,
                RepositoryFormatKnitPack4,
                RepositoryFormatKnitPack5,
                RepositoryFormatKnitPack5RichRoot,
                RepositoryFormatPackDevelopment0,
                RepositoryFormatPackDevelopment0Subtree,
                RepositoryFormatPackDevelopment1,
                RepositoryFormatPackDevelopment1Subtree,
                )
            norichroot = (
                RepositoryFormatKnit1,            # no rr, no subtree
                RepositoryFormatKnitPack1,        # no rr, no subtree
                RepositoryFormatPackDevelopment0, # no rr, no subtree
                RepositoryFormatPackDevelopment1, # no rr, no subtree
                RepositoryFormatKnitPack5,        # no rr, no subtree
                )
            richroot = (
                RepositoryFormatKnit3,            # rr, subtree
                RepositoryFormatKnitPack3,        # rr, subtree
                RepositoryFormatKnitPack4,        # rr, no subtree
                RepositoryFormatKnitPack5RichRoot,# rr, no subtree
                RepositoryFormatPackDevelopment0Subtree, # rr, subtree
                RepositoryFormatPackDevelopment1Subtree, # rr, subtree
                )
            for format in norichroot:
                if format.rich_root_data:
                    raise AssertionError('Format %s is a rich-root format'
                        ' but is included in the non-rich-root list'
                        % (format,))
            for format in richroot:
                if not format.rich_root_data:
                    raise AssertionError('Format %s is not a rich-root format'
                        ' but is included in the rich-root list'
                        % (format,))
            # TODO: One alternative is to just check format.rich_root_data,
            #       instead of keeping membership lists. However, the formats
            #       *also* have to use the same 'Knit' style of storage
            #       (line-deltas, fulltexts, etc.)
            return (isinstance(source._format, norichroot) and
                    isinstance(target._format, richroot))
        except AttributeError:
            return False

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import Knit1to2Fetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, 
               self.target._format)
        f = Knit1to2Fetcher(to_repository=self.target,
                            from_repository=self.source,
                            last_revision=revision_id,
                            pb=pb, find_ghosts=find_ghosts)
        return f.count_copied, f.failed_revisions


class InterDifferingSerializer(InterKnitRepo):

    @classmethod
    def _get_repo_format_to_test(self):
        return None

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with Knit2 source and Knit3 target"""
        if source.supports_rich_root() != target.supports_rich_root():
            return False
        # Ideally, we'd support fetching if the source had no tree references
        # even if it supported them...
        if (getattr(source, '_format.supports_tree_reference', False) and
            not getattr(target, '_format.supports_tree_reference', False)):
            return False
        return True

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """See InterRepository.fetch()."""
        revision_ids = self.target.search_missing_revision_ids(self.source,
            revision_id, find_ghosts=find_ghosts).get_keys()
        revision_ids = tsort.topo_sort(
            self.source.get_graph().get_parent_map(revision_ids))
        def revisions_iterator():
            for current_revision_id in revision_ids:
                revision = self.source.get_revision(current_revision_id)
                tree = self.source.revision_tree(current_revision_id)
                try:
                    signature = self.source.get_signature_text(
                        current_revision_id)
                except errors.NoSuchRevision:
                    signature = None
                yield revision, tree, signature
        if pb is None:
            my_pb = ui.ui_factory.nested_progress_bar()
            pb = my_pb
        else:
            my_pb = None
        try:
            install_revisions(self.target, revisions_iterator(),
                              len(revision_ids), pb)
        finally:
            if my_pb is not None:
                my_pb.finished()
        return len(revision_ids), 0


class InterOtherToRemote(InterRepository):

    def __init__(self, source, target):
        InterRepository.__init__(self, source, target)
        self._real_inter = None

    @staticmethod
    def is_compatible(source, target):
        if isinstance(target, remote.RemoteRepository):
            return True
        return False

    def _ensure_real_inter(self):
        if self._real_inter is None:
            self.target._ensure_real()
            real_target = self.target._real_repository
            self._real_inter = InterRepository.get(self.source, real_target)
    
    def copy_content(self, revision_id=None):
        self._ensure_real_inter()
        self._real_inter.copy_content(revision_id=revision_id)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        self._ensure_real_inter()
        return self._real_inter.fetch(revision_id=revision_id, pb=pb,
            find_ghosts=find_ghosts)

    @classmethod
    def _get_repo_format_to_test(self):
        return None


class InterRemoteToOther(InterRepository):

    def __init__(self, source, target):
        InterRepository.__init__(self, source, target)
        self._real_inter = None

    @staticmethod
    def is_compatible(source, target):
        if not isinstance(source, remote.RemoteRepository):
            return False
        # Is source's model compatible with target's model?
        source._ensure_real()
        real_source = source._real_repository
        if isinstance(real_source, remote.RemoteRepository):
            raise NotImplementedError(
                "We don't support remote repos backed by remote repos yet.")
        return InterRepository._same_model(real_source, target)

    def _ensure_real_inter(self):
        if self._real_inter is None:
            self.source._ensure_real()
            real_source = self.source._real_repository
            self._real_inter = InterRepository.get(real_source, self.target)
    
    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        self._ensure_real_inter()
        return self._real_inter.fetch(revision_id=revision_id, pb=pb,
            find_ghosts=find_ghosts)

    def copy_content(self, revision_id=None):
        self._ensure_real_inter()
        self._real_inter.copy_content(revision_id=revision_id)

    @classmethod
    def _get_repo_format_to_test(self):
        return None



InterRepository.register_optimiser(InterDifferingSerializer)
InterRepository.register_optimiser(InterSameDataRepository)
InterRepository.register_optimiser(InterWeaveRepo)
InterRepository.register_optimiser(InterKnitRepo)
InterRepository.register_optimiser(InterModel1and2)
InterRepository.register_optimiser(InterKnit1and2)
InterRepository.register_optimiser(InterPackRepo)
InterRepository.register_optimiser(InterOtherToRemote)
InterRepository.register_optimiser(InterRemoteToOther)


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

    def __init__(self, repository):
        self.repository = repository
        self.text_index = self.repository._generate_text_key_index()
    
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
        wrong_parents = {}
        self.file_ids = set([file_id for file_id, _ in
            self.text_index.iterkeys()])
        # text keys is now grouped by file_id
        n_weaves = len(self.file_ids)
        files_in_revisions = {}
        revisions_of_files = {}
        n_versions = len(self.text_index)
        progress_bar.update('loading text store', 0, n_versions)
        parent_map = self.repository.texts.get_parent_map(self.text_index)
        # On unlistable transports this could well be empty/error...
        text_keys = self.repository.texts.keys()
        unused_keys = frozenset(text_keys) - set(self.text_index)
        for num, key in enumerate(self.text_index.iterkeys()):
            if progress_bar is not None:
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

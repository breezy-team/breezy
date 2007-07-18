# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
    deprecated_graph,
    errors,
    generate_ids,
    gpg,
    graph,
    lazy_regex,
    lockable_files,
    lockdir,
    osutils,
    registry,
    remote,
    revision as _mod_revision,
    symbol_versioning,
    transactions,
    ui,
    )
from bzrlib.revisiontree import RevisionTree
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.store.text import TextStore
from bzrlib.testament import Testament

""")

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.inter import InterObject
from bzrlib.inventory import Inventory, InventoryDirectory, ROOT_ID
from bzrlib.symbol_versioning import (
        deprecated_method,
        zero_nine,
        )
from bzrlib.trace import mutter, note, warning


# Old formats display a warning, but only once
_deprecation_warning_done = False


######################################################################
# Repositories

class Repository(object):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    The Repository builds on top of Stores and a Transport, which respectively 
    describe the disk data format and the way of accessing the (possibly 
    remote) disk.
    """

    _file_ids_altered_regex = lazy_regex.lazy_compile(
        r'file_id="(?P<file_id>[^"]+)"'
        r'.*revision="(?P<revision_id>[^"]+)"'
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

    @needs_write_lock
    def add_inventory(self, revision_id, inv, parents):
        """Add the inventory inv to the repository as revision_id.
        
        :param parents: The revision ids of the parents that revision_id
                        is known to have and are in the repository already.

        returns the sha1 of the serialized inventory.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        _mod_revision.check_not_reserved_id(revision_id)
        assert inv.revision_id is None or inv.revision_id == revision_id, \
            "Mismatch between inventory revision" \
            " id and insertion revid (%r, %r)" % (inv.revision_id, revision_id)
        assert inv.root is not None
        inv_text = self.serialise_inventory(inv)
        inv_sha1 = osutils.sha_string(inv_text)
        inv_vf = self.control_weaves.get_weave('inventory',
                                               self.get_transaction())
        self._inventory_add_lines(inv_vf, revision_id, parents,
                                  osutils.split_lines(inv_text))
        return inv_sha1

    def _inventory_add_lines(self, inv_vf, revision_id, parents, lines):
        final_parents = []
        for parent in parents:
            if parent in inv_vf:
                final_parents.append(parent)

        inv_vf.add_lines(revision_id, final_parents, lines)

    @needs_write_lock
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
        revision_id = osutils.safe_revision_id(revision_id)
        # TODO: jam 20070210 Shouldn't we check rev.revision_id and
        #       rev.parent_ids?
        _mod_revision.check_not_reserved_id(revision_id)
        if config is not None and config.signature_needed():
            if inv is None:
                inv = self.get_inventory(revision_id)
            plaintext = Testament(rev, inv).as_short_text()
            self.store_revision_signature(
                gpg.GPGStrategy(config), plaintext, revision_id)
        if not revision_id in self.get_inventory_weave():
            if inv is None:
                raise errors.WeaveRevisionNotPresent(revision_id,
                                                     self.get_inventory_weave())
            else:
                # yes, this is not suitable for adding with ghosts.
                self.add_inventory(revision_id, inv, rev.parent_ids)
        self._revision_store.add_revision(rev, self.get_transaction())

    @needs_read_lock
    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        return self.get_inventory_weave().versions()

    def all_revision_ids(self):
        """Returns a list of all the revision ids in the repository. 

        This is deprecated because code should generally work on the graph
        reachable from a particular revision, and ignore any other revisions
        that might be present.  There is no direct replacement method.
        """
        return self._all_revision_ids()

    @needs_read_lock
    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository. 

        These are in as much topological order as the underlying store can 
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        if self._revision_store.text_store.listable():
            return self._revision_store.all_revision_ids(self.get_transaction())
        result = self._all_possible_ids()
        # TODO: jam 20070210 Ensure that _all_possible_ids returns non-unicode
        #       ids. (It should, since _revision_store's API should change to
        #       return utf8 revision_ids)
        return self._eliminate_revisions_not_present(result)

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
        for id in revision_ids:
            if self.has_revision(id):
               result.append(id)
        return result

    @staticmethod
    def create(a_bzrdir):
        """Construct the current default format repository in a_bzrdir."""
        return RepositoryFormat.get_default_format().initialize(a_bzrdir)

    def __init__(self, _format, a_bzrdir, control_files, _revision_store, control_store, text_store):
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
        self._revision_store = _revision_store
        self.text_store = text_store
        # backwards compatibility
        self.weave_store = text_store
        # not right yet - should be more semantically clear ? 
        # 
        self.control_store = control_store
        self.control_weaves = control_store
        # TODO: make sure to construct the right store classes, etc, depending
        # on whether escaping is required.
        self._warn_if_deprecated()
        self._write_group = None

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, 
                           self.bzrdir.transport.base)

    def is_in_write_group(self):
        """Return True if there is an open write group.

        :seealso: start_write_group.
        """
        return self._write_group is not None

    def is_locked(self):
        return self.control_files.is_locked()

    def lock_write(self, token=None):
        """Lock this repository for writing.
        
        :param token: if this is already locked, then lock_write will fail
            unless the token matches the existing lock.
        :returns: a token if this instance supports tokens, otherwise None.
        :raises TokenLockingNotSupported: when a token is given but this
            instance doesn't support using token locks.
        :raises MismatchedToken: if the specified token doesn't match the token
            of the existing lock.

        A token should be passed in if you know that you have locked the object
        some other way, and need to synchronise this object's state with that
        fact.

        XXX: this docstring is duplicated in many places, e.g. lockable_files.py
        """
        result = self.control_files.lock_write(token=token)
        self._refresh_data()
        return result

    def lock_read(self):
        self.control_files.lock_read()
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
        if self.bzrdir.root_transport.listable():
            c, t = self._revision_store.total_size(self.get_transaction())
            result['revisions'] = c
            result['size'] = t
        return result

    @needs_read_lock
    def missing_revision_ids(self, other, revision_id=None):
        """Return the revision ids that other has that this does not.
        
        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        return InterRepository.get(other, self).missing_revision_ids(revision_id)

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
        revision_id = osutils.safe_revision_id(revision_id)
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

    def fetch(self, source, revision_id=None, pb=None):
        """Fetch the content required to construct revision_id from source.

        If revision_id is None all content is copied.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        inter = InterRepository.get(source, self)
        try:
            return inter.fetch(revision_id=revision_id, pb=pb)
        except NotImplementedError:
            raise errors.IncompatibleRepositories(source, self)

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
        revision_id = osutils.safe_revision_id(revision_id)
        result =_CommitBuilder(self, parents, config, timestamp, timezone,
                              committer, revprops, revision_id)
        self.start_write_group()
        return result

    def unlock(self):
        if (self.control_files._lock_count == 1 and
            self.control_files._lock_mode == 'w'):
            if self._write_group is not None:
                raise errors.BzrError(
                    'Must end write groups before releasing write locks.')
        self.control_files.unlock()

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
        """
        if not self.is_locked() or self.control_files._lock_mode != 'w':
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
        revision_id = osutils.safe_revision_id(revision_id)
        return self._revision_store.has_revision_id(revision_id,
                                                    self.get_transaction())

    @needs_read_lock
    def get_revision_reconcile(self, revision_id):
        """'reconcile' helper routine that allows access to a revision always.
        
        This variant of get_revision does not cross check the weave graph
        against the revision one as get_revision does: but it should only
        be used by reconcile, or reconcile-alike commands that are correcting
        or testing the revision graph.
        """
        if not revision_id or not isinstance(revision_id, basestring):
            raise errors.InvalidRevisionId(revision_id=revision_id,
                                           branch=self)
        return self.get_revisions([revision_id])[0]

    @needs_read_lock
    def get_revisions(self, revision_ids):
        revision_ids = [osutils.safe_revision_id(r) for r in revision_ids]
        revs = self._revision_store.get_revisions(revision_ids,
                                                  self.get_transaction())
        for rev in revs:
            assert not isinstance(rev.revision_id, unicode)
            for parent_id in rev.parent_ids:
                assert not isinstance(parent_id, unicode)
        return revs

    @needs_read_lock
    def get_revision_xml(self, revision_id):
        # TODO: jam 20070210 This shouldn't be necessary since get_revision
        #       would have already do it.
        # TODO: jam 20070210 Just use _serializer.write_revision_to_string()
        revision_id = osutils.safe_revision_id(revision_id)
        rev = self.get_revision(revision_id)
        rev_tmp = StringIO()
        # the current serializer..
        self._revision_store._serializer.write_revision(rev, rev_tmp)
        rev_tmp.seek(0)
        return rev_tmp.getvalue()

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        # TODO: jam 20070210 get_revision_reconcile should do this for us
        revision_id = osutils.safe_revision_id(revision_id)
        r = self.get_revision_reconcile(revision_id)
        # weave corruption can lead to absent revision markers that should be
        # present.
        # the following test is reasonably cheap (it needs a single weave read)
        # and the weave is cached in read transactions. In write transactions
        # it is not cached but typically we only read a small number of
        # revisions. For knits when they are introduced we will probably want
        # to ensure that caching write transactions are in use.
        inv = self.get_inventory_weave()
        self._check_revision_parents(r, inv)
        return r

    @needs_read_lock
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

    def _check_revision_parents(self, revision, inventory):
        """Private to Repository and Fetch.
        
        This checks the parentage of revision in an inventory weave for 
        consistency and is only applicable to inventory-weave-for-ancestry
        using repository formats & fetchers.
        """
        weave_parents = inventory.get_parents(revision.revision_id)
        weave_names = inventory.versions()
        for parent_id in revision.parent_ids:
            if parent_id in weave_names:
                # this parent must not be a ghost.
                if not parent_id in weave_parents:
                    # but it is a ghost
                    raise errors.CorruptRepository(self)

    @needs_write_lock
    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        revision_id = osutils.safe_revision_id(revision_id)
        signature = gpg_strategy.sign(plaintext)
        self._revision_store.add_revision_signature_text(revision_id,
                                                         signature,
                                                         self.get_transaction())

    def fileids_altered_by_revision_ids(self, revision_ids):
        """Find the file ids and versions affected by revisions.

        :param revisions: an iterable containing revision ids.
        :return: a dictionary mapping altered file-ids to an iterable of
        revision_ids. Each altered file-ids has the exact revision_ids that
        altered it listed explicitly.
        """
        assert self._serializer.support_altered_by_hack, \
            ("fileids_altered_by_revision_ids only supported for branches " 
             "which store inventory as unnested xml, not on %r" % self)
        selected_revision_ids = set(osutils.safe_revision_id(r)
                                    for r in revision_ids)
        w = self.get_inventory_weave()
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
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for line in w.iter_lines_added_or_present_in_versions(
                                        selected_revision_ids, pb=pb):
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

                if revision_id in selected_revision_ids:
                    try:
                        file_id = unescape_fileid_cache[file_id]
                    except KeyError:
                        unescaped = unescape(file_id)
                        unescape_fileid_cache[file_id] = unescaped
                        file_id = unescaped
                    setdefault(file_id, set()).add(revision_id)
        finally:
            pb.finished()
        return result

    @needs_read_lock
    def get_inventory_weave(self):
        return self.control_weaves.get_weave('inventory',
            self.get_transaction())

    @needs_read_lock
    def get_inventory(self, revision_id):
        """Get Inventory object by hash."""
        # TODO: jam 20070210 Technically we don't need to sanitize, since all
        #       called functions must sanitize.
        revision_id = osutils.safe_revision_id(revision_id)
        return self.deserialise_inventory(
            revision_id, self.get_inventory_xml(revision_id))

    def deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object. 

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        result = self._serializer.read_inventory_from_string(xml)
        result.root.revision = revision_id
        return result

    def serialise_inventory(self, inv):
        return self._serializer.write_inventory_to_string(inv)

    @needs_read_lock
    def get_inventory_xml(self, revision_id):
        """Get inventory XML as a file object."""
        revision_id = osutils.safe_revision_id(revision_id)
        try:
            assert isinstance(revision_id, str), type(revision_id)
            iw = self.get_inventory_weave()
            return iw.get_text(revision_id)
        except IndexError:
            raise errors.HistoryMissing(self, 'inventory', revision_id)

    @needs_read_lock
    def get_inventory_sha1(self, revision_id):
        """Return the sha1 hash of the inventory entry
        """
        # TODO: jam 20070210 Shouldn't this be deprecated / removed?
        revision_id = osutils.safe_revision_id(revision_id)
        return self.get_revision(revision_id).inventory_sha1

    @needs_read_lock
    def get_revision_graph(self, revision_id=None):
        """Return a dictionary containing the revision graph.
        
        :param revision_id: The revision_id to get a graph from. If None, then
        the entire revision graph is returned. This is a deprecated mode of
        operation and will be removed in the future.
        :return: a dictionary of revision_id->revision_parents_list.
        """
        # special case NULL_REVISION
        if revision_id == _mod_revision.NULL_REVISION:
            return {}
        revision_id = osutils.safe_revision_id(revision_id)
        a_weave = self.get_inventory_weave()
        all_revisions = self._eliminate_revisions_not_present(
                                a_weave.versions())
        entire_graph = dict([(node, a_weave.get_parents(node)) for 
                             node in all_revisions])
        if revision_id is None:
            return entire_graph
        elif revision_id not in entire_graph:
            raise errors.NoSuchRevision(self, revision_id)
        else:
            # add what can be reached from revision_id
            result = {}
            pending = set([revision_id])
            while len(pending) > 0:
                node = pending.pop()
                result[node] = entire_graph[node]
                for revision_id in result[node]:
                    if revision_id not in result:
                        pending.add(revision_id)
            return result

    @needs_read_lock
    def get_revision_graph_with_ghosts(self, revision_ids=None):
        """Return a graph of the revisions with ghosts marked as applicable.

        :param revision_ids: an iterable of revisions to graph or None for all.
        :return: a Graph object with the graph reachable from revision_ids.
        """
        result = deprecated_graph.Graph()
        if not revision_ids:
            pending = set(self.all_revision_ids())
            required = set([])
        else:
            pending = set(osutils.safe_revision_id(r) for r in revision_ids)
            # special case NULL_REVISION
            if _mod_revision.NULL_REVISION in pending:
                pending.remove(_mod_revision.NULL_REVISION)
            required = set(pending)
        done = set([])
        while len(pending):
            revision_id = pending.pop()
            try:
                rev = self.get_revision(revision_id)
            except errors.NoSuchRevision:
                if revision_id in required:
                    raise
                # a ghost
                result.add_ghost(revision_id)
                continue
            for parent_id in rev.parent_ids:
                # is this queued or done ?
                if (parent_id not in pending and
                    parent_id not in done):
                    # no, queue it.
                    pending.add(parent_id)
            result.add_node(revision_id, rev.parent_ids)
            done.add(revision_id)
        return result

    def _get_history_vf(self):
        """Get a versionedfile whose history graph reflects all revisions.

        For weave repositories, this is the inventory weave.
        """
        return self.get_inventory_weave()

    def iter_reverse_revision_history(self, revision_id):
        """Iterate backwards through revision ids in the lefthand history

        :param revision_id: The revision id to start with.  All its lefthand
            ancestors will be traversed.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        if revision_id in (None, _mod_revision.NULL_REVISION):
            return
        next_id = revision_id
        versionedfile = self._get_history_vf()
        while True:
            yield next_id
            parents = versionedfile.get_parents(next_id)
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

    @needs_read_lock
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
            revision_id = osutils.safe_revision_id(revision_id)
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self, inv, revision_id)

    @needs_read_lock
    def revision_trees(self, revision_ids):
        """Return Tree for a revision on this branch.

        `revision_id` may not be None or 'null:'"""
        assert None not in revision_ids
        assert _mod_revision.NULL_REVISION not in revision_ids
        texts = self.get_inventory_weave().get_texts(revision_ids)
        for text, revision_id in zip(texts, revision_ids):
            inv = self.deserialise_inventory(revision_id, text)
            yield RevisionTree(self, inv, revision_id)

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
        revision_id = osutils.safe_revision_id(revision_id)
        if not self.has_revision(revision_id):
            raise errors.NoSuchRevision(self, revision_id)
        w = self.get_inventory_weave()
        candidates = w.get_ancestry(revision_id, topo_sorted)
        return [None] + candidates # self._eliminate_revisions_not_present(candidates)

    def pack(self):
        """Compress the data within the repository.

        This operation only makes sense for some repository types. For other
        types it should be a no-op that just returns.

        This stub method does not require a lock, but subclasses should use
        @needs_write_lock as this is a long running call its reasonable to 
        implicitly lock for the user.
        """

    @needs_read_lock
    def print_file(self, file, revision_id):
        """Print `file` to stdout.
        
        FIXME RBC 20060125 as John Meinel points out this is a bad api
        - it writes to stdout, it assumes that that is valid etc. Fix
        by creating a new more flexible convenience function.
        """
        revision_id = osutils.safe_revision_id(revision_id)
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

    def revision_parents(self, revision_id):
        revision_id = osutils.safe_revision_id(revision_id)
        return self.get_inventory_weave().parent_names(revision_id)

    def get_parents(self, revision_ids):
        """See StackedParentsProvider.get_parents"""
        parents_list = []
        for revision_id in revision_ids:
            if revision_id == _mod_revision.NULL_REVISION:
                parents = []
            else:
                try:
                    parents = self.get_revision(revision_id).parent_ids
                except errors.NoSuchRevision:
                    parents = None
                else:
                    if len(parents) == 0:
                        parents = [_mod_revision.NULL_REVISION]
            parents_list.append(parents)
        return parents_list

    def _make_parents_provider(self):
        return self

    def get_graph(self, other_repository=None):
        """Return the graph walker for this repository format"""
        parents_provider = self._make_parents_provider()
        if (other_repository is not None and
            other_repository.bzrdir.transport.base !=
            self.bzrdir.transport.base):
            parents_provider = graph._StackedParentsProvider(
                [parents_provider, other_repository._make_parents_provider()])
        return graph.Graph(parents_provider)

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
        revision_id = osutils.safe_revision_id(revision_id)
        plaintext = Testament.from_revision(self, revision_id).as_short_text()
        self.store_revision_signature(gpg_strategy, plaintext, revision_id)

    @needs_read_lock
    def has_signature_for_revision_id(self, revision_id):
        """Query for a revision signature for revision_id in the repository."""
        revision_id = osutils.safe_revision_id(revision_id)
        return self._revision_store.has_signature(revision_id,
                                                  self.get_transaction())

    @needs_read_lock
    def get_signature_text(self, revision_id):
        """Return the text for a signature."""
        revision_id = osutils.safe_revision_id(revision_id)
        return self._revision_store.get_signature_text(revision_id,
                                                       self.get_transaction())

    @needs_read_lock
    def check(self, revision_ids):
        """Check consistency of all history of given revision_ids.

        Different repository implementations should override _check().

        :param revision_ids: A non-empty list of revision_ids whose ancestry
             will be checked.  Typically the last revision_id of a branch.
        """
        if not revision_ids:
            raise ValueError("revision_ids must be non-empty in %s.check" 
                    % (self,))
        revision_ids = [osutils.safe_revision_id(r) for r in revision_ids]
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
    # backwards compatability hack: skip the root id.
    if not repository.supports_rich_root():
        path, root = entries.next()
        if root.revision != rev.revision_id:
            raise errors.IncompatibleRevision(repr(repository))
    # Add the texts that are not already present
    for path, ie in entries:
        w = repository.weave_store.get_weave_or_empty(ie.file_id,
                repository.get_transaction())
        if ie.revision not in w:
            text_parents = []
            # FIXME: TODO: The following loop *may* be overlapping/duplicate
            # with InventoryEntry.find_previous_heads(). if it is, then there
            # is a latent bug here where the parents may have ancestors of each
            # other. RBC, AB
            for revision, tree in parent_trees.iteritems():
                if ie.file_id not in tree:
                    continue
                parent_id = tree.inventory[ie.file_id].revision
                if parent_id in text_parents:
                    continue
                text_parents.append(parent_id)
                    
            vfile = repository.weave_store.get_weave_or_empty(ie.file_id, 
                repository.get_transaction())
            lines = revision_tree.get_file(ie.file_id).readlines()
            vfile.add_lines(rev.revision_id, text_parents, lines)
    try:
        # install the inventory
        repository.add_inventory(rev.revision_id, inv, present_parents)
    except errors.RevisionAlreadyPresent:
        pass
    repository.add_revision(rev.revision_id, rev, inv)


class MetaDirRepository(Repository):
    """Repositories in the new meta-dir layout."""

    def __init__(self, _format, a_bzrdir, control_files, _revision_store, control_store, text_store):
        super(MetaDirRepository, self).__init__(_format,
                                                a_bzrdir,
                                                control_files,
                                                _revision_store,
                                                control_store,
                                                text_store)
        dir_mode = self.control_files._dir_mode
        file_mode = self.control_files._file_mode

    @needs_read_lock
    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return self.control_files._transport.has('shared-storage')

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
                self.control_files._transport.delete('no-working-trees')
            except errors.NoSuchFile:
                pass
        else:
            self.control_files.put_utf8('no-working-trees', '')
    
    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        return not self.control_files._transport.has('no-working-trees')


class RepositoryFormatRegistry(registry.Registry):
    """Registry of RepositoryFormats.
    """

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
    parameterisation.
    """

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
            raise errors.UnknownFormatError(format=format_string)

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

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        raise NotImplementedError(self._get_control_store)

    def get_format_string(self):
        """Return the ASCII format string that identifies this format.
        
        Note that in pre format ?? repositories the format string is 
        not permitted nor written to disk.
        """
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def _get_revision_store(self, repo_transport, control_files):
        """Return the revision store object for this a_bzrdir."""
        raise NotImplementedError(self._get_revision_store)

    def _get_text_rev_store(self,
                            transport,
                            control_files,
                            name,
                            compressed=True,
                            prefixed=False,
                            serializer=None):
        """Common logic for getting a revision store for a repository.
        
        see self._get_revision_store for the subclass-overridable method to 
        get the store for a repository.
        """
        from bzrlib.store.revision.text import TextRevisionStore
        dir_mode = control_files._dir_mode
        file_mode = control_files._file_mode
        text_store = TextStore(transport.clone(name),
                              prefixed=prefixed,
                              compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode)
        _revision_store = TextRevisionStore(text_store, serializer)
        return _revision_store

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
        try:
            control_files._transport.mkdir_multi(dirs,
                    mode=control_files._dir_mode)
            for file, content in files:
                control_files.put(file, content)
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
            if shared == True:
                control_files.put_utf8('shared-storage', '')
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

# KEEP in sync with bzrdir.format_registry default, which controls the overall
# default control directory format
format_registry.register_lazy(
    'Bazaar-NG Knit Repository Format 1',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit1',
    )
format_registry.default_key = 'Bazaar-NG Knit Repository Format 1'

format_registry.register_lazy(
    'Bazaar Knit Repository Format 3 (bzr 0.15)\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit3',
    )

# Experimental formats. These make no guarantee about data stability.
# There is one format for pre-subtrees, and one for post-subtrees to
# allow ease of testing.
format_registry.register_lazy(
    'Bazaar Experimental no-subtrees\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatGraphKnit1',
    )
format_registry.register_lazy(
    'Bazaar Experimental subtrees\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatGraphKnit3',
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

    _optimisers = []
    """The available optimised InterRepository types."""

    def copy_content(self, revision_id=None):
        raise NotImplementedError(self.copy_content)

    def fetch(self, revision_id=None, pb=None):
        """Fetch the content required to construct revision_id.

        The content is copied from self.source to self.target.

        :param revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        :param pb: optional progress bar to use for progress reports. If not
                   provided a default one will be created.

        Returns the copied revision count and the failed revisions in a tuple:
        (copied, failures).
        """
        raise NotImplementedError(self.fetch)
   
    @needs_read_lock
    def missing_revision_ids(self, revision_id=None):
        """Return the revision ids that source has that target does not.
        
        These are returned in topological order.

        :param revision_id: only return revision ids included by this
                            revision_id.
        """
        # generic, possibly worst case, slow code path.
        target_ids = set(self.target.all_revision_ids())
        if revision_id is not None:
            # TODO: jam 20070210 InterRepository is internal enough that it
            #       should assume revision_ids are already utf-8
            revision_id = osutils.safe_revision_id(revision_id)
            source_ids = self.source.get_ancestry(revision_id)
            assert source_ids[0] is None
            source_ids.pop(0)
        else:
            source_ids = self.source.all_revision_ids()
        result_set = set(source_ids).difference(target_ids)
        # this may look like a no-op: its not. It preserves the ordering
        # other_ids had while only returning the members from other_ids
        # that we've decided we need.
        return [rev_id for rev_id in source_ids if rev_id in result_set]

    @staticmethod
    def _same_model(source, target):
        """True if source and target have the same data representation."""
        if source.supports_rich_root() != target.supports_rich_root():
            return False
        if source._serializer != target._serializer:
            return False
        return True


class InterSameDataRepository(InterRepository):
    """Code for converting between repositories that represent the same data.
    
    Data format and model must match for this to work.
    """

    @classmethod
    def _get_repo_format_to_test(self):
        """Repository format for testing with."""
        return RepositoryFormat.get_default_format()

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
        # TODO: jam 20070210 This is fairly internal, so we should probably
        #       just assert that revision_id is not unicode.
        revision_id = osutils.safe_revision_id(revision_id)
        # but don't bother fetching if we have the needed data now.
        if (revision_id not in (None, _mod_revision.NULL_REVISION) and 
            self.target.has_revision(revision_id)):
            return
        self.target.fetch(self.source, revision_id=revision_id)

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import GenericRepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, 
               self.target._format)
        # TODO: jam 20070210 This should be an assert, not a translate
        revision_id = osutils.safe_revision_id(revision_id)
        f = GenericRepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               pb=pb)
        return f.count_copied, f.failed_revisions


class InterWeaveRepo(InterSameDataRepository):
    """Optimised code paths between Weave based repositories."""

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
        # TODO: jam 20070210 Internal, should be an assert, not translate
        revision_id = osutils.safe_revision_id(revision_id)
        try:
            self.target.set_make_working_trees(self.source.make_working_trees())
        except NotImplementedError:
            pass
        # FIXME do not peek!
        if self.source.control_files._transport.listable():
            pb = ui.ui_factory.nested_progress_bar()
            try:
                self.target.weave_store.copy_all_ids(
                    self.source.weave_store,
                    pb=pb,
                    from_transaction=self.source.get_transaction(),
                    to_transaction=self.target.get_transaction())
                pb.update('copying inventory', 0, 1)
                self.target.control_weaves.copy_multi(
                    self.source.control_weaves, ['inventory'],
                    from_transaction=self.source.get_transaction(),
                    to_transaction=self.target.get_transaction())
                self.target._revision_store.text_store.copy_all_ids(
                    self.source._revision_store.text_store,
                    pb=pb)
            finally:
                pb.finished()
        else:
            self.target.fetch(self.source, revision_id=revision_id)

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import GenericRepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, self.target._format)
        # TODO: jam 20070210 This should be an assert, not a translate
        revision_id = osutils.safe_revision_id(revision_id)
        f = GenericRepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               pb=pb)
        return f.count_copied, f.failed_revisions

    @needs_read_lock
    def missing_revision_ids(self, revision_id=None):
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
            assert source_ids[0] is None
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
        actually_present_revisions = set(self.target._eliminate_revisions_not_present(possibly_present_revisions))
        required_revisions = source_ids_set.difference(actually_present_revisions)
        required_topo_revisions = [rev_id for rev_id in source_ids if rev_id in required_revisions]
        if revision_id is not None:
            # we used get_ancestry to determine source_ids then we are assured all
            # revisions referenced are present as they are installed in topological order.
            # and the tip revision was validated by get_ancestry.
            return required_topo_revisions
        else:
            # if we just grabbed the possibly available ids, then 
            # we only have an estimate of whats available and need to validate
            # that against the revision records.
            return self.source._eliminate_revisions_not_present(required_topo_revisions)


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
    def fetch(self, revision_id=None, pb=None):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import KnitRepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, self.target._format)
        # TODO: jam 20070210 This should be an assert, not a translate
        revision_id = osutils.safe_revision_id(revision_id)
        f = KnitRepoFetcher(to_repository=self.target,
                            from_repository=self.source,
                            last_revision=revision_id,
                            pb=pb)
        return f.count_copied, f.failed_revisions

    @needs_read_lock
    def missing_revision_ids(self, revision_id=None):
        """See InterRepository.missing_revision_ids()."""
        if revision_id is not None:
            source_ids = self.source.get_ancestry(revision_id)
            assert source_ids[0] is None
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
        actually_present_revisions = set(self.target._eliminate_revisions_not_present(possibly_present_revisions))
        required_revisions = source_ids_set.difference(actually_present_revisions)
        required_topo_revisions = [rev_id for rev_id in source_ids if rev_id in required_revisions]
        if revision_id is not None:
            # we used get_ancestry to determine source_ids then we are assured all
            # revisions referenced are present as they are installed in topological order.
            # and the tip revision was validated by get_ancestry.
            return required_topo_revisions
        else:
            # if we just grabbed the possibly available ids, then 
            # we only have an estimate of whats available and need to validate
            # that against the revision records.
            return self.source._eliminate_revisions_not_present(required_topo_revisions)


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
    def fetch(self, revision_id=None, pb=None):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import Model1toKnit2Fetcher
        # TODO: jam 20070210 This should be an assert, not a translate
        revision_id = osutils.safe_revision_id(revision_id)
        f = Model1toKnit2Fetcher(to_repository=self.target,
                                 from_repository=self.source,
                                 last_revision=revision_id,
                                 pb=pb)
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
        # TODO: jam 20070210 Internal, assert, don't translate
        revision_id = osutils.safe_revision_id(revision_id)
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
        from bzrlib.repofmt.knitrepo import RepositoryFormatKnit3
        try:
            from bzrlib.repofmt.knitrepo import RepositoryFormatKnit1, \
                    RepositoryFormatKnit3
            return (isinstance(source._format, (RepositoryFormatKnit1)) and
                    isinstance(target._format, (RepositoryFormatKnit3)))
        except AttributeError:
            return False

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import Knit1to2Fetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, 
               self.target._format)
        # TODO: jam 20070210 This should be an assert, not a translate
        revision_id = osutils.safe_revision_id(revision_id)
        f = Knit1to2Fetcher(to_repository=self.target,
                            from_repository=self.source,
                            last_revision=revision_id,
                            pb=pb)
        return f.count_copied, f.failed_revisions


class InterRemoteRepository(InterRepository):
    """Code for converting between RemoteRepository objects.

    This just gets an non-remote repository from the RemoteRepository, and calls
    InterRepository.get again.
    """

    def __init__(self, source, target):
        if isinstance(source, remote.RemoteRepository):
            source._ensure_real()
            real_source = source._real_repository
        else:
            real_source = source
        if isinstance(target, remote.RemoteRepository):
            target._ensure_real()
            real_target = target._real_repository
        else:
            real_target = target
        self.real_inter = InterRepository.get(real_source, real_target)

    @staticmethod
    def is_compatible(source, target):
        if isinstance(source, remote.RemoteRepository):
            return True
        if isinstance(target, remote.RemoteRepository):
            return True
        return False

    def copy_content(self, revision_id=None):
        self.real_inter.copy_content(revision_id=revision_id)

    def fetch(self, revision_id=None, pb=None):
        self.real_inter.fetch(revision_id=revision_id, pb=pb)

    @classmethod
    def _get_repo_format_to_test(self):
        return None


InterRepository.register_optimiser(InterSameDataRepository)
InterRepository.register_optimiser(InterWeaveRepo)
InterRepository.register_optimiser(InterKnitRepo)
InterRepository.register_optimiser(InterModel1and2)
InterRepository.register_optimiser(InterKnit1and2)
InterRepository.register_optimiser(InterRemoteRepository)


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


class CommitBuilder(object):
    """Provides an interface to build up a commit.

    This allows describing a tree to be committed without needing to 
    know the internals of the format of the repository.
    """
    
    record_root_entry = False
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
            assert isinstance(committer, basestring), type(committer)
            self._committer = committer

        self.new_inventory = Inventory(None)
        self._new_revision_id = osutils.safe_revision_id(revision_id)
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
            symbol_versioning.warn('Root entry should be supplied to'
                ' record_entry_contents, as of bzr 0.10.',
                 DeprecationWarning, stacklevel=2)
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

    def record_entry_contents(self, ie, parent_invs, path, tree):
        """Record the content of ie from tree into the commit if needed.

        Side effect: sets ie.revision when unchanged

        :param ie: An inventory entry present in the commit.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param path: The path the entry is at in the tree.
        :param tree: The tree which contains this entry and should be used to 
        obtain content.
        """
        if self.new_inventory.root is None and ie.parent_id is not None:
            symbol_versioning.warn('Root entry should be supplied to'
                ' record_entry_contents, as of bzr 0.10.',
                 DeprecationWarning, stacklevel=2)
            self.record_entry_contents(tree.inventory.root.copy(), parent_invs,
                                       '', tree)
        self.new_inventory.add(ie)

        # ie.revision is always None if the InventoryEntry is considered
        # for committing. ie.snapshot will record the correct revision 
        # which may be the sole parent if it is untouched.
        if ie.revision is not None:
            return

        # In this revision format, root entries have no knit or weave
        if ie is self.new_inventory.root:
            # When serializing out to disk and back in
            # root.revision is always _new_revision_id
            ie.revision = self._new_revision_id
            return
        previous_entries = ie.find_previous_heads(
            parent_invs,
            self.repository.weave_store,
            self.repository.get_transaction())
        # we are creating a new revision for ie in the history store
        # and inventory.
        ie.snapshot(self._new_revision_id, path, previous_entries, tree, self)

    def modified_directory(self, file_id, file_parents):
        """Record the presence of a symbolic link.

        :param file_id: The file_id of the link to record.
        :param file_parents: The per-file parent revision ids.
        """
        self._add_text_to_weave(file_id, [], file_parents.keys())

    def modified_reference(self, file_id, file_parents):
        """Record the modification of a reference.

        :param file_id: The file_id of the link to record.
        :param file_parents: The per-file parent revision ids.
        """
        self._add_text_to_weave(file_id, [], file_parents.keys())
    
    def modified_file_text(self, file_id, file_parents,
                           get_content_byte_lines, text_sha1=None,
                           text_size=None):
        """Record the text of file file_id

        :param file_id: The file_id of the file to record the text of.
        :param file_parents: The per-file parent revision ids.
        :param get_content_byte_lines: A callable which will return the byte
            lines for the file.
        :param text_sha1: Optional SHA1 of the file contents.
        :param text_size: Optional size of the file contents.
        """
        # mutter('storing text of file {%s} in revision {%s} into %r',
        #        file_id, self._new_revision_id, self.repository.weave_store)
        # special case to avoid diffing on renames or 
        # reparenting
        if (len(file_parents) == 1
            and text_sha1 == file_parents.values()[0].text_sha1
            and text_size == file_parents.values()[0].text_size):
            previous_ie = file_parents.values()[0]
            versionedfile = self.repository.weave_store.get_weave(file_id, 
                self.repository.get_transaction())
            versionedfile.clone_text(self._new_revision_id, 
                previous_ie.revision, file_parents.keys())
            return text_sha1, text_size
        else:
            new_lines = get_content_byte_lines()
            # TODO: Rather than invoking sha_strings here, _add_text_to_weave
            # should return the SHA1 and size
            self._add_text_to_weave(file_id, new_lines, file_parents.keys())
            return osutils.sha_strings(new_lines), \
                sum(map(len, new_lines))

    def modified_link(self, file_id, file_parents, link_target):
        """Record the presence of a symbolic link.

        :param file_id: The file_id of the link to record.
        :param file_parents: The per-file parent revision ids.
        :param link_target: Target location of this link.
        """
        self._add_text_to_weave(file_id, [], file_parents.keys())

    def _add_text_to_weave(self, file_id, new_lines, parents):
        versionedfile = self.repository.weave_store.get_weave_or_empty(
            file_id, self.repository.get_transaction())
        versionedfile.add_lines(self._new_revision_id, parents, new_lines)
        versionedfile.clear_cache()


class _CommitBuilder(CommitBuilder):
    """Temporary class so old CommitBuilders are detected properly
    
    Note: CommitBuilder works whether or not root entry is recorded.
    """

    record_root_entry = True


class RootCommitBuilder(CommitBuilder):
    """This commitbuilder actually records the root id"""
    
    record_root_entry = True

    def record_entry_contents(self, ie, parent_invs, path, tree):
        """Record the content of ie from tree into the commit if needed.

        Side effect: sets ie.revision when unchanged

        :param ie: An inventory entry present in the commit.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param path: The path the entry is at in the tree.
        :param tree: The tree which contains this entry and should be used to 
        obtain content.
        """
        assert self.new_inventory.root is not None or ie.parent_id is None
        self.new_inventory.add(ie)

        # ie.revision is always None if the InventoryEntry is considered
        # for committing. ie.snapshot will record the correct revision 
        # which may be the sole parent if it is untouched.
        if ie.revision is not None:
            return

        previous_entries = ie.find_previous_heads(
            parent_invs,
            self.repository.weave_store,
            self.repository.get_transaction())
        # we are creating a new revision for ie in the history store
        # and inventory.
        ie.snapshot(self._new_revision_id, path, previous_entries, tree, self)


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

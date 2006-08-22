# Copyright (C) 2005, 2006 Canonical Ltd
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

from binascii import hexlify
from copy import deepcopy
from cStringIO import StringIO
import re
import time
from unittest import TestSuite

from bzrlib import bzrdir, check, delta, gpg, errors, xml5, ui, transactions, osutils
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.errors import InvalidRevisionId
from bzrlib.graph import Graph
from bzrlib.inter import InterObject
from bzrlib.inventory import Inventory, InventoryDirectory, ROOT_ID
from bzrlib.knit import KnitVersionedFile, KnitPlainFactory
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.lockdir import LockDir
from bzrlib.osutils import (safe_unicode, rand_bytes, compact_date, 
                            local_time_offset)
from bzrlib.revision import NULL_REVISION, Revision
from bzrlib.revisiontree import RevisionTree
from bzrlib.store.versioned import VersionedFileStore, WeaveStore
from bzrlib.store.text import TextStore
from bzrlib import symbol_versioning
from bzrlib.symbol_versioning import (deprecated_method,
        zero_nine, 
        )
from bzrlib.testament import Testament
from bzrlib.trace import mutter, note, warning
from bzrlib.tsort import topo_sort
from bzrlib.weave import WeaveFile


# Old formats display a warning, but only once
_deprecation_warning_done = False


class Repository(object):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    The Repository builds on top of Stores and a Transport, which respectively 
    describe the disk data format and the way of accessing the (possibly 
    remote) disk.
    """

    @needs_write_lock
    def add_inventory(self, revid, inv, parents):
        """Add the inventory inv to the repository as revid.
        
        :param parents: The revision ids of the parents that revid
                        is known to have and are in the repository already.

        returns the sha1 of the serialized inventory.
        """
        assert inv.revision_id is None or inv.revision_id == revid, \
            "Mismatch between inventory revision" \
            " id and insertion revid (%r, %r)" % (inv.revision_id, revid)
        assert inv.root is not None
        inv_text = xml5.serializer_v5.write_inventory_to_string(inv)
        inv_sha1 = osutils.sha_string(inv_text)
        inv_vf = self.control_weaves.get_weave('inventory',
                                               self.get_transaction())
        self._inventory_add_lines(inv_vf, revid, parents, osutils.split_lines(inv_text))
        return inv_sha1

    def _inventory_add_lines(self, inv_vf, revid, parents, lines):
        final_parents = []
        for parent in parents:
            if parent in inv_vf:
                final_parents.append(parent)

        inv_vf.add_lines(revid, final_parents, lines)

    @needs_write_lock
    def add_revision(self, rev_id, rev, inv=None, config=None):
        """Add rev to the revision store as rev_id.

        :param rev_id: the revision id to use.
        :param rev: The revision object.
        :param inv: The inventory for the revision. if None, it will be looked
                    up in the inventory storer
        :param config: If None no digital signature will be created.
                       If supplied its signature_needed method will be used
                       to determine if a signature should be made.
        """
        if config is not None and config.signature_needed():
            if inv is None:
                inv = self.get_inventory(rev_id)
            plaintext = Testament(rev, inv).as_short_text()
            self.store_revision_signature(
                gpg.GPGStrategy(config), plaintext, rev_id)
        if not rev_id in self.get_inventory_weave():
            if inv is None:
                raise errors.WeaveRevisionNotPresent(rev_id,
                                                     self.get_inventory_weave())
            else:
                # yes, this is not suitable for adding with ghosts.
                self.add_inventory(rev_id, inv, rev.parent_ids)
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

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, 
                           self.bzrdir.transport.base)

    def is_locked(self):
        return self.control_files.is_locked()

    def lock_write(self):
        self.control_files.lock_write()

    def lock_read(self):
        self.control_files.lock_read()

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    @needs_read_lock
    def missing_revision_ids(self, other, revision_id=None):
        """Return the revision ids that other has that this does not.
        
        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        return InterRepository.get(other, self).missing_revision_ids(revision_id)

    @staticmethod
    def open(base):
        """Open the repository rooted at base.

        For instance, if the repository is at URL/.bzr/repository,
        Repository.open(URL) -> a Repository instance.
        """
        control = bzrdir.BzrDir.open(base)
        return control.open_repository()

    def copy_content_into(self, destination, revision_id=None, basis=None):
        """Make a complete copy of the content in self into destination.
        
        This is a destructive operation! Do not use it on existing 
        repositories.
        """
        return InterRepository.get(self, destination).copy_content(revision_id, basis)

    def fetch(self, source, revision_id=None, pb=None):
        """Fetch the content required to construct revision_id from source.

        If revision_id is None all content is copied.
        """
        return InterRepository.get(source, self).fetch(revision_id=revision_id,
                                                       pb=pb)

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
        return _CommitBuilder(self, parents, config, timestamp, timezone,
                              committer, revprops, revision_id)

    def unlock(self):
        self.control_files.unlock()

    @needs_read_lock
    def clone(self, a_bzrdir, revision_id=None, basis=None):
        """Clone this repository into a_bzrdir using the current format.

        Currently no check is made that the format of this repository and
        the bzrdir format are compatible. FIXME RBC 20060201.
        """
        if not isinstance(a_bzrdir._format, self.bzrdir._format.__class__):
            # use target default format.
            result = a_bzrdir.create_repository()
        # FIXME RBC 20060209 split out the repository type to avoid this check ?
        elif isinstance(a_bzrdir._format,
                      (bzrdir.BzrDirFormat4,
                       bzrdir.BzrDirFormat5,
                       bzrdir.BzrDirFormat6)):
            result = a_bzrdir.open_repository()
        else:
            result = self._format.initialize(a_bzrdir, shared=self.is_shared())
        self.copy_content_into(result, revision_id, basis)
        return result

    @needs_read_lock
    def has_revision(self, revision_id):
        """True if this repository has a copy of the revision."""
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
            raise InvalidRevisionId(revision_id=revision_id, branch=self)
        return self._revision_store.get_revisions([revision_id],
                                                  self.get_transaction())[0]
    @needs_read_lock
    def get_revisions(self, revision_ids):
        return self._revision_store.get_revisions(revision_ids,
                                                  self.get_transaction())

    @needs_read_lock
    def get_revision_xml(self, revision_id):
        rev = self.get_revision(revision_id) 
        rev_tmp = StringIO()
        # the current serializer..
        self._revision_store._serializer.write_revision(rev, rev_tmp)
        rev_tmp.seek(0)
        return rev_tmp.getvalue()

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
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
        assert self._format.has_unnested_inventory(), \
            ("fileids_altered_by_revision_ids only supported for branches " 
             "which store inventory as unnested xml, not on %r" % self)
        selected_revision_ids = set(revision_ids)
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
        for line in w.iter_lines_added_or_present_in_versions(selected_revision_ids):
            start = line.find('file_id="')+9
            if start < 9: continue
            end = line.find('"', start)
            assert end>= 0
            file_id = _unescape_xml(line[start:end])

            start = line.find('revision="')+10
            if start < 10: continue
            end = line.find('"', start)
            assert end>= 0
            revision_id = _unescape_xml(line[start:end])
            if revision_id in selected_revision_ids:
                result.setdefault(file_id, set()).add(revision_id)
        return result

    @needs_read_lock
    def get_inventory_weave(self):
        return self.control_weaves.get_weave('inventory',
            self.get_transaction())

    @needs_read_lock
    def get_inventory(self, revision_id):
        """Get Inventory object by hash."""
        return self.deserialise_inventory(
            revision_id, self.get_inventory_xml(revision_id))

    def deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object. 

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        result = xml5.serializer_v5.read_inventory_from_string(xml)
        result.root.revision = revision_id
        return result

    @needs_read_lock
    def get_inventory_xml(self, revision_id):
        """Get inventory XML as a file object."""
        try:
            assert isinstance(revision_id, basestring), type(revision_id)
            iw = self.get_inventory_weave()
            return iw.get_text(revision_id)
        except IndexError:
            raise errors.HistoryMissing(self, 'inventory', revision_id)

    @needs_read_lock
    def get_inventory_sha1(self, revision_id):
        """Return the sha1 hash of the inventory entry
        """
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
        if revision_id == NULL_REVISION:
            return {}
        weave = self.get_inventory_weave()
        all_revisions = self._eliminate_revisions_not_present(weave.versions())
        entire_graph = dict([(node, weave.get_parents(node)) for 
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
        result = Graph()
        if not revision_ids:
            pending = set(self.all_revision_ids())
            required = set([])
        else:
            pending = set(revision_ids)
            # special case NULL_REVISION
            if NULL_REVISION in pending:
                pending.remove(NULL_REVISION)
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
    
    @needs_read_lock
    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the empty tree revision.
        """
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id is None or revision_id == NULL_REVISION:
            return RevisionTree(self, Inventory(), NULL_REVISION)
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self, inv, revision_id)

    @needs_read_lock
    def revision_trees(self, revision_ids):
        """Return Tree for a revision on this branch.

        `revision_id` may not be None or 'null:'"""
        assert None not in revision_ids
        assert NULL_REVISION not in revision_ids
        texts = self.get_inventory_weave().get_texts(revision_ids)
        for text, revision_id in zip(texts, revision_ids):
            inv = self.deserialise_inventory(revision_id, text)
            yield RevisionTree(self, inv, revision_id)

    @needs_read_lock
    def get_ancestry(self, revision_id):
        """Return a list of revision-ids integrated by a revision.

        The first element of the list is always None, indicating the origin 
        revision.  This might change when we have history horizons, or 
        perhaps we should have a new API.
        
        This is topologically sorted.
        """
        if revision_id is None:
            return [None]
        if not self.has_revision(revision_id):
            raise errors.NoSuchRevision(self, revision_id)
        w = self.get_inventory_weave()
        candidates = w.get_ancestry(revision_id)
        return [None] + candidates # self._eliminate_revisions_not_present(candidates)

    @needs_read_lock
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

    def revision_parents(self, revid):
        return self.get_inventory_weave().parent_names(revid)

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
        return self._revision_store.has_signature(revision_id,
                                                  self.get_transaction())

    @needs_read_lock
    def get_signature_text(self, revision_id):
        """Return the text for a signature."""
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


class AllInOneRepository(Repository):
    """Legacy support - the repository behaviour for all-in-one branches."""

    def __init__(self, _format, a_bzrdir, _revision_store, control_store, text_store):
        # we reuse one control files instance.
        dir_mode = a_bzrdir._control_files._dir_mode
        file_mode = a_bzrdir._control_files._file_mode

        def get_store(name, compressed=True, prefixed=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from 
            # some existing branches where there's a mixture; we probably 
            # still want the option to look for both.
            relpath = a_bzrdir._control_files._escape(name)
            store = TextStore(a_bzrdir._control_files._transport.clone(relpath),
                              prefixed=prefixed, compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode)
            #if self._transport.should_cache():
            #    cache_path = os.path.join(self.cache_root, name)
            #    os.mkdir(cache_path)
            #    store = bzrlib.store.CachedStore(store, cache_path)
            return store

        # not broken out yet because the controlweaves|inventory_store
        # and text_store | weave_store bits are still different.
        if isinstance(_format, RepositoryFormat4):
            # cannot remove these - there is still no consistent api 
            # which allows access to this old info.
            self.inventory_store = get_store('inventory-store')
            text_store = get_store('text-store')
        super(AllInOneRepository, self).__init__(_format, a_bzrdir, a_bzrdir._control_files, _revision_store, control_store, text_store)

    @needs_read_lock
    def is_shared(self):
        """AllInOne repositories cannot be shared."""
        return False

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
        return True


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
    
    # backwards compatability hack: skip the root id.
    entries = inv.iter_entries()
    entries.next()
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


class KnitRepository(MetaDirRepository):
    """Knit format repository."""

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def _inventory_add_lines(self, inv_vf, revid, parents, lines):
        inv_vf.add_lines_with_ghosts(revid, parents, lines)

    @needs_read_lock
    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        # Knits get the revision graph from the index of the revision knit, so
        # it's always possible even if they're on an unlistable transport.
        return self._revision_store.all_revision_ids(self.get_transaction())

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """Find file_id(s) which are involved in the changes between revisions.

        This determines the set of revisions which are involved, and then
        finds all file ids affected by those revisions.
        """
        vf = self._get_revision_vf()
        from_set = set(vf.get_ancestry(from_revid))
        to_set = set(vf.get_ancestry(to_revid))
        changed = to_set.difference(from_set)
        return self._fileid_involved_by_set(changed)

    def fileid_involved(self, last_revid=None):
        """Find all file_ids modified in the ancestry of last_revid.

        :param last_revid: If None, last_revision() will be used.
        """
        if not last_revid:
            changed = set(self.all_revision_ids())
        else:
            changed = set(self.get_ancestry(last_revid))
        if None in changed:
            changed.remove(None)
        return self._fileid_involved_by_set(changed)

    @needs_read_lock
    def get_ancestry(self, revision_id):
        """Return a list of revision-ids integrated by a revision.
        
        This is topologically sorted.
        """
        if revision_id is None:
            return [None]
        vf = self._get_revision_vf()
        try:
            return [None] + vf.get_ancestry(revision_id)
        except errors.RevisionNotPresent:
            raise errors.NoSuchRevision(self, revision_id)

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        return self.get_revision_reconcile(revision_id)

    @needs_read_lock
    def get_revision_graph(self, revision_id=None):
        """Return a dictionary containing the revision graph.

        :param revision_id: The revision_id to get a graph from. If None, then
        the entire revision graph is returned. This is a deprecated mode of
        operation and will be removed in the future.
        :return: a dictionary of revision_id->revision_parents_list.
        """
        # special case NULL_REVISION
        if revision_id == NULL_REVISION:
            return {}
        weave = self._get_revision_vf()
        entire_graph = weave.get_graph()
        if revision_id is None:
            return weave.get_graph()
        elif revision_id not in weave:
            raise errors.NoSuchRevision(self, revision_id)
        else:
            # add what can be reached from revision_id
            result = {}
            pending = set([revision_id])
            while len(pending) > 0:
                node = pending.pop()
                result[node] = weave.get_parents(node)
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
        result = Graph()
        vf = self._get_revision_vf()
        versions = set(vf.versions())
        if not revision_ids:
            pending = set(self.all_revision_ids())
            required = set([])
        else:
            pending = set(revision_ids)
            # special case NULL_REVISION
            if NULL_REVISION in pending:
                pending.remove(NULL_REVISION)
            required = set(pending)
        done = set([])
        while len(pending):
            revision_id = pending.pop()
            if not revision_id in versions:
                if revision_id in required:
                    raise errors.NoSuchRevision(self, revision_id)
                # a ghost
                result.add_ghost(revision_id)
                # mark it as done so we don't try for it again.
                done.add(revision_id)
                continue
            parent_ids = vf.get_parents_with_ghosts(revision_id)
            for parent_id in parent_ids:
                # is this queued or done ?
                if (parent_id not in pending and
                    parent_id not in done):
                    # no, queue it.
                    pending.add(parent_id)
            result.add_node(revision_id, parent_ids)
            done.add(revision_id)
        return result

    def _get_revision_vf(self):
        """:return: a versioned file containing the revisions."""
        vf = self._revision_store.get_revision_file(self.get_transaction())
        return vf

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import KnitReconciler
        reconciler = KnitReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler
    
    def revision_parents(self, revision_id):
        return self._get_revision_vf().get_parents(revision_id)


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

    _default_format = None
    """The default format used for new repositories."""

    _formats = {}
    """The known formats."""

    def __str__(self):
        return "<%s>" % self.__class__.__name__

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the repository object in a_bzrdir."""
        try:
            transport = a_bzrdir.get_repository_transport(None)
            format_string = transport.get("format").read()
            return klass._formats[format_string]
        except errors.NoSuchFile:
            raise errors.NoRepositoryPresent(a_bzrdir)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string)

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        raise NotImplementedError(self._get_control_store)
    
    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

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
        text_store =TextStore(transport.clone(name),
                              prefixed=prefixed,
                              compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode)
        _revision_store = TextRevisionStore(text_store, serializer)
        return _revision_store

    def _get_versioned_file_store(self,
                                  name,
                                  transport,
                                  control_files,
                                  prefixed=True,
                                  versionedfile_class=WeaveFile,
                                  escaped=False):
        weave_transport = control_files._transport.clone(name)
        dir_mode = control_files._dir_mode
        file_mode = control_files._file_mode
        return VersionedFileStore(weave_transport, prefixed=prefixed,
                                  dir_mode=dir_mode,
                                  file_mode=file_mode,
                                  versionedfile_class=versionedfile_class,
                                  escaped=escaped)

    def initialize(self, a_bzrdir, shared=False):
        """Initialize a repository of this format in a_bzrdir.

        :param a_bzrdir: The bzrdir to put the new repository in it.
        :param shared: The repository should be initialized as a sharable one.

        This may raise UninitializableFormat if shared repository are not
        compatible the a_bzrdir.
        """

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def has_unnested_inventory(self):
        raise NotImplementedError(self.has_unnested_inventory)

    def check_conversion_target(self, target_format):
        raise NotImplementedError(self.check_conversion_target)

    def open(self, a_bzrdir, _found=False):
        """Return an instance of this format for the bzrdir a_bzrdir.
        
        _found is a private parameter, do not use it.
        """
        raise NotImplementedError(self.open)

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def set_default_format(klass, format):
        klass._default_format = format

    @classmethod
    def unregister_format(klass, format):
        assert klass._formats[format.get_format_string()] is format
        del klass._formats[format.get_format_string()]


class PreSplitOutRepositoryFormat(RepositoryFormat):
    """Base class for the pre split out repository formats."""

    rich_root_data = False

    def initialize(self, a_bzrdir, shared=False, _internal=False):
        """Create a weave repository.
        
        TODO: when creating split out bzr branch formats, move this to a common
        base for Format5, Format6. or something like that.
        """
        from bzrlib.weavefile import write_weave_v5
        from bzrlib.weave import Weave

        if shared:
            raise errors.IncompatibleFormat(self, a_bzrdir._format)

        if not _internal:
            # always initialized when the bzrdir is.
            return self.open(a_bzrdir, _found=True)
        
        # Create an empty weave
        sio = StringIO()
        write_weave_v5(Weave(), sio)
        empty_weave = sio.getvalue()

        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'weaves']
        files = [('inventory.weave', StringIO(empty_weave)),
                 ]
        
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        control_files = LockableFiles(a_bzrdir.transport, 'branch-lock',
                                      TransportLock)
        control_files.create_lock()
        control_files.lock_write()
        control_files._transport.mkdir_multi(dirs,
                mode=control_files._dir_mode)
        try:
            for file, content in files:
                control_files.put(file, content)
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True)

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return self._get_versioned_file_store('',
                                              repo_transport,
                                              control_files,
                                              prefixed=False)

    def _get_text_store(self, transport, control_files):
        """Get a store for file texts for this format."""
        raise NotImplementedError(self._get_text_store)

    def open(self, a_bzrdir, _found=False):
        """See RepositoryFormat.open()."""
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError

        repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = a_bzrdir._control_files
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return AllInOneRepository(_format=self,
                                  a_bzrdir=a_bzrdir,
                                  _revision_store=_revision_store,
                                  control_store=control_store,
                                  text_store=text_store)

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormat4(PreSplitOutRepositoryFormat):
    """Bzr repository format 4.

    This repository format has:
     - flat stores
     - TextStores for texts, inventories,revisions.

    This format is deprecated: it indexes texts using a text id which is
    removed in format 5; initialization and write support for this format
    has been removed.
    """

    def __init__(self):
        super(RepositoryFormat4, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat4()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Repository format 4"

    def has_unnested_inventory(self):
        return True

    def initialize(self, url, shared=False, _internal=False):
        """Format 4 branches cannot be created."""
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not 
        feasible.
        """
        return False

    def _get_control_store(self, repo_transport, control_files):
        """Format 4 repositories have no formal control store at this point.
        
        This will cause any control-file-needing apis to fail - this is desired.
        """
        return None
    
    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        from bzrlib.xml4 import serializer_v4
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        serializer=serializer_v4)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""


class RepositoryFormat5(PreSplitOutRepositoryFormat):
    """Bzr control format 5.

    This repository format has:
     - weaves for file texts and inventory
     - flat stores
     - TextStores for revisions and signatures.
    """

    def __init__(self):
        super(RepositoryFormat5, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat5()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 5"

    def has_unnested_inventory(self):
        return True

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        """Return the revision store object for this a_bzrdir."""
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        compressed=False)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('weaves', transport, control_files, prefixed=False)


class RepositoryFormat6(PreSplitOutRepositoryFormat):
    """Bzr control format 6.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
    """

    def __init__(self):
        super(RepositoryFormat6, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 6"

    def has_unnested_inventory(self):
        return True

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        compressed=False,
                                        prefixed=True)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('weaves', transport, control_files)


class MetaDirRepositoryFormat(RepositoryFormat):
    """Common base class for the new repositories using the metadir layout."""

    rich_root_data = False

    def __init__(self):
        super(MetaDirRepositoryFormat, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def _create_control_files(self, a_bzrdir):
        """Create the required files and the initial control_files object."""
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        repository_transport = a_bzrdir.get_repository_transport(self)
        control_files = LockableFiles(repository_transport, 'lock', LockDir)
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


class RepositoryFormat7(MetaDirRepositoryFormat):
    """Bzr repository 7.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
    """

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return self._get_versioned_file_store('',
                                              repo_transport,
                                              control_files,
                                              prefixed=False)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar-NG Repository format 7"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 7"

    def has_unnested_inventory(self):
        return True

    def check_conversion_target(self, target_format):
        pass

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        compressed=False,
                                        prefixed=True,
                                        )

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('weaves',
                                              transport,
                                              control_files)

    def initialize(self, a_bzrdir, shared=False):
        """Create a weave repository.

        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        from bzrlib.weavefile import write_weave_v5
        from bzrlib.weave import Weave

        # Create an empty weave
        sio = StringIO()
        write_weave_v5(Weave(), sio)
        empty_weave = sio.getvalue()

        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'weaves']
        files = [('inventory.weave', StringIO(empty_weave)), 
                 ]
        utf8_files = [('format', self.get_format_string())]
 
        self._upload_blank_content(a_bzrdir, dirs, files, utf8_files, shared)
        return self.open(a_bzrdir=a_bzrdir, _found=True)

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
            assert format.__class__ ==  self.__class__
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = LockableFiles(repo_transport, 'lock', LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return MetaDirRepository(_format=self,
                                 a_bzrdir=a_bzrdir,
                                 control_files=control_files,
                                 _revision_store=_revision_store,
                                 control_store=control_store,
                                 text_store=text_store)


class RepositoryFormatKnit(MetaDirRepositoryFormat):
    """Bzr repository knit format (generalized). 

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
    """

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return VersionedFileStore(
            repo_transport,
            prefixed=False,
            file_mode=control_files._file_mode,
            versionedfile_class=KnitVersionedFile,
            versionedfile_kwargs={'factory':KnitPlainFactory()},
            )

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        from bzrlib.store.revision.knit import KnitRevisionStore
        versioned_file_store = VersionedFileStore(
            repo_transport,
            file_mode=control_files._file_mode,
            prefixed=False,
            precious=True,
            versionedfile_class=KnitVersionedFile,
            versionedfile_kwargs={'delta':False, 'factory':KnitPlainFactory()},
            escaped=True,
            )
        return KnitRevisionStore(versioned_file_store)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('knits',
                                              transport,
                                              control_files,
                                              versionedfile_class=KnitVersionedFile,
                                              escaped=True)

    def has_unnested_inventory(self):
        return True

    def initialize(self, a_bzrdir, shared=False):
        """Create a knit format 1 repository.

        :param a_bzrdir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'knits']
        files = []
        utf8_files = [('format', self.get_format_string())]
        
        self._upload_blank_content(a_bzrdir, dirs, files, utf8_files, shared)
        repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = LockableFiles(repo_transport, 'lock', LockDir)
        control_store = self._get_control_store(repo_transport, control_files)
        transaction = transactions.WriteTransaction()
        # trigger a write of the inventory store.
        control_store.get_weave_or_empty('inventory', transaction)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        _revision_store.has_revision_id('A', transaction)
        _revision_store.get_signature_file(transaction)
        return self.open(a_bzrdir=a_bzrdir, _found=True)

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
            assert format.__class__ ==  self.__class__
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = LockableFiles(repo_transport, 'lock', LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return KnitRepository(_format=self,
                              a_bzrdir=a_bzrdir,
                              control_files=control_files,
                              _revision_store=_revision_store,
                              control_store=control_store,
                              text_store=text_store)


class RepositoryFormatKnit1(RepositoryFormatKnit):
    """Bzr repository knit format 1.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock

    This format was introduced in bzr 0.8.
    """
    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar-NG Knit Repository Format 1"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 1"

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatKnit2(RepositoryFormatKnit):
    """Bzr repository knit format 2.

    THIS FORMAT IS EXPERIMENTAL
    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
     - Support for recording full info about the tree root

    """
    
    rich_root_data = True

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar Knit Repository Format 2"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 2"

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
RepositoryFormat.register_format(RepositoryFormat7())
_default_format = RepositoryFormatKnit1()
RepositoryFormat.register_format(_default_format)
RepositoryFormat.register_format(RepositoryFormatKnit2())
RepositoryFormat.set_default_format(_default_format)
_legacy_formats = [RepositoryFormat4(),
                   RepositoryFormat5(),
                   RepositoryFormat6()]


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

    def copy_content(self, revision_id=None, basis=None):
        raise NotImplementedError(self.copy_content)

    def fetch(self, revision_id=None, pb=None):
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
            source_ids = self.source.get_ancestry(revision_id)
            assert source_ids[0] == None
            source_ids.pop(0)
        else:
            source_ids = self.source.all_revision_ids()
        result_set = set(source_ids).difference(target_ids)
        # this may look like a no-op: its not. It preserves the ordering
        # other_ids had while only returning the members from other_ids
        # that we've decided we need.
        return [rev_id for rev_id in source_ids if rev_id in result_set]


class InterSameDataRepository(InterRepository):
    """Code for converting between repositories that represent the same data.
    
    Data format and model must match for this to work.
    """

    _matching_repo_format = RepositoryFormat4()
    """Repository format for testing with."""

    @staticmethod
    def is_compatible(source, target):
        if not isinstance(source, Repository):
            return False
        if not isinstance(target, Repository):
            return False
        if source._format.rich_root_data == target._format.rich_root_data:
            return True
        else:
            return False

    @needs_write_lock
    def copy_content(self, revision_id=None, basis=None):
        """Make a complete copy of the content in self into destination.
        
        This is a destructive operation! Do not use it on existing 
        repositories.

        :param revision_id: Only copy the content needed to construct
                            revision_id and its parents.
        :param basis: Copy the needed data preferentially from basis.
        """
        try:
            self.target.set_make_working_trees(self.source.make_working_trees())
        except NotImplementedError:
            pass
        # grab the basis available data
        if basis is not None:
            self.target.fetch(basis, revision_id=revision_id)
        # but don't bother fetching if we have the needed data now.
        if (revision_id not in (None, NULL_REVISION) and 
            self.target.has_revision(revision_id)):
            return
        self.target.fetch(self.source, revision_id=revision_id)

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None):
        """Fetch the content required to construct revision_id.

        The content is copied from source to target.

        :param revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        :param pb: optional progress bar to use for progress reports. If not
                   provided a default one will be created.

        Returns the copied revision count and the failed revisions in a tuple:
        (copied, failures).
        """
        from bzrlib.fetch import GenericRepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, 
               self.target._format)
        f = GenericRepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               pb=pb)
        return f.count_copied, f.failed_revisions


class InterWeaveRepo(InterSameDataRepository):
    """Optimised code paths between Weave based repositories."""

    _matching_repo_format = RepositoryFormat7()
    """Repository format for testing with."""

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Weave formats.
        
        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be 
        overly general.
        """
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
    def copy_content(self, revision_id=None, basis=None):
        """See InterRepository.copy_content()."""
        # weave specific optimised path:
        if basis is not None:
            # copy the basis in, then fetch remaining data.
            basis.copy_content_into(self.target, revision_id)
            # the basis copy_content_into could miss-set this.
            try:
                self.target.set_make_working_trees(self.source.make_working_trees())
            except NotImplementedError:
                pass
            self.target.fetch(self.source, revision_id=revision_id)
        else:
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
            assert source_ids[0] == None
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

    _matching_repo_format = RepositoryFormatKnit1()
    """Repository format for testing with."""

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Knit formats.
        
        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be 
        overly general.
        """
        try:
            return (isinstance(source._format, (RepositoryFormatKnit1)) and
                    isinstance(target._format, (RepositoryFormatKnit1)))
        except AttributeError:
            return False

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None):
        """See InterRepository.fetch()."""
        from bzrlib.fetch import KnitRepoFetcher
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.source, self.source._format, self.target, self.target._format)
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
            assert source_ids[0] == None
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

InterRepository.register_optimiser(InterSameDataRepository)
InterRepository.register_optimiser(InterWeaveRepo)
InterRepository.register_optimiser(InterKnitRepo)


class RepositoryTestProviderAdapter(object):
    """A tool to generate a suite testing multiple repository formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and bzrdir_format and
    repository_format classes into each copy. Each copy is also given a new id()
    to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = TestSuite()
        for repository_format, bzrdir_format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.bzrdir_format = bzrdir_format
            new_test.repository_format = repository_format
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), repository_format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


class InterRepositoryTestProviderAdapter(object):
    """A tool to generate a suite testing multiple inter repository formats.

    This is done by copying the test once for each interrepo provider and injecting
    the transport_server, transport_readonly_server, repository_format and 
    repository_to_format classes into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = TestSuite()
        for interrepo_class, repository_format, repository_format_to in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.interrepo_class = interrepo_class
            new_test.repository_format = repository_format
            new_test.repository_format_to = repository_format_to
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), interrepo_class.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result

    @staticmethod
    def default_test_list():
        """Generate the default list of interrepo permutations to test."""
        result = []
        # test the default InterRepository between format 6 and the current 
        # default format.
        # XXX: robertc 20060220 reinstate this when there are two supported
        # formats which do not have an optimal code path between them.
        result.append((InterRepository,
                       RepositoryFormat6(),
                       RepositoryFormatKnit1()))
        for optimiser in InterRepository._optimisers:
            result.append((optimiser,
                           optimiser._matching_repo_format,
                           optimiser._matching_repo_format
                           ))
        # if there are specific combinations we want to use, we can add them 
        # here.
        return result


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
            self._timezone = local_time_offset()
        else:
            self._timezone = int(timezone)

        self._generate_revision_if_needed()

    def commit(self, message):
        """Make the actual commit.

        :return: The revision id of the recorded revision.
        """
        rev = Revision(timestamp=self._timestamp,
                       timezone=self._timezone,
                       committer=self._committer,
                       message=message,
                       inventory_sha1=self.inv_sha1,
                       revision_id=self._new_revision_id,
                       properties=self._revprops)
        rev.parent_ids = self.parents
        self.repository.add_revision(self._new_revision_id, rev, 
            self.new_inventory, self._config)
        return self._new_revision_id

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
        s = '%s-%s-' % (self._config.user_email(), 
                        compact_date(self._timestamp))
        s += hexlify(rand_bytes(8))
        return s

    def _generate_revision_if_needed(self):
        """Create a revision id if None was supplied.
        
        If the repository can not support user-specified revision ids
        they should override this function and raise UnsupportedOperation
        if _new_revision_id is not None.

        :raises: UnsupportedOperation
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
            if len(parent_invs):
                ie.revision = parent_invs[0].root.revision
            else:
                ie.revision = None
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


_unescape_map = {
    'apos':"'",
    'quot':'"',
    'amp':'&',
    'lt':'<',
    'gt':'>'
}


def _unescaper(match, _map=_unescape_map):
    return _map[match.group(1)]


_unescape_re = None


def _unescape_xml(data):
    """Unescape predefined XML entities in a string of data."""
    global _unescape_re
    if _unescape_re is None:
	_unescape_re = re.compile('\&([^;]*);')
    return _unescape_re.sub(_unescaper, data)

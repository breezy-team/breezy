# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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


"""Copying of history from one branch to another.

The basic plan is that every branch knows the history of everything
that has merged into it.  As the first step of a merge, pull, or
branch operation we copy history from the source into the destination
branch.

The copying is done in a slightly complicated order.  We don't want to
add a revision to the store until everything it refers to is also
stored, so that if a revision is present we can totally recreate it.
However, we can't know what files are included in a revision until we
read its inventory.  So we query the inventory store of the source for
the ids we need, and then pull those ids and then return to the inventories.
"""

import operator

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import InstallFailed
from bzrlib.progress import ProgressPhase
from bzrlib.revision import is_null, NULL_REVISION
from bzrlib.symbol_versioning import (deprecated_function,
        deprecated_method,
        )
from bzrlib.tsort import topo_sort
from bzrlib.trace import mutter
import bzrlib.ui
from bzrlib.versionedfile import filter_absent, FulltextContentFactory

# TODO: Avoid repeatedly opening weaves so many times.

# XXX: This doesn't handle ghost (not present in branch) revisions at
# all yet.  I'm not sure they really should be supported.

# NOTE: This doesn't copy revisions which may be present but not
# merged into the last revision.  I'm not sure we want to do that.

# - get a list of revisions that need to be pulled in
# - for each one, pull in that revision file
#   and get the inventory, and store the inventory with right
#   parents.
# - and get the ancestry, and store that with right parents too
# - and keep a note of all file ids and version seen
# - then go through all files; for each one get the weave,
#   and add in all file versions


class RepoFetcher(object):
    """Pull revisions and texts from one repository to another.

    last_revision
        if set, try to limit to the data this revision references.

    after running:
    count_copied -- number of revisions copied

    This should not be used directly, it's essential a object to encapsulate
    the logic in InterRepository.fetch().
    """

    def __init__(self, to_repository, from_repository, last_revision=None, pb=None,
        find_ghosts=True):
        """Create a repo fetcher.

        :param find_ghosts: If True search the entire history for ghosts.
        """
        # result variables.
        self.failed_revisions = []
        self.count_copied = 0
        if to_repository.has_same_location(from_repository):
            # repository.fetch should be taking care of this case.
            raise errors.BzrError('RepoFetcher run '
                    'between two objects at the same location: '
                    '%r and %r' % (to_repository, from_repository))
        self.to_repository = to_repository
        self.from_repository = from_repository
        # must not mutate self._last_revision as its potentially a shared instance
        self._last_revision = last_revision
        self.find_ghosts = find_ghosts
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.nested_progress_bar()
            self.nested_pb = self.pb
        else:
            self.pb = pb
            self.nested_pb = None
        self.from_repository.lock_read()
        try:
            self.to_repository.lock_write()
            try:
                self.to_repository.start_write_group()
                try:
                    self.__fetch()
                except:
                    self.to_repository.abort_write_group()
                    raise
                else:
                    self.to_repository.commit_write_group()
            finally:
                try:
                    if self.nested_pb is not None:
                        self.nested_pb.finished()
                finally:
                    self.to_repository.unlock()
        finally:
            self.from_repository.unlock()

    def __fetch(self):
        """Primary worker function.

        This initialises all the needed variables, and then fetches the 
        requested revisions, finally clearing the progress bar.
        """
        self.count_total = 0
        self.file_ids_names = {}
        pp = ProgressPhase('Transferring', 4, self.pb)
        try:
            pp.next_phase()
            search = self._revids_to_fetch()
            if search is None:
                return
            if getattr(self, '_fetch_everything_for_search', None) is not None:
                self._fetch_everything_for_search(search, pp)
            else:
                # backward compatibility
                self._fetch_everything_for_revisions(search.get_keys, pp)
        finally:
            self.pb.clear()

    def _fetch_everything_for_search(self, search, pp):
        """Fetch all data for the given set of revisions."""
        # The first phase is "file".  We pass the progress bar for it directly
        # into item_keys_introduced_by, which has more information about how
        # that phase is progressing than we do.  Progress updates for the other
        # phases are taken care of in this function.
        # XXX: there should be a clear owner of the progress reporting.  Perhaps
        # item_keys_introduced_by should have a richer API than it does at the
        # moment, so that it can feed the progress information back to this
        # function?
        phase = 'file'
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            revs = search.get_keys()
            graph = self.from_repository.get_graph()
            revs = list(graph.iter_topo_order(revs))
            data_to_fetch = self.from_repository.item_keys_introduced_by(revs,
                                                                         pb)
            text_keys = []
            for knit_kind, file_id, revisions in data_to_fetch:
                if knit_kind != phase:
                    phase = knit_kind
                    # Make a new progress bar for this phase
                    pb.finished()
                    pp.next_phase()
                    pb = bzrlib.ui.ui_factory.nested_progress_bar()
                if knit_kind == "file":
                    # Accumulate file texts
                    text_keys.extend([(file_id, revision) for revision in
                        revisions])
                elif knit_kind == "inventory":
                    # Now copy the file texts.
                    to_texts = self.to_repository.texts
                    from_texts = self.from_repository.texts
                    to_texts.insert_record_stream(from_texts.get_record_stream(
                        text_keys, self.to_repository._fetch_order,
                        not self.to_repository._fetch_uses_deltas))
                    # Cause an error if a text occurs after we have done the
                    # copy.
                    text_keys = None
                    # Before we process the inventory we generate the root
                    # texts (if necessary) so that the inventories references
                    # will be valid.
                    self._generate_root_texts(revs)
                    # NB: This currently reopens the inventory weave in source;
                    # using a single stream interface instead would avoid this.
                    self._fetch_inventory_weave(revs, pb)
                elif knit_kind == "signatures":
                    # Nothing to do here; this will be taken care of when
                    # _fetch_revision_texts happens.
                    pass
                elif knit_kind == "revisions":
                    self._fetch_revision_texts(revs, pb)
                else:
                    raise AssertionError("Unknown knit kind %r" % knit_kind)
            if self.to_repository._fetch_reconcile:
                self.to_repository.reconcile()
        finally:
            if pb is not None:
                pb.finished()
        self.count_copied += len(revs)
        
    def _revids_to_fetch(self):
        """Determines the exact revisions needed from self.from_repository to
        install self._last_revision in self.to_repository.

        If no revisions need to be fetched, then this just returns None.
        """
        mutter('fetch up to rev {%s}', self._last_revision)
        if self._last_revision is NULL_REVISION:
            # explicit limit of no revisions needed
            return None
        if (self._last_revision is not None and
            self.to_repository.has_revision(self._last_revision)):
            return None
        try:
            return self.to_repository.search_missing_revision_ids(
                self.from_repository, self._last_revision,
                find_ghosts=self.find_ghosts)
        except errors.NoSuchRevision, e:
            raise InstallFailed([self._last_revision])

    def _fetch_inventory_weave(self, revs, pb):
        pb.update("fetch inventory", 0, 2)
        to_weave = self.to_repository.inventories
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            # just merge, this is optimisable and its means we don't
            # copy unreferenced data such as not-needed inventories.
            pb.update("fetch inventory", 1, 3)
            from_weave = self.from_repository.inventories
            pb.update("fetch inventory", 2, 3)
            # we fetch only the referenced inventories because we do not
            # know for unselected inventories whether all their required
            # texts are present in the other repository - it could be
            # corrupt.
            to_weave.insert_record_stream(from_weave.get_record_stream(
                [(rev_id,) for rev_id in revs],
                self.to_repository._fetch_order,
                not self.to_repository._fetch_uses_deltas))
        finally:
            child_pb.finished()

    def _fetch_revision_texts(self, revs, pb):
        # may need to be a InterRevisionStore call here.
        to_sf = self.to_repository.signatures
        from_sf = self.from_repository.signatures
        # A missing signature is just skipped.
        to_sf.insert_record_stream(filter_absent(from_sf.get_record_stream(
            [(rev_id,) for rev_id in revs],
            self.to_repository._fetch_order,
            True)))
        # Bug #261339, some knit repositories accidentally had deltas in their
        # revision stream, when you weren't ever supposed to have deltas.
        # So we now *force* fulltext copying for signatures and revisions
        self._fetch_just_revision_texts(revs)

    def _fetch_just_revision_texts(self, version_ids):
        to_rf = self.to_repository.revisions
        from_rf = self.from_repository.revisions
        to_rf.insert_record_stream(from_rf.get_record_stream(
            [(rev_id,) for rev_id in version_ids],
            self.to_repository._fetch_order,
            True))
        # Bug #261339, some knit repositories accidentally had deltas in their
        # revision stream, when you weren't ever supposed to have deltas.
        # So we now *force* fulltext copying for signatures and revisions

    def _generate_root_texts(self, revs):
        """This will be called by __fetch between fetching weave texts and
        fetching the inventory weave.

        Subclasses should override this if they need to generate root texts
        after fetching weave texts.
        """
        pass


class Inter1and2Helper(object):
    """Helper for operations that convert data from model 1 and 2
    
    This is for use by fetchers and converters.
    """

    def __init__(self, source, target):
        """Constructor.

        :param source: The repository data comes from
        :param target: The repository data goes to
        """
        self.source = source
        self.target = target

    def iter_rev_trees(self, revs):
        """Iterate through RevisionTrees efficiently.

        Additionally, the inventory's revision_id is set if unset.

        Trees are retrieved in batches of 100, and then yielded in the order
        they were requested.

        :param revs: A list of revision ids
        """
        # In case that revs is not a list.
        revs = list(revs)
        while revs:
            for tree in self.source.revision_trees(revs[:100]):
                if tree.inventory.revision_id is None:
                    tree.inventory.revision_id = tree.get_revision_id()
                yield tree
            revs = revs[100:]

    def _find_root_ids(self, revs, parent_map, graph):
        revision_root = {}
        planned_versions = {}
        for tree in self.iter_rev_trees(revs):
            revision_id = tree.inventory.root.revision
            root_id = tree.get_root_id()
            planned_versions.setdefault(root_id, []).append(revision_id)
            revision_root[revision_id] = root_id
        # Find out which parents we don't already know root ids for
        parents = set()
        for revision_parents in parent_map.itervalues():
            parents.update(revision_parents)
        parents.difference_update(revision_root.keys() + [NULL_REVISION])
        # Limit to revisions present in the versionedfile
        parents = graph.get_parent_map(parents).keys()
        for tree in self.iter_rev_trees(parents):
            root_id = tree.get_root_id()
            revision_root[tree.get_revision_id()] = root_id
        return revision_root, planned_versions

    def generate_root_texts(self, revs):
        """Generate VersionedFiles for all root ids.

        :param revs: the revisions to include
        """
        to_texts = self.target.texts
        graph = self.source.get_graph()
        parent_map = graph.get_parent_map(revs)
        rev_order = topo_sort(parent_map)
        rev_id_to_root_id, root_id_to_rev_ids = self._find_root_ids(
            revs, parent_map, graph)
        root_id_order = [(rev_id_to_root_id[rev_id], rev_id) for rev_id in
            rev_order]
        # Guaranteed stable, this groups all the file id operations together
        # retaining topological order within the revisions of a file id.
        # File id splits and joins would invalidate this, but they don't exist
        # yet, and are unlikely to in non-rich-root environments anyway.
        root_id_order.sort(key=operator.itemgetter(0))
        # Create a record stream containing the roots to create.
        def yield_roots():
            for key in root_id_order:
                root_id, rev_id = key
                rev_parents = parent_map[rev_id]
                # We drop revision parents with different file-ids, because
                # that represents a rename of the root to a different location
                # - its not actually a parent for us. (We could look for that
                # file id in the revision tree at considerably more expense,
                # but for now this is sufficient (and reconcile will catch and
                # correct this anyway).
                # When a parent revision is a ghost, we guess that its root id
                # was unchanged (rather than trimming it from the parent list).
                parent_keys = tuple((root_id, parent) for parent in rev_parents
                    if parent != NULL_REVISION and
                        rev_id_to_root_id.get(parent, root_id) == root_id)
                yield FulltextContentFactory(key, parent_keys, None, '')
        to_texts.insert_record_stream(yield_roots())

    def regenerate_inventory(self, revs):
        """Generate a new inventory versionedfile in target, convertin data.
        
        The inventory is retrieved from the source, (deserializing it), and
        stored in the target (reserializing it in a different format).
        :param revs: The revisions to include
        """
        for tree in self.iter_rev_trees(revs):
            parents = tree.get_parent_ids()
            self.target.add_inventory(tree.get_revision_id(), tree.inventory,
                                      parents)

    def fetch_revisions(self, revision_ids):
        # TODO: should this batch them up rather than requesting 10,000
        #       revisions at once?
        for revision in self.source.get_revisions(revision_ids):
            self.target.add_revision(revision.revision_id, revision)


class Model1toKnit2Fetcher(RepoFetcher):
    """Fetch from a Model1 repository into a Knit2 repository
    """
    def __init__(self, to_repository, from_repository, last_revision=None,
                 pb=None, find_ghosts=True):
        self.helper = Inter1and2Helper(from_repository, to_repository)
        RepoFetcher.__init__(self, to_repository, from_repository,
            last_revision, pb, find_ghosts)

    def _generate_root_texts(self, revs):
        self.helper.generate_root_texts(revs)

    def _fetch_inventory_weave(self, revs, pb):
        self.helper.regenerate_inventory(revs)

    def _fetch_revision_texts(self, revs, pb):
        """Fetch revision object texts"""
        count = 0
        total = len(revs)
        for rev in revs:
            pb.update('copying revisions', count, total)
            try:
                sig_text = self.from_repository.get_signature_text(rev)
                self.to_repository.add_signature_text(rev, sig_text)
            except errors.NoSuchRevision:
                # not signed.
                pass
            self._copy_revision(rev)
            count += 1

    def _copy_revision(self, rev):
        self.helper.fetch_revisions([rev])


class Knit1to2Fetcher(RepoFetcher):
    """Fetch from a Knit1 repository into a Knit2 repository"""

    def __init__(self, to_repository, from_repository, last_revision=None,
                 pb=None, find_ghosts=True):
        self.helper = Inter1and2Helper(from_repository, to_repository)
        RepoFetcher.__init__(self, to_repository, from_repository,
            last_revision, pb, find_ghosts)

    def _generate_root_texts(self, revs):
        self.helper.generate_root_texts(revs)

    def _fetch_inventory_weave(self, revs, pb):
        self.helper.regenerate_inventory(revs)

    def _fetch_just_revision_texts(self, version_ids):
        self.helper.fetch_revisions(version_ids)

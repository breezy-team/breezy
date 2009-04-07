# Copyright (C) 2005, 2006, 2008, 2009 Canonical Ltd
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


"""Copying of history from one branch to another.

The basic plan is that every branch knows the history of everything
that has merged into it.  As the first step of a merge, pull, or
branch operation we copy history from the source into the destination
branch.
"""

import operator

import bzrlib
from bzrlib import (
    errors,
    symbol_versioning,
    )
from bzrlib.errors import InstallFailed
from bzrlib.progress import ProgressPhase
from bzrlib.revision import NULL_REVISION
from bzrlib.tsort import topo_sort
from bzrlib.trace import mutter
import bzrlib.ui
from bzrlib.versionedfile import FulltextContentFactory


class RepoFetcher(object):
    """Pull revisions and texts from one repository to another.

    This should not be used directly, it's essential a object to encapsulate
    the logic in InterRepository.fetch().
    """

    def __init__(self, to_repository, from_repository, last_revision=None,
        pb=None, find_ghosts=True, fetch_spec=None):
        """Create a repo fetcher.

        :param last_revision: If set, try to limit to the data this revision
            references.
        :param find_ghosts: If True search the entire history for ghosts.
        :param _write_group_acquired_callable: Don't use; this parameter only
            exists to facilitate a hack done in InterPackRepo.fetch.  We would
            like to remove this parameter.
        :param pb: ProgressBar object to use; deprecated and ignored.
            This method will just create one on top of the stack.
        """
        if pb is not None:
            symbol_versioning.warn(
                symbol_versioning.deprecated_in((1, 14, 0))
                % "pb parameter to RepoFetcher.__init__")
            # and for simplicity it is in fact ignored
        if to_repository.has_same_location(from_repository):
            # repository.fetch should be taking care of this case.
            raise errors.BzrError('RepoFetcher run '
                    'between two objects at the same location: '
                    '%r and %r' % (to_repository, from_repository))
        self.to_repository = to_repository
        self.from_repository = from_repository
        self.sink = to_repository._get_sink()
        # must not mutate self._last_revision as its potentially a shared instance
        self._last_revision = last_revision
        self._fetch_spec = fetch_spec
        self.find_ghosts = find_ghosts
        self.from_repository.lock_read()
        mutter("Using fetch logic to copy between %s(%s) and %s(%s)",
               self.from_repository, self.from_repository._format,
               self.to_repository, self.to_repository._format)
        try:
            self.__fetch()
        finally:
            self.from_repository.unlock()

    def __fetch(self):
        """Primary worker function.

        This initialises all the needed variables, and then fetches the
        requested revisions, finally clearing the progress bar.
        """
        # Roughly this is what we're aiming for fetch to become:
        #
        # missing = self.sink.insert_stream(self.source.get_stream(search))
        # if missing:
        #     missing = self.sink.insert_stream(self.source.get_items(missing))
        # assert not missing
        self.count_total = 0
        self.file_ids_names = {}
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        pb.show_pct = pb.show_count = False
        try:
            pb.update("Finding revisions", 0, 2)
            search = self._revids_to_fetch()
            if search is None:
                return
            pb.update("Fetching revisions", 1, 2)
            self._fetch_everything_for_search(search)
        finally:
            pb.finished()

    def _fetch_everything_for_search(self, search):
        """Fetch all data for the given set of revisions."""
        # The first phase is "file".  We pass the progress bar for it directly
        # into item_keys_introduced_by, which has more information about how
        # that phase is progressing than we do.  Progress updates for the other
        # phases are taken care of in this function.
        # XXX: there should be a clear owner of the progress reporting.  Perhaps
        # item_keys_introduced_by should have a richer API than it does at the
        # moment, so that it can feed the progress information back to this
        # function?
        if (self.from_repository._format.rich_root_data and
            not self.to_repository._format.rich_root_data):
            raise errors.IncompatibleRepositories(
                self.from_repository, self.to_repository,
                "different rich-root support")
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            pb.update("Get stream source")
            source = self.from_repository._get_source(
                self.to_repository._format)
            stream = source.get_stream(search)
            from_format = self.from_repository._format
            pb.update("Inserting stream")
            resume_tokens, missing_keys = self.sink.insert_stream(
                stream, from_format, [])
            if self.to_repository._fallback_repositories:
                # Find all the parent revisions referenced by the stream, but
                # not present in the stream, and make sure we have their
                # inventories.
                revision_ids = search.get_keys()
                parent_maps = self.to_repository.get_parent_map(revision_ids)
                parents = set()
                map(parents.update, parent_maps.itervalues())
                parents.difference_update(revision_ids)
                missing_keys.update(
                    ('inventories', rev_id) for rev_id in parents)
            if missing_keys:
                pb.update("Missing keys")
                stream = source.get_stream_for_missing_keys(missing_keys)
                pb.update("Inserting missing keys")
                resume_tokens, missing_keys = self.sink.insert_stream(
                    stream, from_format, resume_tokens)
            if missing_keys:
                raise AssertionError(
                    "second push failed to complete a fetch %r." % (
                        missing_keys,))
            if resume_tokens:
                raise AssertionError(
                    "second push failed to commit the fetch %r." % (
                        resume_tokens,))
            pb.update("Finishing stream")
            self.sink.finished()
        finally:
            pb.finished()

    def _revids_to_fetch(self):
        """Determines the exact revisions needed from self.from_repository to
        install self._last_revision in self.to_repository.

        If no revisions need to be fetched, then this just returns None.
        """
        if self._fetch_spec is not None:
            return self._fetch_spec
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


class Inter1and2Helper(object):
    """Helper for operations that convert data from model 1 and 2

    This is for use by fetchers and converters.
    """

    def __init__(self, source):
        """Constructor.

        :param source: The repository data comes from
        """
        self.source = source

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
        return [('texts', yield_roots())]

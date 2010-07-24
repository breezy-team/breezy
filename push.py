# Copyright (C) 2009-2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Push implementation that simply prints message saying push is not supported."""

from bzrlib import (
    errors,
    ui,
    )
from bzrlib.graph import (
    PendingAncestryResult,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )

from bzrlib.plugins.git.errors import (
    NoPushSupport,
    )
from bzrlib.plugins.git.object_store import (
    BazaarObjectStore,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    LocalGitRepository,
    GitRepositoryFormat,
    )
from bzrlib.plugins.git.remote import (
    RemoteGitRepository,
    )


class MissingObjectsIterator(object):
    """Iterate over git objects that are missing from a target repository.

    """

    def __init__(self, store, source, pb=None):
        """Create a new missing objects iterator.

        """
        self.source = source
        self._object_store = store
        self._pending = []
        self.pb = pb

    def import_revisions(self, revids, roundtrip):
        """Import a set of revisions into this git repository.

        :param revids: Revision ids of revisions to import
        :param roundtrip: Whether to roundtrip bzr metadata
        """
        for i, revid in enumerate(revids):
            if self.pb:
                self.pb.update("pushing revisions", i, len(revids))
            git_commit = self.import_revision(revid, roundtrip)
            yield (revid, git_commit)

    def import_revision(self, revid, roundtrip):
        """Import a revision into this Git repository.

        :param revid: Revision id of the revision
        :param roundtrip: Whether to roundtrip bzr metadata
        """
        tree = self._object_store.tree_cache.revision_tree(revid)
        rev = self.source.get_revision(revid)
        commit = None
        for path, obj, ie in self._object_store._revision_to_objects(rev, tree,
            roundtrip):
            if obj.type_name == "commit":
                commit = obj
            self._pending.append((obj, path))
        return commit.id

    def __len__(self):
        return len(self._pending)

    def __iter__(self):
        return iter(self._pending)


class InterToGitRepository(InterRepository):
    """InterRepository that copies into a Git repository."""

    _matching_repo_format = GitRepositoryFormat()

    def __init__(self, source, target):
        super(InterToGitRepository, self).__init__(source, target)
        self.mapping = self.target.get_mapping()
        self.source_store = BazaarObjectStore(self.source, self.mapping)

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def dfetch_refs(self, update_refs):
        """Fetch non-roundtripped revisions into the target repository.

        :param update_refs: Generate refs to fetch. Receives dictionary 
            with old names to old git shas. Should return a dictionary
            of new names to Bazaar revision ids.
        :return: revision id map, old refs dictionary and new refs dictionary
        """
        raise NotImplementedError(self.dfetch_refs)

    def fetch_refs(self, update_refs):
        """Fetch possibly roundtripped revisions into the target repository.

        :param update_refs: Generate refs to fetch. Receives dictionary 
            with old refs (git shas), returns dictionary of new names to 
            git shas.
        :return: old refs, new refs
        """
        raise NotImplementedError(self.fetch_refs)


class InterToLocalGitRepository(InterToGitRepository):
    """InterBranch implementation between a Bazaar and a Git repository."""

    def __init__(self, source, target):
        super(InterToLocalGitRepository, self).__init__(source, target)
        self.target_store = self.target._git.object_store
        self.target_refs = self.target._git.refs

    def missing_revisions(self, stop_revisions, check_revid):
        """Find the revisions that are missing from the target repository.

        :param stop_revisions: Revisions to check for
        :param check_revid: Convenience function to check if a revid is 
            present.
        :return: sequence of missing revisions, in topological order
        """
        missing = []
        graph = self.source.get_graph()
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for revid, _ in graph.iter_ancestry(stop_revisions):
                pb.update("determining revisions to fetch", len(missing))
                if not check_revid(revid):
                    missing.append(revid)
        finally:
            pb.finished()
        return graph.iter_topo_order(missing)

    def fetch_refs(self, update_refs):
        old_refs = self.target._git.get_refs()
        new_refs = update_refs(old_refs)
        fetch_spec = PendingAncestryResult(new_refs.values(), self.source)
        self.fetch(fetch_spec=fetch_spec)
        return old_refs, new_refs

    def dfetch_refs(self, update_refs):
        old_refs = self.target._git.get_refs()
        new_refs = update_refs(old_refs)
        revidmap, gitidmap = self.dfetch(new_refs.values())
        for name, revid in new_refs.iteritems():
            try:
                gitid = gitidmap[revid]
            except KeyError:
                gitid = self.source_store._lookup_revision_sha1(revid)
            self.target._git.refs[name] = gitid
            new_refs[name] = revid
        return revidmap, old_refs, new_refs

    def _find_missing_revs(self, stop_revisions):
        def check_revid(revid):
            if revid == NULL_REVISION:
                return True
            sha_id = self.source_store._lookup_revision_sha1(revid)
            try:
                return (sha_id in self.target_store)
            except errors.NoSuchRevision:
                # Ghost, can't push
                return True
        return list(self.missing_revisions(stop_revisions, check_revid))

    def _get_missing_objects_iterator(self, pb):
        return MissingObjectsIterator(self.source_store, self.source, pb)

    def dfetch(self, stop_revisions):
        """Import the gist of the ancestry of a particular revision."""
        gitidmap = {}
        revidmap = {}
        self.source.lock_read()
        try:
            todo = self._find_missing_revs(stop_revisions)
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = self._get_missing_objects_iterator()
                for old_bzr_revid, git_commit in object_generator.import_revisions(
                    todo, roundtrip=False):
                    new_bzr_revid = self.mapping.revision_id_foreign_to_bzr(git_commit)
                    revidmap[old_bzr_revid] = new_bzr_revid
                    gitidmap[old_bzr_revid] = git_commit
                self.target_store.add_objects(object_generator)
            finally:
                pb.finished()
        finally:
            self.source.unlock()
        return revidmap, gitidmap

    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
            fetch_spec=None):
        if revision_id is not None:
            stop_revisions = [revision_id]
        elif fetch_spec is not None:
            stop_revisions = fetch_spec.heads
        else:
            stop_revisions = self.source.all_revision_ids()
        self.source.lock_read()
        try:
            todo = self._find_missing_revs(stop_revisions)
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = self._get_missing_objects_iterator(pb)
                for (revid, git_sha) in object_generator.import_revisions(
                    todo, roundtrip=True):
                    try:
                        self.mapping.revision_id_bzr_to_foreign(revid)
                    except errors.InvalidRevisionId:
                        self.target_refs[self.mapping.revid_as_refname(revid)] = git_sha
                self.target_store.add_objects(object_generator)
            finally:
                pb.finished()
        finally:
            self.source.unlock()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and
                isinstance(target, LocalGitRepository))


class InterToRemoteGitRepository(InterToGitRepository):

    def dfetch_refs(self, update_refs):
        """Import the gist of the ancestry of a particular revision."""
        revidmap = {}
        def determine_wants(old_refs):
            ret = {}
            self.old_refs = old_refs
            self.new_refs = update_refs(self.old_refs)
            for name, revid in self.new_refs.iteritems():
                ret[name] = self.source_store._lookup_revision_sha1(revid)
            return ret
        self.source.lock_read()
        try:
            new_refs = self.target.send_pack(determine_wants,
                    self.source_store.generate_lossy_pack_contents)
        finally:
            self.source.unlock()
        return revidmap, self.old_refs, self.new_refs

    def fetch_refs(self, update_refs):
        raise NoPushSupport()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and
                isinstance(target, RemoteGitRepository))

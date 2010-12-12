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
from bzrlib.plugins.git.refs import (
    UnpeelMap,
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

    def _revision_needs_fetching(self, sha_id, revid):
        if revid == NULL_REVISION:
            return False
        if sha_id is None:
            try:
                sha_id = self.source_store._lookup_revision_sha1(revid)
            except KeyError:
                return False
        try:
            return (sha_id not in self.target_store)
        except errors.NoSuchRevision:
            # Ghost, can't push
            return False

    def missing_revisions(self, stop_revisions):
        """Find the revisions that are missing from the target repository.

        :param stop_revisions: Revisions to check for (tuples with
            Git SHA1, bzr revid)
        :return: sequence of missing revisions, in topological order
        :raise: NoSuchRevision if the stop_revisions are not present in
            the source
        """
        revid_sha_map = {}
        stop_revids = []
        stop_sha1s = []
        for (sha1, revid) in stop_revisions:
            if sha1 is not None and revid is not None:
                revid_sha_map[revid] = sha1
            elif sha1 is not None:
                stop_sha1s.append(sha1)
            else:
                assert revid is not None
                stop_revids.append(revid)
        missing = []
        graph = self.source.get_graph()
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for revid, _ in graph.iter_ancestry(stop_revids):
                assert type(revid) is str
                pb.update("determining revisions to fetch", len(missing))
                sha1 = revid_sha_map.get(revid)
                if self._revision_needs_fetching(sha1, revid):
                    missing.append(revid)
        finally:
            pb.finished()
        for sha1 in stop_sha1s:
            try:
                (kind, (revid, tree_sha, verifiers)) = self.source_store.lookup_git_sha(sha1)
            except KeyError:
                continue
            else:
                missing.append(revid)
                revid_sha_map[revid] = sha1
        return graph.iter_topo_order(missing)

    def _get_target_bzr_refs(self):
        """Return a dictionary with references.

        :return: Dictionary with reference names as keys and tuples
            with Git SHA, Bazaar revid as values.
        """
        bzr_refs = {}
        refs = self.target._git.get_refs()
        for k, v in refs.iteritems():
            try:
                (kind, type_data) = self.source_store.lookup_git_sha(v)
            except KeyError:
                revid = None
            else:
                if kind == "commit":
                    revid = type_data[0]
                else:
                    revid = None
            bzr_refs[k] = (v, revid)
        return bzr_refs

    def fetch_refs(self, update_refs):
        self.source.lock_read()
        try:
            old_refs = self._get_target_bzr_refs()
            new_refs = update_refs(old_refs)
            self.fetch(mapped_refs=new_refs.values())
        finally:
            self.source.unlock()
        return old_refs, new_refs

    def dfetch_refs(self, update_refs):
        self.source.lock_read()
        try:
            old_refs = self._get_target_bzr_refs()
            new_refs = update_refs(old_refs)
            revidmap, gitidmap = self.dfetch(new_refs.values())
            for name, (gitid, revid) in new_refs.iteritems():
                if gitid is None:
                    try:
                        gitid = gitidmap[revid]
                    except KeyError:
                        gitid = self.source_store._lookup_revision_sha1(revid)
                self.target._git.refs[name] = gitid
                new_refs[name] = (gitid, self.source_store.lookup_git_sha(gitid)[1][0])
        finally:
            self.source.unlock()
        return revidmap, old_refs, new_refs

    def _get_missing_objects_iterator(self, pb):
        return MissingObjectsIterator(self.source_store, self.source, pb)

    def dfetch(self, stop_revisions):
        """Import the gist of the ancestry of a particular revision."""
        gitidmap = {}
        revidmap = {}
        self.source.lock_read()
        try:
            todo = list(self.missing_revisions(stop_revisions))
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = self._get_missing_objects_iterator(pb)
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
            fetch_spec=None, mapped_refs=None):
        if mapped_refs is not None:
            stop_revisions = mapped_refs
        elif revision_id is not None:
            stop_revisions = [(None, revision_id)]
        elif fetch_spec is not None:
            stop_revisions = [(None, revid) for revid in fetch_spec.heads]
        else:
            stop_revisions = [(None, revid) for revid in self.source.all_revision_ids()]
        self.source.lock_read()
        try:
            todo = list(self.missing_revisions(stop_revisions))
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
        unpeel_map = UnpeelMap.from_repository(self.source)
        revidmap = {}
        def determine_wants(old_refs):
            ret = {}
            self.old_refs = dict([(k, (v, None)) for (k, v) in old_refs.iteritems()])
            self.new_refs = update_refs(self.old_refs)
            for name, (gitid, revid) in self.new_refs.iteritems():
                if gitid is None:
                    ret[name] = unpeel_map.re_unpeel_tag(self.source_store._lookup_revision_sha1(revid), old_refs.get(name))
                else:
                    ret[name] = gitid
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

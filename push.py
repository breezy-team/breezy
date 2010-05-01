# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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
        ret = []
        for i, revid in enumerate(revids):
            if self.pb:
                self.pb.update("pushing revisions", i, len(revids))
            git_commit = self.import_revision(revid, roundtrip)
            ret.append((revid, git_commit))
        return ret

    def import_revision(self, revid, roundtrip):
        """Import the gist of a revision into this Git repository.

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


class InterToLocalGitRepository(InterToGitRepository):

    def __init__(self, source, target):
        super(InterToLocalGitRepository, self).__init__(source, target)
        self.target_store = self.target._git.object_store

    def missing_revisions(self, stop_revisions, check_revid):
        missing = []
        pb = ui.ui_factory.nested_progress_bar()
        try:
            graph = self.source.get_graph()
            for revid, _ in graph.iter_ancestry(stop_revisions):
                pb.update("determining revisions to fetch", len(missing))
                if not check_revid(revid):
                    missing.append(revid)
            return graph.iter_topo_order(missing)
        finally:
            pb.finished()

    def fetch_refs(self, refs):
        fetch_spec = PendingAncestryResult(refs.values(), self.source)
        self.fetch(fetch_spec=fetch_spec)

    def dfetch_refs(self, refs):
        old_refs = self.target._git.get_refs()
        new_refs = {}
        revidmap, gitidmap = self.dfetch(refs.values())
        for name, revid in refs.iteritems():
            if revid in gitidmap:
                gitid = gitidmap[revid]
            else:
                gitid = self.source_store._lookup_revision_sha1(revid)
            self.target._git.refs[name] = gitid
            new_refs[name] = gitid
        return revidmap, old_refs, new_refs

    def _find_missing_revs(self, stop_revisions):
        def check_revid(revid):
            if revid == NULL_REVISION:
                return True
            try:
                return (self.source_store._lookup_revision_sha1(revid) in self.target_store)
            except errors.NoSuchRevision:
                # Ghost, can't dpush
                return True
        return list(self.missing_revisions(stop_revisions, check_revid))

    def dfetch(self, stop_revisions):
        """Import the gist of the ancestry of a particular revision."""
        gitidmap = {}
        revidmap = {}
        self.source.lock_read()
        try:
            todo = self._find_missing_revs(stop_revisions)
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = MissingObjectsIterator(self.source_store,
                    self.source, pb)
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
            stop_revisions = []
        self.source.lock_read()
        try:
            todo = self._find_missing_revs(stop_revisions)
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = MissingObjectsIterator(self.source_store,
                    self.source, pb)
                object_generator.import_revisions(todo, roundtrip=True)
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

    def dfetch_refs(self, new_refs):
        """Import the gist of the ancestry of a particular revision."""
        revidmap = {}
        old_refs = {}
        def determine_wants(refs):
            ret = {}
            old_refs.update(new_refs)
            for name, revid in new_refs.iteritems():
                ret[name] = self.source_store._lookup_revision_sha1(revid)
            return ret
        self.source.lock_read()
        try:
            new_refs = self.target.send_pack(determine_wants,
                    self.source_store.generate_pack_contents)
        finally:
            self.source.unlock()
        return revidmap, old_refs, new_refs

    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
            fetch_spec=None):
        raise NoPushSupport()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and
                isinstance(target, RemoteGitRepository))

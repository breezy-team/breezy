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
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )

from bzrlib.plugins.git.errors import (
    NoPushSupport,
    )
from bzrlib.plugins.git.mapping import (
    extract_unusual_modes,
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
        self._revids = set()
        self._sent_shas = set()
        self._pending = []
        self.pb = pb

    def import_revisions(self, revids):
        self._revids.update(revids)
        for i, revid in enumerate(revids):
            if self.pb:
                self.pb.update("pushing revisions", i, len(revids))
            git_commit = self.import_revision(revid)
            yield (revid, git_commit)

    def queue(self, obj, path):
        self._pending.append((obj, path))
        self._sent_shas.add(obj.id)

    def import_revision(self, revid):
        """Import the gist of a revision into this Git repository.

        """
        inv = self.source.get_inventory(revid)
        rev = self.source.get_revision(revid)
        invshamap = self._object_store._idmap.get_inventory_sha_map(revid)
        unusual_modes = extract_unusual_modes(rev)
        parent_invshamaps = [self._object_store._idmap.get_inventory_sha_map(r) for r in rev.parent_ids]
        tree_sha = None
        for path, obj in self._object_store._inventory_to_objects(inv, 
                list(self.source.iter_inventories(rev.parent_ids)),
                parent_invshamaps,
                unusual_modes):
            self.queue(obj, path)
            if path == "":
                tree_sha = obj.id
        if tree_sha is None:
            if not rev.parent_ids:
                from dulwich.objects import Tree
                tree_sha = Tree().id
            else:
                tree_sha = parent_invshamaps[0][inv.root.file_id]
        commit = self._object_store._get_commit(rev, tree_sha)
        self.queue(commit, None)
        return commit.id

    def __len__(self):
        return len(self._pending)

    def __iter__(self):
        for i, (object, path) in enumerate(self._pending):
            if self.pb:
                self.pb.update("writing pack objects", i, len(self))
            yield (object, path)


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

    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
            fetch_spec=None):
        raise NoPushSupport()


class InterToLocalGitRepository(InterToGitRepository):

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

    def dfetch_refs(self, refs):
        new_refs = {}
        revidmap, gitidmap = self.dfetch(refs.values())
        for name, revid in refs.iteritems():
            if revid in gitidmap:
                gitid = gitidmap[revid]
            else:
                gitid = self.source_store._lookup_revision_sha1(revid)
            self.target._git.refs[name] = gitid
            new_refs[name] = gitid
        return revidmap, new_refs

    def dfetch(self, stop_revisions):
        """Import the gist of the ancestry of a particular revision."""
        gitidmap = {}
        revidmap = {}
        self.source.lock_read()
        try:
            target_store = self.target._git.object_store
            def check_revid(revid):
                if revid == NULL_REVISION:
                    return True
                try:
                    return (self.source_store._lookup_revision_sha1(revid) in target_store)
                except errors.NoSuchRevision:
                    # Ghost, can't dpush
                    return True
            todo = list(self.missing_revisions(stop_revisions, check_revid))
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = MissingObjectsIterator(self.source_store, self.source, pb)
                for old_bzr_revid, git_commit in object_generator.import_revisions(
                    todo):
                    new_bzr_revid = self.mapping.revision_id_foreign_to_bzr(git_commit)
                    revidmap[old_bzr_revid] = new_bzr_revid
                    gitidmap[old_bzr_revid] = git_commit
                target_store.add_objects(object_generator)
            finally:
                pb.finished()
        finally:
            self.source.unlock()
        return revidmap, gitidmap

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and
                isinstance(target, LocalGitRepository))


class InterToRemoteGitRepository(InterToGitRepository):

    def dfetch_refs(self, new_refs):
        """Import the gist of the ancestry of a particular revision."""
        revidmap = {}
        def determine_wants(refs):
            ret = {}
            for name, revid in new_refs.iteritems():
                ret[name] = self.source_store._lookup_revision_sha1(revid)
            return ret
        self.source.lock_read()
        try:
            new_refs = self.target.send_pack(determine_wants,
                    self.source_store.generate_pack_contents)
        finally:
            self.source.unlock()
        return revidmap, new_refs

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and
                isinstance(target, RemoteGitRepository))

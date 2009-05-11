# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2008-2009 Jelmer Vernooij <jelmer@samba.org>
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

"""An adapter between a Git Repository and a Bazaar Branch"""

import bzrlib
from bzrlib import (
    errors,
    graph,
    inventory,
    osutils,
    repository,
    revision,
    revisiontree,
    ui,
    urlutils,
    )
from bzrlib.foreign import (
    ForeignRepository,
    )
from bzrlib.trace import (
    mutter,
    )
from bzrlib.transport import (
    get_transport,
    )

from bzrlib.plugins.git.commit import (
    GitCommitBuilder,
    )
from bzrlib.plugins.git.foreign import (
    versionedfiles,
    )
from bzrlib.plugins.git.inventory import (
    GitInventory,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    foreign_git,
    mapping_registry,
    )
from bzrlib.plugins.git.versionedfiles import (
    GitTexts,
    )


class GitRepository(ForeignRepository):
    """An adapter to git repositories for bzr."""

    _serializer = None
    _commit_builder_class = GitCommitBuilder
    vcs = foreign_git

    def __init__(self, gitdir, lockfiles):
        ForeignRepository.__init__(self, GitRepositoryFormat(), gitdir, 
            lockfiles)
        from bzrlib.plugins.git import fetch, push
        for optimiser in [fetch.InterRemoteGitNonGitRepository, 
                          fetch.InterLocalGitNonGitRepository,
                          fetch.InterGitGitRepository,
                          push.InterToLocalGitRepository,
                          push.InterToRemoteGitRepository]:
            repository.InterRepository.register_optimiser(optimiser)

    def is_shared(self):
        return True

    def supports_rich_root(self):
        return True

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def get_mapping(self):
        return default_mapping

    def make_working_trees(self):
        return True

    def dfetch(self, source, stop_revision):
        interrepo = repository.InterRepository.get(source, self)
        return interrepo.dfetch(stop_revision)

    def dfetch_refs(self, source, stop_revision):
        interrepo = repository.InterRepository.get(source, self)
        return interrepo.dfetch_refs(stop_revision)


class LocalGitRepository(GitRepository):
    """Git repository on the file system."""

    def __init__(self, gitdir, lockfiles):
        # FIXME: This also caches negatives. Need to be more careful 
        # about this once we start writing to git
        self._parents_provider = graph.CachingParentsProvider(self)
        GitRepository.__init__(self, gitdir, lockfiles)
        self.base = gitdir.root_transport.base
        self._git = gitdir._git
        self.texts = None
        self.signatures = versionedfiles.VirtualSignatureTexts(self)
        self.revisions = versionedfiles.VirtualRevisionTexts(self)
        self.inventories = versionedfiles.VirtualInventoryTexts(self)
        self.texts = GitTexts(self)

    def all_revision_ids(self):
        ret = set([revision.NULL_REVISION])
        heads = self._git.refs.as_dict('refs/heads')
        if heads == {}:
            return ret
        bzr_heads = [self.get_mapping().revision_id_foreign_to_bzr(h) for h in heads.itervalues()]
        ret = set(bzr_heads)
        graph = self.get_graph()
        for rev, parents in graph.iter_ancestry(bzr_heads):
            ret.add(rev)
        return ret

    def _make_parents_provider(self):
        """See Repository._make_parents_provider()."""
        return self._parents_provider

    def get_parent_map(self, revids):
        parent_map = {}
        for revision_id in revids:
            assert isinstance(revision_id, str)
            if revision_id == revision.NULL_REVISION:
                parent_map[revision_id] = ()
                continue
            hexsha, mapping = self.lookup_git_revid(revision_id)
            commit  = self._git.commit(hexsha)
            if commit is None:
                continue
            else:
                parent_map[revision_id] = [mapping.revision_id_foreign_to_bzr(p) for p in commit.parents]
        return parent_map

    def get_ancestry(self, revision_id, topo_sorted=True):
        """See Repository.get_ancestry().
        """
        if revision_id is None:
            return [None, revision.NULL_REVISION] + self._all_revision_ids()
        assert isinstance(revision_id, str)
        ancestry = []
        graph = self.get_graph()
        for rev, parents in graph.iter_ancestry([revision_id]):
            ancestry.append(rev)
        ancestry.reverse()
        return [None] + ancestry

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)

    def lookup_revision_id(self, revid):
        """Lookup a revision id.
        
        :param revid: Bazaar revision id.
        :return: Tuple with git revisionid and mapping.
        """
        # Yes, this doesn't really work, but good enough as a stub
        return osutils.sha(rev_id).hexdigest(), self.get_mapping()

    def has_signature_for_revision_id(self, revision_id):
        return False

    def lookup_git_revid(self, bzr_revid):
        try:
            return mapping_registry.revision_id_bzr_to_foreign(bzr_revid)
        except errors.InvalidRevisionId:
            raise errors.NoSuchRevision(self, bzr_revid)

    def get_revision(self, revision_id):
        git_commit_id, mapping = self.lookup_git_revid(revision_id)
        try:
            commit = self._git.commit(git_commit_id)
        except KeyError:
            raise errors.NoSuchRevision(self, revision_id)
        # print "fetched revision:", git_commit_id
        revision = mapping.import_commit(commit)
        assert revision is not None
        return revision

    def has_revision(self, revision_id):
        try:
            self.get_revision(revision_id)
        except errors.NoSuchRevision:
            return False
        else:
            return True

    def get_revisions(self, revids):
        return [self.get_revision(r) for r in revids]

    def revision_trees(self, revids):
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        revision_id = revision.ensure_null(revision_id)
        if revision_id == revision.NULL_REVISION:
            inv = inventory.Inventory(root_id=None)
            inv.revision_id = revision_id
            return revisiontree.RevisionTree(self, inv, revision_id)
        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def set_make_working_trees(self, trees):
        pass

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref,
        progress=None):
        return self._git.fetch_objects(determine_wants, graph_walker, progress)


class GitRevisionTree(revisiontree.RevisionTree):

    def __init__(self, repository, revision_id):
        self._repository = repository
        self._revision_id = revision_id
        assert isinstance(revision_id, str)
        git_id, self.mapping = repository.lookup_git_revid(revision_id)
        try:
            commit = repository._git.commit(git_id)
        except KeyError, r:
            raise errors.NoSuchRevision(repository, revision_id)
        self.tree = commit.tree
        self._inventory = GitInventory(self.tree, self.mapping, repository._git.object_store, revision_id)

    def get_revision_id(self):
        return self._revision_id

    def get_file_text(self, file_id):
        entry = self._inventory[file_id]
        if entry.kind == 'directory': return ""
        return entry.object.data


class GitRepositoryFormat(repository.RepositoryFormat):
    """Git repository format."""

    supports_tree_reference = False
    rich_root_data = True

    def get_format_description(self):
        return "Git Repository"

    def initialize(self, url, shared=False, _internal=False):
        raise bzr_errors.UninitializableFormat(self)

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data

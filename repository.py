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

from bzrlib import (
    errors,
    inventory,
    repository,
    revision,
    )
try:
    from bzrlib.revisiontree import InventoryRevisionTree
except ImportError: # bzr < 2.4
    from bzrlib.revisiontree import RevisionTree as InventoryRevisionTree
from bzrlib.foreign import (
    ForeignRepository,
    )

from bzrlib.plugins.git.commit import (
    GitCommitBuilder,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    foreign_git,
    mapping_registry,
    )
from bzrlib.plugins.git.tree import (
    GitRevisionTree,
    )
from bzrlib.plugins.git.versionedfiles import (
    GitRevisions,
    GitTexts,
    )


from dulwich.objects import (
    Commit,
    Tag,
    ZERO_SHA,
    )


class GitRepository(ForeignRepository):
    """An adapter to git repositories for bzr."""

    _serializer = None
    _commit_builder_class = GitCommitBuilder
    vcs = foreign_git
    chk_bytes = None

    def __init__(self, gitdir, lockfiles):
        ForeignRepository.__init__(self, GitRepositoryFormat(), gitdir, lockfiles)
        from bzrlib.plugins.git import fetch, push
        for optimiser in [fetch.InterRemoteGitNonGitRepository,
                          fetch.InterLocalGitNonGitRepository,
                          fetch.InterGitGitRepository,
                          push.InterToLocalGitRepository,
                          push.InterToRemoteGitRepository]:
            repository.InterRepository.register_optimiser(optimiser)

    def is_shared(self):
        return False

    def supports_rich_root(self):
        return True

    def _warn_if_deprecated(self, branch=None): # for bzr < 2.4
        # This class isn't deprecated
        pass

    def get_mapping(self):
        return default_mapping

    def make_working_trees(self):
        return not self._git.bare

    def revision_graph_can_have_wrong_parents(self):
        return False

    def dfetch(self, source, stop_revision):
        interrepo = repository.InterRepository.get(source, self)
        return interrepo.dfetch(stop_revision)

    def add_signature_text(self, revid, signature):
        raise errors.UnsupportedOperation(self.add_signature_text, self)


class LocalGitRepository(GitRepository):
    """Git repository on the file system."""

    def __init__(self, gitdir, lockfiles):
        GitRepository.__init__(self, gitdir, lockfiles)
        self.base = gitdir.root_transport.base
        self._git = gitdir._git
        self.signatures = None
        self.revisions = GitRevisions(self, self._git.object_store)
        self.inventories = None
        self.texts = GitTexts(self)

    def _iter_revision_ids(self):
        mapping = self.get_mapping()
        for sha in self._git.object_store:
            o = self._git.object_store[sha]
            if not isinstance(o, Commit):
                continue
            rev, roundtrip_revid, verifiers = mapping.import_commit(o,
                mapping.revision_id_foreign_to_bzr)
            yield o.id, rev.revision_id, roundtrip_revid

    def all_revision_ids(self):
        ret = set([])
        for git_sha, revid, roundtrip_revid in self._iter_revision_ids():
            ret.add(revid)
            if roundtrip_revid:
                ret.add(roundtrip_revid)
        return ret

    def get_parent_map(self, revids):
        parent_map = {}
        for revision_id in revids:
            assert isinstance(revision_id, str)
            if revision_id == revision.NULL_REVISION:
                parent_map[revision_id] = ()
                continue
            hexsha, mapping = self.lookup_bzr_revision_id(revision_id)
            try:
                commit = self._git[hexsha]
            except KeyError:
                continue
            parents = [
                self.lookup_foreign_revision_id(p, mapping)
                for p in commit.parents]
            if parents == []:
                parents = [revision.NULL_REVISION]
            parent_map[revision_id] = tuple(parents)
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
        if revision.NULL_REVISION in ancestry:
            ancestry.remove(revision.NULL_REVISION)
        ancestry.reverse()
        return [None] + ancestry

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)

    def pack(self, hint=None, clean_obsolete_packs=False):
        self._git.object_store.pack_loose_objects()

    def lookup_foreign_revision_id(self, foreign_revid, mapping=None):
        """Lookup a revision id.

        """
        assert type(foreign_revid) is str
        if mapping is None:
            mapping = self.get_mapping()
        if foreign_revid == ZERO_SHA:
            return revision.NULL_REVISION
        commit = self._git[foreign_revid]
        while isinstance(commit, Tag):
            commit = self._git[commit.object[1]]
        rev, roundtrip_revid, verifiers = mapping.import_commit(commit,
            mapping.revision_id_foreign_to_bzr)
        # FIXME: check testament before doing this?
        if roundtrip_revid:
            return roundtrip_revid
        else:
            return rev.revision_id

    def has_signature_for_revision_id(self, revision_id):
        return False

    def lookup_bzr_revision_id(self, bzr_revid, mapping=None):
        try:
            return mapping_registry.revision_id_bzr_to_foreign(bzr_revid)
        except errors.InvalidRevisionId:
            if mapping is None:
                mapping = self.get_mapping()
            try:
                return (self._git.refs[mapping.revid_as_refname(bzr_revid)], mapping)
            except KeyError:
                # Update refs from Git commit objects
                # FIXME: Hitting this a lot will be very inefficient...
                for git_sha, revid, roundtrip_revid in self._iter_revision_ids():
                    if not roundtrip_revid:
                        continue
                    refname = mapping.revid_as_refname(roundtrip_revid)
                    self._git.refs[refname] = git_sha
                    if roundtrip_revid == bzr_revid:
                        return git_sha, mapping
                raise errors.NoSuchRevision(self, bzr_revid)

    def get_revision(self, revision_id):
        if not isinstance(revision_id, str):
            raise errors.InvalidRevisionId(revision_id, self)
        git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        try:
            commit = self._git[git_commit_id]
        except KeyError:
            raise errors.NoSuchRevision(self, revision_id)
        revision, roundtrip_revid, verifiers = mapping.import_commit(
            commit, self.lookup_foreign_revision_id)
        assert revision is not None
        # FIXME: check verifiers ?
        if roundtrip_revid:
            revision.revision_id = roundtrip_revid
        return revision

    def has_revision(self, revision_id):
        """See Repository.has_revision."""
        if revision_id == revision.NULL_REVISION:
            return True
        try:
            git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        except errors.NoSuchRevision:
            return False
        return (git_commit_id in self._git)

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions."""
        return set(filter(self.has_revision, revision_ids))

    def get_revisions(self, revids):
        """See Repository.get_revisions."""
        return [self.get_revision(r) for r in revids]

    def revision_trees(self, revids):
        """See Repository.revision_trees."""
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        """See Repository.revision_tree."""
        revision_id = revision.ensure_null(revision_id)
        if revision_id == revision.NULL_REVISION:
            inv = inventory.Inventory(root_id=None)
            inv.revision_id = revision_id
            return InventoryRevisionTree(self, inv, revision_id)
        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def set_make_working_trees(self, trees):
        raise NotImplementedError(self.set_make_working_trees)

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref,
        progress=None):
        return self._git.fetch_objects(determine_wants, graph_walker, progress)

    def _get_versioned_file_checker(self, text_key_references=None, ancestors=None):
        return GitVersionedFileChecker(self,
            text_key_references=text_key_references, ancestors=ancestors)


class GitVersionedFileChecker(repository._VersionedFileChecker):

    file_ids = []

    def _check_file_version_parents(self, texts, progress_bar):
        return {}, []


class GitRepositoryFormat(repository.RepositoryFormat):
    """Git repository format."""

    supports_tree_reference = False
    rich_root_data = True
    supports_leaving_lock = False
    fast_deltas = True
    supports_funky_characters = True
    supports_external_lookups = False
    supports_full_versioned_files = False
    supports_revision_signatures = False
    revision_graph_can_have_wrong_parents = False

    @property
    def _matchingbzrdir(self):
        from bzrlib.plugins.git.dir import LocalGitControlDirFormat
        return LocalGitControlDirFormat()

    def get_format_description(self):
        return "Git Repository"

    def initialize(self, controldir, shared=False, _internal=False):
        from bzrlib.plugins.git.dir import GitDir
        if not isinstance(controldir, GitDir):
            raise errors.UninitializableFormat(self)
        return controldir.open_repository()

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data

    def get_foreign_tests_repository_factory(self):
        from bzrlib.plugins.git.tests.test_repository import (
            ForeignTestsRepositoryFactory,
            )
        return ForeignTestsRepositoryFactory()

    def network_name(self):
        return "git"

# Copyright (C) 2008-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2007 Canonical Ltd
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

"""An adapter between a Git Repository and a Breezy one."""

from io import BytesIO

from dulwich.errors import NotCommitError
from dulwich.object_store import peel_sha, tree_lookup_path
from dulwich.objects import ZERO_SHA, Commit
from vcsgraph import (
    graph as _mod_graph,
)
from vcsgraph import (
    known_graph as _mod_known_graph,
)

from .. import check, errors, lock, repository, trace, transactions, ui
from .. import revision as _mod_revision
from ..decorators import only_raises
from ..foreign import ForeignRepository
from .filegraph import GitFileLastChangeScanner, GitFileParentProvider
from .mapping import default_mapping, encode_git_path, foreign_vcs_git, mapping_registry
from .tree import GitRevisionTree


class GitCheck(check.Check):
    """Check implementation for Git repositories.

    Validates the integrity of Git objects and repository structure.
    """

    def __init__(self, repository, check_repo=True):
        """Initialize a GitCheck instance.

        Args:
            repository: The Git repository to check.
            check_repo: Whether to check the repository itself (default True).
        """
        self.repository = repository
        self.check_repo = check_repo
        self.checked_rev_cnt = 0
        self.object_count = None
        self.problems = []

    def check(self, callback_refs=None, check_repo=True):
        """Perform integrity check on the repository.

        Args:
            callback_refs: Optional dict of callbacks for progress reporting.
            check_repo: Whether to check the repository itself (default True).
        """
        if callback_refs is None:
            callback_refs = {}
        with (
            self.repository.lock_read(),
            ui.ui_factory.nested_progress_bar() as self.progress,
        ):
            shas = set(self.repository._git.object_store)
            self.object_count = len(shas)
            # TODO(jelmer): Check more things
            for i, sha in enumerate(shas):
                self.progress.update("checking objects", i, self.object_count)
                o = self.repository._git.object_store[sha]
                try:
                    o.check()
                except Exception as e:
                    self.problems.append((sha, e))

    def _report_repo_results(self, verbose):
        trace.note(
            "checked repository {} format {}".format(
                self.repository.user_url, self.repository._format
            )
        )
        trace.note("%6d objects", self.object_count)
        for sha, problem in self.problems:
            trace.note("%s: %s", sha, problem)

    def report_results(self, verbose):
        """Report the results of the integrity check.

        Args:
            verbose: Whether to include verbose output.
        """
        if self.check_repo:
            self._report_repo_results(verbose)


for optimiser in [
    "InterRemoteGitNonGitRepository",
    "InterLocalGitNonGitRepository",
    "InterLocalGitLocalGitRepository",
    "InterLocalGitRemoteGitRepository",
    "InterRemoteGitLocalGitRepository",
    "InterToLocalGitRepository",
    "InterToRemoteGitRepository",
]:
    repository.InterRepository.register_lazy_optimiser(
        "breezy.git.interrepo", optimiser
    )


class GitRepository(ForeignRepository):
    """An adapter to git repositories for bzr."""

    vcs = foreign_vcs_git
    chk_bytes = None

    def __init__(self, gitdir):
        """Initialize a GitRepository instance.

        Args:
            gitdir: The Git directory control structure.
        """
        self._transport = gitdir.root_transport
        super().__init__(GitRepositoryFormat(), gitdir, control_files=None)
        self.base = gitdir.root_transport.base
        self._lock_mode = None
        self._lock_count = 0

    def add_fallback_repository(self, basis_url):
        """Add a fallback repository (not supported for Git).

        Args:
            basis_url: URL of the basis repository.

        Raises:
            UnstackableRepositoryFormat: Always raised as Git doesn't support stacking.
        """
        raise errors.UnstackableRepositoryFormat(
            self._format, self.control_transport.base
        )

    def is_shared(self):
        """Check if this repository is shared.

        Returns:
            bool: Always False for Git repositories.
        """
        return False

    def get_physical_lock_status(self):
        """Get the physical lock status.

        Returns:
            bool: Always False as Git doesn't use physical locks.
        """
        return False

    def lock_write(self):
        """See Branch.lock_write()."""
        if self._lock_mode:
            if self._lock_mode != "w":
                raise errors.ReadOnlyError(self)
            self._lock_count += 1
        else:
            self._lock_mode = "w"
            self._lock_count = 1
            self._transaction = transactions.WriteTransaction()
        return repository.RepositoryWriteLockResult(self.unlock, None)

    def break_lock(self):
        """Break any existing lock (not implemented for Git).

        Raises:
            NotImplementedError: Always raised.
        """
        raise NotImplementedError(self.break_lock)

    def dont_leave_lock_in_place(self):
        """Configure to not leave locks in place (not implemented).

        Raises:
            NotImplementedError: Always raised.
        """
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def leave_lock_in_place(self):
        """Configure to leave locks in place (not implemented).

        Raises:
            NotImplementedError: Always raised.
        """
        raise NotImplementedError(self.leave_lock_in_place)

    def lock_read(self):
        """Acquire a read lock on the repository.

        Returns:
            LogicalLockResult: Lock result that can be used to unlock.
        """
        if self._lock_mode:
            if self._lock_mode not in ("r", "w"):
                raise AssertionError
            self._lock_count += 1
        else:
            self._lock_mode = "r"
            self._lock_count = 1
            self._transaction = transactions.ReadOnlyTransaction()
        return lock.LogicalLockResult(self.unlock)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        """Release a lock on the repository.

        Raises:
            LockNotHeld: If no lock is currently held.
            BzrError: If attempting to unlock with an active write group.
        """
        if self._lock_count == 0:
            raise errors.LockNotHeld(self)
        if self._lock_count == 1 and self._lock_mode == "w":
            if self._write_group is not None:
                self.abort_write_group()
                self._lock_count -= 1
                self._lock_mode = None
                raise errors.BzrError(
                    "Must end write groups before releasing write locks."
                )
        self._lock_count -= 1
        if self._lock_count == 0:
            self._lock_mode = None
            transaction = self._transaction
            self._transaction = None
            transaction.finish()
            # Don't close _git here - with the property-based store access,
            # trees may access the object store after unlock. The object store
            # will be closed when _git is garbage collected, and Pack objects
            # will warn via ResourceWarning if not properly closed.

    def is_write_locked(self):
        """Check if the repository is write locked.

        Returns:
            bool: True if write locked, False otherwise.
        """
        return self._lock_mode == "w"

    def is_locked(self):
        """Check if the repository is locked.

        Returns:
            bool: True if locked (read or write), False otherwise.
        """
        return self._lock_mode is not None

    def get_transaction(self):
        """See Repository.get_transaction()."""
        if self._transaction is None:
            return transactions.PassThroughTransaction()
        else:
            return self._transaction

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from ..reconcile import ReconcileResult

        ret = ReconcileResult()
        ret.aborted = False
        return ret

    def supports_rich_root(self):
        """Check if the repository supports rich root data.

        Returns:
            bool: Always True for Git repositories.
        """
        return True

    def get_mapping(self):
        """Get the default Git-to-Bazaar mapping.

        Returns:
            The default mapping object for Git repositories.
        """
        return default_mapping

    def make_working_trees(self):
        """Check if this repository creates working trees (not implemented).

        Raises:
            NotImplementedError: Always raised for base GitRepository.
        """
        raise NotImplementedError(self.make_working_trees)

    def revision_graph_can_have_wrong_parents(self):
        """Check if revision graph can have incorrect parents.

        Returns:
            bool: Always False for Git repositories.
        """
        return False

    def add_signature_text(self, revid, signature):
        """Add a signature text for a revision (not supported).

        Args:
            revid: Revision ID to sign.
            signature: Signature text.

        Raises:
            UnsupportedOperation: Always raised.
        """
        raise errors.UnsupportedOperation(self.add_signature_text, self)

    def sign_revision(self, revision_id, gpg_strategy):
        """Sign a revision (not supported).

        Args:
            revision_id: ID of revision to sign.
            gpg_strategy: GPG strategy to use.

        Raises:
            UnsupportedOperation: Always raised.
        """
        raise errors.UnsupportedOperation(self.add_signature_text, self)


class LocalGitRepository(GitRepository):
    """Git repository on the file system."""

    def __init__(self, gitdir):
        """Initialize a LocalGitRepository instance.

        Args:
            gitdir: The Git directory control structure.
        """
        GitRepository.__init__(self, gitdir)
        self._git = gitdir._git
        self._file_change_scanner = GitFileLastChangeScanner(self)
        self._transaction = None

    def get_commit_builder(
        self,
        branch,
        parents,
        config,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this repository.

        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        from .commit import GitCommitBuilder

        builder = GitCommitBuilder(
            self,
            parents,
            config,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy,
        )
        self.start_write_group()
        return builder

    def _write_git_config(self, cs):
        f = BytesIO()
        cs.write_to_file(f)
        self._git._put_named_file("config", f.getvalue())

    def get_file_graph(self):
        """Get the file graph for this repository.

        Returns:
            Graph: A graph of file relationships.
        """
        return _mod_graph.Graph(GitFileParentProvider(self._file_change_scanner))

    def iter_files_bytes(self, desired_files):
        """Iterate through file versions.

        Files will not necessarily be returned in the order they occur in
        desired_files.  No specific order is guaranteed.

        Yields pairs of identifier, bytes_iterator.  identifier is an opaque
        value supplied by the caller as part of desired_files.  It should
        uniquely identify the file version in the caller's context.  (Examples:
        an index number or a TreeTransform trans_id.)

        bytes_iterator is an iterable of bytestrings for the file.  The
        kind of iterable and length of the bytestrings are unspecified, but for
        this implementation, it is a list of bytes produced by
        VersionedFile.get_record_stream().

        :param desired_files: a list of (file_id, revision_id, identifier)
            triples
        """
        per_revision = {}
        for file_id, revision_id, identifier in desired_files:
            per_revision.setdefault(revision_id, []).append((file_id, identifier))
        for revid, files in per_revision.items():
            try:
                (commit_id, mapping) = self.lookup_bzr_revision_id(revid)
            except errors.NoSuchRevision as err:
                raise errors.RevisionNotPresent(revid, self) from err
            try:
                commit = self._git.object_store[commit_id]
            except KeyError as err:
                raise errors.RevisionNotPresent(revid, self) from err
            root_tree = commit.tree
            for fileid, identifier in files:
                try:
                    path = mapping.parse_file_id(fileid)
                except ValueError as err:
                    raise errors.RevisionNotPresent((fileid, revid), self) from err
                try:
                    _mode, item_id = tree_lookup_path(
                        self._git.object_store.__getitem__,
                        root_tree,
                        encode_git_path(path),
                    )
                    obj = self._git.object_store[item_id]
                except KeyError as err:
                    raise errors.RevisionNotPresent((fileid, revid), self) from err
                else:
                    if obj.type_name == b"tree":
                        yield (identifier, [])
                    elif obj.type_name == b"blob":
                        yield (identifier, obj.chunked)
                    else:
                        raise AssertionError(f"file text resolved to {obj!r}")

    def gather_stats(self, revid=None, committers=None):
        """See Repository.gather_stats()."""
        result = super().gather_stats(revid, committers)
        revs = []
        for sha in self._git.object_store:
            o = self._git.object_store[sha]
            if o.type_name == b"commit":
                revs.append(o.id)
        result["revisions"] = len(revs)
        return result

    def _iter_revision_ids(self):
        mapping = self.get_mapping()
        for sha in self._git.object_store:
            o = self._git.object_store[sha]
            if not isinstance(o, Commit):
                continue
            revid = mapping.revision_id_foreign_to_bzr(o.id)
            yield o.id, revid

    def all_revision_ids(self):
        """Get all revision IDs in the repository.

        Returns:
            list: All revision IDs in the repository.
        """
        ret = set()
        for _git_sha, revid in self._iter_revision_ids():
            ret.add(revid)
        return list(ret)

    def _get_parents(self, revid, no_alternates=False):
        if not isinstance(revid, bytes):
            raise ValueError
        try:
            (hexsha, mapping) = self.lookup_bzr_revision_id(revid)
        except errors.NoSuchRevision:
            return None
        # FIXME: Honor no_alternates setting
        try:
            commit = self._git.object_store[hexsha]
        except KeyError:
            return None
        ret = []
        for p in commit.parents:
            try:
                ret.append(self.lookup_foreign_revision_id(p, mapping))
            except KeyError:
                ret.append(mapping.revision_id_foreign_to_bzr(p))
        return ret

    def _get_parent_map_no_fallbacks(self, revids):
        return self.get_parent_map(revids, no_alternates=True)

    def get_parent_map(self, revids, no_alternates=False):
        """Get a map of revision IDs to their parents.

        Args:
            revids: Revision IDs to get parents for.
            no_alternates: Whether to exclude alternate repositories.

        Returns:
            dict: Map of revision ID to tuple of parent IDs.
        """
        parent_map = {}
        for revision_id in revids:
            parents = self._get_parents(revision_id, no_alternates=no_alternates)
            if revision_id == _mod_revision.NULL_REVISION:
                parent_map[revision_id] = ()
                continue
            if parents is None:
                continue
            if len(parents) == 0:
                parents = [_mod_revision.NULL_REVISION]
            parent_map[revision_id] = tuple(parents)
        return parent_map

    def get_known_graph_ancestry(self, revision_ids):
        """Return the known graph for a set of revision ids and their ancestors."""
        pending = set(revision_ids)
        parent_map = {}
        while pending:
            this_parent_map = {}
            for revid in pending:
                if revid == _mod_revision.NULL_REVISION:
                    continue
                parents = self._get_parents(revid)
                if parents is not None:
                    this_parent_map[revid] = parents
            parent_map.update(this_parent_map)
            pending = set()
            for values in this_parent_map.values():
                pending.update(values)
            pending = pending.difference(parent_map)
        return _mod_known_graph.KnownGraph(parent_map)

    def get_signature_text(self, revision_id):
        """Get the GPG signature text for a revision.

        Args:
            revision_id: ID of the revision.

        Returns:
            bytes: The GPG signature text.

        Raises:
            NoSuchRevision: If revision not found or has no signature.
        """
        git_commit_id, _mapping = self.lookup_bzr_revision_id(revision_id)
        try:
            commit = self._git.object_store[git_commit_id]
        except KeyError as err:
            raise errors.NoSuchRevision(self, revision_id) from err
        if commit.gpgsig is None:
            raise errors.NoSuchRevision(self, revision_id)
        return commit.gpgsig

    def check(self, revision_ids=None, callback_refs=None, check_repo=True):
        """Check the consistency of the repository.

        Args:
            revision_ids: Specific revision IDs to check (unused).
            callback_refs: Callback references for progress.
            check_repo: Whether to check the repository.

        Returns:
            GitCheck: The check result object.
        """
        result = GitCheck(self, check_repo=check_repo)
        result.check(callback_refs)
        return result

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Pack loose objects in the repository.

        Args:
            hint: Hint about what to pack (unused).
            clean_obsolete_packs: Whether to clean obsolete packs (unused).
        """
        self._git.object_store.pack_loose_objects()

    def lookup_foreign_revision_id(self, foreign_revid, mapping=None):
        """Lookup a revision id.

        :param foreign_revid: Foreign revision id to look up
        :param mapping: Mapping to use (use default mapping if not specified)
        :raise KeyError: If foreign revision was not found
        :return: bzr revision id
        """
        if not isinstance(foreign_revid, bytes):
            raise TypeError(foreign_revid)
        if mapping is None:
            mapping = self.get_mapping()
        if foreign_revid == ZERO_SHA:
            return _mod_revision.NULL_REVISION
        _unpeeled, peeled = peel_sha(self._git.object_store, foreign_revid)
        if not isinstance(peeled, Commit):
            raise NotCommitError(peeled.id)
        revid = mapping.get_revision_id(peeled)
        # FIXME: check testament before doing this?
        return revid

    def has_signature_for_revision_id(self, revision_id):
        """Check whether a GPG signature is present for this revision.

        This is never the case for Git repositories.
        """
        try:
            self.get_signature_text(revision_id)
        except errors.NoSuchRevision:
            return False
        else:
            return True

    def verify_revision_signature(self, revision_id, gpg_strategy):
        """Verify the signature on a revision.

        :param revision_id: the revision to verify
        :gpg_strategy: the GPGStrategy object to used

        :return: gpg.SIGNATURE_VALID or a failed SIGNATURE_ value
        """
        from breezy import gpg

        with self.lock_read():
            git_commit_id, _mapping = self.lookup_bzr_revision_id(revision_id)
            try:
                commit = self._git.object_store[git_commit_id]
            except KeyError as err:
                raise errors.NoSuchRevision(self, revision_id) from err

            if commit.gpgsig is None:
                return gpg.SIGNATURE_NOT_SIGNED, None

            without_sig = Commit.from_string(commit.as_raw_string())
            without_sig.gpgsig = None

            (result, key, _plain_text) = gpg_strategy.verify(
                without_sig.as_raw_string(), commit.gpgsig
            )
            return (result, key)

    def lookup_bzr_revision_id(self, bzr_revid, mapping=None):
        """Lookup a bzr revision id in a Git repository.

        :param bzr_revid: Bazaar revision id
        :param mapping: Optional mapping to use
        :return: Tuple with git commit id, mapping that was used and supplement
            details
        """
        try:
            (git_sha, mapping) = mapping_registry.revision_id_bzr_to_foreign(bzr_revid)
        except errors.InvalidRevisionId as err:
            raise errors.NoSuchRevision(self, bzr_revid) from err
        else:
            return (git_sha, mapping)

    def get_revision(self, revision_id):
        """Get a revision object by ID.

        Args:
            revision_id: The revision ID to retrieve.

        Returns:
            Revision: The revision object.

        Raises:
            InvalidRevisionId: If revision_id is not bytes.
            NoSuchRevision: If revision not found.
        """
        if not isinstance(revision_id, bytes):
            raise errors.InvalidRevisionId(revision_id, self)
        git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        try:
            commit = self._git.object_store[git_commit_id]
        except KeyError as err:
            raise errors.NoSuchRevision(self, revision_id) from err
        revision, roundtrip_revid, _verifiers = mapping.import_commit(
            commit, self.lookup_foreign_revision_id, strict=False
        )
        if revision is None:
            raise AssertionError
        # FIXME: check verifiers ?
        if roundtrip_revid:
            revision.revision_id = roundtrip_revid
        return revision

    def has_revision(self, revision_id):
        """See Repository.has_revision."""
        if revision_id == _mod_revision.NULL_REVISION:
            return True
        try:
            git_commit_id, _mapping = self.lookup_bzr_revision_id(revision_id)
        except errors.NoSuchRevision:
            return False
        return git_commit_id in self._git

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions."""
        return set(filter(self.has_revision, revision_ids))

    def iter_revisions(self, revision_ids):
        """See Repository.get_revisions."""
        for revid in revision_ids:
            try:
                rev = self.get_revision(revid)
            except errors.NoSuchRevision:
                rev = None
            yield (revid, rev)

    def revision_trees(self, revids):
        """See Repository.revision_trees."""
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        """See Repository.revision_tree."""
        if revision_id is None:
            raise ValueError(f"invalid revision id {revision_id}")
        return GitRevisionTree(self, revision_id)

    def set_make_working_trees(self, trees):
        """Set whether to make working trees (not supported).

        Args:
            trees: Whether to make working trees.

        Raises:
            UnsupportedOperation: Always raised.
        """
        raise errors.UnsupportedOperation(self.set_make_working_trees, self)

    def make_working_trees(self):
        """Check if this repository creates working trees.

        Returns:
            bool: True if not a bare repository, False otherwise.
        """
        return not self._git.get_config().get_boolean(("core",), "bare")


class GitRepositoryFormat(repository.RepositoryFormat):
    """Git repository format."""

    supports_versioned_directories = False
    supports_tree_reference = True
    rich_root_data = True
    supports_leaving_lock = False
    fast_deltas = True
    supports_funky_characters = True
    supports_external_lookups = False
    supports_full_versioned_files = False
    supports_revision_signatures = False
    supports_nesting_repositories = False
    revision_graph_can_have_wrong_parents = False
    supports_unreferenced_revisions = True
    supports_setting_revision_ids = False
    supports_storing_branch_nick = False
    supports_overriding_transport = False
    supports_custom_revision_properties = False
    records_per_file_revision = False
    supports_multiple_authors = False
    supports_ghosts = False
    supports_chks = False

    @property
    def _matchingcontroldir(self):
        from .dir import LocalGitControlDirFormat

        return LocalGitControlDirFormat()

    def get_format_description(self):
        """Get a human-readable description of the format.

        Returns:
            str: "Git Repository".
        """
        return "Git Repository"

    def initialize(self, controldir, shared=False, _internal=False):
        """Initialize a repository in a control directory.

        Args:
            controldir: The control directory to initialize in.
            shared: Whether the repository should be shared (unused).
            _internal: Internal flag (unused).

        Returns:
            GitRepository: The opened repository.

        Raises:
            UninitializableFormat: If controldir is not a GitDir.
        """
        from .dir import GitDir

        if not isinstance(controldir, GitDir):
            raise errors.UninitializableFormat(self)
        return controldir.open_repository()

    def check_conversion_target(self, target_repo_format):
        """Check if format can be converted to target format.

        Args:
            target_repo_format: The target repository format.

        Returns:
            bool: True if target supports rich root data.
        """
        return target_repo_format.rich_root_data

    def get_foreign_tests_repository_factory(self):
        """Get a factory for foreign tests repositories.

        Returns:
            ForeignTestsRepositoryFactory: The test repository factory.
        """
        from .tests.test_repository import ForeignTestsRepositoryFactory

        return ForeignTestsRepositoryFactory()

    def network_name(self):
        """Get the network name for this format.

        Returns:
            bytes: b"git".
        """
        return b"git"


def get_extra_interrepo_test_combinations():
    """Get extra test combinations for inter-repository operations.

    Returns:
        list: Tuples of (InterRepository class, source format, target format).
    """
    from ..bzr.groupcompress_repo import RepositoryFormat2a
    from . import interrepo

    return [
        (
            interrepo.InterLocalGitNonGitRepository,
            GitRepositoryFormat(),
            RepositoryFormat2a(),
        ),
        (
            interrepo.InterLocalGitLocalGitRepository,
            GitRepositoryFormat(),
            GitRepositoryFormat(),
        ),
        (
            interrepo.InterToLocalGitRepository,
            RepositoryFormat2a(),
            GitRepositoryFormat(),
        ),
    ]

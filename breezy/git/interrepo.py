# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""InterRepository operations."""

import itertools
from collections.abc import Callable

from dulwich.errors import NotCommitError
from dulwich.object_store import ObjectStoreGraphWalker
from dulwich.objects import ObjectID
from dulwich.pack import PACK_SPOOL_FILE_MAX_SIZE
from dulwich.protocol import CAPABILITY_THIN_PACK, PEELED_TAG_SUFFIX, ZERO_SHA
from dulwich.refs import SYMREF
from dulwich.walk import Walker

from .. import config, trace, ui
from ..errors import (
    DivergedBranches,
    FetchLimitUnsupported,
    InvalidRevisionId,
    LossyPushToSameVCS,
    NoRoundtrippingSupport,
    NoSuchRevision,
)
from ..repository import AbstractSearchResult, FetchResult, InterRepository
from ..revision import NULL_REVISION, RevisionID
from .errors import NoPushSupport
from .fetch import DetermineWantsRecorder, import_git_objects
from .mapping import needs_roundtripping
from .object_store import get_object_store
from .push import MissingObjectsIterator, remote_divergence
from .refs import is_tag, ref_to_tag_name
from .remote import RemoteGitError, RemoteGitRepository
from .repository import GitRepository, GitRepositoryFormat, LocalGitRepository
from .unpeel_map import UnpeelMap

EitherId = tuple[RevisionID | None, ObjectID | None]
EitherRefDict = dict[bytes, EitherId]
RevidMap = dict[RevisionID, tuple[ObjectID, RevisionID]]


class InterToGitRepository(InterRepository):
    """InterRepository that copies into a Git repository."""

    _matching_repo_format = GitRepositoryFormat()

    def __init__(self, source, target):
        super().__init__(source, target)
        self.mapping = self.target.get_mapping()
        self.source_store = get_object_store(self.source, self.mapping)

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id=revision_id, find_ghosts=False)

    def fetch_refs(
        self,
        update_refs: Callable[[dict[bytes, ObjectID]], dict[bytes, ObjectID]],
        lossy: bool,
        overwrite: bool = False,
    ) -> tuple[RevidMap, dict[bytes, ObjectID]]:
        """Fetch possibly roundtripped revisions into the target repository
        and update refs.

        :param update_refs: Generate refs to fetch. Receives dictionary
            with old refs (git shas), returns dictionary of new names to
            git shas.
        :param lossy: Whether to roundtrip
        :return: old refs, new refs
        """
        raise NotImplementedError(self.fetch_refs)

    def search_missing_revision_ids(
        self, find_ghosts=True, revision_ids=None, if_present_ids=None, limit=None
    ):
        if limit is not None:
            raise FetchLimitUnsupported(self)
        git_shas = []
        todo = []
        if revision_ids:
            todo.extend(revision_ids)
        if if_present_ids:
            todo.extend(revision_ids)
        with self.source_store.lock_read():
            for revid in revision_ids:
                if revid == NULL_REVISION:
                    continue
                try:
                    git_sha = self.source_store._lookup_revision_sha1(revid)
                except KeyError:
                    raise NoSuchRevision(revid, self.source)
                git_shas.append(git_sha)
            walker = Walker(
                self.source_store,
                include=git_shas,
                exclude=[
                    sha
                    for sha in self.target.controldir.get_refs_container()
                    .as_dict()
                    .values()
                    if sha != ZERO_SHA
                ],
            )
            missing_revids = set()
            for entry in walker:
                for kind, type_data in self.source_store.lookup_git_sha(
                    entry.commit.id
                ):
                    if kind == "commit":
                        missing_revids.add(type_data[0])
            return self.source.revision_ids_to_search_result(missing_revids)

    def _warn_slow(self):
        if not config.GlobalConfig().suppress_warning("slow_intervcs_push"):
            trace.warning(
                "Pushing from a Bazaar to a Git repository. "
                "For better performance, push into a Bazaar repository."
            )


class InterToLocalGitRepository(InterToGitRepository):
    """InterBranch implementation between a Bazaar and a Git repository."""

    target: LocalGitRepository

    def __init__(self, source, target):
        super().__init__(source, target)
        self.target_store = self.target.controldir._git.object_store
        self.target_refs = self.target.controldir._git.refs

    def _commit_needs_fetching(self, sha_id):
        try:
            return sha_id not in self.target_store
        except NoSuchRevision:
            # Ghost, can't push
            return False

    def _revision_needs_fetching(self, sha_id, revid):
        if revid == NULL_REVISION:
            return False
        if sha_id is None:
            try:
                sha_id = self.source_store._lookup_revision_sha1(revid)
            except KeyError:
                return False
        return self._commit_needs_fetching(sha_id)

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
        for sha1, revid in stop_revisions:
            if sha1 is not None and revid is not None:
                revid_sha_map[revid] = sha1
                stop_revids.append(revid)
            elif sha1 is not None:
                if self._commit_needs_fetching(sha1):
                    for _kind, (
                        revid,
                        _tree_sha,
                        _verifiers,
                    ) in self.source_store.lookup_git_sha(sha1):
                        revid_sha_map[revid] = sha1
                        stop_revids.append(revid)
            else:
                if revid is None:
                    raise AssertionError
                stop_revids.append(revid)
        missing = set()
        graph = self.source.get_graph()
        with ui.ui_factory.nested_progress_bar() as pb:
            while stop_revids:
                new_stop_revids = []
                for revid in stop_revids:
                    sha1 = revid_sha_map.get(revid)
                    if revid not in missing and self._revision_needs_fetching(
                        sha1, revid
                    ):
                        missing.add(revid)
                        new_stop_revids.append(revid)
                stop_revids = set()
                parent_map = graph.get_parent_map(new_stop_revids)
                for parent_revids in parent_map.values():
                    stop_revids.update(parent_revids)
                pb.update("determining revisions to fetch", len(missing))
        return graph.iter_topo_order(missing)

    def _get_target_either_refs(self) -> EitherRefDict:
        """Return a dictionary with references.

        :return: Dictionary with reference names as keys and tuples
            with Git SHA, Bazaar revid as values.
        """
        bzr_refs = {}
        for k in self.target._git.refs.allkeys():
            try:
                v = self.target._git.refs.read_ref(k)
            except KeyError:
                # broken symref?
                continue
            revid = None
            if v and not v.startswith(SYMREF):
                try:
                    for kind, type_data in self.source_store.lookup_git_sha(v):
                        if kind == "commit" and self.source.has_revision(type_data[0]):
                            revid = type_data[0]
                            break
                except KeyError:
                    pass
            bzr_refs[k] = (v, revid)
        return bzr_refs

    def fetch_refs(self, update_refs, lossy, overwrite: bool = False):
        self._warn_slow()
        result_refs = {}
        with self.source_store.lock_read():
            old_refs = self._get_target_either_refs()
            new_refs = update_refs(old_refs)
            revidmap = self.fetch_revs(
                [
                    (git_sha, bzr_revid)
                    for (git_sha, bzr_revid) in new_refs.values()
                    if git_sha is None or not git_sha.startswith(SYMREF)
                ],
                lossy=lossy,
            )
            for name, (gitid, revid) in new_refs.items():
                if gitid is None:
                    try:
                        gitid = revidmap[revid][0]
                    except KeyError:
                        gitid = self.source_store._lookup_revision_sha1(revid)
                if gitid.startswith(SYMREF):
                    self.target_refs.set_symbolic_ref(name, gitid[len(SYMREF) :])
                else:
                    try:
                        old_git_id = old_refs[name][0]
                    except KeyError:
                        self.target_refs.add_if_new(name, gitid)
                    else:
                        self.target_refs.set_if_equals(name, old_git_id, gitid)
                    result_refs[name] = (
                        gitid,
                        revid
                        if not lossy
                        else self.mapping.revision_id_foreign_to_bzr(gitid),
                    )
        return revidmap, old_refs, result_refs

    def fetch_revs(self, revs, lossy: bool, limit: int | None = None) -> RevidMap:
        if not lossy and not self.mapping.roundtripping:
            for _git_sha, bzr_revid in revs:
                if bzr_revid is not None and needs_roundtripping(
                    self.source, bzr_revid
                ):
                    raise NoPushSupport(
                        self.source, self.target, self.mapping, bzr_revid
                    )
        with self.source_store.lock_read():
            todo = list(self.missing_revisions(revs))[:limit]
            revidmap = {}
            with ui.ui_factory.nested_progress_bar() as pb:
                object_generator = MissingObjectsIterator(
                    self.source_store, self.source, pb
                )
                for old_revid, git_sha in object_generator.import_revisions(
                    todo, lossy=lossy
                ):
                    if lossy:
                        new_revid = self.mapping.revision_id_foreign_to_bzr(git_sha)
                    else:
                        new_revid = old_revid
                        try:
                            self.mapping.revision_id_bzr_to_foreign(old_revid)
                        except InvalidRevisionId:
                            pass
                    revidmap[old_revid] = (git_sha, new_revid)
                self.target_store.add_objects(object_generator)
                return revidmap

    def fetch(
        self, revision_id=None, find_ghosts: bool = False, lossy=False, fetch_spec=None
    ) -> FetchResult:
        if revision_id is not None:
            stop_revisions = [(None, revision_id)]
        elif fetch_spec is not None:
            recipe = fetch_spec.get_recipe()
            if recipe[0] in ("search", "proxy-search"):
                stop_revisions = [(None, revid) for revid in recipe[1]]
            else:
                raise AssertionError(
                    "Unsupported search result type {}".format(recipe[0])
                )
        else:
            stop_revisions = [(None, revid) for revid in self.source.all_revision_ids()]
        self._warn_slow()
        try:
            revidmap = self.fetch_revs(stop_revisions, lossy=lossy)
        except NoPushSupport:
            raise NoRoundtrippingSupport(self.source, self.target)
        return FetchResult(revidmap)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return not isinstance(source, GitRepository) and isinstance(
            target, LocalGitRepository
        )


class InterToRemoteGitRepository(InterToGitRepository):
    target: RemoteGitRepository

    def fetch_refs(self, update_refs, lossy, overwrite: bool = False):
        """Import the gist of the ancestry of a particular revision."""
        if not lossy and not self.mapping.roundtripping:
            raise NoPushSupport(self.source, self.target, self.mapping)

        unpeel_map = UnpeelMap.from_repository(self.source)
        revidmap: dict[bytes, bytes] = {}

        def git_update_refs(old_refs):
            ret = {}
            self.old_refs = {k: (v, None) for (k, v) in old_refs.items()}
            new_refs = update_refs(self.old_refs)
            for name, (gitid, revid) in new_refs.items():
                if gitid is None:
                    git_sha = self.source_store._lookup_revision_sha1(revid)
                    gitid = unpeel_map.re_unpeel_tag(git_sha, old_refs.get(name))
                if not overwrite:
                    if remote_divergence(old_refs.get(name), gitid, self.source_store):
                        raise DivergedBranches(self.source, self.target)
                ret[name] = gitid
            return ret

        self._warn_slow()
        with self.source_store.lock_read():
            result = self.target.send_pack(
                git_update_refs, self.source_store.generate_lossy_pack_data
            )
            for ref, error in result.ref_status.items():
                if error:
                    raise RemoteGitError(
                        "unable to update ref {!r}: {}".format(ref, error)
                    )
            new_refs = result.refs
        # FIXME: revidmap?
        return revidmap, self.old_refs, new_refs

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return not isinstance(source, GitRepository) and isinstance(
            target, RemoteGitRepository
        )


class GitSearchResult(AbstractSearchResult):
    def __init__(self, start, exclude, keys):
        self._start = start
        self._exclude = exclude
        self._keys = keys

    def get_keys(self):
        return self._keys

    def get_recipe(self):
        return ("search", self._start, self._exclude, len(self._keys))


class InterFromGitRepository(InterRepository):
    _matching_repo_format = GitRepositoryFormat()

    def _target_has_shas(self, shas):
        raise NotImplementedError(self._target_has_shas)

    def get_determine_wants_heads(self, wants, include_tags=False, tag_selector=None):
        wants = set(wants)

        def determine_wants(refs, depth=None):
            unpeel_lookup = {}
            for k, v in refs.items():
                if k.endswith(PEELED_TAG_SUFFIX):
                    unpeel_lookup[v] = refs[k[: -len(PEELED_TAG_SUFFIX)]]
            potential = {unpeel_lookup.get(w, w) for w in wants}
            if include_tags:
                for k, sha in refs.items():
                    if k.endswith(PEELED_TAG_SUFFIX):
                        continue
                    try:
                        tag_name = ref_to_tag_name(k)
                    except ValueError:
                        continue
                    if tag_selector and not tag_selector(tag_name):
                        continue
                    if sha == ZERO_SHA:
                        continue
                    potential.add(sha)
            return list(potential - self._target_has_shas(potential))

        return determine_wants

    def determine_wants_all(self, refs):
        raise NotImplementedError(self.determine_wants_all)

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, find_ghosts=False)

    def search_missing_revision_ids(
        self, find_ghosts=True, revision_ids=None, if_present_ids=None, limit=None
    ):
        if limit is not None:
            raise FetchLimitUnsupported(self)
        if revision_ids is None and if_present_ids is None:
            todo = set(self.source.all_revision_ids())
        else:
            todo = set()
            if revision_ids is not None:
                for revid in revision_ids:
                    if not self.source.has_revision(revid):
                        raise NoSuchRevision(revid, self.source)
                todo.update(revision_ids)
            if if_present_ids is not None:
                todo.update(if_present_ids)
        result_set = todo.difference(self.target.all_revision_ids())
        result_parents = set(
            itertools.chain.from_iterable(
                self.source.get_graph().get_parent_map(result_set).values()
            )
        )
        included_keys = result_set.intersection(result_parents)
        start_keys = result_set.difference(included_keys)
        exclude_keys = result_parents.difference(result_set)
        return GitSearchResult(start_keys, exclude_keys, result_set)


class InterGitNonGitRepository(InterFromGitRepository):
    """Base InterRepository that copies revisions from a Git into a non-Git
    repository.
    """

    def _target_has_shas(self, shas):
        revids = {}
        for sha in shas:
            try:
                revid = self.source.lookup_foreign_revision_id(sha)
            except NotCommitError:
                # Commit is definitely not present
                continue
            else:
                revids[revid] = sha
        return {revids[r] for r in self.target.has_revisions(revids)}

    def determine_wants_all(self, refs, depth=None):
        potential = set()
        for k, v in refs.items():
            # For non-git target repositories, only worry about peeled
            if v == ZERO_SHA:
                continue
            potential.add(self.source.controldir.get_peeled(k) or v)
        return list(potential - self._target_has_shas(potential))

    def _warn_slow(self):
        if not config.GlobalConfig().suppress_warning("slow_intervcs_push"):
            trace.warning(
                "Fetching from Git to Bazaar repository. "
                "For better performance, fetch into a Git repository."
            )

    def fetch_objects(self, determine_wants, mapping, limit=None, lossy=False):
        """Fetch objects from a remote server.

        :param determine_wants: determine_wants callback
        :param mapping: BzrGitMapping to use
        :param limit: Maximum number of commits to import.
        :return: Tuple with pack hint, last imported revision id and remote
            refs
        """
        raise NotImplementedError(self.fetch_objects)

    def get_determine_wants_revids(self, revids, include_tags=False, tag_selector=None):
        wants = set()
        for revid in set(revids):
            if self.target.has_revision(revid):
                continue
            git_sha, _mapping = self.source.lookup_bzr_revision_id(revid)
            wants.add(git_sha)
        return self.get_determine_wants_heads(
            wants, include_tags=include_tags, tag_selector=tag_selector
        )

    def fetch(
        self,
        revision_id=None,
        find_ghosts=False,
        mapping=None,
        fetch_spec=None,
        include_tags=False,
        lossy=False,
    ):
        if mapping is None:
            mapping = self.source.get_mapping()
        if revision_id is not None:
            interesting_heads = [revision_id]
        elif fetch_spec is not None:
            recipe = fetch_spec.get_recipe()
            if recipe[0] in ("search", "proxy-search"):
                interesting_heads = recipe[1]
            else:
                raise AssertionError(
                    "Unsupported search result type {}".format(recipe[0])
                )
        else:
            interesting_heads = None

        if interesting_heads is not None:
            determine_wants = self.get_determine_wants_revids(
                interesting_heads, include_tags=include_tags
            )
        else:
            determine_wants = self.determine_wants_all

        (pack_hint, _, remote_refs) = self.fetch_objects(
            determine_wants, mapping, lossy=lossy
        )
        if pack_hint is not None and self.target._format.pack_compresses:
            self.target.pack(hint=pack_hint)
        result = FetchResult()
        result.refs = remote_refs
        return result


class InterRemoteGitNonGitRepository(InterGitNonGitRepository):
    """InterRepository that copies revisions from a remote Git into a non-Git
    repository.
    """

    def get_target_heads(self):
        # FIXME: This should be more efficient
        all_revs = self.target.all_revision_ids()
        parent_map = self.target.get_parent_map(all_revs)
        all_parents = set()
        for values in parent_map.values():
            all_parents.update(values)
        return set(all_revs) - all_parents

    def fetch_objects(self, determine_wants, mapping, limit=None, lossy=False):
        """See `InterGitNonGitRepository`."""
        self._warn_slow()
        store = get_object_store(self.target, mapping)
        with store.lock_write():
            heads = self.get_target_heads()
            graph_walker = ObjectStoreGraphWalker(
                [store._lookup_revision_sha1(head) for head in heads],
                lambda sha: store[sha].parents,
            )
            wants_recorder = DetermineWantsRecorder(determine_wants)

            with ui.ui_factory.nested_progress_bar() as pb:
                objects_iter = self.source.fetch_objects(
                    wants_recorder, graph_walker, store.get_raw
                )
                trace.mutter("Importing %d new revisions", len(wants_recorder.wants))
                (pack_hint, last_rev) = import_git_objects(
                    self.target,
                    mapping,
                    objects_iter,
                    store,
                    wants_recorder.wants,
                    pb,
                    limit,
                )
                return (pack_hint, last_rev, wants_recorder.remote_refs)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        if not isinstance(source, RemoteGitRepository):
            return False
        if not target.supports_rich_root():
            return False
        if isinstance(target, GitRepository):
            return False
        return getattr(target._format, "supports_full_versioned_files", True)


class InterLocalGitNonGitRepository(InterGitNonGitRepository):
    """InterRepository that copies revisions from a local Git into a non-Git
    repository.
    """

    def fetch_objects(self, determine_wants, mapping, limit=None, lossy=False):
        """See `InterGitNonGitRepository`."""
        self._warn_slow()
        remote_refs = self.source.controldir.get_refs_container().as_dict()
        wants = determine_wants(remote_refs)
        target_git_object_retriever = get_object_store(self.target, mapping)
        with ui.ui_factory.nested_progress_bar() as pb:
            target_git_object_retriever.lock_write()
            try:
                (pack_hint, last_rev) = import_git_objects(
                    self.target,
                    mapping,
                    self.source._git.object_store,
                    target_git_object_retriever,
                    wants,
                    pb,
                    limit,
                )
                return (pack_hint, last_rev, remote_refs)
            finally:
                target_git_object_retriever.unlock()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        if not isinstance(source, LocalGitRepository):
            return False
        if not target.supports_rich_root():
            return False
        if isinstance(target, GitRepository):
            return False
        return getattr(target._format, "supports_full_versioned_files", True)


class InterGitGitRepository(InterFromGitRepository):
    """InterRepository that copies between Git repositories."""

    source: GitRepository
    target: GitRepository

    def _get_target_either_refs(self):
        ret = {}
        for name, sha1 in self.target.controldir.get_refs_container().as_dict().items():
            ret[name] = (sha1, self.target.lookup_foreign_revision_id(sha1))
        return ret

    def fetch_refs(
        self, update_refs, lossy: bool = False, overwrite: bool = False
    ) -> tuple[RevidMap, EitherRefDict, EitherRefDict]:
        if lossy:
            raise LossyPushToSameVCS(self.source, self.target)
        old_refs = self._get_target_either_refs()
        ref_changes = {}

        def determine_wants(heads, depth=None):
            old_refs = {k: (v, None) for (k, v) in heads.items()}
            new_refs = update_refs(old_refs)
            ret = []
            for name, (sha1, bzr_revid) in list(new_refs.items()):
                if sha1 is None:
                    sha1, _unused_mapping = self.source.lookup_bzr_revision_id(
                        bzr_revid
                    )
                new_refs[name] = (sha1, bzr_revid)
                ret.append(sha1)
            ref_changes.update(new_refs)
            return ret

        self.fetch_objects(determine_wants)
        for k, (git_sha, _bzr_revid) in ref_changes.items():
            self.target._git.refs[k] = git_sha  # type: ignore
        new_refs = self.target.controldir.get_refs_container()
        return {}, old_refs, new_refs

    def fetch_objects(self, determine_wants, limit=None, mapping=None, lossy=False):
        raise NotImplementedError(self.fetch_objects)

    def _target_has_shas(self, shas):
        return {sha for sha in shas if sha in self.target._git.object_store}

    def fetch(
        self,
        revision_id=None,
        find_ghosts=False,
        fetch_spec=None,
        branches=None,
        limit=None,
        include_tags=False,
        lossy=False,
    ):
        if lossy:
            raise LossyPushToSameVCS(self.source, self.target)
        if revision_id is not None:
            args = [revision_id]
        elif fetch_spec is not None:
            recipe = fetch_spec.get_recipe()
            if recipe[0] in ("search", "proxy-search"):
                heads = recipe[1]
            else:
                raise AssertionError(
                    "Unsupported search result type {}".format(recipe[0])
                )
            args = heads
        if branches is not None:
            determine_wants = self.get_determine_wants_branches(
                branches, include_tags=include_tags
            )
        elif fetch_spec is None and revision_id is None:
            determine_wants = self.determine_wants_all
        else:
            determine_wants = self.get_determine_wants_revids(
                args, include_tags=include_tags
            )
        wants_recorder = DetermineWantsRecorder(determine_wants)
        self.fetch_objects(wants_recorder, limit=limit)
        result = FetchResult()
        result.refs = wants_recorder.remote_refs
        return result

    def get_determine_wants_revids(self, revids, include_tags=False, tag_selector=None):
        wants = set()
        for revid in set(revids):
            if revid == NULL_REVISION:
                continue
            git_sha, _mapping = self.source.lookup_bzr_revision_id(revid)
            wants.add(git_sha)
        return self.get_determine_wants_heads(
            wants, include_tags=include_tags, tag_selector=tag_selector
        )

    def get_determine_wants_branches(self, branches, include_tags=False):
        def determine_wants(refs, depth=None):
            ret = []
            for name, value in refs.items():
                if value == ZERO_SHA:
                    continue

                if name.endswith(PEELED_TAG_SUFFIX):
                    continue

                if name in branches or (include_tags and is_tag(name)):
                    ret.append(value)
            return ret

        return determine_wants

    def determine_wants_all(self, refs, depth=None):
        potential = {
            v
            for k, v in refs.items()
            if v != ZERO_SHA and not k.endswith(PEELED_TAG_SUFFIX)
        }
        return list(potential - self._target_has_shas(potential))


class InterLocalGitLocalGitRepository(InterGitGitRepository):
    source: LocalGitRepository
    target: LocalGitRepository

    def fetch_objects(
        self, determine_wants, limit=None, mapping=None, lossy: bool = False
    ):
        if limit is not None:
            raise FetchLimitUnsupported(self)
        if lossy:
            raise LossyPushToSameVCS(self.source, self.target)
        from .remote import DefaultProgressReporter

        with ui.ui_factory.nested_progress_bar() as pb:
            progress = DefaultProgressReporter(pb).progress
            refs = self.source._git.fetch(
                self.target._git, determine_wants, progress=progress
            )
        return (None, None, refs)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return isinstance(source, LocalGitRepository) and isinstance(
            target, LocalGitRepository
        )


class InterRemoteGitLocalGitRepository(InterGitGitRepository):
    def fetch_objects(self, determine_wants, limit=None, mapping=None):
        from tempfile import SpooledTemporaryFile

        if limit is not None:
            raise FetchLimitUnsupported(self)
        graphwalker = self.target._git.get_graph_walker()
        if CAPABILITY_THIN_PACK in self.source.controldir._client._fetch_capabilities:
            # TODO(jelmer): Avoid reading entire file into memory and
            # only processing it after the whole file has been fetched.
            f = SpooledTemporaryFile(
                max_size=PACK_SPOOL_FILE_MAX_SIZE,
                prefix="incoming-",
                dir=getattr(self.target._git.object_store, "path", None),
            )

            def commit():
                if f.tell():
                    f.seek(0)
                    self.target._git.object_store.add_thin_pack(f.read, None)

            def abort():
                pass
        else:
            f, commit, abort = self.target._git.object_store.add_pack()
        try:
            refs = self.source.controldir.fetch_pack(
                determine_wants, graphwalker, f.write
            )
            commit()
            return (None, None, refs)
        except BaseException:
            abort()
            raise

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return isinstance(source, RemoteGitRepository) and isinstance(
            target, LocalGitRepository
        )


class InterLocalGitRemoteGitRepository(InterToGitRepository):
    def fetch_refs(self, update_refs, lossy=False, overwrite=False):
        """Import the gist of the ancestry of a particular revision."""
        if lossy:
            raise LossyPushToSameVCS(self.source, self.target)

        def git_update_refs(old_refs):
            ret = {}
            self.old_refs = {k: (v, None) for (k, v) in old_refs.items()}
            new_refs = update_refs(self.old_refs)
            for name, (gitid, revid) in new_refs.items():
                if gitid is None:
                    gitid = self.source_store._lookup_revision_sha1(revid)
                if not overwrite:
                    if remote_divergence(old_refs.get(name), gitid, self.source_store):
                        raise DivergedBranches(self.source, self.target)
                ret[name] = gitid
            return ret

        new_refs = self.target.send_pack(
            git_update_refs, self.source._git.generate_pack_data
        )
        return None, self.old_refs, new_refs

    @staticmethod
    def is_compatible(source, target):
        return isinstance(source, LocalGitRepository) and isinstance(
            target, RemoteGitRepository
        )

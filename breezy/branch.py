# Copyright (C) 2005-2012 Canonical Ltd
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

__docformat__ = "google"

from typing import TYPE_CHECKING, Dict, List, Optional, TextIO, Tuple, Union, cast

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    ui,
    )
from breezy.bzr import (
    fetch,
    remote,
    vf_search,
    )
""",
)

import contextlib
import itertools

from . import config as _mod_config
from . import debug, errors, registry, repository, urlutils
from . import revision as _mod_revision
from .controldir import (
    ControlComponent,
    ControlComponentFormat,
    ControlComponentFormatRegistry,
    ControlDir,
)
from .hooks import Hooks
from .inter import InterObject
from .lock import LogicalLockResult
from .revision import RevisionID
from .trace import is_quiet, mutter, mutter_callsite, note, warning
from .transport import Transport, get_transport

if TYPE_CHECKING:
    from .tag import TagConflict, TagUpdates


class UnstackableBranchFormat(errors.BzrError):
    _fmt = (
        "The branch '%(url)s'(%(format)s) is not a stackable format. "
        "You will need to upgrade the branch to permit branch stacking."
    )

    def __init__(self, format, url):
        errors.BzrError.__init__(self)
        self.format = format
        self.url = url


class BindingUnsupported(errors.UnsupportedOperation):
    _fmt = "Branch at %(url)s does not support binding."

    def __init__(self, branch):
        errors.BzrError.__init__(self)
        self.branch = branch
        self.url = branch.user_url


class Branch(ControlComponent):
    """Branch holding a history of revisions.

    Attributes:
      hooks: An instance of BranchHooks.
      _master_branch_cache: cached result of get_master_branch, see
        _clear_cached_state.
    """

    controldir: ControlDir

    name: Optional[str]

    base: str

    _format: "BranchFormat"

    _last_revision_info_cache: Optional[Tuple[int, RevisionID]]

    repository: repository.Repository

    hooks: "BranchHooks"

    @property
    def user_transport(self) -> Transport:
        return self.controldir.user_transport

    def __init__(self, possible_transports: Optional[List[Transport]] = None) -> None:
        self.tags = self._format.make_tags(self)
        self._revision_history_cache = None
        self._revision_id_to_revno_cache = None
        self._partial_revision_id_to_revno_cache: Dict[RevisionID, int] = {}
        self._partial_revision_history_cache: List[RevisionID] = []
        self._last_revision_info_cache = None
        self._master_branch_cache = None
        self._merge_sorted_revisions_cache = None
        self._open_hook(possible_transports)
        hooks = Branch.hooks["open"]
        for hook in hooks:
            hook(self)

    def _open_hook(self, possible_transports):
        """Called by init to allow simpler extension of the base class."""

    def _activate_fallback_location(self, url, possible_transports):
        """Activate the branch/repository from url as a fallback repository."""
        for existing_fallback_repo in self.repository._fallback_repositories:
            if existing_fallback_repo.user_url == url:
                # This fallback is already configured.  This probably only
                # happens because ControlDir.sprout is a horrible mess.  To
                # avoid confusing _unstack we don't add this a second time.
                mutter("duplicate activation of fallback %r on %r", url, self)
                return
        repo = self._get_fallback_repository(url, possible_transports)
        if repo.has_same_location(self.repository):
            raise errors.UnstackableLocationError(self.user_url, url)
        self.repository.add_fallback_repository(repo)

    def break_lock(self) -> None:
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        raise NotImplementedError(self.break_lock)

    def _extend_partial_history(
        self,
        stop_index: Optional[int] = None,
        stop_revision: Optional[RevisionID] = None,
    ) -> None:
        """Extend the partial history to include a given index.

        If a stop_index is supplied, stop when that index has been reached.
        If a stop_revision is supplied, stop when that revision is
        encountered.  Otherwise, stop when the beginning of history is
        reached.

        Args:
          stop_index: The index which should be present.  When it is
            present, history extension will stop.
          stop_revision: The revision id which should be present.  When
            it is encountered, history extension will stop.
        """
        if len(self._partial_revision_history_cache) == 0:
            self._partial_revision_history_cache = [self.last_revision()]
        repository._iter_for_revno(
            self.repository,
            self._partial_revision_history_cache,
            stop_index=stop_index,
            stop_revision=stop_revision,
        )
        if self._partial_revision_history_cache[-1] == _mod_revision.NULL_REVISION:
            self._partial_revision_history_cache.pop()

    def _get_check_refs(self):
        """Get the references needed for check().

        See breezy.check.
        """
        revid = self.last_revision()
        return [("revision-existence", revid), ("lefthand-distance", revid)]

    @staticmethod
    def open(base, _unsupported=False, possible_transports=None):
        """Open the branch rooted at base.

        For instance, if the branch is at URL/.bzr/branch,
        Branch.open(URL) -> a Branch instance.
        """
        control = ControlDir.open(
            base, possible_transports=possible_transports, _unsupported=_unsupported
        )
        return control.open_branch(
            unsupported=_unsupported, possible_transports=possible_transports
        )

    @staticmethod
    def open_from_transport(
        transport: Transport,
        name: Optional[str] = None,
        _unsupported: bool = False,
        possible_transports=None,
    ):
        """Open the branch rooted at transport."""
        control = ControlDir.open_from_transport(transport, _unsupported)
        return control.open_branch(
            name=name, unsupported=_unsupported, possible_transports=possible_transports
        )

    @staticmethod
    def open_containing(url, possible_transports=None):
        """Open an existing branch which contains url.

        This probes for a branch at url, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an
        unsupported format, UnknownFormatError or UnsupportedFormatError are
        raised.  If there is one, it is returned, along with the unused portion
        of url.
        """
        control, relpath = ControlDir.open_containing(url, possible_transports)
        branch = control.open_branch(possible_transports=possible_transports)
        return (branch, relpath)

    def _push_should_merge_tags(self):
        """Should _basic_push merge this branch's tags into the target?

        The default implementation returns False if this branch has no tags,
        and True the rest of the time.  Subclasses may override this.
        """
        return self.supports_tags() and self.tags.get_tag_dict()

    def get_config(self):
        """Get a breezy.config.BranchConfig for this Branch.

        This can then be used to get and set configuration options for the
        branch.

        Returns: A breezy.config.BranchConfig.
        """
        return _mod_config.BranchConfig(self)

    def get_config_stack(self) -> _mod_config.Stack:
        """Get a breezy.config.BranchStack for this Branch.

        This can then be used to get and set configuration options for the
        branch.

        Returns: A breezy.config.BranchStack.
        """
        return _mod_config.BranchStack(self)

    def store_uncommitted(self, creator) -> None:
        """Store uncommitted changes from a ShelfCreator.

        Args:
          creator: The ShelfCreator containing uncommitted changes, or
            None to delete any stored changes.
        :raises: ChangesAlreadyStored if the branch already has changes.
        """
        raise NotImplementedError(self.store_uncommitted)

    def get_unshelver(self, tree):
        """Return a shelf.Unshelver for this branch and tree.

        Args:
          tree: The tree to use to construct the Unshelver.
        Returns: an Unshelver or None if no changes are stored.
        """
        raise NotImplementedError(self.get_unshelver)

    def _get_fallback_repository(self, url, possible_transports):
        """Get the repository we fallback to at url."""
        url = urlutils.join(self.base, url)
        a_branch = Branch.open(url, possible_transports=possible_transports)
        return a_branch.repository

    def _get_nick(self, local=False, possible_transports=None):
        config = self.get_config()
        # explicit overrides master, but don't look for master if local is True
        if not local and not config.has_explicit_nickname():
            try:
                master = self.get_master_branch(possible_transports)
                if master and self.user_url == master.user_url:
                    raise errors.RecursiveBind(self.user_url)
                if master is not None:
                    # return the master branch value
                    return master.nick
            except errors.RecursiveBind as e:
                raise e
            except errors.BzrError as e:
                # Silently fall back to local implicit nick if the master is
                # unavailable
                mutter(
                    "Could not connect to bound branch, "
                    "falling back to local nick.\n " + str(e)
                )
        return config.get_nickname()

    def _set_nick(self, nick):
        self.get_config().set_user_option("nickname", nick, warn_masked=True)

    nick = property(_get_nick, _set_nick)

    def is_locked(self):
        raise NotImplementedError(self.is_locked)

    def _lefthand_history(self, revision_id, last_rev=None, other_branch=None):
        if "evil" in debug.debug_flags:
            mutter_callsite(4, "_lefthand_history scales with history.")
        # stop_revision must be a descendant of last_revision
        graph = self.repository.get_graph()
        if last_rev is not None:
            if not graph.is_ancestor(last_rev, revision_id):
                # our previous tip is not merged into stop_revision
                raise errors.DivergedBranches(self, other_branch)
        # make a new revision history from the graph
        parents_map = graph.get_parent_map([revision_id])
        if revision_id not in parents_map:
            raise errors.NoSuchRevision(self, revision_id)
        current_rev_id = revision_id
        new_history = []
        check_not_reserved_id = _mod_revision.check_not_reserved_id
        # Do not include ghosts or graph origin in revision_history
        while current_rev_id in parents_map and len(parents_map[current_rev_id]) > 0:
            check_not_reserved_id(current_rev_id)
            new_history.append(current_rev_id)
            current_rev_id = parents_map[current_rev_id][0]
            parents_map = graph.get_parent_map([current_rev_id])
        new_history.reverse()
        return new_history

    def lock_write(self, token=None):
        """Lock the branch for write operations.

          token: A token to permit reacquiring a previously held and
            preserved lock.
        Returns: A BranchWriteLockResult.
        """
        raise NotImplementedError(self.lock_write)

    def lock_read(self):
        """Lock the branch for read operations.

        Returns: A breezy.lock.LogicalLockResult.
        """
        raise NotImplementedError(self.lock_read)

    def unlock(self):
        raise NotImplementedError(self.unlock)

    def peek_lock_mode(self):
        """Return lock mode for the Branch: 'r', 'w' or None."""
        raise NotImplementedError(self.peek_lock_mode)

    def get_physical_lock_status(self):
        raise NotImplementedError(self.get_physical_lock_status)

    def dotted_revno_to_revision_id(self, revno, _cache_reverse=False):
        """Return the revision_id for a dotted revno.

        Args:
          revno: a tuple like (1,) or (1,1,2)
          _cache_reverse: a private parameter enabling storage
           of the reverse mapping in a top level cache. (This should
           only be done in selective circumstances as we want to
           avoid having the mapping cached multiple times.)
        Returns: the revision_id
        :raises errors.NoSuchRevision: if the revno doesn't exist
        """
        with self.lock_read():
            rev_id = self._do_dotted_revno_to_revision_id(revno)
            if _cache_reverse:
                self._partial_revision_id_to_revno_cache[rev_id] = revno
            return rev_id

    def _do_dotted_revno_to_revision_id(self, revno):
        """Worker function for dotted_revno_to_revision_id.

        Subclasses should override this if they wish to
        provide a more efficient implementation.
        """
        if len(revno) == 1:
            try:
                return self.get_rev_id(revno[0])
            except errors.RevisionNotPresent as exc:
                raise errors.GhostRevisionsHaveNoRevno(
                    revno[0], exc.revision_id
                ) from exc
        revision_id_to_revno = self.get_revision_id_to_revno_map()
        revision_ids = [
            revision_id
            for revision_id, this_revno in revision_id_to_revno.items()
            if revno == this_revno
        ]
        if len(revision_ids) == 1:
            return revision_ids[0]
        else:
            revno_str = ".".join(map(str, revno))
            raise errors.NoSuchRevision(self, revno_str)

    def revision_id_to_dotted_revno(self, revision_id):
        """Given a revision id, return its dotted revno.

        Returns: a tuple like (1,) or (400,1,3).
        """
        with self.lock_read():
            return self._do_revision_id_to_dotted_revno(revision_id)

    def _do_revision_id_to_dotted_revno(self, revision_id):
        """Worker function for revision_id_to_revno."""
        # Try the caches if they are loaded
        result = self._partial_revision_id_to_revno_cache.get(revision_id)
        if result is not None:
            return result
        if self._revision_id_to_revno_cache:
            result = self._revision_id_to_revno_cache.get(revision_id)
            if result is None:
                raise errors.NoSuchRevision(self, revision_id)
        # Try the mainline as it's optimised
        try:
            revno = self.revision_id_to_revno(revision_id)
            return (revno,)
        except errors.NoSuchRevision as exc:
            # We need to load and use the full revno map after all
            result = self.get_revision_id_to_revno_map().get(revision_id)
            if result is None:
                raise errors.NoSuchRevision(self, revision_id) from exc
        return result

    def get_revision_id_to_revno_map(self):
        """Return the revision_id => dotted revno map.

        This will be regenerated on demand, but will be cached.

        Returns: A dictionary mapping revision_id => dotted revno.
            This dictionary should not be modified by the caller.
        """
        if "evil" in debug.debug_flags:
            mutter_callsite(3, "get_revision_id_to_revno_map scales with ancestry.")
        with self.lock_read():
            if self._revision_id_to_revno_cache is not None:
                mapping = self._revision_id_to_revno_cache
            else:
                mapping = self._gen_revno_map()
                self._cache_revision_id_to_revno(mapping)
            # TODO: jam 20070417 Since this is being cached, should we be
            # returning a copy?
            # I would rather not, and instead just declare that users should
            # not modify the return value.
            return mapping

    def _gen_revno_map(self):
        """Create a new mapping from revision ids to dotted revnos.

        Dotted revnos are generated based on the current tip in the revision
        history.
        This is the worker function for get_revision_id_to_revno_map, which
        just caches the return value.

        Returns: A dictionary mapping revision_id => dotted revno.
        """
        revision_id_to_revno = {
            rev_id: revno
            for rev_id, depth, revno, end_of_merge in self.iter_merge_sorted_revisions()
        }
        return revision_id_to_revno

    def iter_merge_sorted_revisions(
        self,
        start_revision_id=None,
        stop_revision_id=None,
        stop_rule="exclude",
        direction="reverse",
    ):
        """Walk the revisions for a branch in merge sorted order.

        Merge sorted order is the output from a merge-aware,
        topological sort, i.e. all parents come before their
        children going forward; the opposite for reverse.

        Args:
          start_revision_id: the revision_id to begin walking from.
            If None, the branch tip is used.
          stop_revision_id: the revision_id to terminate the walk
            after. If None, the rest of history is included.
          stop_rule: if stop_revision_id is not None, the precise rule
            to use for termination:

            * 'exclude' - leave the stop revision out of the result (default)
            * 'include' - the stop revision is the last item in the result
            * 'with-merges' - include the stop revision and all of its
              merged revisions in the result
            * 'with-merges-without-common-ancestry' - filter out revisions
              that are in both ancestries
          direction: either 'reverse' or 'forward':

            * reverse means return the start_revision_id first, i.e.
              start at the most recent revision and go backwards in history
            * forward returns tuples in the opposite order to reverse.
              Note in particular that forward does *not* do any intelligent
              ordering w.r.t. depth as some clients of this API may like.
              (If required, that ought to be done at higher layers.)

        Returns: an iterator over (revision_id, depth, revno, end_of_merge)
            tuples where:

            * revision_id: the unique id of the revision
            * depth: How many levels of merging deep this node has been
              found.
            * revno_sequence: This field provides a sequence of
              revision numbers for all revisions. The format is:
              (REVNO, BRANCHNUM, BRANCHREVNO). BRANCHNUM is the number of the
              branch that the revno is on. From left to right the REVNO numbers
              are the sequence numbers within that branch of the revision.
            * end_of_merge: When True the next node (earlier in history) is
              part of a different merge.
        """
        with self.lock_read():
            # Note: depth and revno values are in the context of the branch so
            # we need the full graph to get stable numbers, regardless of the
            # start_revision_id.
            if self._merge_sorted_revisions_cache is None:
                last_revision = self.last_revision()
                known_graph = self.repository.get_known_graph_ancestry([last_revision])
                self._merge_sorted_revisions_cache = known_graph.merge_sort(
                    last_revision
                )
            filtered = self._filter_merge_sorted_revisions(
                self._merge_sorted_revisions_cache,
                start_revision_id,
                stop_revision_id,
                stop_rule,
            )
            # Make sure we don't return revisions that are not part of the
            # start_revision_id ancestry.
            filtered = self._filter_start_non_ancestors(filtered)
            if direction == "reverse":
                return filtered
            if direction == "forward":
                return reversed(list(filtered))
            else:
                raise ValueError("invalid direction {!r}".format(direction))

    def _filter_merge_sorted_revisions(
        self, merge_sorted_revisions, start_revision_id, stop_revision_id, stop_rule
    ):
        """Iterate over an inclusive range of sorted revisions."""
        rev_iter = iter(merge_sorted_revisions)
        if start_revision_id is not None:
            for node in rev_iter:
                rev_id = node.key
                if rev_id != start_revision_id:
                    continue
                else:
                    # The decision to include the start or not
                    # depends on the stop_rule if a stop is provided
                    # so pop this node back into the iterator
                    rev_iter = itertools.chain(iter([node]), rev_iter)
                    break
        if stop_revision_id is None:
            # Yield everything
            for node in rev_iter:
                rev_id = node.key
                yield (rev_id, node.merge_depth, node.revno, node.end_of_merge)
        elif stop_rule == "exclude":
            for node in rev_iter:
                rev_id = node.key
                if rev_id == stop_revision_id:
                    return
                yield (rev_id, node.merge_depth, node.revno, node.end_of_merge)
        elif stop_rule == "include":
            for node in rev_iter:
                rev_id = node.key
                yield (rev_id, node.merge_depth, node.revno, node.end_of_merge)
                if rev_id == stop_revision_id:
                    return
        elif stop_rule == "with-merges-without-common-ancestry":
            # We want to exclude all revisions that are already part of the
            # stop_revision_id ancestry.
            graph = self.repository.get_graph()
            ancestors = graph.find_unique_ancestors(
                start_revision_id, [stop_revision_id]
            )
            for node in rev_iter:
                rev_id = node.key
                if rev_id not in ancestors:
                    continue
                yield (rev_id, node.merge_depth, node.revno, node.end_of_merge)
        elif stop_rule == "with-merges":
            stop_rev = self.repository.get_revision(stop_revision_id)
            if stop_rev.parent_ids:
                left_parent = stop_rev.parent_ids[0]
            else:
                left_parent = _mod_revision.NULL_REVISION
            # left_parent is the actual revision we want to stop logging at,
            # since we want to show the merged revisions after the stop_rev too
            reached_stop_revision_id = False
            revision_id_whitelist = []
            for node in rev_iter:
                rev_id = node.key
                if rev_id == left_parent:
                    # reached the left parent after the stop_revision
                    return
                if not reached_stop_revision_id or rev_id in revision_id_whitelist:
                    yield (rev_id, node.merge_depth, node.revno, node.end_of_merge)
                    if reached_stop_revision_id or rev_id == stop_revision_id:
                        # only do the merged revs of rev_id from now on
                        rev = self.repository.get_revision(rev_id)
                        if rev.parent_ids:
                            reached_stop_revision_id = True
                            revision_id_whitelist.extend(rev.parent_ids)
        else:
            raise ValueError("invalid stop_rule {!r}".format(stop_rule))

    def _filter_start_non_ancestors(self, rev_iter):
        # If we started from a dotted revno, we want to consider it as a tip
        # and don't want to yield revisions that are not part of its
        # ancestry. Given the order guaranteed by the merge sort, we will see
        # uninteresting descendants of the first parent of our tip before the
        # tip itself.
        try:
            first = next(rev_iter)
        except StopIteration:
            return
        (rev_id, merge_depth, revno, end_of_merge) = first
        yield first
        if not merge_depth:
            # We start at a mainline revision so by definition, all others
            # revisions in rev_iter are ancestors
            yield from rev_iter

        clean = False
        whitelist = set()
        pmap = self.repository.get_parent_map([rev_id])
        parents = pmap.get(rev_id, [])
        if parents:
            whitelist.update(parents)
        else:
            # If there is no parents, there is nothing of interest left

            # FIXME: It's hard to test this scenario here as this code is never
            # called in that case. -- vila 20100322
            return

        for rev_id, merge_depth, revno, end_of_merge in rev_iter:
            if not clean:
                if rev_id in whitelist:
                    pmap = self.repository.get_parent_map([rev_id])
                    parents = pmap.get(rev_id, [])
                    whitelist.remove(rev_id)
                    whitelist.update(parents)
                    if merge_depth == 0:
                        # We've reached the mainline, there is nothing left to
                        # filter
                        clean = True
                else:
                    # A revision that is not part of the ancestry of our
                    # starting revision.
                    continue
            yield (rev_id, merge_depth, revno, end_of_merge)

    def leave_lock_in_place(self):
        """Tell this branch object not to release the physical lock when this
        object is unlocked.

        If lock_write doesn't return a token, then this method is not
        supported.
        """
        self.control_files.leave_in_place()

    def dont_leave_lock_in_place(self):
        """Tell this branch object to release the physical lock when this
        object is unlocked, even if it didn't originally acquire it.

        If lock_write doesn't return a token, then this method is not
        supported.
        """
        self.control_files.dont_leave_in_place()

    def bind(self, other):
        """Bind the local branch the other branch.

        Args:
          other: The branch to bind to
        """
        raise BindingUnsupported(self)

    def get_append_revisions_only(self):
        """Whether it is only possible to append revisions to the history."""
        if not self._format.supports_set_append_revisions_only():
            return False
        return self.get_config_stack().get("append_revisions_only")

    def set_append_revisions_only(self, enabled: bool) -> None:
        if not self._format.supports_set_append_revisions_only():
            raise errors.UpgradeRequired(self.user_url)
        self.get_config_stack().set("append_revisions_only", enabled)

    def fetch(self, from_branch, stop_revision=None, limit=None, lossy=False):
        """Copy revisions from from_branch into this branch.

        Args:
          from_branch: Where to copy from.
          stop_revision: What revision to stop at (None for at the end
                              of the branch.
          limit: Optional rough limit of revisions to fetch
        Returns: None
        """
        with self.lock_write():
            return InterBranch.get(from_branch, self).fetch(
                stop_revision, limit=limit, lossy=lossy
            )

    def get_bound_location(self) -> Optional[str]:
        """Return the URL of the branch we are bound to.

        Older format branches cannot bind, please be sure to use a metadir
        branch.
        """
        return None

    def get_old_bound_location(self):
        """Return the URL of the branch we used to be bound to."""
        raise errors.UpgradeRequired(self.user_url)

    def get_commit_builder(
        self,
        parents,
        config_stack=None,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this branch.

        Args:
          parents: Revision ids of the parents of the new revision.
          config: Optional configuration to use.
          timestamp: Optional timestamp recorded for commit.
          timezone: Optional timezone for timestamp.
          committer: Optional committer to set for commit.
          revprops: Optional dictionary of revision properties.
          revision_id: Optional revision id.
          lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        if config_stack is None:
            config_stack = self.get_config_stack()

        return self.repository.get_commit_builder(
            self,
            parents,
            config_stack,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy,
        )

    def get_master_branch(
        self, possible_transports: Optional[List[Transport]] = None
    ) -> Optional["Branch"]:
        """Return the branch we are bound to.

        Returns: Either a Branch, or None
        """
        return None

    def get_stacked_on_url(self) -> str:
        """Get the URL this branch is stacked against.

        Raises:
          NotStacked: If the branch is not stacked.
          UnstackableBranchFormat: If the branch does not support
            stacking.
        """
        raise NotImplementedError(self.get_stacked_on_url)

    def set_last_revision_info(
        self, revno: Optional[int], revision_id: RevisionID
    ) -> None:
        """Set the last revision of this branch.

        The caller is responsible for checking that the revno is correct
        for this revision id.

        It may be possible to set the branch last revision to an id not
        present in the repository.  However, branches can also be
        configured to check constraints on history, in which case this may not
        be permitted.
        """
        raise NotImplementedError(self.set_last_revision_info)

    def generate_revision_history(
        self,
        revision_id: RevisionID,
        last_rev: Optional[RevisionID] = None,
        other_branch: Optional["Branch"] = None,
    ) -> None:
        """See Branch.generate_revision_history."""
        with self.lock_write():
            graph = self.repository.get_graph()
            (last_revno, last_revid) = self.last_revision_info()
            known_revision_ids = [
                (last_revid, last_revno),
                (_mod_revision.NULL_REVISION, 0),
            ]
            if last_rev is not None:
                if not graph.is_ancestor(last_rev, revision_id):
                    # our previous tip is not merged into stop_revision
                    raise errors.DivergedBranches(self, other_branch)
            revno = graph.find_distance_to_null(revision_id, known_revision_ids)
            self.set_last_revision_info(revno, revision_id)

    def _set_parent_location(self, url: Optional[str]) -> None:
        raise NotImplementedError(self._set_parent_location)

    def set_parent(self, url: Optional[str]) -> None:
        """See Branch.set_parent."""
        # TODO: Maybe delete old location files?
        # URLs should never be unicode, even on the local fs,
        # FIXUP this and get_parent in a future branch format bump:
        # read and rewrite the file. RBC 20060125
        if url is not None:
            if isinstance(url, str):
                try:
                    url.encode("ascii")
                except UnicodeEncodeError as exc:
                    raise urlutils.InvalidURL(
                        url, "Urls must be 7-bit ascii, use breezy.urlutils.escape"
                    ) from exc
            url = urlutils.relative_url(self.base, url)
        with self.lock_write():
            self._set_parent_location(url)

    def set_stacked_on_url(self, url: str) -> None:
        """Set the URL this branch is stacked against.

        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        :raises UnstackableRepositoryFormat: If the repository does not support
            stacking.
        """
        raise NotImplementedError(self.set_stacked_on_url)

    def _cache_revision_history(self, rev_history):
        """Set the cached revision history to rev_history.

        The revision_history method will use this cache to avoid regenerating
        the revision history.

        This API is semi-public; it only for use by subclasses, all other code
        should consider it to be private.
        """
        self._revision_history_cache = rev_history

    def _cache_revision_id_to_revno(self, revision_id_to_revno):
        """Set the cached revision_id => revno map to revision_id_to_revno.

        This API is semi-public; it only for use by subclasses, all other code
        should consider it to be private.
        """
        self._revision_id_to_revno_cache = revision_id_to_revno

    def _clear_cached_state(self) -> None:
        """Clear any cached data on this branch, e.g. cached revision history.

        This means the next call to revision_history will need to call
        _gen_revision_history.

        This API is semi-public; it is only for use by subclasses, all other
        code should consider it to be private.
        """
        self._revision_history_cache = None
        self._revision_id_to_revno_cache = None
        self._last_revision_info_cache = None
        self._master_branch_cache = None
        self._merge_sorted_revisions_cache = None
        self._partial_revision_history_cache = []
        self._partial_revision_id_to_revno_cache = {}

    def _gen_revision_history(self):
        """Return sequence of revision hashes on to this branch.

        Unlike revision_history, this method always regenerates or rereads the
        revision history, i.e. it does not cache the result, so repeated calls
        may be expensive.

        Concrete subclasses should override this instead of revision_history so
        that subclasses do not need to deal with caching logic.

        This API is semi-public; it only for use by subclasses, all other code
        should consider it to be private.
        """
        raise NotImplementedError(self._gen_revision_history)

    def _revision_history(self) -> List[RevisionID]:
        if "evil" in debug.debug_flags:
            mutter_callsite(3, "revision_history scales with history.")
        if self._revision_history_cache is not None:
            history = self._revision_history_cache
        else:
            history = self._gen_revision_history()
            self._cache_revision_history(history)
        return list(history)

    def revno(self):
        """Return current revision number for this branch.

        That is equivalent to the number of revisions committed to
        this branch.
        """
        return self.last_revision_info()[0]

    def unbind(self):
        """Older format branches cannot bind or unbind."""
        raise errors.UpgradeRequired(self.user_url)

    def last_revision(self) -> RevisionID:
        """Return last revision id, or NULL_REVISION."""
        return self.last_revision_info()[1]

    def last_revision_info(self) -> Tuple[int, RevisionID]:
        """Return information about the last revision.

        Returns: A tuple (revno, revision_id).
        """
        with self.lock_read():
            if self._last_revision_info_cache is None:
                self._last_revision_info_cache = self._read_last_revision_info()
            return self._last_revision_info_cache

    def _read_last_revision_info(self):
        raise NotImplementedError(self._read_last_revision_info)

    def import_last_revision_info_and_tags(self, source, revno, revid, *, lossy=False):
        """Set the last revision info, importing from another repo if necessary.

        This is used by the bound branch code to upload a revision to
        the master branch first before updating the tip of the local branch.
        Revisions referenced by source's tags are also transferred.

        Args:
          source: Source branch to optionally fetch from
          revno: Revision number of the new tip
          revid: Revision id of the new tip
          lossy: Whether to discard metadata that can not be
            natively represented
        Returns: Tuple with the new revision number and revision id
            (should only be different from the arguments when lossy=True)
        """
        if not self.repository.has_same_location(source.repository):
            self.fetch(source, revid)
        self.set_last_revision_info(revno, revid)
        return (revno, revid)

    def revision_id_to_revno(self, revision_id: RevisionID) -> int:
        """Given a revision id, return its revno."""
        if _mod_revision.is_null(revision_id):
            return 0
        history = self._revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError as exc:
            raise errors.NoSuchRevision(self, revision_id) from exc

    def get_rev_id(
        self, revno: int, history: Optional[List[RevisionID]] = None
    ) -> RevisionID:
        """Find the revision id of the specified revno."""
        with self.lock_read():
            if revno == 0:
                return _mod_revision.NULL_REVISION
            last_revno, last_revid = self.last_revision_info()
            if revno == last_revno:
                return last_revid
            if revno <= 0 or revno > last_revno:
                raise errors.NoSuchRevision(self, revno)
            distance_from_last = last_revno - revno
            if len(self._partial_revision_history_cache) <= distance_from_last:
                self._extend_partial_history(distance_from_last)
            return self._partial_revision_history_cache[distance_from_last]

    def pull(
        self,
        source: "Branch",
        *,
        overwrite: bool = False,
        stop_revision: Optional[RevisionID] = None,
        possible_transports: Optional[List[Transport]] = None,
        **kwargs,
    ) -> "PullResult":
        """Mirror source into this branch.

        This branch is considered to be 'local', having low latency.

        Returns: PullResult instance
        """
        return InterBranch.get(source, self).pull(
            overwrite=overwrite,
            stop_revision=stop_revision,
            possible_transports=possible_transports,
            **kwargs,
        )

    def push(
        self,
        target: "Branch",
        *,
        overwrite: bool = False,
        stop_revision: Optional[RevisionID] = None,
        lossy: bool = False,
        **kwargs,
    ):
        """Mirror this branch into target.

        This branch is considered to be 'local', having low latency.
        """
        return InterBranch.get(self, target).push(
            overwrite, stop_revision, lossy, **kwargs
        )

    def basis_tree(self):
        """Return `Tree` object for last revision."""
        return self.repository.revision_tree(self.last_revision())

    def get_parent(self) -> Optional[str]:
        """Return the parent location of the branch.

        This is the default location for pull/missing.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        parent = self._get_parent_location()
        if parent is None:
            return parent
        # This is an old-format absolute path to a local branch
        # turn it into a url
        if parent.startswith("/"):
            parent = urlutils.local_path_to_url(parent)
        try:
            return urlutils.join(self.base[:-1], parent)
        except urlutils.InvalidURLJoin as exc:
            raise errors.InaccessibleParent(parent, self.user_url) from exc

    def _get_parent_location(self):
        raise NotImplementedError(self._get_parent_location)

    def _set_config_location(self, name, url, *, config=None, make_relative=False):
        if config is None:
            config = self.get_config_stack()
        if url is None:
            url = ""
        elif make_relative:
            url = urlutils.relative_url(self.base, url)
        config.set(name, url)

    def _get_config_location(self, name: str, *, config=None) -> Optional[str]:
        if config is None:
            config = self.get_config_stack()
        location = config.get(name)
        if location == "":
            location = None
        return cast(Optional[str], location)

    def get_child_submit_format(self) -> Optional[str]:
        """Return the preferred format of submissions to this branch."""
        return cast(Optional[str], self.get_config_stack().get("child_submit_format"))

    def get_submit_branch(self) -> Optional[str]:
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        return cast(Optional[str], self.get_config_stack().get("submit_branch"))

    def set_submit_branch(self, location: str) -> None:
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        self.get_config_stack().set("submit_branch", location)

    def get_public_branch(self) -> Optional[str]:
        """Return the public location of the branch.

        This is used by merge directives.
        """
        return self._get_config_location("public_branch")

    def set_public_branch(self, location: str) -> None:
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        self._set_config_location("public_branch", location)

    def get_push_location(self) -> Optional[str]:
        """Return None or the location to push this branch to."""
        return cast(str, self.get_config_stack().get("push_location"))

    def set_push_location(self, location: str) -> None:
        """Set a new push location for this branch."""
        raise NotImplementedError(self.set_push_location)

    def _run_post_change_branch_tip_hooks(self, old_revno, old_revid):
        """Run the post_change_branch_tip hooks."""
        hooks = Branch.hooks["post_change_branch_tip"]
        if not hooks:
            return
        new_revno, new_revid = self.last_revision_info()
        params = ChangeBranchTipParams(self, old_revno, new_revno, old_revid, new_revid)
        for hook in hooks:
            hook(params)

    def _run_pre_change_branch_tip_hooks(self, new_revno, new_revid):
        """Run the pre_change_branch_tip hooks."""
        hooks = Branch.hooks["pre_change_branch_tip"]
        if not hooks:
            return
        old_revno, old_revid = self.last_revision_info()
        params = ChangeBranchTipParams(self, old_revno, new_revno, old_revid, new_revid)
        for hook in hooks:
            hook(params)

    def update(self) -> None:
        """Synchronise this branch with the master branch if any.

        Returns: None or the last_revision pivoted out during the update.
        """
        return None

    def check_revno(self, revno: int) -> None:
        """\
        Check whether a revno corresponds to any revision.
        Zero (the NULL revision) is considered valid.
        """
        if revno != 0:
            self.check_real_revno(revno)

    def check_real_revno(self, revno: int) -> None:
        """\
        Check whether a revno corresponds to a real revision.
        Zero (the NULL revision) is considered invalid.
        """
        if revno < 1 or revno > self.revno():
            raise errors.InvalidRevisionNumber(revno)

    def clone(
        self,
        to_controldir: ControlDir,
        *,
        revision_id: Optional[RevisionID] = None,
        name: Optional[str] = None,
        repository_policy=None,
        tag_selector=None,
    ) -> "Branch":
        """Clone this branch into to_controldir preserving all semantic values.

        Most API users will want 'create_clone_on_transport', which creates a
        new bzrdir and branch on the fly.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        result = to_controldir.create_branch(name=name)
        with self.lock_read(), result.lock_write():
            if repository_policy is not None:
                repository_policy.configure_branch(result)
            self.copy_content_into(
                result, revision_id=revision_id, tag_selector=tag_selector
            )
        return result

    def sprout(
        self,
        to_controldir,
        *,
        revision_id=None,
        repository_policy=None,
        repository=None,
        lossy=False,
        tag_selector=None,
        name=None,
    ):
        """Create a new line of development from the branch, into to_controldir.

        to_controldir controls the branch format.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        if repository_policy is not None and repository_policy.requires_stacking():
            to_controldir._format.require_stacking(_skip_repo=True)
        result = to_controldir.create_branch(repository=repository, name=name)
        if lossy:
            raise errors.LossyPushToSameVCS(self, result)
        with self.lock_read(), result.lock_write():
            if repository_policy is not None:
                repository_policy.configure_branch(result)
            self.copy_content_into(
                result, revision_id=revision_id, tag_selector=tag_selector
            )
            master_url = self.get_bound_location()
            if master_url is None:
                result.set_parent(self.user_url)
            else:
                result.set_parent(master_url)
        return result

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch6, but works for BzrBranch5, as long as the destination's
        repository contains all the lefthand ancestors of the intended
        last_revision.  If not, set_last_revision_info will fail.

        Args:
          destination: The branch to copy the history into
          revision_id: The revision-id to truncate history at.  May
             be None to copy complete history.
        """
        source_revno, source_revision_id = self.last_revision_info()
        if revision_id is None:
            revno, revision_id = source_revno, source_revision_id
        else:
            graph = self.repository.get_graph()
            try:
                revno = graph.find_distance_to_null(
                    revision_id, [(source_revision_id, source_revno)]
                )
            except errors.GhostRevisionsHaveNoRevno:
                # Default to 1, if we can't find anything else
                revno = 1
        destination.set_last_revision_info(revno, revision_id)

    def copy_content_into(self, destination, *, revision_id=None, tag_selector=None):
        """Copy the content of self into destination.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        tag_selector: Optional callback that receives a tag name
            and should return a boolean to indicate whether a tag should be copied
        """
        return InterBranch.get(self, destination).copy_content_into(
            revision_id=revision_id, tag_selector=tag_selector
        )

    def update_references(self, target):
        if not self._format.supports_reference_locations:
            return
        return InterBranch.get(self, target).update_references()

    def check(self, refs):
        """Check consistency of the branch.

        In particular this checks that revisions given in the revision-history
        do actually match up in the revision graph, and that they're all
        present in the repository.

        Callers will typically also want to check the repository.

        Args:
          refs: Calculated refs for this branch as specified by
            branch._get_check_refs()
        Returns: A BranchCheckResult.
        """
        with self.lock_read():
            result = BranchCheckResult(self)
            last_revno, last_revision_id = self.last_revision_info()
            actual_revno = refs[("lefthand-distance", last_revision_id)]
            if actual_revno != last_revno:
                result.errors.append(
                    errors.BzrCheckError(
                        "revno does not match len(mainline) {} != {}".format(
                            last_revno, actual_revno
                        )
                    )
                )
            # TODO: We should probably also check that self.revision_history
            # matches the repository for older branch formats.
            # If looking for the code that cross-checks repository parents
            # against the Graph.iter_lefthand_ancestry output, that is now a
            # repository specific check.
            return result

    def _get_checkout_format(self, lightweight=False):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        format = self.repository.controldir.checkout_metadir()
        format.set_branch_format(self._format)
        return format

    def create_clone_on_transport(
        self,
        to_transport,
        *,
        revision_id=None,
        stacked_on=None,
        create_prefix=False,
        use_existing_dir=False,
        no_tree=None,
        tag_selector=None,
    ):
        """Create a clone of this branch and its bzrdir.

        Args:
          to_transport: The transport to clone onto.
          revision_id: The revision id to use as tip in the new branch.
            If None the tip is obtained from this branch.
          stacked_on: An optional URL to stack the clone on.
          create_prefix: Create any missing directories leading up to
            to_transport.
          use_existing_dir: Use an existing directory if one exists.
        """
        # XXX: Fix the bzrdir API to allow getting the branch back from the
        # clone call. Or something. 20090224 RBC/spiv.
        # XXX: Should this perhaps clone colocated branches as well,
        # rather than just the default branch? 20100319 JRV
        if revision_id is None:
            revision_id = self.last_revision()
        dir_to = self.controldir.clone_on_transport(
            to_transport,
            revision_id=revision_id,
            stacked_on=stacked_on,
            create_prefix=create_prefix,
            use_existing_dir=use_existing_dir,
            no_tree=no_tree,
            tag_selector=tag_selector,
        )
        return dir_to.open_branch()

    def create_checkout(
        self,
        to_location,
        *,
        revision_id=None,
        lightweight=False,
        accelerator_tree=None,
        hardlink=False,
        recurse_nested=True,
    ):
        """Create a checkout of a branch.

        Args:
          to_location: The url to produce the checkout at
          revision_id: The revision to check out
          lightweight: If True, produce a lightweight checkout, otherwise,
            produce a bound branch (heavyweight checkout)
          accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
          hardlink: If true, hard-link files from accelerator_tree,
            where possible.
          recurse_nested: Whether to recurse into nested trees
        Returns: The tree of the created checkout
        """
        t = get_transport(to_location)
        t.ensure_base()
        format = self._get_checkout_format(lightweight=lightweight)
        try:
            checkout = format.initialize_on_transport(t)
        except errors.AlreadyControlDirError as exc:
            # It's fine if the control directory already exists,
            # as long as there is no existing branch and working tree.
            checkout = ControlDir.open_from_transport(t)
            try:
                checkout.open_branch()
            except errors.NotBranchError:
                pass
            else:
                raise errors.AlreadyControlDirError(t.base) from exc
            if (
                checkout.control_transport.base
                == self.controldir.control_transport.base
            ):
                # When checking out to the same control directory,
                # always create a lightweight checkout
                lightweight = True

        if lightweight:
            from_branch = checkout.set_branch_reference(target_branch=self)
        else:
            policy = checkout.determine_repository_policy()
            policy.acquire_repository()
            checkout_branch = checkout.create_branch()
            checkout_branch.bind(self)
            # pull up to the specified revision_id to set the initial
            # branch tip correctly, and seed it with history.
            checkout_branch.pull(self, stop_revision=revision_id)
            from_branch = None
        tree = checkout.create_workingtree(
            revision_id,
            from_branch=from_branch,
            accelerator_tree=accelerator_tree,
            hardlink=hardlink,
        )
        basis_tree = tree.basis_tree()
        with basis_tree.lock_read():
            for path in basis_tree.iter_references():
                reference_parent = tree.reference_parent(path)
                if reference_parent is None:
                    warning("Branch location for %s unknown.", path)
                    continue
                reference_parent.create_checkout(
                    tree.abspath(path),
                    revision_id=basis_tree.get_reference_revision(path),
                    lightweight=lightweight,
                )
        return tree

    def reconcile(self, thorough=True):
        """Make sure the data stored in this branch is consistent.

        Returns: A `ReconcileResult` object.
        """
        raise NotImplementedError(self.reconcile)

    def supports_tags(self):
        return self._format.supports_tags()

    def automatic_tag_name(self, revision_id):
        """Try to automatically find the tag name for a revision.

        Args:
          revision_id: Revision id of the revision.
        Returns: A tag name or None if no tag name could be determined.
        """
        for hook in Branch.hooks["automatic_tag_name"]:
            ret = hook(self, revision_id)
            if ret is not None:
                return ret
        return None

    def _check_if_descendant_or_diverged(
        self, revision_a, revision_b, graph, other_branch
    ):
        """Ensure that revision_b is a descendant of revision_a.

        This is a helper function for update_revisions.

        :raises: DivergedBranches if revision_b has diverged from revision_a.
        Returns: True if revision_b is a descendant of revision_a.
        """
        relation = self._revision_relations(revision_a, revision_b, graph)
        if relation == "b_descends_from_a":
            return True
        elif relation == "diverged":
            raise errors.DivergedBranches(self, other_branch)
        elif relation == "a_descends_from_b":
            return False
        else:
            raise AssertionError("invalid relation: {!r}".format(relation))

    def _revision_relations(self, revision_a, revision_b, graph):
        """Determine the relationship between two revisions.

        Returns: One of: 'a_descends_from_b', 'b_descends_from_a', 'diverged'
        """
        heads = graph.heads([revision_a, revision_b])
        if heads == {revision_b}:
            return "b_descends_from_a"
        elif heads == {revision_a, revision_b}:
            # These branches have diverged
            return "diverged"
        elif heads == {revision_a}:
            return "a_descends_from_b"
        else:
            raise AssertionError("invalid heads: {!r}".format(heads))

    def heads_to_fetch(self):
        """Return the heads that must and that should be fetched to copy this
        branch into another repo.

        Returns: a 2-tuple of (must_fetch, if_present_fetch).  must_fetch is a
            set of heads that must be fetched.  if_present_fetch is a set of
            heads that must be fetched if present, but no error is necessary if
            they are not present.
        """
        # For bzr native formats must_fetch is just the tip, and
        # if_present_fetch are the tags.
        must_fetch = {self.last_revision()}
        if_present_fetch = set()
        if self.get_config_stack().get("branch.fetch_tags"):
            try:
                if_present_fetch = set(self.tags.get_reverse_tag_dict())
            except errors.TagsNotSupported:
                pass
        must_fetch.discard(_mod_revision.NULL_REVISION)
        if_present_fetch.discard(_mod_revision.NULL_REVISION)
        return must_fetch, if_present_fetch

    def create_memorytree(self):
        """Create a memory tree for this branch.

        Returns: An in-memory MutableTree instance
        """
        from . import memorytree

        return memorytree.MemoryTree.create_on_branch(self)


class BranchFormat(ControlComponentFormat):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format description
     * an open routine.

    Formats are placed in an dict by their format string for reference
    during branch opening. It's not required that these be instances, they
    can be classes themselves with class methods - it simply depends on
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object will be created every time regardless.
    """

    def __eq__(self, other):
        return self.__class__ is other.__class__

    def __ne__(self, other):
        return not (self == other)

    def get_reference(self, controldir, name=None):
        """Get the target reference of the branch in controldir.

        format probing must have been completed before calling
        this method - it is assumed that the format of the branch
        in controldir is correct.

        Args:
          controldir: The controldir to get the branch data from.
          name: Name of the colocated branch to fetch
        Returns: None if the branch is not a reference branch.
        """
        return None

    @classmethod
    def set_reference(self, controldir, name, to_branch):
        """Set the target reference of the branch in controldir.

        format probing must have been completed before calling
        this method - it is assumed that the format of the branch
        in controldir is correct.

        Args:
          controldir: The controldir to set the branch reference for.
          name: Name of colocated branch to set, None for default
          to_branch: branch that the checkout is to reference
        """
        raise NotImplementedError(self.set_reference)

    def get_format_description(self):
        """Return the short format description for this format."""
        raise NotImplementedError(self.get_format_description)

    def _run_post_branch_init_hooks(self, controldir, name, branch):
        hooks = Branch.hooks["post_branch_init"]
        if not hooks:
            return
        params = BranchInitHookParams(self, controldir, name, branch)
        for hook in hooks:
            hook(params)

    def initialize(
        self, controldir, name=None, repository=None, append_revisions_only=None
    ):
        """Create a branch of this format in controldir.

        Args:
          name: Name of the colocated branch to create.
        """
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def make_tags(self, branch):
        """Create a tags object for branch.

        This method is on BranchFormat, because BranchFormats are reflected
        over the wire via network_name(), whereas full Branch instances require
        multiple VFS method calls to operate at all.

        The default implementation returns a disabled-tags instance.

        Note that it is normal for branch to be a RemoteBranch when using tags
        on a RemoteBranch.
        """
        from .tag import DisabledTags

        return DisabledTags(branch)

    def network_name(self):
        """A simple byte string uniquely identifying this format for RPC calls.

        MetaDir branch formats use their disk format string to identify the
        repository over the wire. All in one formats such as bzr < 0.8, and
        foreign formats like svn/git and hg should use some marker which is
        unique and immutable.
        """
        raise NotImplementedError(self.network_name)

    def open(
        self,
        controldir,
        name=None,
        _found=False,
        ignore_fallbacks=False,
        found_repository=None,
        possible_transports=None,
    ):
        """Return the branch object for controldir.

        Args:
          controldir: A ControlDir that contains a branch.
          name: Name of colocated branch to open
          _found: a private parameter, do not use it. It is used to
            indicate if format probing has already be done.
          ignore_fallbacks: when set, no fallback branches will be opened
            (if there are any).  Default is to open fallbacks.
        """
        raise NotImplementedError(self.open)

    def supports_set_append_revisions_only(self):
        """True if this format supports set_append_revisions_only."""
        return False

    def supports_stacking(self):
        """True if this format records a stacked-on branch."""
        return False

    def supports_leaving_lock(self):
        """True if this format supports leaving locks in place."""
        return False  # by default

    def __str__(self):
        return self.get_format_description().rstrip()

    def supports_tags(self):
        """True if this format supports tags stored in the branch."""
        return False  # by default

    def tags_are_versioned(self):
        """Whether the tag container for this branch versions tags."""
        return False

    def supports_tags_referencing_ghosts(self):
        """True if tags can reference ghost revisions."""
        return True

    def supports_store_uncommitted(self):
        """True if uncommitted changes can be stored in this branch."""
        return True

    def stores_revno(self):
        """True if this branch format store revision numbers."""
        return True


class BranchHooks(Hooks):
    """A dictionary mapping hook name to a list of callables for branch hooks.

    e.g. ['post_push'] Is the list of items to be called when the
    push function is invoked.
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        Hooks.__init__(self, "breezy.branch", "Branch.hooks")
        self.add_hook(
            "open",
            "Called with the Branch object that has been opened after a "
            "branch is opened.",
            (1, 8),
        )
        self.add_hook(
            "post_push",
            "Called after a push operation completes. post_push is called "
            "with a breezy.branch.BranchPushResult object and only runs in "
            "the bzr client.",
            (0, 15),
        )
        self.add_hook(
            "post_pull",
            "Called after a pull operation completes. post_pull is called "
            "with a breezy.branch.PullResult object and only runs in the "
            "bzr client.",
            (0, 15),
        )
        self.add_hook(
            "pre_commit",
            "Called after a commit is calculated but before it is "
            "completed. pre_commit is called with (local, master, old_revno, "
            "old_revid, future_revno, future_revid, tree_delta, future_tree"
            "). old_revid is NULL_REVISION for the first commit to a branch, "
            "tree_delta is a TreeDelta object describing changes from the "
            "basis revision. hooks MUST NOT modify this delta. "
            " future_tree is an in-memory tree obtained from "
            "CommitBuilder.revision_tree() and hooks MUST NOT modify this "
            "tree.",
            (0, 91),
        )
        self.add_hook(
            "post_commit",
            "Called in the bzr client after a commit has completed. "
            "post_commit is called with (local, master, old_revno, old_revid, "
            "new_revno, new_revid). old_revid is NULL_REVISION for the first "
            "commit to a branch.",
            (0, 15),
        )
        self.add_hook(
            "post_uncommit",
            "Called in the bzr client after an uncommit completes. "
            "post_uncommit is called with (local, master, old_revno, "
            "old_revid, new_revno, new_revid) where local is the local branch "
            "or None, master is the target branch, and an empty branch "
            "receives new_revno of 0, new_revid of None.",
            (0, 15),
        )
        self.add_hook(
            "pre_change_branch_tip",
            "Called in bzr client and server before a change to the tip of a "
            "branch is made. pre_change_branch_tip is called with a "
            "breezy.branch.ChangeBranchTipParams. Note that push, pull, "
            "commit, uncommit will all trigger this hook.",
            (1, 6),
        )
        self.add_hook(
            "post_change_branch_tip",
            "Called in bzr client and server after a change to the tip of a "
            "branch is made. post_change_branch_tip is called with a "
            "breezy.branch.ChangeBranchTipParams. Note that push, pull, "
            "commit, uncommit will all trigger this hook.",
            (1, 4),
        )
        self.add_hook(
            "transform_fallback_location",
            "Called when a stacked branch is activating its fallback "
            "locations. transform_fallback_location is called with (branch, "
            "url), and should return a new url. Returning the same url "
            "allows it to be used as-is, returning a different one can be "
            "used to cause the branch to stack on a closer copy of that "
            "fallback_location. Note that the branch cannot have history "
            "accessing methods called on it during this hook because the "
            "fallback locations have not been activated. When there are "
            "multiple hooks installed for transform_fallback_location, "
            "all are called with the url returned from the previous hook."
            "The order is however undefined.",
            (1, 9),
        )
        self.add_hook(
            "automatic_tag_name",
            "Called to determine an automatic tag name for a revision. "
            "automatic_tag_name is called with (branch, revision_id) and "
            "should return a tag name or None if no tag name could be "
            "determined. The first non-None tag name returned will be used.",
            (2, 2),
        )
        self.add_hook(
            "post_branch_init",
            "Called after new branch initialization completes. "
            "post_branch_init is called with a "
            "breezy.branch.BranchInitHookParams. "
            "Note that init, branch and checkout (both heavyweight and "
            "lightweight) will all trigger this hook.",
            (2, 2),
        )
        self.add_hook(
            "post_switch",
            "Called after a checkout switches branch. "
            "post_switch is called with a "
            "breezy.branch.SwitchHookParams.",
            (2, 2),
        )


# install the default hooks into the Branch class.
Branch.hooks = BranchHooks()  # type: ignore


class ChangeBranchTipParams:
    """Object holding parameters passed to `*_change_branch_tip` hooks.

    There are 5 fields that hooks may wish to access:

    Attributes:
      branch: the branch being changed
      old_revno: revision number before the change
      new_revno: revision number after the change
      old_revid: revision id before the change
      new_revid: revision id after the change

    The revid fields are strings. The revno fields are integers.
    """

    def __init__(self, branch, old_revno, new_revno, old_revid, new_revid):
        """Create a group of ChangeBranchTip parameters.

        Args:
          branch: The branch being changed.
          old_revno: Revision number before the change.
          new_revno: Revision number after the change.
          old_revid: Tip revision id before the change.
          new_revid: Tip revision id after the change.
        """
        self.branch = branch
        self.old_revno = old_revno
        self.new_revno = new_revno
        self.old_revid = old_revid
        self.new_revid = new_revid

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<{} of {} from ({}, {}) to ({}, {})>".format(
            self.__class__.__name__,
            self.branch,
            self.old_revno,
            self.old_revid,
            self.new_revno,
            self.new_revid,
        )


class BranchInitHookParams:
    """Object holding parameters passed to `*_branch_init` hooks.

    There are 4 fields that hooks may wish to access:

    Attributes:
      format: the branch format
      bzrdir: the ControlDir where the branch will be/has been initialized
      name: name of colocated branch, if any (or None)
      branch: the branch created

    Note that for lightweight checkouts, the bzrdir and format fields refer to
    the checkout, hence they are different from the corresponding fields in
    branch, which refer to the original branch.
    """

    def __init__(self, format, controldir, name, branch):
        """Create a group of BranchInitHook parameters.

        Args:
          format: the branch format
          controldir: the ControlDir where the branch will be/has been
            initialized
          name: name of colocated branch, if any (or None)
          branch: the branch created

        Note that for lightweight checkouts, the bzrdir and format fields refer
        to the checkout, hence they are different from the corresponding fields
        in branch, which refer to the original branch.
        """
        self.format = format
        self.controldir = controldir
        self.name = name
        self.branch = branch

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<{} of {}>".format(self.__class__.__name__, self.branch)


class SwitchHookParams:
    """Object holding parameters passed to `*_switch` hooks.

    There are 4 fields that hooks may wish to access:

    Attributes:
      control_dir: ControlDir of the checkout to change
      to_branch: branch that the checkout is to reference
      force: skip the check for local commits in a heavy checkout
      revision_id: revision ID to switch to (or None)
    """

    def __init__(self, control_dir, to_branch, force, revision_id):
        """Create a group of SwitchHook parameters.

        Args:
          control_dir: ControlDir of the checkout to change
          to_branch: branch that the checkout is to reference
          force: skip the check for local commits in a heavy checkout
          revision_id: revision ID to switch to (or None)
        """
        self.control_dir = control_dir
        self.to_branch = to_branch
        self.force = force
        self.revision_id = revision_id

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<{} for {} to ({}, {})>".format(
            self.__class__.__name__, self.control_dir, self.to_branch, self.revision_id
        )


class BranchFormatRegistry(ControlComponentFormatRegistry):
    """Branch format registry."""

    def __init__(self, other_registry=None):
        super().__init__(other_registry)
        self._default_format = None
        self._default_format_key = None

    def get_default(self):
        """Return the current default format."""
        if self._default_format_key is not None and self._default_format is None:
            self._default_format = self.get(self._default_format_key)
        return self._default_format

    def set_default(self, format):
        """Set the default format."""
        self._default_format = format
        self._default_format_key = None

    def set_default_key(self, format_string):
        """Set the default format by its format string."""
        self._default_format_key = format_string
        self._default_format = None


network_format_registry = registry.FormatRegistry[BranchFormat]()
"""Registry of formats indexed by their network name.

The network name for a branch format is an identifier that can be used when
referring to formats with smart server operations. See
BranchFormat.network_name() for more detail.
"""

format_registry = BranchFormatRegistry(network_format_registry)


class BranchWriteLockResult(LogicalLockResult):
    """The result of write locking a branch.

    Attributes:
      token: The token obtained from the underlying branch lock, or
        None.
      unlock: A callable which will unlock the lock.
    """

    def __repr__(self):
        return "BranchWriteLockResult({!r}, {!r})".format(self.unlock, self.token)


######################################################################
# results of operations


class _Result:
    def _show_tag_conficts(self, to_file):
        if not getattr(self, "tag_conflicts", None):
            return
        to_file.write("Conflicting tags:\n")
        for name, _value1, _value2 in self.tag_conflicts:
            to_file.write("    {}\n".format(name))


class PullResult(_Result):
    """Result of a Branch.pull operation.

    Attributes:
      old_revno: Revision number before pull.
      new_revno: Revision number after pull.
      old_revid: Tip revision id before pull.
      new_revid: Tip revision id after pull.
      source_branch: Source (local) branch object. (read locked)
      master_branch: Master branch of the target, or the target if no
        Master
      local_branch: target branch if there is a Master, else None
      target_branch: Target/destination branch object. (write locked)
      tag_conflicts: A list of tag conflicts, see BasicTags.merge_to
      tag_updates: A dict with new tags, see BasicTags.merge_to
    """

    old_revno: Union[int, property]
    new_revno: Union[int, property]
    old_revid: RevisionID
    new_revid: RevisionID
    source_branch: Branch
    master_branch: Branch
    local_branch: Optional[Branch]
    target_branch: Branch
    tag_conflicts: List["TagConflict"]
    tag_updates: "TagUpdates"

    def report(self, to_file: TextIO) -> None:
        tag_conflicts = getattr(self, "tag_conflicts", None)
        tag_updates = getattr(self, "tag_updates", None)
        if not is_quiet():
            if self.old_revid != self.new_revid:
                to_file.write(f"Now on revision {self.new_revno}.\n")
            if tag_updates:
                to_file.write(f"{len(tag_updates)} tag(s) updated.\n")
            if self.old_revid == self.new_revid and not tag_updates:
                if not tag_conflicts:
                    to_file.write("No revisions or tags to pull.\n")
                else:
                    to_file.write("No revisions to pull.\n")
        self._show_tag_conficts(to_file)


class BranchPushResult(_Result):
    """Result of a Branch.push operation.

    Attributes:
      old_revno: Revision number (eg 10) of the target before push.
      new_revno: Revision number (eg 12) of the target after push.
      old_revid: Tip revision id (eg joe@foo.com-1234234-aoeua34) of target
        before the push.
      new_revid: Tip revision id (eg joe@foo.com-5676566-boa234a) of target
        after the push.
      source_branch: Source branch object that the push was from. This is
        read locked, and generally is a local (and thus low latency) branch.
      master_branch: If target is a bound branch, the master branch of
        target, or target itself. Always write locked.
      target_branch: The direct Branch where data is being sent (write
        locked).
      local_branch: If the target is a bound branch this will be the
        target, otherwise it will be None.
    """

    old_revno: int
    new_revno: int
    old_revid: RevisionID
    new_revid: RevisionID
    source_branch: Branch
    master_branch: Branch
    target_branch: Branch
    local_branch: Optional[Branch]

    def report(self, to_file: TextIO) -> None:
        from breezy.i18n import gettext, ngettext

        # TODO: This function gets passed a to_file, but then
        # ignores it and calls note() instead. This is also
        # inconsistent with PullResult(), which writes to stdout.
        # -- JRV20110901, bug #838853
        tag_conflicts = getattr(self, "tag_conflicts", None)
        tag_updates = getattr(self, "tag_updates", None)
        if not is_quiet():
            if self.old_revid != self.new_revid:
                if self.new_revno is not None:
                    note(gettext("Pushed up to revision %d."), self.new_revno)
                else:
                    note(
                        gettext("Pushed up to revision id %s."),
                        self.new_revid.decode("utf-8"),
                    )
            if tag_updates:
                note(
                    ngettext("%d tag updated.", "%d tags updated.", len(tag_updates))
                    % len(tag_updates)
                )
            if self.old_revid == self.new_revid and not tag_updates:
                if not tag_conflicts:
                    note(gettext("No new revisions or tags to push."))
                else:
                    note(gettext("No new revisions to push."))
        self._show_tag_conficts(to_file)


class BranchCheckResult:
    """Results of checking branch consistency.

    See `Branch.check`
    """

    def __init__(self, branch):
        self.branch = branch
        self.errors = []

    def report_results(self, verbose: bool) -> None:
        """Report the check results via trace.note.

        Args:
          verbose: Requests more detailed display of what was checked,
            if any.
        """
        from breezy.i18n import gettext

        note(
            gettext("checked branch {0} format {1}").format(
                self.branch.user_url, self.branch._format
            )
        )
        for error in self.errors:
            note(gettext("found error:%s"), error)


class InterBranch(InterObject[Branch]):
    """This class represents operations taking place between two branches.

    Its instances have methods like pull() and push() and contain
    references to the source and target repositories these operations
    can be carried out on.
    """

    _optimisers = []
    """The available optimised InterBranch types."""

    @classmethod
    def _get_branch_formats_to_test(klass):
        """Return an iterable of format tuples for testing.

        Returns: An iterable of (from_format, to_format) to use when testing
            this InterBranch class. Each InterBranch class should define this
            method itself.
        """
        raise NotImplementedError(klass._get_branch_formats_to_test)

    def pull(
        self,
        overwrite: bool = False,
        stop_revision: Optional[RevisionID] = None,
        possible_transports: Optional[List[Transport]] = None,
        local: bool = False,
        tag_selector=None,
    ) -> PullResult:
        """Mirror source into target branch.

        The target branch is considered to be 'local', having low latency.

        Returns: PullResult instance
        """
        raise NotImplementedError(self.pull)

    def push(
        self,
        overwrite: bool = False,
        stop_revision: Optional[RevisionID] = None,
        lossy: bool = False,
        _override_hook_source_branch: Optional[Branch] = None,
        tag_selector=None,
    ):
        """Mirror the source branch into the target branch.

        The source branch is considered to be 'local', having low latency.
        """
        raise NotImplementedError(self.push)

    def copy_content_into(self, revision_id=None, tag_selector=None):
        """Copy the content of source into target.

        Args:
          revision_id:
            if not None, the revision history in the new branch will
            be truncated to end with revision_id.
          tag_selector: Optional callback that can decide
            to copy or not copy tags.
        """
        raise NotImplementedError(self.copy_content_into)

    def fetch(
        self,
        stop_revision: Optional[RevisionID] = None,
        limit: Optional[int] = None,
        lossy: bool = False,
    ) -> repository.FetchResult:
        """Fetch revisions.

        Args:
          stop_revision: Last revision to fetch
          limit: Optional rough limit of revisions to fetch
        Returns: FetchResult object
        """
        raise NotImplementedError(self.fetch)

    def update_references(self) -> None:
        """Import reference information from source to target."""
        raise NotImplementedError(self.update_references)

    @classmethod
    def get(self, source: Branch, target: Branch) -> "InterBranch":
        return cast(InterBranch, super().get(source, target))


def _fix_overwrite_type(overwrite):
    if isinstance(overwrite, bool):
        if overwrite:
            return ["history", "tags"]
        else:
            return []
    return overwrite


class GenericInterBranch(InterBranch):
    """InterBranch implementation that uses public Branch functions."""

    @classmethod
    def is_compatible(klass, source, target):
        # GenericBranch uses the public API, so always compatible
        return True

    @classmethod
    def _get_branch_formats_to_test(klass):
        return [(format_registry.get_default(), format_registry.get_default())]

    @classmethod
    def unwrap_format(klass, format):
        if isinstance(format, remote.RemoteBranchFormat):
            format._ensure_real()
            return format._custom_format
        return format

    def copy_content_into(self, revision_id=None, tag_selector=None):
        """Copy the content of source into target.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        with self.source.lock_read(), self.target.lock_write():
            self.source._synchronize_history(self.target, revision_id)
            self.update_references()
            try:
                parent = self.source.get_parent()
            except errors.InaccessibleParent as e:
                mutter("parent was not accessible to copy: %s", str(e))
            else:
                if parent:
                    self.target.set_parent(parent)
            if self.source._push_should_merge_tags():
                self.source.tags.merge_to(self.target.tags, selector=tag_selector)

    def fetch(self, stop_revision=None, limit=None, lossy=False):
        if self.target.base == self.source.base:
            return (0, [])
        with self.source.lock_read(), self.target.lock_write():
            fetch_spec_factory = fetch.FetchSpecFactory()
            fetch_spec_factory.source_branch = self.source
            fetch_spec_factory.source_branch_stop_revision_id = stop_revision
            fetch_spec_factory.source_repo = self.source.repository
            fetch_spec_factory.target_repo = self.target.repository
            fetch_spec_factory.target_repo_kind = fetch.TargetRepoKinds.PREEXISTING
            fetch_spec_factory.limit = limit
            fetch_spec = fetch_spec_factory.make_fetch_spec()
            return self.target.repository.fetch(
                self.source.repository, lossy=lossy, fetch_spec=fetch_spec
            )

    def _update_revisions(self, stop_revision=None, overwrite=False, graph=None):
        with self.source.lock_read(), self.target.lock_write():
            other_revno, other_last_revision = self.source.last_revision_info()
            stop_revno = None  # unknown
            if stop_revision is None:
                stop_revision = other_last_revision
                if _mod_revision.is_null(stop_revision):
                    # if there are no commits, we're done.
                    return
                stop_revno = other_revno

            # what's the current last revision, before we fetch [and change it
            # possibly]
            last_rev = self.target.last_revision()
            # we fetch here so that we don't process data twice in the common
            # case of having something to pull, and so that the check for
            # already merged can operate on the just fetched graph, which will
            # be cached in memory.
            self.fetch(stop_revision=stop_revision)
            # Check to see if one is an ancestor of the other
            if not overwrite:
                if graph is None:
                    graph = self.target.repository.get_graph()
                if self.target._check_if_descendant_or_diverged(
                    stop_revision, last_rev, graph, self.source
                ):
                    # stop_revision is a descendant of last_rev, but we aren't
                    # overwriting, so we're done.
                    return
            if stop_revno is None:
                if graph is None:
                    graph = self.target.repository.get_graph()
                this_revno, this_last_revision = self.target.last_revision_info()
                stop_revno = graph.find_distance_to_null(
                    stop_revision,
                    [
                        (other_last_revision, other_revno),
                        (this_last_revision, this_revno),
                    ],
                )
            self.target.set_last_revision_info(stop_revno, stop_revision)

    def pull(
        self,
        overwrite=False,
        stop_revision=None,
        possible_transports=None,
        run_hooks=True,
        _override_hook_target=None,
        local=False,
        tag_selector=None,
    ):
        """Pull from source into self, updating my master if any.

        Args:
          run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        """
        with contextlib.ExitStack() as exit_stack:
            exit_stack.enter_context(self.target.lock_write())
            bound_location = self.target.get_bound_location()
            if local and not bound_location:
                raise errors.LocalRequiresBoundBranch()
            master_branch = None
            source_is_master = False
            if bound_location:
                # bound_location comes from a config file, some care has to be
                # taken to relate it to source.user_url
                normalized = urlutils.normalize_url(bound_location)
                try:
                    relpath = self.source.user_transport.relpath(normalized)
                    source_is_master = relpath == ""
                except (errors.PathNotChild, urlutils.InvalidURL):
                    source_is_master = False
            if not local and bound_location and not source_is_master:
                # not pulling from master, so we need to update master.
                master_branch = self.target.get_master_branch(possible_transports)
                exit_stack.enter_context(master_branch.lock_write())
            if master_branch:
                # pull from source into master.
                master_branch.pull(
                    self.source,
                    overwrite=overwrite,
                    stop_revision=stop_revision,
                    run_hooks=False,
                    tag_selector=tag_selector,
                )
            return self._pull(
                overwrite,
                stop_revision,
                _hook_master=master_branch,
                run_hooks=run_hooks,
                _override_hook_target=_override_hook_target,
                merge_tags_to_master=not source_is_master,
                tag_selector=tag_selector,
            )

    def push(
        self,
        overwrite=False,
        stop_revision=None,
        lossy=False,
        _override_hook_source_branch=None,
        tag_selector=None,
    ):
        """See InterBranch.push.

        This is the basic concrete implementation of push()

        Args:
          _override_hook_source_branch: If specified, run the hooks
            passing this Branch as the source, rather than self.  This is for
            use of RemoteBranch, where push is delegated to the underlying
            vfs-based Branch.
        """
        if lossy:
            raise errors.LossyPushToSameVCS(self.source, self.target)
        # TODO: Public option to disable running hooks - should be trivial but
        # needs tests.

        def _run_hooks():
            if _override_hook_source_branch:
                result.source_branch = _override_hook_source_branch
            for hook in Branch.hooks["post_push"]:
                hook(result)

        with self.source.lock_read(), self.target.lock_write():
            bound_location = self.target.get_bound_location()
            if bound_location and self.target.base != bound_location:
                # there is a master branch.
                #
                # XXX: Why the second check?  Is it even supported for a branch
                # to be bound to itself? -- mbp 20070507
                master_branch = self.target.get_master_branch()
                with master_branch.lock_write():
                    # push into the master from the source branch.
                    master_inter = InterBranch.get(self.source, master_branch)
                    master_inter._basic_push(
                        overwrite, stop_revision, tag_selector=tag_selector
                    )
                    # and push into the target branch from the source. Note
                    # that we push from the source branch again, because it's
                    # considered the highest bandwidth repository.
                    result = self._basic_push(
                        overwrite, stop_revision, tag_selector=tag_selector
                    )
                    result.master_branch = master_branch
                    result.local_branch = self.target
                    _run_hooks()
            else:
                master_branch = None
                # no master branch
                result = self._basic_push(
                    overwrite, stop_revision, tag_selector=tag_selector
                )
                # TODO: Why set master_branch and local_branch if there's no
                # binding?  Maybe cleaner to just leave them unset? -- mbp
                # 20070504
                result.master_branch = self.target
                result.local_branch = None
                _run_hooks()
            return result

    def _basic_push(self, overwrite, stop_revision, tag_selector=None):
        """Basic implementation of push without bound branches or hooks.

        Must be called with source read locked and target write locked.
        """
        result = BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revno, result.old_revid = self.target.last_revision_info()
        overwrite = _fix_overwrite_type(overwrite)
        if result.old_revid != stop_revision:
            # We assume that during 'push' this repository is closer than
            # the target.
            graph = self.source.repository.get_graph(self.target.repository)
            self._update_revisions(
                stop_revision, overwrite=("history" in overwrite), graph=graph
            )
        if self.source._push_should_merge_tags():
            result.tag_updates, result.tag_conflicts = self.source.tags.merge_to(
                self.target.tags, "tags" in overwrite, selector=tag_selector
            )
        self.update_references()
        result.new_revno, result.new_revid = self.target.last_revision_info()
        return result

    def _pull(
        self,
        overwrite=False,
        stop_revision=None,
        possible_transports=None,
        _hook_master=None,
        run_hooks=True,
        _override_hook_target=None,
        local=False,
        merge_tags_to_master=True,
        tag_selector=None,
    ):
        """See Branch.pull.

        This function is the core worker, used by GenericInterBranch.pull to
        avoid duplication when pulling source->master and source->local.

        Args:
          _hook_master: Private parameter - set the branch to
            be supplied as the master to pull hooks.
          run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
          _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
          local: Only update the local branch, and not the bound branch.
        """
        # This type of branch can't be bound.
        if local:
            raise errors.LocalRequiresBoundBranch()
        result = PullResult()
        result.source_branch = self.source
        if _override_hook_target is None:
            result.target_branch = self.target
        else:
            result.target_branch = _override_hook_target
        with self.source.lock_read():
            # We assume that during 'pull' the target repository is closer than
            # the source one.
            graph = self.target.repository.get_graph(self.source.repository)
            # TODO: Branch formats should have a flag that indicates
            # that revno's are expensive, and pull() should honor that flag.
            # -- JRV20090506
            result.old_revno, result.old_revid = self.target.last_revision_info()
            overwrite = _fix_overwrite_type(overwrite)
            self._update_revisions(
                stop_revision, overwrite=("history" in overwrite), graph=graph
            )
            # TODO: The old revid should be specified when merging tags,
            # so a tags implementation that versions tags can only
            # pull in the most recent changes. -- JRV20090506
            result.tag_updates, result.tag_conflicts = self.source.tags.merge_to(
                self.target.tags,
                "tags" in overwrite,
                ignore_master=not merge_tags_to_master,
                selector=tag_selector,
            )
            self.update_references()
            result.new_revno, result.new_revid = self.target.last_revision_info()
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = result.target_branch
            else:
                result.master_branch = result.target_branch
                result.local_branch = None
            if run_hooks:
                for hook in Branch.hooks["post_pull"]:
                    hook(result)
            return result

    def update_references(self):
        if not getattr(self.source._format, "supports_reference_locations", False):
            return
        reference_dict = self.source._get_all_reference_info()
        if len(reference_dict) == 0:
            return
        old_base = self.source.base
        new_base = self.target.base
        target_reference_dict = self.target._get_all_reference_info()
        for tree_path, (branch_location, file_id) in reference_dict.items():
            try:
                branch_location = urlutils.rebase_url(
                    branch_location, old_base, new_base
                )
            except urlutils.InvalidRebaseURLs:
                # Fall back to absolute URL
                branch_location = urlutils.join(old_base, branch_location)
            target_reference_dict.setdefault(tree_path, (branch_location, file_id))
        self.target._set_all_reference_info(target_reference_dict)


InterBranch.register_optimiser(GenericInterBranch)

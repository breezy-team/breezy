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

from __future__ import absolute_import

import bzrlib.bzrdir

from cStringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import itertools
from bzrlib import (
    bzrdir,
    controldir,
    cache_utf8,
    cleanup,
    config as _mod_config,
    debug,
    errors,
    fetch,
    graph as _mod_graph,
    lockdir,
    lockable_files,
    remote,
    repository,
    revision as _mod_revision,
    rio,
    shelf,
    tag as _mod_tag,
    transport,
    ui,
    urlutils,
    vf_search,
    )
from bzrlib.i18n import gettext, ngettext
""")

# Explicitly import bzrlib.bzrdir so that the BzrProber
# is guaranteed to be registered.
import bzrlib.bzrdir

from bzrlib import (
    bzrdir,
    controldir,
    )
from bzrlib.decorators import (
    needs_read_lock,
    needs_write_lock,
    only_raises,
    )
from bzrlib.hooks import Hooks
from bzrlib.inter import InterObject
from bzrlib.lock import _RelockDebugMixin, LogicalLockResult
from bzrlib import registry
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )
from bzrlib.trace import mutter, mutter_callsite, note, is_quiet


class Branch(controldir.ControlComponent):
    """Branch holding a history of revisions.

    :ivar base:
        Base directory/url of the branch; using control_url and
        control_transport is more standardized.
    :ivar hooks: An instance of BranchHooks.
    :ivar _master_branch_cache: cached result of get_master_branch, see
        _clear_cached_state.
    """
    # this is really an instance variable - FIXME move it there
    # - RBC 20060112
    base = None

    @property
    def control_transport(self):
        return self._transport

    @property
    def user_transport(self):
        return self.bzrdir.user_transport

    def __init__(self, possible_transports=None):
        self.tags = self._format.make_tags(self)
        self._revision_history_cache = None
        self._revision_id_to_revno_cache = None
        self._partial_revision_id_to_revno_cache = {}
        self._partial_revision_history_cache = []
        self._tags_bytes = None
        self._last_revision_info_cache = None
        self._master_branch_cache = None
        self._merge_sorted_revisions_cache = None
        self._open_hook(possible_transports)
        hooks = Branch.hooks['open']
        for hook in hooks:
            hook(self)

    def _open_hook(self, possible_transports):
        """Called by init to allow simpler extension of the base class."""

    def _activate_fallback_location(self, url, possible_transports):
        """Activate the branch/repository from url as a fallback repository."""
        for existing_fallback_repo in self.repository._fallback_repositories:
            if existing_fallback_repo.user_url == url:
                # This fallback is already configured.  This probably only
                # happens because ControlDir.sprout is a horrible mess.  To avoid
                # confusing _unstack we don't add this a second time.
                mutter('duplicate activation of fallback %r on %r', url, self)
                return
        repo = self._get_fallback_repository(url, possible_transports)
        if repo.has_same_location(self.repository):
            raise errors.UnstackableLocationError(self.user_url, url)
        self.repository.add_fallback_repository(repo)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        self.control_files.break_lock()
        self.repository.break_lock()
        master = self.get_master_branch()
        if master is not None:
            master.break_lock()

    def _check_stackable_repo(self):
        if not self.repository._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(self.repository._format,
                self.repository.base)

    def _extend_partial_history(self, stop_index=None, stop_revision=None):
        """Extend the partial history to include a given index

        If a stop_index is supplied, stop when that index has been reached.
        If a stop_revision is supplied, stop when that revision is
        encountered.  Otherwise, stop when the beginning of history is
        reached.

        :param stop_index: The index which should be present.  When it is
            present, history extension will stop.
        :param stop_revision: The revision id which should be present.  When
            it is encountered, history extension will stop.
        """
        if len(self._partial_revision_history_cache) == 0:
            self._partial_revision_history_cache = [self.last_revision()]
        repository._iter_for_revno(
            self.repository, self._partial_revision_history_cache,
            stop_index=stop_index, stop_revision=stop_revision)
        if self._partial_revision_history_cache[-1] == _mod_revision.NULL_REVISION:
            self._partial_revision_history_cache.pop()

    def _get_check_refs(self):
        """Get the references needed for check().

        See bzrlib.check.
        """
        revid = self.last_revision()
        return [('revision-existence', revid), ('lefthand-distance', revid)]

    @staticmethod
    def open(base, _unsupported=False, possible_transports=None):
        """Open the branch rooted at base.

        For instance, if the branch is at URL/.bzr/branch,
        Branch.open(URL) -> a Branch instance.
        """
        control = controldir.ControlDir.open(base,
            possible_transports=possible_transports, _unsupported=_unsupported)
        return control.open_branch(unsupported=_unsupported,
            possible_transports=possible_transports)

    @staticmethod
    def open_from_transport(transport, name=None, _unsupported=False,
            possible_transports=None):
        """Open the branch rooted at transport"""
        control = controldir.ControlDir.open_from_transport(transport, _unsupported)
        return control.open_branch(name=name, unsupported=_unsupported,
            possible_transports=possible_transports)

    @staticmethod
    def open_containing(url, possible_transports=None):
        """Open an existing branch which contains url.

        This probes for a branch at url, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an unsupported
        format, UnknownFormatError or UnsupportedFormatError are raised.
        If there is one, it is returned, along with the unused portion of url.
        """
        control, relpath = controldir.ControlDir.open_containing(url,
                                                         possible_transports)
        branch = control.open_branch(possible_transports=possible_transports)
        return (branch, relpath)

    def _push_should_merge_tags(self):
        """Should _basic_push merge this branch's tags into the target?

        The default implementation returns False if this branch has no tags,
        and True the rest of the time.  Subclasses may override this.
        """
        return self.supports_tags() and self.tags.get_tag_dict()

    def get_config(self):
        """Get a bzrlib.config.BranchConfig for this Branch.

        This can then be used to get and set configuration options for the
        branch.

        :return: A bzrlib.config.BranchConfig.
        """
        return _mod_config.BranchConfig(self)

    def get_config_stack(self):
        """Get a bzrlib.config.BranchStack for this Branch.

        This can then be used to get and set configuration options for the
        branch.

        :return: A bzrlib.config.BranchStack.
        """
        return _mod_config.BranchStack(self)

    def _get_config(self):
        """Get the concrete config for just the config in this branch.

        This is not intended for client use; see Branch.get_config for the
        public API.

        Added in 1.14.

        :return: An object supporting get_option and set_option.
        """
        raise NotImplementedError(self._get_config)

    def store_uncommitted(self, creator):
        """Store uncommitted changes from a ShelfCreator.

        :param creator: The ShelfCreator containing uncommitted changes, or
            None to delete any stored changes.
        :raises: ChangesAlreadyStored if the branch already has changes.
        """
        raise NotImplementedError(self.store_uncommitted)

    def get_unshelver(self, tree):
        """Return a shelf.Unshelver for this branch and tree.

        :param tree: The tree to use to construct the Unshelver.
        :return: an Unshelver or None if no changes are stored.
        """
        raise NotImplementedError(self.get_unshelver)

    def _get_fallback_repository(self, url, possible_transports):
        """Get the repository we fallback to at url."""
        url = urlutils.join(self.base, url)
        a_branch = Branch.open(url, possible_transports=possible_transports)
        return a_branch.repository

    @needs_read_lock
    def _get_tags_bytes(self):
        """Get the bytes of a serialised tags dict.

        Note that not all branches support tags, nor do all use the same tags
        logic: this method is specific to BasicTags. Other tag implementations
        may use the same method name and behave differently, safely, because
        of the double-dispatch via
        format.make_tags->tags_instance->get_tags_dict.

        :return: The bytes of the tags file.
        :seealso: Branch._set_tags_bytes.
        """
        if self._tags_bytes is None:
            self._tags_bytes = self._transport.get_bytes('tags')
        return self._tags_bytes

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
            except errors.RecursiveBind, e:
                raise e
            except errors.BzrError, e:
                # Silently fall back to local implicit nick if the master is
                # unavailable
                mutter("Could not connect to bound branch, "
                    "falling back to local nick.\n " + str(e))
        return config.get_nickname()

    def _set_nick(self, nick):
        self.get_config().set_user_option('nickname', nick, warn_masked=True)

    nick = property(_get_nick, _set_nick)

    def is_locked(self):
        raise NotImplementedError(self.is_locked)

    def _lefthand_history(self, revision_id, last_rev=None,
                          other_branch=None):
        if 'evil' in debug.debug_flags:
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
        while (current_rev_id in parents_map and
               len(parents_map[current_rev_id]) > 0):
            check_not_reserved_id(current_rev_id)
            new_history.append(current_rev_id)
            current_rev_id = parents_map[current_rev_id][0]
            parents_map = graph.get_parent_map([current_rev_id])
        new_history.reverse()
        return new_history

    def lock_write(self, token=None):
        """Lock the branch for write operations.

        :param token: A token to permit reacquiring a previously held and
            preserved lock.
        :return: A BranchWriteLockResult.
        """
        raise NotImplementedError(self.lock_write)

    def lock_read(self):
        """Lock the branch for read operations.

        :return: A bzrlib.lock.LogicalLockResult.
        """
        raise NotImplementedError(self.lock_read)

    def unlock(self):
        raise NotImplementedError(self.unlock)

    def peek_lock_mode(self):
        """Return lock mode for the Branch: 'r', 'w' or None"""
        raise NotImplementedError(self.peek_lock_mode)

    def get_physical_lock_status(self):
        raise NotImplementedError(self.get_physical_lock_status)

    @needs_read_lock
    def dotted_revno_to_revision_id(self, revno, _cache_reverse=False):
        """Return the revision_id for a dotted revno.

        :param revno: a tuple like (1,) or (1,1,2)
        :param _cache_reverse: a private parameter enabling storage
           of the reverse mapping in a top level cache. (This should
           only be done in selective circumstances as we want to
           avoid having the mapping cached multiple times.)
        :return: the revision_id
        :raises errors.NoSuchRevision: if the revno doesn't exist
        """
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
            return self.get_rev_id(revno[0])
        revision_id_to_revno = self.get_revision_id_to_revno_map()
        revision_ids = [revision_id for revision_id, this_revno
                        in revision_id_to_revno.iteritems()
                        if revno == this_revno]
        if len(revision_ids) == 1:
            return revision_ids[0]
        else:
            revno_str = '.'.join(map(str, revno))
            raise errors.NoSuchRevision(self, revno_str)

    @needs_read_lock
    def revision_id_to_dotted_revno(self, revision_id):
        """Given a revision id, return its dotted revno.

        :return: a tuple like (1,) or (400,1,3).
        """
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
        except errors.NoSuchRevision:
            # We need to load and use the full revno map after all
            result = self.get_revision_id_to_revno_map().get(revision_id)
            if result is None:
                raise errors.NoSuchRevision(self, revision_id)
        return result

    @needs_read_lock
    def get_revision_id_to_revno_map(self):
        """Return the revision_id => dotted revno map.

        This will be regenerated on demand, but will be cached.

        :return: A dictionary mapping revision_id => dotted revno.
            This dictionary should not be modified by the caller.
        """
        if self._revision_id_to_revno_cache is not None:
            mapping = self._revision_id_to_revno_cache
        else:
            mapping = self._gen_revno_map()
            self._cache_revision_id_to_revno(mapping)
        # TODO: jam 20070417 Since this is being cached, should we be returning
        #       a copy?
        # I would rather not, and instead just declare that users should not
        # modify the return value.
        return mapping

    def _gen_revno_map(self):
        """Create a new mapping from revision ids to dotted revnos.

        Dotted revnos are generated based on the current tip in the revision
        history.
        This is the worker function for get_revision_id_to_revno_map, which
        just caches the return value.

        :return: A dictionary mapping revision_id => dotted revno.
        """
        revision_id_to_revno = dict((rev_id, revno)
            for rev_id, depth, revno, end_of_merge
             in self.iter_merge_sorted_revisions())
        return revision_id_to_revno

    @needs_read_lock
    def iter_merge_sorted_revisions(self, start_revision_id=None,
            stop_revision_id=None, stop_rule='exclude', direction='reverse'):
        """Walk the revisions for a branch in merge sorted order.

        Merge sorted order is the output from a merge-aware,
        topological sort, i.e. all parents come before their
        children going forward; the opposite for reverse.

        :param start_revision_id: the revision_id to begin walking from.
            If None, the branch tip is used.
        :param stop_revision_id: the revision_id to terminate the walk
            after. If None, the rest of history is included.
        :param stop_rule: if stop_revision_id is not None, the precise rule
            to use for termination:

            * 'exclude' - leave the stop revision out of the result (default)
            * 'include' - the stop revision is the last item in the result
            * 'with-merges' - include the stop revision and all of its
              merged revisions in the result
            * 'with-merges-without-common-ancestry' - filter out revisions 
              that are in both ancestries
        :param direction: either 'reverse' or 'forward':

            * reverse means return the start_revision_id first, i.e.
              start at the most recent revision and go backwards in history
            * forward returns tuples in the opposite order to reverse.
              Note in particular that forward does *not* do any intelligent
              ordering w.r.t. depth as some clients of this API may like.
              (If required, that ought to be done at higher layers.)

        :return: an iterator over (revision_id, depth, revno, end_of_merge)
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
        # Note: depth and revno values are in the context of the branch so
        # we need the full graph to get stable numbers, regardless of the
        # start_revision_id.
        if self._merge_sorted_revisions_cache is None:
            last_revision = self.last_revision()
            known_graph = self.repository.get_known_graph_ancestry(
                [last_revision])
            self._merge_sorted_revisions_cache = known_graph.merge_sort(
                last_revision)
        filtered = self._filter_merge_sorted_revisions(
            self._merge_sorted_revisions_cache, start_revision_id,
            stop_revision_id, stop_rule)
        # Make sure we don't return revisions that are not part of the
        # start_revision_id ancestry.
        filtered = self._filter_start_non_ancestors(filtered)
        if direction == 'reverse':
            return filtered
        if direction == 'forward':
            return reversed(list(filtered))
        else:
            raise ValueError('invalid direction %r' % direction)

    def _filter_merge_sorted_revisions(self, merge_sorted_revisions,
        start_revision_id, stop_revision_id, stop_rule):
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
                yield (rev_id, node.merge_depth, node.revno,
                       node.end_of_merge)
        elif stop_rule == 'exclude':
            for node in rev_iter:
                rev_id = node.key
                if rev_id == stop_revision_id:
                    return
                yield (rev_id, node.merge_depth, node.revno,
                       node.end_of_merge)
        elif stop_rule == 'include':
            for node in rev_iter:
                rev_id = node.key
                yield (rev_id, node.merge_depth, node.revno,
                       node.end_of_merge)
                if rev_id == stop_revision_id:
                    return
        elif stop_rule == 'with-merges-without-common-ancestry':
            # We want to exclude all revisions that are already part of the
            # stop_revision_id ancestry.
            graph = self.repository.get_graph()
            ancestors = graph.find_unique_ancestors(start_revision_id,
                                                    [stop_revision_id])
            for node in rev_iter:
                rev_id = node.key
                if rev_id not in ancestors:
                    continue
                yield (rev_id, node.merge_depth, node.revno,
                       node.end_of_merge)
        elif stop_rule == 'with-merges':
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
                if (not reached_stop_revision_id or
                        rev_id in revision_id_whitelist):
                    yield (rev_id, node.merge_depth, node.revno,
                       node.end_of_merge)
                    if reached_stop_revision_id or rev_id == stop_revision_id:
                        # only do the merged revs of rev_id from now on
                        rev = self.repository.get_revision(rev_id)
                        if rev.parent_ids:
                            reached_stop_revision_id = True
                            revision_id_whitelist.extend(rev.parent_ids)
        else:
            raise ValueError('invalid stop_rule %r' % stop_rule)

    def _filter_start_non_ancestors(self, rev_iter):
        # If we started from a dotted revno, we want to consider it as a tip
        # and don't want to yield revisions that are not part of its
        # ancestry. Given the order guaranteed by the merge sort, we will see
        # uninteresting descendants of the first parent of our tip before the
        # tip itself.
        first = rev_iter.next()
        (rev_id, merge_depth, revno, end_of_merge) = first
        yield first
        if not merge_depth:
            # We start at a mainline revision so by definition, all others
            # revisions in rev_iter are ancestors
            for node in rev_iter:
                yield node

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

        for (rev_id, merge_depth, revno, end_of_merge) in rev_iter:
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

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.leave_in_place()

    def dont_leave_lock_in_place(self):
        """Tell this branch object to release the physical lock when this
        object is unlocked, even if it didn't originally acquire it.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.dont_leave_in_place()

    def bind(self, other):
        """Bind the local branch the other branch.

        :param other: The branch to bind to
        :type other: Branch
        """
        raise errors.UpgradeRequired(self.user_url)

    def get_append_revisions_only(self):
        """Whether it is only possible to append revisions to the history.
        """
        if not self._format.supports_set_append_revisions_only():
            return False
        return self.get_config_stack().get('append_revisions_only')

    def set_append_revisions_only(self, enabled):
        if not self._format.supports_set_append_revisions_only():
            raise errors.UpgradeRequired(self.user_url)
        self.get_config_stack().set('append_revisions_only', enabled)

    def set_reference_info(self, file_id, tree_path, branch_location):
        """Set the branch location to use for a tree reference."""
        raise errors.UnsupportedOperation(self.set_reference_info, self)

    def get_reference_info(self, file_id):
        """Get the tree_path and branch_location for a tree reference."""
        raise errors.UnsupportedOperation(self.get_reference_info, self)

    @needs_write_lock
    def fetch(self, from_branch, last_revision=None, limit=None):
        """Copy revisions from from_branch into this branch.

        :param from_branch: Where to copy from.
        :param last_revision: What revision to stop at (None for at the end
                              of the branch.
        :param limit: Optional rough limit of revisions to fetch
        :return: None
        """
        return InterBranch.get(from_branch, self).fetch(last_revision, limit=limit)

    def get_bound_location(self):
        """Return the URL of the branch we are bound to.

        Older format branches cannot bind, please be sure to use a metadir
        branch.
        """
        return None

    def get_old_bound_location(self):
        """Return the URL of the branch we used to be bound to
        """
        raise errors.UpgradeRequired(self.user_url)

    def get_commit_builder(self, parents, config_stack=None, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None, lossy=False):
        """Obtain a CommitBuilder for this branch.

        :param parents: Revision ids of the parents of the new revision.
        :param config: Optional configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS 
        """

        if config_stack is None:
            config_stack = self.get_config_stack()

        return self.repository.get_commit_builder(self, parents, config_stack,
            timestamp, timezone, committer, revprops, revision_id,
            lossy)

    def get_master_branch(self, possible_transports=None):
        """Return the branch we are bound to.

        :return: Either a Branch, or None
        """
        return None

    @deprecated_method(deprecated_in((2, 5, 0)))
    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """
        try:
            revid = self.get_rev_id(revno)
        except errors.NoSuchRevision:
            raise errors.InvalidRevisionNumber(revno)
        return self.repository.get_revision_delta(revid)

    def get_stacked_on_url(self):
        """Get the URL this branch is stacked against.

        :raises NotStacked: If the branch is not stacked.
        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        """
        raise NotImplementedError(self.get_stacked_on_url)

    def print_file(self, file, revision_id):
        """Print `file` to stdout."""
        raise NotImplementedError(self.print_file)

    @needs_write_lock
    def set_last_revision_info(self, revno, revision_id):
        """Set the last revision of this branch.

        The caller is responsible for checking that the revno is correct
        for this revision id.

        It may be possible to set the branch last revision to an id not
        present in the repository.  However, branches can also be
        configured to check constraints on history, in which case this may not
        be permitted.
        """
        raise NotImplementedError(self.set_last_revision_info)

    @needs_write_lock
    def generate_revision_history(self, revision_id, last_rev=None,
                                  other_branch=None):
        """See Branch.generate_revision_history"""
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

    @needs_write_lock
    def set_parent(self, url):
        """See Branch.set_parent."""
        # TODO: Maybe delete old location files?
        # URLs should never be unicode, even on the local fs,
        # FIXUP this and get_parent in a future branch format bump:
        # read and rewrite the file. RBC 20060125
        if url is not None:
            if isinstance(url, unicode):
                try:
                    url = url.encode('ascii')
                except UnicodeEncodeError:
                    raise errors.InvalidURL(url,
                        "Urls must be 7-bit ascii, "
                        "use bzrlib.urlutils.escape")
            url = urlutils.relative_url(self.base, url)
        self._set_parent_location(url)

    @needs_write_lock
    def set_stacked_on_url(self, url):
        """Set the URL this branch is stacked against.

        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        :raises UnstackableRepositoryFormat: If the repository does not support
            stacking.
        """
        if not self._format.supports_stacking():
            raise errors.UnstackableBranchFormat(self._format, self.user_url)
        # XXX: Changing from one fallback repository to another does not check
        # that all the data you need is present in the new fallback.
        # Possibly it should.
        self._check_stackable_repo()
        if not url:
            try:
                old_url = self.get_stacked_on_url()
            except (errors.NotStacked, errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat):
                return
            self._unstack()
        else:
            self._activate_fallback_location(url,
                possible_transports=[self.bzrdir.root_transport])
        # write this out after the repository is stacked to avoid setting a
        # stacked config that doesn't work.
        self._set_config_location('stacked_on_location', url)

    def _unstack(self):
        """Change a branch to be unstacked, copying data as needed.

        Don't call this directly, use set_stacked_on_url(None).
        """
        pb = ui.ui_factory.nested_progress_bar()
        try:
            pb.update(gettext("Unstacking"))
            # The basic approach here is to fetch the tip of the branch,
            # including all available ghosts, from the existing stacked
            # repository into a new repository object without the fallbacks. 
            #
            # XXX: See <https://launchpad.net/bugs/397286> - this may not be
            # correct for CHKMap repostiories
            old_repository = self.repository
            if len(old_repository._fallback_repositories) != 1:
                raise AssertionError("can't cope with fallback repositories "
                    "of %r (fallbacks: %r)" % (old_repository,
                        old_repository._fallback_repositories))
            # Open the new repository object.
            # Repositories don't offer an interface to remove fallback
            # repositories today; take the conceptually simpler option and just
            # reopen it.  We reopen it starting from the URL so that we
            # get a separate connection for RemoteRepositories and can
            # stream from one of them to the other.  This does mean doing
            # separate SSH connection setup, but unstacking is not a
            # common operation so it's tolerable.
            new_bzrdir = controldir.ControlDir.open(
                self.bzrdir.root_transport.base)
            new_repository = new_bzrdir.find_repository()
            if new_repository._fallback_repositories:
                raise AssertionError("didn't expect %r to have "
                    "fallback_repositories"
                    % (self.repository,))
            # Replace self.repository with the new repository.
            # Do our best to transfer the lock state (i.e. lock-tokens and
            # lock count) of self.repository to the new repository.
            lock_token = old_repository.lock_write().repository_token
            self.repository = new_repository
            if isinstance(self, remote.RemoteBranch):
                # Remote branches can have a second reference to the old
                # repository that need to be replaced.
                if self._real_branch is not None:
                    self._real_branch.repository = new_repository
            self.repository.lock_write(token=lock_token)
            if lock_token is not None:
                old_repository.leave_lock_in_place()
            old_repository.unlock()
            if lock_token is not None:
                # XXX: self.repository.leave_lock_in_place() before this
                # function will not be preserved.  Fortunately that doesn't
                # affect the current default format (2a), and would be a
                # corner-case anyway.
                #  - Andrew Bennetts, 2010/06/30
                self.repository.dont_leave_lock_in_place()
            old_lock_count = 0
            while True:
                try:
                    old_repository.unlock()
                except errors.LockNotHeld:
                    break
                old_lock_count += 1
            if old_lock_count == 0:
                raise AssertionError(
                    'old_repository should have been locked at least once.')
            for i in range(old_lock_count-1):
                self.repository.lock_write()
            # Fetch from the old repository into the new.
            old_repository.lock_read()
            try:
                # XXX: If you unstack a branch while it has a working tree
                # with a pending merge, the pending-merged revisions will no
                # longer be present.  You can (probably) revert and remerge.
                try:
                    tags_to_fetch = set(self.tags.get_reverse_tag_dict())
                except errors.TagsNotSupported:
                    tags_to_fetch = set()
                fetch_spec = vf_search.NotInOtherForRevs(self.repository,
                    old_repository, required_ids=[self.last_revision()],
                    if_present_ids=tags_to_fetch, find_ghosts=True).execute()
                self.repository.fetch(old_repository, fetch_spec=fetch_spec)
            finally:
                old_repository.unlock()
        finally:
            pb.finished()

    def _set_tags_bytes(self, bytes):
        """Mirror method for _get_tags_bytes.

        :seealso: Branch._get_tags_bytes.
        """
        op = cleanup.OperationWithCleanups(self._set_tags_bytes_locked)
        op.add_cleanup(self.lock_write().unlock)
        return op.run_simple(bytes)

    def _set_tags_bytes_locked(self, bytes):
        self._tags_bytes = bytes
        return self._transport.put_bytes('tags', bytes)

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

    def _clear_cached_state(self):
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
        self._tags_bytes = None

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

    def _revision_history(self):
        if 'evil' in debug.debug_flags:
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

    def last_revision(self):
        """Return last revision id, or NULL_REVISION."""
        return self.last_revision_info()[1]

    @needs_read_lock
    def last_revision_info(self):
        """Return information about the last revision.

        :return: A tuple (revno, revision_id).
        """
        if self._last_revision_info_cache is None:
            self._last_revision_info_cache = self._read_last_revision_info()
        return self._last_revision_info_cache

    def _read_last_revision_info(self):
        raise NotImplementedError(self._read_last_revision_info)

    def import_last_revision_info_and_tags(self, source, revno, revid,
                                           lossy=False):
        """Set the last revision info, importing from another repo if necessary.

        This is used by the bound branch code to upload a revision to
        the master branch first before updating the tip of the local branch.
        Revisions referenced by source's tags are also transferred.

        :param source: Source branch to optionally fetch from
        :param revno: Revision number of the new tip
        :param revid: Revision id of the new tip
        :param lossy: Whether to discard metadata that can not be
            natively represented
        :return: Tuple with the new revision number and revision id
            (should only be different from the arguments when lossy=True)
        """
        if not self.repository.has_same_location(source.repository):
            self.fetch(source, revid)
        self.set_last_revision_info(revno, revid)
        return (revno, revid)

    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if _mod_revision.is_null(revision_id):
            return 0
        history = self._revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError:
            raise errors.NoSuchRevision(self, revision_id)

    @needs_read_lock
    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
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

    def pull(self, source, overwrite=False, stop_revision=None,
             possible_transports=None, *args, **kwargs):
        """Mirror source into this branch.

        This branch is considered to be 'local', having low latency.

        :returns: PullResult instance
        """
        return InterBranch.get(source, self).pull(overwrite=overwrite,
            stop_revision=stop_revision,
            possible_transports=possible_transports, *args, **kwargs)

    def push(self, target, overwrite=False, stop_revision=None, lossy=False,
            *args, **kwargs):
        """Mirror this branch into target.

        This branch is considered to be 'local', having low latency.
        """
        return InterBranch.get(self, target).push(overwrite, stop_revision,
            lossy, *args, **kwargs)

    def basis_tree(self):
        """Return `Tree` object for last revision."""
        return self.repository.revision_tree(self.last_revision())

    def get_parent(self):
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
        if parent.startswith('/'):
            parent = urlutils.local_path_to_url(parent.decode('utf8'))
        try:
            return urlutils.join(self.base[:-1], parent)
        except errors.InvalidURLJoin, e:
            raise errors.InaccessibleParent(parent, self.user_url)

    def _get_parent_location(self):
        raise NotImplementedError(self._get_parent_location)

    def _set_config_location(self, name, url, config=None,
                             make_relative=False):
        if config is None:
            config = self.get_config_stack()
        if url is None:
            url = ''
        elif make_relative:
            url = urlutils.relative_url(self.base, url)
        config.set(name, url)

    def _get_config_location(self, name, config=None):
        if config is None:
            config = self.get_config_stack()
        location = config.get(name)
        if location == '':
            location = None
        return location

    def get_child_submit_format(self):
        """Return the preferred format of submissions to this branch."""
        return self.get_config_stack().get('child_submit_format')

    def get_submit_branch(self):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        return self.get_config_stack().get('submit_branch')

    def set_submit_branch(self, location):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        self.get_config_stack().set('submit_branch', location)

    def get_public_branch(self):
        """Return the public location of the branch.

        This is used by merge directives.
        """
        return self._get_config_location('public_branch')

    def set_public_branch(self, location):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        self._set_config_location('public_branch', location)

    def get_push_location(self):
        """Return None or the location to push this branch to."""
        return self.get_config_stack().get('push_location')

    def set_push_location(self, location):
        """Set a new push location for this branch."""
        raise NotImplementedError(self.set_push_location)

    def _run_post_change_branch_tip_hooks(self, old_revno, old_revid):
        """Run the post_change_branch_tip hooks."""
        hooks = Branch.hooks['post_change_branch_tip']
        if not hooks:
            return
        new_revno, new_revid = self.last_revision_info()
        params = ChangeBranchTipParams(
            self, old_revno, new_revno, old_revid, new_revid)
        for hook in hooks:
            hook(params)

    def _run_pre_change_branch_tip_hooks(self, new_revno, new_revid):
        """Run the pre_change_branch_tip hooks."""
        hooks = Branch.hooks['pre_change_branch_tip']
        if not hooks:
            return
        old_revno, old_revid = self.last_revision_info()
        params = ChangeBranchTipParams(
            self, old_revno, new_revno, old_revid, new_revid)
        for hook in hooks:
            hook(params)

    @needs_write_lock
    def update(self):
        """Synchronise this branch with the master branch if any.

        :return: None or the last_revision pivoted out during the update.
        """
        return None

    def check_revno(self, revno):
        """\
        Check whether a revno corresponds to any revision.
        Zero (the NULL revision) is considered valid.
        """
        if revno != 0:
            self.check_real_revno(revno)

    def check_real_revno(self, revno):
        """\
        Check whether a revno corresponds to a real revision.
        Zero (the NULL revision) is considered invalid
        """
        if revno < 1 or revno > self.revno():
            raise errors.InvalidRevisionNumber(revno)

    @needs_read_lock
    def clone(self, to_bzrdir, revision_id=None, repository_policy=None):
        """Clone this branch into to_bzrdir preserving all semantic values.

        Most API users will want 'create_clone_on_transport', which creates a
        new bzrdir and branch on the fly.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        result = to_bzrdir.create_branch()
        result.lock_write()
        try:
            if repository_policy is not None:
                repository_policy.configure_branch(result)
            self.copy_content_into(result, revision_id=revision_id)
        finally:
            result.unlock()
        return result

    @needs_read_lock
    def sprout(self, to_bzrdir, revision_id=None, repository_policy=None,
            repository=None):
        """Create a new line of development from the branch, into to_bzrdir.

        to_bzrdir controls the branch format.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        if (repository_policy is not None and
            repository_policy.requires_stacking()):
            to_bzrdir._format.require_stacking(_skip_repo=True)
        result = to_bzrdir.create_branch(repository=repository)
        result.lock_write()
        try:
            if repository_policy is not None:
                repository_policy.configure_branch(result)
            self.copy_content_into(result, revision_id=revision_id)
            master_url = self.get_bound_location()
            if master_url is None:
                result.set_parent(self.bzrdir.root_transport.base)
            else:
                result.set_parent(master_url)
        finally:
            result.unlock()
        return result

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch6, but works for BzrBranch5, as long as the destination's
        repository contains all the lefthand ancestors of the intended
        last_revision.  If not, set_last_revision_info will fail.

        :param destination: The branch to copy the history into
        :param revision_id: The revision-id to truncate history at.  May
          be None to copy complete history.
        """
        source_revno, source_revision_id = self.last_revision_info()
        if revision_id is None:
            revno, revision_id = source_revno, source_revision_id
        else:
            graph = self.repository.get_graph()
            try:
                revno = graph.find_distance_to_null(revision_id, 
                    [(source_revision_id, source_revno)])
            except errors.GhostRevisionsHaveNoRevno:
                # Default to 1, if we can't find anything else
                revno = 1
        destination.set_last_revision_info(revno, revision_id)

    def copy_content_into(self, destination, revision_id=None):
        """Copy the content of self into destination.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        return InterBranch.get(self, destination).copy_content_into(
            revision_id=revision_id)

    def update_references(self, target):
        if not getattr(self._format, 'supports_reference_locations', False):
            return
        reference_dict = self._get_all_reference_info()
        if len(reference_dict) == 0:
            return
        old_base = self.base
        new_base = target.base
        target_reference_dict = target._get_all_reference_info()
        for file_id, (tree_path, branch_location) in (
            reference_dict.items()):
            branch_location = urlutils.rebase_url(branch_location,
                                                  old_base, new_base)
            target_reference_dict.setdefault(
                file_id, (tree_path, branch_location))
        target._set_all_reference_info(target_reference_dict)

    @needs_read_lock
    def check(self, refs):
        """Check consistency of the branch.

        In particular this checks that revisions given in the revision-history
        do actually match up in the revision graph, and that they're all
        present in the repository.

        Callers will typically also want to check the repository.

        :param refs: Calculated refs for this branch as specified by
            branch._get_check_refs()
        :return: A BranchCheckResult.
        """
        result = BranchCheckResult(self)
        last_revno, last_revision_id = self.last_revision_info()
        actual_revno = refs[('lefthand-distance', last_revision_id)]
        if actual_revno != last_revno:
            result.errors.append(errors.BzrCheckError(
                'revno does not match len(mainline) %s != %s' % (
                last_revno, actual_revno)))
        # TODO: We should probably also check that self.revision_history
        # matches the repository for older branch formats.
        # If looking for the code that cross-checks repository parents against
        # the Graph.iter_lefthand_ancestry output, that is now a repository
        # specific check.
        return result

    def _get_checkout_format(self, lightweight=False):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        format = self.repository.bzrdir.checkout_metadir()
        format.set_branch_format(self._format)
        return format

    def create_clone_on_transport(self, to_transport, revision_id=None,
        stacked_on=None, create_prefix=False, use_existing_dir=False,
        no_tree=None):
        """Create a clone of this branch and its bzrdir.

        :param to_transport: The transport to clone onto.
        :param revision_id: The revision id to use as tip in the new branch.
            If None the tip is obtained from this branch.
        :param stacked_on: An optional URL to stack the clone on.
        :param create_prefix: Create any missing directories leading up to
            to_transport.
        :param use_existing_dir: Use an existing directory if one exists.
        """
        # XXX: Fix the bzrdir API to allow getting the branch back from the
        # clone call. Or something. 20090224 RBC/spiv.
        # XXX: Should this perhaps clone colocated branches as well, 
        # rather than just the default branch? 20100319 JRV
        if revision_id is None:
            revision_id = self.last_revision()
        dir_to = self.bzrdir.clone_on_transport(to_transport,
            revision_id=revision_id, stacked_on=stacked_on,
            create_prefix=create_prefix, use_existing_dir=use_existing_dir,
            no_tree=no_tree)
        return dir_to.open_branch()

    def create_checkout(self, to_location, revision_id=None,
                        lightweight=False, accelerator_tree=None,
                        hardlink=False):
        """Create a checkout of a branch.

        :param to_location: The url to produce the checkout at
        :param revision_id: The revision to check out
        :param lightweight: If True, produce a lightweight checkout, otherwise,
            produce a bound branch (heavyweight checkout)
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        :param hardlink: If true, hard-link files from accelerator_tree,
            where possible.
        :return: The tree of the created checkout
        """
        t = transport.get_transport(to_location)
        t.ensure_base()
        format = self._get_checkout_format(lightweight=lightweight)
        try:
            checkout = format.initialize_on_transport(t)
        except errors.AlreadyControlDirError:
            # It's fine if the control directory already exists,
            # as long as there is no existing branch and working tree.
            checkout = controldir.ControlDir.open_from_transport(t)
            try:
                checkout.open_branch()
            except errors.NotBranchError:
                pass
            else:
                raise errors.AlreadyControlDirError(t.base)
            if checkout.control_transport.base == self.bzrdir.control_transport.base:
                # When checking out to the same control directory,
                # always create a lightweight checkout
                lightweight = True

        if lightweight:
            from_branch = checkout.set_branch_reference(target_branch=self)
        else:
            policy = checkout.determine_repository_policy()
            repo = policy.acquire_repository()[0]
            checkout_branch = checkout.create_branch()
            checkout_branch.bind(self)
            # pull up to the specified revision_id to set the initial
            # branch tip correctly, and seed it with history.
            checkout_branch.pull(self, stop_revision=revision_id)
            from_branch = None
        tree = checkout.create_workingtree(revision_id,
                                           from_branch=from_branch,
                                           accelerator_tree=accelerator_tree,
                                           hardlink=hardlink)
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        try:
            for path, file_id in basis_tree.iter_references():
                reference_parent = self.reference_parent(file_id, path)
                reference_parent.create_checkout(tree.abspath(path),
                    basis_tree.get_reference_revision(file_id, path),
                    lightweight)
        finally:
            basis_tree.unlock()
        return tree

    @needs_write_lock
    def reconcile(self, thorough=True):
        """Make sure the data stored in this branch is consistent."""
        from bzrlib.reconcile import BranchReconciler
        reconciler = BranchReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler

    def reference_parent(self, file_id, path, possible_transports=None):
        """Return the parent branch for a tree-reference file_id

        :param file_id: The file_id of the tree reference
        :param path: The path of the file_id in the tree
        :return: A branch associated with the file_id
        """
        # FIXME should provide multiple branches, based on config
        return Branch.open(self.bzrdir.root_transport.clone(path).base,
                           possible_transports=possible_transports)

    def supports_tags(self):
        return self._format.supports_tags()

    def automatic_tag_name(self, revision_id):
        """Try to automatically find the tag name for a revision.

        :param revision_id: Revision id of the revision.
        :return: A tag name or None if no tag name could be determined.
        """
        for hook in Branch.hooks['automatic_tag_name']:
            ret = hook(self, revision_id)
            if ret is not None:
                return ret
        return None

    def _check_if_descendant_or_diverged(self, revision_a, revision_b, graph,
                                         other_branch):
        """Ensure that revision_b is a descendant of revision_a.

        This is a helper function for update_revisions.

        :raises: DivergedBranches if revision_b has diverged from revision_a.
        :returns: True if revision_b is a descendant of revision_a.
        """
        relation = self._revision_relations(revision_a, revision_b, graph)
        if relation == 'b_descends_from_a':
            return True
        elif relation == 'diverged':
            raise errors.DivergedBranches(self, other_branch)
        elif relation == 'a_descends_from_b':
            return False
        else:
            raise AssertionError("invalid relation: %r" % (relation,))

    def _revision_relations(self, revision_a, revision_b, graph):
        """Determine the relationship between two revisions.

        :returns: One of: 'a_descends_from_b', 'b_descends_from_a', 'diverged'
        """
        heads = graph.heads([revision_a, revision_b])
        if heads == set([revision_b]):
            return 'b_descends_from_a'
        elif heads == set([revision_a, revision_b]):
            # These branches have diverged
            return 'diverged'
        elif heads == set([revision_a]):
            return 'a_descends_from_b'
        else:
            raise AssertionError("invalid heads: %r" % (heads,))

    def heads_to_fetch(self):
        """Return the heads that must and that should be fetched to copy this
        branch into another repo.

        :returns: a 2-tuple of (must_fetch, if_present_fetch).  must_fetch is a
            set of heads that must be fetched.  if_present_fetch is a set of
            heads that must be fetched if present, but no error is necessary if
            they are not present.
        """
        # For bzr native formats must_fetch is just the tip, and
        # if_present_fetch are the tags.
        must_fetch = set([self.last_revision()])
        if_present_fetch = set()
        if self.get_config_stack().get('branch.fetch_tags'):
            try:
                if_present_fetch = set(self.tags.get_reverse_tag_dict())
            except errors.TagsNotSupported:
                pass
        must_fetch.discard(_mod_revision.NULL_REVISION)
        if_present_fetch.discard(_mod_revision.NULL_REVISION)
        return must_fetch, if_present_fetch


class BranchFormat(controldir.ControlComponentFormat):
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

        :param controldir: The controldir to get the branch data from.
        :param name: Name of the colocated branch to fetch
        :return: None if the branch is not a reference branch.
        """
        return None

    @classmethod
    def set_reference(self, controldir, name, to_branch):
        """Set the target reference of the branch in controldir.

        format probing must have been completed before calling
        this method - it is assumed that the format of the branch
        in controldir is correct.

        :param controldir: The controldir to set the branch reference for.
        :param name: Name of colocated branch to set, None for default
        :param to_branch: branch that the checkout is to reference
        """
        raise NotImplementedError(self.set_reference)

    def get_format_description(self):
        """Return the short format description for this format."""
        raise NotImplementedError(self.get_format_description)

    def _run_post_branch_init_hooks(self, controldir, name, branch):
        hooks = Branch.hooks['post_branch_init']
        if not hooks:
            return
        params = BranchInitHookParams(self, controldir, name, branch)
        for hook in hooks:
            hook(params)

    def initialize(self, controldir, name=None, repository=None,
                   append_revisions_only=None):
        """Create a branch of this format in controldir.

        :param name: Name of the colocated branch to create.
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
        return _mod_tag.DisabledTags(branch)

    def network_name(self):
        """A simple byte string uniquely identifying this format for RPC calls.

        MetaDir branch formats use their disk format string to identify the
        repository over the wire. All in one formats such as bzr < 0.8, and
        foreign formats like svn/git and hg should use some marker which is
        unique and immutable.
        """
        raise NotImplementedError(self.network_name)

    def open(self, controldir, name=None, _found=False, ignore_fallbacks=False,
            found_repository=None, possible_transports=None):
        """Return the branch object for controldir.

        :param controldir: A ControlDir that contains a branch.
        :param name: Name of colocated branch to open
        :param _found: a private parameter, do not use it. It is used to
            indicate if format probing has already be done.
        :param ignore_fallbacks: when set, no fallback branches will be opened
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
        return False # by default

    def __str__(self):
        return self.get_format_description().rstrip()

    def supports_tags(self):
        """True if this format supports tags stored in the branch"""
        return False  # by default

    def tags_are_versioned(self):
        """Whether the tag container for this branch versions tags."""
        return False

    def supports_tags_referencing_ghosts(self):
        """True if tags can reference ghost revisions."""
        return True


class MetaDirBranchFormatFactory(registry._LazyObjectGetter):
    """A factory for a BranchFormat object, permitting simple lazy registration.
    
    While none of the built in BranchFormats are lazy registered yet,
    bzrlib.tests.test_branch.TestMetaDirBranchFormatFactory demonstrates how to
    use it, and the bzr-loom plugin uses it as well (see
    bzrlib.plugins.loom.formats).
    """

    def __init__(self, format_string, module_name, member_name):
        """Create a MetaDirBranchFormatFactory.

        :param format_string: The format string the format has.
        :param module_name: Module to load the format class from.
        :param member_name: Attribute name within the module for the format class.
        """
        registry._LazyObjectGetter.__init__(self, module_name, member_name)
        self._format_string = format_string

    def get_format_string(self):
        """See BranchFormat.get_format_string."""
        return self._format_string

    def __call__(self):
        """Used for network_format_registry support."""
        return self.get_obj()()


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
        Hooks.__init__(self, "bzrlib.branch", "Branch.hooks")
        self.add_hook('open',
            "Called with the Branch object that has been opened after a "
            "branch is opened.", (1, 8))
        self.add_hook('post_push',
            "Called after a push operation completes. post_push is called "
            "with a bzrlib.branch.BranchPushResult object and only runs in the "
            "bzr client.", (0, 15))
        self.add_hook('post_pull',
            "Called after a pull operation completes. post_pull is called "
            "with a bzrlib.branch.PullResult object and only runs in the "
            "bzr client.", (0, 15))
        self.add_hook('pre_commit',
            "Called after a commit is calculated but before it is "
            "completed. pre_commit is called with (local, master, old_revno, "
            "old_revid, future_revno, future_revid, tree_delta, future_tree"
            "). old_revid is NULL_REVISION for the first commit to a branch, "
            "tree_delta is a TreeDelta object describing changes from the "
            "basis revision. hooks MUST NOT modify this delta. "
            " future_tree is an in-memory tree obtained from "
            "CommitBuilder.revision_tree() and hooks MUST NOT modify this "
            "tree.", (0,91))
        self.add_hook('post_commit',
            "Called in the bzr client after a commit has completed. "
            "post_commit is called with (local, master, old_revno, old_revid, "
            "new_revno, new_revid). old_revid is NULL_REVISION for the first "
            "commit to a branch.", (0, 15))
        self.add_hook('post_uncommit',
            "Called in the bzr client after an uncommit completes. "
            "post_uncommit is called with (local, master, old_revno, "
            "old_revid, new_revno, new_revid) where local is the local branch "
            "or None, master is the target branch, and an empty branch "
            "receives new_revno of 0, new_revid of None.", (0, 15))
        self.add_hook('pre_change_branch_tip',
            "Called in bzr client and server before a change to the tip of a "
            "branch is made. pre_change_branch_tip is called with a "
            "bzrlib.branch.ChangeBranchTipParams. Note that push, pull, "
            "commit, uncommit will all trigger this hook.", (1, 6))
        self.add_hook('post_change_branch_tip',
            "Called in bzr client and server after a change to the tip of a "
            "branch is made. post_change_branch_tip is called with a "
            "bzrlib.branch.ChangeBranchTipParams. Note that push, pull, "
            "commit, uncommit will all trigger this hook.", (1, 4))
        self.add_hook('transform_fallback_location',
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
            "The order is however undefined.", (1, 9))
        self.add_hook('automatic_tag_name',
            "Called to determine an automatic tag name for a revision. "
            "automatic_tag_name is called with (branch, revision_id) and "
            "should return a tag name or None if no tag name could be "
            "determined. The first non-None tag name returned will be used.",
            (2, 2))
        self.add_hook('post_branch_init',
            "Called after new branch initialization completes. "
            "post_branch_init is called with a "
            "bzrlib.branch.BranchInitHookParams. "
            "Note that init, branch and checkout (both heavyweight and "
            "lightweight) will all trigger this hook.", (2, 2))
        self.add_hook('post_switch',
            "Called after a checkout switches branch. "
            "post_switch is called with a "
            "bzrlib.branch.SwitchHookParams.", (2, 2))



# install the default hooks into the Branch class.
Branch.hooks = BranchHooks()


class ChangeBranchTipParams(object):
    """Object holding parameters passed to `*_change_branch_tip` hooks.

    There are 5 fields that hooks may wish to access:

    :ivar branch: the branch being changed
    :ivar old_revno: revision number before the change
    :ivar new_revno: revision number after the change
    :ivar old_revid: revision id before the change
    :ivar new_revid: revision id after the change

    The revid fields are strings. The revno fields are integers.
    """

    def __init__(self, branch, old_revno, new_revno, old_revid, new_revid):
        """Create a group of ChangeBranchTip parameters.

        :param branch: The branch being changed.
        :param old_revno: Revision number before the change.
        :param new_revno: Revision number after the change.
        :param old_revid: Tip revision id before the change.
        :param new_revid: Tip revision id after the change.
        """
        self.branch = branch
        self.old_revno = old_revno
        self.new_revno = new_revno
        self.old_revid = old_revid
        self.new_revid = new_revid

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<%s of %s from (%s, %s) to (%s, %s)>" % (
            self.__class__.__name__, self.branch,
            self.old_revno, self.old_revid, self.new_revno, self.new_revid)


class BranchInitHookParams(object):
    """Object holding parameters passed to `*_branch_init` hooks.

    There are 4 fields that hooks may wish to access:

    :ivar format: the branch format
    :ivar bzrdir: the ControlDir where the branch will be/has been initialized
    :ivar name: name of colocated branch, if any (or None)
    :ivar branch: the branch created

    Note that for lightweight checkouts, the bzrdir and format fields refer to
    the checkout, hence they are different from the corresponding fields in
    branch, which refer to the original branch.
    """

    def __init__(self, format, controldir, name, branch):
        """Create a group of BranchInitHook parameters.

        :param format: the branch format
        :param controldir: the ControlDir where the branch will be/has been
            initialized
        :param name: name of colocated branch, if any (or None)
        :param branch: the branch created

        Note that for lightweight checkouts, the bzrdir and format fields refer
        to the checkout, hence they are different from the corresponding fields
        in branch, which refer to the original branch.
        """
        self.format = format
        self.bzrdir = controldir
        self.name = name
        self.branch = branch

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<%s of %s>" % (self.__class__.__name__, self.branch)


class SwitchHookParams(object):
    """Object holding parameters passed to `*_switch` hooks.

    There are 4 fields that hooks may wish to access:

    :ivar control_dir: ControlDir of the checkout to change
    :ivar to_branch: branch that the checkout is to reference
    :ivar force: skip the check for local commits in a heavy checkout
    :ivar revision_id: revision ID to switch to (or None)
    """

    def __init__(self, control_dir, to_branch, force, revision_id):
        """Create a group of SwitchHook parameters.

        :param control_dir: ControlDir of the checkout to change
        :param to_branch: branch that the checkout is to reference
        :param force: skip the check for local commits in a heavy checkout
        :param revision_id: revision ID to switch to (or None)
        """
        self.control_dir = control_dir
        self.to_branch = to_branch
        self.force = force
        self.revision_id = revision_id

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<%s for %s to (%s, %s)>" % (self.__class__.__name__,
            self.control_dir, self.to_branch,
            self.revision_id)


class BranchFormatMetadir(bzrdir.BzrFormat, BranchFormat):
    """Base class for branch formats that live in meta directories.
    """

    def __init__(self):
        BranchFormat.__init__(self)
        bzrdir.BzrFormat.__init__(self)

    @classmethod
    def find_format(klass, controldir, name=None):
        """Return the format for the branch object in controldir."""
        try:
            transport = controldir.get_branch_transport(None, name=name)
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=name, bzrdir=controldir)
        try:
            format_string = transport.get_bytes("format")
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base, bzrdir=controldir)
        return klass._find_format(format_registry, 'branch', format_string)

    def _branch_class(self):
        """What class to instantiate on open calls."""
        raise NotImplementedError(self._branch_class)

    def _get_initial_config(self, append_revisions_only=None):
        if append_revisions_only:
            return "append_revisions_only = True\n"
        else:
            # Avoid writing anything if append_revisions_only is disabled,
            # as that is the default.
            return ""

    def _initialize_helper(self, a_bzrdir, utf8_files, name=None,
                           repository=None):
        """Initialize a branch in a control dir, with specified files

        :param a_bzrdir: The bzrdir to initialize the branch in
        :param utf8_files: The files to create as a list of
            (filename, content) tuples
        :param name: Name of colocated branch to create, if any
        :return: a branch in this format
        """
        if name is None:
            name = a_bzrdir._get_selected_branch()
        mutter('creating branch %r in %s', self, a_bzrdir.user_url)
        branch_transport = a_bzrdir.get_branch_transport(self, name=name)
        control_files = lockable_files.LockableFiles(branch_transport,
            'lock', lockdir.LockDir)
        control_files.create_lock()
        control_files.lock_write()
        try:
            utf8_files += [('format', self.as_string())]
            for (filename, content) in utf8_files:
                branch_transport.put_bytes(
                    filename, content,
                    mode=a_bzrdir._get_file_mode())
        finally:
            control_files.unlock()
        branch = self.open(a_bzrdir, name, _found=True,
                found_repository=repository)
        self._run_post_branch_init_hooks(a_bzrdir, name, branch)
        return branch

    def open(self, a_bzrdir, name=None, _found=False, ignore_fallbacks=False,
            found_repository=None, possible_transports=None):
        """See BranchFormat.open()."""
        if name is None:
            name = a_bzrdir._get_selected_branch()
        if not _found:
            format = BranchFormatMetadir.find_format(a_bzrdir, name=name)
            if format.__class__ != self.__class__:
                raise AssertionError("wrong format %r found for %r" %
                    (format, self))
        transport = a_bzrdir.get_branch_transport(None, name=name)
        try:
            control_files = lockable_files.LockableFiles(transport, 'lock',
                                                         lockdir.LockDir)
            if found_repository is None:
                found_repository = a_bzrdir.find_repository()
            return self._branch_class()(_format=self,
                              _control_files=control_files,
                              name=name,
                              a_bzrdir=a_bzrdir,
                              _repository=found_repository,
                              ignore_fallbacks=ignore_fallbacks,
                              possible_transports=possible_transports)
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base, bzrdir=a_bzrdir)

    @property
    def _matchingbzrdir(self):
        ret = bzrdir.BzrDirMetaFormat1()
        ret.set_branch_format(self)
        return ret

    def supports_tags(self):
        return True

    def supports_leaving_lock(self):
        return True

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
            basedir=None):
        BranchFormat.check_support_status(self,
            allow_unsupported=allow_unsupported, recommend_upgrade=recommend_upgrade,
            basedir=basedir)
        bzrdir.BzrFormat.check_support_status(self, allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade, basedir=basedir)


class BzrBranchFormat6(BranchFormatMetadir):
    """Branch format with last-revision and tags.

    Unlike previous formats, this has no explicit revision history. Instead,
    this just stores the last-revision, and the left-hand history leading
    up to there is the history.

    This format was introduced in bzr 0.15
    and became the default in 0.91.
    """

    def _branch_class(self):
        return BzrBranch6

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return "Bazaar Branch Format 6 (bzr 0.15)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 6"

    def initialize(self, a_bzrdir, name=None, repository=None,
                   append_revisions_only=None):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('last-revision', '0 null:\n'),
                      ('branch.conf',
                          self._get_initial_config(append_revisions_only)),
                      ('tags', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files, name, repository)

    def make_tags(self, branch):
        """See bzrlib.branch.BranchFormat.make_tags()."""
        return _mod_tag.BasicTags(branch)

    def supports_set_append_revisions_only(self):
        return True


class BzrBranchFormat8(BranchFormatMetadir):
    """Metadir format supporting storing locations of subtree branches."""

    def _branch_class(self):
        return BzrBranch8

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return "Bazaar Branch Format 8 (needs bzr 1.15)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 8"

    def initialize(self, a_bzrdir, name=None, repository=None,
                   append_revisions_only=None):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('last-revision', '0 null:\n'),
                      ('branch.conf',
                          self._get_initial_config(append_revisions_only)),
                      ('tags', ''),
                      ('references', '')
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files, name, repository)

    def make_tags(self, branch):
        """See bzrlib.branch.BranchFormat.make_tags()."""
        return _mod_tag.BasicTags(branch)

    def supports_set_append_revisions_only(self):
        return True

    def supports_stacking(self):
        return True

    supports_reference_locations = True


class BzrBranchFormat7(BranchFormatMetadir):
    """Branch format with last-revision, tags, and a stacked location pointer.

    The stacked location pointer is passed down to the repository and requires
    a repository format with supports_external_lookups = True.

    This format was introduced in bzr 1.6.
    """

    def initialize(self, a_bzrdir, name=None, repository=None,
                   append_revisions_only=None):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('last-revision', '0 null:\n'),
                      ('branch.conf',
                          self._get_initial_config(append_revisions_only)),
                      ('tags', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files, name, repository)

    def _branch_class(self):
        return BzrBranch7

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return "Bazaar Branch Format 7 (needs bzr 1.6)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 7"

    def supports_set_append_revisions_only(self):
        return True

    def supports_stacking(self):
        return True

    def make_tags(self, branch):
        """See bzrlib.branch.BranchFormat.make_tags()."""
        return _mod_tag.BasicTags(branch)

    supports_reference_locations = False


class BranchReferenceFormat(BranchFormatMetadir):
    """Bzr branch reference format.

    Branch references are used in implementing checkouts, they
    act as an alias to the real branch which is at some other url.

    This format has:
     - A location file
     - a format string
    """

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return "Bazaar-NG Branch Reference Format 1\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Checkout reference format 1"

    def get_reference(self, a_bzrdir, name=None):
        """See BranchFormat.get_reference()."""
        transport = a_bzrdir.get_branch_transport(None, name=name)
        return transport.get_bytes('location')

    def set_reference(self, a_bzrdir, name, to_branch):
        """See BranchFormat.set_reference()."""
        transport = a_bzrdir.get_branch_transport(None, name=name)
        location = transport.put_bytes('location', to_branch.base)

    def initialize(self, a_bzrdir, name=None, target_branch=None,
            repository=None, append_revisions_only=None):
        """Create a branch of this format in a_bzrdir."""
        if target_branch is None:
            # this format does not implement branch itself, thus the implicit
            # creation contract must see it as uninitializable
            raise errors.UninitializableFormat(self)
        mutter('creating branch reference in %s', a_bzrdir.user_url)
        if a_bzrdir._format.fixed_components:
            raise errors.IncompatibleFormat(self, a_bzrdir._format)
        if name is None:
            name = a_bzrdir._get_selected_branch()
        branch_transport = a_bzrdir.get_branch_transport(self, name=name)
        branch_transport.put_bytes('location',
            target_branch.user_url)
        branch_transport.put_bytes('format', self.as_string())
        branch = self.open(a_bzrdir, name, _found=True,
            possible_transports=[target_branch.bzrdir.root_transport])
        self._run_post_branch_init_hooks(a_bzrdir, name, branch)
        return branch

    def _make_reference_clone_function(format, a_branch):
        """Create a clone() routine for a branch dynamically."""
        def clone(to_bzrdir, revision_id=None,
            repository_policy=None):
            """See Branch.clone()."""
            return format.initialize(to_bzrdir, target_branch=a_branch)
            # cannot obey revision_id limits when cloning a reference ...
            # FIXME RBC 20060210 either nuke revision_id for clone, or
            # emit some sort of warning/error to the caller ?!
        return clone

    def open(self, a_bzrdir, name=None, _found=False, location=None,
             possible_transports=None, ignore_fallbacks=False,
             found_repository=None):
        """Return the branch that the branch reference in a_bzrdir points at.

        :param a_bzrdir: A BzrDir that contains a branch.
        :param name: Name of colocated branch to open, if any
        :param _found: a private parameter, do not use it. It is used to
            indicate if format probing has already be done.
        :param ignore_fallbacks: when set, no fallback branches will be opened
            (if there are any).  Default is to open fallbacks.
        :param location: The location of the referenced branch.  If
            unspecified, this will be determined from the branch reference in
            a_bzrdir.
        :param possible_transports: An optional reusable transports list.
        """
        if name is None:
            name = a_bzrdir._get_selected_branch()
        if not _found:
            format = BranchFormatMetadir.find_format(a_bzrdir, name=name)
            if format.__class__ != self.__class__:
                raise AssertionError("wrong format %r found for %r" %
                    (format, self))
        if location is None:
            location = self.get_reference(a_bzrdir, name)
        real_bzrdir = controldir.ControlDir.open(
            location, possible_transports=possible_transports)
        result = real_bzrdir.open_branch(ignore_fallbacks=ignore_fallbacks,
            possible_transports=possible_transports)
        # this changes the behaviour of result.clone to create a new reference
        # rather than a copy of the content of the branch.
        # I did not use a proxy object because that needs much more extensive
        # testing, and we are only changing one behaviour at the moment.
        # If we decide to alter more behaviours - i.e. the implicit nickname
        # then this should be refactored to introduce a tested proxy branch
        # and a subclass of that for use in overriding clone() and ....
        # - RBC 20060210
        result.clone = self._make_reference_clone_function(result)
        return result


class BranchFormatRegistry(controldir.ControlComponentFormatRegistry):
    """Branch format registry."""

    def __init__(self, other_registry=None):
        super(BranchFormatRegistry, self).__init__(other_registry)
        self._default_format = None

    def set_default(self, format):
        self._default_format = format

    def get_default(self):
        return self._default_format


network_format_registry = registry.FormatRegistry()
"""Registry of formats indexed by their network name.

The network name for a branch format is an identifier that can be used when
referring to formats with smart server operations. See
BranchFormat.network_name() for more detail.
"""

format_registry = BranchFormatRegistry(network_format_registry)


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
__format6 = BzrBranchFormat6()
__format7 = BzrBranchFormat7()
__format8 = BzrBranchFormat8()
format_registry.register_lazy(
    "Bazaar-NG branch format 5\n", "bzrlib.branchfmt.fullhistory", "BzrBranchFormat5")
format_registry.register(BranchReferenceFormat())
format_registry.register(__format6)
format_registry.register(__format7)
format_registry.register(__format8)
format_registry.set_default(__format7)


class BranchWriteLockResult(LogicalLockResult):
    """The result of write locking a branch.

    :ivar branch_token: The token obtained from the underlying branch lock, or
        None.
    :ivar unlock: A callable which will unlock the lock.
    """

    def __init__(self, unlock, branch_token):
        LogicalLockResult.__init__(self, unlock)
        self.branch_token = branch_token

    def __repr__(self):
        return "BranchWriteLockResult(%s, %s)" % (self.branch_token,
            self.unlock)


class BzrBranch(Branch, _RelockDebugMixin):
    """A branch stored in the actual filesystem.

    Note that it's "local" in the context of the filesystem; it doesn't
    really matter if it's on an nfs/smb/afs/coda/... share, as long as
    it's writable, and can be accessed via the normal filesystem API.

    :ivar _transport: Transport for file operations on this branch's
        control files, typically pointing to the .bzr/branch directory.
    :ivar repository: Repository for this branch.
    :ivar base: The url of the base directory for this branch; the one
        containing the .bzr directory.
    :ivar name: Optional colocated branch name as it exists in the control
        directory.
    """

    def __init__(self, _format=None,
                 _control_files=None, a_bzrdir=None, name=None,
                 _repository=None, ignore_fallbacks=False,
                 possible_transports=None):
        """Create new branch object at a particular location."""
        if a_bzrdir is None:
            raise ValueError('a_bzrdir must be supplied')
        if name is None:
            raise ValueError('name must be supplied')
        self.bzrdir = a_bzrdir
        self._user_transport = self.bzrdir.transport.clone('..')
        if name != "":
            self._user_transport.set_segment_parameter(
                "branch", urlutils.escape(name))
        self._base = self._user_transport.base
        self.name = name
        self._format = _format
        if _control_files is None:
            raise ValueError('BzrBranch _control_files is None')
        self.control_files = _control_files
        self._transport = _control_files._transport
        self.repository = _repository
        self.conf_store = None
        Branch.__init__(self, possible_transports)

    def __str__(self):
        return '%s(%s)' % (self.__class__.__name__, self.user_url)

    __repr__ = __str__

    def _get_base(self):
        """Returns the directory containing the control directory."""
        return self._base

    base = property(_get_base, doc="The URL for the root of this branch.")

    @property
    def user_transport(self):
        return self._user_transport

    def _get_config(self):
        return _mod_config.TransportConfig(self._transport, 'branch.conf')

    def _get_config_store(self):
        if self.conf_store is None:
            self.conf_store =  _mod_config.BranchStore(self)
        return self.conf_store

    def _uncommitted_branch(self):
        """Return the branch that may contain uncommitted changes."""
        master = self.get_master_branch()
        if master is not None:
            return master
        else:
            return self

    def store_uncommitted(self, creator):
        """Store uncommitted changes from a ShelfCreator.

        :param creator: The ShelfCreator containing uncommitted changes, or
            None to delete any stored changes.
        :raises: ChangesAlreadyStored if the branch already has changes.
        """
        branch = self._uncommitted_branch()
        if creator is None:
            branch._transport.delete('stored-transform')
            return
        if branch._transport.has('stored-transform'):
            raise errors.ChangesAlreadyStored
        transform = StringIO()
        creator.write_shelf(transform)
        transform.seek(0)
        branch._transport.put_file('stored-transform', transform)

    def get_unshelver(self, tree):
        """Return a shelf.Unshelver for this branch and tree.

        :param tree: The tree to use to construct the Unshelver.
        :return: an Unshelver or None if no changes are stored.
        """
        branch = self._uncommitted_branch()
        try:
            transform = branch._transport.get('stored-transform')
        except errors.NoSuchFile:
            return None
        return shelf.Unshelver.from_tree_and_shelf(tree, transform)

    def is_locked(self):
        return self.control_files.is_locked()

    def lock_write(self, token=None):
        """Lock the branch for write operations.

        :param token: A token to permit reacquiring a previously held and
            preserved lock.
        :return: A BranchWriteLockResult.
        """
        if not self.is_locked():
            self._note_lock('w')
            self.repository._warn_if_deprecated(self)
            self.repository.lock_write()
            took_lock = True
        else:
            took_lock = False
        try:
            return BranchWriteLockResult(self.unlock,
                self.control_files.lock_write(token=token))
        except:
            if took_lock:
                self.repository.unlock()
            raise

    def lock_read(self):
        """Lock the branch for read operations.

        :return: A bzrlib.lock.LogicalLockResult.
        """
        if not self.is_locked():
            self._note_lock('r')
            self.repository._warn_if_deprecated(self)
            self.repository.lock_read()
            took_lock = True
        else:
            took_lock = False
        try:
            self.control_files.lock_read()
            return LogicalLockResult(self.unlock)
        except:
            if took_lock:
                self.repository.unlock()
            raise

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if self.control_files._lock_count == 1 and self.conf_store is not None:
            self.conf_store.save_changes()
        try:
            self.control_files.unlock()
        finally:
            if not self.control_files.is_locked():
                self.repository.unlock()
                # we just released the lock
                self._clear_cached_state()

    def peek_lock_mode(self):
        if self.control_files._lock_count == 0:
            return None
        else:
            return self.control_files._lock_mode

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    @needs_read_lock
    def print_file(self, file, revision_id):
        """See Branch.print_file."""
        return self.repository.print_file(file, revision_id)

    @needs_write_lock
    def set_last_revision_info(self, revno, revision_id):
        if not revision_id or not isinstance(revision_id, basestring):
            raise errors.InvalidRevisionId(revision_id=revision_id, branch=self)
        revision_id = _mod_revision.ensure_null(revision_id)
        old_revno, old_revid = self.last_revision_info()
        if self.get_append_revisions_only():
            self._check_history_violation(revision_id)
        self._run_pre_change_branch_tip_hooks(revno, revision_id)
        self._write_last_revision_info(revno, revision_id)
        self._clear_cached_state()
        self._last_revision_info_cache = revno, revision_id
        self._run_post_change_branch_tip_hooks(old_revno, old_revid)

    def basis_tree(self):
        """See Branch.basis_tree."""
        return self.repository.revision_tree(self.last_revision())

    def _get_parent_location(self):
        _locs = ['parent', 'pull', 'x-pull']
        for l in _locs:
            try:
                return self._transport.get_bytes(l).strip('\n')
            except errors.NoSuchFile:
                pass
        return None

    def get_stacked_on_url(self):
        raise errors.UnstackableBranchFormat(self._format, self.user_url)

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option(
            'push_location', location,
            store=_mod_config.STORE_LOCATION_NORECURSE)

    def _set_parent_location(self, url):
        if url is None:
            self._transport.delete('parent')
        else:
            self._transport.put_bytes('parent', url + '\n',
                mode=self.bzrdir._get_file_mode())

    @needs_write_lock
    def unbind(self):
        """If bound, unbind"""
        return self.set_bound_location(None)

    @needs_write_lock
    def bind(self, other):
        """Bind this branch to the branch other.

        This does not push or pull data between the branches, though it does
        check for divergence to raise an error when the branches are not
        either the same, or one a prefix of the other. That behaviour may not
        be useful, so that check may be removed in future.

        :param other: The branch to bind to
        :type other: Branch
        """
        # TODO: jam 20051230 Consider checking if the target is bound
        #       It is debatable whether you should be able to bind to
        #       a branch which is itself bound.
        #       Committing is obviously forbidden,
        #       but binding itself may not be.
        #       Since we *have* to check at commit time, we don't
        #       *need* to check here

        # we want to raise diverged if:
        # last_rev is not in the other_last_rev history, AND
        # other_last_rev is not in our history, and do it without pulling
        # history around
        self.set_bound_location(other.base)

    def get_bound_location(self):
        try:
            return self._transport.get_bytes('bound')[:-1]
        except errors.NoSuchFile:
            return None

    @needs_read_lock
    def get_master_branch(self, possible_transports=None):
        """Return the branch we are bound to.

        :return: Either a Branch, or None
        """
        if self._master_branch_cache is None:
            self._master_branch_cache = self._get_master_branch(
                possible_transports)
        return self._master_branch_cache

    def _get_master_branch(self, possible_transports):
        bound_loc = self.get_bound_location()
        if not bound_loc:
            return None
        try:
            return Branch.open(bound_loc,
                               possible_transports=possible_transports)
        except (errors.NotBranchError, errors.ConnectionError), e:
            raise errors.BoundBranchConnectionFailure(
                    self, bound_loc, e)

    @needs_write_lock
    def set_bound_location(self, location):
        """Set the target where this branch is bound to.

        :param location: URL to the target branch
        """
        self._master_branch_cache = None
        if location:
            self._transport.put_bytes('bound', location+'\n',
                mode=self.bzrdir._get_file_mode())
        else:
            try:
                self._transport.delete('bound')
            except errors.NoSuchFile:
                return False
            return True

    @needs_write_lock
    def update(self, possible_transports=None):
        """Synchronise this branch with the master branch if any.

        :return: None or the last_revision that was pivoted out during the
                 update.
        """
        master = self.get_master_branch(possible_transports)
        if master is not None:
            old_tip = _mod_revision.ensure_null(self.last_revision())
            self.pull(master, overwrite=True)
            if self.repository.get_graph().is_ancestor(old_tip,
                _mod_revision.ensure_null(self.last_revision())):
                return None
            return old_tip
        return None

    def _read_last_revision_info(self):
        revision_string = self._transport.get_bytes('last-revision')
        revno, revision_id = revision_string.rstrip('\n').split(' ', 1)
        revision_id = cache_utf8.get_cached_utf8(revision_id)
        revno = int(revno)
        return revno, revision_id

    def _write_last_revision_info(self, revno, revision_id):
        """Simply write out the revision id, with no checks.

        Use set_last_revision_info to perform this safely.

        Does not update the revision_history cache.
        """
        revision_id = _mod_revision.ensure_null(revision_id)
        out_string = '%d %s\n' % (revno, revision_id)
        self._transport.put_bytes('last-revision', out_string,
            mode=self.bzrdir._get_file_mode())

    @needs_write_lock
    def update_feature_flags(self, updated_flags):
        """Update the feature flags for this branch.

        :param updated_flags: Dictionary mapping feature names to necessities
            A necessity can be None to indicate the feature should be removed
        """
        self._format._update_feature_flags(updated_flags)
        self.control_transport.put_bytes('format', self._format.as_string())


class BzrBranch8(BzrBranch):
    """A branch that stores tree-reference locations."""

    def _open_hook(self, possible_transports=None):
        if self._ignore_fallbacks:
            return
        if possible_transports is None:
            possible_transports = [self.bzrdir.root_transport]
        try:
            url = self.get_stacked_on_url()
        except (errors.UnstackableRepositoryFormat, errors.NotStacked,
            errors.UnstackableBranchFormat):
            pass
        else:
            for hook in Branch.hooks['transform_fallback_location']:
                url = hook(self, url)
                if url is None:
                    hook_name = Branch.hooks.get_hook_name(hook)
                    raise AssertionError(
                        "'transform_fallback_location' hook %s returned "
                        "None, not a URL." % hook_name)
            self._activate_fallback_location(url,
                possible_transports=possible_transports)

    def __init__(self, *args, **kwargs):
        self._ignore_fallbacks = kwargs.get('ignore_fallbacks', False)
        super(BzrBranch8, self).__init__(*args, **kwargs)
        self._last_revision_info_cache = None
        self._reference_info = None

    def _clear_cached_state(self):
        super(BzrBranch8, self)._clear_cached_state()
        self._last_revision_info_cache = None
        self._reference_info = None

    def _check_history_violation(self, revision_id):
        current_revid = self.last_revision()
        last_revision = _mod_revision.ensure_null(current_revid)
        if _mod_revision.is_null(last_revision):
            return
        graph = self.repository.get_graph()
        for lh_ancestor in graph.iter_lefthand_ancestry(revision_id):
            if lh_ancestor == current_revid:
                return
        raise errors.AppendRevisionsOnlyViolation(self.user_url)

    def _gen_revision_history(self):
        """Generate the revision history from last revision
        """
        last_revno, last_revision = self.last_revision_info()
        self._extend_partial_history(stop_index=last_revno-1)
        return list(reversed(self._partial_revision_history_cache))

    @needs_write_lock
    def _set_parent_location(self, url):
        """Set the parent branch"""
        self._set_config_location('parent_location', url, make_relative=True)

    @needs_read_lock
    def _get_parent_location(self):
        """Set the parent branch"""
        return self._get_config_location('parent_location')

    @needs_write_lock
    def _set_all_reference_info(self, info_dict):
        """Replace all reference info stored in a branch.

        :param info_dict: A dict of {file_id: (tree_path, branch_location)}
        """
        s = StringIO()
        writer = rio.RioWriter(s)
        for key, (tree_path, branch_location) in info_dict.iteritems():
            stanza = rio.Stanza(file_id=key, tree_path=tree_path,
                                branch_location=branch_location)
            writer.write_stanza(stanza)
        self._transport.put_bytes('references', s.getvalue())
        self._reference_info = info_dict

    @needs_read_lock
    def _get_all_reference_info(self):
        """Return all the reference info stored in a branch.

        :return: A dict of {file_id: (tree_path, branch_location)}
        """
        if self._reference_info is not None:
            return self._reference_info
        rio_file = self._transport.get('references')
        try:
            stanzas = rio.read_stanzas(rio_file)
            info_dict = dict((s['file_id'], (s['tree_path'],
                             s['branch_location'])) for s in stanzas)
        finally:
            rio_file.close()
        self._reference_info = info_dict
        return info_dict

    def set_reference_info(self, file_id, tree_path, branch_location):
        """Set the branch location to use for a tree reference.

        :param file_id: The file-id of the tree reference.
        :param tree_path: The path of the tree reference in the tree.
        :param branch_location: The location of the branch to retrieve tree
            references from.
        """
        info_dict = self._get_all_reference_info()
        info_dict[file_id] = (tree_path, branch_location)
        if None in (tree_path, branch_location):
            if tree_path is not None:
                raise ValueError('tree_path must be None when branch_location'
                                 ' is None.')
            if branch_location is not None:
                raise ValueError('branch_location must be None when tree_path'
                                 ' is None.')
            del info_dict[file_id]
        self._set_all_reference_info(info_dict)

    def get_reference_info(self, file_id):
        """Get the tree_path and branch_location for a tree reference.

        :return: a tuple of (tree_path, branch_location)
        """
        return self._get_all_reference_info().get(file_id, (None, None))

    def reference_parent(self, file_id, path, possible_transports=None):
        """Return the parent branch for a tree-reference file_id.

        :param file_id: The file_id of the tree reference
        :param path: The path of the file_id in the tree
        :return: A branch associated with the file_id
        """
        branch_location = self.get_reference_info(file_id)[1]
        if branch_location is None:
            return Branch.reference_parent(self, file_id, path,
                                           possible_transports)
        branch_location = urlutils.join(self.user_url, branch_location)
        return Branch.open(branch_location,
                           possible_transports=possible_transports)

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self._set_config_location('push_location', location)

    def set_bound_location(self, location):
        """See Branch.set_push_location."""
        self._master_branch_cache = None
        result = None
        conf = self.get_config_stack()
        if location is None:
            if not conf.get('bound'):
                return False
            else:
                conf.set('bound', 'False')
                return True
        else:
            self._set_config_location('bound_location', location,
                                      config=conf)
            conf.set('bound', 'True')
        return True

    def _get_bound_location(self, bound):
        """Return the bound location in the config file.

        Return None if the bound parameter does not match"""
        conf = self.get_config_stack()
        if conf.get('bound') != bound:
            return None
        return self._get_config_location('bound_location', config=conf)

    def get_bound_location(self):
        """See Branch.get_bound_location."""
        return self._get_bound_location(True)

    def get_old_bound_location(self):
        """See Branch.get_old_bound_location"""
        return self._get_bound_location(False)

    def get_stacked_on_url(self):
        # you can always ask for the URL; but you might not be able to use it
        # if the repo can't support stacking.
        ## self._check_stackable_repo()
        # stacked_on_location is only ever defined in branch.conf, so don't
        # waste effort reading the whole stack of config files.
        conf = _mod_config.BranchOnlyStack(self)
        stacked_url = self._get_config_location('stacked_on_location',
                                                config=conf)
        if stacked_url is None:
            raise errors.NotStacked(self)
        return stacked_url.encode('utf-8')

    @needs_read_lock
    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        if revno == 0:
            return _mod_revision.NULL_REVISION

        last_revno, last_revision_id = self.last_revision_info()
        if revno <= 0 or revno > last_revno:
            raise errors.NoSuchRevision(self, revno)

        if history is not None:
            return history[revno - 1]

        index = last_revno - revno
        if len(self._partial_revision_history_cache) <= index:
            self._extend_partial_history(stop_index=index)
        if len(self._partial_revision_history_cache) > index:
            return self._partial_revision_history_cache[index]
        else:
            raise errors.NoSuchRevision(self, revno)

    @needs_read_lock
    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if _mod_revision.is_null(revision_id):
            return 0
        try:
            index = self._partial_revision_history_cache.index(revision_id)
        except ValueError:
            try:
                self._extend_partial_history(stop_revision=revision_id)
            except errors.RevisionNotPresent, e:
                raise errors.GhostRevisionsHaveNoRevno(revision_id, e.revision_id)
            index = len(self._partial_revision_history_cache) - 1
            if index < 0:
                raise errors.NoSuchRevision(self, revision_id)
            if self._partial_revision_history_cache[index] != revision_id:
                raise errors.NoSuchRevision(self, revision_id)
        return self.revno() - index


class BzrBranch7(BzrBranch8):
    """A branch with support for a fallback repository."""

    def set_reference_info(self, file_id, tree_path, branch_location):
        Branch.set_reference_info(self, file_id, tree_path, branch_location)

    def get_reference_info(self, file_id):
        Branch.get_reference_info(self, file_id)

    def reference_parent(self, file_id, path, possible_transports=None):
        return Branch.reference_parent(self, file_id, path,
                                       possible_transports)


class BzrBranch6(BzrBranch7):
    """See BzrBranchFormat6 for the capabilities of this branch.

    This subclass of BzrBranch7 disables the new features BzrBranch7 added,
    i.e. stacking.
    """

    def get_stacked_on_url(self):
        raise errors.UnstackableBranchFormat(self._format, self.user_url)


######################################################################
# results of operations


class _Result(object):

    def _show_tag_conficts(self, to_file):
        if not getattr(self, 'tag_conflicts', None):
            return
        to_file.write('Conflicting tags:\n')
        for name, value1, value2 in self.tag_conflicts:
            to_file.write('    %s\n' % (name, ))


class PullResult(_Result):
    """Result of a Branch.pull operation.

    :ivar old_revno: Revision number before pull.
    :ivar new_revno: Revision number after pull.
    :ivar old_revid: Tip revision id before pull.
    :ivar new_revid: Tip revision id after pull.
    :ivar source_branch: Source (local) branch object. (read locked)
    :ivar master_branch: Master branch of the target, or the target if no
        Master
    :ivar local_branch: target branch if there is a Master, else None
    :ivar target_branch: Target/destination branch object. (write locked)
    :ivar tag_conflicts: A list of tag conflicts, see BasicTags.merge_to
    :ivar tag_updates: A dict with new tags, see BasicTags.merge_to
    """

    def report(self, to_file):
        tag_conflicts = getattr(self, "tag_conflicts", None)
        tag_updates = getattr(self, "tag_updates", None)
        if not is_quiet():
            if self.old_revid != self.new_revid:
                to_file.write('Now on revision %d.\n' % self.new_revno)
            if tag_updates:
                to_file.write('%d tag(s) updated.\n' % len(tag_updates))
            if self.old_revid == self.new_revid and not tag_updates:
                if not tag_conflicts:
                    to_file.write('No revisions or tags to pull.\n')
                else:
                    to_file.write('No revisions to pull.\n')
        self._show_tag_conficts(to_file)


class BranchPushResult(_Result):
    """Result of a Branch.push operation.

    :ivar old_revno: Revision number (eg 10) of the target before push.
    :ivar new_revno: Revision number (eg 12) of the target after push.
    :ivar old_revid: Tip revision id (eg joe@foo.com-1234234-aoeua34) of target
        before the push.
    :ivar new_revid: Tip revision id (eg joe@foo.com-5676566-boa234a) of target
        after the push.
    :ivar source_branch: Source branch object that the push was from. This is
        read locked, and generally is a local (and thus low latency) branch.
    :ivar master_branch: If target is a bound branch, the master branch of
        target, or target itself. Always write locked.
    :ivar target_branch: The direct Branch where data is being sent (write
        locked).
    :ivar local_branch: If the target is a bound branch this will be the
        target, otherwise it will be None.
    """

    def report(self, to_file):
        # TODO: This function gets passed a to_file, but then
        # ignores it and calls note() instead. This is also
        # inconsistent with PullResult(), which writes to stdout.
        # -- JRV20110901, bug #838853
        tag_conflicts = getattr(self, "tag_conflicts", None)
        tag_updates = getattr(self, "tag_updates", None)
        if not is_quiet():
            if self.old_revid != self.new_revid:
                note(gettext('Pushed up to revision %d.') % self.new_revno)
            if tag_updates:
                note(ngettext('%d tag updated.', '%d tags updated.', len(tag_updates)) % len(tag_updates))
            if self.old_revid == self.new_revid and not tag_updates:
                if not tag_conflicts:
                    note(gettext('No new revisions or tags to push.'))
                else:
                    note(gettext('No new revisions to push.'))
        self._show_tag_conficts(to_file)


class BranchCheckResult(object):
    """Results of checking branch consistency.

    :see: Branch.check
    """

    def __init__(self, branch):
        self.branch = branch
        self.errors = []

    def report_results(self, verbose):
        """Report the check results via trace.note.

        :param verbose: Requests more detailed display of what was checked,
            if any.
        """
        note(gettext('checked branch {0} format {1}').format(
                                self.branch.user_url, self.branch._format))
        for error in self.errors:
            note(gettext('found error:%s'), error)


class Converter5to6(object):
    """Perform an in-place upgrade of format 5 to format 6"""

    def convert(self, branch):
        # Data for 5 and 6 can peacefully coexist.
        format = BzrBranchFormat6()
        new_branch = format.open(branch.bzrdir, _found=True)

        # Copy source data into target
        new_branch._write_last_revision_info(*branch.last_revision_info())
        new_branch.lock_write()
        try:
            new_branch.set_parent(branch.get_parent())
            new_branch.set_bound_location(branch.get_bound_location())
            new_branch.set_push_location(branch.get_push_location())
        finally:
            new_branch.unlock()

        # New branch has no tags by default
        new_branch.tags._set_tag_dict({})

        # Copying done; now update target format
        new_branch._transport.put_bytes('format',
            format.as_string(),
            mode=new_branch.bzrdir._get_file_mode())

        # Clean up old files
        new_branch._transport.delete('revision-history')
        branch.lock_write()
        try:
            try:
                branch.set_parent(None)
            except errors.NoSuchFile:
                pass
            branch.set_bound_location(None)
        finally:
            branch.unlock()


class Converter6to7(object):
    """Perform an in-place upgrade of format 6 to format 7"""

    def convert(self, branch):
        format = BzrBranchFormat7()
        branch._set_config_location('stacked_on_location', '')
        # update target format
        branch._transport.put_bytes('format', format.as_string())


class Converter7to8(object):
    """Perform an in-place upgrade of format 7 to format 8"""

    def convert(self, branch):
        format = BzrBranchFormat8()
        branch._transport.put_bytes('references', '')
        # update target format
        branch._transport.put_bytes('format', format.as_string())


class InterBranch(InterObject):
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
        
        :return: An iterable of (from_format, to_format) to use when testing
            this InterBranch class. Each InterBranch class should define this
            method itself.
        """
        raise NotImplementedError(klass._get_branch_formats_to_test)

    @needs_write_lock
    def pull(self, overwrite=False, stop_revision=None,
             possible_transports=None, local=False):
        """Mirror source into target branch.

        The target branch is considered to be 'local', having low latency.

        :returns: PullResult instance
        """
        raise NotImplementedError(self.pull)

    @needs_write_lock
    def push(self, overwrite=False, stop_revision=None, lossy=False,
             _override_hook_source_branch=None):
        """Mirror the source branch into the target branch.

        The source branch is considered to be 'local', having low latency.
        """
        raise NotImplementedError(self.push)

    @needs_write_lock
    def copy_content_into(self, revision_id=None):
        """Copy the content of source into target

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        raise NotImplementedError(self.copy_content_into)

    @needs_write_lock
    def fetch(self, stop_revision=None, limit=None):
        """Fetch revisions.

        :param stop_revision: Last revision to fetch
        :param limit: Optional rough limit of revisions to fetch
        """
        raise NotImplementedError(self.fetch)


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

    @needs_write_lock
    def copy_content_into(self, revision_id=None):
        """Copy the content of source into target

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        self.source.update_references(self.target)
        self.source._synchronize_history(self.target, revision_id)
        try:
            parent = self.source.get_parent()
        except errors.InaccessibleParent, e:
            mutter('parent was not accessible to copy: %s', e)
        else:
            if parent:
                self.target.set_parent(parent)
        if self.source._push_should_merge_tags():
            self.source.tags.merge_to(self.target.tags)

    @needs_write_lock
    def fetch(self, stop_revision=None, limit=None):
        if self.target.base == self.source.base:
            return (0, [])
        self.source.lock_read()
        try:
            fetch_spec_factory = fetch.FetchSpecFactory()
            fetch_spec_factory.source_branch = self.source
            fetch_spec_factory.source_branch_stop_revision_id = stop_revision
            fetch_spec_factory.source_repo = self.source.repository
            fetch_spec_factory.target_repo = self.target.repository
            fetch_spec_factory.target_repo_kind = fetch.TargetRepoKinds.PREEXISTING
            fetch_spec_factory.limit = limit
            fetch_spec = fetch_spec_factory.make_fetch_spec()
            return self.target.repository.fetch(self.source.repository,
                fetch_spec=fetch_spec)
        finally:
            self.source.unlock()

    @needs_write_lock
    def _update_revisions(self, stop_revision=None, overwrite=False,
            graph=None):
        other_revno, other_last_revision = self.source.last_revision_info()
        stop_revno = None # unknown
        if stop_revision is None:
            stop_revision = other_last_revision
            if _mod_revision.is_null(stop_revision):
                # if there are no commits, we're done.
                return
            stop_revno = other_revno

        # what's the current last revision, before we fetch [and change it
        # possibly]
        last_rev = _mod_revision.ensure_null(self.target.last_revision())
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
                    stop_revision, last_rev, graph, self.source):
                # stop_revision is a descendant of last_rev, but we aren't
                # overwriting, so we're done.
                return
        if stop_revno is None:
            if graph is None:
                graph = self.target.repository.get_graph()
            this_revno, this_last_revision = \
                    self.target.last_revision_info()
            stop_revno = graph.find_distance_to_null(stop_revision,
                            [(other_last_revision, other_revno),
                             (this_last_revision, this_revno)])
        self.target.set_last_revision_info(stop_revno, stop_revision)

    @needs_write_lock
    def pull(self, overwrite=False, stop_revision=None,
             possible_transports=None, run_hooks=True,
             _override_hook_target=None, local=False):
        """Pull from source into self, updating my master if any.

        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        """
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
                source_is_master = (relpath == '')
            except (errors.PathNotChild, errors.InvalidURL):
                source_is_master = False
        if not local and bound_location and not source_is_master:
            # not pulling from master, so we need to update master.
            master_branch = self.target.get_master_branch(possible_transports)
            master_branch.lock_write()
        try:
            if master_branch:
                # pull from source into master.
                master_branch.pull(self.source, overwrite, stop_revision,
                    run_hooks=False)
            return self._pull(overwrite,
                stop_revision, _hook_master=master_branch,
                run_hooks=run_hooks,
                _override_hook_target=_override_hook_target,
                merge_tags_to_master=not source_is_master)
        finally:
            if master_branch:
                master_branch.unlock()

    def push(self, overwrite=False, stop_revision=None, lossy=False,
             _override_hook_source_branch=None):
        """See InterBranch.push.

        This is the basic concrete implementation of push()

        :param _override_hook_source_branch: If specified, run the hooks
            passing this Branch as the source, rather than self.  This is for
            use of RemoteBranch, where push is delegated to the underlying
            vfs-based Branch.
        """
        if lossy:
            raise errors.LossyPushToSameVCS(self.source, self.target)
        # TODO: Public option to disable running hooks - should be trivial but
        # needs tests.

        op = cleanup.OperationWithCleanups(self._push_with_bound_branches)
        op.add_cleanup(self.source.lock_read().unlock)
        op.add_cleanup(self.target.lock_write().unlock)
        return op.run(overwrite, stop_revision,
            _override_hook_source_branch=_override_hook_source_branch)

    def _basic_push(self, overwrite, stop_revision):
        """Basic implementation of push without bound branches or hooks.

        Must be called with source read locked and target write locked.
        """
        result = BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revno, result.old_revid = self.target.last_revision_info()
        self.source.update_references(self.target)
        overwrite = _fix_overwrite_type(overwrite)
        if result.old_revid != stop_revision:
            # We assume that during 'push' this repository is closer than
            # the target.
            graph = self.source.repository.get_graph(self.target.repository)
            self._update_revisions(stop_revision,
                overwrite=("history" in overwrite),
                graph=graph)
        if self.source._push_should_merge_tags():
            result.tag_updates, result.tag_conflicts = (
                self.source.tags.merge_to(
                self.target.tags, "tags" in overwrite))
        result.new_revno, result.new_revid = self.target.last_revision_info()
        return result

    def _push_with_bound_branches(self, operation, overwrite, stop_revision,
            _override_hook_source_branch=None):
        """Push from source into target, and into target's master if any.
        """
        def _run_hooks():
            if _override_hook_source_branch:
                result.source_branch = _override_hook_source_branch
            for hook in Branch.hooks['post_push']:
                hook(result)

        bound_location = self.target.get_bound_location()
        if bound_location and self.target.base != bound_location:
            # there is a master branch.
            #
            # XXX: Why the second check?  Is it even supported for a branch to
            # be bound to itself? -- mbp 20070507
            master_branch = self.target.get_master_branch()
            master_branch.lock_write()
            operation.add_cleanup(master_branch.unlock)
            # push into the master from the source branch.
            master_inter = InterBranch.get(self.source, master_branch)
            master_inter._basic_push(overwrite, stop_revision)
            # and push into the target branch from the source. Note that
            # we push from the source branch again, because it's considered
            # the highest bandwidth repository.
            result = self._basic_push(overwrite, stop_revision)
            result.master_branch = master_branch
            result.local_branch = self.target
        else:
            master_branch = None
            # no master branch
            result = self._basic_push(overwrite, stop_revision)
            # TODO: Why set master_branch and local_branch if there's no
            # binding?  Maybe cleaner to just leave them unset? -- mbp
            # 20070504
            result.master_branch = self.target
            result.local_branch = None
        _run_hooks()
        return result

    def _pull(self, overwrite=False, stop_revision=None,
             possible_transports=None, _hook_master=None, run_hooks=True,
             _override_hook_target=None, local=False,
             merge_tags_to_master=True):
        """See Branch.pull.

        This function is the core worker, used by GenericInterBranch.pull to
        avoid duplication when pulling source->master and source->local.

        :param _hook_master: Private parameter - set the branch to
            be supplied as the master to pull hooks.
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        :param _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
        :param local: Only update the local branch, and not the bound branch.
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
        self.source.lock_read()
        try:
            # We assume that during 'pull' the target repository is closer than
            # the source one.
            self.source.update_references(self.target)
            graph = self.target.repository.get_graph(self.source.repository)
            # TODO: Branch formats should have a flag that indicates 
            # that revno's are expensive, and pull() should honor that flag.
            # -- JRV20090506
            result.old_revno, result.old_revid = \
                self.target.last_revision_info()
            overwrite = _fix_overwrite_type(overwrite)
            self._update_revisions(stop_revision,
                overwrite=("history" in overwrite),
                graph=graph)
            # TODO: The old revid should be specified when merging tags, 
            # so a tags implementation that versions tags can only 
            # pull in the most recent changes. -- JRV20090506
            result.tag_updates, result.tag_conflicts = (
                self.source.tags.merge_to(self.target.tags,
                    "tags" in overwrite,
                    ignore_master=not merge_tags_to_master))
            result.new_revno, result.new_revid = self.target.last_revision_info()
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = result.target_branch
            else:
                result.master_branch = result.target_branch
                result.local_branch = None
            if run_hooks:
                for hook in Branch.hooks['post_pull']:
                    hook(result)
        finally:
            self.source.unlock()
        return result


InterBranch.register_optimiser(GenericInterBranch)

# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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


import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from itertools import chain
from bzrlib import (
        bzrdir,
        cache_utf8,
        config as _mod_config,
        debug,
        errors,
        lockdir,
        lockable_files,
        repository,
        revision as _mod_revision,
        transport,
        tsort,
        ui,
        urlutils,
        )
from bzrlib.config import BranchConfig
from bzrlib.repofmt.pack_repo import RepositoryFormatPackDevelopment1Subtree
from bzrlib.tag import (
    BasicTags,
    DisabledTags,
    )
""")

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.hooks import Hooks
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )
from bzrlib.trace import mutter, mutter_callsite, note, is_quiet


BZR_BRANCH_FORMAT_4 = "Bazaar-NG branch, format 0.0.4\n"
BZR_BRANCH_FORMAT_5 = "Bazaar-NG branch, format 5\n"
BZR_BRANCH_FORMAT_6 = "Bazaar Branch Format 6 (bzr 0.15)\n"


# TODO: Maybe include checks for common corruption of newlines, etc?

# TODO: Some operations like log might retrieve the same revisions
# repeatedly to calculate deltas.  We could perhaps have a weakref
# cache in memory to make this faster.  In general anything can be
# cached in memory between lock and unlock operations. .. nb thats
# what the transaction identity map provides


######################################################################
# branch objects

class Branch(object):
    """Branch holding a history of revisions.

    base
        Base directory/url of the branch.

    hooks: An instance of BranchHooks.
    """
    # this is really an instance variable - FIXME move it there
    # - RBC 20060112
    base = None

    # override this to set the strategy for storing tags
    def _make_tags(self):
        return DisabledTags(self)

    def __init__(self, *ignored, **ignored_too):
        self.tags = self._make_tags()
        self._revision_history_cache = None
        self._revision_id_to_revno_cache = None
        self._last_revision_info_cache = None
        self._open_hook()

    def _open_hook(self):
        """Called by init to allow simpler extension of the base class."""

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

    @staticmethod
    def open(base, _unsupported=False, possible_transports=None):
        """Open the branch rooted at base.

        For instance, if the branch is at URL/.bzr/branch,
        Branch.open(URL) -> a Branch instance.
        """
        control = bzrdir.BzrDir.open(base, _unsupported,
                                     possible_transports=possible_transports)
        return control.open_branch(_unsupported)

    @staticmethod
    def open_from_transport(transport, _unsupported=False):
        """Open the branch rooted at transport"""
        control = bzrdir.BzrDir.open_from_transport(transport, _unsupported)
        return control.open_branch(_unsupported)

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
        control, relpath = bzrdir.BzrDir.open_containing(url,
                                                         possible_transports)
        return control.open_branch(), relpath

    def get_config(self):
        return BranchConfig(self)

    def _get_nick(self):
        return self.get_config().get_nickname()

    def _set_nick(self, nick):
        self.get_config().set_user_option('nickname', nick, warn_masked=True)

    nick = property(_get_nick, _set_nick)

    def is_locked(self):
        raise NotImplementedError(self.is_locked)

    def lock_write(self):
        raise NotImplementedError(self.lock_write)

    def lock_read(self):
        raise NotImplementedError(self.lock_read)

    def unlock(self):
        raise NotImplementedError(self.unlock)

    def peek_lock_mode(self):
        """Return lock mode for the Branch: 'r', 'w' or None"""
        raise NotImplementedError(self.peek_lock_mode)

    def get_physical_lock_status(self):
        raise NotImplementedError(self.get_physical_lock_status)

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
        last_revision = self.last_revision()
        revision_graph = repository._old_get_graph(self.repository,
            last_revision)
        merge_sorted_revisions = tsort.merge_sort(
            revision_graph,
            last_revision,
            None,
            generate_revno=True)
        revision_id_to_revno = dict((rev_id, revno)
                                    for seq_num, rev_id, depth, revno, end_of_merge
                                     in merge_sorted_revisions)
        return revision_id_to_revno

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

    @deprecated_method(deprecated_in((0, 16, 0)))
    def abspath(self, name):
        """Return absolute filename for something in the branch
        
        XXX: Robert Collins 20051017 what is this used for? why is it a branch
        method and not a tree method.
        """
        raise NotImplementedError(self.abspath)

    def bind(self, other):
        """Bind the local branch the other branch.

        :param other: The branch to bind to
        :type other: Branch
        """
        raise errors.UpgradeRequired(self.base)

    @needs_write_lock
    def fetch(self, from_branch, last_revision=None, pb=None):
        """Copy revisions from from_branch into this branch.

        :param from_branch: Where to copy from.
        :param last_revision: What revision to stop at (None for at the end
                              of the branch.
        :param pb: An optional progress bar to use.

        Returns the copied revision count and the failed revisions in a tuple:
        (copied, failures).
        """
        if self.base == from_branch.base:
            return (0, [])
        if pb is None:
            nested_pb = ui.ui_factory.nested_progress_bar()
            pb = nested_pb
        else:
            nested_pb = None

        from_branch.lock_read()
        try:
            if last_revision is None:
                pb.update('get source history')
                last_revision = from_branch.last_revision()
                last_revision = _mod_revision.ensure_null(last_revision)
            return self.repository.fetch(from_branch.repository,
                                         revision_id=last_revision,
                                         pb=nested_pb)
        finally:
            if nested_pb is not None:
                nested_pb.finished()
            from_branch.unlock()

    def get_bound_location(self):
        """Return the URL of the branch we are bound to.

        Older format branches cannot bind, please be sure to use a metadir
        branch.
        """
        return None
    
    def get_old_bound_location(self):
        """Return the URL of the branch we used to be bound to
        """
        raise errors.UpgradeRequired(self.base)

    def get_commit_builder(self, parents, config=None, timestamp=None, 
                           timezone=None, committer=None, revprops=None, 
                           revision_id=None):
        """Obtain a CommitBuilder for this branch.
        
        :param parents: Revision ids of the parents of the new revision.
        :param config: Optional configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        """

        if config is None:
            config = self.get_config()
        
        return self.repository.get_commit_builder(self, parents, config,
            timestamp, timezone, committer, revprops, revision_id)

    def get_master_branch(self, possible_transports=None):
        """Return the branch we are bound to.
        
        :return: Either a Branch, or None
        """
        return None

    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """
        rh = self.revision_history()
        if not (1 <= revno <= len(rh)):
            raise errors.InvalidRevisionNumber(revno)
        return self.repository.get_revision_delta(rh[revno-1])

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

    def set_revision_history(self, rev_history):
        raise NotImplementedError(self.set_revision_history)

    def set_stacked_on_url(self, url):
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

    def _clear_cached_state(self):
        """Clear any cached data on this branch, e.g. cached revision history.

        This means the next call to revision_history will need to call
        _gen_revision_history.

        This API is semi-public; it only for use by subclasses, all other code
        should consider it to be private.
        """
        self._revision_history_cache = None
        self._revision_id_to_revno_cache = None
        self._last_revision_info_cache = None

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

    @needs_read_lock
    def revision_history(self):
        """Return sequence of revision ids on this branch.
        
        This method will cache the revision history for as long as it is safe to
        do so.
        """
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
        raise errors.UpgradeRequired(self.base)

    def set_append_revisions_only(self, enabled):
        """Older format branches are never restricted to append-only"""
        raise errors.UpgradeRequired(self.base)

    def last_revision(self):
        """Return last revision id, or NULL_REVISION."""
        return self.last_revision_info()[1]

    @needs_read_lock
    def last_revision_info(self):
        """Return information about the last revision.

        :return: A tuple (revno, revision_id).
        """
        if self._last_revision_info_cache is None:
            self._last_revision_info_cache = self._last_revision_info()
        return self._last_revision_info_cache

    def _last_revision_info(self):
        rh = self.revision_history()
        revno = len(rh)
        if revno:
            return (revno, rh[-1])
        else:
            return (0, _mod_revision.NULL_REVISION)

    @deprecated_method(deprecated_in((1, 6, 0)))
    def missing_revisions(self, other, stop_revision=None):
        """Return a list of new revisions that would perfectly fit.
        
        If self and other have not diverged, return a list of the revisions
        present in other, but missing from self.
        """
        self_history = self.revision_history()
        self_len = len(self_history)
        other_history = other.revision_history()
        other_len = len(other_history)
        common_index = min(self_len, other_len) -1
        if common_index >= 0 and \
            self_history[common_index] != other_history[common_index]:
            raise errors.DivergedBranches(self, other)

        if stop_revision is None:
            stop_revision = other_len
        else:
            if stop_revision > other_len:
                raise errors.NoSuchRevision(self, stop_revision)
        return other_history[self_len:stop_revision]

    @needs_write_lock
    def update_revisions(self, other, stop_revision=None, overwrite=False,
                         graph=None):
        """Pull in new perfect-fit revisions.

        :param other: Another Branch to pull from
        :param stop_revision: Updated until the given revision
        :param overwrite: Always set the branch pointer, rather than checking
            to see if it is a proper descendant.
        :param graph: A Graph object that can be used to query history
            information. This can be None.
        :return: None
        """
        other.lock_read()
        try:
            other_revno, other_last_revision = other.last_revision_info()
            stop_revno = None # unknown
            if stop_revision is None:
                stop_revision = other_last_revision
                if _mod_revision.is_null(stop_revision):
                    # if there are no commits, we're done.
                    return
                stop_revno = other_revno

            # what's the current last revision, before we fetch [and change it
            # possibly]
            last_rev = _mod_revision.ensure_null(self.last_revision())
            # we fetch here so that we don't process data twice in the common
            # case of having something to pull, and so that the check for 
            # already merged can operate on the just fetched graph, which will
            # be cached in memory.
            self.fetch(other, stop_revision)
            # Check to see if one is an ancestor of the other
            if not overwrite:
                if graph is None:
                    graph = self.repository.get_graph()
                if self._check_if_descendant_or_diverged(
                        stop_revision, last_rev, graph, other):
                    # stop_revision is a descendant of last_rev, but we aren't
                    # overwriting, so we're done.
                    return
            if stop_revno is None:
                if graph is None:
                    graph = self.repository.get_graph()
                this_revno, this_last_revision = self.last_revision_info()
                stop_revno = graph.find_distance_to_null(stop_revision,
                                [(other_last_revision, other_revno),
                                 (this_last_revision, this_revno)])
            self.set_last_revision_info(stop_revno, stop_revision)
        finally:
            other.unlock()

    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if _mod_revision.is_null(revision_id):
            return 0
        history = self.revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError:
            raise errors.NoSuchRevision(self, revision_id)

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        if revno == 0:
            return _mod_revision.NULL_REVISION
        if history is None:
            history = self.revision_history()
        if revno <= 0 or revno > len(history):
            raise errors.NoSuchRevision(self, revno)
        return history[revno - 1]

    def pull(self, source, overwrite=False, stop_revision=None,
             possible_transports=None, _override_hook_target=None):
        """Mirror source into this branch.

        This branch is considered to be 'local', having low latency.

        :returns: PullResult instance
        """
        raise NotImplementedError(self.pull)

    def push(self, target, overwrite=False, stop_revision=None):
        """Mirror this branch into target.

        This branch is considered to be 'local', having low latency.
        """
        raise NotImplementedError(self.push)

    def basis_tree(self):
        """Return `Tree` object for last revision."""
        return self.repository.revision_tree(self.last_revision())

    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        raise NotImplementedError(self.rename_one)

    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist as a versioned directory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  If it is a directory, 

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        raise NotImplementedError(self.move)

    def get_parent(self):
        """Return the parent location of the branch.

        This is the default location for push/pull/missing.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        raise NotImplementedError(self.get_parent)

    def _set_config_location(self, name, url, config=None,
                             make_relative=False):
        if config is None:
            config = self.get_config()
        if url is None:
            url = ''
        elif make_relative:
            url = urlutils.relative_url(self.base, url)
        config.set_user_option(name, url, warn_masked=True)

    def _get_config_location(self, name, config=None):
        if config is None:
            config = self.get_config()
        location = config.get_user_option(name)
        if location == '':
            location = None
        return location

    def get_submit_branch(self):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        return self.get_config().get_user_option('submit_branch')

    def set_submit_branch(self, location):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        self.get_config().set_user_option('submit_branch', location,
            warn_masked=True)

    def get_public_branch(self):
        """Return the public location of the branch.

        This is is used by merge directives.
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
        """Return the None or the location to push this branch to."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """Set a new push location for this branch."""
        raise NotImplementedError(self.set_push_location)

    def set_parent(self, url):
        raise NotImplementedError(self.set_parent)

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
    def clone(self, to_bzrdir, revision_id=None):
        """Clone this branch into to_bzrdir preserving all semantic values.
        
        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        result = self._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        return  result

    @needs_read_lock
    def sprout(self, to_bzrdir, revision_id=None):
        """Create a new line of development from the branch, into to_bzrdir.
        
        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        result = self._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        result.set_parent(self.bzrdir.root_transport.base)
        return result

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch5, but works for BzrBranch6 as long as the revision
        history is the true lefthand parent history, and all of the revisions
        are in the destination's repository.  If not, set_revision_history
        will fail.

        :param destination: The branch to copy the history into
        :param revision_id: The revision-id to truncate history at.  May
          be None to copy complete history.
        """
        if revision_id == _mod_revision.NULL_REVISION:
            new_history = []
        new_history = self.revision_history()
        if revision_id is not None and new_history != []:
            try:
                new_history = new_history[:new_history.index(revision_id) + 1]
            except ValueError:
                rev = self.repository.get_revision(revision_id)
                new_history = rev.get_history(self.repository)[1:]
        destination.set_revision_history(new_history)

    @needs_read_lock
    def copy_content_into(self, destination, revision_id=None):
        """Copy the content of self into destination.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        self._synchronize_history(destination, revision_id)
        try:
            parent = self.get_parent()
        except errors.InaccessibleParent, e:
            mutter('parent was not accessible to copy: %s', e)
        else:
            if parent:
                destination.set_parent(parent)
        self.tags.merge_to(destination.tags)

    @needs_read_lock
    def check(self):
        """Check consistency of the branch.

        In particular this checks that revisions given in the revision-history
        do actually match up in the revision graph, and that they're all 
        present in the repository.
        
        Callers will typically also want to check the repository.

        :return: A BranchCheckResult.
        """
        mainline_parent_id = None
        last_revno, last_revision_id = self.last_revision_info()
        real_rev_history = list(self.repository.iter_reverse_revision_history(
                                last_revision_id))
        real_rev_history.reverse()
        if len(real_rev_history) != last_revno:
            raise errors.BzrCheckError('revno does not match len(mainline)'
                ' %s != %s' % (last_revno, len(real_rev_history)))
        # TODO: We should probably also check that real_rev_history actually
        #       matches self.revision_history()
        for revision_id in real_rev_history:
            try:
                revision = self.repository.get_revision(revision_id)
            except errors.NoSuchRevision, e:
                raise errors.BzrCheckError("mainline revision {%s} not in repository"
                            % revision_id)
            # In general the first entry on the revision history has no parents.
            # But it's not illegal for it to have parents listed; this can happen
            # in imports from Arch when the parents weren't reachable.
            if mainline_parent_id is not None:
                if mainline_parent_id not in revision.parent_ids:
                    raise errors.BzrCheckError("previous revision {%s} not listed among "
                                        "parents of {%s}"
                                        % (mainline_parent_id, revision_id))
            mainline_parent_id = revision_id
        return BranchCheckResult(self)

    def _get_checkout_format(self):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        if isinstance(self.bzrdir, bzrdir.BzrDirPreSplitOut):
            from bzrlib.repofmt import weaverepo
            format = bzrdir.BzrDirMetaFormat1()
            format.repository_format = weaverepo.RepositoryFormat7()
        else:
            format = self.repository.bzrdir.checkout_metadir()
            format.set_branch_format(self._format)
        return format

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
        if lightweight:
            format = self._get_checkout_format()
            checkout = format.initialize_on_transport(t)
            from_branch = BranchReferenceFormat().initialize(checkout, self)
        else:
            format = self._get_checkout_format()
            checkout_branch = bzrdir.BzrDir.create_branch_convenience(
                to_location, force_new_tree=False, format=format)
            checkout = checkout_branch.bzrdir
            checkout_branch.bind(self)
            # pull up to the specified revision_id to set the initial 
            # branch tip correctly, and seed it with history.
            checkout_branch.pull(self, stop_revision=revision_id)
            from_branch=None
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

    def reference_parent(self, file_id, path):
        """Return the parent branch for a tree-reference file_id
        :param file_id: The file_id of the tree reference
        :param path: The path of the file_id in the tree
        :return: A branch associated with the file_id
        """
        # FIXME should provide multiple branches, based on config
        return Branch.open(self.bzrdir.root_transport.clone(path).base)

    def supports_tags(self):
        return self._format.supports_tags()

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


class BranchFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
    during branch opening. Its not required that these be instances, they
    can be classes themselves with class methods - it simply depends on 
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every time regardless.
    """

    _default_format = None
    """The default format used for new branches."""

    _formats = {}
    """The known formats."""

    def __eq__(self, other):
        return self.__class__ is other.__class__

    def __ne__(self, other):
        return not (self == other)

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the branch object in a_bzrdir."""
        try:
            transport = a_bzrdir.get_branch_transport(None)
            format_string = transport.get("format").read()
            return klass._formats[format_string]
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string, kind='branch')

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_reference(self, a_bzrdir):
        """Get the target reference of the branch in a_bzrdir.

        format probing must have been completed before calling
        this method - it is assumed that the format of the branch
        in a_bzrdir is correct.

        :param a_bzrdir: The bzrdir to get the branch data from.
        :return: None if the branch is not a reference branch.
        """
        return None

    @classmethod
    def set_reference(self, a_bzrdir, to_branch):
        """Set the target reference of the branch in a_bzrdir.

        format probing must have been completed before calling
        this method - it is assumed that the format of the branch
        in a_bzrdir is correct.

        :param a_bzrdir: The bzrdir to set the branch reference for.
        :param to_branch: branch that the checkout is to reference
        """
        raise NotImplementedError(self.set_reference)

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short format description for this format."""
        raise NotImplementedError(self.get_format_description)

    def _initialize_helper(self, a_bzrdir, utf8_files, lock_type='metadir',
                           set_format=True):
        """Initialize a branch in a bzrdir, with specified files

        :param a_bzrdir: The bzrdir to initialize the branch in
        :param utf8_files: The files to create as a list of
            (filename, content) tuples
        :param set_format: If True, set the format with
            self.get_format_string.  (BzrBranch4 has its format set
            elsewhere)
        :return: a branch in this format
        """
        mutter('creating branch %r in %s', self, a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        lock_map = {
            'metadir': ('lock', lockdir.LockDir),
            'branch4': ('branch-lock', lockable_files.TransportLock),
        }
        lock_name, lock_class = lock_map[lock_type]
        control_files = lockable_files.LockableFiles(branch_transport,
            lock_name, lock_class)
        control_files.create_lock()
        control_files.lock_write()
        if set_format:
            utf8_files += [('format', self.get_format_string())]
        try:
            for (filename, content) in utf8_files:
                branch_transport.put_bytes(
                    filename, content,
                    mode=a_bzrdir._get_file_mode())
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True)

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        raise NotImplementedError(self.open)

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def set_default_format(klass, format):
        klass._default_format = format

    def supports_stacking(self):
        """True if this format records a stacked-on branch."""
        return False

    @classmethod
    def unregister_format(klass, format):
        del klass._formats[format.get_format_string()]

    def __str__(self):
        return self.get_format_string().rstrip()

    def supports_tags(self):
        """True if this format supports tags stored in the branch"""
        return False  # by default


class BranchHooks(Hooks):
    """A dictionary mapping hook name to a list of callables for branch hooks.
    
    e.g. ['set_rh'] Is the list of items to be called when the
    set_revision_history function is invoked.
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        Hooks.__init__(self)
        # Introduced in 0.15:
        # invoked whenever the revision history has been set
        # with set_revision_history. The api signature is
        # (branch, revision_history), and the branch will
        # be write-locked.
        self['set_rh'] = []
        # invoked after a push operation completes.
        # the api signature is
        # (push_result)
        # containing the members
        # (source, local, master, old_revno, old_revid, new_revno, new_revid)
        # where local is the local target branch or None, master is the target 
        # master branch, and the rest should be self explanatory. The source
        # is read locked and the target branches write locked. Source will
        # be the local low-latency branch.
        self['post_push'] = []
        # invoked after a pull operation completes.
        # the api signature is
        # (pull_result)
        # containing the members
        # (source, local, master, old_revno, old_revid, new_revno, new_revid)
        # where local is the local branch or None, master is the target 
        # master branch, and the rest should be self explanatory. The source
        # is read locked and the target branches write locked. The local
        # branch is the low-latency branch.
        self['post_pull'] = []
        # invoked before a commit operation takes place.
        # the api signature is
        # (local, master, old_revno, old_revid, future_revno, future_revid,
        #  tree_delta, future_tree).
        # old_revid is NULL_REVISION for the first commit to a branch
        # tree_delta is a TreeDelta object describing changes from the basis
        # revision, hooks MUST NOT modify this delta
        # future_tree is an in-memory tree obtained from
        # CommitBuilder.revision_tree() and hooks MUST NOT modify this tree
        self['pre_commit'] = []
        # invoked after a commit operation completes.
        # the api signature is 
        # (local, master, old_revno, old_revid, new_revno, new_revid)
        # old_revid is NULL_REVISION for the first commit to a branch.
        self['post_commit'] = []
        # invoked after a uncommit operation completes.
        # the api signature is
        # (local, master, old_revno, old_revid, new_revno, new_revid) where
        # local is the local branch or None, master is the target branch,
        # and an empty branch recieves new_revno of 0, new_revid of None.
        self['post_uncommit'] = []
        # Introduced in 1.6
        # Invoked before the tip of a branch changes.
        # the api signature is
        # (params) where params is a ChangeBranchTipParams with the members
        # (branch, old_revno, new_revno, old_revid, new_revid)
        self['pre_change_branch_tip'] = []
        # Introduced in 1.4
        # Invoked after the tip of a branch changes.
        # the api signature is
        # (params) where params is a ChangeBranchTipParams with the members
        # (branch, old_revno, new_revno, old_revid, new_revid)
        self['post_change_branch_tip'] = []


# install the default hooks into the Branch class.
Branch.hooks = BranchHooks()


class ChangeBranchTipParams(object):
    """Object holding parameters passed to *_change_branch_tip hooks.

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


class BzrBranchFormat4(BranchFormat):
    """Bzr branch format 4.

    This format has:
     - a revision-history file.
     - a branch-lock lock file [ to be shared with the bzrdir ]
    """

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 4"

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files,
                                       lock_type='branch4', set_format=False)

    def __init__(self):
        super(BzrBranchFormat4, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        return BzrBranch(_format=self,
                         _control_files=a_bzrdir._control_files,
                         a_bzrdir=a_bzrdir,
                         _repository=a_bzrdir.open_repository())

    def __str__(self):
        return "Bazaar-NG branch format 4"


class BranchFormatMetadir(BranchFormat):
    """Common logic for meta-dir based branch formats."""

    def _branch_class(self):
        """What class to instantiate on open calls."""
        raise NotImplementedError(self._branch_class)

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir.

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            format = BranchFormat.find_format(a_bzrdir)
            if format.__class__ != self.__class__:
                raise AssertionError("wrong format %r found for %r" %
                    (format, self))
        try:
            transport = a_bzrdir.get_branch_transport(None)
            control_files = lockable_files.LockableFiles(transport, 'lock',
                                                         lockdir.LockDir)
            return self._branch_class()(_format=self,
                              _control_files=control_files,
                              a_bzrdir=a_bzrdir,
                              _repository=a_bzrdir.find_repository())
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)

    def __init__(self):
        super(BranchFormatMetadir, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def supports_tags(self):
        return True


class BzrBranchFormat5(BranchFormatMetadir):
    """Bzr branch format 5.

    This format has:
     - a revision-history file.
     - a format string
     - a lock dir guarding the branch itself
     - all of this stored in a branch/ subdirectory
     - works with shared repositories.

    This format is new in bzr 0.8.
    """

    def _branch_class(self):
        return BzrBranch5

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar-NG branch format 5\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 5"
        
    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files)

    def supports_tags(self):
        return False


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

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar Branch Format 6 (bzr 0.15)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 6"

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('last-revision', '0 null:\n'),
                      ('branch.conf', ''),
                      ('tags', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files)


class BzrBranchFormat7(BranchFormatMetadir):
    """Branch format with last-revision, tags, and a stacked location pointer.

    The stacked location pointer is passed down to the repository and requires
    a repository format with supports_external_lookups = True.

    This format was introduced in bzr 1.6.
    """

    def _branch_class(self):
        return BzrBranch7

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar Branch Format 7 (needs bzr 1.6)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 7"

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('last-revision', '0 null:\n'),
                      ('branch.conf', ''),
                      ('tags', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files)

    def __init__(self):
        super(BzrBranchFormat7, self).__init__()
        self._matchingbzrdir.repository_format = \
            RepositoryFormatPackDevelopment1Subtree()

    def supports_stacking(self):
        return True


class BranchReferenceFormat(BranchFormat):
    """Bzr branch reference format.

    Branch references are used in implementing checkouts, they
    act as an alias to the real branch which is at some other url.

    This format has:
     - A location file
     - a format string
    """

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar-NG Branch Reference Format 1\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Checkout reference format 1"

    def get_reference(self, a_bzrdir):
        """See BranchFormat.get_reference()."""
        transport = a_bzrdir.get_branch_transport(None)
        return transport.get('location').read()

    def set_reference(self, a_bzrdir, to_branch):
        """See BranchFormat.set_reference()."""
        transport = a_bzrdir.get_branch_transport(None)
        location = transport.put_bytes('location', to_branch.base)

    def initialize(self, a_bzrdir, target_branch=None):
        """Create a branch of this format in a_bzrdir."""
        if target_branch is None:
            # this format does not implement branch itself, thus the implicit
            # creation contract must see it as uninitializable
            raise errors.UninitializableFormat(self)
        mutter('creating branch reference in %s', a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        branch_transport.put_bytes('location',
            target_branch.bzrdir.root_transport.base)
        branch_transport.put_bytes('format', self.get_format_string())
        return self.open(
            a_bzrdir, _found=True,
            possible_transports=[target_branch.bzrdir.root_transport])

    def __init__(self):
        super(BranchReferenceFormat, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def _make_reference_clone_function(format, a_branch):
        """Create a clone() routine for a branch dynamically."""
        def clone(to_bzrdir, revision_id=None):
            """See Branch.clone()."""
            return format.initialize(to_bzrdir, a_branch)
            # cannot obey revision_id limits when cloning a reference ...
            # FIXME RBC 20060210 either nuke revision_id for clone, or
            # emit some sort of warning/error to the caller ?!
        return clone

    def open(self, a_bzrdir, _found=False, location=None,
             possible_transports=None):
        """Return the branch that the branch reference in a_bzrdir points at.

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            format = BranchFormat.find_format(a_bzrdir)
            if format.__class__ != self.__class__:
                raise AssertionError("wrong format %r found for %r" %
                    (format, self))
        if location is None:
            location = self.get_reference(a_bzrdir)
        real_bzrdir = bzrdir.BzrDir.open(
            location, possible_transports=possible_transports)
        result = real_bzrdir.open_branch()
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


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
__format5 = BzrBranchFormat5()
__format6 = BzrBranchFormat6()
__format7 = BzrBranchFormat7()
BranchFormat.register_format(__format5)
BranchFormat.register_format(BranchReferenceFormat())
BranchFormat.register_format(__format6)
BranchFormat.register_format(__format7)
BranchFormat.set_default_format(__format6)
_legacy_formats = [BzrBranchFormat4(),
                   ]

class BzrBranch(Branch):
    """A branch stored in the actual filesystem.

    Note that it's "local" in the context of the filesystem; it doesn't
    really matter if it's on an nfs/smb/afs/coda/... share, as long as
    it's writable, and can be accessed via the normal filesystem API.

    :ivar _transport: Transport for file operations on this branch's 
        control files, typically pointing to the .bzr/branch directory.
    :ivar repository: Repository for this branch.
    :ivar base: The url of the base directory for this branch; the one 
        containing the .bzr directory.
    """
    
    def __init__(self, _format=None,
                 _control_files=None, a_bzrdir=None, _repository=None):
        """Create new branch object at a particular location."""
        if a_bzrdir is None:
            raise ValueError('a_bzrdir must be supplied')
        else:
            self.bzrdir = a_bzrdir
        self._base = self.bzrdir.transport.clone('..').base
        # XXX: We should be able to just do
        #   self.base = self.bzrdir.root_transport.base
        # but this does not quite work yet -- mbp 20080522
        self._format = _format
        if _control_files is None:
            raise ValueError('BzrBranch _control_files is None')
        self.control_files = _control_files
        self._transport = _control_files._transport
        self.repository = _repository
        Branch.__init__(self)

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

    __repr__ = __str__

    def _get_base(self):
        """Returns the directory containing the control directory."""
        return self._base

    base = property(_get_base, doc="The URL for the root of this branch.")

    @deprecated_method(deprecated_in((0, 16, 0)))
    def abspath(self, name):
        """See Branch.abspath."""
        return self._transport.abspath(name)

    def is_locked(self):
        return self.control_files.is_locked()

    def lock_write(self, token=None):
        repo_token = self.repository.lock_write()
        try:
            token = self.control_files.lock_write(token=token)
        except:
            self.repository.unlock()
            raise
        return token

    def lock_read(self):
        self.repository.lock_read()
        try:
            self.control_files.lock_read()
        except:
            self.repository.unlock()
            raise

    def unlock(self):
        # TODO: test for failed two phase locks. This is known broken.
        try:
            self.control_files.unlock()
        finally:
            self.repository.unlock()
        if not self.control_files.is_locked():
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

    def _write_revision_history(self, history):
        """Factored out of set_revision_history.

        This performs the actual writing to disk.
        It is intended to be called by BzrBranch5.set_revision_history."""
        self._transport.put_bytes(
            'revision-history', '\n'.join(history),
            mode=self.bzrdir._get_file_mode())

    @needs_write_lock
    def set_revision_history(self, rev_history):
        """See Branch.set_revision_history."""
        if 'evil' in debug.debug_flags:
            mutter_callsite(3, "set_revision_history scales with history.")
        check_not_reserved_id = _mod_revision.check_not_reserved_id
        for rev_id in rev_history:
            check_not_reserved_id(rev_id)
        if Branch.hooks['post_change_branch_tip']:
            # Don't calculate the last_revision_info() if there are no hooks
            # that will use it.
            old_revno, old_revid = self.last_revision_info()
        if len(rev_history) == 0:
            revid = _mod_revision.NULL_REVISION
        else:
            revid = rev_history[-1]
        self._run_pre_change_branch_tip_hooks(len(rev_history), revid)
        self._write_revision_history(rev_history)
        self._clear_cached_state()
        self._cache_revision_history(rev_history)
        for hook in Branch.hooks['set_rh']:
            hook(self, rev_history)
        if Branch.hooks['post_change_branch_tip']:
            self._run_post_change_branch_tip_hooks(old_revno, old_revid)

    def _run_pre_change_branch_tip_hooks(self, new_revno, new_revid):
        """Run the pre_change_branch_tip hooks."""
        hooks = Branch.hooks['pre_change_branch_tip']
        if not hooks:
            return
        old_revno, old_revid = self.last_revision_info()
        params = ChangeBranchTipParams(
            self, old_revno, new_revno, old_revid, new_revid)
        for hook in hooks:
            try:
                hook(params)
            except errors.TipChangeRejected:
                raise
            except Exception:
                exc_info = sys.exc_info()
                hook_name = Branch.hooks.get_hook_name(hook)
                raise errors.HookFailed(
                    'pre_change_branch_tip', hook_name, exc_info)
 
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
        revision_id = _mod_revision.ensure_null(revision_id)
        # this old format stores the full history, but this api doesn't
        # provide it, so we must generate, and might as well check it's
        # correct
        history = self._lefthand_history(revision_id)
        if len(history) != revno:
            raise AssertionError('%d != %d' % (len(history), revno))
        self.set_revision_history(history)

    def _gen_revision_history(self):
        history = self._transport.get_bytes('revision-history').split('\n')
        if history[-1:] == ['']:
            # There shouldn't be a trailing newline, but just in case.
            history.pop()
        return history

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

    @needs_write_lock
    def generate_revision_history(self, revision_id, last_rev=None,
        other_branch=None):
        """Create a new revision history that will finish with revision_id.

        :param revision_id: the new tip to use.
        :param last_rev: The previous last_revision. If not None, then this
            must be a ancestory of revision_id, or DivergedBranches is raised.
        :param other_branch: The other branch that DivergedBranches should
            raise with respect to.
        """
        self.set_revision_history(self._lefthand_history(revision_id,
            last_rev, other_branch))

    def basis_tree(self):
        """See Branch.basis_tree."""
        return self.repository.revision_tree(self.last_revision())

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
             _hook_master=None, run_hooks=True, possible_transports=None,
             _override_hook_target=None):
        """See Branch.pull.

        :param _hook_master: Private parameter - set the branch to 
            be supplied as the master to pull hooks.
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        :param _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
        """
        result = PullResult()
        result.source_branch = source
        if _override_hook_target is None:
            result.target_branch = self
        else:
            result.target_branch = _override_hook_target
        source.lock_read()
        try:
            # We assume that during 'pull' the local repository is closer than
            # the remote one.
            graph = self.repository.get_graph(source.repository)
            result.old_revno, result.old_revid = self.last_revision_info()
            self.update_revisions(source, stop_revision, overwrite=overwrite,
                                  graph=graph)
            result.tag_conflicts = source.tags.merge_to(self.tags, overwrite)
            result.new_revno, result.new_revid = self.last_revision_info()
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
            source.unlock()
        return result

    def _get_parent_location(self):
        _locs = ['parent', 'pull', 'x-pull']
        for l in _locs:
            try:
                return self._transport.get_bytes(l).strip('\n')
            except errors.NoSuchFile:
                pass
        return None

    @needs_read_lock
    def push(self, target, overwrite=False, stop_revision=None,
             _override_hook_source_branch=None):
        """See Branch.push.

        This is the basic concrete implementation of push()

        :param _override_hook_source_branch: If specified, run
        the hooks passing this Branch as the source, rather than self.  
        This is for use of RemoteBranch, where push is delegated to the
        underlying vfs-based Branch. 
        """
        # TODO: Public option to disable running hooks - should be trivial but
        # needs tests.
        target.lock_write()
        try:
            result = self._push_with_bound_branches(target, overwrite,
                    stop_revision,
                    _override_hook_source_branch=_override_hook_source_branch)
            return result
        finally:
            target.unlock()

    def _push_with_bound_branches(self, target, overwrite,
            stop_revision,
            _override_hook_source_branch=None):
        """Push from self into target, and into target's master if any.
        
        This is on the base BzrBranch class even though it doesn't support 
        bound branches because the *target* might be bound.
        """
        def _run_hooks():
            if _override_hook_source_branch:
                result.source_branch = _override_hook_source_branch
            for hook in Branch.hooks['post_push']:
                hook(result)

        bound_location = target.get_bound_location()
        if bound_location and target.base != bound_location:
            # there is a master branch.
            #
            # XXX: Why the second check?  Is it even supported for a branch to
            # be bound to itself? -- mbp 20070507
            master_branch = target.get_master_branch()
            master_branch.lock_write()
            try:
                # push into the master from this branch.
                self._basic_push(master_branch, overwrite, stop_revision)
                # and push into the target branch from this. Note that we push from
                # this branch again, because its considered the highest bandwidth
                # repository.
                result = self._basic_push(target, overwrite, stop_revision)
                result.master_branch = master_branch
                result.local_branch = target
                _run_hooks()
                return result
            finally:
                master_branch.unlock()
        else:
            # no master branch
            result = self._basic_push(target, overwrite, stop_revision)
            # TODO: Why set master_branch and local_branch if there's no
            # binding?  Maybe cleaner to just leave them unset? -- mbp
            # 20070504
            result.master_branch = target
            result.local_branch = None
            _run_hooks()
            return result

    def _basic_push(self, target, overwrite, stop_revision):
        """Basic implementation of push without bound branches or hooks.

        Must be called with self read locked and target write locked.
        """
        result = PushResult()
        result.source_branch = self
        result.target_branch = target
        result.old_revno, result.old_revid = target.last_revision_info()

        # We assume that during 'push' this repository is closer than
        # the target.
        graph = self.repository.get_graph(target.repository)
        target.update_revisions(self, stop_revision, overwrite=overwrite,
                                graph=graph)
        result.tag_conflicts = self.tags.merge_to(target.tags, overwrite)
        result.new_revno, result.new_revid = target.last_revision_info()
        return result

    def get_parent(self):
        """See Branch.get_parent."""
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
            raise errors.InaccessibleParent(parent, self.base)

    def get_stacked_on_url(self):
        raise errors.UnstackableBranchFormat(self._format, self.base)

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option(
            'push_location', location,
            store=_mod_config.STORE_LOCATION_NORECURSE)

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

    def _set_parent_location(self, url):
        if url is None:
            self._transport.delete('parent')
        else:
            self._transport.put_bytes('parent', url + '\n',
                mode=self.bzrdir._get_file_mode())

    def set_stacked_on_url(self, url):
        raise errors.UnstackableBranchFormat(self._format, self.base)


class BzrBranch5(BzrBranch):
    """A format 5 branch. This supports new features over plain branches.

    It has support for a master_branch which is the data for bound branches.
    """

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
             run_hooks=True, possible_transports=None,
             _override_hook_target=None):
        """Pull from source into self, updating my master if any.
        
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        """
        bound_location = self.get_bound_location()
        master_branch = None
        if bound_location and source.base != bound_location:
            # not pulling from master, so we need to update master.
            master_branch = self.get_master_branch(possible_transports)
            master_branch.lock_write()
        try:
            if master_branch:
                # pull from source into master.
                master_branch.pull(source, overwrite, stop_revision,
                    run_hooks=False)
            return super(BzrBranch5, self).pull(source, overwrite,
                stop_revision, _hook_master=master_branch,
                run_hooks=run_hooks,
                _override_hook_target=_override_hook_target)
        finally:
            if master_branch:
                master_branch.unlock()

    def get_bound_location(self):
        try:
            return self._transport.get_bytes('bound')[:-1]
        except errors.NoSuchFile:
            return None

    @needs_read_lock
    def get_master_branch(self, possible_transports=None):
        """Return the branch we are bound to.
        
        :return: Either a Branch, or None

        This could memoise the branch, but if thats done
        it must be revalidated on each new lock.
        So for now we just don't memoise it.
        # RBC 20060304 review this decision.
        """
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

    @needs_write_lock
    def unbind(self):
        """If bound, unbind"""
        return self.set_bound_location(None)

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


class BzrBranch7(BzrBranch5):
    """A branch with support for a fallback repository."""

    def _get_fallback_repository(self, url):
        """Get the repository we fallback to at url."""
        url = urlutils.join(self.base, url)
        return bzrdir.BzrDir.open(url).open_branch().repository

    def _activate_fallback_location(self, url):
        """Activate the branch/repository from url as a fallback repository."""
        self.repository.add_fallback_repository(
            self._get_fallback_repository(url))

    def _open_hook(self):
        try:
            url = self.get_stacked_on_url()
        except (errors.UnstackableRepositoryFormat, errors.NotStacked,
            errors.UnstackableBranchFormat):
            pass
        else:
            self._activate_fallback_location(url)

    def _check_stackable_repo(self):
        if not self.repository._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(self.repository._format,
                self.repository.base)

    def __init__(self, *args, **kwargs):
        super(BzrBranch7, self).__init__(*args, **kwargs)
        self._last_revision_info_cache = None
        self._partial_revision_history_cache = []

    def _clear_cached_state(self):
        super(BzrBranch7, self)._clear_cached_state()
        self._last_revision_info_cache = None
        self._partial_revision_history_cache = []

    def _last_revision_info(self):
        revision_string = self._transport.get_bytes('last-revision')
        revno, revision_id = revision_string.rstrip('\n').split(' ', 1)
        revision_id = cache_utf8.get_cached_utf8(revision_id)
        revno = int(revno)
        return revno, revision_id

    def _write_last_revision_info(self, revno, revision_id):
        """Simply write out the revision id, with no checks.

        Use set_last_revision_info to perform this safely.

        Does not update the revision_history cache.
        Intended to be called by set_last_revision_info and
        _write_revision_history.
        """
        revision_id = _mod_revision.ensure_null(revision_id)
        out_string = '%d %s\n' % (revno, revision_id)
        self._transport.put_bytes('last-revision', out_string,
            mode=self.bzrdir._get_file_mode())

    @needs_write_lock
    def set_last_revision_info(self, revno, revision_id):
        revision_id = _mod_revision.ensure_null(revision_id)
        old_revno, old_revid = self.last_revision_info()
        if self._get_append_revisions_only():
            self._check_history_violation(revision_id)
        self._run_pre_change_branch_tip_hooks(revno, revision_id)
        self._write_last_revision_info(revno, revision_id)
        self._clear_cached_state()
        self._last_revision_info_cache = revno, revision_id
        self._run_post_change_branch_tip_hooks(old_revno, old_revid)

    def _check_history_violation(self, revision_id):
        last_revision = _mod_revision.ensure_null(self.last_revision())
        if _mod_revision.is_null(last_revision):
            return
        if last_revision not in self._lefthand_history(revision_id):
            raise errors.AppendRevisionsOnlyViolation(self.base)

    def _gen_revision_history(self):
        """Generate the revision history from last revision
        """
        last_revno, last_revision = self.last_revision_info()
        self._extend_partial_history(stop_index=last_revno-1)
        return list(reversed(self._partial_revision_history_cache))

    def _extend_partial_history(self, stop_index=None, stop_revision=None):
        """Extend the partial history to include a given index

        If a stop_index is supplied, stop when that index has been reached.
        If a stop_revision is supplied, stop when that revision is
        encountered.  Otherwise, stop when the beginning of history is
        reached.

        :param stop_index: The index which should be present.  When it is
            present, history extension will stop.
        :param revision_id: The revision id which should be present.  When
            it is encountered, history extension will stop.
        """
        repo = self.repository
        if len(self._partial_revision_history_cache) == 0:
            iterator = repo.iter_reverse_revision_history(self.last_revision())
        else:
            start_revision = self._partial_revision_history_cache[-1]
            iterator = repo.iter_reverse_revision_history(start_revision)
            #skip the last revision in the list
            next_revision = iterator.next()
        for revision_id in iterator:
            self._partial_revision_history_cache.append(revision_id)
            if (stop_index is not None and
                len(self._partial_revision_history_cache) > stop_index):
                break
            if revision_id == stop_revision:
                break

    def _write_revision_history(self, history):
        """Factored out of set_revision_history.

        This performs the actual writing to disk, with format-specific checks.
        It is intended to be called by BzrBranch5.set_revision_history.
        """
        if len(history) == 0:
            last_revision = 'null:'
        else:
            if history != self._lefthand_history(history[-1]):
                raise errors.NotLefthandHistory(history)
            last_revision = history[-1]
        if self._get_append_revisions_only():
            self._check_history_violation(last_revision)
        self._write_last_revision_info(len(history), last_revision)

    @needs_write_lock
    def _set_parent_location(self, url):
        """Set the parent branch"""
        self._set_config_location('parent_location', url, make_relative=True)

    @needs_read_lock
    def _get_parent_location(self):
        """Set the parent branch"""
        return self._get_config_location('parent_location')

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self._set_config_location('push_location', location)

    def set_bound_location(self, location):
        """See Branch.set_push_location."""
        result = None
        config = self.get_config()
        if location is None:
            if config.get_user_option('bound') != 'True':
                return False
            else:
                config.set_user_option('bound', 'False', warn_masked=True)
                return True
        else:
            self._set_config_location('bound_location', location,
                                      config=config)
            config.set_user_option('bound', 'True', warn_masked=True)
        return True

    def _get_bound_location(self, bound):
        """Return the bound location in the config file.

        Return None if the bound parameter does not match"""
        config = self.get_config()
        config_bound = (config.get_user_option('bound') == 'True')
        if config_bound != bound:
            return None
        return self._get_config_location('bound_location', config=config)

    def get_bound_location(self):
        """See Branch.set_push_location."""
        return self._get_bound_location(True)

    def get_old_bound_location(self):
        """See Branch.get_old_bound_location"""
        return self._get_bound_location(False)

    def get_stacked_on_url(self):
        self._check_stackable_repo()
        stacked_url = self._get_config_location('stacked_on_location')
        if stacked_url is None:
            raise errors.NotStacked(self)
        return stacked_url

    def set_append_revisions_only(self, enabled):
        if enabled:
            value = 'True'
        else:
            value = 'False'
        self.get_config().set_user_option('append_revisions_only', value,
            warn_masked=True)

    def set_stacked_on_url(self, url):
        self._check_stackable_repo()
        if not url:
            try:
                old_url = self.get_stacked_on_url()
            except (errors.NotStacked, errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat):
                return
            url = ''
            # repositories don't offer an interface to remove fallback
            # repositories today; take the conceptually simpler option and just
            # reopen it.
            self.repository = self.bzrdir.find_repository()
            # for every revision reference the branch has, ensure it is pulled
            # in.
            source_repository = self._get_fallback_repository(old_url)
            for revision_id in chain([self.last_revision()],
                self.tags.get_reverse_tag_dict()):
                self.repository.fetch(source_repository, revision_id,
                    find_ghosts=True)
        else:
            self._activate_fallback_location(url)
        # write this out after the repository is stacked to avoid setting a
        # stacked config that doesn't work.
        self._set_config_location('stacked_on_location', url)

    def _get_append_revisions_only(self):
        value = self.get_config().get_user_option('append_revisions_only')
        return value == 'True'

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
        elif source_revision_id == revision_id:
            # we know the revno without needing to walk all of history
            revno = source_revno
        else:
            # To figure out the revno for a random revision, we need to build
            # the revision history, and count its length.
            # We don't care about the order, just how long it is.
            # Alternatively, we could start at the current location, and count
            # backwards. But there is no guarantee that we will find it since
            # it may be a merged revision.
            revno = len(list(self.repository.iter_reverse_revision_history(
                                                                revision_id)))
        destination.set_last_revision_info(revno, revision_id)

    def _make_tags(self):
        return BasicTags(self)

    @needs_write_lock
    def generate_revision_history(self, revision_id, last_rev=None,
                                  other_branch=None):
        """See BzrBranch5.generate_revision_history"""
        history = self._lefthand_history(revision_id, last_rev, other_branch)
        revno = len(history)
        self.set_last_revision_info(revno, revision_id)

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
            self._extend_partial_history(stop_revision=revision_id)
            index = len(self._partial_revision_history_cache) - 1
            if self._partial_revision_history_cache[index] != revision_id:
                raise errors.NoSuchRevision(self, revision_id)
        return self.revno() - index


class BzrBranch6(BzrBranch7):
    """See BzrBranchFormat6 for the capabilities of this branch.

    This subclass of BzrBranch7 disables the new features BzrBranch7 added,
    i.e. stacking.
    """

    def get_stacked_on_url(self):
        raise errors.UnstackableBranchFormat(self._format, self.base)

    def set_stacked_on_url(self, url):
        raise errors.UnstackableBranchFormat(self._format, self.base)


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
    :ivar source_branch: Source (local) branch object.
    :ivar master_branch: Master branch of the target, or the target if no
        Master
    :ivar local_branch: target branch if there is a Master, else None
    :ivar target_branch: Target/destination branch object.
    :ivar tag_conflicts: A list of tag conflicts, see BasicTags.merge_to
    """

    def __int__(self):
        # DEPRECATED: pull used to return the change in revno
        return self.new_revno - self.old_revno

    def report(self, to_file):
        if not is_quiet():
            if self.old_revid == self.new_revid:
                to_file.write('No revisions to pull.\n')
            else:
                to_file.write('Now on revision %d.\n' % self.new_revno)
        self._show_tag_conficts(to_file)


class PushResult(_Result):
    """Result of a Branch.push operation.

    :ivar old_revno: Revision number before push.
    :ivar new_revno: Revision number after push.
    :ivar old_revid: Tip revision id before push.
    :ivar new_revid: Tip revision id after push.
    :ivar source_branch: Source branch object.
    :ivar master_branch: Master branch of the target, or None.
    :ivar target_branch: Target/destination branch object.
    """

    def __int__(self):
        # DEPRECATED: push used to return the change in revno
        return self.new_revno - self.old_revno

    def report(self, to_file):
        """Write a human-readable description of the result."""
        if self.old_revid == self.new_revid:
            to_file.write('No new revisions to push.\n')
        else:
            to_file.write('Pushed up to revision %d.\n' % self.new_revno)
        self._show_tag_conficts(to_file)


class BranchCheckResult(object):
    """Results of checking branch consistency.

    :see: Branch.check
    """

    def __init__(self, branch):
        self.branch = branch

    def report_results(self, verbose):
        """Report the check results via trace.note.
        
        :param verbose: Requests more detailed display of what was checked,
            if any.
        """
        note('checked branch %s format %s',
             self.branch.base,
             self.branch._format)


class Converter5to6(object):
    """Perform an in-place upgrade of format 5 to format 6"""

    def convert(self, branch):
        # Data for 5 and 6 can peacefully coexist.
        format = BzrBranchFormat6()
        new_branch = format.open(branch.bzrdir, _found=True)

        # Copy source data into target
        new_branch._write_last_revision_info(*branch.last_revision_info())
        new_branch.set_parent(branch.get_parent())
        new_branch.set_bound_location(branch.get_bound_location())
        new_branch.set_push_location(branch.get_push_location())

        # New branch has no tags by default
        new_branch.tags._set_tag_dict({})

        # Copying done; now update target format
        new_branch._transport.put_bytes('format',
            format.get_format_string(),
            mode=new_branch.bzrdir._get_file_mode())

        # Clean up old files
        new_branch._transport.delete('revision-history')
        try:
            branch.set_parent(None)
        except errors.NoSuchFile:
            pass
        branch.set_bound_location(None)


class Converter6to7(object):
    """Perform an in-place upgrade of format 6 to format 7"""

    def convert(self, branch):
        format = BzrBranchFormat7()
        branch._set_config_location('stacked_on_location', '')
        # update target format
        branch._transport.put_bytes('format', format.get_format_string())

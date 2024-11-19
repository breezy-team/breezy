# Copyright (C) 2005-2011 Canonical Ltd
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

from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
import time

from breezy import (
    config,
    )
from breezy.i18n import gettext
""",
)

import contextlib

from . import controldir, debug, errors, graph, osutils, registry, ui
from . import revision as _mod_revision
from .decorators import only_raises
from .inter import InterObject
from .lock import LogicalLockResult, _RelockDebugMixin
from .trace import log_exception_quietly, mutter, mutter_callsite, note, warning

if TYPE_CHECKING:
    from .revisiontree import RevisionTree

# Old formats display a warning, but only once
_deprecation_warning_done = False


class IsInWriteGroupError(errors.InternalBzrError):
    _fmt = "May not refresh_data of repo %(repo)s while in a write group."

    def __init__(self, repo):
        errors.InternalBzrError.__init__(self, repo=repo)


class CannotSetRevisionId(errors.BzrError):
    _fmt = "Repository format does not support setting revision ids."


class FetchResult:
    """Result of a fetch operation.

    Attributes:
      revidmap: For lossy fetches, map from source revid to target revid.
      total_fetched: Number of revisions fetched
    """

    def __init__(self, total_fetched=None, revidmap=None):
        self.total_fetched = total_fetched
        self.revidmap = revidmap


class CommitBuilder:
    """Provides an interface to build up a commit.

    This allows describing a tree to be committed without needing to
    know the internals of the format of the repository.
    """

    # all clients should supply tree roots.
    record_root_entry = True
    # whether this commit builder will automatically update the branch that is
    # being committed to
    updates_branch = False

    def __init__(
        self,
        repository,
        parents,
        config_stack,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Initiate a CommitBuilder.

        Args:
          repository: Repository to commit to.
          parents: Revision ids of the parents of the new revision.
          timestamp: Optional timestamp recorded for commit.
          timezone: Optional timezone for timestamp.
          committer: Optional committer to set for commit.
          revprops: Optional dictionary of revision properties.
          revision_id: Optional revision id.
          lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        self._config_stack = config_stack
        self._lossy = lossy

        if committer is None:
            self._committer = self._config_stack.get("email")
        elif not isinstance(committer, str):
            self._committer = committer.decode()  # throw if non-ascii
        else:
            self._committer = committer

        self.parents = parents
        self.repository = repository

        self._revprops = {}
        if revprops is not None:
            self._validate_revprops(revprops)
            self._revprops.update(revprops)

        if timestamp is None:
            timestamp = time.time()
        # Restrict resolution to 1ms
        self._timestamp = round(timestamp, 3)

        if timezone is None:
            self._timezone = osutils.local_time_offset()
        else:
            self._timezone = int(timezone)

        self._generate_revision_if_needed(revision_id)

    def any_changes(self):
        """Return True if any entries were changed.

        This includes merge-only changes. It is the core for the --unchanged
        detection in commit.

        Returns: True if any changes have occured.
        """
        raise NotImplementedError(self.any_changes)

    def _validate_unicode_text(self, text, context):
        """Verify things like commit messages don't have bogus characters."""
        # TODO(jelmer): Make this repository-format specific
        if "\r" in text:
            raise ValueError(f"Invalid value for {context}: {text!r}")

    def _validate_revprops(self, revprops):
        for key, value in revprops.items():
            # We know that the XML serializers do not round trip '\r'
            # correctly, so refuse to accept them
            if not isinstance(value, str):
                raise ValueError(
                    f"revision property ({key}) is not a valid"
                    f" (unicode) string: {value!r}"
                )
            # TODO(jelmer): Make this repository-format specific
            self._validate_unicode_text(value, f"revision property ({key})")

    def commit(self, message):
        """Make the actual commit.

        Returns: The revision id of the recorded revision.
        """
        raise NotImplementedError(self.commit)

    def abort(self):
        """Abort the commit that is being built."""
        raise NotImplementedError(self.abort)

    def revision_tree(self) -> "RevisionTree":
        """Return the tree that was just committed.

        After calling commit() this can be called to get a
        RevisionTree representing the newly committed tree. This is
        preferred to calling Repository.revision_tree() because that may
        require deserializing the inventory, while we already have a copy in
        memory.
        """
        raise NotImplementedError(self.revision_tree)

    def finish_inventory(self):
        """Tell the builder that the inventory is finished.

        Returns: The inventory id in the repository, which can be used with
            repository.get_inventory.
        """
        raise NotImplementedError(self.finish_inventory)

    def _generate_revision_if_needed(self, revision_id):
        """Create a revision id if None was supplied.

        If the repository can not support user-specified revision ids
        they should override this function and raise CannotSetRevisionId
        if _new_revision_id is not None.

        Raises:
          CannotSetRevisionId
        """
        if not self.repository._format.supports_setting_revision_ids:
            if revision_id is not None:
                raise CannotSetRevisionId()
            return
        if revision_id is None:
            self._new_revision_id = self._gen_revision_id()
            self.random_revid = True
        else:
            self._new_revision_id = revision_id
            self.random_revid = False

    def record_iter_changes(self, tree, basis_revision_id, iter_changes):
        """Record a new tree via iter_changes.

        Args:
          tree: The tree to obtain text contents from for changed objects.
          basis_revision_id: The revision id of the tree the iter_changes
            has been generated against. Currently assumed to be the same
            as self.parents[0] - if it is not, errors may occur.
          iter_changes: An iter_changes iterator with the changes to apply
            to basis_revision_id. The iterator must not include any items with
            a current kind of None - missing items must be either filtered out
            or errored-on beefore record_iter_changes sees the item.
        Returns: A generator of (relpath, fs_hash) tuples for use with
            tree._observed_sha1.
        """
        raise NotImplementedError(self.record_iter_changes)


class RepositoryWriteLockResult(LogicalLockResult):
    """The result of write locking a repository.

    Attributes:
      repository_token: The token obtained from the underlying lock, or
        None.
      unlock: A callable which will unlock the lock.
    """

    def __init__(self, unlock, repository_token):
        LogicalLockResult.__init__(self, unlock)
        self.repository_token = repository_token

    def __repr__(self):
        return f"RepositoryWriteLockResult({self.repository_token}, {self.unlock})"


class WriteGroup:
    """Context manager that manages a write group.

    Raising an exception will result in the write group being aborted.
    """

    def __init__(self, repository, suppress_errors=False):
        self.repository = repository
        self._suppress_errors = suppress_errors

    def __enter__(self):
        self.repository.start_write_group()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.repository.abort_write_group(self._suppress_errors)
            return False
        else:
            self.repository.commit_write_group()


######################################################################
# Repositories


class Repository(controldir.ControlComponent, _RelockDebugMixin):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    See VersionedFileRepository in breezy.vf_repository for the
    base class for most Bazaar repositories.
    """

    # Does this repository implementation support random access to
    # items in the tree, or just bulk fetching/pushing of data?
    supports_random_access = True

    def abort_write_group(self, suppress_errors=False):
        """Commit the contents accrued within the current write group.

        Args:
          suppress_errors: if true, abort_write_group will catch and log
            unexpected errors that happen during the abort, rather than
            allowing them to propagate.  Defaults to False.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            if suppress_errors:
                mutter(
                    "(suppressed) mismatched lock context and write group. %r, %r",
                    self._write_group,
                    self.get_transaction(),
                )
                return
            raise errors.BzrError(
                f"mismatched lock context and write group. {self._write_group!r}, {self.get_transaction()!r}"
            )
        try:
            self._abort_write_group()
        except Exception as exc:
            self._write_group = None
            if not suppress_errors:
                raise
            mutter("abort_write_group failed")
            log_exception_quietly()
            note(gettext("brz: ERROR (ignored): %s"), exc)
        self._write_group = None

    def _abort_write_group(self):
        """Template method for per-repository write group cleanup.

        This is called during abort before the write group is considered to be
        finished and should cleanup any internal state accrued during the write
        group. There is no requirement that data handed to the repository be
        *not* made available - this is not a rollback - but neither should any
        attempt be made to ensure that data added is fully commited. Abort is
        invoked when an error has occured so futher disk or network operations
        may not be possible or may error and if possible should not be
        attempted.
        """

    def add_fallback_repository(self, repository):
        """Add a repository to use for looking up data not held locally.

        Args:
          repository: A repository.
        """
        raise NotImplementedError(self.add_fallback_repository)

    def _check_fallback_repository(self, repository):
        """Check that this repository can fallback to repository safely.

        Raise an error if not.

        Args:
          repository: A repository to fallback to.
        """
        return InterRepository._assert_same_model(self, repository)

    def all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        This is conceptually deprecated because code should generally work on
        the graph reachable from a particular revision, and ignore any other
        revisions that might be present.  There is no direct replacement
        method.
        """
        if debug.debug_flag_enabled("evil"):
            mutter_callsite(2, "all_revision_ids is linear with history.")
        return self._all_revision_ids()

    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        These are in as much topological order as the underlying store can
        present.
        """
        raise NotImplementedError(self._all_revision_ids)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.
        """
        self.control_files.break_lock()

    @staticmethod
    def create(controldir):
        """Construct the current default format repository in controldir."""
        return RepositoryFormat.get_default_format().initialize(controldir)

    def __init__(self, _format, controldir, control_files):
        """Instantiate a Repository.

        Args:
          _format: The format of the repository on disk.
          controldir: The ControlDir of the repository.
          control_files: Control files to use for locking, etc.
        """
        # In the future we will have a single api for all stores for
        # getting file texts, inventories and revisions, then
        # this construct will accept instances of those things.
        super().__init__()
        self._format = _format
        # the following are part of the public API for Repository:
        self.controldir = controldir
        self.control_files = control_files
        # for tests
        self._write_group = None
        # Additional places to query for data.
        self._fallback_repositories = []

    @property
    def user_transport(self):
        return self.controldir.user_transport

    @property
    def control_transport(self):
        return self._transport

    def __repr__(self):
        if self._fallback_repositories:
            return "{}({!r}, fallback_repositories={!r})".format(
                self.__class__.__name__, self.base, self._fallback_repositories
            )
        else:
            return f"{self.__class__.__name__}({self.base!r})"

    def _has_same_fallbacks(self, other_repo):
        """Returns true if the repositories have the same fallbacks."""
        my_fb = self._fallback_repositories
        other_fb = other_repo._fallback_repositories
        if len(my_fb) != len(other_fb):
            return False
        return all(f.has_same_location(g) for f, g in zip(my_fb, other_fb))

    def has_same_location(self, other):
        """Returns a boolean indicating if this repository is at the same
        location as another repository.

        This might return False even when two repository objects are accessing
        the same physical repository via different URLs.
        """
        if self.__class__ is not other.__class__:
            return False
        return self.control_url == other.control_url

    def is_in_write_group(self):
        """Return True if there is an open write group.

        :seealso: start_write_group.
        """
        return self._write_group is not None

    def is_locked(self):
        return self.control_files.is_locked()

    def is_write_locked(self):
        """Return True if this object is write locked."""
        return self.is_locked() and self.control_files._lock_mode == "w"

    def lock_write(self, token=None):
        """Lock this repository for writing.

        This causes caching within the repository obejct to start accumlating
        data during reads, and allows a 'write_group' to be obtained. Write
        groups must be used for actual data insertion.

        A token should be passed in if you know that you have locked the object
        some other way, and need to synchronise this object's state with that
        fact.

        Args:
          token: if this is already locked, then lock_write will fail
            unless the token matches the existing lock.

        Returns:
          a token if this instance supports tokens, otherwise None.

        Raises:
          TokenLockingNotSupported: when a token is given but this
            instance doesn't support using token locks.
          MismatchedToken: if the specified token doesn't match the token
            of the existing lock.

        Returns:
          A RepositoryWriteLockResult.
        """
        locked = self.is_locked()
        token = self.control_files.lock_write(token=token)
        if not locked:
            self._warn_if_deprecated()
            self._note_lock("w")
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
            self._refresh_data()
        return RepositoryWriteLockResult(self.unlock, token)

    def lock_read(self):
        """Lock the repository for read operations.

        Returns: An object with an unlock method which will release the lock
            obtained.
        """
        locked = self.is_locked()
        self.control_files.lock_read()
        if not locked:
            self._warn_if_deprecated()
            self._note_lock("r")
            for repo in self._fallback_repositories:
                repo.lock_read()
            self._refresh_data()
        return LogicalLockResult(self.unlock)

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    def leave_lock_in_place(self):
        """Tell this repository not to release the physical lock when this
        object is unlocked.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.leave_in_place()

    def dont_leave_lock_in_place(self):
        """Tell this repository to release the physical lock when this
        object is unlocked, even if it didn't originally acquire it.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.dont_leave_in_place()

    def gather_stats(self, revid=None, committers=None):
        """Gather statistics from a revision id.

        Args:
          revid: The revision id to gather statistics from, if None, then
            no revision specific statistics are gathered.
          committers: Optional parameter controlling whether to grab
            a count of committers from the revision specific statistics.
        Returns: A dictionary of statistics. Currently this contains:
            committers: The number of committers if requested.
            firstrev: A tuple with timestamp, timezone for the penultimate left
                most ancestor of revid, if revid is not the NULL_REVISION.
            latestrev: A tuple with timestamp, timezone for revid, if revid is
                not the NULL_REVISION.
            revisions: The total revision count in the repository.
            size: An estimate disk size of the repository in bytes.
        """
        with self.lock_read():
            result = {}
            if revid and committers:
                result["committers"] = 0
            if revid and revid != _mod_revision.NULL_REVISION:
                graph = self.get_graph()
                if committers:
                    all_committers = set()
                revisions = [
                    r
                    for (r, p) in graph.iter_ancestry([revid])
                    if r != _mod_revision.NULL_REVISION
                ]
                last_revision = None
                if not committers:
                    # ignore the revisions in the middle - just grab first and last
                    revisions = revisions[0], revisions[-1]
                for revision in self.get_revisions(revisions):
                    if not last_revision:
                        last_revision = revision
                    if committers:
                        all_committers.add(revision.committer)
                first_revision = revision
                if committers:
                    result["committers"] = len(all_committers)
                result["firstrev"] = (first_revision.timestamp, first_revision.timezone)
                result["latestrev"] = (last_revision.timestamp, last_revision.timezone)
            return result

    def find_branches(self, using=False):
        """Find branches underneath this repository.

        This will include branches inside other branches.

        Args:
          using: If True, list only branches using this repository.
        """
        if using and not self.is_shared():
            yield from self.controldir.list_branches()
            return

        class Evaluator:
            def __init__(self):
                self.first_call = True

            def __call__(self, controldir):
                # On the first call, the parameter is always the controldir
                # containing the current repo.
                if not self.first_call:
                    try:
                        repository = controldir.open_repository()
                    except errors.NoRepositoryPresent:
                        pass
                    else:
                        return False, ([], repository)
                self.first_call = False
                value = (controldir.list_branches(), None)
                return True, value

        for branches, repository in controldir.ControlDir.find_controldirs(
            self.user_transport, evaluate=Evaluator()
        ):
            if branches is not None:
                yield from branches
            if not using and repository is not None:
                yield from repository.find_branches()

    def search_missing_revision_ids(
        self,
        other,
        find_ghosts=True,
        revision_ids=None,
        if_present_ids=None,
        limit=None,
    ):
        """Return the revision ids that other has that this does not.

        These are returned in topological order.

        revision_ids: only return revision ids included by revision_id.
        """
        with self.lock_read():
            return InterRepository.get(other, self).search_missing_revision_ids(
                find_ghosts=find_ghosts,
                revision_ids=revision_ids,
                if_present_ids=if_present_ids,
                limit=limit,
            )

    @staticmethod
    def open(base):
        """Open the repository rooted at base.

        For instance, if the repository is at URL/.bzr/repository,
        Repository.open(URL) -> a Repository instance.
        """
        control = controldir.ControlDir.open(base)
        return control.open_repository()

    def copy_content_into(self, destination, revision_id=None):
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.
        """
        return InterRepository.get(self, destination).copy_content(revision_id)

    def commit_write_group(self):
        """Commit the contents accrued within the current write group.

        :seealso: start_write_group.

        Returns: it may return an opaque hint that can be passed to 'pack'.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            raise errors.BzrError(
                f"mismatched lock context {self.get_transaction()!r} and "
                f"write group {self._write_group!r}."
            )
        result = self._commit_write_group()
        self._write_group = None
        return result

    def _commit_write_group(self):
        """Template method for per-repository write group cleanup.

        This is called before the write group is considered to be
        finished and should ensure that all data handed to the repository
        for writing during the write group is safely committed (to the
        extent possible considering file system caching etc).
        """

    def suspend_write_group(self):
        """Suspend a write group.

        Raises:
          UnsuspendableWriteGroup: If the write group can not be
            suspended.

        Returns:
          List of tokens
        """
        raise errors.UnsuspendableWriteGroup(self)

    def refresh_data(self):
        """Re-read any data needed to synchronise with disk.

        This method is intended to be called after another repository instance
        (such as one used by a smart server) has inserted data into the
        repository. On all repositories this will work outside of write groups.
        Some repository formats (pack and newer for breezy native formats)
        support refresh_data inside write groups. If called inside a write
        group on a repository that does not support refreshing in a write group
        IsInWriteGroupError will be raised.
        """
        self._refresh_data()

    def resume_write_group(self, tokens):
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group:
            raise errors.BzrError("already in a write group")
        self._resume_write_group(tokens)
        # so we can detect unlock/relock - the write group is now entered.
        self._write_group = self.get_transaction()

    def _resume_write_group(self, tokens):
        raise errors.UnsuspendableWriteGroup(self)

    def fetch(self, source, revision_id=None, find_ghosts=False, lossy=False):
        """Fetch the content required to construct revision_id from source.

        If revision_id is None, then all content is copied.

        fetch() may not be used when the repository is in a write group -
        either finish the current write group before using fetch, or use
        fetch before starting the write group.

        Args:
          find_ghosts: Find and copy revisions in the source that are
            ghosts in the target (and not reachable directly by walking out to
            the first-present revision in target from revision_id).
          revision_id: If specified, all the content needed for this
            revision ID will be copied to the target.  Fetch will determine for
            itself which content needs to be copied.
        Returns: A FetchResult object
        """
        if self.is_in_write_group():
            raise errors.InternalBzrError("May not fetch while in a write group.")
        # fast path same-url fetch operations
        # TODO: lift out to somewhere common with RemoteRepository
        # <https://bugs.launchpad.net/bzr/+bug/401646>
        if self.has_same_location(source) and self._has_same_fallbacks(source):
            # check that last_revision is in 'from' and then return a
            # no-operation.
            if revision_id is not None and not _mod_revision.is_null(revision_id):
                self.get_revision(revision_id)
            return 0, []
        inter = InterRepository.get(source, self)
        return inter.fetch(
            revision_id=revision_id, find_ghosts=find_ghosts, lossy=lossy
        )

    def get_commit_builder(
        self,
        branch,
        parents,
        config_stack,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this repository.

        Args:
          branch: Branch to commit to.
          parents: Revision ids of the parents of the new revision.
          config_stack: Configuration stack to use.
          timestamp: Optional timestamp recorded for commit.
          timezone: Optional timezone for timestamp.
          committer: Optional committer to set for commit.
          revprops: Optional dictionary of revision properties.
          revision_id: Optional revision id.
          lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        raise NotImplementedError(self.get_commit_builder)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if self.control_files._lock_count == 1 and self.control_files._lock_mode == "w":
            if self._write_group is not None:
                self.abort_write_group()
                self.control_files.unlock()
                raise errors.BzrError(
                    "Must end write groups before releasing write locks."
                )
        self.control_files.unlock()
        if self.control_files._lock_count == 0:
            for repo in self._fallback_repositories:
                repo.unlock()

    def clone(self, controldir, revision_id=None):
        """Clone this repository into controldir using the current format.

        Currently no check is made that the format of this repository and
        the bzrdir format are compatible. FIXME RBC 20060201.

        Returns: The newly created destination repository.
        """
        with self.lock_read():
            # TODO: deprecate after 0.16; cloning this with all its settings is
            # probably not very useful -- mbp 20070423
            dest_repo = self._create_sprouting_repo(controldir, shared=self.is_shared())
            self.copy_content_into(dest_repo, revision_id)
            return dest_repo

    def start_write_group(self):
        """Start a write group in the repository.

        Write groups are used by repositories which do not have a 1:1 mapping
        between file ids and backend store to manage the insertion of data from
        both fetch and commit operations.

        A write lock is required around the
        start_write_group/commit_write_group for the support of lock-requiring
        repository formats.

        One can only insert data into a repository inside a write group.

        Returns: None.
        """
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group:
            raise errors.BzrError("already in a write group")
        self._start_write_group()
        # so we can detect unlock/relock - the write group is now entered.
        self._write_group = self.get_transaction()

    def _start_write_group(self):
        """Template method for per-repository write group startup.

        This is called before the write group is considered to be
        entered.
        """

    def sprout(self, to_bzrdir, revision_id=None):
        """Create a descendent repository for new development.

        Unlike clone, this does not copy the settings of the repository.
        """
        with self.lock_read():
            dest_repo = self._create_sprouting_repo(to_bzrdir, shared=False)
            dest_repo.fetch(self, revision_id=revision_id)
            return dest_repo

    def _create_sprouting_repo(self, a_controldir, shared):
        if not isinstance(a_controldir._format, self.controldir._format.__class__):
            # use target default format.
            dest_repo = a_controldir.create_repository()
        else:
            # Most control formats need the repository to be specifically
            # created, but on some old all-in-one formats it's not needed
            try:
                dest_repo = self._format.initialize(a_controldir, shared=shared)
            except errors.UninitializableFormat:
                dest_repo = a_controldir.open_repository()
        return dest_repo

    def has_revision(self, revision_id):
        """True if this repository has a copy of the revision."""
        with self.lock_read():
            return revision_id in self.has_revisions((revision_id,))

    def has_revisions(self, revision_ids):
        """Probe to find out the presence of multiple revisions.

        Args:
          revision_ids: An iterable of revision_ids.
        Returns: A set of the revision_ids that were present.
        """
        raise NotImplementedError(self.has_revisions)

    def get_revision(self, revision_id):
        """Return the Revision object for a named revision."""
        with self.lock_read():
            return self.get_revisions([revision_id])[0]

    def get_revision_reconcile(self, revision_id):
        """'reconcile' helper routine that allows access to a revision always.

        This variant of get_revision does not cross check the weave graph
        against the revision one as get_revision does: but it should only
        be used by reconcile, or reconcile-alike commands that are correcting
        or testing the revision graph.
        """
        raise NotImplementedError(self.get_revision_reconcile)

    def get_revisions(self, revision_ids):
        """Get many revisions at once.

        Repositories that need to check data on every revision read should
        subclass this method.
        """
        revs = {}
        for revid, rev in self.iter_revisions(revision_ids):
            if rev is None:
                raise errors.NoSuchRevision(self, revid)
            revs[revid] = rev
        return [revs[revid] for revid in revision_ids]

    def iter_revisions(self, revision_ids):
        """Iterate over revision objects.

        Args:
          revision_ids: An iterable of revisions to examine. None may be
            passed to request all revisions known to the repository. Note that
            not all repositories can find unreferenced revisions; for those
            repositories only referenced ones will be returned.
        Returns: An iterator of (revid, revision) tuples. Absent revisions (
            those asked for but not available) are returned as (revid, None).
            N.B.: Revisions are not necessarily yielded in order.
        """
        raise NotImplementedError(self.iter_revisions)

    def get_revision_delta(self, revision_id):
        """Return the delta for one revision.

        The delta is relative to the left-hand predecessor of the
        revision.
        """
        with self.lock_read():
            r = self.get_revision(revision_id)
            return list(self.get_revision_deltas([r]))[0]

    def get_revision_deltas(self, revisions, specific_files=None):
        """Produce a generator of revision deltas.

        Note that the input is a sequence of REVISIONS, not revision ids.
        Trees will be held in memory until the generator exits.
        Each delta is relative to the revision's lefthand predecessor.

        specific_files should exist in the first revision.

        Args:
          specific_files: if not None, the result is filtered
          so that only those files, their parents and their
          children are included.
        """
        from .tree import InterTree

        # Get the revision-ids of interest
        required_trees = set()
        for revision in revisions:
            required_trees.add(revision.revision_id)
            required_trees.update(revision.parent_ids[:1])

        trees = {t.get_revision_id(): t for t in self.revision_trees(required_trees)}

        # Calculate the deltas
        for revision in revisions:
            if not revision.parent_ids:
                old_tree = self.revision_tree(_mod_revision.NULL_REVISION)
            else:
                old_tree = trees[revision.parent_ids[0]]
            intertree = InterTree.get(old_tree, trees[revision.revision_id])
            yield intertree.compare(specific_files=specific_files)
            if specific_files is not None:
                specific_files = [
                    p
                    for p in intertree.find_source_paths(specific_files).values()
                    if p is not None
                ]

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        raise NotImplementedError(self.store_revision_signature)

    def add_signature_text(self, revision_id, signature):
        """Store a signature text for a revision.

        Args:
          revision_id: Revision id of the revision
          signature: Signature text.
        """
        raise NotImplementedError(self.add_signature_text)

    def iter_files_bytes(self, desired_files):
        """Iterate through file versions.

        Files will not necessarily be returned in the order they occur in
        desired_files.  No specific order is guaranteed.

        Yields pairs of identifier, bytes_iterator.  identifier is an opaque
        value supplied by the caller as part of desired_files.  It should
        uniquely identify the file version in the caller's context.  (Examples:
        an index number or a TreeTransform trans_id.)

        Args:
          desired_files: a list of (file_id, revision_id, identifier)
            triples
        """
        raise NotImplementedError(self.iter_files_bytes)

    def get_rev_id_for_revno(self, revno, known_pair):
        """Return the revision id of a revno, given a later (revno, revid)
        pair in the same history.

        Returns: if found (True, revid).  If the available history ran out
            before reaching the revno, then this returns
            (False, (closest_revno, closest_revid)).
        """
        known_revno, known_revid = known_pair
        partial_history = [known_revid]
        distance_from_known = known_revno - revno
        if distance_from_known < 0:
            raise errors.RevnoOutOfBounds(revno, (0, known_revno))
        try:
            _iter_for_revno(self, partial_history, stop_index=distance_from_known)
        except errors.RevisionNotPresent as err:
            if err.revision_id == known_revid:
                # The start revision (known_revid) wasn't found.
                raise errors.NoSuchRevision(self, known_revid) from err
            # This is a stacked repository with no fallbacks, or a there's a
            # left-hand ghost.  Either way, even though the revision named in
            # the error isn't in this repo, we know it's the next step in this
            # left-hand history.
            partial_history.append(err.revision_id)
        if len(partial_history) <= distance_from_known:
            # Didn't find enough history to get a revid for the revno.
            earliest_revno = known_revno - len(partial_history) + 1
            return (False, (earliest_revno, partial_history[-1]))
        if len(partial_history) - 1 > distance_from_known:
            raise AssertionError("_iter_for_revno returned too much history")
        return (True, partial_history[-1])

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        raise NotImplementedError(self.is_shared)

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        raise NotImplementedError(self.reconcile)

    def _refresh_data(self):
        """Helper called from lock_* to ensure coherency with disk.

        The default implementation does nothing; it is however possible
        for repositories to maintain loaded indices across multiple locks
        by checking inside their implementation of this method to see
        whether their indices are still valid. This depends of course on
        the disk format being validatable in this manner. This method is
        also called by the refresh_data() public interface to cause a refresh
        to occur while in a write lock so that data inserted by a smart server
        push operation is visible on the client's instance of the physical
        repository.
        """

    def revision_tree(self, revision_id) -> "RevisionTree":
        """Return Tree for a revision on this branch.

        `revision_id` may be NULL_REVISION for the empty tree revision.
        """
        raise NotImplementedError(self.revision_tree)

    def revision_trees(self, revision_ids):
        """Return Trees for revisions in this repository.

        Args:
          revision_ids: a sequence of revision-ids;
          a revision-id may not be None or b'null:'
        """
        raise NotImplementedError(self.revision_trees)

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Compress the data within the repository.

        This operation only makes sense for some repository types. For other
        types it should be a no-op that just returns.

        This stub method does not require a lock, but subclasses should use
        self.write_lock as this is a long running call it's reasonable to
        implicitly lock for the user.

        Args:
          hint: If not supplied, the whole repository is packed.
            If supplied, the repository may use the hint parameter as a
            hint for the parts of the repository to pack. A hint can be
            obtained from the result of commit_write_group(). Out of
            date hints are simply ignored, because concurrent operations
            can obsolete them rapidly.

          clean_obsolete_packs: Clean obsolete packs immediately after
            the pack operation.
        """

    def get_transaction(self):
        return self.control_files.get_transaction()

    def get_parent_map(self, revision_ids):
        """See graph.StackedParentsProvider.get_parent_map."""
        raise NotImplementedError(self.get_parent_map)

    def _get_parent_map_no_fallbacks(self, revision_ids):
        """Same as Repository.get_parent_map except doesn't query fallbacks."""
        # revisions index works in keys; this just works in revisions
        # therefore wrap and unwrap
        query_keys = []
        result = {}
        for revision_id in revision_ids:
            if revision_id == _mod_revision.NULL_REVISION:
                result[revision_id] = ()
            elif revision_id is None:
                raise ValueError("get_parent_map(None) is not valid")
            else:
                query_keys.append((revision_id,))
        vf = self.revisions.without_fallbacks()
        for (revision_id,), parent_keys in vf.get_parent_map(query_keys).items():
            if parent_keys:
                result[revision_id] = tuple(
                    [parent_revid for (parent_revid,) in parent_keys]
                )
            else:
                result[revision_id] = (_mod_revision.NULL_REVISION,)
        return result

    def _make_parents_provider(self):
        if not self._format.supports_external_lookups:
            return self
        return graph.StackedParentsProvider(
            _LazyListJoin(
                [self._make_parents_provider_unstacked()], self._fallback_repositories
            )
        )

    def _make_parents_provider_unstacked(self):
        return graph.CallableToParentsProviderAdapter(self._get_parent_map_no_fallbacks)

    def get_known_graph_ancestry(self, revision_ids):
        """Return the known graph for a set of revision ids and their ancestors."""
        raise NotImplementedError(self.get_known_graph_ancestry)

    def get_file_graph(self):
        """Return the graph walker for files."""
        raise NotImplementedError(self.get_file_graph)

    def get_graph(self, other_repository=None):
        """Return the graph walker for this repository format."""
        parents_provider = self._make_parents_provider()
        if other_repository is not None and not self.has_same_location(
            other_repository
        ):
            parents_provider = graph.StackedParentsProvider(
                [parents_provider, other_repository._make_parents_provider()]
            )
        return graph.Graph(parents_provider)

    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.

        Args:
          new_value: True to restore the default, False to disable making
                          working trees.
        """
        raise NotImplementedError(self.set_make_working_trees)

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        raise NotImplementedError(self.make_working_trees)

    def sign_revision(self, revision_id, gpg_strategy):
        raise NotImplementedError(self.sign_revision)

    def verify_revision_signature(self, revision_id, gpg_strategy):
        """Verify the signature on a revision.

        Args:
          revision_id: the revision to verify
          gpg_strategy: the GPGStrategy object to used

        Returns: gpg.SIGNATURE_VALID or a failed SIGNATURE_ value
        """
        raise NotImplementedError(self.verify_revision_signature)

    def verify_revision_signatures(self, revision_ids, gpg_strategy):
        """Verify revision signatures for a number of revisions.

        Args:
          revision_id: the revision to verify
          gpg_strategy: the GPGStrategy object to used

        Returns:
          Iterator over tuples with revision id, result and keys
        """
        with self.lock_read():
            for revid in revision_ids:
                (result, key) = self.verify_revision_signature(revid, gpg_strategy)
                yield revid, result, key

    def has_signature_for_revision_id(self, revision_id):
        """Query for a revision signature for revision_id in the repository."""
        raise NotImplementedError(self.has_signature_for_revision_id)

    def get_signature_text(self, revision_id):
        """Return the text for a signature."""
        raise NotImplementedError(self.get_signature_text)

    def check(self, revision_ids=None, callback_refs=None, check_repo=True):
        """Check consistency of all history of given revision_ids.

        Different repository implementations should override _check().

        Args:
          revision_ids: A non-empty list of revision_ids whose ancestry
             will be checked.  Typically the last revision_id of a branch.
          callback_refs: A dict of check-refs to resolve and callback
            the check/_check method on the items listed as wanting the ref.
            see breezy.check.
          check_repo: If False do not check the repository contents, just
            calculate the data callback_refs requires and call them back.
        """
        return self._check(
            revision_ids=revision_ids,
            callback_refs=callback_refs,
            check_repo=check_repo,
        )

    def _check(self, revision_ids=None, callback_refs=None, check_repo=True):
        raise NotImplementedError(self.check)

    def _warn_if_deprecated(self, branch=None):
        if not self._format.is_deprecated():
            return
        global _deprecation_warning_done
        if _deprecation_warning_done:
            return
        try:
            conf = config.GlobalStack() if branch is None else branch.get_config_stack()
            if "format_deprecation" in conf.get("suppress_warnings"):
                return
            warning(
                f"Format {self._format} for {self.controldir.transport.base} is deprecated -"
                " please use 'brz upgrade' to get better performance"
            )
        finally:
            _deprecation_warning_done = True

    def supports_rich_root(self):
        return self._format.rich_root_data

    def _check_ascii_revisionid(self, revision_id, method):
        """Private helper for ascii-only repositories."""
        # weave repositories refuse to store revisionids that are non-ascii.
        if revision_id is not None:
            # weaves require ascii revision ids.
            if isinstance(revision_id, str):
                try:
                    revision_id.encode("ascii")
                except UnicodeEncodeError as err:
                    raise errors.NonAsciiRevisionId(method, self) from err
            else:
                try:
                    revision_id.decode("ascii")
                except UnicodeDecodeError as err:
                    raise errors.NonAsciiRevisionId(method, self) from err


class RepositoryFormatRegistry(controldir.ControlComponentFormatRegistry):
    """Repository format registry."""

    def get_default(self):
        """Return the current default format."""
        return controldir.format_registry.make_controldir("default").repository_format


network_format_registry = registry.FormatRegistry["RepositoryFormat", None]()
"""Registry of formats indexed by their network name.

The network name for a repository format is an identifier that can be used when
referring to formats with smart server operations. See
RepositoryFormat.network_name() for more detail.
"""


format_registry = RepositoryFormatRegistry(network_format_registry)
"""Registry of formats, indexed by their BzrDirMetaFormat format string.

This can contain either format instances themselves, or classes/factories that
can be called to obtain one.
"""


#####################################################################
# Repository Formats


class RepositoryFormat(controldir.ControlComponentFormat):
    """A repository format.

    Formats provide four things:
     * An initialization routine to construct repository data on disk.
     * a optional format string which is used when the BzrDir supports
       versioned children.
     * an open routine which returns a Repository instance.
     * A network name for referring to the format in smart server RPC
       methods.

    There is one and only one Format subclass for each on-disk format. But
    there can be one Repository subclass that is used for several different
    formats. The _format attribute on a Repository instance can be used to
    determine the disk format.

    Formats are placed in a registry by their format string for reference
    during opening. These should be subclasses of RepositoryFormat for
    consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object may be created even when a repository instance hasn't been
    created.

    Common instance attributes:
    _matchingcontroldir - the controldir format that the repository format was
    originally written to work with. This can be used if manually
    constructing a bzrdir and repository, or more commonly for test suite
    parameterization.
    """

    # Set to True or False in derived classes. True indicates that the format
    # supports ghosts gracefully.
    supports_ghosts: bool
    # Can this repository be given external locations to lookup additional
    # data. Set to True or False in derived classes.
    supports_external_lookups: bool
    # Does this format support CHK bytestring lookups. Set to True or False in
    # derived classes.
    supports_chks: bool
    # Should fetch trigger a reconcile after the fetch? Only needed for
    # some repository formats that can suffer internal inconsistencies.
    _fetch_reconcile: bool = False
    # Does this format have < O(tree_size) delta generation. Used to hint what
    # code path for commit, amongst other things.
    fast_deltas: bool
    # Does doing a pack operation compress data? Useful for the pack UI command
    # (so if there is one pack, the operation can still proceed because it may
    # help), and for fetching when data won't have come from the same
    # compressor.
    pack_compresses: bool = False
    # Does the repository storage understand references to trees?
    supports_tree_reference: bool
    # Is the format experimental ?
    experimental: bool = False
    # Does this repository format escape funky characters, or does it create
    # files with similar names as the versioned files in its contents on disk
    # ?
    supports_funky_characters: bool
    # Does this repository format support leaving locks?
    supports_leaving_lock: bool
    # Does this format support the full VersionedFiles interface?
    supports_full_versioned_files: bool
    # Does this format support signing revision signatures?
    supports_revision_signatures: bool = True
    # Can the revision graph have incorrect parents?
    revision_graph_can_have_wrong_parents: bool
    # Does this format support setting revision ids?
    supports_setting_revision_ids: bool = True
    # Does this format support rich root data?
    rich_root_data: bool
    # Does this format support explicitly versioned directories?
    supports_versioned_directories: bool
    # Can other repositories be nested into one of this format?
    supports_nesting_repositories: bool
    # Is it possible for revisions to be present without being referenced
    # somewhere ?
    supports_unreferenced_revisions: bool
    # Does this format store the current Branch.nick in a revision when
    # creating commits?
    supports_storing_branch_nick: bool = True
    # Does the format support overriding the transport to use
    supports_overriding_transport: bool = True
    # Does the format support setting custom revision properties?
    supports_custom_revision_properties: bool = True
    # Does the format record per-file revision metadata?
    records_per_file_revision: bool = True
    supports_multiple_authors: bool = True

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __eq__(self, other):
        # format objects are generally stateless
        return isinstance(other, self.__class__)

    def __ne__(self, other):
        return not self == other

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def initialize(self, controldir, shared=False):
        """Initialize a repository of this format in controldir.

        Args:
          controldir: The controldir to put the new repository in it.
          shared: The repository should be initialized as a sharable one.

        Returns:
          The new repository object.

        This may raise UninitializableFormat if shared repository are not
        compatible the controldir.
        """
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def is_deprecated(self):
        """Is this format deprecated?

        Deprecated formats may trigger a user-visible warning recommending
        the user to upgrade. They are still fully supported.
        """
        return False

    def network_name(self):
        """A simple byte string uniquely identifying this format for RPC calls.

        MetaDir repository formats use their disk format string to identify the
        repository over the wire. All in one formats such as bzr < 0.8, and
        foreign formats like svn/git and hg should use some marker which is
        unique and immutable.
        """
        raise NotImplementedError(self.network_name)

    def check_conversion_target(self, target_format):
        if self.rich_root_data and not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                "Does not support rich root data.", target_format, from_format=self
            )
        if self.supports_tree_reference and not getattr(
            target_format, "supports_tree_reference", False
        ):
            raise errors.BadConversionTarget(
                "Does not support nested trees", target_format, from_format=self
            )

    def open(self, controldir, _found=False):
        """Return an instance of this format for a controldir.

        _found is a private parameter, do not use it.
        """
        raise NotImplementedError(self.open)

    def _run_post_repo_init_hooks(self, repository, controldir, shared):
        from .controldir import ControlDir, RepoInitHookParams

        hooks = ControlDir.hooks["post_repo_init"]
        if not hooks:
            return
        params = RepoInitHookParams(repository, self, controldir, shared)
        for hook in hooks:
            hook(params)


class AbstractSearchResult:
    """The result of a search, describing a set of keys.

    Search results are typically used as the 'fetch_spec' parameter when
    fetching revisions.

    :seealso: AbstractSearch
    """

    def get_recipe(self):
        """Return a recipe that can be used to replay this search.

        The recipe allows reconstruction of the same results at a later date.

        :return: A tuple of `(search_kind_str, *details)`.  The details vary by
            kind of search result.
        """
        raise NotImplementedError(self.get_recipe)

    def get_network_struct(self):
        """Return a tuple that can be transmitted via the HPSS protocol."""
        raise NotImplementedError(self.get_network_struct)

    def get_keys(self):
        """Return the keys found in this search.

        :return: A set of keys.
        """
        raise NotImplementedError(self.get_keys)

    def is_empty(self):
        """Return false if the search lists 1 or more revisions."""
        raise NotImplementedError(self.is_empty)

    def refine(self, seen, referenced):
        """Create a new search by refining this search.

        :param seen: Revisions that have been satisfied.
        :param referenced: Revision references observed while satisfying some
            of this search.
        :return: A search result.
        """
        raise NotImplementedError(self.refine)


class InterRepository(InterObject[Repository]):
    """This class represents operations taking place between two repositories.

    Its instances have methods like copy_content and fetch, and contain
    references to the source and target repositories these operations can be
    carried out on.

    Often we will provide convenience methods on 'repository' which carry out
    operations with another repository - they will always forward to
    InterRepository.get(other).method_name(parameters).
    """

    _optimisers = []
    """The available optimised InterRepository types."""

    def copy_content(
        self, revision_id: Optional[_mod_revision.RevisionID] = None
    ) -> None:
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.

        Args:
          revision_id: Only copy the content needed to construct
                            revision_id and its parents.
        """
        with self.lock_write():
            with contextlib.suppress(
                NotImplementedError, errors.RepositoryUpgradeRequired
            ):
                self.target.set_make_working_trees(self.source.make_working_trees())
            self.target.fetch(self.source, revision_id=revision_id)

    def fetch(
        self,
        revision_id: Optional[_mod_revision.RevisionID] = None,
        find_ghosts: bool = False,
        lossy: bool = False,
    ) -> FetchResult:
        """Fetch the content required to construct revision_id.

        The content is copied from self.source to self.target.

        Args:
          revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        Returns: FetchResult
        """
        raise NotImplementedError(self.fetch)

    def search_missing_revision_ids(
        self,
        find_ghosts: bool = True,
        revision_ids: Optional[Iterable[_mod_revision.RevisionID]] = None,
        if_present_ids: Optional[Iterable[_mod_revision.RevisionID]] = None,
        limit: Optional[int] = None,
    ) -> AbstractSearchResult:
        """Return the revision ids that source has that target does not.

        Args:
          revision_ids: return revision ids included by these
            revision_ids.  NoSuchRevision will be raised if any of these
            revisions are not present.
          if_present_ids: like revision_ids, but will not cause
            NoSuchRevision if any of these are absent, instead they will simply
            not be in the result.  This is useful for e.g. finding revisions
            to fetch for tags, which may reference absent revisions.
          find_ghosts: If True find missing revisions in deep history
            rather than just finding the surface difference.
          limit: Maximum number of revisions to return, topologically
            ordered
        Returns: A SearchResult.
        """
        raise NotImplementedError(self.search_missing_revision_ids)

    @staticmethod
    def _same_model(source, target):
        """True if source and target have the same data representation.

        Note: this is always called on the base class; overriding it in a
        subclass will have no effect.
        """
        try:
            InterRepository._assert_same_model(source, target)
            return True
        except errors.IncompatibleRepositories:
            return False

    @staticmethod
    def _assert_same_model(source, target):
        """Raise an exception if two repositories do not use the same model."""
        if source.supports_rich_root() != target.supports_rich_root():
            raise errors.IncompatibleRepositories(
                source, target, "different rich-root support"
            )
        if not hasattr(source, "_revision_serializer") or not hasattr(
            target, "_revision_serializer"
        ):
            if source != target:
                raise errors.IncompatibleRepositories(
                    source, target, "different formats"
                )
            return

        if source._inventory_serializer != target._inventory_serializer:
            raise errors.IncompatibleRepositories(
                source, target, "different inventory serializers"
            )

        if source._revision_serializer != target._revision_serializer:
            raise errors.IncompatibleRepositories(
                source, target, "different revision serializers"
            )


class CopyConverter:
    """A repository conversion tool which just performs a copy of the content.

    This is slow but quite reliable.
    """

    def __init__(self, target_format):
        """Create a CopyConverter.

        Args:
          target_format: The format the resulting repository should be.
        """
        self.target_format = target_format

    def convert(self, repo, pb):
        """Perform the conversion of to_convert, giving feedback via pb.

        Args:
          to_convert: The disk object to convert.
          pb: a progress bar to use for progress information.
        """
        with ui.ui_factory.nested_progress_bar() as pb:
            self.count = 0
            self.total = 4
            # this is only useful with metadir layouts - separated repo content.
            # trigger an assertion if not such
            repo._format.get_format_string()
            self.repo_dir = repo.controldir
            pb.update(gettext("Moving repository to repository.backup"))
            self.repo_dir.transport.move("repository", "repository.backup")
            backup_transport = self.repo_dir.transport.clone("repository.backup")
            repo._format.check_conversion_target(self.target_format)
            self.source_repo = repo._format.open(
                self.repo_dir, _found=True, _override_transport=backup_transport
            )
            pb.update(gettext("Creating new repository"))
            converted = self.target_format.initialize(
                self.repo_dir, self.source_repo.is_shared()
            )
            with converted.lock_write():
                pb.update(gettext("Copying content"))
                self.source_repo.copy_content_into(converted)
            pb.update(gettext("Deleting old repository content"))
            self.repo_dir.transport.delete_tree("repository.backup")
            ui.ui_factory.note(gettext("repository converted"))


def _strip_NULL_ghosts(revision_graph):
    """Also don't use this. more compatibility code for unmigrated clients."""
    # Filter ghosts, and null:
    if _mod_revision.NULL_REVISION in revision_graph:
        del revision_graph[_mod_revision.NULL_REVISION]
    for key, parents in revision_graph.items():
        revision_graph[key] = tuple(
            parent for parent in parents if parent in revision_graph
        )
    return revision_graph


def _iter_for_revno(repo, partial_history_cache, stop_index=None, stop_revision=None):
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
    start_revision = partial_history_cache[-1]
    graph = repo.get_graph()
    iterator = graph.iter_lefthand_ancestry(
        start_revision, (_mod_revision.NULL_REVISION,)
    )
    try:
        # skip the last revision in the list
        next(iterator)
        while True:
            if stop_index is not None and len(partial_history_cache) > stop_index:
                break
            if partial_history_cache[-1] == stop_revision:
                break
            revision_id = next(iterator)
            partial_history_cache.append(revision_id)
    except StopIteration:
        # No more history
        return


class _LazyListJoin:
    """An iterable yielding the contents of many lists as one list.

    Each iterator made from this will reflect the current contents of the lists
    at the time the iterator is made.

    This is used by Repository's _make_parents_provider implementation so that
    it is safe to do::

      pp = repo._make_parents_provider()      # uses a list of fallback repos
      pp.add_fallback_repository(other_repo)  # appends to that list
      result = pp.get_parent_map(...)
      # The result will include revs from other_repo
    """

    def __init__(self, *list_parts):
        self.list_parts = list_parts

    def __iter__(self):
        full_list = []
        for list_part in self.list_parts:
            full_list.extend(list_part)
        return iter(full_list)

    def __repr__(self):
        return f"{self.__module__}.{self.__class__.__name__}({self.list_parts})"

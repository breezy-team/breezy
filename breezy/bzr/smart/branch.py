# Copyright (C) 2006-2010 Canonical Ltd
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

"""Server-side branch related request implmentations."""

import fastbencode as bencode

from ... import errors
from ... import revision as _mod_revision
from ... import transport as _mod_transport
from ...controldir import ControlDir
from .request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
)


class SmartServerBranchRequest(SmartServerRequest):
    """Base class for handling common branch request logic.

    This class provides the basic infrastructure for handling smart server
    requests that operate on branches. It handles path resolution, branch
    opening, and ensures that branch references are properly rejected.

    Attributes:
        transport: The transport used to access the branch.
        root_client_path: The root path from the client's perspective.
    """

    def do(self, path, *args):
        """Execute a request for a branch at path.

        All Branch requests take a path to the branch as their first argument.

        If the branch is a branch reference, NotBranchError is raised.

        :param path: The path for the repository as received from the
            client.
        :return: A SmartServerResponse from self.do_with_branch().
        """
        transport = self.transport_from_client_path(path)
        controldir = ControlDir.open_from_transport(transport)
        if controldir.get_branch_reference() is not None:
            raise errors.NotBranchError(transport.base)
        branch = controldir.open_branch(ignore_fallbacks=True)
        return self.do_with_branch(branch, *args)


class SmartServerLockedBranchRequest(SmartServerBranchRequest):
    """Base class for handling common branch request logic for requests that need a write lock.

    This class extends SmartServerBranchRequest to provide automatic write lock
    acquisition and release for operations that modify branch state. It ensures
    that both branch and repository locks are properly managed.

    The locking is performed using context managers to guarantee proper cleanup
    even if exceptions occur during request processing.
    """

    def do_with_branch(self, branch, branch_token, repo_token, *args):
        """Execute a request for a branch.

        A write lock will be acquired with the given tokens for the branch and
        repository locks.  The lock will be released once the request is
        processed.  The physical lock state won't be changed.
        """
        # XXX: write a test for LockContention
        with (
            branch.repository.lock_write(token=repo_token),
            branch.lock_write(token=branch_token),
        ):
            return self.do_with_locked_branch(branch, *args)


class SmartServerBranchBreakLock(SmartServerBranchRequest):
    """Request handler for breaking branch locks.

    This handler allows clients to forcibly break a lock on a branch,
    useful when a lock is held by a dead process.
    """

    def do_with_branch(self, branch):
        """Break a branch lock.

        Args:
            branch: The branch whose lock should be broken.

        Returns:
            SuccessfulSmartServerResponse: Always returns success after breaking the lock.

        Note:
            This operation forcibly breaks the lock, which may cause data loss
            if another process is actively using the branch.
        """
        branch.break_lock()
        return SuccessfulSmartServerResponse(
            (b"ok",),
        )


class SmartServerBranchGetConfigFile(SmartServerBranchRequest):
    """Request handler for retrieving branch configuration files.

    Returns the raw content of the branch.conf file from the branch's
    control directory.
    """

    def do_with_branch(self, branch):
        """Return the content of branch.conf.

        The body is not utf8 decoded - its the literal bytestream from disk.
        """
        try:
            content = branch.control_transport.get_bytes("branch.conf")
        except _mod_transport.NoSuchFile:
            content = b""
        return SuccessfulSmartServerResponse((b"ok",), content)


class SmartServerBranchPutConfigFile(SmartServerBranchRequest):
    """Set the configuration data for a branch.

    New in 2.5.
    """

    def do_with_branch(self, branch, branch_token, repo_token):
        """Set the content of branch.conf.

        The body is not utf8 decoded - its the literal bytestream for disk.
        """
        self._branch = branch
        self._branch_token = branch_token
        self._repo_token = repo_token
        # Signal we want a body
        return None

    def do_body(self, body_bytes):
        """Process body data for tag setting request.

        Args:
            body_bytes: Bytes containing tag data.
        """
        with (
            self._branch.repository.lock_write(token=self._repo_token),
            self._branch.lock_write(token=self._branch_token),
        ):
            self._branch.control_transport.put_bytes("branch.conf", body_bytes)
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerBranchGetParent(SmartServerBranchRequest):
    """Request handler for retrieving a branch's parent location.

    Returns the parent branch URL that this branch was created from,
    or an empty string if no parent is set.
    """

    def do_with_branch(self, branch):
        """Return the parent of branch.

        Args:
            branch: The branch to query for parent location.

        Returns:
            SuccessfulSmartServerResponse: Contains the UTF-8 encoded parent URL,
                or an empty string if no parent is set.
        """
        parent = branch._get_parent_location() or ""
        return SuccessfulSmartServerResponse((parent.encode("utf-8"),))


class SmartServerBranchGetTagsBytes(SmartServerBranchRequest):
    """Request handler for retrieving branch tags as raw bytes.

    Returns the serialized tag dictionary for the branch.
    """

    def do_with_branch(self, branch):
        """Return the _get_tags_bytes for a branch.

        Args:
            branch: The branch to retrieve tags from.

        Returns:
            SuccessfulSmartServerResponse: Contains the serialized tag dictionary
                as raw bytes.
        """
        bytes = branch._get_tags_bytes()
        return SuccessfulSmartServerResponse((bytes,))


class SmartServerBranchSetTagsBytes(SmartServerLockedBranchRequest):
    """Request handler for setting branch tags from raw bytes.

    Updates the branch's tag dictionary with the provided serialized data.
    Requires a write lock on the branch.

    New in 1.18.
    """

    def __init__(self, backing_transport, root_client_path="/", jail_root=None):
        """Initialize the SmartServerBranchSetTagsBytes handler.

        Args:
            backing_transport: The transport for accessing the branch.
            root_client_path: The root path from client's perspective (default: "/").
            jail_root: Optional root directory to restrict access to.
        """
        SmartServerLockedBranchRequest.__init__(
            self, backing_transport, root_client_path, jail_root
        )
        self.locked = False

    def do_with_locked_branch(self, branch):
        """Call _set_tags_bytes for a branch.

        New in 1.18.
        """
        # We need to keep this branch locked until we get a body with the tags
        # bytes.
        self.branch = branch
        self.branch.lock_write()
        self.locked = True

    def do_body(self, bytes):
        """Process the body containing serialized tags.

        Args:
            bytes: The serialized tag data to set on the branch.

        Returns:
            SuccessfulSmartServerResponse indicating completion.
        """
        self.branch._set_tags_bytes(bytes)
        return SuccessfulSmartServerResponse(())

    def do_end(self):
        """Clean up after tag setting operation.

        Ensures the branch lock is properly released if it was acquired.
        """
        # TODO: this request shouldn't have to do this housekeeping manually.
        # Some of this logic probably belongs in a base class.
        if not self.locked:
            # We never acquired the branch successfully in the first place, so
            # there's nothing more to do.
            return
        try:
            return SmartServerLockedBranchRequest.do_end(self)
        finally:
            # Only try unlocking if we locked successfully in the first place
            self.branch.unlock()


class SmartServerBranchHeadsToFetch(SmartServerBranchRequest):
    """Request handler for determining which branch heads need fetching.

    Returns two lists of revision IDs: those that must be fetched and
    those that should be fetched if present.

    New in 2.4.
    """

    def do_with_branch(self, branch):
        """Return the heads-to-fetch for a Branch as two bencoded lists.

        See Branch.heads_to_fetch.

        New in 2.4.
        """
        must_fetch, if_present_fetch = branch.heads_to_fetch()
        return SuccessfulSmartServerResponse((list(must_fetch), list(if_present_fetch)))


class SmartServerBranchRequestGetStackedOnURL(SmartServerBranchRequest):
    """Request handler for retrieving the stacked-on branch URL.

    Returns the URL of the branch that this branch is stacked on,
    allowing for more efficient storage by sharing history.
    """

    def do_with_branch(self, branch):
        """Return the URL of the branch this branch is stacked on.

        Args:
            branch: The branch to query for stacking information.

        Returns:
            SuccessfulSmartServerResponse: Contains "ok" status and the ASCII-encoded
                stacked-on URL.

        Raises:
            Implicitly raises NotStacked error if branch is not stacked.
        """
        stacked_on_url = branch.get_stacked_on_url()
        return SuccessfulSmartServerResponse((b"ok", stacked_on_url.encode("ascii")))


class SmartServerRequestRevisionHistory(SmartServerBranchRequest):
    """Request handler for retrieving the complete revision history.

    Returns the list of all revision IDs in the branch's ancestry,
    from oldest to newest.
    """

    def do_with_branch(self, branch):
        r"""Get the revision history for the branch.

        The revision list is returned as the body content,
        with each revision utf8 encoded and \x00 joined.
        """
        with branch.lock_read():
            graph = branch.repository.get_graph()
            stop_revisions = (None, _mod_revision.NULL_REVISION)
            history = list(
                graph.iter_lefthand_ancestry(branch.last_revision(), stop_revisions)
            )
        return SuccessfulSmartServerResponse(
            (b"ok",), (b"\x00".join(reversed(history)))
        )


class SmartServerBranchRequestLastRevisionInfo(SmartServerBranchRequest):
    """Request handler for retrieving the last revision information.

    Returns the revision number and revision ID of the branch tip.
    """

    def do_with_branch(self, branch):
        """Return branch.last_revision_info().

        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        revno, last_revision = branch.last_revision_info()
        return SuccessfulSmartServerResponse(
            (b"ok", str(revno).encode("ascii"), last_revision)
        )


class SmartServerBranchRequestRevisionIdToRevno(SmartServerBranchRequest):
    """Request handler for converting revision IDs to revision numbers.

    Maps a revision ID to its corresponding dotted revision number
    in the branch's history.

    New in 2.5.
    """

    def do_with_branch(self, branch, revid):
        """Return branch.revision_id_to_revno().

        New in 2.5.

        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        try:
            dotted_revno = branch.revision_id_to_dotted_revno(revid)
        except errors.NoSuchRevision:
            return FailedSmartServerResponse((b"NoSuchRevision", revid))
        except errors.GhostRevisionsHaveNoRevno as e:
            return FailedSmartServerResponse(
                (b"GhostRevisionsHaveNoRevno", e.revision_id, e.ghost_revision_id)
            )
        return SuccessfulSmartServerResponse(
            (b"ok",) + tuple([b"%d" % x for x in dotted_revno])
        )


class SmartServerSetTipRequest(SmartServerLockedBranchRequest):
    """Base class for handling common branch request logic for requests that update the branch tip.

    This class provides a common framework for operations that modify the branch tip,
    including proper error handling for tip change rejections. It ensures that
    TipChangeRejected exceptions are properly caught and converted to appropriate
    response objects.

    Subclasses should implement do_tip_change_with_locked_branch() to perform
    the actual tip modification.
    """

    def do_with_locked_branch(self, branch, *args):
        """Execute tip change operation with proper error handling.

        Args:
            branch: The locked branch to operate on.
            *args: Additional arguments passed to the tip change method.

        Returns:
            SmartServerResponse: Result from the tip change operation, or
                FailedSmartServerResponse if TipChangeRejected is raised.
        """
        try:
            return self.do_tip_change_with_locked_branch(branch, *args)
        except errors.TipChangeRejected as e:
            msg = e.msg
            if isinstance(msg, str):
                msg = msg.encode("utf-8")
            return FailedSmartServerResponse((b"TipChangeRejected", msg))


class SmartServerBranchRequestSetConfigOption(SmartServerLockedBranchRequest):
    """Set an option in the branch configuration.

    Updates a single configuration option in the branch's configuration file.
    Requires a write lock on the branch.
    """

    def do_with_locked_branch(self, branch, value, name, section):
        """Set a configuration option value.

        Args:
            branch: The branch to update.
            value: The value to set (as bytes, will be decoded).
            name: The option name (as bytes, will be decoded).
            section: The configuration section (as bytes, will be decoded), or empty for default.

        Returns:
            SuccessfulSmartServerResponse indicating completion.
        """
        if not section:
            section = None
        branch._get_config().set_option(
            value.decode("utf-8"),
            name.decode("utf-8"),
            section.decode("utf-8") if section is not None else None,
        )
        return SuccessfulSmartServerResponse(())


class SmartServerBranchRequestSetConfigOptionDict(SmartServerLockedBranchRequest):
    """Set an option in the branch configuration using a dictionary.

    Updates a configuration option that stores dictionary values.
    The dictionary is bencoded for transmission.

    New in 2.2.
    """

    def do_with_locked_branch(self, branch, value_dict, name, section):
        """Set a dictionary configuration option.

        Args:
            branch: The branch to update.
            value_dict: Bencoded dictionary of values to set.
            name: The option name (as bytes, will be decoded).
            section: The configuration section (as bytes, will be decoded), or empty for default.

        Returns:
            SuccessfulSmartServerResponse indicating completion.
        """
        utf8_dict = bencode.bdecode(value_dict)
        value_dict = {}
        for key, value in utf8_dict.items():
            value_dict[key.decode("utf8")] = value.decode("utf8")
        section = None if not section else section.decode("utf-8")
        branch._get_config().set_option(value_dict, name.decode("utf-8"), section)
        return SuccessfulSmartServerResponse(())


class SmartServerBranchRequestSetLastRevision(SmartServerSetTipRequest):
    """Request handler for setting the branch tip revision.

    Updates the branch to point to a specific revision as its tip.
    The revision must already exist in the repository.
    """

    def do_tip_change_with_locked_branch(self, branch, new_last_revision_id):
        """Set the last revision of the branch.

        Args:
            branch: The branch to update.
            new_last_revision_id: The revision ID to set as the tip.

        Returns:
            SuccessfulSmartServerResponse on success.
            FailedSmartServerResponse if the revision doesn't exist.
        """
        if new_last_revision_id == b"null:":
            branch.set_last_revision_info(0, new_last_revision_id)
        else:
            if not branch.repository.has_revision(new_last_revision_id):
                return FailedSmartServerResponse(
                    (b"NoSuchRevision", new_last_revision_id)
                )
            branch.generate_revision_history(new_last_revision_id, None, None)
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerBranchRequestSetLastRevisionEx(SmartServerSetTipRequest):
    """Request handler for setting branch tip with advanced options.

    Provides more control over tip changes, including handling of
    divergent branches and descendant relationships.

    New in 1.6.
    """

    def do_tip_change_with_locked_branch(
        self, branch, new_last_revision_id, allow_divergence, allow_overwrite_descendant
    ):
        """Set the last revision of the branch.

        New in 1.6.

        :param new_last_revision_id: the revision ID to set as the last
            revision of the branch.
        :param allow_divergence: A flag.  If non-zero, change the revision ID
            even if the new_last_revision_id's ancestry has diverged from the
            current last revision.  If zero, a 'Diverged' error will be
            returned if new_last_revision_id is not a descendant of the current
            last revision.
        :param allow_overwrite_descendant:  A flag.  If zero and
            new_last_revision_id is not a descendant of the current last
            revision, then the last revision will not be changed.  If non-zero
            and there is no divergence, then the last revision is always
            changed.

        :returns: on success, a tuple of ('ok', revno, revision_id), where
            revno and revision_id are the new values of the current last
            revision info.  The revision_id might be different to the
            new_last_revision_id if allow_overwrite_descendant was not set.
        """
        do_not_overwrite_descendant = not allow_overwrite_descendant
        try:
            last_revno, last_rev = branch.last_revision_info()
            graph = branch.repository.get_graph()
            if not allow_divergence or do_not_overwrite_descendant:
                relation = branch._revision_relations(
                    last_rev, new_last_revision_id, graph
                )
                if relation == "diverged" and not allow_divergence:
                    return FailedSmartServerResponse((b"Diverged",))
                if relation == "a_descends_from_b" and do_not_overwrite_descendant:
                    return SuccessfulSmartServerResponse((b"ok", last_revno, last_rev))
            new_revno = graph.find_distance_to_null(
                new_last_revision_id, [(last_rev, last_revno)]
            )
            branch.set_last_revision_info(new_revno, new_last_revision_id)
        except errors.GhostRevisionsHaveNoRevno:
            return FailedSmartServerResponse((b"NoSuchRevision", new_last_revision_id))
        return SuccessfulSmartServerResponse((b"ok", new_revno, new_last_revision_id))


class SmartServerBranchRequestSetLastRevisionInfo(SmartServerSetTipRequest):
    """Request handler for setting both revision number and revision ID.

    Sets the revno and the revision ID of the specified branch. This allows
    direct control over both the revision number and ID, useful for operations
    that need to set specific revision numbers.

    New in breezy 1.4.
    """

    def do_tip_change_with_locked_branch(self, branch, new_revno, new_last_revision_id):
        """Set the branch tip to a specific revision number and ID.

        Args:
            branch: The branch to update.
            new_revno: The revision number to set (as bytes, will be converted to int).
            new_last_revision_id: The revision ID to set as the tip.

        Returns:
            SuccessfulSmartServerResponse: On success.
            FailedSmartServerResponse: If the revision doesn't exist.
        """
        try:
            branch.set_last_revision_info(int(new_revno), new_last_revision_id)
        except errors.NoSuchRevision:
            return FailedSmartServerResponse((b"NoSuchRevision", new_last_revision_id))
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerBranchRequestSetParentLocation(SmartServerLockedBranchRequest):
    """Request handler for setting a branch's parent location.

    Updates the parent branch URL, which is typically the location from which
    this branch was originally created. The parent location is used for
    operations like 'bzr missing' and 'bzr merge'.

    Takes a location to set, which must be utf8 encoded.
    """

    def do_with_locked_branch(self, branch, location):
        """Set the parent location for the branch.

        Args:
            branch: The branch to update.
            location: The parent location URL (UTF-8 encoded bytes).

        Returns:
            SuccessfulSmartServerResponse: Empty response on success.
        """
        branch._set_parent_location(location.decode("utf-8"))
        return SuccessfulSmartServerResponse(())


class SmartServerBranchRequestLockWrite(SmartServerBranchRequest):
    """Request handler for acquiring a write lock on a branch.

    Acquires write locks on both the branch and its repository,
    returning tokens that can be used to reacquire the locks.
    """

    def do_with_branch(self, branch, branch_token=b"", repo_token=b""):
        """Acquire a write lock on the branch.

        Args:
            branch: The branch to lock.
            branch_token: Optional token to reacquire an existing branch lock.
            repo_token: Optional token to reacquire an existing repository lock.

        Returns:
            SuccessfulSmartServerResponse with lock tokens on success.
            FailedSmartServerResponse on lock contention or other errors.
        """
        if branch_token == b"":
            branch_token = None
        if repo_token == b"":
            repo_token = None
        try:
            repo_token = branch.repository.lock_write(token=repo_token).repository_token
            try:
                branch_token = branch.lock_write(token=branch_token).token
            finally:
                # this leaves the repository with 1 lock
                branch.repository.unlock()
        except errors.LockContention:
            return FailedSmartServerResponse((b"LockContention",))
        except errors.TokenMismatch:
            return FailedSmartServerResponse((b"TokenMismatch",))
        except errors.UnlockableTransport:
            return FailedSmartServerResponse((b"UnlockableTransport",))
        except errors.LockFailed as e:
            return FailedSmartServerResponse(
                (b"LockFailed", str(e.lock).encode("utf-8"), str(e.why).encode("utf-8"))
            )
        if repo_token is None:
            repo_token = b""
        else:
            branch.repository.leave_lock_in_place()
        branch.leave_lock_in_place()
        branch.unlock()
        return SuccessfulSmartServerResponse((b"ok", branch_token, repo_token))


class SmartServerBranchRequestUnlock(SmartServerBranchRequest):
    """Request handler for releasing branch locks.

    Releases write locks on both the branch and its repository
    using the provided tokens.
    """

    def do_with_branch(self, branch, branch_token, repo_token):
        """Release locks on the branch.

        Args:
            branch: The branch to unlock.
            branch_token: Token for the branch lock to release.
            repo_token: Token for the repository lock to release.

        Returns:
            SuccessfulSmartServerResponse on success.
            FailedSmartServerResponse if tokens don't match.
        """
        try:
            with branch.repository.lock_write(token=repo_token):
                branch.lock_write(token=branch_token)
        except errors.TokenMismatch:
            return FailedSmartServerResponse((b"TokenMismatch",))
        if repo_token:
            branch.repository.dont_leave_lock_in_place()
        branch.dont_leave_lock_in_place()
        branch.unlock()
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerBranchRequestGetPhysicalLockStatus(SmartServerBranchRequest):
    """Request handler for checking if a branch has a physical lock.

    Returns whether the branch is currently locked at the OS/filesystem level.
    This is useful for determining if another process has an active lock on
    the branch.

    New in 2.5.
    """

    def do_with_branch(self, branch):
        """Check the physical lock status of the branch.

        Args:
            branch: The branch to check.

        Returns:
            SuccessfulSmartServerResponse: Contains "yes" if locked, "no" if not.
        """
        if branch.get_physical_lock_status():
            return SuccessfulSmartServerResponse((b"yes",))
        else:
            return SuccessfulSmartServerResponse((b"no",))


class SmartServerBranchRequestGetAllReferenceInfo(SmartServerBranchRequest):
    """Request handler for retrieving all reference information from a branch.

    Returns information about all references stored in the branch, including
    file IDs and their associated reference data. The response is bencoded
    for efficient transmission.

    New in 3.1.
    """

    def do_with_branch(self, branch):
        """Retrieve all reference information from the branch.

        Args:
            branch: The branch to query.

        Returns:
            SuccessfulSmartServerResponse: Contains "ok" status and bencoded
                reference data. The data is a list of tuples containing
                (key, file_id, reference_path) where reference_path may be empty.
        """
        all_reference_info = branch._get_all_reference_info()
        content = bencode.bencode(
            [
                (
                    key,
                    value[0].encode("utf-8"),
                    value[1].encode("utf-8") if value[1] else b"",
                )
                for (key, value) in all_reference_info.items()
            ]
        )
        return SuccessfulSmartServerResponse((b"ok",), content)

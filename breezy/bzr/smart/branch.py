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

from ... import (
    errors,
    revision as _mod_revision,
    transport as _mod_transport,
    )
from ...controldir import ControlDir
from .request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
    )


class SmartServerBranchRequest(SmartServerRequest):
    """Base class for handling common branch request logic.
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
    """Base class for handling common branch request logic for requests that
    need a write lock.
    """

    def do_with_branch(self, branch, branch_token, repo_token, *args):
        """Execute a request for a branch.

        A write lock will be acquired with the given tokens for the branch and
        repository locks.  The lock will be released once the request is
        processed.  The physical lock state won't be changed.
        """
        # XXX: write a test for LockContention
        with branch.repository.lock_write(token=repo_token), \
                branch.lock_write(token=branch_token):
            return self.do_with_locked_branch(branch, *args)


class SmartServerBranchBreakLock(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Break a branch lock.
        """
        branch.break_lock()
        return SuccessfulSmartServerResponse((b'ok', ), )


class SmartServerBranchGetConfigFile(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Return the content of branch.conf

        The body is not utf8 decoded - its the literal bytestream from disk.
        """
        try:
            content = branch.control_transport.get_bytes('branch.conf')
        except _mod_transport.NoSuchFile:
            content = b''
        return SuccessfulSmartServerResponse((b'ok', ), content)


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
        with self._branch.repository.lock_write(token=self._repo_token), \
                self._branch.lock_write(token=self._branch_token):
            self._branch.control_transport.put_bytes(
                'branch.conf', body_bytes)
        return SuccessfulSmartServerResponse((b'ok', ))


class SmartServerBranchGetParent(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Return the parent of branch."""
        parent = branch._get_parent_location() or ''
        return SuccessfulSmartServerResponse((parent.encode('utf-8'),))


class SmartServerBranchGetTagsBytes(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Return the _get_tags_bytes for a branch."""
        bytes = branch._get_tags_bytes()
        return SuccessfulSmartServerResponse((bytes,))


class SmartServerBranchSetTagsBytes(SmartServerLockedBranchRequest):

    def __init__(self, backing_transport, root_client_path='/', jail_root=None):
        SmartServerLockedBranchRequest.__init__(
            self, backing_transport, root_client_path, jail_root)
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
        self.branch._set_tags_bytes(bytes)
        return SuccessfulSmartServerResponse(())

    def do_end(self):
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

    def do_with_branch(self, branch):
        """Return the heads-to-fetch for a Branch as two bencoded lists.

        See Branch.heads_to_fetch.

        New in 2.4.
        """
        must_fetch, if_present_fetch = branch.heads_to_fetch()
        return SuccessfulSmartServerResponse(
            (list(must_fetch), list(if_present_fetch)))


class SmartServerBranchRequestGetStackedOnURL(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        stacked_on_url = branch.get_stacked_on_url()
        return SuccessfulSmartServerResponse((b'ok', stacked_on_url.encode('ascii')))


class SmartServerRequestRevisionHistory(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Get the revision history for the branch.

        The revision list is returned as the body content,
        with each revision utf8 encoded and \x00 joined.
        """
        with branch.lock_read():
            graph = branch.repository.get_graph()
            stop_revisions = (None, _mod_revision.NULL_REVISION)
            history = list(graph.iter_lefthand_ancestry(
                branch.last_revision(), stop_revisions))
        return SuccessfulSmartServerResponse(
            (b'ok', ), (b'\x00'.join(reversed(history))))


class SmartServerBranchRequestLastRevisionInfo(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Return branch.last_revision_info().

        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        revno, last_revision = branch.last_revision_info()
        return SuccessfulSmartServerResponse(
            (b'ok', str(revno).encode('ascii'), last_revision))


class SmartServerBranchRequestRevisionIdToRevno(SmartServerBranchRequest):

    def do_with_branch(self, branch, revid):
        """Return branch.revision_id_to_revno().

        New in 2.5.

        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        try:
            dotted_revno = branch.revision_id_to_dotted_revno(revid)
        except errors.NoSuchRevision:
            return FailedSmartServerResponse((b'NoSuchRevision', revid))
        except errors.GhostRevisionsHaveNoRevno as e:
            return FailedSmartServerResponse(
                (b'GhostRevisionsHaveNoRevno', e.revision_id,
                    e.ghost_revision_id))
        return SuccessfulSmartServerResponse(
            (b'ok', ) + tuple([b'%d' % x for x in dotted_revno]))


class SmartServerSetTipRequest(SmartServerLockedBranchRequest):
    """Base class for handling common branch request logic for requests that
    update the branch tip.
    """

    def do_with_locked_branch(self, branch, *args):
        try:
            return self.do_tip_change_with_locked_branch(branch, *args)
        except errors.TipChangeRejected as e:
            msg = e.msg
            if isinstance(msg, str):
                msg = msg.encode('utf-8')
            return FailedSmartServerResponse((b'TipChangeRejected', msg))


class SmartServerBranchRequestSetConfigOption(SmartServerLockedBranchRequest):
    """Set an option in the branch configuration."""

    def do_with_locked_branch(self, branch, value, name, section):
        if not section:
            section = None
        branch._get_config().set_option(
            value.decode('utf-8'), name.decode('utf-8'),
            section.decode('utf-8') if section is not None else None)
        return SuccessfulSmartServerResponse(())


class SmartServerBranchRequestSetConfigOptionDict(SmartServerLockedBranchRequest):
    """Set an option in the branch configuration.

    New in 2.2.
    """

    def do_with_locked_branch(self, branch, value_dict, name, section):
        utf8_dict = bencode.bdecode(value_dict)
        value_dict = {}
        for key, value in utf8_dict.items():
            value_dict[key.decode('utf8')] = value.decode('utf8')
        if not section:
            section = None
        else:
            section = section.decode('utf-8')
        branch._get_config().set_option(value_dict, name.decode('utf-8'), section)
        return SuccessfulSmartServerResponse(())


class SmartServerBranchRequestSetLastRevision(SmartServerSetTipRequest):

    def do_tip_change_with_locked_branch(self, branch, new_last_revision_id):
        if new_last_revision_id == b'null:':
            branch.set_last_revision_info(0, new_last_revision_id)
        else:
            if not branch.repository.has_revision(new_last_revision_id):
                return FailedSmartServerResponse(
                    (b'NoSuchRevision', new_last_revision_id))
            branch.generate_revision_history(new_last_revision_id, None, None)
        return SuccessfulSmartServerResponse((b'ok',))


class SmartServerBranchRequestSetLastRevisionEx(SmartServerSetTipRequest):

    def do_tip_change_with_locked_branch(self, branch, new_last_revision_id,
                                         allow_divergence, allow_overwrite_descendant):
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
                    last_rev, new_last_revision_id, graph)
                if relation == 'diverged' and not allow_divergence:
                    return FailedSmartServerResponse((b'Diverged',))
                if relation == 'a_descends_from_b' and do_not_overwrite_descendant:
                    return SuccessfulSmartServerResponse(
                        (b'ok', last_revno, last_rev))
            new_revno = graph.find_distance_to_null(
                new_last_revision_id, [(last_rev, last_revno)])
            branch.set_last_revision_info(new_revno, new_last_revision_id)
        except errors.GhostRevisionsHaveNoRevno:
            return FailedSmartServerResponse(
                (b'NoSuchRevision', new_last_revision_id))
        return SuccessfulSmartServerResponse(
            (b'ok', new_revno, new_last_revision_id))


class SmartServerBranchRequestSetLastRevisionInfo(SmartServerSetTipRequest):
    """Branch.set_last_revision_info.  Sets the revno and the revision ID of
    the specified branch.

    New in breezy 1.4.
    """

    def do_tip_change_with_locked_branch(self, branch, new_revno,
                                         new_last_revision_id):
        try:
            branch.set_last_revision_info(int(new_revno), new_last_revision_id)
        except errors.NoSuchRevision:
            return FailedSmartServerResponse(
                (b'NoSuchRevision', new_last_revision_id))
        return SuccessfulSmartServerResponse((b'ok',))


class SmartServerBranchRequestSetParentLocation(SmartServerLockedBranchRequest):
    """Set the parent location for a branch.

    Takes a location to set, which must be utf8 encoded.
    """

    def do_with_locked_branch(self, branch, location):
        branch._set_parent_location(location.decode('utf-8'))
        return SuccessfulSmartServerResponse(())


class SmartServerBranchRequestLockWrite(SmartServerBranchRequest):

    def do_with_branch(self, branch, branch_token=b'', repo_token=b''):
        if branch_token == b'':
            branch_token = None
        if repo_token == b'':
            repo_token = None
        try:
            repo_token = branch.repository.lock_write(
                token=repo_token).repository_token
            try:
                branch_token = branch.lock_write(
                    token=branch_token).token
            finally:
                # this leaves the repository with 1 lock
                branch.repository.unlock()
        except errors.LockContention:
            return FailedSmartServerResponse((b'LockContention',))
        except errors.TokenMismatch:
            return FailedSmartServerResponse((b'TokenMismatch',))
        except errors.UnlockableTransport:
            return FailedSmartServerResponse((b'UnlockableTransport',))
        except errors.LockFailed as e:
            return FailedSmartServerResponse((b'LockFailed',
                                              str(e.lock).encode('utf-8'), str(e.why).encode('utf-8')))
        if repo_token is None:
            repo_token = b''
        else:
            branch.repository.leave_lock_in_place()
        branch.leave_lock_in_place()
        branch.unlock()
        return SuccessfulSmartServerResponse((b'ok', branch_token, repo_token))


class SmartServerBranchRequestUnlock(SmartServerBranchRequest):

    def do_with_branch(self, branch, branch_token, repo_token):
        try:
            with branch.repository.lock_write(token=repo_token):
                branch.lock_write(token=branch_token)
        except errors.TokenMismatch:
            return FailedSmartServerResponse((b'TokenMismatch',))
        if repo_token:
            branch.repository.dont_leave_lock_in_place()
        branch.dont_leave_lock_in_place()
        branch.unlock()
        return SuccessfulSmartServerResponse((b'ok',))


class SmartServerBranchRequestGetPhysicalLockStatus(SmartServerBranchRequest):
    """Get the physical lock status for a branch.

    New in 2.5.
    """

    def do_with_branch(self, branch):
        if branch.get_physical_lock_status():
            return SuccessfulSmartServerResponse((b'yes',))
        else:
            return SuccessfulSmartServerResponse((b'no',))


class SmartServerBranchRequestGetAllReferenceInfo(SmartServerBranchRequest):
    """Get the reference information.

    New in 3.1.
    """

    def do_with_branch(self, branch):
        all_reference_info = branch._get_all_reference_info()
        content = bencode.bencode([
            (key, value[0].encode('utf-8'), value[1].encode('utf-8') if value[1] else b'')
            for (key, value) in all_reference_info.items()])
        return SuccessfulSmartServerResponse((b'ok', ), content)

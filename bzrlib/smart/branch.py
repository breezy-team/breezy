# Copyright (C) 2006 Canonical Ltd
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

"""Server-side branch related request implmentations."""


from bzrlib import errors
from bzrlib.bzrdir import BzrDir
from bzrlib.smart.request import (
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
        bzrdir = BzrDir.open_from_transport(transport)
        if bzrdir.get_branch_reference() is not None:
            raise errors.NotBranchError(transport.base)
        branch = bzrdir.open_branch()
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
        branch.repository.lock_write(token=repo_token)
        try:
            branch.lock_write(token=branch_token)
            try:
                return self.do_with_locked_branch(branch, *args)
            finally:
                branch.unlock()
        finally:
            branch.repository.unlock()


class SmartServerBranchGetConfigFile(SmartServerBranchRequest):
    
    def do_with_branch(self, branch):
        """Return the content of branch.conf
        
        The body is not utf8 decoded - its the literal bytestream from disk.
        """
        # This was at one time called by RemoteBranchLockableFiles
        # intercepting access to this file; as of 1.5 it is not called by the
        # client but retained for compatibility.  It may be called again to
        # allow the client to get the configuration without needing vfs
        # access.
        try:
            content = branch._transport.get_bytes('branch.conf')
        except errors.NoSuchFile:
            content = ''
        return SuccessfulSmartServerResponse( ('ok', ), content)


class SmartServerRequestRevisionHistory(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Get the revision history for the branch.

        The revision list is returned as the body content,
        with each revision utf8 encoded and \x00 joined.
        """
        return SuccessfulSmartServerResponse(
            ('ok', ), ('\x00'.join(branch.revision_history())))


class SmartServerBranchRequestLastRevisionInfo(SmartServerBranchRequest):
    
    def do_with_branch(self, branch):
        """Return branch.last_revision_info().
        
        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        revno, last_revision = branch.last_revision_info()
        return SuccessfulSmartServerResponse(('ok', str(revno), last_revision))


class SmartServerSetTipRequest(SmartServerLockedBranchRequest):
    """Base class for handling common branch request logic for requests that
    update the branch tip.
    """

    def do_with_locked_branch(self, branch, *args):
        try:
            return self.do_tip_change_with_locked_branch(branch, *args)
        except errors.TipChangeRejected, e:
            msg = e.msg
            if isinstance(msg, unicode):
                msg = msg.encode('utf-8')
            return FailedSmartServerResponse(('TipChangeRejected', msg))


class SmartServerBranchRequestSetLastRevision(SmartServerSetTipRequest):
    
    def do_tip_change_with_locked_branch(self, branch, new_last_revision_id):
        if new_last_revision_id == 'null:':
            branch.set_revision_history([])
        else:
            if not branch.repository.has_revision(new_last_revision_id):
                return FailedSmartServerResponse(
                    ('NoSuchRevision', new_last_revision_id))
            branch.generate_revision_history(new_last_revision_id)
        return SuccessfulSmartServerResponse(('ok',))


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
                    return FailedSmartServerResponse(('Diverged',))
                if relation == 'a_descends_from_b' and do_not_overwrite_descendant:
                    return SuccessfulSmartServerResponse(
                        ('ok', last_revno, last_rev))
            new_revno = graph.find_distance_to_null(
                new_last_revision_id, [(last_rev, last_revno)])
            branch.set_last_revision_info(new_revno, new_last_revision_id)
        except errors.GhostRevisionsHaveNoRevno:
            return FailedSmartServerResponse(
                ('NoSuchRevision', new_last_revision_id))
        return SuccessfulSmartServerResponse(
            ('ok', new_revno, new_last_revision_id))


class SmartServerBranchRequestSetLastRevisionInfo(SmartServerSetTipRequest):
    """Branch.set_last_revision_info.  Sets the revno and the revision ID of
    the specified branch.

    New in bzrlib 1.4.
    """
    
    def do_tip_change_with_locked_branch(self, branch, new_revno,
            new_last_revision_id):
        try:
            branch.set_last_revision_info(int(new_revno), new_last_revision_id)
        except errors.NoSuchRevision:
            return FailedSmartServerResponse(
                ('NoSuchRevision', new_last_revision_id))
        return SuccessfulSmartServerResponse(('ok',))


class SmartServerBranchRequestLockWrite(SmartServerBranchRequest):
    
    def do_with_branch(self, branch, branch_token='', repo_token=''):
        if branch_token == '':
            branch_token = None
        if repo_token == '':
            repo_token = None
        try:
            repo_token = branch.repository.lock_write(token=repo_token)
            try:
                branch_token = branch.lock_write(token=branch_token)
            finally:
                # this leaves the repository with 1 lock
                branch.repository.unlock()
        except errors.LockContention:
            return FailedSmartServerResponse(('LockContention',))
        except errors.TokenMismatch:
            return FailedSmartServerResponse(('TokenMismatch',))
        except errors.UnlockableTransport:
            return FailedSmartServerResponse(('UnlockableTransport',))
        except errors.LockFailed, e:
            return FailedSmartServerResponse(('LockFailed', str(e.lock), str(e.why)))
        if repo_token is None:
            repo_token = ''
        else:
            branch.repository.leave_lock_in_place()
        branch.leave_lock_in_place()
        branch.unlock()
        return SuccessfulSmartServerResponse(('ok', branch_token, repo_token))


class SmartServerBranchRequestUnlock(SmartServerBranchRequest):

    def do_with_branch(self, branch, branch_token, repo_token):
        try:
            branch.repository.lock_write(token=repo_token)
            try:
                branch.lock_write(token=branch_token)
            finally:
                branch.repository.unlock()
        except errors.TokenMismatch:
            return FailedSmartServerResponse(('TokenMismatch',))
        if repo_token:
            branch.repository.dont_leave_lock_in_place()
        branch.dont_leave_lock_in_place()
        branch.unlock()
        return SuccessfulSmartServerResponse(('ok',))
        

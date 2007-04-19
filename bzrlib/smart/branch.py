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
from bzrlib.revision import NULL_REVISION
from bzrlib.smart.request import SmartServerRequest, SmartServerResponse


class SmartServerBranchRequest(SmartServerRequest):
    """Base class for handling common branch request logic."""

    def do(self, path, *args):
        """Execute a request for a branch at path.

        If the branch is a branch reference, NotBranchError is raised.
        """
        transport = self._backing_transport.clone(path)
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
        """Return the content of branch.control_files.get('branch.conf').
        
        The body is not utf8 decoded - its the literal bytestream from disk.
        """
        try:
            content = branch.control_files.get('branch.conf').read()
        except errors.NoSuchFile:
            content = ''
        return SmartServerResponse( ('ok', ), content)


class SmartServerRequestRevisionHistory(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Get the revision history for the branch.

        The revision list is returned as the body content,
        with each revision utf8 encoded and \x00 joined.
        """
        return SmartServerResponse(
            ('ok', ), ('\x00'.join(branch.revision_history())))


class SmartServerBranchRequestLastRevisionInfo(SmartServerBranchRequest):
    
    def do_with_branch(self, branch):
        """Return branch.last_revision_info().
        
        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        revno, last_revision = branch.last_revision_info()
        return SmartServerResponse(('ok', str(revno), last_revision))


class SmartServerBranchRequestSetLastRevision(SmartServerLockedBranchRequest):
    
    def do_with_locked_branch(self, branch, new_last_revision_id):
        if new_last_revision_id == 'null:':
            branch.set_revision_history([])
        else:
            if not branch.repository.has_revision(new_last_revision_id):
                return SmartServerResponse(
                    ('NoSuchRevision', new_last_revision_id))
            branch.generate_revision_history(new_last_revision_id)
        return SmartServerResponse(('ok',))


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
                branch.repository.unlock()
        except errors.LockContention:
            return SmartServerResponse(('LockContention',))
        except errors.TokenMismatch:
            return SmartServerResponse(('TokenMismatch',))
        except errors.UnlockableTransport:
            return SmartServerResponse(('UnlockableTransport',))
        branch.repository.leave_lock_in_place()
        branch.leave_lock_in_place()
        branch.unlock()
        return SmartServerResponse(('ok', branch_token, repo_token))


class SmartServerBranchRequestUnlock(SmartServerBranchRequest):

    def do_with_branch(self, branch, branch_token, repo_token):
        try:
            branch.repository.lock_write(token=repo_token)
            try:
                branch.lock_write(token=branch_token)
            finally:
                branch.repository.unlock()
        except errors.TokenMismatch:
            return SmartServerResponse(('TokenMismatch',))
        branch.repository.dont_leave_lock_in_place()
        branch.dont_leave_lock_in_place()
        branch.unlock()
        return SmartServerResponse(('ok',))
        

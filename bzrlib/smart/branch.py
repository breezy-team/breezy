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

    def do(self, path):
        """Execute a request for a branch at path.

        If the branch is a branch reference, NotBranchError is raised.
        """
        transport = self._backing_transport.clone(path)
        bzrdir = BzrDir.open_from_transport(transport)
        if bzrdir.get_branch_reference() is not None:
            raise errors.NotBranchError(transport.base)
        branch = bzrdir.open_branch()
        return self.do_with_branch(branch)


class SmartServerRequestRevisionHistory(SmartServerBranchRequest):

    def do_with_branch(self, branch):
        """Get the revision history for the branch.

        The revision list is returned as the body content,
        with each revision utf8 encoded and \x00 joined.
        """
        return SmartServerResponse(('ok', ),
            ('\x00'.join(branch.revision_history())).encode('utf8'))


class SmartServerBranchRequestLastRevisionInfo(SmartServerBranchRequest):
    
    def do_with_branch(self, branch):
        """Return branch.last_revision_info().
        
        The revno is encoded in decimal, the revision_id is encoded as utf8.
        """
        revno, last_revision = branch.last_revision_info()
        if last_revision == NULL_REVISION:
            last_revision = ''
        return SmartServerResponse(
            ('ok', str(revno), last_revision.encode('utf8')))



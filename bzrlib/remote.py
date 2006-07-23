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


from bzrlib import branch, errors, repository
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.branch import Branch, BranchFormat
from bzrlib.trace import mutter
from bzrlib.transport.smart import SmartTransport


class RemoteBzrDirFormat(BzrDirFormat):
    """Format representing bzrdirs accessed via a smart server"""
    
    def probe_transport(self, transport):
        mutter("%r probe for bzrdir in %r" % (self, transport))
        if isinstance(transport, SmartTransport):
            return self
        else:
            raise errors.NoSmartServer(transport.base)

    def _open(self, transport):
        return RemoteBzrDir(transport)


class RemoteBzrDir(BzrDir):
    """Control directory on a remote server, accessed by HPSS."""

    def __init__(self, transport):
        BzrDir.__init__(self, transport, RemoteBzrDirFormat)
        self.client = transport.get_smart_client()
        # this object holds a delegated bzrdir that uses file-level operations
        # to talk to the other side
        self._real_bzrdir = BzrDirFormat.get_default_format().open(transport, _found=True)
        self._repository = None
        self._branch = None

    def open_repository(self):
        # OK just very fake response for now
        if not self._repository:
            self._repository = self._real_bzrdir.open_repository()
        return self._repository

    def open_branch(self):
        # Very fake - use file-level transport
        return RemoteBranch(self, self.client)

    def get_branch_transport(self, branch_format):
        return self._real_bzrdir.get_branch_transport(branch_format)


class RemoteRepositoryFormat(repository.RepositoryFormatKnit1):
    """Format for repositories accessed over rpc.

    Instances of this repository are represented by RemoteRepository 
    instances.
    """

    _matchingbzrdir = RemoteBzrDirFormat


class RemoteRepository(repository.Repository):
    """Repository accessed over rpc.

    For the moment everything is delegated to IO-like operations over 
    the transport.
    """



class RemoteBranchFormat(branch.BranchFormat):

    def open(self, a_bzrdir):
        return RemoteBranch(a_bzrdir, a_bzrdir.client)


class RemoteBranch(branch.Branch):
    """Branch stored on a server accessed by HPSS RPC.

    At the moment most operations are mapped down to simple file operations.
    """

    def __init__(self, my_bzrdir, smart_client):
        self.bzrdir = my_bzrdir
        self.client = smart_client
        self.transport = my_bzrdir.transport
        self.repository = self.bzrdir.open_repository()
        real_format = BranchFormat.get_default_format()
        self._real_branch = real_format.open(my_bzrdir, _found=True)

    def lock_read(self):
        pass

    def unlock(self):
        # TODO: implement write locking, passed through to the other end?  Or
        # perhaps we should not lock but rather do higher-level operations?
        pass

    def revision_history(self):
        return self._real_branch.revision_history()


# when first loaded, register this format.
#
# TODO: Actually this needs to be done earlier; we can hold off on loading
# this code until it's needed though.

# We can't use register_control_format because it adds it at a lower priority
# than the existing branches, whereas this should take priority.
BzrDirFormat._control_formats.insert(0, RemoteBzrDirFormat())

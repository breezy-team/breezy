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

# TODO: At some point, handle upgrades by just passing the whole request
# across to run on the server.


from bzrlib import branch, errors, repository
from bzrlib.bzrdir import BzrDir, BzrDirFormat, RemoteBzrDirFormat
from bzrlib.branch import Branch, BranchFormat
from bzrlib.trace import mutter

# Note: RemoteBzrDirFormat is in bzrdir.py

class RemoteBzrDir(BzrDir):
    """Control directory on a remote server, accessed by HPSS."""

    def __init__(self, transport):
        BzrDir.__init__(self, transport, RemoteBzrDirFormat())
        self.client = transport.get_smart_client()
        # this object holds a delegated bzrdir that uses file-level operations
        # to talk to the other side
        # XXX: We should go into find_format, but not allow it to find
        # RemoteBzrDirFormat and make sure it finds the real underlying format.
        
        default_format = BzrDirFormat.get_default_format()
        self._real_bzrdir = default_format.open(transport, _found=True)
        self._real_bzrdir._format.probe_transport(transport)
        self._branch = None

    def create_repository(self, shared=False):
        return RemoteRepository(
            self, self._real_bzrdir.create_repository(shared=shared))

    def create_branch(self):
        real_branch = self._real_bzrdir.create_branch()
        real_repository = real_branch.repository
        remote_repository = RemoteRepository(self, real_repository)
        return RemoteBranch(self, remote_repository, real_branch)

    def create_workingtree(self, revision_id=None):
        real_workingtree = self._real_bzrdir.create_workingtree(revision_id=revision_id)
        return RemoteWorkingTree(self, real_workingtree)

    def open_repository(self):
        return RemoteRepository(self, self._real_bzrdir.open_repository())

    def open_branch(self, _unsupported=False):
        real_branch = self._real_bzrdir.open_branch(unsupported=_unsupported)
        if real_branch.bzrdir is self._real_bzrdir:
            # This branch accessed through the smart server, so wrap the
            # file-level objects.
            real_repository = real_branch.repository
            remote_repository = RemoteRepository(self, real_repository)
            return RemoteBranch(self, remote_repository, real_branch)
        else:
            # We were redirected to somewhere else, so don't wrap.
            return real_branch

    def open_workingtree(self):
        return RemoteWorkingTree(self, self._real_bzrdir.open_workingtree())

    def get_branch_transport(self, branch_format):
        return self._real_bzrdir.get_branch_transport(branch_format)

    def get_repository_transport(self, repository_format):
        return self._real_bzrdir.get_repository_transport(repository_format)

    def get_workingtree_transport(self, workingtree_format):
        return self._real_bzrdir.get_workingtree_transport(workingtree_format)

    def can_convert_format(self):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False

    def needs_format_conversion(self, format=None):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False


class RemoteRepositoryFormat(repository.RepositoryFormat):
    """Format for repositories accessed over rpc.

    Instances of this repository are represented by RemoteRepository
    instances.
    """

    _matchingbzrdir = RemoteBzrDirFormat

    def initialize(self, a_bzrdir, shared=False):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.create_repository(shared=shared)
    
    def open(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.open_repository()

    def get_format_description(self):
        return 'bzr remote repository'

    def __eq__(self, other):
        return self.__class__ == other.__class__

    rich_root_data = False


class RemoteRepository(object):
    """Repository accessed over rpc.

    For the moment everything is delegated to IO-like operations over
    the transport.
    """

    def __init__(self, remote_bzrdir, real_repository):
        self.real_repository = real_repository
        self.bzrdir = remote_bzrdir
        self._format = RemoteRepositoryFormat()

    def __getattr__(self, name):
        # XXX: temporary way to lazily delegate everything to the real
        # repository
        return getattr(self.real_repository, name)


class RemoteBranchFormat(branch.BranchFormat):

    def open(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.open_branch()

    def initialize(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.create_branch()


class RemoteBranch(branch.Branch):
    """Branch stored on a server accessed by HPSS RPC.

    At the moment most operations are mapped down to simple file operations.
    """

    def __init__(self, remote_bzrdir, remote_repository, real_branch):
        self.bzrdir = remote_bzrdir
        self.transport = remote_bzrdir.transport
        self.repository = remote_repository
        self._real_branch = real_branch
        self._format = RemoteBranchFormat()

    def lock_read(self):
        return self._real_branch.lock_read()

    def lock_write(self):
        return self._real_branch.lock_write()

    def unlock(self):
        return self._real_branch.unlock()

    def break_lock(self):
        return self._real_branch.break_lock()

    def revision_history(self):
        return self._real_branch.revision_history()

    def set_revision_history(self, rev_history):
        return self._real_branch.set_revision_history(rev_history)

    def get_parent(self):
        return self._real_branch.get_parent()
        
    def set_parent(self, url):
        return self._real_branch.set_parent(url)
        

class RemoteWorkingTree(object):

    def __init__(self, remote_bzrdir, real_workingtree):
        self.real_workingtree = real_workingtree
        self.bzrdir = remote_bzrdir

    def __getattr__(self, name):
        # XXX: temporary way to lazily delegate everything to the real
        # workingtree
        return getattr(self.real_workingtree, name)



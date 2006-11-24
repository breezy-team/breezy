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

from urlparse import urlparse

from bzrlib import branch, errors, repository
from bzrlib.bzrdir import BzrDir, BzrDirFormat, RemoteBzrDirFormat
from bzrlib.branch import BranchReferenceFormat
from bzrlib.smart import client, vfs
from bzrlib.urlutils import unescape

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
        
        # THIS IS A COMPLETE AND UTTER LIE.
        # XXX: XXX: XXX: must be removed before merging to mainline
        # SMART_SERVER_MERGE_BLOCKER
        default_format = BzrDirFormat.get_default_format()
        self._real_bzrdir = default_format.open(transport, _found=True)
        path = self._path_for_remote_call()
        #self._real_bzrdir._format.probe_transport(transport)
        response = client.SmartClient(self.client).call('probe_dont_use', path)
        if response == ('no',):
            raise errors.NotBranchError(path=transport.base)
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

    def open_branch(self, _unsupported=False):
        assert _unsupported == False, 'unsupported flag support not implemented yet.'
        path = self._path_for_remote_call()
        response = client.SmartClient(self.client).call('BzrDir.open_branch', path)
        assert response[0] == 'ok', 'unexpected response code %s' % response[0]
        if response[0] != 'ok':
            # this should probably be a regular translate no ?
            raise errors.NotBranchError(path=self.root_transport.base)
        if response[1] == '':
            # branch at this location.
            if vfs.vfs_enabled():
                # if the VFS is enabled, create a local object using the VFS.
                real_branch = self._real_bzrdir.open_branch(unsupported=_unsupported)
                # This branch accessed through the smart server, so wrap the
                # file-level objects.
                real_repository = real_branch.repository
                remote_repository = RemoteRepository(self, real_repository)
                return RemoteBranch(self, remote_repository, real_branch)
            else:
                # otherwise just create a proxy for the branch.
                return RemoteBranch(self, self.find_repository())
        else:
            # a branch reference, use the existing BranchReference logic.
            format = BranchReferenceFormat()
            return format.open(self, _found=True, location=response[1])

    def open_repository(self):
        path = self._path_for_remote_call()
        response = client.SmartClient(self.client).call('BzrDir.find_repository', path)
        assert response[0] == 'ok', 'unexpected response code %s' % response[0]
        if response[1] == '':
            if vfs.vfs_enabled():
                return RemoteRepository(self, self._real_bzrdir.open_repository())
            else:
                return RemoteRepository(self)
        else:
            raise errors.NoRepositoryPresent(self)

    def open_workingtree(self):
        return RemoteWorkingTree(self, self._real_bzrdir.open_workingtree())

    def _path_for_remote_call(self):
        """Return the path to be used for this bzrdir in a remote call."""
        return unescape(urlparse(self.root_transport.base)[2])

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

    def __init__(self, remote_bzrdir, real_repository=None):
        """Create a RemoteRepository instance.
        
        :param remote_bzrdir: The bzrdir hosting this repository.
        :param real_repository: If not None, a local implementation of the
            repository logic for the repository, usually accessing the data
            via the VFS.
        """
        if real_repository:
            self._real_repository = real_repository
        self.bzrdir = remote_bzrdir
        self._format = RemoteRepositoryFormat()


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

    def __init__(self, remote_bzrdir, remote_repository, real_branch=None):
        """Create a RemoteBranch instance.

        :param real_branch: An optional local implementation of the branch
            format, usually accessing the data via the VFS.
        """
        self.bzrdir = remote_bzrdir
        self._client = client.SmartClient(self.bzrdir.client)
        self.repository = remote_repository
        if real_branch is not None:
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
        """See Branch.revision_history()."""
        # XXX: TODO: this does not cache the revision history for the duration
        # of a lock, which is a bug - see the code for regular branches
        # for details.
        path = self.bzrdir._path_for_remote_call()
        response = self._client.call2('Branch.revision_history', path)
        assert response[0][0] == 'ok', 'unexpected response code %s' % response[0]
        result = response[1].read_body_bytes().decode('utf8').split('\x00')
        if result == ['']:
            return []
        return result

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



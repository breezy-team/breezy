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


from bzrlib import bzrdir, branch, errors, repository
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.branch import Branch, BranchFormat
from bzrlib.trace import mutter
from bzrlib.transport.smart import SmartTransport


class RemoteBzrDirFormat(bzrdir.BzrDirMetaFormat1):
    """Format representing bzrdirs accessed via a smart server"""

    def get_format_description(self):
        return 'bzr remote bzrdir'
    
    def probe_transport(self, transport):
        ## mutter("%r probe for bzrdir in %r" % (self, transport))
        try:
            transport.get_smart_client()
        except (NotImplementedError, AttributeError,
                errors.TransportNotPossible):
            raise errors.NoSmartServer(transport.base)
        else:
            return self

    def _open(self, transport):
        return RemoteBzrDir(transport)

    def __eq__(self, other):
        return self.get_format_description() == other.get_format_description()


class RemoteBzrDir(BzrDir):
    """Control directory on a remote server, accessed by HPSS."""

    def __init__(self, transport):
        BzrDir.__init__(self, transport, RemoteBzrDirFormat())
        self.client = transport.get_smart_client()
        # this object holds a delegated bzrdir that uses file-level operations
        # to talk to the other side
        # XXX: We should go into find_format, but not allow it to find
        # RemoteBzrDirFormat and make sure it finds the real underlying format.
        ##import pdb; pdb.set_trace()
        
        self._real_bzrdir = BzrDirFormat.get_default_format().open(transport, _found=True)
        self._real_bzrdir._format.probe_transport(transport)
        self._branch = None

    def create_repository(self, shared=False):
        return RemoteRepository(self._real_bzrdir.create_repository(shared=shared), self)

    def create_branch(self):
        self._real_bzrdir.create_branch()
        return self.open_branch()

    def create_workingtree(self, revision_id=None):
        self._real_bzrdir.create_workingtree(revision_id=revision_id)
        return self.open_workingtree()

    def open_repository(self):
        return RemoteRepository.open(self._real_bzrdir.open_repository(), self)

    def open_branch(self):
        format = RemoteBranchFormat.find_format(self)
        return RemoteBranchFormat().open(self)

    def open_workingtree(self):
        return RemoteWorkingTree.open(self._real_bzrdir.open_workingtree(), self)

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
        real_format = repository.RepositoryFormatKnit1()
        real_repo = real_format.initialize(a_bzrdir, shared=shared)
        return RemoteRepository.open(real_repo, a_bzrdir)
    
    def open(self, a_bzrdir):
        real_format = repository.RepositoryFormatKnit1()
        real_repo = real_format.open(a_bzrdir)
        return RemoteRepository.open(real_repo, a_bzrdir)

    def get_format_description(self):
        return 'bzr remote repository'

    def __eq__(self, other):
        return self.get_format_description() == other.get_format_description()


class RemoteRepository(object):
    """Repository accessed over rpc.

    For the moment everything is delegated to IO-like operations over
    the transport.
    """

    def __init__(self, real_repository, remote_bzrdir):
        self.real_repository = real_repository
        self.bzrdir = remote_bzrdir
        self._format = RemoteRepositoryFormat()

    @classmethod
    def open(cls, real_repository, remote_bzrdir):
        return cls(real_repository, remote_bzrdir)

    def __getattr__(self, name):
        # XXX: temporary way to lazily delegate everything to the real
        # repository
        return getattr(self.real_repository, name)


class RemoteBranchFormat(branch.BranchFormat):

    @classmethod
    def find_format(cls, a_bzrdir):
        BranchFormat.find_format(a_bzrdir._real_bzrdir)
        return cls.open(cls(), a_bzrdir)
    
    def open(self, a_bzrdir):
        return RemoteBranch(a_bzrdir,
                            _repository=a_bzrdir.open_repository())

    def initialize(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.create_branch()


class RemoteBranch(branch.Branch):
    """Branch stored on a server accessed by HPSS RPC.

    At the moment most operations are mapped down to simple file operations.
    """

    def __init__(self, my_bzrdir, _repository=None):
        self.bzrdir = my_bzrdir
        self.transport = my_bzrdir.transport
        self.repository = _repository
        # XXX: Should be possible to open things other than the default format.
        real_format = BranchFormat.get_default_format()
        self._real_branch = real_format.open(my_bzrdir, _found=True)
        self._format = RemoteBranchFormat()

    @classmethod
    def open(cls, my_bzrdir):
        return cls(my_bzrdir)

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

    def __init__(self, real_workingtree, remote_bzrdir):
        self.real_workingtree = real_workingtree
        self.bzrdir = remote_bzrdir

    @classmethod
    def open(cls, real_workingtree, remote_bzrdir):
        return cls(real_workingtree, remote_bzrdir)

    def __getattr__(self, name):
        # XXX: temporary way to lazily delegate everything to the real
        # workingtree
        return getattr(self.real_workingtree, name)


# when first loaded, register this format.
#
# TODO: Actually this needs to be done earlier; we can hold off on loading
# this code until it's needed though.

# We can't use register_control_format because it adds it at a lower priority
# than the existing branches, whereas this should take priority.
BzrDirFormat._control_formats.insert(0, RemoteBzrDirFormat())

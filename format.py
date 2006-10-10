# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.bzrdir import BzrDirFormat, BzrDir
from bzrlib.errors import NotBranchError, NotLocalUrl, NoRepositoryPresent
from bzrlib.lockable_files import TransportLock
from bzrlib.progress import ProgressBar
from bzrlib.transport.local import LocalTransport
import bzrlib.urlutils as urlutils

from svn.core import SubversionException
import svn.core, svn.repos

from branch import SvnBranch
from repository import SvnRepository
from scheme import BranchingScheme
from transport import SvnRaTransport, bzr_to_svn_url, svn_to_bzr_url


class SvnRemoteAccess(BzrDir):
    """BzrDir implementation for Subversion connections.
    
    This is used for all non-checkout connections 
    to Subversion repositories.
    """
    def __init__(self, _transport, _format, scheme=None):
        """See BzrDir.__init__()."""
        super(SvnRemoteAccess, self).__init__(_transport, _format)

        self.transport = None
        self.svn_root_transport = _transport.get_root()

        svn_url = bzr_to_svn_url(self.root_transport.base)
        root_svn_url = bzr_to_svn_url(self.svn_root_transport.base)

        assert svn_url.startswith(root_svn_url)
        self.branch_path = svn_url[len(root_svn_url):]

        if scheme is None:
            self.scheme = BranchingScheme.guess_scheme(self.branch_path)
        else:
            self.scheme = scheme

        if (not self.scheme.is_branch(self.branch_path) and 
                self.branch_path != ""):
            raise NotBranchError(path=self.root_transport.base)

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        """See BzrDir.clone().

        Not supported on Subversion connections.
        """
        raise NotImplementedError(SvnRemoteAccess.clone)

    def sprout(self, url, revision_id=None, basis=None, force_new_repo=False):
        """See BzrDir.sprout()."""
        result = BzrDirFormat.get_default_format().initialize(url)
        repo = self.open_repository()
        if force_new_repo:
            result_repo = repo.clone(result, revision_id, basis)
        else:
            try:
                result_repo = result.find_repository()
                result_repo.fetch(repo, revision_id=revision_id, 
                                  pb=ProgressBar())
            except NoRepositoryPresent:
                result_repo = repo.clone(result, revision_id, basis)

        branch = self.open_branch()
        branch.sprout(result, revision_id)
        result.create_workingtree()
        return result

    def open_repository(self):
        """Open the repository associated with this BzrDir.
        
        :return: instance of SvnRepository.
        """
        repos = SvnRepository(self, self.svn_root_transport)
        repos._format = self._format
        return repos

    # Subversion has all-in-one, so a repository is always present,
    # no need to look for it.
    find_repository = open_repository

    def open_workingtree(self):
        """See BzrDir.open_workingtree().

        Will always raise NotLocalUrl as this 
        BzrDir can not be associated with working trees.
        """
        # Working trees never exist on remote Subversion repositories
        raise NotLocalUrl(self.root_transport.base)

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree().

        Will always raise NotLocalUrl as this 
        BzrDir can not be associated with working trees.
        """
        raise NotLocalUrl(self.root_transport.base)

    def create_branch(self):
        """See BzrDir.create_branch()."""
        repos = self.open_repository()
        # TODO: Check if there are any revisions in this repository 
        # yet if it is the top-level one
        branch = SvnBranch(self.root_transport.base, repos, self.branch_path)
        branch.bzrdir = self
        return branch

    def open_branch(self, unsupported=True):
        """See BzrDir.open_branch()."""

        if not self.scheme.is_branch(self.branch_path):
            raise NotBranchError(path=self.root_transport.base)

        repos = self.open_repository()

        branch = SvnBranch(self.root_transport.base, repos, self.branch_path)
 
        branch.bzrdir = self
        return branch


class SvnFormat(BzrDirFormat):
    _lock_class = TransportLock

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        if isinstance(transport, SvnRaTransport):
            return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        return SvnRemoteAccess(transport, self)

    def get_format_string(self):
        return 'Subversion Smart Server'

    def get_format_description(self):
        return 'Subversion Smart Server'

    def initialize_on_transport(self, transport):
        """See BzrDir.initialize_on_transport()."""
        if not isinstance(transport, LocalTransport):
            raise NotImplementedError(self.initialize, 
                "Can't create Subversion Repositories/branches on "
                "non-local transports")

        local_path = transport._local_base.rstrip("/")
        repos = svn.repos.create(local_path, '', '', None, None)
        return self.open(SvnRaTransport(svn_to_bzr_url(transport.base)), _found=True)

    def is_supported(self):
        """See BzrDir.is_supported()."""
        return True

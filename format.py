# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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
"""Subversion BzrDir formats."""

from bzrlib import urlutils
from bzrlib.bzrdir import BzrDirFormat, BzrDir, format_registry
from bzrlib.errors import (NotBranchError, NotLocalUrl, NoRepositoryPresent,
                           NoWorkingTree, AlreadyBranchError)
from bzrlib.lockable_files import TransportLock
from bzrlib.transport.local import LocalTransport

from svn.core import SubversionException
import svn.core, svn.repos

from errors import NoSvnRepositoryPresent
from repository import SvnRepository
from transport import SvnRaTransport, bzr_to_svn_url, get_svn_ra_transport

def get_rich_root_format():
    format = BzrDirFormat.get_default_format()
    if format.repository_format.rich_root_data:
        return format
    # Default format does not support rich root data, 
    # fall back to dirstate-with-subtree
    format = format_registry.make_bzrdir('dirstate-with-subtree')
    assert format.repository_format.rich_root_data
    return format


class SvnRemoteAccess(BzrDir):
    """BzrDir implementation for Subversion connections.
    
    This is used for all non-checkout connections 
    to Subversion repositories.
    """
    def __init__(self, _transport, _format):
        """See BzrDir.__init__()."""
        _transport = get_svn_ra_transport(_transport)
        self._format = _format
        self.transport = None
        self.root_transport = _transport

        svn_url = bzr_to_svn_url(self.root_transport.base)
        self.svn_root_url = _transport.get_repos_root()

        assert svn_url.startswith(self.svn_root_url)
        self.branch_path = svn_url[len(self.svn_root_url):]

    def clone(self, url, revision_id=None, force_new_repo=False):
        """See BzrDir.clone().

        Not supported on Subversion connections.
        """
        raise NotImplementedError(SvnRemoteAccess.clone)

    def sprout(self, url, revision_id=None, force_new_repo=False,
            recurse='down', possible_transports=None):
        """See BzrDir.sprout()."""
        # FIXME: Use possible_transports
        # FIXME: Use recurse
        format = get_rich_root_format()
        result = format.initialize(url)
        repo = self.find_repository()
        if force_new_repo:
            result_repo = repo.clone(result, revision_id)
        else:
            try:
                result_repo = result.find_repository()
                result_repo.fetch(repo, revision_id=revision_id)
            except NoRepositoryPresent:
                result_repo = repo.clone(result, revision_id)
        branch = self.open_branch()
        result_branch = branch.sprout(result, revision_id)
        if result_branch.repository.make_working_trees():
            result.create_workingtree()
        return result

    def open_repository(self, _unsupported=False):
        """Open the repository associated with this BzrDir.
        
        :return: instance of SvnRepository.
        """
        if self.branch_path == "":
            return SvnRepository(self, self.root_transport)
        raise NoSvnRepositoryPresent(self.root_transport.base)

    def find_repository(self):
        """Open the repository associated with this BzrDir.
        
        :return: instance of SvnRepository.
        """
        transport = self.root_transport
        if self.svn_root_url != transport.base:
            transport = transport.clone_root()
        return SvnRepository(self, transport, self.branch_path)

    def open_workingtree(self, _unsupported=False,
            recommend_upgrade=True):
        """See BzrDir.open_workingtree().

        Will always raise NotLocalUrl as this 
        BzrDir can not be associated with working trees.
        """
        # Working trees never exist on remote Subversion repositories
        raise NoWorkingTree(self.root_transport.base)

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree().

        Will always raise NotLocalUrl as this 
        BzrDir can not be associated with working trees.
        """
        raise NotLocalUrl(self.root_transport.base)

    def needs_format_conversion(self, format=None):
        """See BzrDir.needs_format_conversion()."""
        # if the format is not the same as the system default,
        # an upgrade is needed.
        if format is None:
            format = BzrDirFormat.get_default_format()
        return not isinstance(self._format, format.__class__)

    def import_branch(self, source, stop_revision=None):
        """Create a new branch in this repository, possibly 
        with the specified history, optionally importing revisions.
        
        :param source: Source branch
        :param stop_revision: Tip of new branch
        :return: Branch object
        """
        from commit import push_new
        if stop_revision is None:
            stop_revision = source.last_revision()
        target_branch_path = self.branch_path.strip("/")
        repos = self.find_repository()
        full_branch_url = urlutils.join(repos.transport.base, 
                                        target_branch_path)
        if repos.transport.check_path(target_branch_path,
            repos.transport.get_latest_revnum()) != svn.core.svn_node_none:
            raise AlreadyBranchError(full_branch_url)
        push_new(repos, target_branch_path, source, stop_revision)
        branch = self.open_branch()
        branch.pull(source, stop_revision=stop_revision)
        return branch

    def create_branch(self):
        """See BzrDir.create_branch()."""
        from branch import SvnBranch
        repos = self.find_repository()

        if self.branch_path != "":
            # TODO: Set NULL_REVISION in SVN_PROP_BZR_BRANCHING_SCHEME
            repos.transport.mkdir(self.branch_path.strip("/"))
        elif repos.transport.get_latest_revnum() > 0:
            # Bail out if there are already revisions in this repository
            raise AlreadyBranchError(self.root_transport.base)
        branch = SvnBranch(self.root_transport.base, repos, self.branch_path)
        branch.bzrdir = self
        return branch

    def open_branch(self, unsupported=True):
        """See BzrDir.open_branch()."""
        from branch import SvnBranch
        repos = self.find_repository()
        branch = SvnBranch(self.root_transport.base, repos, self.branch_path)
        branch.bzrdir = self
        return branch

    def create_repository(self, shared=False, format=None):
        """See BzrDir.create_repository."""
        return self.open_repository()


class SvnFormat(BzrDirFormat):
    """Format for the Subversion smart server."""
    _lock_class = TransportLock

    def __init__(self):
        super(SvnFormat, self).__init__()
        from repository import SvnRepositoryFormat
        self.repository_format = SvnRepositoryFormat()

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        transport = get_svn_ra_transport(transport)

        if isinstance(transport, SvnRaTransport):
            return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        try: 
            return SvnRemoteAccess(transport, self)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_RA_DAV_REQUEST_FAILED:
                raise NotBranchError(transport.base)
            raise

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
        svn.repos.create(local_path, '', '', None, None)
        return self.open(get_svn_ra_transport(transport), _found=True)

    def is_supported(self):
        """See BzrDir.is_supported()."""
        return True


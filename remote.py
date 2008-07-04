# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Subversion BzrDir formats."""

import bzrlib
from bzrlib import urlutils
from bzrlib.bzrdir import BzrDirFormat, BzrDir, format_registry
from bzrlib.errors import (NotBranchError, NotLocalUrl, NoRepositoryPresent,
                           NoWorkingTree, AlreadyBranchError)
from bzrlib.transport.local import LocalTransport

from bzrlib.plugins.svn import core
from bzrlib.plugins.svn.errors import NoSvnRepositoryPresent
from bzrlib.plugins.svn.format import get_rich_root_format, SvnRemoteFormat
from bzrlib.plugins.svn.repository import SvnRepository
from bzrlib.plugins.svn.transport import bzr_to_svn_url, get_svn_ra_transport


class SvnRemoteAccess(BzrDir):
    """BzrDir implementation for Subversion connections.
    
    This is used for all non-checkout connections 
    to Subversion repositories.
    """
    def __init__(self, _transport, _format=None):
        """See BzrDir.__init__()."""
        _transport = get_svn_ra_transport(_transport)
        if _format is None:
            _format = SvnRemoteFormat()
        self._format = _format
        self.transport = None
        self.root_transport = _transport

        svn_url = bzr_to_svn_url(self.root_transport.base)
        self.svn_root_url = _transport.get_svn_repos_root()
        self.root_url = _transport.get_repos_root()

        assert svn_url.startswith(self.svn_root_url)
        self.branch_path = svn_url[len(self.svn_root_url):]

    def clone(self, url, revision_id=None, force_new_repo=False):
        """See BzrDir.clone().

        Not supported on Subversion connections.
        """
        raise NotImplementedError(SvnRemoteAccess.clone)

    def open_repository(self, _unsupported=False):
        """Open the repository associated with this BzrDir.
        
        :return: instance of SvnRepository.
        """
        if self.branch_path == "":
            return SvnRepository(self, self.root_transport)
        raise NoSvnRepositoryPresent(self.root_transport.base)

    def break_lock(self):
        pass

    def find_repository(self):
        """Open the repository associated with this BzrDir.
        
        :return: instance of SvnRepository.
        """
        transport = self.root_transport
        if self.root_url != transport.base:
            transport = transport.clone_root()
        return SvnRepository(self, transport, self.branch_path)

    def cloning_metadir(self):
        """Produce a metadir suitable for cloning with."""
        return bzrlib.bzrdir.format_registry.make_bzrdir("rich-root-pack")

    def open_workingtree(self, _unsupported=False,
            recommend_upgrade=True):
        """See BzrDir.open_workingtree().

        Will always raise NotLocalUrl as this 
        BzrDir can not be associated with working trees.
        """
        # Working trees never exist on remote Subversion repositories
        raise NoWorkingTree(self.root_transport.base)

    def create_workingtree(self, revision_id=None, hardlink=None):
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
        from bzrlib.plugins.svn.commit import push_new
        source.lock_read()
        try:
            if stop_revision is None:
                stop_revision = source.last_revision()
            target_branch_path = self.branch_path.strip("/")
            repos = self.find_repository()
            repos.lock_write()
            try:
                full_branch_url = urlutils.join(repos.transport.base, 
                                                target_branch_path)
                if repos.transport.check_path(target_branch_path,
                    repos.get_latest_revnum()) != core.NODE_NONE:
                    raise AlreadyBranchError(full_branch_url)
                push_new(repos, target_branch_path, source, stop_revision)
            finally:
                repos.unlock()
            branch = self.open_branch()
            branch.lock_write()
            try:
                branch.pull(source, stop_revision=stop_revision)
            finally:
                branch.unlock()
        finally:
            source.unlock()
        return branch

    def create_branch(self):
        """See BzrDir.create_branch()."""
        from branch import SvnBranch
        repos = self.find_repository()

        if self.branch_path != "":
            # TODO: Set NULL_REVISION in SVN_PROP_BZR_BRANCHING_SCHEME
            repos.transport.mkdir(self.branch_path.strip("/"))
        elif repos.get_latest_revnum() > 0:
            # Bail out if there are already revisions in this repository
            raise AlreadyBranchError(self.root_transport.base)
        branch = SvnBranch(repos, self.branch_path)
        branch.bzrdir = self
        return branch

    def open_branch(self, unsupported=True):
        """See BzrDir.open_branch()."""
        from bzrlib.plugins.svn.branch import SvnBranch
        repos = self.find_repository()
        branch = SvnBranch(repos, self.branch_path)
        branch.bzrdir = self
        return branch

    def create_repository(self, shared=False, format=None):
        """See BzrDir.create_repository."""
        return self.open_repository()



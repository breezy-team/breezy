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
from repository import SvnRepository
from branch import SvnBranch
from libsvn._core import SubversionException
from bzrlib.errors import NotBranchError, NotLocalUrl
from bzrlib.lockable_files import TransportLock
import svn.core
from transport import SvnTransport

class SvnRemoteAccess(BzrDir):
    def __init__(self, _transport, _format):
        self.root_transport = self.transport = _transport
        self._format = _format

        assert isinstance(_transport, SvnTransport)

        self.url = _transport.base
        self.branch_path = _transport.path

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        raise NotImplementedError(SvnRemoteAccess.clone)

    def open_repository(self):
        repos = SvnRepository(self, self.transport.root_url)
        repos._format = self._format
        return repos

    # Subversion has all-in-one, so a repository is always present
    find_repository = open_repository

    # Working trees never exist on Subversion repositories
    def open_workingtree(self):
        raise NotLocalUrl(self.url)

    def create_workingtree(self):
        raise NotImplementedError(SvnRemoteAccess.create_workingtree)

    def open_branch(self, unsupported=True):
        repos = self.open_repository()

        try:
            branch = SvnBranch(repos, self.branch_path)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_RA_ILLEGAL_URL or \
               num == svn.core.SVN_ERR_WC_NOT_DIRECTORY or \
               num == svn.core.SVN_ERR_RA_NO_REPOS_UUID or \
               num == svn.core.SVN_ERR_RA_SVN_REPOS_NOT_FOUND or \
               num == svn.core.SVN_ERR_FS_NOT_FOUND or \
               num == svn.core.SVN_ERR_RA_DAV_REQUEST_FAILED:
               raise NotBranchError(path=self.url)
            raise
 
        branch.bzrdir = self
        return branch

class SvnFormat(BzrDirFormat):

    _lock_class = TransportLock

    def _open(self, transport):
        return SvnRemoteAccess(transport, self)

    def get_format_string(self):
        return 'Subversion Smart Server'

    def get_format_description(self):
        return 'Subversion Smart Server'

    def initialize(self,url):
        assert isinstance(url, basestring)
        #FIXME: bzr itself should fall back here
        return BzrDirFormat.get_default_format().initialize(url)
        raise NotImplementedError(SvnFormat.initialize)



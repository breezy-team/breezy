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
from bzrlib.errors import NotBranchError, NotLocalUrl
from bzrlib.lockable_files import TransportLock
import bzrlib.urlutils as urlutils

from branch import SvnBranch
from repository import SvnRepository
from scheme import BranchingScheme
from transport import SvnRaTransport

from svn.core import SubversionException
import svn.core

class SvnRemoteAccess(BzrDir):
    def __init__(self, _transport, _format):
        assert isinstance(_transport, SvnRaTransport)

        self._format = _format
        self.root_transport = _transport.get_root()
        self.transport = _transport
        self.url = _transport.base

        assert self.transport.base.startswith(self.root_transport.base)
        self.branch_path = self.transport.base[len(self.root_transport.base):]

        self.scheme = BranchingScheme.guess_scheme(self.branch_path)

        if not self.scheme.is_branch(self.branch_path):
            raise NotBranchError(path=self.transport.base)

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        raise NotImplementedError(SvnRemoteAccess.clone)

    def sprout(self, url, revision_id=None, basis=None, force_new_repo=False):
        # FIXME: honor force_new_repo
        result = BzrDirFormat.get_default_format().initialize(url)
        repo = self.open_repository()
        result_repo = repo.clone(result, revision_id, basis)
        branch = self.open_branch()
        branch.sprout(result, revision_id)
        result.create_workingtree()
        return result

    def open_repository(self):
        repos = SvnRepository(self, self.root_transport)
        repos._format = self._format
        return repos

    # Subversion has all-in-one, so a repository is always present
    find_repository = open_repository

    # Working trees never exist on remote Subversion repositories
    def open_workingtree(self):
        raise NotLocalUrl(self.url)

    def create_workingtree(self, revision_id=None):
        # TODO
        raise NotImplementedError(self.create_workingtree)

    def open_branch(self, unsupported=True):
        repos = self.open_repository()

        try:
            branch = SvnBranch(repos, self.branch_path)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_WC_NOT_DIRECTORY:
               raise NotBranchError(path=self.url)
            raise
 
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

    def initialize(self, url):
        raise NotImplementedError(self.initialize)

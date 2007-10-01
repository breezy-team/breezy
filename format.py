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

from bzrlib.bzrdir import BzrDirFormat, BzrDir, format_registry
from bzrlib.lazy_import import lazy_import
from bzrlib.lockable_files import TransportLock

lazy_import(globals(), """
import errors
import remote

from bzrlib import errors as bzr_errors
""")

def get_rich_root_format():
    format = BzrDirFormat.get_default_format()
    if format.repository_format.rich_root_data:
        return format
    # Default format does not support rich root data, 
    # fall back to dirstate-with-subtree
    format = format_registry.make_bzrdir('dirstate-with-subtree')
    assert format.repository_format.rich_root_data
    return format


class SvnRemoteFormat(BzrDirFormat):
    """Format for the Subversion smart server."""
    _lock_class = TransportLock

    def __init__(self):
        super(SvnRemoteFormat, self).__init__()
        from repository import SvnRepositoryFormat
        self.repository_format = SvnRepositoryFormat()

    @classmethod
    def probe_transport(klass, transport):
        from transport import get_svn_ra_transport
        import svn.core
        format = klass()

        try:
            transport = get_svn_ra_transport(transport)
        except svn.core.SubversionException, (_, num):
            if num in (svn.core.SVN_ERR_RA_ILLEGAL_URL, \
                       svn.core.SVN_ERR_RA_LOCAL_REPOS_OPEN_FAILED, \
                       svn.core.SVN_ERR_BAD_URL):
                raise bzr_errors.NotBranchError(path=transport.base)

        return format

    def _open(self, transport):
        import svn.core
        try: 
            return remote.SvnRemoteAccess(transport, self)
        except svn.core.SubversionException, (_, num):
            if num == svn.core.SVN_ERR_RA_DAV_REQUEST_FAILED:
                raise bzr_errors.NotBranchError(transport.base)
            raise

    def get_format_string(self):
        return 'Subversion Smart Server'

    def get_format_description(self):
        return 'Subversion Smart Server'

    def initialize_on_transport(self, transport):
        """See BzrDir.initialize_on_transport()."""
        from transport import get_svn_ra_transport
        from bzrlib.transport.local import LocalTransport
        import svn.repos

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


class SvnWorkingTreeDirFormat(BzrDirFormat):
    """Working Tree implementation that uses Subversion working copies."""
    _lock_class = TransportLock

    def __init__(self):
        super(SvnWorkingTreeDirFormat, self).__init__()
        from repository import SvnRepositoryFormat
        self.repository_format = SvnRepositoryFormat()

    @classmethod
    def probe_transport(klass, transport):
        import svn
        from bzrlib.transport.local import LocalTransport
        format = klass()

        if isinstance(transport, LocalTransport) and \
            transport.has(svn.wc.get_adm_dir()):
            return format

        raise bzr_errors.NotBranchError(path=transport.base)

    def _open(self, transport):
        import svn.core
        from workingtree import SvnCheckout
        subr_version = svn.core.svn_subr_version()
        if subr_version.major == 1 and subr_version.minor < 4:
            raise errors.NoCheckoutSupport()
        try:
            return SvnCheckout(transport, self)
        except svn.core.SubversionException, (_, num):
            if num in (svn.core.SVN_ERR_RA_LOCAL_REPOS_OPEN_FAILED,):
                raise errors.NoSvnRepositoryPresent(transport.base)
            raise

    def get_format_string(self):
        return 'Subversion Local Checkout'

    def get_format_description(self):
        return 'Subversion Local Checkout'

    def initialize_on_transport(self, transport):
        raise UninitializableFormat(self)

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        if format is None:
            format = get_rich_root_format()
        raise NotImplementedError(self.get_converter)

# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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

from transport import SvnRaTransport
from format import SvnRemoteAccess

import bzrlib
from bzrlib.bzrdir import BzrDirFormat, BzrDir
from bzrlib.errors import NotBranchError, NoSuchFile
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import TransportLock
from bzrlib.progress import DummyProgress
from bzrlib.transport import Transport
import bzrlib.urlutils as urlutils
import bzrlib.osutils as osutils
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

import tempfile
from cStringIO import StringIO

import svn.repos, svn.core
from svn.core import SubversionException

class SvnDumpFile(SvnRemoteAccess):
    """Allow directly accessing Repositories in Subversion Dump Files.

    This will build the repository from the dumpfile in a temporary
    directory.
    """
    def __init__(self, nested_transport, format):
        """Instantiate a new instance of SvnDumpFile.

        :param nested_transport: Transport to use for reading the file.
        :param format: BzrDirFormat
        """
        assert isinstance(nested_transport, Transport)
        assert isinstance(format, BzrDirFormat)
        self.tmp_repos = None

        transport = nested_transport

        dumpfile = None

        while not dumpfile:
            last_name = urlutils.basename(transport.base)
            parent_transport = transport
            transport = transport.clone('..')
            from stat import S_ISDIR
            if not S_ISDIR(transport.stat(last_name).st_mode):
                dumpfile = transport.get(last_name)

        if dumpfile.readline() != "SVN-fs-dump-format-version: 2":
            raise NotBranchError(path=nested_transport.base)
        
        dumpfile.seek(0)

        repos_path = parent_transport.relpath(nested_transport.base)

        self.tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
        repos = svn.repos.create(self.tmp_repos, '', '', None, None)
        try:
            svn.repos.load_fs2(repos, dumpfile, StringIO(), 
                svn.repos.load_uuid_default, '', 0, 0, None)
        except SubversionException, (svn.core.SVN_ERR_STREAM_MALFORMED_DATA, _):
            raise NotBranchError(path=nested_transport.base)

        svn_url = 'file://%s/%s' % (self.tmp_repos, repos_path)
        remote_transport = SvnRaTransport(svn_url)

        super(SvnDumpFile, self).__init__(remote_transport, format)

    def __del__(self):
        if self.tmp_repos:
            osutils.rmtree(self.tmp_repos)
            self.tmp_repos = None


class SvnDumpFileFormat(BzrDirFormat):
    _lock_class = TransportLock

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        # FIXME: This is way inefficient over remote transports..
        #if SvnDumpFile(transport, format):
        #    return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        return SvnDumpFile(transport, self)

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return 'Subversion Dump File'

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return 'Subversion Dump File'

    def initialize(self,url):
        raise NotImplementedError(SvnFormat.initialize)

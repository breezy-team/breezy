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
from bzrlib.errors import NotBranchError
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import TransportLock
from bzrlib.progress import DummyProgress
import bzrlib.urlutils as urlutils
import bzrlib.osutils as osutils
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

import tempfile
from cStringIO import StringIO

import svn.repos, svn.core
from libsvn.core import SubversionException

class SvnDumpFile(SvnRemoteAccess):
    def __init__(self, nested_transport, format):
        self.tmp_repos = None

        transport = nested_transport

        dumpfile = None

        while not dumpfile:
            last_name = urlutils.basename(transport.base)
            parent_transport = transport
            transport = transport.clone('..')
            try:
                dumpfile = transport.get(last_name)
            except:
                pass

        repos_path = parent_transport.relpath(nested_transport.base)

        self.tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
        repos = svn.repos.svn_repos_create(self.tmp_repos, '', '', None, None)
        try:
            svn.repos.svn_repos_load_fs2(repos, dumpfile, StringIO(), 
                svn.repos.svn_repos_load_uuid_default, '', 0, 0, None)
        except SubversionException, (svn.core.SVN_ERR_STREAM_MALFORMED_DATA, _):
            raise NotBranchError(path=nested_transport.base)

        svn_url = 'svn+file://%s/%s' % (self.tmp_repos, repos_path)
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
        if SvnDumpFile(transport, format):
            return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        return SvnDumpFile(transport, self)

    def get_format_string(self):
        return 'Subversion Dump File'

    def get_format_description(self):
        return 'Subversion Dump File'

    def initialize(self,url):
        raise NotImplementedError(SvnFormat.initialize)

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

import bzrlib
from bzrlib.bzrdir import BzrDirFormat
from bzrlib.errors import NotBranchError
from bzrlib.lockable_files import TransportLock
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat
from transport import SvnRaTransport
from format import SvnRemoteAccess, SvnFormat

import svn.core, svn.wc
from libsvn._core import SubversionException

class SvnWorkingTree(WorkingTree):
    """Implementation of WorkingTree that uses a Subversion 
    Working Copy for storage."""
    def __init__(self, path, branch):
        WorkingTree.__init__(self, path, branch)
        self.path = path
        self.wc = svn.wc.open_adm3(self.path)

    def revert(self, filenames, old_tree=None, backups=True):
        # FIXME: Respect old_tree and backups
        svn.wc.revert(filenames, True, self.wc, self.pool)

    def move(self, from_paths, to_name):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        for entry in from_paths:
            svn.wc.move(entry, revt, to_name, False, self.wc, self.pool)

    def rename_one(self, from_rel, to_rel):
        # There is no difference between rename and move in SVN
        self.move([from_rel], to_rel)

    def add(self, files, ids=None):
        for f in files:
            svn.wc.add2(f, False, self.wc, self.pool)
            if ids:
                id = ids.pop()
                if id:
                    svn.wc.prop_set2('bzr:id', id, f, False, self.pool)

class SvnWorkingTreeFormat(WorkingTreeFormat):
    def get_format_description(self):
        return "Subversion Working Copy"

    def initialize(self, a_bzrdir, revision_id=None):
        # FIXME
        raise NotImplementedError(self.initialize)

    def open(self, a_bzrdir):
        # FIXME
        raise NotImplementedError(self.initialize)


class SvnLocalAccess(SvnRemoteAccess):
    def __init__(self, transport, format):
        self.local_path = transport.base.rstrip("/")
        if self.local_path.startswith("file://"):
            self.local_path = self.local_path[len("file://"):]
        
        self.wc = svn.wc.adm_open3(None, self.local_path, False, 0, None)
        self.transport = transport
        self.wc_entry = svn.wc.entry(self.local_path, self.wc, True)

        # Open related remote repository + branch
        url = self.wc_entry.url
        if not url.startswith("svn"):
            url = "svn+" + url
        format = SvnFormat()
        try:
            remote_transport = SvnRaTransport(url)
        except Exception, e:
            print e
        while True:
            print remote_transport.base
            try:
                format = SvnFormat.probe_transport(remote_transport)
            except NotBranchError, e:
                pass
            new_t = remote_transport.clone('..')
            assert new_t.base != remote_transport.base
            remote_transport = new_t

        super(SvnLocalAccess, self).__init__(remote_transport)

class SvnWorkingTreeDirFormat(BzrDirFormat):
    _lock_class = TransportLock

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        if transport.has('.svn'):
            return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        return SvnLocalAccess(transport, self)

    def get_format_string(self):
        return 'Subversion Local Checkout'

    def get_format_description(self):
        return 'Subversion Local Checkout'

    def initialize(self,url):
        raise NotImplementedError(SvnFormat.initialize)

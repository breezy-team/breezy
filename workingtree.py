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
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import TransportLock
from bzrlib.progress import DummyProgress
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

from branch import _global_pool
from format import SvnRemoteAccess, SvnFormat
from repository import SvnRepository
from transport import SvnRaTransport

import os

import svn.core, svn.wc
from libsvn.core import SubversionException

class SvnWorkingTree(WorkingTree):
    """Implementation of WorkingTree that uses a Subversion 
    Working Copy for storage."""
    def __init__(self, wc, branch):
        self._format = SvnWorkingTreeFormat()
        self.wc = wc
        self.basedir = svn.wc.adm_access_path(self.wc)
        self._branch = branch

    def _get_inventory(self):
        return Inventory()
        raise NotImplementedError(self._get_inventory)

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def lock_write(self):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass

    def is_control_filename(self, path):
        return path == '.svn'

    def get_file_by_path(self, path):
        raise NotImplementedError(self.get_file_by_path)

    def get_file_lines(self, file_id):
        raise NotImplementedError(self.get_file_lines)

    def remove(self, files, verbose=False, to_file=None):
        for file in files:
            svn.wc.delete2(os.path.join(self.basedir, file), self.wc, None, 
                           None, None)

    def revert(self, files, old_tree=None, backups=True, pb=DummyProgress()):
        if old_tree is not None:
            # TODO: Also make sure old_tree != basis_tree
            super(SvnWorkingTree, self).revert(files, old_tree, backups, pb)
            return
        
        svn.wc.revert([os.path.join(self.basedir, f) for f in files],
                      self.wc, False, False, None, None)

    def move(self, from_paths, to_name):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        for entry in from_paths:
            svn.wc.move(entry, revt, to_name, False, self.wc)

    def rename_one(self, from_rel, to_rel):
        # There is no difference between rename and move in SVN
        self.move([from_rel], to_rel)

    def read_working_inventory(self):
        return self.inventory

    def add(self, files, ids=None):
        for f in files:
            svn.wc.add2(f, False, self.wc)
            if ids:
                id = ids.pop()
                if id:
                    svn.wc.prop_set2('bzr:id', id, f, False)

    def pending_merges(self):
        return []

    def set_pending_merges(self):
        raise NotImplementedError(self.set_pending_merges)

    def unknowns(self):
        raise NotImplementedError(self.unknowns)

    def basis_tree(self):
        raise NotImplementedError(self.basis_tree)

    def pull(self, source, overwrite=False, stop_revision=None):
        raise NotImplementedError(self.pull)

    def extras(self):
        raise NotImplementedError(self.extras)

class SvnWorkingTreeFormat(WorkingTreeFormat):
    def get_format_description(self):
        return "Subversion Working Copy"

    def initialize(self, a_bzrdir, revision_id=None):
        # FIXME
        raise NotImplementedError(self.initialize)

    def open(self, a_bzrdir):
        # FIXME
        raise NotImplementedError(self.initialize)

class OptimizedRepository(SvnRepository):
    def revision_tree(self, revision_id):
        # TODO: if revision id matches base revno, 
        # return working_tree.basis_tree() 
        return super(OptimizedRepository, self).revision_tree(revision_id)

class SvnLocalAccess(SvnRemoteAccess):
    def __init__(self, transport, format):
        self.local_path = transport.base.rstrip("/")
        if self.local_path.startswith("file://"):
            self.local_path = self.local_path[len("file://"):]
        
        self.wc = svn.wc.adm_open3(None, self.local_path, True, 100, None)
        self.transport = transport

        # Open related remote repository + branch
        url, self.base_revno = svn.wc.get_ancestry(self.local_path, self.wc)
        if not url.startswith("svn"):
            url = "svn+" + url

        remote_transport = SvnRaTransport(url)

        super(SvnLocalAccess, self).__init__(remote_transport, SvnFormat())

    def __del__(self):
        pass #svn.wc.adm_close(self.wc)

    def open_repository(self):
        repos = OptimizedRepository(self, self.transport.root_url)
        repos._format = self._format
        return repos

    def clone(self, path):
        raise NotImplementedError(self.clone)

    # Subversion has all-in-one, so a repository is always present
    find_repository = open_repository

    # Working trees never exist on Subversion repositories
    def open_workingtree(self, _unsupported=False):
        return SvnWorkingTree(self.wc, self.open_branch())

    def create_workingtree(self):
        raise NotImplementedError(SvnRemoteAccess.create_workingtree)


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

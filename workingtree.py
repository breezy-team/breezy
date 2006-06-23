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

from binascii import hexlify
from bzrlib.bzrdir import BzrDirFormat
from bzrlib.errors import NotBranchError, NoSuchFile
from bzrlib.inventory import Inventory, InventoryDirectory, InventoryFile
from bzrlib.lockable_files import TransportLock
from bzrlib.osutils import rand_bytes
from bzrlib.progress import DummyProgress
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

from format import SvnRemoteAccess, SvnFormat
from repository import SvnRepository
from transport import SvnRaTransport

import os

import svn.core, svn.wc
from svn.core import SubversionException

class SvnWorkingTree(WorkingTree):
    """Implementation of WorkingTree that uses a Subversion 
    Working Copy for storage."""
    def __init__(self, bzrdir, wc, branch, base_revid):
        self._format = SvnWorkingTreeFormat()
        self.wc = wc
        self.basedir = svn.wc.adm_access_path(self.wc)
        self.base_revid = base_revid
        self.bzrdir = bzrdir
        self._branch = branch
        self._set_inventory(self.read_working_inventory())

    def lock_write(self):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass

    def is_control_filename(self, path):
        return svn.wc.is_adm_dir(path)

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
        
        for f in files:
            svn.wc.revert(os.path.join(self.basedir, f),
                      self.wc, False, False, None, None)

    def move(self, from_paths, to_name):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_working
        for entry in from_paths:
            old_path = os.path.join(self.basedir, entry)
            new_path = os.path.join(self.basedir, to_name, entry)
            svn.wc.copy(old_path, self.wc, new_path, None, None)
            self.remove([entry])

    def rename_one(self, from_rel, to_rel):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        svn.wc.copy(os.path.join(self.basedir, from_rel), 
                    self.wc,
                    os.path.join(self.basedir, to_rel),
                    None, None)
        self.remove([from_rel])

    def read_working_inventory(self):
        basis_inv = self.basis_tree().inventory
        inv = Inventory()

        def add_dir_to_inv(relpath, wc):
            id = inv.path2id(relpath)
            entries = svn.wc.entries_read(wc, True)
            for entry in entries:
                if entry == "":
                    continue

                schedule = entries[entry].schedule

                if schedule == svn.wc.schedule_normal:
                    # Keep old id
                    subid = basis_inv.path2id(os.path.join(relpath, entry))
                    assert subid
                elif schedule == svn.wc.schedule_delete:
                    continue
                elif schedule == svn.wc.schedule_add or \
                     schedule == svn.wc.schedule_replace:
                    # TODO: See if the file this file was copied from disappeared
                    # and has no other copies -> in that case, take id of other file
                    subid = hexlify(rand_bytes(8))

                abspath = os.path.join(self.basedir, relpath, entry).rstrip("/")
                if entries[entry].kind == svn.core.svn_node_dir:
                    inv.add(InventoryDirectory(subid, entry, id))
                    subwc = svn.wc.adm_open3(wc, abspath, False, 0, None)
                    add_dir_to_inv(os.path.join(relpath, entry), subwc)
                    svn.wc.adm_close(subwc)
                else:
                    from bzrlib.osutils import fingerprint_file
                    data = fingerprint_file(open(abspath))
                    file = InventoryFile(subid, entry, id)
                    file.text_sha1 = data['sha1']
                    file.text_size = data['size']
                    inv.add(file)

        add_dir_to_inv("", self.wc)

        return inv

    def add(self, files, ids=None):
        for f in files:
            try:
                svn.wc.add2(os.path.join(self.basedir, f), self.wc, None, 0, None, None, None)
            except SubversionException, (_, num):
                if num == svn.core.SVN_ERR_ENTRY_EXISTS:
                    continue
                if num == svn.core.SVN_ERR_WC_PATH_NOT_FOUND:
                    raise NoSuchFile(path=f)
                raise
            if ids:
                id = ids.pop()
                if id:
                    svn.wc.prop_set2('bzr:fileid', id, f, False)

    def pending_merges(self):
        return []

    def set_pending_merges(self):
        raise NotImplementedError(self.set_pending_merges)

    def unknowns(self):
        raise NotImplementedError(self.unknowns)

    def basis_tree(self):
        return self._branch.repository.revision_tree(self.base_revid)

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
    """Wrapper around SvnRepository that uses some files from local disk."""
    def revision_tree(self, revision_id):
        # TODO: if revision id matches base revno, 
        # return working_tree.basis_tree() 
        return super(OptimizedRepository, self).revision_tree(revision_id)


class SvnLocalAccess(SvnRemoteAccess):
    def __init__(self, transport, format):
        self.wc = None
        self.local_path = transport.base.rstrip("/")
        if self.local_path.startswith("file://"):
            self.local_path = self.local_path[len("file://"):]
        
        self.wc = svn.wc.adm_open3(None, self.local_path, True, 0, None)
        self.transport = transport

        # Open related remote repository + branch
        url, revno = svn.wc.get_ancestry(self.local_path, self.wc)
        if not url.startswith("svn"):
            url = "svn+" + url

        self.base_revno = svn.wc.status2(self.local_path, self.wc).ood_last_cmt_rev

        remote_transport = SvnRaTransport(url)

        super(SvnLocalAccess, self).__init__(remote_transport, format)

    def __del__(self):
        if self.wc is not None:
            svn.wc.adm_close(self.wc)
            self.wc = None

    def open_repository(self):
        repos = OptimizedRepository(self, self.root_transport)
        repos._format = self._format
        return repos

    def clone(self, path):
        raise NotImplementedError(self.clone)

    # Subversion has all-in-one, so a repository is always present
    find_repository = open_repository

    # Working trees never exist on Subversion repositories
    def open_workingtree(self, _unsupported=False):
        return SvnWorkingTree(self, self.wc, self.open_branch(), 
                self.open_repository().generate_revision_id(
                    self.base_revno, self.branch_path))

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
        raise NotImplementedError(self.initialize)

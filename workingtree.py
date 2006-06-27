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
from bzrlib.lockable_files import TransportLock, LockableFiles
from bzrlib.lockdir import LockDir
from bzrlib.osutils import rand_bytes, fingerprint_file
from bzrlib.progress import DummyProgress
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

from format import SvnRemoteAccess, SvnFormat
from repository import SvnRepository
from transport import SvnRaTransport, svn_config
from tree import SvnBasisTree

import os

import svn.core, svn.wc
from svn.core import SubversionException

class SvnWorkingTree(WorkingTree):
    """Implementation of WorkingTree that uses a Subversion 
    Working Copy for storage."""
    def __init__(self, bzrdir, local_path, branch, base_revid):
        self._format = SvnWorkingTreeFormat()
        self.basedir = local_path
        self.base_revid = base_revid
        self.bzrdir = bzrdir
        self._branch = branch
        self._set_inventory(self.read_working_inventory())
        try:
            os.makedirs(os.path.join(self.basedir, svn.wc.get_adm_dir(), 'bzr'))
        except OSError:
            pass
        self._control_files = LockableFiles(bzrdir.transport, 
                os.path.join(svn.wc.get_adm_dir(), 'bzr'), LockDir)

    def lock_write(self):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass

    def get_ignore_list(self):
        ignores = []

        def dir_add(wc, prefix):
            ignores.append(os.path.join(prefix, svn.wc.get_adm_dir()))
            for pat in svn.wc.get_ignores(svn_config, wc):
                ignores.append(os.path.join(prefix, pat))

            entries = svn.wc.entries_read(wc, True)
            for entry in entries:
                if entry == "":
                    continue

                if entries[entry].kind != svn.core.svn_node_dir:
                    continue

                subwc = svn.wc.adm_open3(wc, os.path.join(self.basedir, prefix, entry), False, 0, None)
                try:
                    dir_add(subwc, os.path.join(prefix, entry))
                finally:
                    svn.wc.adm_close(subwc)

        wc = self._get_wc()
        dir_add(wc, "")
        svn.wc.adm_close(wc)

        return ignores

    def is_ignored(self, filename):
        if svn.wc.is_adm_dir(os.path.basename(filename)):
            return True

        (wc, name) = self._get_rel_wc(filename)
        try:
            ignores = svn.wc.get_ignores(svn_config, wc)
            from fnmatch import fnmatch
            for pattern in ignores:
                if fnmatch(name, pattern):
                    return True
            return False
        finally:
            svn.wc.adm_close(wc)

    def is_control_filename(self, path):
        return svn.wc.is_adm_dir(path)

    def remove(self, files, verbose=False, to_file=None):
        wc = self._get_wc(write_lock=True)
        try:
            for file in files:
                svn.wc.delete2(self.abspath(file), wc, None, None, None)
        finally:
            svn.wc.adm_close(wc)

    def _get_wc(self, relpath="", write_lock=False):
        return svn.wc.adm_open3(None, self.abspath(relpath).rstrip("/"), write_lock, 0, None)

    def _get_rel_wc(self, relpath, write_lock=False):
        dir = os.path.dirname(relpath)
        file = os.path.basename(relpath)
        return (self._get_wc(dir, write_lock), file)

    def move(self, from_paths, to_name):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_working
        to_wc = self._get_wc(to_name, write_lock=True)
        try:
            for entry in from_paths:
                svn.wc.copy(self.abspath(entry), to_wc, os.path.basename(entry), None, None)
        finally:
            svn.wc.adm_close(to_wc)

        for entry in from_paths:
            self.remove([entry])

    def rename_one(self, from_rel, to_rel):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        (to_wc, to_file) = self._get_rel_wc(to_rel, write_lock=True)
        try:
            svn.wc.copy(self.abspath(from_rel), to_wc, to_file, None, None)
            svn.wc.delete2(self.abspath(from_rel), to_wc, None, None, None)
        finally:
            svn.wc.adm_close(to_wc)

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
                    subid = entry

                abspath = os.path.join(self.basedir, relpath, entry).rstrip("/")
                if entries[entry].kind == svn.core.svn_node_dir:
                    inv.add(InventoryDirectory(subid, entry, id))
                    subwc = svn.wc.adm_open3(wc, abspath, False, 0, None)
                    add_dir_to_inv(os.path.join(relpath, entry), subwc)
                    svn.wc.adm_close(subwc)
                else:
                    file = InventoryFile(subid, entry, id)
                    try:
                        data = fingerprint_file(open(abspath))
                        file.text_sha1 = data['sha1']
                        file.text_size = data['size']
                        inv.add(file)
                    except IOError:
                        # Ignore non-existing files
                        pass

        wc = self._get_wc() 
        try:
            add_dir_to_inv("", wc)
        finally:
            svn.wc.adm_close(wc)

        return inv

    def set_last_revision(self, revid):
        pass # FIXME

    def add(self, files, ids=None):
        assert isinstance(files, list)
        wc = self._get_wc(write_lock=True)
        try:
            for f in files:
                try:
                    svn.wc.add2(os.path.join(self.basedir, f), wc, None, 0, 
                            None, None, None)
                    if ids:
                        svn.wc.prop_set2('bzr:fileid', ids.pop(), relpath, wc, 
                                False)
                except SubversionException, (_, num):
                    if num == svn.core.SVN_ERR_ENTRY_EXISTS:
                        continue
                    elif num == svn.core.SVN_ERR_WC_PATH_NOT_FOUND:
                        raise NoSuchFile(path=f)
                    raise
        finally:
            svn.wc.adm_close(wc)

    def basis_tree(self):
        return SvnBasisTree(self)

    def pull(self, source, overwrite=False, stop_revision=None):
        raise NotImplementedError(self.pull)

    def get_file_sha1(self, file_id, path=None):
        if not path:
            path = self._inventory.id2path(file_id)

        return fingerprint_file(open(self.abspath(path)))['sha1']

    def pending_merges(self):
        try:
            super(SvnWorkingTree, self).pending_merges()
        except NoSuchFile:
            return []


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
        self.local_path = transport.base.rstrip("/")
        if self.local_path.startswith("file://"):
            self.local_path = self.local_path[len("file://"):]
        
        wc = svn.wc.adm_open3(None, self.local_path, True, 0, None)

        # Open related remote repository + branch
        url, revno = svn.wc.get_ancestry(self.local_path, wc)
        if not url.startswith("svn"):
            url = "svn+" + url

        self.base_revno = svn.wc.status2(self.local_path, wc).ood_last_cmt_rev

        remote_transport = SvnRaTransport(url)

        super(SvnLocalAccess, self).__init__(remote_transport, format)

        self.transport = transport
        svn.wc.adm_close(wc)

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
        return SvnWorkingTree(self, self.local_path, self.open_branch(), 
                self.open_repository().generate_revision_id(
                    self.base_revno, self.branch_path))

    def create_workingtree(self):
        raise NotImplementedError(SvnRemoteAccess.create_workingtree)


class SvnWorkingTreeDirFormat(BzrDirFormat):
    _lock_class = TransportLock

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        if transport.has(svn.wc.get_adm_dir()):
            return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        return SvnLocalAccess(transport, self)

    def get_format_string(self):
        return 'Subversion Local Checkout'

    def get_format_description(self):
        return 'Subversion Local Checkout'

    def initialize_on_transport(self, transport):
        raise NotImplementedError(self.initialize_on_transport)

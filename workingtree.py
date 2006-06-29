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
from bzrlib.inventory import (Inventory, InventoryDirectory, InventoryFile, 
                              ROOT_ID)
from bzrlib.lockable_files import TransportLock, LockableFiles
from bzrlib.lockdir import LockDir
from bzrlib.osutils import rand_bytes, fingerprint_file
from bzrlib.progress import DummyProgress
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
from bzrlib.tree import EmptyTree
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

from branch import SvnBranch
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
    def __init__(self, bzrdir, local_path, branch):
        self._format = SvnWorkingTreeFormat()
        self.basedir = local_path
        self.bzrdir = bzrdir
        self._branch = branch
        self.base_revnum = 0

        self._set_inventory(self.read_working_inventory())
        mutter('working inv: %r' % self.read_working_inventory().entries())

        self.base_revid = branch.repository.generate_revision_id(
                    self.base_revnum, branch.branch_path)
        mutter('basis inv: %r' % self.basis_tree().inventory.entries())
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

            entries = svn.wc.entries_read(wc, False)
            for entry in entries:
                if entry == "":
                    continue

                if entries[entry].kind != svn.core.svn_node_dir:
                    continue

                subprefix = os.path.join(prefix, entry)

                subwc = svn.wc.adm_open3(wc, self.abspath(subprefix), False, 0, None)
                try:
                    dir_add(subwc, subprefix)
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
        assert wc
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
        inv = Inventory()

        def add_file_to_inv(relpath, id, revid, parent_id):
            """Add a file to the inventory."""
            file = InventoryFile(id, os.path.basename(relpath), parent_id)
            file.revision = revid
            try:
                data = fingerprint_file(open(self.abspath(relpath)))
                file.text_sha1 = data['sha1']
                file.text_size = data['size']
                inv.add(file)
            except IOError:
                # Ignore non-existing files
                pass

        def find_copies(url, relpath=""):
            wc = self._get_wc(relpath)
            entries = svn.wc.entries_read(wc, False)
            for entry in entries.values():
                subrelpath = os.path.join(relpath, entry.name)
                if entry.name == "" or entry.kind != 'directory':
                    if ((entry.copyfrom_url == url or entry.url == url) and 
                        not (entry.schedule in (svn.wc.schedule_delete,
                                                svn.wc.schedule_replace))):
                        yield os.path.join(self.branch.branch_path.strip("/"), subrelpath)
                else:
                    find_copies(subrelpath)
            svn.wc.adm_close(wc)

        def find_ids(entry):
            relpath = entry.url[len(entry.repos):].strip("/")
            if entry.schedule == svn.wc.schedule_normal:
                assert entry.revision >= 0
                # Keep old id
                mutter('stay: %r' % relpath)
                return self.branch.repository.path_to_file_id(entry.revision, 
                        relpath)
            elif entry.schedule == svn.wc.schedule_delete:
                return (None, None)
            elif (entry.schedule == svn.wc.schedule_add or 
                  entry.schedule == svn.wc.schedule_replace):
                # See if the file this file was copied from disappeared
                # and has no other copies -> in that case, take id of other file
                mutter('copies(%r): %r' % (relpath, list(find_copies(entry.copyfrom_url))))
                if entry.copyfrom_url and list(find_copies(entry.copyfrom_url)) == [relpath]:
                    return self.branch.repository.path_to_file_id(entry.copyfrom_rev,
                        entry.copyfrom_url[len(entry.repos):])
                return ("NEW-" + entry.url[len(entry.repos):].strip("/").replace("/", "@"), None)
            else:
                assert 0

        def add_dir_to_inv(relpath, wc, parent_id):
            entries = svn.wc.entries_read(wc, False)

            entry = entries[""]
            
            (id, revid) = find_ids(entry)

            if id is None:
                return

            self.base_revnum = max(self.base_revnum, entry.revision)

            # First handle directory itself
            if id is ROOT_ID:
                inv.revision_id = revid
            else:
                inventry = InventoryDirectory(id, os.path.basename(relpath), parent_id)
                inventry.revision = revid
                inv.add(inventry)

            for name in entries:
                if name == "":
                    continue

                subrelpath = os.path.join(relpath, name)

                entry = entries[name]
                assert entry
                
                if entry.kind == svn.core.svn_node_dir:
                    subwc = svn.wc.adm_open3(wc, self.abspath(subrelpath), 
                                             False, 0, None)
                    add_dir_to_inv(subrelpath, subwc, id)
                    svn.wc.adm_close(subwc)
                else:
                    (subid, subrevid) = find_ids(entry)
                    if subid:
                        self.base_revnum = max(self.base_revnum, entry.revision)
                        add_file_to_inv(subrelpath, subid, subrevid, id)

        wc = self._get_wc() 
        try:
            add_dir_to_inv("", wc, None)
        finally:
            svn.wc.adm_close(wc)

        return inv

    def set_last_revision(self, revid):
        mutter('setting last revision to %r' % revid)
        if revid is None or revid == NULL_REVISION:
            self.base_revid = revid
            return

        # TODO: Implement more efficient version
        newrev = self.branch.repository.get_revision(revid)
        newrevtree = self.branch.repository.revision_tree(revid)

        def update_settings(wc, path):
            id = newrevtree.inventory.path2id(path)
            mutter("Updating settings for %r" % id)
            (_, revnum) = self.branch.repository.parse_revision_id(
                    newrevtree.inventory[id].revision)

            svn.wc.process_committed2(self.abspath(path).rstrip("/"), wc, 
                          False, revnum, 
                          svn.core.svn_time_to_cstring(newrev.timestamp), 
                          newrev.committer, None, False)

            if newrevtree.inventory[id].kind != 'directory':
                return

            entries = svn.wc.entries_read(wc, True)
            for entry in entries:
                if entry == "":
                    continue

                subwc = svn.wc.adm_open3(wc, os.path.join(self.basedir, path, entry), False, 0, None)
                try:
                    update_settings(subwc, os.path.join(path, entry))
                finally:
                    svn.wc.adm_close(subwc)

        # Set proper version for all files in the wc
        wc = self._get_wc(write_lock=True)
        update_settings(wc, "")
        svn.wc.adm_close(wc)
        self.base_revid = revid

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
        if self.base_revid is None or self.base_revid == NULL_REVISION:
            return EmptyTree()

        return SvnBasisTree(self, self.base_revid)

    def pull(self, source, overwrite=False, stop_revision=None):
        raise NotImplementedError(self.pull)

    def get_file_sha1(self, file_id, path=None):
        if not path:
            path = self._inventory.id2path(file_id)

        return fingerprint_file(open(self.abspath(path)))['sha1']

    def pending_merges(self):
        try:
            return super(SvnWorkingTree, self).pending_merges()
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

class OptimizedBranch(SvnBranch):
    """Wrapper around SvnBranch that uses some files from local disk."""

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

        remote_transport = SvnRaTransport(url)

        super(SvnLocalAccess, self).__init__(remote_transport, format)

        self.transport = transport
        svn.wc.adm_close(wc)

    def open_repository(self):
        repos = OptimizedRepository(self, self.root_transport)
        repos._format = self._format
        return repos

    def open_branch(self, _unsupported=True):
        """See BzrDir.open_branch()."""
        repos = self.open_repository()

        try:
            branch = OptimizedBranch(repos, self.branch_path)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_WC_NOT_DIRECTORY:
                raise NotBranchError(path=self.url)
            raise

        branch.bzrdir = self
        return branch

    def clone(self, path):
        raise NotImplementedError(self.clone)

    # Subversion has all-in-one, so a repository is always present
    find_repository = open_repository

    # Working trees never exist on Subversion repositories
    def open_workingtree(self, _unsupported=False):
        return SvnWorkingTree(self, self.local_path, self.open_branch())

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

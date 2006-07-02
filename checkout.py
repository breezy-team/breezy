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
from bzrlib.bzrdir import BzrDirFormat, BzrDir
from bzrlib.delta import compare_trees
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
from repository import SvnRepository, escape_svn_path, SVN_PROP_BZR_MERGE
from scheme import BranchingScheme
from transport import (SvnRaTransport, svn_config, 
                       svn_to_bzr_url) 
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
        self.client_ctx = svn.client.create_context()
        self.client_ctx.log_msg_func2 = svn.client.svn_swig_py_get_commit_log_func
        self.client_ctx.log_msg_baton2 = self.log_message_func

        self._set_inventory(self.read_working_inventory())
        mutter('working inv: %r' % self.read_working_inventory().entries())

        self.base_revid = branch.repository.generate_revision_id(
                    self.base_revnum, branch.branch_path)
        mutter('basis inv: %r' % self.basis_tree().inventory.entries())
        self.controldir = os.path.join(self.basedir, svn.wc.get_adm_dir(), 'bzr')
        try:
            os.makedirs(self.controldir)
            os.makedirs(os.path.join(self.controldir, 'lock'))
        except OSError:
            pass
        control_transport = bzrdir.transport.clone(os.path.join(svn.wc.get_adm_dir(), 'bzr'))
        self._control_files = LockableFiles(control_transport, 'lock', LockDir)

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
        try:
            dir_add(wc, "")
        finally:
            svn.wc.adm_close(wc)

        return ignores

    def _write_inventory(self, inv):
        pass

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
                        yield os.path.join(
                                self.branch.branch_path.strip("/"), 
                                subrelpath)
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
                return ("NEW-" + escape_svn_path(entry.url[len(entry.repos):].strip("/")), None)
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
                    try:
                        add_dir_to_inv(subrelpath, subwc, id)
                    finally:
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
        try:
            update_settings(wc, "")
        finally:
            svn.wc.adm_close(wc)
        self.base_revid = revid


    def log_message_func(self, items, pool):
        """ Simple log message provider for unit tests. """
        return self._message

    def commit(self, message=None, revprops=None, timestamp=None, timezone=None, committer=None, rev_id=None, allow_pointless=True, 
            strict=False, verbose=False, local=False, reporter=None, config=None, specific_files=None):
        assert timestamp is None
        assert timezone is None
        assert rev_id is None

        if specific_files:
            specific_files = [self.abspath(x).encode('utf8') for x in specific_files]
        else:
            specific_files = [self.basedir.encode('utf8')]

        assert isinstance(message, basestring)
        self._message = message

        commit_info = svn.client.commit3(specific_files, True, False, self.client_ctx)

        revid = self.branch.repository.generate_revision_id(commit_info.revision, self.branch.branch_path)

        self.base_revid = revid
        self.branch._revision_history.append(revid)

        return revid

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
        if stop_revision is None:
            stop_revision = self.branch.last_revision()
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = self.branch.repository.parse_revision_id(stop_revision)[1]
        fetched = svn.client.update(self.basedir, rev, True, self.client_ctx)
        self.base_revid = self.branch.repository.generate_revision_id(fetched, self.branch.branch_path)
        return fetched-rev.value.number

    def get_file_sha1(self, file_id, path=None):
        if not path:
            path = self._inventory.id2path(file_id)

        return fingerprint_file(open(self.abspath(path)))['sha1']

    def _get_base_merges(self):
        return self.branch.repository._get_dir_prop(self.branch.branch_path, 
                                            self.base_revnum, 
                                            SVN_PROP_BZR_MERGE, "")


    def set_pending_merges(self, merges):
        merged = self._get_base_merges()
        if len(merges) > 0:
            merged += "\t".join(merges) + "\n"

        wc = self._get_wc(write_lock=True)
        try:
            svn.wc.prop_set2(SVN_PROP_BZR_MERGE, merged, self.basedir, wc, 
            False)
        finally:
            svn.wc.adm_close(wc)

    def add_pending_merge(self, revid):
        merges = self.pending_merges()
        merges.append(revid)
        self.set_pending_merges(existing)

    def pending_merges(self):
        merged = self._get_base_merges().splitlines()
        wc = self._get_wc()
        try:
            set_merged = svn.wc.prop_get(SVN_PROP_BZR_MERGE, 
                                         self.basedir, wc).splitlines()
        finally:
            svn.wc.adm_close(wc)

        assert (len(merged) == len(set_merged) or 
               len(merged)+1 == len(set_merged))

        if len(set_merged) > len(merged):
            return set_merged[-1].split("\t")

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


class SvnCheckout(BzrDir):
    def __init__(self, transport, format):
        super(SvnCheckout, self).__init__(transport, format)
        self.local_path = transport.local_abspath(".")
        
        # Open related remote repository + branch
        wc = svn.wc.adm_open3(None, self.local_path, False, 0, None)
        try:
            svn_url = svn.wc.entry(self.local_path, wc, True).url
        finally:
            svn.wc.adm_close(wc)

        bzr_url = svn_to_bzr_url(svn_url)

        self.remote_transport = SvnRaTransport(svn_url)
        self.svn_root_transport = self.remote_transport.get_root()
        self.root_transport = self.transport = transport
        self.branch_path = svn_url[len(svn_to_bzr_url(self.svn_root_transport.base)):]
        self.scheme = BranchingScheme.guess_scheme(self.branch_path)
        mutter('scheme for %r is %r' % (self.branch_path, self.scheme))
        if not self.scheme.is_branch(self.branch_path):
            raise NotBranchError(path=self.transport.base)

    def clone(self, path):
        raise NotImplementedError(self.clone)

    def open_workingtree(self, _unsupported=False):
        return SvnWorkingTree(self, self.local_path, self.open_branch())

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
        repos = SvnRepository(self, self.svn_root_transport)
        repos._format = self._format
        return repos

    # Subversion has all-in-one, so a repository is always present
    find_repository = open_repository

    def create_workingtree(self, revision_id=None):
        raise NotImplementedError(self.create_workingtree)

    def create_branch(self):
        """See BzrDir.create_branch()."""
        raise NotImplementedError(self.create_branch)

    def open_branch(self, unsupported=True):
        """See BzrDir.open_branch()."""
        repos = self.open_repository()

        try:
            branch = SvnBranch(self.root_transport.base, repos, self.branch_path)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_WC_NOT_DIRECTORY:
               raise NotBranchError(path=self.url)
            raise
 
        branch.bzrdir = self
        return branch


class SvnWorkingTreeDirFormat(BzrDirFormat):
    _lock_class = TransportLock

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        if transport.has(svn.wc.get_adm_dir()):
            return format

        raise NotBranchError(path=transport.base)

    def _open(self, transport):
        return SvnCheckout(transport, self)

    def get_format_string(self):
        return 'Subversion Local Checkout'

    def get_format_description(self):
        return 'Subversion Local Checkout'

    def initialize_on_transport(self, transport):
        raise NotImplementedError(self.initialize_on_transport)

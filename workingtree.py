# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>

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
"""Checkouts and working trees (working copies)."""

import bzrlib
from bzrlib.branch import PullResult
from bzrlib.bzrdir import BzrDirFormat, BzrDir
from bzrlib.errors import (InvalidRevisionId, NotBranchError, NoSuchFile,
                           NoRepositoryPresent, BzrError)
from bzrlib.inventory import Inventory, InventoryFile, InventoryLink
from bzrlib.lockable_files import TransportLock, LockableFiles
from bzrlib.lockdir import LockDir
from bzrlib.osutils import file_kind, fingerprint_file
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
from bzrlib.tree import RevisionTree
from bzrlib.transport.local import LocalTransport
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat

from branch import SvnBranch
from convert import SvnConverter
from errors import LocalCommitsUnsupported
from repository import (SvnRepository, SVN_PROP_BZR_MERGE,
                        SVN_PROP_SVK_MERGE, SVN_PROP_BZR_FILEIDS, 
                        SVN_PROP_BZR_REVISION_ID, SVN_PROP_BZR_REVISION_INFO,
                        revision_id_to_svk_feature, generate_revision_metadata) 
from revids import escape_svn_path
from scheme import BranchingScheme
from transport import (SvnRaTransport, svn_config, bzr_to_svn_url, 
                       _create_auth_baton) 
from tree import SvnBasisTree

from copy import copy
import os
import urllib

import svn.core, svn.wc
from svn.core import SubversionException, Pool

from errors import NoCheckoutSupport
from format import get_rich_root_format

class WorkingTreeInconsistent(BzrError):
    _fmt = """Working copy is in inconsistent state (%(min_revnum)d:%(max_revnum)d)"""

    def __init__(self, min_revnum, max_revnum):
        self.min_revnum = min_revnum
        self.max_revnum = max_revnum


class SvnWorkingTree(WorkingTree):
    """WorkingTree implementation that uses a Subversion Working Copy for storage."""
    def __init__(self, bzrdir, local_path, branch):
        self._format = SvnWorkingTreeFormat()
        self.basedir = local_path
        self.bzrdir = bzrdir
        self._branch = branch
        self.base_revnum = 0
        self.pool = Pool()
        self.client_ctx = svn.client.create_context()
        self.client_ctx.config = svn_config
        self.client_ctx.log_msg_func2 = \
                svn.client.svn_swig_py_get_commit_log_func
        self.client_ctx.auth_baton = _create_auth_baton(self.pool)

        self._get_wc()
        status = svn.wc.revision_status(self.basedir, None, True, None, None)
        if status.min_rev != status.max_rev:
            #raise WorkingTreeInconsistent(status.min_rev, status.max_rev)
            rev = svn.core.svn_opt_revision_t()
            rev.kind = svn.core.svn_opt_revision_number
            rev.value.number = status.max_rev
            assert status.max_rev == svn.client.update(self.basedir, rev,
                                     True, self.client_ctx, Pool())

        self.base_revnum = status.max_rev
        self.base_tree = SvnBasisTree(self)
        self.base_revid = branch.repository.generate_revision_id(
                    self.base_revnum, branch.branch_path, bzrdir.scheme)

        self.read_working_inventory()

        self.controldir = os.path.join(self.basedir, svn.wc.get_adm_dir(), 
                                       'bzr')
        try:
            os.makedirs(self.controldir)
            os.makedirs(os.path.join(self.controldir, 'lock'))
        except OSError:
            pass
        control_transport = bzrdir.transport.clone(os.path.join(
                                                   svn.wc.get_adm_dir(), 'bzr'))
        self._control_files = LockableFiles(control_transport, 'lock', LockDir)

    def get_ignore_list(self):
        ignores = set([svn.wc.get_adm_dir()])
        ignores.update(svn.wc.get_default_ignores(svn_config))

        def dir_add(wc, prefix):
            ignorestr = svn.wc.prop_get(svn.core.SVN_PROP_IGNORE, 
                                        self.abspath(prefix).rstrip("/"), wc)
            if ignorestr is not None:
                for pat in ignorestr.splitlines():
                    ignores.add("./"+os.path.join(prefix, pat))

            entries = svn.wc.entries_read(wc, False)
            for entry in entries:
                if entry == "":
                    continue

                if entries[entry].kind != svn.core.svn_node_dir:
                    continue

                subprefix = os.path.join(prefix, entry)

                subwc = svn.wc.adm_open3(wc, self.abspath(subprefix), False, 
                                         0, None)
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

    def is_control_filename(self, path):
        return svn.wc.is_adm_dir(path)

    def remove(self, files, verbose=False, to_file=None):
        # FIXME: Use to_file argument
        # FIXME: Use verbose argument
        assert isinstance(files, list)
        wc = self._get_wc(write_lock=True)
        try:
            for file in files:
                svn.wc.delete2(self.abspath(file), wc, None, None, None)
        finally:
            svn.wc.adm_close(wc)

        for file in files:
            self._change_fileid_mapping(None, file)
        self.read_working_inventory()

    def _get_wc(self, relpath="", write_lock=False):
        return svn.wc.adm_open3(None, self.abspath(relpath).rstrip("/"), 
                                write_lock, 0, None)

    def _get_rel_wc(self, relpath, write_lock=False):
        dir = os.path.dirname(relpath)
        file = os.path.basename(relpath)
        return (self._get_wc(dir, write_lock), file)

    def move(self, from_paths, to_dir=None, after=False, **kwargs):
        # FIXME: Use after argument
        assert after != True
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_working
        for entry in from_paths:
            try:
                to_wc = self._get_wc(to_dir, write_lock=True)
                svn.wc.copy(self.abspath(entry), to_wc, 
                            os.path.basename(entry), None, None)
            finally:
                svn.wc.adm_close(to_wc)
            try:
                from_wc = self._get_wc(write_lock=True)
                svn.wc.delete2(self.abspath(entry), from_wc, None, None, None)
            finally:
                svn.wc.adm_close(from_wc)
            new_name = "%s/%s" % (to_dir, os.path.basename(entry))
            self._change_fileid_mapping(self.inventory.path2id(entry), new_name)
            self._change_fileid_mapping(None, entry)

        self.read_working_inventory()

    def rename_one(self, from_rel, to_rel, after=False):
        # FIXME: Use after
        assert after != True
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        (to_wc, to_file) = self._get_rel_wc(to_rel, write_lock=True)
        from_id = self.inventory.path2id(from_rel)
        try:
            svn.wc.copy(self.abspath(from_rel), to_wc, to_file, None, None)
            svn.wc.delete2(self.abspath(from_rel), to_wc, None, None, None)
        finally:
            svn.wc.adm_close(to_wc)
        self._change_fileid_mapping(None, from_rel)
        self._change_fileid_mapping(from_id, to_rel)
        self.read_working_inventory()

    def path_to_file_id(self, revnum, current_revnum, path):
        """Generate a bzr file id from a Subversion file name. 
        
        :param revnum: Revision number.
        :param path: Absolute path.
        :return: Tuple with file id and revision id.
        """
        assert isinstance(revnum, int) and revnum >= 0
        assert isinstance(path, basestring)

        (_, rp) = self.branch.scheme.unprefix(path)
        entry = self.base_tree.id_map[rp]
        assert entry[0] is not None
        assert isinstance(entry[0], str), "fileid %r for %r is not a string" % (entry[0], path)
        return entry

    def read_working_inventory(self):
        inv = Inventory()

        def add_file_to_inv(relpath, id, revid, parent_id):
            """Add a file to the inventory."""
            if os.path.islink(self.abspath(relpath)):
                file = InventoryLink(id, os.path.basename(relpath), parent_id)
                file.revision = revid
                file.symlink_target = os.readlink(self.abspath(relpath))
                file.text_sha1 = None
                file.text_size = None
                file.executable = False
                inv.add(file)
            else:
                file = InventoryFile(id, os.path.basename(relpath), parent_id)
                file.revision = revid
                try:
                    data = fingerprint_file(open(self.abspath(relpath)))
                    file.text_sha1 = data['sha1']
                    file.text_size = data['size']
                    file.executable = self.is_executable(id, relpath)
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

        def find_ids(entry, rootwc):
            relpath = urllib.unquote(entry.url[len(entry.repos):].strip("/"))
            assert entry.schedule in (svn.wc.schedule_normal, 
                                      svn.wc.schedule_delete,
                                      svn.wc.schedule_add,
                                      svn.wc.schedule_replace)
            if entry.schedule == svn.wc.schedule_normal:
                assert entry.revision >= 0
                # Keep old id
                return self.path_to_file_id(entry.cmt_rev, entry.revision, 
                        relpath)
            elif entry.schedule == svn.wc.schedule_delete:
                return (None, None)
            elif (entry.schedule == svn.wc.schedule_add or 
                  entry.schedule == svn.wc.schedule_replace):
                # See if the file this file was copied from disappeared
                # and has no other copies -> in that case, take id of other file
                if (entry.copyfrom_url and 
                    list(find_copies(entry.copyfrom_url)) == [relpath]):
                    return self.path_to_file_id(entry.copyfrom_rev, 
                        entry.revision, entry.copyfrom_url[len(entry.repos):])
                ids = self._get_new_file_ids(rootwc)
                if ids.has_key(relpath):
                    return (ids[relpath], None)
                return ("NEW-" + escape_svn_path(entry.url[len(entry.repos):].strip("/")), None)

        def add_dir_to_inv(relpath, wc, parent_id):
            entries = svn.wc.entries_read(wc, False)
            entry = entries[""]
            assert parent_id is None or isinstance(parent_id, str), \
                    "%r is not a string" % parent_id
            (id, revid) = find_ids(entry, rootwc)
            if id is None:
                mutter('no id for %r' % entry.url)
                return
            assert revid is None or isinstance(revid, str), "%r is not a string" % revid
            assert isinstance(id, str), "%r is not a string" % id

            # First handle directory itself
            inv.add_path(relpath, 'directory', id, parent_id).revision = revid
            if relpath == "":
                inv.revision_id = revid

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
                    (subid, subrevid) = find_ids(entry, rootwc)
                    if subid:
                        add_file_to_inv(subrelpath, subid, subrevid, id)
                    else:
                        mutter('no id for %r' % entry.url)

        rootwc = self._get_wc() 
        try:
            add_dir_to_inv("", rootwc, None)
        finally:
            svn.wc.adm_close(rootwc)

        self._set_inventory(inv, dirty=False)
        return inv

    def set_last_revision(self, revid):
        mutter('setting last revision to %r' % revid)
        if revid is None or revid == NULL_REVISION:
            self.base_revid = revid
            self.base_revnum = 0
            self.base_tree = RevisionTree(self, Inventory(), revid)
            return

        rev = self.branch.lookup_revision_id(revid)
        self.base_revnum = rev
        self.base_revid = revid
        self.base_tree = SvnBasisTree(self)

        # TODO: Implement more efficient version
        newrev = self.branch.repository.get_revision(revid)
        newrevtree = self.branch.repository.revision_tree(revid)

        def update_settings(wc, path):
            id = newrevtree.inventory.path2id(path)
            mutter("Updating settings for %r" % id)
            revnum = self.branch.lookup_revision_id(
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

    def commit(self, message=None, message_callback=None, revprops=None, 
               timestamp=None, timezone=None, committer=None, rev_id=None, 
               allow_pointless=True, strict=False, verbose=False, local=False, 
               reporter=None, config=None, specific_files=None):
        # FIXME: Use allow_pointless
        # FIXME: Use verbose
        # FIXME: Use reporter
        # FIXME: Use strict
        if local:
            raise LocalCommitsUnsupported()

        if specific_files:
            specific_files = [self.abspath(x).encode('utf8') for x in specific_files]
        else:
            specific_files = [self.basedir.encode('utf8')]

        if message_callback is not None:
            def log_message_func(items, pool):
                """ Simple log message provider for unit tests. """
                return message_callback(self).encode("utf-8")
        else:
            assert isinstance(message, basestring)
            def log_message_func(items, pool):
                """ Simple log message provider for unit tests. """
                return message.encode("utf-8")

        self.client_ctx.log_msg_baton2 = log_message_func
        if rev_id is not None:
            extra = "%d %s\n" % (self.branch.revno()+1, rev_id)
        else:
            extra = ""
        wc = self._get_wc(write_lock=True)
        try:
            svn.wc.prop_set(SVN_PROP_BZR_REVISION_ID+str(self.branch.scheme), 
                             self._get_bzr_revids() + extra,
                             self.basedir, wc)
            svn.wc.prop_set(SVN_PROP_BZR_REVISION_INFO, 
                             generate_revision_metadata(timestamp, 
                                                        timezone, 
                                                        committer,
                                                        revprops),
                             self.basedir, wc)
        finally:
            svn.wc.adm_close(wc)

        try:
            commit_info = svn.client.commit3(specific_files, True, False, 
                                         self.client_ctx)
        except:
            # Reset properties so the next subversion commit won't 
            # accidently set these properties.
            wc = self._get_wc(write_lock=True)
            svn.wc.prop_set(SVN_PROP_BZR_REVISION_ID+str(self.branch.scheme), 
                             self._get_bzr_revids(), self.basedir, wc)
            svn.wc.prop_set(SVN_PROP_BZR_REVISION_INFO, 
                self.branch.repository.branchprop_list.get_property(
                self.branch.branch_path, self.base_revnum, 
                SVN_PROP_BZR_REVISION_INFO, ""), 
                self.basedir, wc)
            svn.wc.adm_close(wc)
            raise

        self.client_ctx.log_msg_baton2 = None

        revid = self.branch.generate_revision_id(commit_info.revision)

        self.base_revid = revid
        self.base_revnum = commit_info.revision
        self.base_tree = SvnBasisTree(self)

        self.branch.repository._latest_revnum = commit_info.revision

        #FIXME: Use public API:
        if self.branch._revision_history is not None:
            self.branch._revision_history.append(revid)

        return revid

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        assert isinstance(recurse, bool)
        if action is None:
            action = bzrlib.add.AddAction()
        # TODO: use action
        if not file_list:
            # no paths supplied: add the entire tree.
            file_list = [u'.']
        ignored = {}
        added = []

        for file_path in file_list:
            todo = []
            file_path = os.path.abspath(file_path)
            f = self.relpath(file_path)
            wc = self._get_wc(os.path.dirname(f), write_lock=True)
            try:
                if not self.inventory.has_filename(f):
                    if save:
                        mutter('adding %r' % file_path)
                        svn.wc.add2(file_path, wc, None, 0, None, None, None)
                    added.append(file_path)
                if recurse and file_kind(file_path) == 'directory':
                    # Filter out ignored files and update ignored
                    for c in os.listdir(file_path):
                        if self.is_control_filename(c):
                            continue
                        c_path = os.path.join(file_path, c)
                        ignore_glob = self.is_ignored(c)
                        if ignore_glob is not None:
                            ignored.setdefault(ignore_glob, []).append(c_path)
                        todo.append(c_path)
            finally:
                svn.wc.adm_close(wc)
            if todo != []:
                cadded, cignored = self.smart_add(todo, recurse, action, save)
                added.extend(cadded)
                ignored.update(cignored)
        return added, ignored

    def add(self, files, ids=None, kinds=None):
        # TODO: Use kinds
        if isinstance(files, str):
            files = [files]
            if isinstance(ids, str):
                ids = [ids]
        if ids:
            ids = copy(ids)
            ids.reverse()
        assert isinstance(files, list)
        for f in files:
            wc = self._get_wc(os.path.dirname(f), write_lock=True)
            try:
                try:
                    svn.wc.add2(os.path.join(self.basedir, f), wc, None, 0, 
                            None, None, None)
                    if ids:
                        self._change_fileid_mapping(ids.pop(), f, wc)
                except SubversionException, (_, num):
                    if num == svn.core.SVN_ERR_ENTRY_EXISTS:
                        continue
                    elif num == svn.core.SVN_ERR_WC_PATH_NOT_FOUND:
                        raise NoSuchFile(path=f)
                    raise
            finally:
                svn.wc.adm_close(wc)
        self.read_working_inventory()

    def basis_tree(self):
        if self.base_revid is None or self.base_revid == NULL_REVISION:
            return self.branch.repository.revision_tree(self.base_revid)

        return self.base_tree

    def pull(self, source, overwrite=False, stop_revision=None, 
             delta_reporter=None):
        # FIXME: Use delta_reporter
        # FIXME: Use overwrite
        result = PullResult()
        result.source_branch = source
        result.master_branch = None
        result.target_branch = self.branch
        (result.old_revno, result.old_revid) = self.branch.last_revision_info()
        if stop_revision is None:
            stop_revision = self.branch.last_revision()
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = self.branch.lookup_revision_id(stop_revision)
        fetched = svn.client.update(self.basedir, rev, True, self.client_ctx)
        self.base_revid = self.branch.repository.generate_revision_id(fetched, self.branch.branch_path)
        result.new_revid = self.branch.generate_revision_id(fetched)
        result.new_revno = self.branch.revision_id_to_revno(result.new_revid)
        return result

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        if not path:
            path = self._inventory.id2path(file_id)
        return fingerprint_file(open(self.abspath(path)))['sha1']

    def _change_fileid_mapping(self, id, path, wc=None):
        if wc is None:
            subwc = self._get_wc(write_lock=True)
        else:
            subwc = wc
        new_entries = self._get_new_file_ids(subwc)
        if id is None:
            if new_entries.has_key(path):
                del new_entries[path]
        else:
            assert isinstance(id, str)
            new_entries[path] = id
        committed = self.branch.repository.branchprop_list.get_property(
                self.branch.branch_path, 
                self.base_revnum, 
                SVN_PROP_BZR_FILEIDS, "")
        existing = committed + "".join(map(lambda (path, id): "%s\t%s\n" % (path, id), new_entries.items()))
        if existing != "":
            svn.wc.prop_set(SVN_PROP_BZR_FILEIDS, existing.encode("utf-8"), self.basedir, subwc)
        if wc is None:
            svn.wc.adm_close(subwc)

    def _get_new_file_ids(self, wc):
        committed = self.branch.repository.branchprop_list.get_property(
                self.branch.branch_path, self.base_revnum, 
                SVN_PROP_BZR_FILEIDS, "")
        existing = svn.wc.prop_get(SVN_PROP_BZR_FILEIDS, self.basedir, wc)
        if existing is None:
            return {}
        else:
            return dict(map(lambda x: str(x).split("\t"), 
                existing[len(committed):].splitlines()))

    def _get_bzr_revids(self):
        return self.branch.repository.branchprop_list.get_property(
                self.branch.branch_path, self.base_revnum, 
                SVN_PROP_BZR_REVISION_ID+str(self.branch.scheme), "")

    def _get_bzr_merges(self):
        return self.branch.repository.branchprop_list.get_property(
                self.branch.branch_path, self.base_revnum, 
                SVN_PROP_BZR_MERGE, "")

    def _get_svk_merges(self):
        return self.branch.repository.branchprop_list.get_property(
                self.branch.branch_path, self.base_revnum, 
                SVN_PROP_SVK_MERGE, "")

    def set_pending_merges(self, merges):
        wc = self._get_wc(write_lock=True)
        try:
            # Set bzr:merge
            if len(merges) > 0:
                bzr_merge = "\t".join(merges) + "\n"
            else:
                bzr_merge = ""

            svn.wc.prop_set(SVN_PROP_BZR_MERGE, 
                                 self._get_bzr_merges() + bzr_merge, 
                                 self.basedir, wc)

            # Set svk:merge
            svk_merge = ""
            for merge in merges:
                try:
                    svk_merge += revision_id_to_svk_feature(merge) + "\n"
                except InvalidRevisionId:
                    pass

            svn.wc.prop_set2(SVN_PROP_SVK_MERGE, 
                             self._get_svk_merges() + svk_merge, self.basedir, 
                             wc, False)
        finally:
            svn.wc.adm_close(wc)

    def add_pending_merge(self, revid):
        merges = self.pending_merges()
        merges.append(revid)
        self.set_pending_merges(merges)

    def pending_merges(self):
        merged = self._get_bzr_merges().splitlines()
        wc = self._get_wc()
        try:
            merged_data = svn.wc.prop_get(SVN_PROP_BZR_MERGE, self.basedir, wc)
            if merged_data is None:
                set_merged = []
            else:
                set_merged = merged_data.splitlines()
        finally:
            svn.wc.adm_close(wc)

        assert (len(merged) == len(set_merged) or 
               len(merged)+1 == len(set_merged))

        if len(set_merged) > len(merged):
            return set_merged[-1].split("\t")

        return []

    def _reset_data(self):
        pass

    def unlock(self):
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()



class SvnWorkingTreeFormat(WorkingTreeFormat):
    """Subversion working copy format."""
    def get_format_description(self):
        return "Subversion Working Copy"

    def initialize(self, a_bzrdir, revision_id=None):
        raise NotImplementedError(self.initialize)

    def open(self, a_bzrdir):
        raise NotImplementedError(self.initialize)


class SvnCheckout(BzrDir):
    """BzrDir implementation for Subversion checkouts (directories 
    containing a .svn subdirectory."""
    def __init__(self, transport, format):
        super(SvnCheckout, self).__init__(transport, format)
        self.local_path = transport.local_abspath(".")
        
        # Open related remote repository + branch
        wc = svn.wc.adm_open3(None, self.local_path, False, 0, None)
        try:
            svn_url = svn.wc.entry(self.local_path, wc, True).url
        finally:
            svn.wc.adm_close(wc)

        self.remote_transport = SvnRaTransport(svn_url)
        self.svn_root_transport = SvnRaTransport(self.remote_transport.get_repos_root())
        self.root_transport = self.transport = transport

        self.branch_path = svn_url[len(bzr_to_svn_url(self.svn_root_transport.base)):]
        self.scheme = BranchingScheme.guess_scheme(self.branch_path)
        mutter('scheme for %r is %r' % (self.branch_path, self.scheme))
        if not self.scheme.is_branch(self.branch_path) and not self.scheme.is_tag(self.branch_path):
            raise NotBranchError(path=self.transport.base)

    def clone(self, path, revision_id=None, force_new_repo=False):
        raise NotImplementedError(self.clone)

    def open_workingtree(self, _unsupported=False, recommend_upgrade=False):
        return SvnWorkingTree(self, self.local_path, self.open_branch())

    def sprout(self, url, revision_id=None, force_new_repo=False, 
               recurse='down'):
        # FIXME: honor force_new_repo
        # FIXME: Use recurse
        result = get_rich_root_format().initialize(url)
        repo = self.find_repository()
        repo.clone(result, revision_id)
        branch = self.open_branch()
        branch.sprout(result, revision_id)
        result.create_workingtree()
        return result

    def open_repository(self):
        raise NoRepositoryPresent(self)

    def find_repository(self):
        return SvnRepository(self, self.svn_root_transport)

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree().

        Not implemented for Subversion because having a .svn directory
        implies having a working copy.
        """
        raise NotImplementedError(self.create_workingtree)

    def create_branch(self):
        """See BzrDir.create_branch()."""
        raise NotImplementedError(self.create_branch)

    def open_branch(self, unsupported=True):
        """See BzrDir.open_branch()."""
        repos = self.find_repository()

        try:
            branch = SvnBranch(self.root_transport.base, repos, self.branch_path)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_WC_NOT_DIRECTORY:
                raise NotBranchError(path=self.base)
            raise
 
        branch.bzrdir = self
        return branch


class SvnWorkingTreeDirFormat(BzrDirFormat):
    """Working Tree implementation that uses Subversion working copies."""
    _lock_class = TransportLock

    @classmethod
    def probe_transport(klass, transport):
        format = klass()

        if isinstance(transport, LocalTransport) and \
            transport.has(svn.wc.get_adm_dir()):
            subr_version = svn.core.svn_subr_version()
            if subr_version.major == 1 and subr_version.minor < 4:
                raise NoCheckoutSupport()
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

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        if format is None:
            format = get_rich_root_format()
        return SvnConverter(format)

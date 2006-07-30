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
from bzrlib.decorators import needs_write_lock
from bzrlib.inventory import Inventory, ROOT_ID
import bzrlib.osutils as osutils
from bzrlib.progress import ProgressBar
from bzrlib.revision import Revision
from bzrlib.repository import InterRepository
from bzrlib.trace import mutter

from copy import copy
from cStringIO import StringIO
import md5
import os

from svn.core import SubversionException, Pool
import svn.core

from repository import (SvnRepository, SVN_PROP_BZR_MERGE, SVN_PROP_SVK_MERGE,
                SVN_PROP_BZR_REVPROP_PREFIX)
from tree import apply_txdelta_handler


def md5_strings(strings):
    s = md5.new()
    map(s.update, strings)
    return s.hexdigest()

class RevisionBuildEditor(svn.delta.Editor):
    def __init__(self, source, target, branch_path, revnum, prev_inventory, revid, svn_revprops, id_map, parent_branch, parent_id_map):
        self.branch_path = branch_path
        self.inventory = copy(prev_inventory)
        self.revid = revid
        self.revnum = revnum
        self.id_map = id_map
        self.parent_branch = parent_branch
        self.parent_id_map = parent_id_map
        self.source = source
        self.target = target
        self.transact = target.get_transaction()
        self.weave_store = target.weave_store
    
        self.dir_baserev = {}

        self._parent_ids = None
        self._revprops = {}
        self._svn_revprops = svn_revprops

    def _get_revision(self, revid):
        if self._parent_ids is None:
            self._parent_ids = ""

        parent_ids = self.source.revision_parents(revid, self._parent_ids)

        # Commit SVN revision properties to a Revision object
        rev = Revision(revision_id=revid, parent_ids=parent_ids)

        rev.timestamp = 1.0 * svn.core.secs_from_timestr(
            self._svn_revprops[2], None) #date
        rev.timezone = None

        rev.committer = self._svn_revprops[0] # author
        if rev.committer is None:
            rev.committer = ""
        rev.message = self._svn_revprops[1] # message

        rev.properties = self._revprops
        return rev

    def open_root(self, base_revnum, baton):
        if self.inventory.revision_id is None:
            self.dir_baserev[ROOT_ID] = []
        else:
            self.dir_baserev[ROOT_ID] = [self.inventory.revision_id]
        self.inventory.revision_id = self.revid
        return ROOT_ID

    def relpath(self, path):
        return path.strip("/")

    def delete_entry(self, path, revnum, parent_baton, pool):
        del self.inventory[self.inventory.path2id(path)]

    def close_directory(self, id):
        revid = self.revid

        if id != ROOT_ID:
            self.inventory[id].revision = revid

        file_weave = self.weave_store.get_weave_or_empty(id, self.transact)
        if not file_weave.has_version(revid):
            file_weave.add_lines(revid, self.dir_baserev[id], [])

    def add_directory(self, path, parent_baton, copyfrom_path, copyfrom_revnum, pool):
        file_id, revision_id = self.id_map[path]

        if copyfrom_path is not None:
            base_file_id, base_revid = self.source.path_to_file_id(copyfrom_revnum, os.path.join(self.parent_branch, copyfrom_path))
            if base_file_id == file_id: 
                self.dir_baserev[file_id] = [base_revid]
                ie = self.inventory[file_id]
                ie.revision = revision_id
                return file_id

        self.dir_baserev[file_id] = []
        ie = self.inventory.add_path(path, 'directory', file_id)
        if ie:
            ie.revision = revision_id

        return file_id

    def open_directory(self, path, parent_baton, base_revnum, pool):
        return self.add_directory(path, parent_baton, path, base_revnum, pool)

    def change_dir_prop(self, id, name, value, pool):
        if name == SVN_PROP_BZR_MERGE:
            if id != ROOT_ID:
                mutter('rogue %r on non-root directory' % SVN_PROP_BZR_MERGE)
                return
            
            self._parent_ids = value.splitlines()[-1]
        elif name == SVN_PROP_SVK_MERGE:
            if self._parent_ids is None:
                # Only set parents using svk:merge if no 
                # bzr:merge set.
                pass # FIXME 
        elif name.startswith(SVN_PROP_BZR_REVPROP_PREFIX):
            self._revprops[name[len(SVN_PROP_BZR_REVPROP_PREFIX):]] = value
        elif name in (svn.core.SVN_PROP_ENTRY_COMMITTED_DATE,
                      svn.core.SVN_PROP_ENTRY_COMMITTED_REV,
                      svn.core.SVN_PROP_ENTRY_LAST_AUTHOR,
                      svn.core.SVN_PROP_ENTRY_LOCK_TOKEN,
                      svn.core.SVN_PROP_ENTRY_UUID,
                      svn.core.SVN_PROP_EXECUTABLE):
            pass
        elif name.startswith(svn.core.SVN_PROP_WC_PREFIX):
            pass
        else:
            mutter('unsupported file property %r' % name)

    def change_file_prop(self, id, name, value, pool):
        if name == svn.core.SVN_PROP_EXECUTABLE: 
            # Strange, you'd expect executable to match svn.core.SVN_PROP_EXECUTABLE_VALUE, but that's not how SVN behaves.
            self.is_executable = (value != None)
        elif (name == svn.core.SVN_PROP_SPECIAL):
            self.is_symlink = (value != None)
        elif name == svn.core.SVN_PROP_ENTRY_COMMITTED_REV:
            self.last_file_rev = int(value)
        elif name in (svn.core.SVN_PROP_ENTRY_COMMITTED_DATE,
                      svn.core.SVN_PROP_ENTRY_LAST_AUTHOR,
                      svn.core.SVN_PROP_ENTRY_LOCK_TOKEN,
                      svn.core.SVN_PROP_ENTRY_UUID,
                      svn.core.SVN_PROP_MIME_TYPE):
            pass
        elif name.startswith(svn.core.SVN_PROP_WC_PREFIX):
            pass
        else:
            mutter('unsupported file property %r' % name)

    def add_file(self, path, parent_id, copyfrom_path, copyfrom_revnum, baton):
        self.is_symlink = False
        self.is_executable = None
        self.file_data = ""
        self.file_parents = []
        self.file_stream = None
        return path

    def open_file(self, path, parent_id, base_revnum, pool):
        self.is_executable = None
        file_id, revision_id = self.parent_id_map[path]
        self.is_symlink = (self.inventory[file_id].kind == 'symlink')
        file_weave = self.weave_store.get_weave_or_empty(file_id, self.transact)
        self.file_data = file_weave.get_text(revision_id)
        self.file_parents = [revision_id]
        self.file_stream = None
        return path

    def close_file(self, path, checksum):
        if self.file_stream is not None:
            self.file_stream.seek(0)
            lines = osutils.split_lines(self.file_stream.read())
        else:
            # Data didn't change or file is new
            lines = osutils.split_lines(self.file_data)

        actual_checksum = md5_strings(lines)
        assert checksum is None or checksum == actual_checksum

        file_id, revision_id = self.id_map[path]
        file_weave = self.weave_store.get_weave_or_empty(file_id, self.transact)
        if not file_weave.has_version(revision_id):
            file_weave.add_lines(revision_id, self.file_parents, lines)

        if file_id in self.inventory:
            ie = self.inventory[file_id]
        elif self.is_symlink:
            ie = self.inventory.add_path(path, 'symlink', file_id)
        else:
            ie = self.inventory.add_path(path, 'file', file_id)
        ie.revision = revision_id

        if self.is_symlink:
            ie.symlink_target = lines[0][len("link "):]
            ie.text_sha1 = None
            ie.text_size = None
            ie.text_id = None
        else:
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            if self.is_executable is not None:
                ie.executable = self.is_executable

        self.file_stream = None

    def close_edit(self):
        rev = self._get_revision(self.revid)
        self.inventory.revision_id = self.revid
        rev.inventory_sha1 = osutils.sha_string(
            bzrlib.xml5.serializer_v5.write_inventory_to_string(
                self.inventory))
        self.target.add_revision(self.revid, rev, self.inventory)

    def abort_edit(self):
        pass

    def apply_textdelta(self, file_id, base_checksum):
        actual_checksum = md5.new(self.file_data).hexdigest(),
        assert (base_checksum is None or base_checksum == actual_checksum,
            "base checksum mismatch: %r != %r" % (base_checksum, actual_checksum))
        self.file_stream = StringIO()
        return apply_txdelta_handler(StringIO(self.file_data), self.file_stream)


class InterSvnRepository(InterRepository):
    """Svn to any repository actions."""

    _matching_repo_format = None 
    """The format to test with - as yet there is no SvnRepoFormat."""

    @needs_write_lock
    def copy_content(self, revision_id=None, basis=None, pb=ProgressBar()):
        """See InterRepository.copy_content."""
        # Dictionary with paths as keys, revnums as values

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call self.target.add_revision() 
        # or self.target.add_inventory() each time
        if revision_id is None:
            path = ""
            until_revnum = self.source._latest_revnum
        else:
            (path, until_revnum) = self.source.parse_revision_id(revision_id)

        repos_root = svn.ra.get_repos_root(self.source.ra)
        
        needed = []
        parents = {}
        prev_revid = None
        for (branch, changes, revnum) in \
            self.source._log.follow_history(path, until_revnum):
            revid = self.source.generate_revision_id(revnum, branch)

            if prev_revid is not None:
                parents[prev_revid] = revid

            prev_revid = revid

            if not self.target.has_revision(revid):
                needed.append((branch, revnum, revid, changes))

        parents[prev_revid] = None

        num = 0
        needed.reverse()
        prev_revid = None
        for (branch, revnum, revid, changes) in needed:
            if pb is not None:
                pb.update('copying revision', num+1, len(needed)+1)
            num += 1

            parent_revid = parents[revid]

            if parent_revid is not None:
                (parent_branch, parent_revnum) = self.source.parse_revision_id(parent_revid)
            else:
                parent_revnum = 0
                parent_branch = None

            if parent_revid is None:
                parent_id_map = {"": (ROOT_ID, None)}
                id_map = self.source.get_fileid_map(revnum, branch)
                parent_inv = Inventory()
            elif prev_revid != parent_revid:
                parent_id_map = self.source.get_fileid_map(parent_revnum, parent_branch)
                id_map = self.source.get_fileid_map(revnum, branch)
                parent_inv = self.target.get_inventory(parent_revid)
            else:
                parent_id_map = copy(id_map)
                self.source.transform_fileid_map(self.source.uuid, 
                                        revnum, branch, 
                                        changes, id_map)
                parent_inv = prev_inv


            editor = RevisionBuildEditor(self.source, self.target, branch, 
                                         revnum, parent_inv, revid, 
                                     self.source._log.get_revision_info(revnum),
                                     id_map, parent_branch, parent_id_map)

            edit, edit_baton = svn.delta.make_editor(editor)


            if parent_branch is None:
                svn.ra.reparent(self.source.ra, repos_root)
            else:
                svn.ra.reparent(self.source.ra, "%s/%s" % (repos_root, parent_branch))

            pool = Pool()
            if parent_branch != branch:
                mutter('svn switch %r:%r -> %r:%r' % 
                               (parent_branch, parent_revnum, branch, revnum))
                reporter, reporter_baton = svn.ra.do_switch(self.source.ra, 
                           revnum, "", True, 
                           "%s/%s" % (repos_root, branch),
                           edit, edit_baton, pool)
            else:
                mutter('svn update -r %r:%r %r' % 
                               (parent_revnum, revnum, branch))
                reporter, reporter_baton = svn.ra.do_update(self.source.ra, 
                           revnum, "", True, 
                           edit, edit_baton, pool)

            # Report status of existing paths
            svn.ra.reporter2_invoke_set_path(reporter, reporter_baton, 
                "", parent_revnum, False, None)

            svn.ra.reporter2_invoke_finish_report(reporter, reporter_baton)

            svn.ra.reparent(self.source.ra, repos_root)

            prev_inv = editor.inventory
            prev_revid = revid

        if pb is not None:
            pb.clear()


    @needs_write_lock
    def fetch(self, revision_id=None, pb=ProgressBar()):
        """Fetch revisions. """
        self.copy_content(revision_id=revision_id, pb=pb)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        return isinstance(source, SvnRepository)




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
"""Fetching revisions from Subversion repositories in batches."""

import bzrlib
from bzrlib import osutils, ui, urlutils
from bzrlib.inventory import Inventory
from bzrlib.revision import Revision
from bzrlib.repository import InterRepository
from bzrlib.trace import mutter

from copy import copy
from cStringIO import StringIO
import md5

from svn.core import Pool
import svn.core

from fileids import generate_file_id
from repository import (SvnRepository, SVN_PROP_BZR_ANCESTRY, 
                SVN_PROP_SVK_MERGE, SVN_PROP_BZR_MERGE,
                SVN_PROP_BZR_PREFIX, SVN_PROP_BZR_REVISION_INFO, 
                SVN_PROP_BZR_BRANCHING_SCHEME, SVN_PROP_BZR_REVISION_ID,
                SVN_PROP_BZR_FILEIDS, SvnRepositoryFormat, 
                parse_revision_metadata, parse_merge_property)
from tree import apply_txdelta_handler


def md5_strings(strings):
    """Return the MD5sum of the concatenation of strings.

    :param strings: Strings to find the MD5sum of.
    :return: MD5sum
    """
    s = md5.new()
    map(s.update, strings)
    return s.hexdigest()


class RevisionBuildEditor(svn.delta.Editor):
    """Implementation of the Subversion commit editor interface that builds a 
    Bazaar revision.
    """
    def __init__(self, source, target, branch_path, prev_inventory, revid, 
                 svn_revprops, id_map, scheme):
        self.branch_path = branch_path
        self.old_inventory = prev_inventory
        self.inventory = copy(prev_inventory)
        self.revid = revid
        self.id_map = id_map
        self.scheme = scheme
        self.source = source
        self.target = target
        self.transact = target.get_transaction()
        self.weave_store = target.weave_store
        self.dir_baserev = {}
        self._bzr_merges = []
        self._svk_merges = []
        self._revinfo = None
        self._svn_revprops = svn_revprops
        self._premature_deletes = set()
        self.pool = Pool()

    def _get_revision(self, revid):
        """Creates the revision object.

        :param revid: Revision id of the revision to create.
        """
        parent_ids = self.source.revision_parents(revid, self._bzr_merges)

        # Commit SVN revision properties to a Revision object
        rev = Revision(revision_id=revid, parent_ids=parent_ids)

        if self._svn_revprops[2] is not None:
            rev.timestamp = 1.0 * svn.core.secs_from_timestr(
                self._svn_revprops[2], None) #date
        else:
            rev.timestamp = 0 # FIXME: Obtain repository creation time
        rev.timezone = None

        rev.committer = self._svn_revprops[0] # author
        if rev.committer is None:
            rev.committer = ""
        rev.message = self._svn_revprops[1] # message

        if self._revinfo:
            parse_revision_metadata(self._revinfo, rev)

        return rev

    def open_root(self, base_revnum, baton):
        if self.old_inventory.root is None:
            # First time the root is set
            file_id = generate_file_id(self.source, self.revid, "")
            self.dir_baserev[file_id] = []
        else:
            assert self.old_inventory.root.revision is not None
            if self.id_map.has_key(""):
                file_id = self.id_map[""]
            else:
                file_id = self.old_inventory.root.file_id
            self.dir_baserev[file_id] = [self.old_inventory.root.revision]

        if self.inventory.root is not None and \
                file_id == self.inventory.root.file_id:
            ie = self.inventory.root
        else:
            ie = self.inventory.add_path("", 'directory', file_id)
        ie.revision = self.revid
        return file_id

    def _get_existing_id(self, parent_id, path):
        if self.id_map.has_key(path):
            return self.id_map[path]
        return self._get_old_id(parent_id, path)

    def _get_old_id(self, parent_id, old_path):
        return self.old_inventory[parent_id].children[urlutils.basename(old_path)].file_id

    def _get_new_id(self, parent_id, new_path):
        if self.id_map.has_key(new_path):
            return self.id_map[new_path]
        return generate_file_id(self.source, self.revid, new_path)

    def delete_entry(self, path, revnum, parent_id, pool):
        path = path.decode("utf-8")
        if path in self._premature_deletes:
            self._premature_deletes.remove(path)
        else:
            self.inventory.remove_recursive_id(self._get_old_id(parent_id, path))

    def close_directory(self, id):
        self.inventory[id].revision = self.revid

        # Only record root if the target repository supports it
        if self.target.supports_rich_root:
            file_weave = self.weave_store.get_weave_or_empty(id, self.transact)
            if not file_weave.has_version(self.revid):
                file_weave.add_lines(self.revid, self.dir_baserev[id], [])

    def add_directory(self, path, parent_id, copyfrom_path, copyfrom_revnum, 
                      pool):
        path = path.decode("utf-8")
        file_id = self._get_new_id(parent_id, path)

        self.dir_baserev[file_id] = []
        if file_id in self.inventory:
            # This directory was moved here from somewhere else, but the 
            # other location hasn't been removed yet. 
            if copyfrom_path is None:
                # FIXME: This should never happen!
                copyfrom_path = self.old_inventory.id2path(file_id)
            assert copyfrom_path == self.old_inventory.id2path(file_id)
            assert copyfrom_path not in self._premature_deletes
            self._premature_deletes.add(copyfrom_path)
            self.inventory.rename(file_id, parent_id, urlutils.basename(path))
            ie = self.inventory[file_id]
        else:
            ie = self.inventory.add_path(path, 'directory', file_id)
        ie.revision = self.revid

        return file_id

    def open_directory(self, path, parent_id, base_revnum, pool):
        assert base_revnum >= 0
        base_file_id = self._get_old_id(parent_id, path)
        base_revid = self.old_inventory[base_file_id].revision
        file_id = self._get_existing_id(parent_id, path)
        if file_id == base_file_id:
            self.dir_baserev[file_id] = [base_revid]
            ie = self.inventory[file_id]
        else:
            # Replace if original was inside this branch
            # change id of base_file_id to file_id
            ie = self.inventory[base_file_id]
            for name in ie.children:
                ie.children[name].parent_id = file_id
            # FIXME: Don't touch inventory internals
            del self.inventory._byid[base_file_id]
            self.inventory._byid[file_id] = ie
            ie.file_id = file_id
            self.dir_baserev[file_id] = []
        ie.revision = self.revid
        return file_id

    def change_dir_prop(self, id, name, value, pool):
        if name == SVN_PROP_BZR_BRANCHING_SCHEME:
            if id != self.inventory.root.file_id:
                mutter('rogue %r on non-root directory' % name)
                return
        elif name == SVN_PROP_BZR_ANCESTRY+str(self.scheme):
            if id != self.inventory.root.file_id:
                mutter('rogue %r on non-root directory' % name)
                return
            
            self._bzr_merges = parse_merge_property(value.splitlines()[-1])
        elif (name.startswith(SVN_PROP_BZR_ANCESTRY) or 
              name.startswith(SVN_PROP_BZR_REVISION_ID)):
            pass
        elif name == SVN_PROP_SVK_MERGE:
            self._svk_merges = None # Force Repository.revision_parents() to look it up
        elif name == SVN_PROP_BZR_REVISION_INFO:
            if id != self.inventory.root.file_id:
                mutter('rogue %r on non-root directory' % SVN_PROP_BZR_REVISION_INFO)
                return
 
            self._revinfo = value
        elif name in (svn.core.SVN_PROP_ENTRY_COMMITTED_DATE,
                      svn.core.SVN_PROP_ENTRY_COMMITTED_REV,
                      svn.core.SVN_PROP_ENTRY_LAST_AUTHOR,
                      svn.core.SVN_PROP_ENTRY_LOCK_TOKEN,
                      svn.core.SVN_PROP_ENTRY_UUID,
                      svn.core.SVN_PROP_EXECUTABLE):
            pass
        elif name.startswith(svn.core.SVN_PROP_WC_PREFIX):
            pass
        elif name in (SVN_PROP_BZR_MERGE, SVN_PROP_BZR_FILEIDS):
            pass
        elif (name.startswith(svn.core.SVN_PROP_PREFIX) or
              name.startswith(SVN_PROP_BZR_PREFIX)):
            mutter('unsupported dir property %r' % name)

    def change_file_prop(self, id, name, value, pool):
        if name == svn.core.SVN_PROP_EXECUTABLE: 
            # You'd expect executable to match 
            # svn.core.SVN_PROP_EXECUTABLE_VALUE, but that's not 
            # how SVN behaves. It appears to consider the presence 
            # of the property sufficient to mark it executable.
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
        elif (name.startswith(svn.core.SVN_PROP_PREFIX) or
              name.startswith(SVN_PROP_BZR_PREFIX)):
            mutter('unsupported file property %r' % name)

    def add_file(self, path, parent_id, copyfrom_path, copyfrom_revnum, baton):
        path = path.decode("utf-8")
        self.is_symlink = False
        self.is_executable = None
        self.file_data = ""
        self.file_parents = []
        self.file_stream = None
        self.file_id = self._get_new_id(parent_id, path)
        if self.file_id in self.inventory:
            # This file was moved here from somewhere else, but the 
            # other location hasn't been removed yet. 
            if copyfrom_path is None:
                # FIXME: This should never happen!
                copyfrom_path = self.old_inventory.id2path(self.file_id)
            assert copyfrom_path == self.old_inventory.id2path(self.file_id)
            assert copyfrom_path not in self._premature_deletes
            self._premature_deletes.add(copyfrom_path)
            self.inventory.rename(self.file_id, parent_id, urlutils.basename(path))
        return path

    def open_file(self, path, parent_id, base_revnum, pool):
        base_file_id = self._get_old_id(parent_id, path)
        base_revid = self.old_inventory[base_file_id].revision
        self.file_id = self._get_existing_id(parent_id, path)
        self.is_executable = None
        self.is_symlink = (self.inventory[base_file_id].kind == 'symlink')
        file_weave = self.weave_store.get_weave_or_empty(base_file_id, 
                                                         self.transact)
        self.file_data = file_weave.get_text(base_revid)
        self.file_stream = None
        if self.file_id == base_file_id:
            self.file_parents = [base_revid]
        else:
            # Replace
            del self.inventory[base_file_id]
            self.file_parents = []
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

        file_weave = self.weave_store.get_weave_or_empty(self.file_id, 
                                                         self.transact)
        if not file_weave.has_version(self.revid):
            file_weave.add_lines(self.revid, self.file_parents, lines)

        if self.file_id in self.inventory:
            ie = self.inventory[self.file_id]
        elif self.is_symlink:
            ie = self.inventory.add_path(path, 'symlink', self.file_id)
        else:
            ie = self.inventory.add_path(path, 'file', self.file_id)
        ie.revision = self.revid

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
        assert len(self._premature_deletes) == 0
        rev = self._get_revision(self.revid)
        self.inventory.revision_id = self.revid
        rev.inventory_sha1 = osutils.sha_string(
            bzrlib.xml5.serializer_v5.write_inventory_to_string(
                self.inventory))
        self.target.add_revision(self.revid, rev, self.inventory)
        self.pool.destroy()

    def abort_edit(self):
        pass

    def apply_textdelta(self, file_id, base_checksum):
        actual_checksum = md5.new(self.file_data).hexdigest(),
        assert (base_checksum is None or base_checksum == actual_checksum,
            "base checksum mismatch: %r != %r" % (base_checksum, 
                                                  actual_checksum))
        self.file_stream = StringIO()
        return apply_txdelta_handler(StringIO(self.file_data), 
                                     self.file_stream, self.pool)


class InterFromSvnRepository(InterRepository):
    """Svn to any repository actions."""

    _matching_repo_format = SvnRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def _find_all(self):
        parents = {}
        needed = filter(lambda x: not self.target.has_revision(x), 
                        self.source.all_revision_ids())
        for revid in needed:
            (branch, revnum, scheme) = self.source.lookup_revision_id(revid)
            parents[revid] = self.source._mainline_revision_parent(branch, 
                                               revnum, scheme)
        return (needed, parents)

    def _find_until(self, revision_id):
        """Find all missing revisions until revision_id

        :param revision_id: Stop revision
        :return: Tuple with revisions missing and a dictionary with 
            parents for those revision.
        """
        needed = []
        parents = {}
        (path, until_revnum, scheme) = self.source.lookup_revision_id(
                                                                    revision_id)

        prev_revid = None
        for (branch, revnum) in self.source.follow_branch(path, 
                                                          until_revnum, scheme):
            revid = self.source.generate_revision_id(revnum, branch, str(scheme))

            if prev_revid is not None:
                parents[prev_revid] = revid

            prev_revid = revid

            if not self.target.has_revision(revid):
                needed.append(revid)

        parents[prev_revid] = None
        return (needed, parents)

    def copy_content(self, revision_id=None, basis=None, pb=None):
        """See InterRepository.copy_content."""
        # FIXME: Use basis
        # Dictionary with paths as keys, revnums as values

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call self.target.add_revision() 
        # or self.target.add_inventory() each time
        self.target.lock_read()
        try:
            if revision_id is None:
                (needed, parents) = self._find_all()
            else:
                (needed, parents) = self._find_until(revision_id)
        finally:
            self.target.unlock()

        if len(needed) == 0:
            # Nothing to fetch
            return

        repos_root = self.source.transport.get_repos_root()

        prev_revid = None
        transport = self.source.transport
        self.target.lock_write()
        if pb is None:
            pb = ui.ui_factory.nested_progress_bar()
            nested_pb = pb
        else:
            nested_pb = None
        num = 0
        prev_inv = None
        try:
            for revid in reversed(needed):
                (branch, revnum, scheme) = self.source.lookup_revision_id(revid)
                pb.update('copying revision', num, len(needed))

                parent_revid = parents[revid]

                if parent_revid is None:
                    parent_inv = Inventory(root_id=None)
                elif prev_revid != parent_revid:
                    parent_inv = self.target.get_inventory(parent_revid)
                else:
                    assert prev_inv is not None
                    parent_inv = prev_inv

                changes = self.source._log.get_revision_paths(revnum, branch)
                renames = self.source.revision_fileid_renames(revid)
                id_map = self.source.transform_fileid_map(self.source.uuid, 
                                      revnum, branch, changes, renames, scheme)

                editor = RevisionBuildEditor(self.source, self.target, branch, 
                             parent_inv, revid, 
                             self.source._log.get_revision_info(revnum),
                             id_map, scheme)

                pool = Pool()
                edit, edit_baton = svn.delta.make_editor(editor, pool)

                if parent_revid is None:
                    transport.reparent(urlutils.join(repos_root, branch))
                    reporter = transport.do_update(
                                   revnum, True, edit, edit_baton, pool)

                    # Report status of existing paths
                    reporter.set_path("", revnum, True, None, pool)
                else:
                    (parent_branch, parent_revnum, scheme) = \
                            self.source.lookup_revision_id(parent_revid)
                    transport.reparent(urlutils.join(repos_root, parent_branch))

                    if parent_branch != branch:
                        reporter = transport.do_switch(
                                   revnum, True, 
                                   urlutils.join(repos_root, branch), 
                                   edit, edit_baton, pool)
                    else:
                        reporter = transport.do_update(
                                   revnum, True, edit, edit_baton, pool)

                    # Report status of existing paths
                    reporter.set_path("", parent_revnum, False, None, pool)

                lock = transport.lock_read(".")
                reporter.finish_report(pool)
                lock.unlock()

                prev_inv = editor.inventory
                prev_revid = revid
                pool.destroy()
                num += 1
        finally:
            self.target.unlock()
            if nested_pb is not None:
                nested_pb.finished()
        self.source.transport.reparent_root()

    def fetch(self, revision_id=None, pb=None):
        """Fetch revisions. """
        self.copy_content(revision_id=revision_id, pb=pb)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, SvnRepository) and \
                target.supports_rich_root()


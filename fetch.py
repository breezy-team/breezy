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
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.repository import InterRepository
from bzrlib.trace import mutter

from cStringIO import StringIO
import md5

from svn.core import Pool
import svn.core

from bzrlib.plugins.svn.errors import InvalidFileName
from fileids import generate_file_id
from repository import (SvnRepository, SVN_PROP_BZR_ANCESTRY, 
                SVN_PROP_SVK_MERGE, SVN_PROP_BZR_MERGE,
                SVN_PROP_BZR_PREFIX, SVN_PROP_BZR_REVISION_INFO, 
                SVN_PROP_BZR_BRANCHING_SCHEME, SVN_PROP_BZR_REVISION_ID,
                SVN_REVPROP_BZR_MAPPING_VERSION, MAPPING_VERSION,
                SVN_PROP_BZR_FILEIDS, SvnRepositoryFormat, 
                parse_revision_metadata, parse_merge_property,
                revision_parse_svn_revprops)
from tree import apply_txdelta_handler


def _escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    if message is None:
        return None
    import re
    # FIXME: RBC 20060419 this should be done by the revision
    # serialiser not by commit. Then we can also add an unescaper
    # in the deserializer and start roundtripping revision messages
    # precisely. See repository_implementations/test_repository.py
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


def md5_strings(strings):
    """Return the MD5sum of the concatenation of strings.

    :param strings: Strings to find the MD5sum of.
    :return: MD5sum
    """
    s = md5.new()
    map(s.update, strings)
    return s.hexdigest()


def check_filename(path):
    """Check that a path does not contain invalid characters.

    :param path: Path to check
    :raises InvalidFileName:
    """
    assert isinstance(path, unicode)
    if u"\\" in path:
        raise InvalidFileName(path)


class RevisionBuildEditor(svn.delta.Editor):
    """Implementation of the Subversion commit editor interface that builds a 
    Bazaar revision.
    """
    def __init__(self, source, target):
        self.target = target
        self.source = source
        self.transact = target.get_transaction()

    def start_revision(self, revid, prev_inventory):
        self.revid = revid
        (self.branch_path, self.revnum, self.scheme) = self.source.lookup_revision_id(revid)
        changes = self.source._log.get_revision_paths(self.revnum, self.branch_path)
        renames = self.source.revision_fileid_renames(revid)
        self.id_map = self.source.transform_fileid_map(self.source.uuid, 
                              self.revnum, self.branch_path, changes, renames, 
                              self.scheme)
        self.dir_baserev = {}
        self._revinfo = None
        self._bzr_merges = []
        self._svk_merges = []
        self._premature_deletes = set()
        self.pool = Pool()
        self.old_inventory = prev_inventory
        self.inventory = prev_inventory.copy()
        self._start_revision()

    def _get_parent_ids(self):
        return self.source.revision_parents(self.revid, self._bzr_merges)

    def _get_revision(self, revid):
        """Creates the revision object.

        :param revid: Revision id of the revision to create.
        """

        # Commit SVN revision properties to a Revision object
        rev = Revision(revision_id=revid, parent_ids=self._get_parent_ids())

        svn_revprops = self.source._log._get_transport().revprop_list(self.revnum)
        revision_parse_svn_revprops(rev, svn_revprops)

        if self._revinfo and svn_revprops.get(SVN_REVPROP_BZR_MAPPING_VERSION) != str(MAPPING_VERSION):
            parse_revision_metadata(self._revinfo, rev)

        return rev

    def open_root(self, base_revnum, baton):
        if self.old_inventory.root is None:
            # First time the root is set
            old_file_id = None
            file_id = generate_file_id(self.source, self.revid, u"")
            self.dir_baserev[file_id] = []
        else:
            assert self.old_inventory.root.revision is not None
            old_file_id = self.old_inventory.root.file_id
            if self.id_map.has_key(""):
                file_id = self.id_map[""]
            else:
                file_id = old_file_id
            self.dir_baserev[file_id] = [self.old_inventory.root.revision]

        if self.inventory.root is not None and \
                file_id == self.inventory.root.file_id:
            ie = self.inventory.root
        else:
            ie = self.inventory.add_path("", 'directory', file_id)
        ie.revision = self.revid
        return (old_file_id, file_id)

    def _get_existing_id(self, parent_id, path):
        assert isinstance(path, unicode)
        assert isinstance(parent_id, str)
        if self.id_map.has_key(path):
            return self.id_map[path]
        return self._get_old_id(parent_id, path)

    def _get_old_id(self, parent_id, old_path):
        assert isinstance(old_path, unicode)
        assert isinstance(parent_id, str)
        return self.old_inventory[parent_id].children[urlutils.basename(old_path)].file_id

    def _get_new_id(self, parent_id, new_path):
        assert isinstance(new_path, unicode)
        assert isinstance(parent_id, str)
        if self.id_map.has_key(new_path):
            return self.id_map[new_path]
        return generate_file_id(self.source, self.revid, new_path)

    def _rename(self, file_id, parent_id, path):
        assert isinstance(path, unicode)
        assert isinstance(parent_id, str)
        # Only rename if not right yet
        if (self.inventory[file_id].parent_id == parent_id and 
            self.inventory[file_id].name == urlutils.basename(path)):
            return
        self.inventory.rename(file_id, parent_id, urlutils.basename(path))

    def delete_entry(self, path, revnum, (old_parent_id, new_parent_id), pool):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        if path in self._premature_deletes:
            # Delete recursively
            self._premature_deletes.remove(path)
            for p in self._premature_deletes.copy():
                if p.startswith("%s/" % path):
                    self._premature_deletes.remove(p)
        else:
            self.inventory.remove_recursive_id(self._get_old_id(new_parent_id, path))

    def close_directory(self, (old_id, new_id)):
        self.inventory[new_id].revision = self.revid

        # Only record root if the target repository supports it
        self._store_directory(new_id, self.dir_baserev[new_id])

    def add_directory(self, path, (old_parent_id, new_parent_id), copyfrom_path, copyfrom_revnum, 
                      pool):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        check_filename(path)
        file_id = self._get_new_id(new_parent_id, path)

        self.dir_baserev[file_id] = []
        if file_id in self.inventory:
            # This directory was moved here from somewhere else, but the 
            # other location hasn't been removed yet. 
            if copyfrom_path is None:
                # This should ideally never happen!
                copyfrom_path = self.old_inventory.id2path(file_id)
                mutter('no copyfrom path set, assuming %r' % copyfrom_path)
            assert copyfrom_path == self.old_inventory.id2path(file_id)
            assert copyfrom_path not in self._premature_deletes
            self._premature_deletes.add(copyfrom_path)
            self._rename(file_id, new_parent_id, path)
            ie = self.inventory[file_id]
            old_file_id = file_id
        else:
            old_file_id = None
            ie = self.inventory.add_path(path, 'directory', file_id)
        ie.revision = self.revid

        return (old_file_id, file_id)

    def open_directory(self, path, (old_parent_id, new_parent_id), base_revnum, pool):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        assert base_revnum >= 0
        base_file_id = self._get_old_id(old_parent_id, path)
        base_revid = self.old_inventory[base_file_id].revision
        file_id = self._get_existing_id(new_parent_id, path)
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
        return (base_file_id, file_id)

    def change_dir_prop(self, (old_id, new_id), name, value, pool):
        if name == SVN_PROP_BZR_BRANCHING_SCHEME:
            if new_id != self.inventory.root.file_id:
                mutter('rogue %r on non-root directory' % name)
                return
        elif name == SVN_PROP_BZR_ANCESTRY+str(self.scheme):
            if new_id != self.inventory.root.file_id:
                mutter('rogue %r on non-root directory' % name)
                return
            
            self._bzr_merges = parse_merge_property(value.splitlines()[-1])
        elif (name.startswith(SVN_PROP_BZR_ANCESTRY) or 
              name.startswith(SVN_PROP_BZR_REVISION_ID)):
            pass
        elif name == SVN_PROP_SVK_MERGE:
            self._svk_merges = None # Force Repository.revision_parents() to look it up
        elif name == SVN_PROP_BZR_REVISION_INFO:
            if new_id != self.inventory.root.file_id:
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

    def add_file(self, path, (old_parent_id, new_parent_id), copyfrom_path, copyfrom_revnum, baton):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        check_filename(path)
        self.is_symlink = False
        self.is_executable = None
        self.file_data = ""
        self.file_parents = []
        self.file_stream = None
        self.file_id = self._get_new_id(new_parent_id, path)
        if self.file_id in self.inventory:
            # This file was moved here from somewhere else, but the 
            # other location hasn't been removed yet. 
            if copyfrom_path is None:
                # This should ideally never happen
                copyfrom_path = self.old_inventory.id2path(self.file_id)
                mutter('no copyfrom path set, assuming %r' % copyfrom_path)
            assert copyfrom_path == self.old_inventory.id2path(self.file_id)
            assert copyfrom_path not in self._premature_deletes
            self._premature_deletes.add(copyfrom_path)
            # No need to rename if it's already in the right spot
            self._rename(self.file_id, new_parent_id, path)
        return path

    def open_file(self, path, (old_parent_id, new_parent_id), base_revnum, pool):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        base_file_id = self._get_old_id(old_parent_id, path)
        base_revid = self.old_inventory[base_file_id].revision
        self.file_id = self._get_existing_id(new_parent_id, path)
        self.is_executable = None
        self.is_symlink = (self.inventory[base_file_id].kind == 'symlink')
        self.file_data = self._get_file_data(base_file_id, base_revid)
        self.file_stream = None
        if self.file_id == base_file_id:
            self.file_parents = [base_revid]
        else:
            # Replace
            del self.inventory[base_file_id]
            self.file_parents = []
        return path

    def close_file(self, path, checksum):
        assert isinstance(path, unicode)
        if self.file_stream is not None:
            self.file_stream.seek(0)
            lines = osutils.split_lines(self.file_stream.read())
        else:
            # Data didn't change or file is new
            lines = osutils.split_lines(self.file_data)

        actual_checksum = md5_strings(lines)
        assert checksum is None or checksum == actual_checksum

        self._store_file(self.file_id, lines, self.file_parents)

        if self.file_id in self.inventory:
            ie = self.inventory[self.file_id]
        elif self.is_symlink:
            ie = self.inventory.add_path(path, 'symlink', self.file_id)
        else:
            ie = self.inventory.add_path(path, 'file', self.file_id)
        ie.revision = self.revid

        if self.is_symlink:
            ie.kind = 'symlink'
            ie.symlink_target = lines[0][len("link "):]
            ie.text_sha1 = None
            ie.text_size = None
            ie.text_id = None
        else:
            ie.kind = 'file'
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            if self.is_executable is not None:
                ie.executable = self.is_executable

        self.file_stream = None

    def close_edit(self):
        assert len(self._premature_deletes) == 0
        self._finish_commit()
        self.pool.destroy()

    def apply_textdelta(self, file_id, base_checksum):
        actual_checksum = md5.new(self.file_data).hexdigest(),
        assert (base_checksum is None or base_checksum == actual_checksum,
            "base checksum mismatch: %r != %r" % (base_checksum, 
                                                  actual_checksum))
        self.file_stream = StringIO()
        return apply_txdelta_handler(StringIO(self.file_data), 
                                     self.file_stream, self.pool)

    def _store_file(self, file_id, lines, parents):
        raise NotImplementedError(self._store_file)

    def _store_directory(self, file_id, parents):
        raise NotImplementedError(self._store_directory)

    def _get_file_data(self, file_id, revid):
        raise NotImplementedError(self._get_file_data)

    def _finish_commit(self):
        raise NotImplementedError(self._finish_commit)

    def abort_edit(self):
        pass

    def _start_revision(self):
        pass


class WeaveRevisionBuildEditor(RevisionBuildEditor):
    """Subversion commit editor that can write to a weave-based repository.
    """
    def __init__(self, source, target):
        RevisionBuildEditor.__init__(self, source, target)
        self.weave_store = target.weave_store

    def _start_revision(self):
        self._write_group_active = True
        self.target.start_write_group()

    def _store_directory(self, file_id, parents):
        file_weave = self.weave_store.get_weave_or_empty(file_id, self.transact)
        if not file_weave.has_version(self.revid):
            file_weave.add_lines(self.revid, parents, [])

    def _get_file_data(self, file_id, revid):
        file_weave = self.weave_store.get_weave_or_empty(file_id, self.transact)
        return file_weave.get_text(revid)

    def _store_file(self, file_id, lines, parents):
        file_weave = self.weave_store.get_weave_or_empty(file_id, self.transact)
        if not file_weave.has_version(self.revid):
            file_weave.add_lines(self.revid, parents, lines)

    def _finish_commit(self):
        rev = self._get_revision(self.revid)
        self.inventory.revision_id = self.revid
        # Escaping the commit message is really the task of the serialiser
        rev.message = _escape_commit_message(rev.message)
        rev.inventory_sha1 = osutils.sha_string(
                self.target.serialise_inventory(self.inventory))
        self.target.add_revision(self.revid, rev, self.inventory)
        self.target.commit_write_group()
        self._write_group_active = False

    def abort_edit(self):
        if self._write_group_active:
            self.target.abort_write_group()
            self._write_group_active = False


class PackRevisionBuildEditor(WeaveRevisionBuildEditor):
    """Revision Build Editor for Subversion that is specific for the packs API.
    """
    def __init__(self, source, target):
        WeaveRevisionBuildEditor.__init__(self, source, target)

    def _add_text_to_weave(self, file_id, new_lines, parents):
        return self.target._packs._add_text_to_weave(file_id,
            self.revid, new_lines, parents, nostore_sha=None, 
            random_revid=False)

    def _store_directory(self, file_id, parents):
        self._add_text_to_weave(file_id, [], parents)

    def _store_file(self, file_id, lines, parents):
        self._add_text_to_weave(file_id, lines, parents)


class CommitBuilderRevisionBuildEditor(RevisionBuildEditor):
    """Revision Build Editor for Subversion that uses the CommitBuilder API.
    """
    def __init__(self, source, target):
        RevisionBuildEditor.__init__(self, source, target)
        raise NotImplementedError(self)


def get_revision_build_editor(repository):
    """Obtain a RevisionBuildEditor for a particular target repository.
    
    :param repository: Repository to obtain the buildeditor for.
    :return: Class object of class descending from RevisionBuildEditor
    """
    if hasattr(repository, '_packs'):
        return PackRevisionBuildEditor
    return WeaveRevisionBuildEditor


class InterFromSvnRepository(InterRepository):
    """Svn to any repository actions."""

    _matching_repo_format = SvnRepositoryFormat()

    _supports_branches = True

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def _find_all(self):
        """Find all revisions from the source repository that are not 
        yet in the target repository.
        """
        parents = {}
        needed = filter(lambda x: not self.target.has_revision(x), 
                        self.source.all_revision_ids())
        for revid in needed:
            (branch, revnum, scheme) = self.source.lookup_revision_id(revid)
            parents[revid] = self.source._mainline_revision_parent(branch, 
                                               revnum, scheme)
        needed.reverse()
        return (needed, parents)

    def _find_branches(self, branches, find_ghosts=False):
        set_needed = set()
        ret_needed = list()
        ret_parents = dict()
        for revid in branches:
            (needed, parents) = self._find_until(revid, find_ghosts=find_ghosts)
            for rev in needed:
                if not rev in set_needed:
                    ret_needed.append(rev)
                    set_needed.add(rev)
            ret_parents.update(parents)
        return ret_needed, ret_parents

    def _find_until(self, revision_id, find_ghosts=False):
        """Find all missing revisions until revision_id

        :param revision_id: Stop revision
        :param find_ghosts: Find ghosts
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
            elif not find_ghosts:
                break

        parents[prev_revid] = None
        needed.reverse()
        return (needed, parents)

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def _fetch_replay(self, revids, pb=None):
        """Copy a set of related revisions using svn.ra.replay.

        :param revids: Revision ids to copy.
        :param pb: Optional progress bar
        """
        raise NotImplementedError(self._copy_revisions_replay)

    def _fetch_switch(self, revids, pb=None, lhs_parent=None):
        """Copy a set of related revisions using svn.ra.switch.

        :param revids: List of revision ids of revisions to copy, 
                       newest first.
        :param pb: Optional progress bar.
        """
        repos_root = self.source.transport.get_svn_repos_root()

        prev_revid = None
        transport = self.source.transport
        if pb is None:
            pb = ui.ui_factory.nested_progress_bar()
            nested_pb = pb
        else:
            nested_pb = None
        num = 0
        prev_inv = None

        self.target.lock_write()
        revbuildklass = get_revision_build_editor(self.target)
        editor = revbuildklass(self.source, self.target)

        try:
            for revid in revids:
                pb.update('copying revision', num, len(revids))

                parent_revid = lhs_parent[revid]

                if parent_revid is None:
                    parent_inv = Inventory(root_id=None)
                elif prev_revid != parent_revid:
                    parent_inv = self.target.get_inventory(parent_revid)
                else:
                    parent_inv = prev_inv

                editor.start_revision(revid, parent_inv)

                try:
                    pool = Pool()

                    if parent_revid is None:
                        branch_url = urlutils.join(repos_root, 
                                                   editor.branch_path)
                        transport.reparent(branch_url)
                        assert transport.svn_url == branch_url.rstrip("/"), \
                            "Expected %r, got %r" % (transport.svn_url, branch_url)
                        reporter = transport.do_update(editor.revnum, True, 
                                                       editor, pool)

                        # Report status of existing paths
                        reporter.set_path("", editor.revnum, True, None, pool)
                    else:
                        (parent_branch, parent_revnum, scheme) = \
                                self.source.lookup_revision_id(parent_revid)
                        transport.reparent(urlutils.join(repos_root, parent_branch))

                        if parent_branch != editor.branch_path:
                            reporter = transport.do_switch(editor.revnum, True, 
                                urlutils.join(repos_root, editor.branch_path), 
                                editor, pool)
                        else:
                            reporter = transport.do_update(editor.revnum, True, editor)

                        # Report status of existing paths
                        reporter.set_path("", parent_revnum, False, None, pool)

                    lock = transport.lock_read(".")
                    reporter.finish_report(pool)
                    lock.unlock()
                except:
                    editor.abort_edit()
                    raise

                prev_inv = editor.inventory
                prev_revid = revid
                pool.destroy()
                num += 1
        finally:
            self.target.unlock()
            if nested_pb is not None:
                nested_pb.finished()
        self.source.transport.reparent_root()

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              branches=None):
        """Fetch revisions. """
        if revision_id == NULL_REVISION:
            return
        # Dictionary with paths as keys, revnums as values

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call self.target.add_revision() 
        # or self.target.add_inventory() each time
        self.target.lock_read()
        try:
            if branches is not None:
                (needed, lhs_parent) = self._find_branches(branches, 
                                                           find_ghosts)
            elif revision_id is None:
                (needed, lhs_parent) = self._find_all()
            else:
                (needed, lhs_parent) = self._find_until(revision_id, 
                                                        find_ghosts)
        finally:
            self.target.unlock()

        if len(needed) == 0:
            # Nothing to fetch
            return

        self._fetch_switch(needed, pb, lhs_parent)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, SvnRepository) and target.supports_rich_root()


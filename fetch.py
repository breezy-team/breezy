# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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
from bzrlib import delta, osutils, ui, urlutils
from bzrlib.errors import NoSuchRevision
from bzrlib.inventory import Inventory
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.repository import InterRepository
from bzrlib.trace import mutter

from cStringIO import StringIO
import md5

from bzrlib.plugins.svn import properties
from bzrlib.plugins.svn.delta import apply_txdelta_handler
from bzrlib.plugins.svn.errors import InvalidFileName
from bzrlib.plugins.svn.logwalker import lazy_dict
from bzrlib.plugins.svn.mapping import (SVN_PROP_BZR_MERGE, 
                     SVN_PROP_BZR_PREFIX, SVN_PROP_BZR_REVISION_INFO, 
                     SVN_PROP_BZR_REVISION_ID,
                     SVN_PROP_BZR_FILEIDS, SVN_REVPROP_BZR_SIGNATURE,
                     parse_merge_property,
                     parse_revision_metadata)
from bzrlib.plugins.svn.properties import parse_externals_description
from bzrlib.plugins.svn.repository import SvnRepository, SvnRepositoryFormat
from bzrlib.plugins.svn.svk import SVN_PROP_SVK_MERGE
from bzrlib.plugins.svn.transport import _url_escape_uri
from bzrlib.plugins.svn.tree import inventory_add_external

FETCH_COMMIT_WRITE_SIZE = 500

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


class DeltaBuildEditor(object):
    """Implementation of the Subversion commit editor interface that 
    converts Subversion to Bazaar semantics.
    """
    def __init__(self, revmeta, mapping):
        self.revmeta = revmeta
        self._id_map = None
        self._premature_deletes = set()
        self.mapping = mapping

    def set_target_revision(self, revnum):
        assert self.revmeta.revnum == revnum

    def _get_id_map(self):
        if self._id_map is not None:
            return self._id_map

        self._id_map = self.source.transform_fileid_map(self.revmeta, self.mapping)

        return self._id_map

    def open_root(self, base_revnum):
        return self._open_root(base_revnum)

    def close(self):
        pass

    def abort(self):
        pass

    def _get_existing_id(self, old_parent_id, new_parent_id, path):
        assert isinstance(path, unicode)
        assert isinstance(old_parent_id, str)
        assert isinstance(new_parent_id, str)
        ret = self._get_id_map().get(path)
        if ret is not None:
            return ret
        return self.old_inventory[old_parent_id].children[urlutils.basename(path)].file_id

    def _get_new_id(self, parent_id, new_path):
        assert isinstance(new_path, unicode)
        assert isinstance(parent_id, str)
        ret = self._get_id_map().get(new_path)
        if ret is not None:
            return ret
        return self.mapping.generate_file_id(self.source.uuid, self.revmeta.revnum, 
                                             self.revmeta.branch_path, new_path)

    def _rename(self, file_id, parent_id, old_path, new_path, kind):
        raise NotImplementedError


class DirectoryBuildEditor(object):
    def __init__(self, editor):
        self.editor = editor

    def close(self):
        self._close()

    def add_directory(self, path, copyfrom_path=None, copyfrom_revnum=-1):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        check_filename(path)
        return self._add_directory(path, copyfrom_path, copyfrom_revnum)

    def open_directory(self, path, base_revnum):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        assert base_revnum >= 0
        return self._open_directory(path, base_revnum)

    def change_prop(self, name, value):
        if self.new_id == self.editor.inventory.root.file_id:
            # Replay lazy_dict, since it may be more expensive
            if type(self.editor.revmeta.fileprops) != dict:
                self.editor.revmeta.fileprops = {}
            self.editor.revmeta.fileprops[name] = value

        if name in (properties.PROP_ENTRY_COMMITTED_DATE,
                    properties.PROP_ENTRY_COMMITTED_REV,
                    properties.PROP_ENTRY_LAST_AUTHOR,
                    properties.PROP_ENTRY_LOCK_TOKEN,
                    properties.PROP_ENTRY_UUID,
                    properties.PROP_EXECUTABLE):
            pass
        elif (name.startswith(properties.PROP_WC_PREFIX)):
            pass
        elif name.startswith(properties.PROP_PREFIX):
            mutter('unsupported dir property %r', name)

    def add_file(self, path, copyfrom_path=None, copyfrom_revnum=-1):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        check_filename(path)
        return self._add_file(path, copyfrom_path, copyfrom_revnum)

    def open_file(self, path, base_revnum):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        return self._open_file(path, base_revnum)

    def delete_entry(self, path, revnum):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        return self._delete_entry(path, revnum)


class FileBuildEditor(object):
    def __init__(self, editor, path):
        self.path = path
        self.editor = editor
        self.is_executable = None
        self.is_special = None

    def apply_textdelta(self, base_checksum=None):
        return self._apply_textdelta(base_checksum)

    def change_prop(self, name, value):
        if name == properties.PROP_EXECUTABLE: 
            # You'd expect executable to match 
            # properties.PROP_EXECUTABLE_VALUE, but that's not 
            # how SVN behaves. It appears to consider the presence 
            # of the property sufficient to mark it executable.
            self.is_executable = (value is not None)
        elif (name == properties.PROP_SPECIAL):
            self.is_special = (value != None)
        elif name == properties.PROP_ENTRY_COMMITTED_REV:
            self.last_file_rev = int(value)
        elif name == properties.PROP_EXTERNALS:
            mutter('svn:externals property on file!')
        elif name in (properties.PROP_ENTRY_COMMITTED_DATE,
                      properties.PROP_ENTRY_LAST_AUTHOR,
                      properties.PROP_ENTRY_LOCK_TOKEN,
                      properties.PROP_ENTRY_UUID,
                      properties.PROP_MIME_TYPE):
            pass
        elif name.startswith(properties.PROP_WC_PREFIX):
            pass
        elif (name.startswith(properties.PROP_PREFIX) or
              name.startswith(SVN_PROP_BZR_PREFIX)):
            mutter('unsupported file property %r', name)

    def close(self, checksum=None):
        assert isinstance(self.path, unicode)
        return self._close()


class DirectoryRevisionBuildEditor(DirectoryBuildEditor):
    def __init__(self, editor, old_id, new_id, parent_revids=[]):
        super(DirectoryRevisionBuildEditor, self).__init__(editor)
        self.old_id = old_id
        self.new_id = new_id
        self.parent_revids = parent_revids

    def _delete_entry(self, path, revnum):
        if path in self.editor._premature_deletes:
            # Delete recursively
            self.editor._premature_deletes.remove(path)
            for p in self.editor._premature_deletes.copy():
                if p.startswith("%s/" % path):
                    self.editor._premature_deletes.remove(p)
        else:
            self.editor.inventory.remove_recursive_id(self.editor._get_old_id(self.old_id, path))

    def _close(self):
        self.editor.inventory[self.new_id].revision = self.editor.revid

        self.editor.texts.add_lines((self.new_id, self.editor.revid), 
                 [(self.new_id, revid) for revid in self.parent_revids], [])

        if self.new_id == self.editor.inventory.root.file_id:
            assert len(self.editor._premature_deletes) == 0
            self.editor._finish_commit()

    def _add_directory(self, path, copyfrom_path=None, copyfrom_revnum=-1):
        file_id = self.editor._get_new_id(self.new_id, path)

        if file_id in self.editor.inventory:
            # This directory was moved here from somewhere else, but the 
            # other location hasn't been removed yet. 
            if copyfrom_path is None:
                # This should ideally never happen!
                copyfrom_path = self.editor.old_inventory.id2path(file_id)
                mutter('no copyfrom path set, assuming %r', copyfrom_path)
            assert copyfrom_path == self.editor.old_inventory.id2path(file_id)
            assert copyfrom_path not in self.editor._premature_deletes
            self.editor._premature_deletes.add(copyfrom_path)
            self.editor._rename(file_id, self.new_id, copyfrom_path, path, 'directory')
            ie = self.editor.inventory[file_id]
            old_file_id = file_id
        else:
            old_file_id = None
            ie = self.editor.inventory.add_path(path, 'directory', file_id)
        ie.revision = self.editor.revid

        return DirectoryRevisionBuildEditor(self.editor, old_file_id, file_id)

    def _open_directory(self, path, base_revnum):
        base_file_id = self.editor._get_old_id(self.old_id, path)
        base_revid = self.editor.old_inventory[base_file_id].revision
        file_id = self.editor._get_existing_id(self.old_id, self.new_id, path)
        if file_id == base_file_id:
            file_parents = [base_revid]
            ie = self.editor.inventory[file_id]
        else:
            # Replace if original was inside this branch
            # change id of base_file_id to file_id
            ie = self.editor.inventory[base_file_id]
            for name in ie.children:
                ie.children[name].parent_id = file_id
            # FIXME: Don't touch inventory internals
            del self.editor.inventory._byid[base_file_id]
            self.editor.inventory._byid[file_id] = ie
            ie.file_id = file_id
            file_parents = []
        ie.revision = self.editor.revid
        return DirectoryRevisionBuildEditor(self.editor, base_file_id, file_id, 
                                    file_parents)

    def _add_file(self, path, copyfrom_path=None, copyfrom_revnum=-1):
        file_id = self.editor._get_new_id(self.new_id, path)
        if file_id in self.editor.inventory:
            # This file was moved here from somewhere else, but the 
            # other location hasn't been removed yet. 
            if copyfrom_path is None:
                # This should ideally never happen
                copyfrom_path = self.editor.old_inventory.id2path(file_id)
                mutter('no copyfrom path set, assuming %r', copyfrom_path)
            assert copyfrom_path == self.editor.old_inventory.id2path(file_id)
            assert copyfrom_path not in self.editor._premature_deletes
            self.editor._premature_deletes.add(copyfrom_path)
            # No need to rename if it's already in the right spot
            self.editor._rename(file_id, self.new_id, copyfrom_path, path, 'file')
        return FileRevisionBuildEditor(self.editor, path, file_id)

    def _open_file(self, path, base_revnum):
        base_file_id = self.editor._get_old_id(self.old_id, path)
        base_revid = self.editor.old_inventory[base_file_id].revision
        file_id = self.editor._get_existing_id(self.old_id, self.new_id, path)
        is_symlink = (self.editor.inventory[base_file_id].kind == 'symlink')
        record = self.editor.texts.get_record_stream([(base_file_id, base_revid)], 'unordered', True).next()
        file_data = record.get_bytes_as('fulltext')
        if file_id == base_file_id:
            file_parents = [base_revid]
        else:
            # Replace with historical version
            del self.editor.inventory[base_file_id]
            file_parents = []
        return FileRevisionBuildEditor(self.editor, path, file_id, 
                               file_parents, file_data, is_symlink=is_symlink)


class FileRevisionBuildEditor(FileBuildEditor):
    def __init__(self, editor, path, file_id, file_parents=[], data="", 
                 is_symlink=False):
        super(FileRevisionBuildEditor, self).__init__(editor, path)
        self.file_id = file_id
        self.file_data = data
        self.is_symlink = is_symlink
        self.file_parents = file_parents
        self.file_stream = None

    def _apply_textdelta(self, base_checksum=None):
        actual_checksum = md5.new(self.file_data).hexdigest()
        assert (base_checksum is None or base_checksum == actual_checksum,
            "base checksum mismatch: %r != %r" % (base_checksum, 
                                                  actual_checksum))
        self.file_stream = StringIO()
        return apply_txdelta_handler(self.file_data, self.file_stream)

    def _close(self, checksum=None):
        if self.file_stream is not None:
            self.file_stream.seek(0)
            lines = osutils.split_lines(self.file_stream.read())
        else:
            # Data didn't change or file is new
            lines = osutils.split_lines(self.file_data)

        actual_checksum = md5_strings(lines)
        assert checksum is None or checksum == actual_checksum

        self.editor.texts.add_lines((self.file_id, self.editor.revid), 
                [(self.file_id, revid) for revid in self.file_parents], lines)

        if self.is_special is not None:
            self.is_symlink = (self.is_special and len(lines) > 0 and lines[0].startswith("link "))

        assert self.is_symlink in (True, False)

        if self.file_id in self.editor.inventory:
            if self.is_executable is None:
                self.is_executable = self.editor.inventory[self.file_id].executable
            del self.editor.inventory[self.file_id]

        if self.is_symlink:
            ie = self.editor.inventory.add_path(self.path, 'symlink', self.file_id)
            ie.symlink_target = "".join(lines)[len("link "):]
            ie.text_sha1 = None
            ie.text_size = None
            ie.executable = False
            ie.revision = self.editor.revid
        else:
            ie = self.editor.inventory.add_path(self.path, 'file', self.file_id)
            ie.revision = self.editor.revid
            ie.kind = 'file'
            ie.symlink_target = None
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            assert ie.text_size is not None
            ie.executable = self.is_executable

        self.file_stream = None


class RevisionBuildEditor(DeltaBuildEditor):
    """Implementation of the Subversion commit editor interface that builds a 
    Bazaar revision.
    """
    def __init__(self, source, target, revid, prev_inventory, revmeta):
        self.target = target
        self.source = source
        self.texts = target.texts
        self.revid = revid
        mapping = self.source.lookup_revision_id(revid)[2]
        self.old_inventory = prev_inventory
        self.inventory = prev_inventory.copy()
        super(RevisionBuildEditor, self).__init__(revmeta, mapping)

    def _get_revision(self, revid):
        """Creates the revision object.

        :param revid: Revision id of the revision to create.
        """

        # Commit SVN revision properties to a Revision object
        parent_ids = self.revmeta.get_parent_ids(self.mapping)
        if parent_ids == (NULL_REVISION,):
            parent_ids = ()
        assert not NULL_REVISION in parent_ids, "parents: %r" % parent_ids
        rev = Revision(revision_id=revid, 
                       parent_ids=parent_ids)

        self.mapping.import_revision(self.revmeta.revprops, self.revmeta.fileprops, 
                                     self.revmeta.repository.uuid, self.revmeta.branch_path,
                                     self.revmeta.revnum, rev)

        signature = self.revmeta.revprops.get(SVN_REVPROP_BZR_SIGNATURE)

        return (rev, signature)

    def _finish_commit(self):
        (rev, signature) = self._get_revision(self.revid)
        self.inventory.revision_id = self.revid
        # Escaping the commit message is really the task of the serialiser
        rev.message = _escape_commit_message(rev.message)
        rev.inventory_sha1 = None
        self.target.add_revision(self.revid, rev, self.inventory)
        if signature is not None:
            self.target.add_signature_text(self.revid, signature)

    def _rename(self, file_id, parent_id, old_path, new_path, kind):
        assert isinstance(new_path, unicode)
        assert isinstance(parent_id, str)
        # Only rename if not right yet
        if (self.inventory[file_id].parent_id == parent_id and 
            self.inventory[file_id].name == urlutils.basename(new_path)):
            return
        self.inventory.rename(file_id, parent_id, urlutils.basename(new_path))

    def _open_root(self, base_revnum):
        if self.old_inventory.root is None:
            # First time the root is set
            old_file_id = None
            file_id = self.mapping.generate_file_id(self.source.uuid, self.revmeta.revnum, self.revmeta.branch_path, u"")
            file_parents = []
        else:
            assert self.old_inventory.root.revision is not None
            old_file_id = self.old_inventory.root.file_id
            file_id = self._get_id_map().get("", old_file_id)
            file_parents = [self.old_inventory.root.revision]

        if self.inventory.root is not None and \
                file_id == self.inventory.root.file_id:
            ie = self.inventory.root
        else:
            ie = self.inventory.add_path("", 'directory', file_id)
        ie.revision = self.revid
        return DirectoryRevisionBuildEditor(self, old_file_id, file_id, file_parents)

    def _get_old_id(self, parent_id, old_path):
        assert isinstance(old_path, unicode)
        assert isinstance(parent_id, str)
        return self.old_inventory[parent_id].children[urlutils.basename(old_path)].file_id


class TreeDeltaBuildeditor(DeltaBuildEditor):
    """Implementation of the Subversion commit editor interface that builds a 
    Bazaar TreeDelta.
    """
    def __init__(self):
        self.delta = delta.TreeDelta()
        self.delta.unversioned = []
        # To make sure we fall over if anybody tries to use it:
        self.delta.unchanged = None

    def _rename(self, file_id, parent_id, old_path, new_path, kind):
        # FIXME: Fill in text_modified and meta_modified
        self.delta.renamed.append((old_path, new_path, file_id, kind, 
                                   text_modified, meta_modified))

    def _remove_recursive(self, file_id, path):
        # FIXME: Fill in kind
        self.delta.removed.append((path, file_id, 'unknown-kind'))


def report_inventory_contents(reporter, inv, revnum, start_empty):
    try:
        reporter.set_path("", revnum, start_empty)

        # Report status of existing paths
        for path, entry in inv.iter_entries():
            if path != "":
                reporter.set_path(path.encode("utf-8"), revnum, start_empty)
    except:
        reporter.abort()
        raise
    reporter.finish()


class InterFromSvnRepository(InterRepository):
    """Svn to any repository actions."""

    _matching_repo_format = SvnRepositoryFormat()

    _supports_branches = True

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def _find_all(self, mapping, pb=None):
        """Find all revisions from the source repository that are not 
        yet in the target repository.
        """
        parents = {}
        meta_map = {}
        graph = self.source.get_graph()
        available_revs = set()
        for revmeta in self.source.iter_all_changes(pb=pb):
            revid = revmeta.get_revision_id(mapping)
            available_revs.add(revid)
            meta_map[revid] = revmeta
        missing = available_revs.difference(self.target.has_revisions(available_revs))
        needed = list(graph.iter_topo_order(missing))
        parents = graph.get_parent_map(needed)
        return [(revid, parents[revid][0], meta_map[revid]) for revid in needed]

    def _find_branches(self, branches, find_ghosts=False, pb=None):
        set_needed = set()
        ret_needed = list()
        checked = set()
        for branch in branches:
            if pb:
                pb.update("determining revisions to fetch", branches.index(branch), len(branches))
            try:
                nestedpb = ui.ui_factory.nested_progress_bar()
                for rev in self._find_until(branch.last_revision(), find_ghosts=find_ghosts, 
                                            pb=nestedpb, checked=checked):
                    if rev[0] not in set_needed:
                        ret_needed.append(rev)
                        set_needed.add(rev[0])
            finally:
                nestedpb.finished()
        return ret_needed

    def _find_until(self, revision_id, find_ghosts=False, pb=None,
                    checked=None):
        """Find all missing revisions until revision_id

        :param revision_id: Stop revision
        :param find_ghosts: Find ghosts
        :return: Tuple with revisions missing and a dictionary with 
            parents for those revision.
        """
        if checked is None:
            checked = set()
        if revision_id in checked:
            return []
        extra = set()
        needed = []
        revs = []
        meta_map = {}
        lhs_parent = {}
        def check_revid(revision_id):
            try:
                (branch_path, revnum, mapping) = self.source.lookup_revision_id(revision_id)
            except NoSuchRevision:
                return # Ghost
            for revmeta in self.source.iter_reverse_branch_changes(branch_path, revnum, 
                                                                   to_revnum=0, mapping=mapping):
                if pb:
                    pb.update("determining revisions to fetch", revnum-revmeta.revnum, revnum)
                revid = revmeta.get_revision_id(mapping)
                parent_ids = revmeta.get_parent_ids(mapping)
                lhs_parent[revid] = parent_ids[0]
                meta_map[revid] = revmeta
                if revid in checked:
                    # This revision (and its ancestry) has already been checked
                    break
                extra.update(parent_ids[1:])
                if not self.target.has_revision(revid):
                    revs.append(revid)
                elif not find_ghosts:
                    break
                checked.add(revid)

        check_revid(revision_id)

        for revid in extra:
            if revid not in revs:
                check_revid(revid)

        needed = [(revid, lhs_parent[revid], meta_map[revid]) for revid in reversed(revs)]

        return needed

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def _fetch_replay(self, revids, pb=None):
        """Copy a set of related revisions using svn.ra.replay.

        :param revids: Revision ids to copy.
        :param pb: Optional progress bar
        """
        raise NotImplementedError(self._copy_revisions_replay)

    def _fetch_switch(self, repos_root, revids, pb=None):
        """Copy a set of related revisions using svn.ra.switch.

        :param revids: List of revision ids of revisions to copy, 
                       newest first.
        :param pb: Optional progress bar.
        """
        prev_revid = None
        if pb is None:
            pb = ui.ui_factory.nested_progress_bar()
            nested_pb = pb
        else:
            nested_pb = None
        num = 0
        prev_inv = None

        try:
            for (revid, parent_revid, revmeta) in revids:
                assert revid != NULL_REVISION
                pb.update('copying revision', num, len(revids))

                assert parent_revid is not None and parent_revid != revid

                if parent_revid == NULL_REVISION:
                    parent_inv = Inventory(root_id=None)
                elif prev_revid != parent_revid:
                    parent_inv = self.target.get_inventory(parent_revid)
                else:
                    parent_inv = prev_inv

                if parent_revid == NULL_REVISION:
                    parent_branch = revmeta.branch_path
                    parent_revnum = revmeta.revnum
                    start_empty = True
                else:
                    (parent_branch, parent_revnum, mapping) = \
                            self.source.lookup_revision_id(parent_revid)
                    start_empty = False

                if not self.target.is_in_write_group():
                    self.target.start_write_group()
                try:
                    editor = RevisionBuildEditor(self.source, self.target, revid, parent_inv, revmeta)
                    try:
                        conn = None
                        try:
                            conn = self.source.transport.connections.get(urlutils.join(repos_root, parent_branch))

                            assert revmeta.revnum > parent_revnum or start_empty

                            if parent_branch != revmeta.branch_path:
                                reporter = conn.do_switch(revmeta.revnum, "", True, 
                                    _url_escape_uri(urlutils.join(repos_root, revmeta.branch_path)), 
                                    editor)
                            else:
                                reporter = conn.do_update(revmeta.revnum, "", True, editor)

                            report_inventory_contents(reporter, parent_inv, parent_revnum, start_empty)
                        finally:
                            if conn is not None:
                                if not conn.busy:
                                    self.source.transport.add_connection(conn)
                    except:
                        editor.abort()
                        raise
                except:
                    if self.target.is_in_write_group():
                        self.target.abort_write_group()
                    raise
                if num % FETCH_COMMIT_WRITE_SIZE == 0:
                    self.target.commit_write_group()

                prev_inv = editor.inventory
                prev_revid = revid
                num += 1
            if self.target.is_in_write_group():
                self.target.commit_write_group()
        finally:
            if nested_pb is not None:
                nested_pb.finished()

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              branches=None):
        """Fetch revisions. """
        if revision_id == NULL_REVISION:
            return
        # Dictionary with paths as keys, revnums as values

        if pb:
            pb.update("determining revisions to fetch", 0, 2)

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call self.target.add_revision() 
        # or self.target.add_inventory() each time
        self.target.lock_write()
        try:
            nested_pb = ui.ui_factory.nested_progress_bar()
            try:
                if branches is not None:
                    needed = self._find_branches(branches, find_ghosts, 
                                pb=nested_pb)
                elif revision_id is None:
                    needed = self._find_all(self.source.get_mapping(), pb=nested_pb)
                else:
                    needed = self._find_until(revision_id, find_ghosts, pb=nested_pb)
            finally:
                nested_pb.finished()

            if len(needed) == 0:
                # Nothing to fetch
                return

            self._fetch_switch(self.source.transport.get_svn_repos_root(), needed, pb)
        finally:
            self.target.unlock()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, SvnRepository) and target.supports_rich_root()


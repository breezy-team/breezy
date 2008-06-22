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
from bzrlib import osutils, ui, urlutils
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
from bzrlib.plugins.svn.repository import SvnRepository, SvnRepositoryFormat
from bzrlib.plugins.svn.svk import SVN_PROP_SVK_MERGE
from bzrlib.plugins.svn.tree import (parse_externals_description, 
                  inventory_add_external)

import svn.delta

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


class RevisionBuildEditor(object):
    """Implementation of the Subversion commit editor interface that builds a 
    Bazaar revision.
    """
    def __init__(self, source, target):
        self.target = target
        self.source = source
        self.transact = target.get_transaction()

    def set_target_revision(self, revnum):
        assert self.revnum == revnum

    def start_revision(self, revid, prev_inventory, revmeta):
        self.revid = revid
        (self.branch_path, self.revnum, self.mapping) = self.source.lookup_revision_id(revid)
        self.revmeta = revmeta
        self._id_map = None
        self.dir_baserev = {}
        self._revinfo = None
        self._premature_deletes = set()
        self.old_inventory = prev_inventory
        self.inventory = prev_inventory.copy()
        self._start_revision()

    def _get_id_map(self):
        if self._id_map is not None:
            return self._id_map

        renames = self.mapping.import_fileid_map(self.revmeta.revprops, self.revmeta.fileprops)
        self._id_map = self.source.transform_fileid_map(self.source.uuid, 
                              self.revnum, self.branch_path, self.revmeta.paths, renames, 
                              self.mapping)

        return self._id_map

    def _get_revision(self, revid):
        """Creates the revision object.

        :param revid: Revision id of the revision to create.
        """

        # Commit SVN revision properties to a Revision object
        rev = Revision(revision_id=revid, parent_ids=self.revmeta.get_parent_ids(self.mapping))

        self.mapping.import_revision(self.revmeta.revprops, self.revmeta.fileprops, rev)

        signature = self.revmeta.revprops.get(SVN_REVPROP_BZR_SIGNATURE)

        return (rev, signature)

    def open_root(self, base_revnum):
        if self.old_inventory.root is None:
            # First time the root is set
            old_file_id = None
            file_id = self.mapping.generate_file_id(self.source.uuid, self.revnum, self.branch_path, u"")
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
        return DirectoryBuildEditor(self, old_file_id, file_id, file_parents)

    def close(self):
        pass

    def _store_directory(self, file_id, parents):
        raise NotImplementedError(self._store_directory)

    def _get_file_data(self, file_id, revid):
        raise NotImplementedError(self._get_file_data)

    def _finish_commit(self):
        raise NotImplementedError(self._finish_commit)

    def abort(self):
        pass

    def _start_revision(self):
        pass

    def _store_file(self, file_id, lines, parents):
        raise NotImplementedError(self._store_file)

    def _get_existing_id(self, old_parent_id, new_parent_id, path):
        assert isinstance(path, unicode)
        assert isinstance(old_parent_id, str)
        assert isinstance(new_parent_id, str)
        ret = self._get_id_map().get(path)
        if ret is not None:
            return ret
        return self.old_inventory[old_parent_id].children[urlutils.basename(path)].file_id

    def _get_old_id(self, parent_id, old_path):
        assert isinstance(old_path, unicode)
        assert isinstance(parent_id, str)
        return self.old_inventory[parent_id].children[urlutils.basename(old_path)].file_id

    def _get_new_id(self, parent_id, new_path):
        assert isinstance(new_path, unicode)
        assert isinstance(parent_id, str)
        ret = self._get_id_map().get(new_path)
        if ret is not None:
            return ret
        return self.mapping.generate_file_id(self.source.uuid, self.revnum, 
                                             self.branch_path, new_path)

    def _rename(self, file_id, parent_id, path):
        assert isinstance(path, unicode)
        assert isinstance(parent_id, str)
        # Only rename if not right yet
        if (self.inventory[file_id].parent_id == parent_id and 
            self.inventory[file_id].name == urlutils.basename(path)):
            return
        self.inventory.rename(file_id, parent_id, urlutils.basename(path))


class DirectoryBuildEditor(object):
    def __init__(self, editor, old_id, new_id, parent_revids=[]):
        self.editor = editor
        self.old_id = old_id
        self.new_id = new_id
        self.parent_revids = parent_revids

    def close(self):
        self.editor.inventory[self.new_id].revision = self.editor.revid

        # Only record root if the target repository supports it
        self.editor._store_directory(self.new_id, self.parent_revids)

        if self.new_id == self.editor.inventory.root.file_id:
            assert len(self.editor._premature_deletes) == 0
            self.editor._finish_commit()

    def add_directory(self, path, copyfrom_path=None, copyfrom_revnum=-1):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        check_filename(path)
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
            self.editor._rename(file_id, self.new_id, path)
            ie = self.editor.inventory[file_id]
            old_file_id = file_id
        else:
            old_file_id = None
            ie = self.editor.inventory.add_path(path, 'directory', file_id)
        ie.revision = self.editor.revid

        return DirectoryBuildEditor(self.editor, old_file_id, file_id)

    def open_directory(self, path, base_revnum):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        assert base_revnum >= 0
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
        return DirectoryBuildEditor(self.editor, base_file_id, file_id, 
                                    file_parents)

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
            self.editor._rename(file_id, self.new_id, path)
        return FileBuildEditor(self.editor, path, file_id)

    def open_file(self, path, base_revnum):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        base_file_id = self.editor._get_old_id(self.old_id, path)
        base_revid = self.editor.old_inventory[base_file_id].revision
        file_id = self.editor._get_existing_id(self.old_id, self.new_id, path)
        is_symlink = (self.editor.inventory[base_file_id].kind == 'symlink')
        file_data = self.editor._get_file_data(base_file_id, base_revid)
        if file_id == base_file_id:
            file_parents = [base_revid]
        else:
            # Replace
            del self.editor.inventory[base_file_id]
            file_parents = []
        return FileBuildEditor(self.editor, path, file_id, 
                               file_parents, file_data, is_symlink=is_symlink)

    def delete_entry(self, path, revnum):
        assert isinstance(path, str)
        path = path.decode("utf-8")
        if path in self.editor._premature_deletes:
            # Delete recursively
            self.editor._premature_deletes.remove(path)
            for p in self.editor._premature_deletes.copy():
                if p.startswith("%s/" % path):
                    self.editor._premature_deletes.remove(p)
        else:
            self.editor.inventory.remove_recursive_id(self.editor._get_old_id(self.old_id, path))


class FileBuildEditor(object):
    def __init__(self, editor, path, file_id, file_parents=[], data="", 
                 is_symlink=False):
        self.path = path
        self.editor = editor
        self.file_id = file_id
        self.file_data = data
        self.is_symlink = is_symlink
        self.file_parents = file_parents
        self.is_executable = None
        self.file_stream = None

    def apply_textdelta(self, base_checksum=None):
        actual_checksum = md5.new(self.file_data).hexdigest()
        assert (base_checksum is None or base_checksum == actual_checksum,
            "base checksum mismatch: %r != %r" % (base_checksum, 
                                                  actual_checksum))
        self.file_stream = StringIO()
        return apply_txdelta_handler(self.file_data, self.file_stream)

    def change_prop(self, name, value):
        if name == properties.PROP_EXECUTABLE: 
            # You'd expect executable to match 
            # properties.PROP_EXECUTABLE_VALUE, but that's not 
            # how SVN behaves. It appears to consider the presence 
            # of the property sufficient to mark it executable.
            self.is_executable = (value != None)
        elif (name == properties.PROP_SPECIAL):
            self.is_symlink = (value != None)
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
        if self.file_stream is not None:
            self.file_stream.seek(0)
            lines = osutils.split_lines(self.file_stream.read())
        else:
            # Data didn't change or file is new
            lines = osutils.split_lines(self.file_data)

        actual_checksum = md5_strings(lines)
        assert checksum is None or checksum == actual_checksum

        self.editor._store_file(self.file_id, lines, self.file_parents)

        assert self.is_symlink in (True, False)

        if self.file_id in self.editor.inventory:
            del self.editor.inventory[self.file_id]

        if self.is_symlink:
            ie = self.editor.inventory.add_path(self.path, 'symlink', self.file_id)
            ie.symlink_target = lines[0][len("link "):]
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
            if self.is_executable is not None:
                ie.executable = self.is_executable

        self.file_stream = None


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
        (rev, signature) = self._get_revision(self.revid)
        self.inventory.revision_id = self.revid
        # Escaping the commit message is really the task of the serialiser
        rev.message = _escape_commit_message(rev.message)
        rev.inventory_sha1 = None
        self.target.add_revision(self.revid, rev, self.inventory)
        if signature is not None:
            self.target.add_signature_text(self.revid, signature)
        self.target.commit_write_group()
        self._write_group_active = False

    def abort(self):
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
    if getattr(repository, '_packs', None):
        return PackRevisionBuildEditor
    return WeaveRevisionBuildEditor


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

    def _find_branches(self, branches, find_ghosts=False, fetch_rhs_ancestry=False, pb=None):
        set_needed = set()
        ret_needed = list()
        for revid in branches:
            if pb:
                pb.update("determining revisions to fetch", branches.index(revid), len(branches))
            try:
                nestedpb = ui.ui_factory.nested_progress_bar()
                for rev in self._find_until(revid, find_ghosts=find_ghosts, fetch_rhs_ancestry=False,
                                            pb=nestedpb):
                    if rev[0] not in set_needed:
                        ret_needed.append(rev)
                        set_needed.add(rev[0])
            finally:
                nestedpb.finished()
        return ret_needed

    def _find_until(self, revision_id, find_ghosts=False, fetch_rhs_ancestry=False, pb=None):
        """Find all missing revisions until revision_id

        :param revision_id: Stop revision
        :param find_ghosts: Find ghosts
        :param fetch_rhs_ancestry: Fetch right hand side ancestors
        :return: Tuple with revisions missing and a dictionary with 
            parents for those revision.
        """
        extra = set()
        needed = []
        revs = []
        meta_map = {}
        lhs_parent = {}
        def check_revid(revision_id):
            prev = None
            (branch_path, revnum, mapping) = self.source.lookup_revision_id(revision_id)
            for revmeta in self.source.iter_reverse_branch_changes(branch_path, revnum, mapping):
                if pb:
                    pb.update("determining revisions to fetch", revnum-revmeta.revnum, revnum)
                revid = revmeta.get_revision_id(mapping)
                lhs_parent[prev] = revid
                meta_map[revid] = revmeta
                if fetch_rhs_ancestry:
                    extra.update(revmeta.get_rhs_parents(mapping))
                if not self.target.has_revision(revid):
                    revs.append(revid)
                elif not find_ghosts:
                    prev = None
                    break
                prev = revid
            lhs_parent[prev] = NULL_REVISION

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

        self.target.lock_write()
        revbuildklass = get_revision_build_editor(self.target)
        editor = revbuildklass(self.source, self.target)

        try:
            for (revid, parent_revid, revmeta) in revids:
                pb.update('copying revision', num, len(revids))

                assert parent_revid is not None

                if parent_revid == NULL_REVISION:
                    parent_inv = Inventory(root_id=None)
                elif prev_revid != parent_revid:
                    parent_inv = self.target.get_inventory(parent_revid)
                else:
                    parent_inv = prev_inv

                editor.start_revision(revid, parent_inv, revmeta)

                try:
                    conn = None
                    try:
                        if parent_revid == NULL_REVISION:
                            branch_url = urlutils.join(repos_root, 
                                                       editor.branch_path)

                            conn = self.source.transport.connections.get(branch_url)
                            reporter = conn.do_update(editor.revnum, "", True, 
                                                           editor)

                            try:
                                # Report status of existing paths
                                reporter.set_path("", editor.revnum, True, None)
                            except:
                                reporter.abort()
                                raise
                        else:
                            (parent_branch, parent_revnum, mapping) = \
                                    self.source.lookup_revision_id(parent_revid)
                            conn = self.source.transport.connections.get(urlutils.join(repos_root, parent_branch))

                            if parent_branch != editor.branch_path:
                                reporter = conn.do_switch(editor.revnum, "", True, 
                                    urlutils.join(repos_root, editor.branch_path), 
                                    editor)
                            else:
                                reporter = conn.do_update(editor.revnum, "", True, editor)

                            try:
                                # Report status of existing paths
                                reporter.set_path("", parent_revnum, False, None)
                            except:
                                reporter.abort()
                                raise

                        reporter.finish()
                    finally:
                        if conn is not None:
                            if not conn.busy:
                                self.source.transport.add_connection(conn)
                except:
                    editor.abort()
                    raise

                prev_inv = editor.inventory
                prev_revid = revid
                num += 1
        finally:
            self.target.unlock()
            if nested_pb is not None:
                nested_pb.finished()

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              branches=None, fetch_rhs_ancestry=False):
        """Fetch revisions. """
        if revision_id == NULL_REVISION:
            return
        # Dictionary with paths as keys, revnums as values

        if pb:
            pb.update("determining revisions to fetch", 0, 2)

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call self.target.add_revision() 
        # or self.target.add_inventory() each time
        self.target.lock_read()
        try:
            if branches is not None:
                needed = self._find_branches(branches, find_ghosts, fetch_rhs_ancestry, pb=pb)
            elif revision_id is None:
                needed = self._find_all(self.source.get_mapping(), pb=pb)
            else:
                needed = self._find_until(revision_id, find_ghosts, fetch_rhs_ancestry, pb=pb)
        finally:
            self.target.unlock()

        if len(needed) == 0:
            # Nothing to fetch
            return

        self._fetch_switch(self.source.transport.get_svn_repos_root(), needed, pb)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, SvnRepository) and target.supports_rich_root()


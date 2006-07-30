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
import bzrlib.osutils as osutils
from bzrlib.progress import DummyProgress
from bzrlib.trace import mutter
from bzrlib.tree import RevisionTree, EmptyTree

import os
import md5
from cStringIO import StringIO

import svn.core, svn.wc, svn.delta
from svn.core import SubversionException, Pool

_global_pool = Pool()

def apply_txdelta_handler(src_stream, target_stream):
    assert hasattr(src_stream, 'read')
    assert hasattr(target_stream, 'write')
    ret = svn.delta.svn_txdelta_apply(
            src_stream, 
            target_stream,
            None,
            _global_pool)

    def wrapper(window):
        svn.delta.invoke_txdelta_window_handler(
            ret[1], window, ret[2])

    return wrapper

class SvnRevisionTree(RevisionTree):
     def __init__(self, repository, revision_id, inventory=None):
        self._repository = repository
        self._revision_id = revision_id
        (self.branch_path, self.revnum) = repository.parse_revision_id(revision_id)
        self._inventory = Inventory()
        self._inventory.revision_id = revision_id
        self.id_map = repository.get_fileid_map(self.revnum, self.branch_path)
        self.editor = TreeBuildEditor(self)
        self.file_data = {}

        editor, baton = svn.delta.make_editor(self.editor)

        root_repos = svn.ra.get_repos_root(repository.ra)
        mutter('svn checkout -r %r %r' % (self.revnum, self.branch_path))
        reporter, reporter_baton = svn.ra.do_switch(repository.ra, self.revnum, "", True, os.path.join(root_repos, self.branch_path), editor, baton)

        svn.ra.reporter2_invoke_set_path(reporter, reporter_baton, "", 0, True, None)

        svn.ra.reporter2_invoke_finish_report(reporter, reporter_baton)

     def get_file_lines(self, file_id):
        return osutils.split_lines(self.file_data[file_id])


class TreeBuildEditor(svn.delta.Editor):
    def __init__(self, tree):
        self.tree = tree
        self.repository = tree._repository
        self.last_revnum = {}
        self.dir_revnum = {}
        self.dir_ignores = {}

    def set_target_revision(self, revnum):
        self.revnum = revnum

    def open_root(self, revnum, baton):
        return ROOT_ID

    def relpath(self, path):
        bp, rp = self.tree._repository.scheme.unprefix(path)
        if bp == self.tree.branch_path:
            return rp
        return None

    def add_directory(self, path, parent_baton, copyfrom_path, copyfrom_revnum, pool):
        file_id, revision_id = self.tree.id_map[path]
        ie = self.tree._inventory.add_path(path, 'directory', file_id)

        ie.revision = revision_id
        return file_id

    def change_dir_prop(self, id, name, value, pool):
        from repository import (SVN_PROP_BZR_MERGE, SVN_PROP_SVK_MERGE, 
                        SVN_PROP_BZR_REVPROP_PREFIX)

        if name == svn.core.SVN_PROP_ENTRY_COMMITTED_REV:
            self.dir_revnum[id] = int(value)
        elif name == svn.core.SVN_PROP_IGNORE:
            self.dir_ignores[id] = value
        elif name == SVN_PROP_BZR_MERGE or name == SVN_PROP_SVK_MERGE:
            if id != ROOT_ID:
                mutter('%r set on non-root dir!' % SVN_PROP_BZR_MERGE)
                return
        elif name in (svn.core.SVN_PROP_ENTRY_COMMITTED_DATE,
                      svn.core.SVN_PROP_ENTRY_LAST_AUTHOR,
                      svn.core.SVN_PROP_ENTRY_LOCK_TOKEN,
                      svn.core.SVN_PROP_ENTRY_UUID,
                      svn.core.SVN_PROP_EXECUTABLE):
            pass
        else:
            mutter('unsupported dir property %r' % name)

    def change_file_prop(self, id, name, value, pool):
        if name == svn.core.SVN_PROP_EXECUTABLE:
            self.is_executable = (value != None)
        elif name == svn.core.SVN_PROP_SPECIAL:
            self.is_symlink = (value != None)
        elif name == svn.core.SVN_PROP_ENTRY_COMMITTED_REV:
            self.last_file_rev = int(value)
        elif name in (svn.core.SVN_PROP_ENTRY_COMMITTED_DATE,
                      svn.core.SVN_PROP_ENTRY_LAST_AUTHOR,
                      svn.core.SVN_PROP_ENTRY_LOCK_TOKEN,
                      svn.core.SVN_PROP_ENTRY_UUID,
                      svn.core.SVN_PROP_MIME_TYPE):
            pass
        else:
            mutter('unsupported file property %r' % name)

    def add_file(self, path, parent_id, copyfrom_path, copyfrom_revnum, baton):
        self.is_symlink = False
        self.is_executable = False
        return path

    def close_dir(self, id):
        if id in self.tree._inventory and self.dir_ignores.has_key(id):
            self.tree._inventory[id].ignores = self.dir_ignores[id]

    def close_file(self, path, checksum):
        file_id, revision_id = self.tree.id_map[path]

        if self.is_symlink:
            ie = self.tree._inventory.add_path(path, 'symlink', file_id)
        else:
            ie = self.tree._inventory.add_path(path, 'file', file_id)
        ie.revision = revision_id

        if self.file_stream:
            self.file_stream.seek(0)
            file_data = self.file_stream.read()
        else:
            file_data = ""

        actual_checksum = md5.new(file_data).hexdigest()
        assert(checksum is None or checksum == actual_checksum,
                "checksum mismatch: %r != %r" % (checksum, actual_checksum))

        if self.is_symlink:
            ie.symlink_target = file_data[len("link "):]
            ie.text_sha1 = None
            ie.text_size = None
            ie.text_id = None
        else:
            ie.text_sha1 = osutils.sha_string(file_data)
            ie.text_size = len(file_data)
            self.tree.file_data[file_id] = file_data
            ie.executable = self.is_executable

        self.file_stream = None

    def close_edit(self):
        pass

    def abort_edit(self):
        pass

    def apply_textdelta(self, file_id, base_checksum):
        self.file_stream = StringIO()
        return apply_txdelta_handler(StringIO(""), self.file_stream)


class SvnInventoryFile(InventoryFile):
    """Inventory entry that can either be a plain file or a 
    symbolic link. Avoids fetching data until necessary. """
    def __init__(self, file_id, name, parent_id, repository, path, revnum, 
                 has_props):
        self.repository = repository
        self.path = path
        self.has_props = has_props
        self.revnum = revnum
        InventoryFile.__init__(self, file_id, name, parent_id)

    def _get_sha1(self):
        text = self.repository._get_file(self.path, self.revnum).read()
        return osutils.sha_string(text)

    def _get_executable(self):
        if not self.has_props:
            return False

        value = self.repository._get_file_prop(self.path, self.revnum, 
                    svn.core.SVN_PROP_EXECUTABLE)
        if value and value == svn.core.SVN_PROP_EXECUTABLE_VALUE:
            return True
        return False 

    def _is_special(self):
        if not self.has_props:
            return False

        value = self.repository._get_file_prop(self.path, self.revnum, 
                    svn.core.SVN_PROP_SPECIAL)
        if value and value == svn.core.SVN_PROP_SPECIAL_VALUE:
            return True
        return False 

    def _get_symlink_target(self):
        if not self._is_special():
            return None
        data = self.repository._get_file(self.path, self.revnum).read()
        if not data.startswith("link "):
            raise BzrError("Improperly formatted symlink file")
        return data[len("link "):]

    def _get_kind(self):
        if self._is_special():
            return 'symlink'
        return 'file'

    # FIXME: we need a set function here because of InventoryEntry.__init__
    def _phony_set(self, data):
        pass
   
    text_sha1 = property(_get_sha1, _phony_set)
    executable = property(_get_executable, _phony_set)
    symlink_target = property(_get_symlink_target, _phony_set)
    kind = property(_get_kind, _phony_set)


class SvnBasisTree(SvnRevisionTree):
    """Optimized version of SvnRevisionTree."""
    def __init__(self, workingtree, revid):
        super(SvnBasisTree, self).__init__(workingtree.branch.repository,
                                           revid)
        self.workingtree = workingtree

    def get_file_lines(self, file_id):
        path = self.id2path(file_id)
        base_copy = svn.wc.get_pristine_copy_path(self.workingtree.abspath(path))
        return osutils.split_lines(open(base_copy).read())


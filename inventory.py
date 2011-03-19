# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Git inventory."""


from dulwich.objects import (
    Blob,
    Tree,
    )


from bzrlib import (
    errors,
    inventory,
    osutils,
    ui,
    )

from bzrlib.plugins.git.mapping import (
    mode_kind,
    mode_is_executable,
    )


class GitInventoryEntry(inventory.InventoryEntry):

    _git_class = None

    def __init__(self, inv, parent_id, hexsha, path, name, executable):
        self.name = name
        self.parent_id = parent_id
        self._inventory = inv
        self._object = None
        self.hexsha = hexsha
        self.path = path
        self.revision = self._inventory.revision_id
        self.executable = executable
        self.file_id = self._inventory.fileid_map.lookup_file_id(
            path.encode('utf-8'))

    @property
    def object(self):
        if self._object is None:
            self._object = self._inventory.store[self.hexsha]
            assert isinstance(self._object, self._git_class), \
                    "Expected instance of %r, got %r" % \
                    (self._git_class, self._object)
        return self._object


class GitInventoryFile(GitInventoryEntry):

    _git_class = Blob

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryFile, self).__init__(inv, parent_id, hexsha, path,
            basename, executable)
        self.kind = 'file'
        self.text_id = None
        self.symlink_target = None

    @property
    def text_sha1(self):
        return osutils.sha_strings(self.object.chunked)

    @property
    def text_size(self):
        return len(self.object.data)

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r, sha1=%r, len=%s, revision=%s)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id,
                   self.text_sha1,
                   self.text_size,
                   self.revision))

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def copy(self):
        other = inventory.InventoryFile(self.file_id, self.name,
            self.parent_id)
        other.executable = self.executable
        other.text_id = self.text_id
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        other.revision = self.revision
        return other


class GitInventoryLink(GitInventoryEntry):

    _git_class = Blob

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryLink, self).__init__(inv, parent_id, hexsha, path, basename, executable)
        self.text_sha1 = None
        self.text_size = None
        self.kind = 'symlink'

    @property
    def symlink_target(self):
        return self.object.data

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def copy(self):
        other = inventory.InventoryLink(self.file_id, self.name, self.parent_id)
        other.executable = self.executable
        other.symlink_target = self.symlink_target
        other.revision = self.revision
        return other


class GitInventoryTreeReference(GitInventoryEntry):

    _git_class = None

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryTreeReference, self).__init__(inv, parent_id, hexsha, path, basename, executable)
        self.hexsha = hexsha
        self.reference_revision = inv.mapping.revision_id_foreign_to_bzr(hexsha)
        self.text_sha1 = None
        self.text_size = None
        self.symlink_target = None
        self.kind = 'tree-reference'
        self._children = None

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return '/'


class GitInventoryDirectory(GitInventoryEntry):

    _git_class = Tree

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryDirectory, self).__init__(inv, parent_id, hexsha, path, basename, executable)
        self.text_sha1 = None
        self.text_size = None
        self.symlink_target = None
        self.kind = 'directory'
        self._children = None

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return '/'

    @property
    def children(self):
        if self._children is None:
            self._retrieve_children()
        return self._children

    def _retrieve_children(self):
        self._children = {}
        for name, mode, hexsha in self.object.iteritems():
            basename = name.decode("utf-8")
            child_path = osutils.pathjoin(self.path, basename)
            if self._inventory.mapping.is_control_file(child_path):
                continue
            executable = mode_is_executable(mode)
            kind_class = {'directory': GitInventoryDirectory,
                          'file': GitInventoryFile,
                          'symlink': GitInventoryLink,
                          'tree-reference': GitInventoryTreeReference}[mode_kind(mode)]
            self._children[basename] = kind_class(self._inventory,
                self.file_id, hexsha, child_path, basename, executable)

    def copy(self):
        other = inventory.InventoryDirectory(self.file_id, self.name,
                                             self.parent_id)
        other.revision = self.revision
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other


class GitInventory(inventory.Inventory):

    def __repr__(self):
        return "<%s for %r in %r>" % (self.__class__.__name__,
                self.root.hexsha, self.store)

    def __init__(self, tree_id, mapping, fileid_map, store, revision_id):
        super(GitInventory, self).__init__(revision_id=revision_id)
        self.store = store
        self.fileid_map = fileid_map
        self.mapping = mapping
        self.root = GitInventoryDirectory(self, None, tree_id, u"", u"", False)

    def _get_ie(self, path):
        if path == "" or path == []:
            return self.root
        if isinstance(path, basestring):
            parts = path.split("/")
        else:
            parts = path
        ie = self.root
        for name in parts:
            ie = ie.children[name]
        return ie

    def has_filename(self, path):
        try:
            self._get_ie(path)
            return True
        except KeyError:
            return False

    def has_id(self, file_id):
        try:
            self.id2path(file_id)
            return True
        except errors.NoSuchId:
            return False

    def id2path(self, file_id):
        path = self.fileid_map.lookup_path(file_id)
        try:
            ie = self._get_ie(path)
        except KeyError:
            raise errors.NoSuchId(None, file_id)

    def path2id(self, path):
        try:
            return self._get_ie(path).file_id
        except KeyError:
            return None

    def __getitem__(self, file_id):
        if file_id == inventory.ROOT_ID:
            return self.root
        path = self.fileid_map.lookup_path(file_id)
        try:
            return self._get_ie(path)
        except KeyError:
            raise errors.NoSuchId(None, file_id)


class GitIndexInventory(inventory.Inventory):
    """Inventory that retrieves its contents from an index file."""

    def __repr__(self):
        return "<%s for %r>" % (self.__class__.__name__, self.index)

    def __init__(self, basis_inventory, fileid_map, index, store):
        if basis_inventory is None:
            root_id = None
        else:
            root_id = basis_inventory.root.file_id
        super(GitIndexInventory, self).__init__(revision_id=None, root_id=root_id)
        self.basis_inv = basis_inventory
        self.fileid_map = fileid_map
        self.index = index
        self._contents_read = False
        self.store = store
        self.root = self.add_path("", 'directory',
            self.fileid_map.lookup_file_id(""), None)

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        self._read_contents()
        return super(GitIndexInventory, self).iter_entries_by_dir(
            specific_file_ids=specific_file_ids, yield_parents=yield_parents)

    def has_id(self, file_id):
        if type(file_id) != str:
            raise AssertionError
        try:
            self.id2path(file_id)
            return True
        except errors.NoSuchId:
            return False

    def has_filename(self, path):
        if path in self.index:
            return True
        self._read_contents()
        return super(GitIndexInventory, self).has_filename(path)

    def id2path(self, file_id):
        if type(file_id) != str:
            raise AssertionError
        path = self.fileid_map.lookup_path(file_id)
        if path in self.index:
            return path
        self._read_contents()
        return super(GitIndexInventory, self).id2path(file_id)

    def path2id(self, path):
        if type(path) in (list, tuple):
            path = "/".join(path)
        encoded_path = path.encode("utf-8")
        if encoded_path in self.index:
            file_id = self.fileid_map.lookup_file_id(encoded_path)
        else:
            self._read_contents()
            file_id = super(GitIndexInventory, self).path2id(path)
        if file_id is not None and type(file_id) is not str:
            raise AssertionError
        return file_id

    def __getitem__(self, file_id):
        self._read_contents()
        return super(GitIndexInventory, self).__getitem__(file_id)

    def _read_contents(self):
        if self._contents_read:
            return
        self._contents_read = True
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, (path, value) in enumerate(self.index.iteritems()):
                pb.update("creating working inventory from index",
                        i, len(self.index))
                assert isinstance(path, str)
                assert isinstance(value, tuple) and len(value) == 10
                (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
                if self.basis_inv is not None:
                    try:
                        old_ie = self.basis_inv._get_ie(path)
                    except KeyError:
                        old_ie = None
                else:
                    old_ie = None
                if old_ie is None:
                    file_id = self.fileid_map.lookup_file_id(path)
                else:
                    file_id = old_ie.file_id
                if type(file_id) != str:
                    raise AssertionError
                kind = mode_kind(mode)
                if old_ie is not None and old_ie.hexsha == sha:
                    # Hasn't changed since basis inv
                    self.add_parents(path)
                    self.add(old_ie)
                else:
                    ie = self.add_path(path.decode("utf-8"), kind, file_id,
                        self.add_parents(path))
                    data = self.store[sha].data
                    if kind == "symlink":
                        ie.symlink_target = data
                    else:
                        ie.text_sha1 = osutils.sha_string(data)
                        ie.text_size = len(data)
                    ie.revision = None
        finally:
            pb.finished()

    def add_parents(self, path):
        assert isinstance(path, str)
        dirname, _ = osutils.split(path)
        file_id = super(GitIndexInventory, self).path2id(dirname)
        if file_id is None:
            if dirname == "":
                parent_fid = None
            else:
                parent_fid = self.add_parents(dirname)
            ie = self.add_path(dirname.decode("utf-8"), 'directory',
                    self.fileid_map.lookup_file_id(dirname), parent_fid)
            if self.basis_inv is not None and ie.file_id in self.basis_inv:
                ie.revision = self.basis_inv[ie.file_id].revision
            file_id = ie.file_id
        if type(file_id) != str:
            raise AssertionError
        return file_id


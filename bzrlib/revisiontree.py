# Copyright (C) 2005 Canonical Ltd
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

"""RevisionTree - a Tree implementation backed by repository data for a revision."""

from cStringIO import StringIO

from bzrlib.tree import Tree


class RevisionTree(Tree):
    """Tree viewing a previous revision.

    File text can be retrieved from the text store.

    TODO: Some kind of `__repr__` method, but a good one
           probably means knowing the branch and revision number,
           or at least passing a description to the constructor.
    """
    
    def __init__(self, branch, inv, revision_id):
        # for compatability the 'branch' parameter has not been renamed to 
        # repository at this point. However, we should change RevisionTree's
        # construction to always be via Repository and not via direct 
        # construction - this will mean that we can change the constructor
        # with much less chance of breaking client code.
        self._repository = branch
        self._weave_store = branch.weave_store
        self._inventory = inv
        self._revision_id = revision_id

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        A RevisionTree's parents match the revision graph.
        """
        if self._revision_id not in (None, 'null:'):
            parent_ids = self._repository.get_revision(
                self._revision_id).parent_ids
        else:
            parent_ids = []
        return parent_ids
        
    def get_revision_id(self):
        """Return the revision id associated with this tree."""
        return self._revision_id

    def get_weave(self, file_id):
        return self._weave_store.get_weave(file_id,
                self._repository.get_transaction())

    def get_file_lines(self, file_id):
        ie = self._inventory[file_id]
        weave = self.get_weave(file_id)
        return weave.get_lines(ie.revision)

    def get_file_text(self, file_id):
        return ''.join(self.get_file_lines(file_id))

    def get_file(self, file_id):
        return StringIO(self.get_file_text(file_id))

    def annotate_iter(self, file_id):
        """See Tree.annotate_iter"""
        w = self.get_weave(file_id)
        return w.annotate_iter(self.inventory[file_id].revision)

    def get_file_size(self, file_id):
        return self._inventory[file_id].text_size

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        ie = self._inventory[file_id]
        if ie.kind == "file":
            return ie.text_sha1
        return None

    def get_file_mtime(self, file_id, path=None):
        ie = self._inventory[file_id]
        revision = self._repository.get_revision(ie.revision)
        return revision.timestamp

    def is_executable(self, file_id, path=None):
        ie = self._inventory[file_id]
        if ie.kind != "file":
            return None 
        return self._inventory[file_id].executable

    def has_filename(self, filename):
        return bool(self.inventory.path2id(filename))

    def list_files(self, include_root=False):
        # The only files returned by this are those from the version
        entries = self.inventory.iter_entries()
        # skip the root for compatability with the current apis.
        if self.inventory.root is not None and not include_root:
            # skip the root for compatability with the current apis.
            entries.next()
        for path, entry in entries:
            yield path, 'V', entry.kind, entry.file_id, entry

    def get_symlink_target(self, file_id):
        ie = self._inventory[file_id]
        return ie.symlink_target;

    def kind(self, file_id):
        return self._inventory[file_id].kind

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def _file_size(self, entry, stat_value):
        assert entry.text_size is not None
        return entry.text_size

    def lock_read(self):
        self._repository.lock_read()

    def unlock(self):
        self._repository.unlock()



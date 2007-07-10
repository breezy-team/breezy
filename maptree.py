# Copyright (C) 2006-2007 by Jelmer Vernooij
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
"""Map Tree."""

from bzrlib.config import Config
from bzrlib.errors import BzrError, NoSuchFile, UnknownFormatError
from bzrlib.generate_ids import gen_revision_id
from bzrlib import osutils
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
import bzrlib.ui as ui


def map_file_ids(repository, old_parents, new_parents):
    """Try to determine the equivalent file ids in two sets of parents.

    :param repository: Repository to use
    :param old_parents: List of revision ids of old parents
    :param new_parents: List of revision ids of new parents
    """
    assert len(old_parents) == len(new_parents)
    ret = {}
    for (oldp, newp) in zip(old_parents, new_parents):
        oldinv = repository.get_revision_inventory(oldp)
        newinv = repository.get_revision_inventory(newp)
        for path, ie in oldinv.iter_entries():
            if newinv.has_filename(path):
                ret[ie.file_id] = newinv.path2id(path)
    return ret


class MapInventory:
    def __init__(self, oldinv, maptree):
        self.oldinv = oldinv
        self.maptree = maptree

    def map_ie(self, ie):
        """Fix the references to old file ids in an inventory entry.

        :param ie: Inventory entry to map
        :return: New inventory entry
        """
        new_ie = ie.copy()
        new_ie.file_id = self.maptree.new_id(new_ie.file_id)
        new_ie.parent_id = self.maptree.new_id(new_ie.parent_id)
        return new_ie

    def __len__(self):
        return len(self.oldinv)

    def iter_entries(self):
        for path, ie in self.oldinv.iter_entries():
            yield path, self.map_ie(ie)

    def path2id(self, path):
        return self.maptree.new_id(self.oldinv.path2id(path))

    def id2path(self, id):
        return self.oldinv.id2path(self.maptree.old_id(id))

    def has_id(self, id):
        return self.oldinv.has_id(self.maptree.old_id(id))


class MapTree:
    """Wrapper around a tree that translates file ids.
    """
    # TODO: Inventory
    def __init__(self, oldtree, fileid_map):
        """Create a new MapTree. 

        :param oldtree: Old tree to map to.
        :param fileid_map: Map with old -> new file ids.
        """
        self.oldtree = oldtree
        self.map = fileid_map
        self.inventory = MapInventory(self.oldtree.inventory, self)

    def old_id(self, file_id):
        """Look up the original file id of a file.

        :param file_id: New file id
        :return: Old file id if mapped, otherwise new file id
        """
        for x in self.map:
            if self.map[x] == file_id:
                return x
        return file_id

    def new_id(self, file_id):
        """Look up the new file id of a file.

        :param file_id: Old file id
        :return: New file id
        """
        try:
            return self.map[file_id]
        except KeyError:
            return file_id

    def get_file_sha1(self, file_id, path=None):
        return self.oldtree.get_file_sha1(file_id=self.old_id(file_id), 
                                          path=path)

    def get_file(self, file_id):
        return self.oldtree.get_file(self.old_id(file_id=file_id))

    def is_executable(self, file_id, path=None):
        return self.oldtree.is_executable(self.old_id(file_id=file_id), 
                                          path=path)

    def has_filename(self, filename):
        return self.oldtree.has_filename(filename)

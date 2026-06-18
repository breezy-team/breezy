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


def map_file_ids(repository, old_parents, new_parents):
    """Try to determine the equivalent file ids in two sets of parents.

    :param repository: Repository to use
    :param old_parents: List of revision ids of old parents
    :param new_parents: List of revision ids of new parents
    """
    if len(old_parents) != len(new_parents):
        raise ValueError(
            f"Number of parents does not match: {len(old_parents)} != {len(new_parents)}"
        )
    ret = {}
    for oldp, newp in zip(old_parents, new_parents, strict=False):
        oldtree = repository.revision_tree(oldp)
        newtree = repository.revision_tree(newp)
        for path, ie in oldtree.iter_entries_by_dir():
            file_id = newtree.path2id(path)
            if file_id is not None:
                ret[ie.file_id] = file_id
    return ret


class MapTree:
    """Wrapper around a tree that translates file ids."""

    def __init__(self, oldtree, fileid_map):
        """Create a new MapTree.

        :param oldtree: Old tree to map to.
        :param fileid_map: Map with old -> new file ids.
        """
        self.oldtree = oldtree
        self.map = fileid_map

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

    def get_file_sha1(self, path, file_id=None):
        """See Tree.get_file_sha1()."""
        return self.oldtree.get_file_sha1(path)

    def get_file_with_stat(self, path, file_id=None):
        """See Tree.get_file_with_stat()."""
        if getattr(self.oldtree, "get_file_with_stat", None) is not None:
            return self.oldtree.get_file_with_stat(path=path)
        else:
            return self.get_file(path), None

    def get_file(self, path, file_id=None):
        """See Tree.get_file()."""
        return self.oldtree.get_file(path)

    def is_executable(self, path, file_id=None):
        """See Tree.is_executable()."""
        return self.oldtree.is_executable(path)

    def has_filename(self, filename):
        """See Tree.has_filename()."""
        return self.oldtree.has_filename(filename)

    def path_content_summary(self, path):
        """See Tree.path_content_summary()."""
        return self.oldtree.path_content_summary(path)

    def map_ie(self, ie):
        """Fix the references to old file ids in an inventory entry.

        :param ie: Inventory entry to map
        :return: New inventory entry
        """
        new_ie = ie.copy()
        new_ie.file_id = self.new_id(new_ie.file_id)
        new_ie.parent_id = self.new_id(new_ie.parent_id)
        return new_ie

    def iter_entries_by_dir(self):
        """See Tree.iter_entries_by_dir."""
        for path, ie in self.oldtree.iter_entries_by_dir():
            yield path, self.map_ie(ie)

    def path2id(self, path):
        """Return the file id for a path.

        Args:
            path: The path to look up.

        Returns:
            The new file id for the path, or None if the path doesn't exist.
        """
        file_id = self.oldtree.path2id(path)
        if file_id is None:
            return None
        return self.new_id(file_id)

    def id2path(self, file_id, recurse="down"):
        """Return the path for a file id.

        Args:
            file_id: The file id to look up.
            recurse: Direction to recurse when building the path.

        Returns:
            The path corresponding to the file id.
        """
        return self.oldtree.id2path(self.old_id(file_id=file_id), recurse=recurse)

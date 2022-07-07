# Copyright (C) 2006, 2008, 2009, 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""TreeBuilder helper class.

TreeBuilders are used to build trees of various shapes or properties. This
can be extremely useful in testing for instance.
"""

from . import errors


class AlreadyBuilding(errors.BzrError):

    _fmt = "The tree builder is already building a tree."


class NotBuilding(errors.BzrError):

    _fmt = "Not currently building a tree."


class TreeBuilder(object):
    """A TreeBuilder allows the creation of specific content in one tree at a
    time.
    """

    def __init__(self):
        """Construct a TreeBuilder."""
        self._tree = None
        self._root_done = False

    def build(self, recipe):
        """Build recipe into the current tree.

        :param recipe: A sequence of paths. For each path, the corresponding
            path in the current tree is created and added. If the path ends in
            '/' then a directory is added, otherwise a regular file is added.
        """
        self._ensure_building()
        if not self._root_done:
            self._tree.add('', 'directory', ids=b'root-id')
            self._root_done = True
        for name in recipe:
            if name.endswith('/'):
                self._tree.mkdir(name[:-1])
            else:
                end = b'\n'
                content = b"contents of %s%s" % (name.encode('utf-8'), end)
                self._tree.add(name, 'file')
                self._tree.put_file_bytes_non_atomic(name, content)

    def _ensure_building(self):
        """Raise NotBuilding if there is no current tree being built."""
        if self._tree is None:
            raise NotBuilding

    def finish_tree(self):
        """Finish building the current tree."""
        self._ensure_building()
        tree = self._tree
        self._tree = None
        tree.unlock()

    def start_tree(self, tree):
        """Start building on tree.

        :param tree: A tree to start building on. It must provide the
            MutableTree interface.
        """
        if self._tree is not None:
            raise AlreadyBuilding
        self._tree = tree
        self._tree.lock_tree_write()

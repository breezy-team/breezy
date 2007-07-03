# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Helper functions for adding files to working trees."""

import errno
import os
import sys

import bzrlib.bzrdir
import bzrlib.errors as errors
import bzrlib.osutils
from bzrlib.symbol_versioning import *
from bzrlib.workingtree import WorkingTree


class AddAction(object):
    """A class which defines what action to take when adding a file."""

    def __init__(self, to_file=None, should_print=None):
        """Initialize an action which prints added files to an output stream.

        :param to_file: The stream to write into. This is expected to take
            Unicode paths. If not supplied, it will default to ``sys.stdout``.
        :param should_print: If False, printing will be supressed.
        """
        self._to_file = to_file
        if to_file is None:
            self._to_file = sys.stdout
        self.should_print = False
        if should_print is not None:
            self.should_print = should_print

    def __call__(self, inv, parent_ie, path, kind, _quote=bzrlib.osutils.quotefn):
        """Add path to inventory.

        The default action does nothing.

        :param inv: The inventory we are working with.
        :param path: The FastPath being added
        :param kind: The kind of the object being added.
        """
        if self.should_print:
            self._to_file.write('added %s\n' % _quote(path.raw_path))
        return None


class AddFromBaseAction(AddAction):
    """This class will try to extract file ids from another tree."""

    def __init__(self, base_tree, base_path, to_file=None, should_print=None):
        super(AddFromBaseAction, self).__init__(to_file=to_file,
                                                should_print=should_print)
        self.base_tree = base_tree
        self.base_path = base_path

    def __call__(self, inv, parent_ie, path, kind):
        # Place the parent call
        # Now check to see if we can extract an id for this file
        file_id, base_path = self._get_base_file_id(path, parent_ie)
        if file_id is not None:
            if self.should_print:
                self._to_file.write('added %s w/ file id from %s\n'
                                    % (path.raw_path, base_path))
        else:
            # we aren't doing anything special, so let the default
            # reporter happen
            file_id = super(AddFromBaseAction, self).__call__(
                        inv, parent_ie, path, kind)
        return file_id

    def _get_base_file_id(self, path, parent_ie):
        """Look for a file id in the base branch.

        First, if the base tree has the parent directory,
        we look for a file with the same name in that directory.
        Else, we look for an entry in the base tree with the same path.
        """

        if (parent_ie.file_id in self.base_tree):
            base_parent_ie = self.base_tree.inventory[parent_ie.file_id]
            base_child_ie = base_parent_ie.children.get(path.base_path)
            if base_child_ie is not None:
                return (base_child_ie.file_id,
                        self.base_tree.id2path(base_child_ie.file_id))
        full_base_path = bzrlib.osutils.pathjoin(self.base_path, path.raw_path)
        # This may return None, but it is our last attempt
        return self.base_tree.path2id(full_base_path), full_base_path


# TODO: jam 20050105 These could be used for compatibility
#       however, they bind against the current stdout, not the
#       one which exists at the time they are called, so they
#       don't work for the test suite.
# deprecated
add_action_add = AddAction()
add_action_null = add_action_add
add_action_add_and_print = AddAction(should_print=True)
add_action_print = add_action_add_and_print


@deprecated_function(zero_eighteen)
def smart_add(file_list, recurse=True, action=None, save=True):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    Returns the number of files added.
    Deprecated in 0.18. Please use MutableTree.smart_add.
    """
    tree = WorkingTree.open_containing(file_list[0])[0]
    return smart_add_tree(tree, file_list, recurse, action=action, save=save)


@deprecated_function(zero_eighteen)
def smart_add_tree(tree, file_list, recurse=True, action=None, save=True):
    """Deprecated in 0.18. Please use MutableTree.smart_add."""
    return tree.smart_add(file_list, recurse, action, save)


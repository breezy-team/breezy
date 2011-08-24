# Copyright (C) 2005-2010 Canonical Ltd
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

"""Helper functions for adding files to working trees."""

import sys
import os

from bzrlib import (
    osutils,
    ui, 
    )


class AddAction(object):
    """A class which defines what action to take when adding a file."""

    def __init__(self, to_file=None, should_print=None):
        """Initialize an action which prints added files to an output stream.

        :param to_file: The stream to write into. This is expected to take
            Unicode paths. If not supplied, it will default to ``sys.stdout``.
        :param should_print: If False, printing will be suppressed.
        """
        self._to_file = to_file
        if to_file is None:
            self._to_file = sys.stdout
        self.should_print = False
        if should_print is not None:
            self.should_print = should_print

    def __call__(self, inv, parent_ie, path, kind, _quote=osutils.quotefn):
        """Add path to inventory.

        The default action does nothing.

        :param inv: The inventory we are working with.
        :param path: The FastPath being added
        :param kind: The kind of the object being added.
        """
        if self.should_print:
            self._to_file.write('adding %s\n' % _quote(path))
        return None

    def skip_file(self, tree, path, kind, stat_value = None):
        """Test whether the given file should be skipped or not.
        
        The default action never skips. Note this is only called during
        recursive adds
        
        :param tree: The tree we are working in
        :param path: The path being added
        :param kind: The kind of object being added.
        :param stat: Stat result for this file, if available already
        :return bool. True if the file should be skipped (not added)
        """
        return False


class AddWithSkipLargeAction(AddAction):
    """A class that can decide to skip a file if it's considered too large"""

    # default 20 MB
    _DEFAULT_MAX_FILE_SIZE = 20000000
    _optionName = 'add.maximum_file_size'
    _maxSize = None

    def skip_file(self, tree, path, kind, stat_value = None):
        if kind != 'file':
            return False            
        if self._maxSize is None:
            config = tree.branch.get_config()
            self._maxSize = config.get_user_option_as_int_from_SI(
                self._optionName,  
                self._DEFAULT_MAX_FILE_SIZE)
        if stat_value is None:
            file_size = os.path.getsize(path);
        else:
            file_size = stat_value.st_size;
        if self._maxSize > 0 and file_size > self._maxSize:
            ui.ui_factory.show_warning(
                "skipping %s (larger than %s of %d bytes)" % 
                (path, self._optionName,  self._maxSize))
            return True
        return False


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
                self._to_file.write('adding %s w/ file id from %s\n'
                                    % (path, base_path))
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

        if self.base_tree.has_id(parent_ie.file_id):
            base_parent_ie = self.base_tree.inventory[parent_ie.file_id]
            base_child_ie = base_parent_ie.children.get(
                osutils.basename(path))
            if base_child_ie is not None:
                return (base_child_ie.file_id,
                        self.base_tree.id2path(base_child_ie.file_id))
        full_base_path = osutils.pathjoin(self.base_path, path)
        # This may return None, but it is our last attempt
        return self.base_tree.path2id(full_base_path), full_base_path
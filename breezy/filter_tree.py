# Copyright (C) 2011 Canonical Ltd
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

"""Content-filtered view of any tree.
"""

from io import BytesIO

from . import (
    tree,
    )
from .filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )


class ContentFilterTree(tree.Tree):
    """A virtual tree that applies content filters to an underlying tree.

    Not every operation is supported yet.
    """

    def __init__(self, backing_tree, filter_stack_callback):
        """Construct a new filtered tree view.

        :param filter_stack_callback: A callable taking a path that returns
            the filter stack that should be used for that path.
        :param backing_tree: An underlying tree to wrap.
        """
        self.backing_tree = backing_tree
        self.filter_stack_callback = filter_stack_callback

    def get_file_text(self, path):
        chunks = self.backing_tree.get_file_lines(path)
        filters = self.filter_stack_callback(path)
        context = ContentFilterContext(path, self)
        contents = filtered_output_bytes(chunks, filters, context)
        content = b''.join(contents)
        return content

    def get_file(self, path):
        return BytesIO(self.get_file_text(path))

    def has_filename(self, filename):
        return self.backing_tree.has_filename

    def is_executable(self, path):
        return self.backing_tree.is_executable(path)

    def iter_entries_by_dir(self, specific_files=None, recurse_nested=False):
        # NB: This simply returns the parent tree's entries; the length may be
        # wrong but it can't easily be calculated without filtering the whole
        # text.  Currently all callers cope with this; perhaps they should be
        # updated to a narrower interface that only provides things guaranteed
        # cheaply available across all trees. -- mbp 20110705
        return self.backing_tree.iter_entries_by_dir(
            specific_files=specific_files, recurse_nested=recurse_nested)

    def lock_read(self):
        return self.backing_tree.lock_read()

    def unlock(self):
        return self.backing_tree.unlock()

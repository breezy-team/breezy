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

"""Export a Tree to a non-versioned directory.
"""


import os
import StringIO

from bzrlib import errors, osutils
from bzrlib.filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )
from bzrlib.trace import mutter


def dir_exporter(tree, dest, root, filtered=False):
    """Export this tree to a new directory.

    `dest` should not exist, and will be created holding the
    contents of this tree.

    TODO: To handle subdirectories we need to create the
           directories first.

    :note: If the export fails, the destination directory will be
           left in a half-assed state.
    """
    os.mkdir(dest)
    mutter('export version %r', tree)
    inv = tree.inventory
    entries = inv.iter_entries()
    entries.next() # skip root
    for dp, ie in entries:
        # .bzrignore has no meaning outside of a working tree
        # so do not export it
        if dp == ".bzrignore":
            continue
        
        fullpath = osutils.pathjoin(dest, dp)
        if ie.kind == "file":
            if filtered:
                chunks = tree.get_file_lines(ie.file_id)
                filters = tree._content_filter_stack(dp)
                context = ContentFilterContext(dp)
                contents = filtered_output_bytes(chunks, filters, context)
                content = ''.join(contents)
                fileobj = StringIO.StringIO(content)
            else:
                fileobj = tree.get_file(ie.file_id)
            osutils.pumpfile(fileobj, file(fullpath, 'wb'))
            if tree.is_executable(ie.file_id):
                os.chmod(fullpath, 0755)
        elif ie.kind == "directory":
            os.mkdir(fullpath)
        elif ie.kind == "symlink":
            try:
                os.symlink(ie.symlink_target, fullpath)
            except OSError,e:
                raise errors.BzrError(
                    "Failed to create symlink %r -> %r, error: %s"
                    % (fullpath, self.symlink_target, e))
        else:
            raise errors.BzrError("don't know how to export {%s} of kind %r" %
               (ie.file_id, ie.kind))

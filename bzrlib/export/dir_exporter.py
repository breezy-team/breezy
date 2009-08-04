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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Export a Tree to a non-versioned directory.
"""

import errno
import os
import StringIO

from bzrlib import errors, osutils
from bzrlib.export import _export_iter_entries
from bzrlib.filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )
from bzrlib.trace import mutter


def dir_exporter(tree, dest, root, subdir, filtered=False):
    """Export this tree to a new directory.

    `dest` should not exist, and will be created holding the
    contents of this tree.

    TODO: To handle subdirectories we need to create the
           directories first.

    :note: If the export fails, the destination directory will be
           left in a half-assed state.
    """
    mutter('export version %r', tree)
    try:
        os.mkdir(dest)
    except OSError, e:
        if e.errno == errno.EEXIST:
            # check if directory empty
            if os.listdir(dest) != []:
                raise errors.BzrError("Can't export tree to non-empty directory.")
        else:
            raise
    for dp, ie in _export_iter_entries(tree, subdir):
        fullpath = osutils.pathjoin(dest, dp)
        if ie.kind == "file":
            if filtered:
                chunks = tree.get_file_lines(ie.file_id)
                filters = tree._content_filter_stack(dp)
                context = ContentFilterContext(dp, tree, ie)
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
                symlink_target = tree.get_symlink_target(ie.file_id)
                os.symlink(symlink_target, fullpath)
            except OSError,e:
                raise errors.BzrError(
                    "Failed to create symlink %r -> %r, error: %s"
                    % (fullpath, symlink_target, e))
        else:
            raise errors.BzrError("don't know how to export {%s} of kind %r" %
               (ie.file_id, ie.kind))

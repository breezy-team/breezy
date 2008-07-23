# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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
import sys
import tarfile
import time

from bzrlib import errors, export, osutils
from bzrlib.filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )
from bzrlib.trace import mutter


def tar_exporter(tree, dest, root, compression=None, filtered=False):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    now = time.time()
    compression = str(compression or '')
    if dest == '-':
        # XXX: If no root is given, the output tarball will contain files
        # named '-/foo'; perhaps this is the most reasonable thing.
        ball = tarfile.open(None, 'w|' + compression, sys.stdout)
    else:
        if root is None:
            root = export.get_root_name(dest)
        ball = tarfile.open(dest, 'w:' + compression)
    mutter('export version %r', tree)
    inv = tree.inventory
    entries = inv.iter_entries()
    entries.next() # skip root
    for dp, ie in entries:
        # .bzrignore has no meaning outside of a working tree
        # so do not export it
        if dp == ".bzrignore":
            continue

        filename = osutils.pathjoin(root, dp).encode('utf8')
        item = tarfile.TarInfo(filename)
        item.mtime = now
        if ie.kind == "file":
            item.type = tarfile.REGTYPE
            if tree.is_executable(ie.file_id):
                item.mode = 0755
            else:
                item.mode = 0644
            if filtered:
                chunks = tree.get_file_lines(ie.file_id)
                filters = tree._content_filter_stack(dp)
                context = ContentFilterContext(dp)
                contents = filtered_output_bytes(chunks, filters, context)
                content = ''.join(contents)
                item.size = len(content)
                fileobj = StringIO.StringIO(content)
            else:
                item.size = ie.text_size
                fileobj = tree.get_file(ie.file_id)
        elif ie.kind == "directory":
            item.type = tarfile.DIRTYPE
            item.name += '/'
            item.size = 0
            item.mode = 0755
            fileobj = None
        elif ie.kind == "symlink":
            item.type = tarfile.SYMTYPE
            item.size = 0
            item.mode = 0755
            item.linkname = ie.symlink_target
            fileobj = None
        else:
            raise BzrError("don't know how to export {%s} of kind %r" %
                           (ie.file_id, ie.kind))
        ball.addfile(item, fileobj)
    ball.close()


def tgz_exporter(tree, dest, root, filtered=False):
    tar_exporter(tree, dest, root, compression='gz', filtered=filtered)


def tbz_exporter(tree, dest, root, filtered=False):
    tar_exporter(tree, dest, root, compression='bz2', filtered=filtered)

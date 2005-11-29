# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Export a Tree to a non-versioned directory.
"""

import os
from bzrlib.trace import mutter
import tarfile


def tar_exporter(tree, dest, root, compression=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    from time import time
    now = time()
    compression = str(compression or '')
    if root is None:
        root = get_root_name(dest)
    try:
        ball = tarfile.open(dest, 'w:' + compression)
    except tarfile.CompressionError, e:
        raise BzrError(str(e))
    mutter('export version %r', tree)
    inv = tree.inventory
    for dp, ie in inv.iter_entries():
        mutter("  export {%s} kind %s to %s", ie.file_id, ie.kind, dest)
        item, fileobj = ie.get_tar_item(root, dp, now, tree)
        ball.addfile(item, fileobj)
    ball.close()


def tgz_exporter(tree, dest, root):
    tar_exporter(tree, dest, root, compression='gz')


def tbz_exporter(tree, dest, root):
    tar_exporter(tree, dest, root, compression='bz2')


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

def dir_exporter(tree, dest, root):
    """Export this tree to a new directory.

    `dest` should not exist, and will be created holding the
    contents of this tree.

    TODO: To handle subdirectories we need to create the
           directories first.

    :note: If the export fails, the destination directory will be
           left in a half-assed state.
    """
    import os
    os.mkdir(dest)
    mutter('export version %r', tree)
    inv = tree.inventory
    for dp, ie in inv.iter_entries():
        # .bzrignore has no meaning outside of a working tree
        # so do not export it
        if dp == ".bzrignore":
            continue
        
        ie.put_on_disk(dest, dp, tree)


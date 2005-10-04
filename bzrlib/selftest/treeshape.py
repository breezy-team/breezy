# Copyright (C) 2005 by Canonical Ltd

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


"""Test helper for constructing and testing directories.

This module transforms filesystem directories to and from Python lists.  
As a Python list the descriptions can be stored in test cases, compared,
etc.
"""

# TODO: Script to write a description of a directory for testing
# TODO: Helper that compares two structures and raises a helpful error
# where they differ.  Option to ignore some files or directories in the 
# comparison.

import os

def build_tree_contents(template):
    """Reconstitute some files from a text description.

    Each element of template is a tuple.  The first element is a filename,
    with an optional ending character indicating the type.

    The template is built relative to the Python process's current
    working directory.
    """
    for tt in template:
        name = tt[0]
        if name[-1] == '/':
            os.mkdir(name)
        elif name[-1] == '@':
            raise NotImplementedError('symlinks not handled yet')
        else:
            f = file(name, 'wb')
            try:
                f.write(tt[1])
            finally:
                f.close()


def pack_tree_contents(top):
    """Make a Python datastructure description of a tree.
    
    If top is an absolute path the descriptions will be absolute."""
    for dirpath, dirnames, filenames in os.walk(top):
        yield (dirpath + '/', )
        filenames.sort()
        for fn in filenames:
            fullpath = os.path.join(dirpath, fn)
            yield (fullpath, file(fullpath, 'rb').read())

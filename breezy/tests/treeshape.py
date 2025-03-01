# Copyright (C) 2005, 2010 Canonical Ltd
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
import stat

from ..osutils import pathjoin
from ..trace import warning


def build_tree_contents(template):
    """Reconstitute some files from a text description.

    Each element of template is a tuple.  The first element is a filename,
    with an optional ending character indicating the type.

    The template is built relative to the Python process's current
    working directory.

    ('foo/',) will build a directory.
    ('foo', 'bar') will write 'bar' to 'foo'
    ('foo@', 'linktarget') will raise an error
    """
    for tt in template:
        name = tt[0]
        if name[-1] == "/":
            os.mkdir(name)
        elif name[-1] == "@":
            os.symlink(tt[1], tt[0][:-1])
        else:
            with open(name, "w" + ("b" if isinstance(tt[1], bytes) else "")) as f:
                f.write(tt[1])


def capture_tree_contents(top):
    """Make a Python datastructure description of a tree.

    If top is an absolute path the descriptions will be absolute.
    """
    for dirpath, _dirnames, filenames in os.walk(top):
        yield (dirpath + "/",)
        filenames.sort()
        for fn in filenames:
            fullpath = pathjoin(dirpath, fn)
            if fullpath[-1] in "@/":
                raise AssertionError(fullpath)
            info = os.lstat(fullpath)
            if stat.S_ISLNK(info.st_mode):
                yield (fullpath + "@", os.readlink(fullpath))
            elif stat.S_ISREG(info.st_mode):
                with open(fullpath, "rb") as f:
                    file_bytes = f.read()
                yield (fullpath, file_bytes)
            else:
                warning("can't capture file %s with mode %#o", fullpath, info.st_mode)
                pass

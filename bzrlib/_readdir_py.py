# Copyright (C) 2006, 2008 Canonical Ltd
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

"""Python implementation of readdir interface."""


import os


def read_dir(path):
    """Like os.listdir, this reads the contents of a directory.

    There is a C module which is recommended which will return
    a sort key in the first element of the tuple to allow slightly
    more efficient behaviour on the operating systems part.

    :param path: the directory to list.
    :return: a list of (None, basename) tuples.
    """
    return [(None, name) for name in os.listdir(path)]

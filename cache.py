# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>
#               2007 David Allouche <ddaa@ddaa.net>

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
"""Git cache directory access."""

# Shamelessly copied from bzr-svn.

import os

import sqlite3

from bzrlib.config import config_dir, ensure_config_dir_exists


def create_cache_dir():
    """Create the top-level bzr-git cache directory.

    :return: Path to cache directory.
    """
    ensure_config_dir_exists()
    cache_dir = os.path.join(config_dir(), 'git-cache')

    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)

        open(os.path.join(cache_dir, "README"), 'w').write(
"""This directory contains information cached by the bzr-git plugin.

It is used for performance reasons only and can be removed
without losing data.

""")
    return cache_dir

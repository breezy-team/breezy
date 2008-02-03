# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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
"""Subversion cache directory access."""

import bzrlib
from bzrlib.config import config_dir, ensure_config_dir_exists
from bzrlib.trace import warning

import os

def create_cache_dir():
    """Create the top-level bzr-svn cache directory.
    
    :return: Path to cache directory.
    """
    ensure_config_dir_exists()
    cache_dir = os.path.join(config_dir(), 'svn-cache')

    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)

        open(os.path.join(cache_dir, "README"), 'w').write(
"""This directory contains information cached by the bzr-svn plugin.

It is used for performance reasons only and can be removed 
without losing data.

See http://bazaar-vcs.org/BzrForeignBranches/Subversion for details.
""")
    return cache_dir


def check_pysqlite_version(sqlite3):
    """Check that sqlite library is compatible.

    """
    if (sqlite3.sqlite_version_info[0] < 3 or 
            (sqlite3.sqlite_version_info[0] == 3 and 
             sqlite3.sqlite_version_info[1] < 3)):
        warning('Needs at least sqlite 3.3.x')
        raise bzrlib.errors.BzrError("incompatible sqlite library")

try:
    try:
        import sqlite3
        check_pysqlite_version(sqlite3)
    except (ImportError, bzrlib.errors.BzrError), e: 
        from pysqlite2 import dbapi2 as sqlite3
        check_pysqlite_version(sqlite3)
except:
    warning('Needs at least Python2.5 or Python2.4 with the pysqlite2 '
            'module')
    raise bzrlib.errors.BzrError("missing sqlite library")


class CacheTable:
    """Simple base class for SQLite-based caches."""
    def __init__(self, cache_db=None):
        if cache_db is None:
            self.cachedb = sqlite3.connect(":memory:")
        else:
            self.cachedb = cache_db
        self._create_table()
        self.cachedb.commit()

    def _create_table(self):
        pass

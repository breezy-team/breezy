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

from bzrlib.errors import (InvalidRevisionId, NoSuchRevision, 
                           NotBranchError, UninitializableFormat)

MAPPING_VERSION = 3
REVISION_ID_PREFIX = "svn-v%d-" % MAPPING_VERSION

import urllib

try:
    import sqlite3
except ImportError:
    from pysqlite2 import dbapi2 as sqlite3

def escape_svn_path(x):
    if isinstance(x, unicode):
        x = x.encode("utf-8")
    return urllib.quote(x, "")
unescape_svn_path = urllib.unquote


def parse_svn_revision_id(revid):
    """Parse an existing Subversion-based revision id.

    :param revid: The revision id.
    :raises: InvalidRevisionId
    :return: Tuple with uuid, branch path and revision number.
    """

    assert revid
    assert isinstance(revid, basestring)

    if not revid.startswith(REVISION_ID_PREFIX):
        raise InvalidRevisionId(revid, "")

    try:
        (version, uuid, branch_path, srevnum)= revid.split(":")
    except ValueError:
        raise InvalidRevisionId(revid, "")

    revid = revid[len(REVISION_ID_PREFIX):]

    return (uuid, unescape_svn_path(branch_path), int(srevnum))


def generate_svn_revision_id(uuid, revnum, path, scheme="undefined"):
    """Generate a unambiguous revision id. 
    
    :param uuid: UUID of the repository.
    :param revnum: Subversion revision number.
    :param path: Branch path.
    :param scheme: Name of the branching scheme in use

    :return: New revision id.
    """
    assert isinstance(revnum, int)
    assert isinstance(path, basestring)
    assert revnum >= 0
    assert revnum > 0 or path == "", \
            "Trying to generate revid for (%r,%r)" % (path, revnum)
    return "%s%s:%s:%s:%d" % (REVISION_ID_PREFIX, scheme, uuid, \
                   escape_svn_path(path.strip("/")), revnum)


class RevidMap(object):
    """Revision id mapping store. 

    Stores mapping from revid -> (path, revnum, scheme)
    """
    def __init__(self, cache_db=None):
        if cache_db is None:
            self.cachedb = sqlite3.connect(":memory:")
        else:
            self.cachedb = cache_db
        self.cachedb.executescript("""
        create table if not exists revmap (revid text, path text, min_revnum integer, max_revnum integer, scheme text);
        create index if not exists revid on revmap (revid);
        """)
        self.cachedb.commit()
    
    def lookup_revid(self, revid):
        for branch, revnum, scheme in self.cachedb.execute(
                "select path, min_revnum, max_revnum, scheme from revmap where revid='%s'" % revid):
            return branch, min_revnum, max_revnum, scheme
        raise NoSuchRevision(self, revid)

    def insert_revid(self, revid, branch, min_revnum, max_revnum, scheme):
        self.cachedb.execute("insert into revmap (revid, path, min_revnum, max_revnum, scheme) VALUES (?, ?, ?, ?, ?)", (revid, branch, min_revnum, max_revnum, scheme))

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
from bzrlib.trace import mutter

MAPPING_VERSION = 3
REVISION_ID_PREFIX = "svn-v%d-" % MAPPING_VERSION

import urllib

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

    assert revid is not None
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
            from cache import sqlite3
            self.cachedb = sqlite3.connect(":memory:")
        else:
            self.cachedb = cache_db
        self.cachedb.executescript("""
        create table if not exists revmap (revid text, path text, min_revnum integer, max_revnum integer, scheme text, dist_to_origin integer);
        create index if not exists revid on revmap (revid);
        """)
        self.cachedb.commit()
    
    def lookup_revid(self, revid):
        mutter('lookup branch revid %r' % revid)
        ret = self.cachedb.execute(
            "select path, min_revnum, max_revnum, scheme from revmap where revid='%s'" % revid).fetchone()
        if ret is None:
            raise NoSuchRevision(self, revid)
        return (str(ret[0]), ret[1], ret[2], ret[3])

    def lookup_branch_revnum(self, revnum, path):
        mutter('lookup branch revnum %r, %r' % (revnum, path))
        # FIXME: SCHEME MISSING
        revid = self.cachedb.execute(
                "select revid from revmap where max_revnum = min_revnum and min_revnum='%s' and path='%s'" % (revnum, path)).fetchone()
        if revid is not None:
            return str(revid[0])
        return None

    def insert_revid(self, revid, branch, min_revnum, max_revnum, scheme, 
                     dist_to_origin=None):
        assert revid is not None and revid != ""
        self.cachedb.execute(
            "insert into revmap (revid, path, min_revnum, max_revnum, scheme) VALUES (?, ?, ?, ?, ?)", 
            (revid, branch, min_revnum, max_revnum, scheme))
        if dist_to_origin is not None:
            self.cachedb.execute(
                "update revmap set dist_to_origin = ?", 
                (dist_to_origin,))

    def lookup_dist_to_origin(self, revid):
        revno = self.cachedb.execute(
                "select dist_to_origin from revmap where revid='%s'" % revid).fetchone()
        if revno is not None and revno[0] is not None:
            return int(revno[0])
        return None


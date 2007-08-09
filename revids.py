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

from bzrlib.errors import (InvalidRevisionId, NoSuchRevision)

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
    :return: Tuple with uuid, branch path, revision number and scheme.
    """

    assert revid is not None
    assert isinstance(revid, basestring)

    if not revid.startswith(REVISION_ID_PREFIX):
        raise InvalidRevisionId(revid, "")

    try:
        (version, uuid, branch_path, srevnum) = revid.split(":")
    except ValueError:
        raise InvalidRevisionId(revid, "")

    if not version.startswith(REVISION_ID_PREFIX):
        raise InvalidRevisionId(revid, "")

    scheme = version[len(REVISION_ID_PREFIX):]

    return (uuid, unescape_svn_path(branch_path), int(srevnum), scheme)


def generate_svn_revision_id(uuid, revnum, path, scheme):
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
        create table if not exists revmap (revid text, path text, min_revnum integer, max_revnum integer, scheme text);
        create index if not exists revid on revmap (revid);
        create unique index if not exists revid_path_scheme on revmap (revid, path, scheme);
        create unique index if not exists lookup_branch_revnum on revmap (max_revnum, min_revnum, path, scheme);
        create table if not exists revno_cache (revid text unique, dist_to_origin integer);
        create index if not exists revid on revno_cache (revid);
        """)
        self.cachedb.commit()
    
    def lookup_revid(self, revid):
        ret = self.cachedb.execute(
            "select path, min_revnum, max_revnum, scheme from revmap where revid='%s'" % revid).fetchone()
        if ret is None:
            raise NoSuchRevision(self, revid)
        return (str(ret[0]), ret[1], ret[2], ret[3])

    def lookup_branch_revnum(self, revnum, path, scheme):
        """Lookup a revision by revision number, branch path and branching scheme.

        :param revnum: Subversion revision number.
        :param path: Subversion branch path.
        :param scheme: Branching scheme name
        """
        assert isinstance(revnum, int)
        assert isinstance(path, basestring)
        assert isinstance(scheme, basestring)
        revid = self.cachedb.execute(
                "select revid from revmap where max_revnum = min_revnum and min_revnum='%s' and path='%s' and scheme='%s'" % (revnum, path, scheme)).fetchone()
        if revid is not None:
            return str(revid[0])
        return None

    def insert_revid(self, revid, branch, min_revnum, max_revnum, scheme, 
                     dist_to_origin=None):
        assert revid is not None and revid != ""
        assert isinstance(scheme, basestring)
        cursor = self.cachedb.execute(
            "update revmap set min_revnum = MAX(min_revnum,?), max_revnum = MIN(max_revnum, ?) WHERE revid=? AND path=? AND scheme=?",
            (min_revnum, max_revnum, revid, branch, scheme))
        if cursor.rowcount == 0:
            self.cachedb.execute(
                "insert into revmap (revid,path,min_revnum,max_revnum,scheme) VALUES (?,?,?,?,?)",
                (revid, branch, min_revnum, max_revnum, scheme))
        if dist_to_origin is not None:
            self.cachedb.execute(
                "replace into revno_cache (revid,dist_to_origin) VALUES (?,?)", 
                (revid, dist_to_origin))

    def lookup_dist_to_origin(self, revid):
        revno = self.cachedb.execute(
                "select dist_to_origin from revno_cache where revid='%s'" % revid).fetchone()
        if revno is not None and revno[0] is not None:
            return int(revno[0])
        return None

    def insert_revision_history(self, revhistory):
        i = 1
        for revid in revhistory:
            self.cachedb.execute(
                "replace into revno_cache (revid,dist_to_origin) VALUES (?,?)",
                (revid, i))
            i += 1
        self.cachedb.commit()


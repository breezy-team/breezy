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

"""Revision id generation and caching."""

from bzrlib.errors import (InvalidRevisionId, NoSuchRevision)

from cache import CacheTable

class RevidMap(CacheTable):
    """Revision id mapping store. 

    Stores mapping from revid -> (path, revnum, scheme)
    """
    def _create_table(self):
        self.cachedb.executescript("""
        create table if not exists revmap (revid text, path text, min_revnum integer, max_revnum integer, scheme text);
        create index if not exists revid on revmap (revid);
        create unique index if not exists revid_path_scheme on revmap (revid, path, scheme);
        drop index if exists lookup_branch_revnum;
        create index if not exists lookup_branch_revnum_non_unique on revmap (max_revnum, min_revnum, path, scheme);
        create table if not exists revno_cache (revid text unique, dist_to_origin integer);
        create index if not exists revid on revno_cache (revid);
        create table if not exists revids_seen (scheme text, max_revnum int);
        create unique index if not exists scheme on revids_seen (scheme);
        """)

    def set_last_revnum_checked(self, scheme, revnum):
        """Remember the latest revision number that has been checked
        for a particular scheme.

        :param scheme: Branching scheme name.
        :param revnum: Revision number.
        """
        self.cachedb.execute("replace into revids_seen (scheme, max_revnum) VALUES (?, ?)", (scheme, revnum))

    def last_revnum_checked(self, scheme):
        """Retrieve the latest revision number that has been checked 
        for revision ids for a particular branching scheme.

        :param scheme: Branching scheme name.
        :return: Last revision number checked or 0.
        """
        ret = self.cachedb.execute(
            "select max_revnum from revids_seen where scheme = ?", (scheme,)).fetchone()
        if ret is None:
            return 0
        return int(ret[0])
    
    def lookup_revid(self, revid):
        """Lookup the details for a particular revision id.

        :param revid: Revision id.
        :return: Tuple with path inside repository, minimum revision number, maximum revision number and 
            branching scheme.
        """
        assert isinstance(revid, str)
        ret = self.cachedb.execute(
            "select path, min_revnum, max_revnum, scheme from revmap where revid='%s'" % revid).fetchone()
        if ret is None:
            raise NoSuchRevision(self, revid)
        return (ret[0].encode("utf-8"), int(ret[1]), int(ret[2]), ret[3].encode("utf-8"))

    def lookup_branch_revnum(self, revnum, path, scheme):
        """Lookup a revision by revision number, branch path and branching scheme.

        :param revnum: Subversion revision number.
        :param path: Subversion branch path.
        :param scheme: Branching scheme name
        """
        assert isinstance(revnum, int)
        assert isinstance(path, str)
        assert isinstance(scheme, str)
        revid = self.cachedb.execute(
                "select revid from revmap where max_revnum = '%s' and min_revnum='%s' and path='%s' and scheme='%s'" % (revnum, revnum, path, scheme)).fetchone()
        if revid is not None:
            return str(revid[0])
        return None

    def insert_revid(self, revid, branch, min_revnum, max_revnum, scheme, 
                     dist_to_origin=None):
        """Insert a revision id into the revision id cache.

        :param revid: Revision id for which to insert metadata.
        :param branch: Branch path at which the revision was seen
        :param min_revnum: Minimum Subversion revision number in which the 
                           revid was found
        :param max_revnum: Maximum Subversion revision number in which the 
                           revid was found
        :param scheme: Name of the branching scheme with which the revision 
                       was found
        :param dist_to_origin: Optional distance to the origin of this branch.
        """
        assert revid is not None and revid != ""
        assert isinstance(scheme, str)
        assert isinstance(branch, str)
        assert isinstance(min_revnum, int) and isinstance(max_revnum, int)
        assert dist_to_origin is None or isinstance(dist_to_origin, int)
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
        """Lookup the number of lhs revisions between the revid and NULL_REVISIOn.
        :param revid: Revision id of the revision for which to do the lookup.
        :return: None if the distance is not known, or an integer.
        """
        assert isinstance(revid, str)
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


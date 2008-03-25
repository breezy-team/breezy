# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Revision id generation and caching."""

from bzrlib import debug
from bzrlib.errors import (InvalidRevisionId, NoSuchRevision)
from bzrlib.trace import mutter

from cache import CacheTable

class RevidMap(CacheTable):
    """Revision id mapping store. 

    Stores mapping from revid -> (path, revnum, scheme)
    """
    def mutter(self, text):
        if "cache" in debug.debug_flags:
            mutter(text)

    def _create_table(self):
        self.cachedb.executescript("""
        create table if not exists revmap (revid text, path text, min_revnum integer, max_revnum integer, scheme text);
        create index if not exists revid on revmap (revid);
        create unique index if not exists revid_path_scheme on revmap (revid, path, scheme);
        drop index if exists lookup_branch_revnum;
        create index if not exists lookup_branch_revnum_non_unique on revmap (max_revnum, min_revnum, path, scheme);
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
        self.mutter("last revnum checked %r" % scheme)
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
        self.mutter("lookup revid %r" % revid)
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
        self.mutter("lookup branch,revnum %r:%r" % (path, revnum))
        assert isinstance(revnum, int)
        assert isinstance(path, str)
        assert isinstance(scheme, str)
        revid = self.cachedb.execute(
                "select revid from revmap where max_revnum = '%s' and min_revnum='%s' and path='%s' and scheme='%s'" % (revnum, revnum, path, scheme)).fetchone()
        if revid is not None:
            return str(revid[0])
        return None

    def insert_revid(self, revid, branch, min_revnum, max_revnum, scheme):
        """Insert a revision id into the revision id cache.

        :param revid: Revision id for which to insert metadata.
        :param branch: Branch path at which the revision was seen
        :param min_revnum: Minimum Subversion revision number in which the 
                           revid was found
        :param max_revnum: Maximum Subversion revision number in which the 
                           revid was found
        :param scheme: Name of the branching scheme with which the revision 
                       was found
        """
        assert revid is not None and revid != ""
        assert isinstance(scheme, str)
        assert isinstance(branch, str)
        assert isinstance(min_revnum, int) and isinstance(max_revnum, int)
        cursor = self.cachedb.execute(
            "update revmap set min_revnum = MAX(min_revnum,?), max_revnum = MIN(max_revnum, ?) WHERE revid=? AND path=? AND scheme=?",
            (min_revnum, max_revnum, revid, branch, scheme))
        if cursor.rowcount == 0:
            self.cachedb.execute(
                "insert into revmap (revid,path,min_revnum,max_revnum,scheme) VALUES (?,?,?,?,?)",
                (revid, branch, min_revnum, max_revnum, scheme))

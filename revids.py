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

from bzrlib.plugins.svn.cache import CacheTable
from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.errors import InvalidPropertyValue, ERR_FS_NO_SUCH_REVISION, ERR_FS_NOT_DIRECTORY
from bzrlib.plugins.svn.mapping import (parse_revision_id, BzrSvnMapping, 
                     SVN_PROP_BZR_REVISION_ID, parse_revid_property)
from bzrlib.plugins.svn.mapping3 import BzrSvnMappingv3FileProps
from bzrlib.plugins.svn.mapping3.scheme import BranchingScheme

class RevidMap(object):
    def __init__(self, repos):
        self.repos = repos

    def get_revision_id(self, revnum, path, mapping, revprops, fileprops):
        # See if there is a bzr:revision-id revprop set
        try:
            (bzr_revno, revid) = mapping.get_revision_id(path, revprops, fileprops)
        except SubversionException, (_, num):
            if num == ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(path, revnum)
            raise

        # Or generate it
        if revid is None:
            return mapping.generate_revision_id(self.repos.uuid, revnum, path)

        return revid

    def get_branch_revnum(self, revid, layout):
        """Find the (branch, revnum) tuple for a revision id."""
        # Try a simple parse
        try:
            (uuid, branch_path, revnum, mapping) = parse_revision_id(revid)
            assert isinstance(branch_path, str)
            assert isinstance(mapping, BzrSvnMapping)
            if uuid == self.repos.uuid:
                return (branch_path, revnum, mapping)
            # If the UUID doesn't match, this may still be a valid revision
            # id; a revision from another SVN repository may be pushed into 
            # this one.
        except InvalidRevisionId:
            pass

        for entry_revid, branch, revno, mapping in self.discover_revids(layout, 0, self.repos.get_latest_revnum()):
            if revid == entry_revid:
                return self.bisect_revid_revnum(revid, branch, revno)
        raise NoSuchRevision(self, revid)

    def discover_revids(self, layout, from_revnum, to_revnum):
        for (branch, revno) in self.repos.find_fileprop_branches(layout, from_revnum, to_revnum):
            assert isinstance(branch, str)
            assert isinstance(revno, int)
            # Look at their bzr:revision-id-vX
            revids = set()
            try:
                props = self.repos.branchprop_list.get_properties(branch, revno)
                for propname, propvalue in props.items():
                    if not propname.startswith(SVN_PROP_BZR_REVISION_ID):
                        continue
                    scheme = propname[len(SVN_PROP_BZR_REVISION_ID):]
                    for line in propvalue.splitlines():
                        try:
                            revids.add((parse_revid_property(line), scheme))
                        except InvalidPropertyValue, ie:
                            mutter(str(ie))
            except SubversionException, (_, ERR_FS_NOT_DIRECTORY):
                    continue

            # If there are any new entries that are not yet in the cache, 
            # add them
            for ((entry_revno, entry_revid), scheme) in revids:
                yield (entry_revid, branch, revno, BzrSvnMappingv3FileProps(BranchingScheme.find_scheme(scheme)))

    def bisect_revid_revnum(self, revid, branch_path, max_revnum):
        # Find the branch property between min_revnum and max_revnum that 
        # added revid
        for revmeta in self.repos.iter_reverse_branch_changes(branch_path, max_revnum):
            for propname, propvalue in revmeta.fileprops.items():
                if not propname.startswith(SVN_PROP_BZR_REVISION_ID):
                    continue
                try:
                    (entry_revno, entry_revid) = parse_revid_property(
                        propvalue.splitlines()[-1])
                except InvalidPropertyValue:
                    # Don't warn about encountering an invalid property, 
                    # that will already have happened earlier
                    continue
                if entry_revid == revid:
                    scheme = BranchingScheme.find_scheme(propname[len(SVN_PROP_BZR_REVISION_ID):])
                    assert (scheme.is_tag(revmeta.branch_path) or 
                            scheme.is_branch(revmeta.branch_path))
                    return (revmeta.branch_path, revmeta.revnum, BzrSvnMappingv3FileProps(scheme))

        raise AssertionError("Revision id %s was added incorrectly" % revid)


class CachingRevidMap(object):
    def __init__(self, actual, cachedb=None):
        self.cache = RevisionIdMapCache(cachedb)
        self.actual = actual

    def get_revision_id(self, revnum, path, mapping, changed_fileprops, revprops):
        # Look in the cache to see if it already has a revision id
        revid = self.cache.lookup_branch_revnum(revnum, path, str(mapping.scheme))
        if revid is not None:
            return revid

        revid = self.actual.get_revision_id(revnum, path, mapping, changed_fileprops, revprops)

        self.cache.insert_revid(revid, path, revnum, revnum, str(mapping.scheme))
        self.cache.commit_conditionally()

        return revid

    def get_branch_revnum(self, revid, layout):
        # Try a simple parse
        try:
            (uuid, branch_path, revnum, mapping) = parse_revision_id(revid)
            assert isinstance(branch_path, str)
            assert isinstance(mapping, BzrSvnMapping)
            if uuid == self.actual.repos.uuid:
                return (branch_path, revnum, mapping)
            # If the UUID doesn't match, this may still be a valid revision
            # id; a revision from another SVN repository may be pushed into 
            # this one.
        except InvalidRevisionId:
            pass

        def get_scheme(name):
            from mapping3.scheme import BranchingScheme
            assert isinstance(name, str)
            return BranchingScheme.find_scheme(name)

        # Check the record out of the cache, if it exists
        try:
            (branch_path, min_revnum, max_revnum, \
                    scheme) = self.cache.lookup_revid(revid)
            assert isinstance(branch_path, str)
            assert isinstance(scheme, str)
            # Entry already complete?
            if min_revnum == max_revnum:
                return (branch_path, min_revnum, BzrSvnMappingv3FileProps(get_scheme(scheme)))
        except NoSuchRevision, e:
            last_revnum = self.actual.repos.get_latest_revnum()
            if (last_revnum <= self.cache.last_revnum_checked(str(layout))):
                # All revision ids in this repository for the current 
                # layout have already been discovered. No need to 
                # check again.
                raise e
            found = False
            revid_seen = set()
            for entry_revid, branch, revno, mapping in self.actual.discover_revids(layout, self.cache.last_revnum_checked(str(layout)), last_revnum):
                if entry_revid == revid:
                    found = True
                if entry_revid not in revid_seen:
                    self.cache.insert_revid(entry_revid, branch, 0, revno, str(mapping.scheme))
                    revid_seen.add(entry_revid)
                
            # We've added all the revision ids for this layout in the repository,
            # so no need to check again unless new revisions got added
            self.cache.set_last_revnum_checked(str(layout), last_revnum)
            if not found:
                raise e
            (branch_path, min_revnum, max_revnum, scheme) = self.cache.lookup_revid(revid)
            assert isinstance(branch_path, str)

        return self.actual.bisect_revid_revnum(revid, branch_path, max_revnum)


class RevisionIdMapCache(CacheTable):
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
        create table if not exists revids_seen (scheme text, max_revnum int);
        create unique index if not exists scheme on revids_seen (scheme);
        """)
        # Revisions ids are quite expensive
        self._commit_interval = 100

    def set_last_revnum_checked(self, layout, revnum):
        """Remember the latest revision number that has been checked
        for a particular scheme.

        :param layout: Repository layout.
        :param revnum: Revision number.
        """
        self.cachedb.execute("replace into revids_seen (scheme, max_revnum) VALUES (?, ?)", (layout, revnum))
        self.commit_conditionally()

    def last_revnum_checked(self, layout):
        """Retrieve the latest revision number that has been checked 
        for revision ids for a particular branching scheme.

        :param layout: Repository layout.
        :return: Last revision number checked or 0.
        """
        self.mutter("last revnum checked %r", layout)
        ret = self.cachedb.execute(
            "select max_revnum from revids_seen where scheme = ?", (layout,)).fetchone()
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
        self.mutter("lookup revid %r", revid)
        ret = self.cachedb.execute(
            "select path, min_revnum, max_revnum, scheme from revmap where revid=?", (revid,)).fetchone()
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
        row = self.cachedb.execute(
                "select revid from revmap where max_revnum = ? and min_revnum=? and path=? and scheme=?", (revnum, revnum, path, scheme)).fetchone()
        if row is not None:
            ret = str(row[0])
        else:
            ret = None
        self.mutter("lookup branch,revnum %r:%r -> %r", path, revnum, ret)
        return ret

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
        self.mutter("insert revid %r:%r-%r -> %r", branch, min_revnum, max_revnum, revid)
        cursor = self.cachedb.execute(
            "update revmap set min_revnum = MAX(min_revnum,?), max_revnum = MIN(max_revnum, ?) WHERE revid=? AND path=? AND scheme=?",
            (min_revnum, max_revnum, revid, branch, scheme))
        if cursor.rowcount == 0:
            self.cachedb.execute(
                "insert into revmap (revid,path,min_revnum,max_revnum,scheme) VALUES (?,?,?,?,?)",
                (revid, branch, min_revnum, max_revnum, scheme))

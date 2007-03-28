# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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

import bzrlib
from bzrlib.branch import BranchCheckResult
from bzrlib.config import config_dir, ensure_config_dir_exists
from bzrlib.errors import (InvalidRevisionId, NoSuchRevision, 
                           NotBranchError, UninitializableFormat)
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import LockableFiles, TransportLock
import bzrlib.osutils as osutils
from bzrlib.repository import Repository, RepositoryFormat
from bzrlib.revisiontree import RevisionTree
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.transport import Transport
from bzrlib.trace import mutter

from svn.core import SubversionException, Pool
import svn.core

import os
try:
    import sqlite3
except ImportError:
    from pysqlite2 import dbapi2 as sqlite3

from branchprops import BranchPropertyList
import errors
import logwalker
from tree import SvnRevisionTree

MAPPING_VERSION = 3
REVISION_ID_PREFIX = "svn-v%d-" % MAPPING_VERSION
SVN_PROP_BZR_PREFIX = 'bzr:'
SVN_PROP_BZR_MERGE = 'bzr:merge'
SVN_PROP_BZR_FILEIDS = 'bzr:file-ids'
SVN_PROP_SVK_MERGE = 'svk:merge'
SVN_PROP_BZR_FILEIDS = 'bzr:file-ids'
SVN_PROP_BZR_REVPROP_PREFIX = 'bzr:revprop:'
SVN_REVPROP_BZR_SIGNATURE = 'bzr:gpg-signature'

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
    assert revnum > 0 or path == ""
    return "%s%s:%s:%s:%d" % (REVISION_ID_PREFIX, scheme, uuid, \
                   escape_svn_path(path.strip("/")), revnum)


def svk_feature_to_revision_id(feature):
    """Create a revision id from a svk feature identifier.

    :param feature: The feature identifier as string.
    :return: Matching revision id.
    """
    (uuid, branch, revnum) = feature.split(":")
    return generate_svn_revision_id(uuid, int(revnum), branch.strip("/"))


def revision_id_to_svk_feature(revid):
    """Create a SVK feature identifier from a revision id.

    :param revid: Revision id to convert.
    :return: Matching SVK feature identifier.
    """
    (uuid, branch, revnum) = parse_svn_revision_id(revid)
    return "%s:/%s:%d" % (uuid, branch, revnum)


def create_cache_dir():
    ensure_config_dir_exists()
    cache_dir = os.path.join(config_dir(), 'svn-cache')

    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)

        open(os.path.join(cache_dir, "README"), 'w').write(
"""This directory contains information cached by the bzr-svn plugin.

It is used for performance reasons only and can be removed 
without losing data.

See http://bazaar-vcs.org/BzrSvn for details.
""")
    return cache_dir


class SvnRepositoryFormat(RepositoryFormat):
    rich_root_data = False

    def __init__(self):
        super(SvnRepositoryFormat, self).__init__()
        from format import SvnFormat
        self._matchingbzrdir = SvnFormat()

    def get_format_description(self):
        return "Subversion Repository"

    def initialize(self, url, shared=False, _internal=False):
        """Svn repositories cannot be created."""
        raise UninitializableFormat(self)

cachedbs = {}

class SvnRepository(Repository):
    """
    Provides a simplified interface to a Subversion repository 
    by using the RA (remote access) API from subversion
    """
    def __init__(self, bzrdir, transport):
        from fileids import SimpleFileIdMap
        _revision_store = None

        assert isinstance(transport, Transport)

        control_files = LockableFiles(transport, '', TransportLock)
        Repository.__init__(self, SvnRepositoryFormat(), bzrdir, 
            control_files, None, None, None)

        self.transport = transport
        self.uuid = transport.get_uuid()
        self.base = transport.base
        self.dir_cache = {}
        self.scheme = bzrdir.scheme
        self.pool = Pool()

        assert self.base
        assert self.uuid

        cache_file = os.path.join(self.create_cache_dir(), 'cache-v1')
        if not cachedbs.has_key(cache_file):
            cachedbs[cache_file] = sqlite3.connect(cache_file)
        self.cachedb = cachedbs[cache_file]

        self._latest_revnum = transport.get_latest_revnum()
        self._log = logwalker.LogWalker(transport=transport, 
                                        cache_db=self.cachedb, 
                                        last_revnum=self._latest_revnum)

        self.branchprop_list = BranchPropertyList(self._log, self.cachedb)
        self.fileid_map = SimpleFileIdMap(self, self.cachedb)

    def set_branching_scheme(self, scheme):
        self.scheme = scheme

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, 
                           self.base)

    def create_cache_dir(self):
        cache_dir = create_cache_dir()
        dir = os.path.join(cache_dir, self.uuid)
        if not os.path.exists(dir):
            os.mkdir(dir)
        return dir

    def _check(self, revision_ids):
        return BranchCheckResult(self)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def get_fileid_map(self, revnum, path):
        return self.fileid_map.get_map(self.uuid, revnum, path,
                                       self.revision_fileid_renames)

    def transform_fileid_map(self, uuid, revnum, branch, changes, renames):
        return self.fileid_map.apply_changes(uuid, revnum, branch, changes, 
                                             renames)

    def all_revision_ids(self):
        for (bp, rev) in self.follow_history(self.transport.get_latest_revnum()):
            yield self.generate_revision_id(rev, bp)

    def get_inventory_weave(self):
        raise NotImplementedError(self.get_inventory_weave)

    def set_make_working_trees(self, new_value):
        """See Repository.set_make_working_trees()."""
        pass # FIXME: ignored, nowhere to store it... 

    def make_working_trees(self):
        return False

    def get_ancestry(self, revision_id):
        """See Repository.get_ancestry().
        
        Note: only the first bit is topologically ordered!
        """
        if revision_id is None: 
            return [None]

        (path, revnum) = self.parse_revision_id(revision_id)

        ancestry = []

        for l in self.branchprop_list.get_property(path, revnum, 
                                    SVN_PROP_BZR_MERGE, "").splitlines():
            ancestry.extend(l.split("\n"))

        if revnum > 0:
            for (branch, rev) in self.follow_branch(path, revnum - 1):
                ancestry.append(self.generate_revision_id(rev, branch))

        ancestry.append(None)

        ancestry.reverse()

        return ancestry

    def has_revision(self, revision_id):
        if revision_id is None:
            return True

        try:
            (path, revnum) = self.parse_revision_id(revision_id)
        except NoSuchRevision:
            return False

        try:
            return (svn.core.svn_node_none != self.transport.check_path(path.encode('utf8'), revnum))
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                return False
            raise

    def revision_trees(self, revids):
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        if revision_id is None:
            revision_id = NULL_REVISION

        if revision_id == NULL_REVISION:
            inventory = Inventory(root_id=None)
            inventory.revision_id = revision_id
            return RevisionTree(self, inventory, revision_id)

        return SvnRevisionTree(self, revision_id)

    def revision_fileid_renames(self, revid):
        (path, revnum) = self.parse_revision_id(revid)
        items = self.branchprop_list.get_property_diff(path, revnum, 
                                  SVN_PROP_BZR_FILEIDS).splitlines()
        return dict(map(lambda x: x.split("\t"), items))

    def _mainline_revision_parent(self, path, revnum):
        assert isinstance(path, basestring)
        assert isinstance(revnum, int)
        for (branch, rev) in self.follow_branch(path, revnum):
            if rev < revnum:
                return self.generate_revision_id(rev, branch)
        return None

    def revision_parents(self, revision_id, merged_data=None):
        parent_ids = []
        (branch, revnum) = self.parse_revision_id(revision_id)
        mainline_parent = self._mainline_revision_parent(branch, revnum)
        if mainline_parent is not None:
            parent_ids.append(mainline_parent)
            (parent_path, parent_revnum) = self.parse_revision_id(mainline_parent)
        else:
            parent_path = None

        # if the branch didn't change, bzr:merge can't have changed
        if not self._log.touches_path(branch, revnum):
            return parent_ids
       
        if merged_data is None:
            new_merge = self.branchprop_list.get_property(branch, revnum, 
                                           SVN_PROP_BZR_MERGE, "").splitlines()

            if len(new_merge) == 0 or parent_path is None:
                old_merge = ""
            else:
                old_merge = self.branchprop_list.get_property(parent_path, parent_revnum, 
                        SVN_PROP_BZR_MERGE, "").splitlines()

            assert (len(old_merge) == len(new_merge) or 
                    len(old_merge) + 1 == len(new_merge))

            if len(old_merge) < len(new_merge):
                merged_data = new_merge[-1]
            else:
                merged_data = ""

        if ' ' in merged_data:
            mutter('invalid revision id %r in merged property, skipping' % merged_data)
            merged_data = ""

        if merged_data != "":
            parent_ids.extend(merged_data.split("\t"))

        return parent_ids

    def get_revision(self, revision_id):
        """See Repository.get_revision."""
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)

        (path, revnum) = self.parse_revision_id(revision_id)
        
        parent_ids = self.revision_parents(revision_id)

        # Commit SVN revision properties to a Revision object
        rev = Revision(revision_id=revision_id, parent_ids=parent_ids)

        svn_props = self.branchprop_list.get_properties(path, revnum)
        bzr_props = {}
        for name in svn_props:
            if not name.startswith(SVN_PROP_BZR_REVPROP_PREFIX):
                continue

            bzr_props[name[len(SVN_PROP_BZR_REVPROP_PREFIX):]] = svn_props[name]

        (rev.committer, rev.message, date) = self._log.get_revision_info(revnum)
        if rev.committer is None:
            rev.committer = ""

        if date is not None:
            rev.timestamp = 1.0 * svn.core.secs_from_timestr(date, None)
        else:
            rev.timestamp = 0.0 # FIXME: Obtain repository creation time
        rev.timezone = None
        rev.properties = bzr_props
        rev.inventory_sha1 = property(lambda: self.get_inventory_sha1(revision_id))

        return rev

    def get_revisions(self, revision_ids):
        # TODO: More efficient implementation?
        return map(self.get_revision, revision_ids)

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError(self.add_revision)

    def fileid_involved_between_revs(self, from_revid, to_revid):
        raise NotImplementedError(self.fileid_involved_by_set)

    def fileid_involved(self, last_revid=None):
        raise NotImplementedError(self.fileid_involved)

    def fileids_altered_by_revision_ids(self, revision_ids):
        raise NotImplementedError(self.fileids_altered_by_revision_ids)

    def fileid_involved_by_set(self, changes):
        raise NotImplementedError(self.fileid_involved_by_set)

    def generate_revision_id(self, revnum, path):
        """Generate a unambiguous revision id. 
        
        :param revnum: Subversion revision number.
        :param path: Branch path.

        :return: New revision id.
        """
        return generate_svn_revision_id(self.uuid, revnum, path)

    def parse_revision_id(self, revid):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :raises: NoSuchRevision
        :return: Tuple with branch path and revision number.
        """

        try:
            (uuid, branch_path, revnum) = parse_svn_revision_id(revid)
        except InvalidRevisionId:
            raise NoSuchRevision(self, revid)

        if uuid != self.uuid:
            raise NoSuchRevision(self, revid)

        return (branch_path, revnum)

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(
            self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        return osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(
            self.get_revision(revision_id))

    def follow_history(self, revnum):
        while revnum >= 0:
            yielded_paths = []
            paths = self._log.get_revision_paths(revnum)
            for p in paths:
                try:
                    bp = self.scheme.unprefix(p)[0]
                    if not bp in yielded_paths:
                        if not paths.has_key(bp) or paths[bp][0] != 'D':
                            yield (bp, revnum)
                        yielded_paths.append(bp)
                except NotBranchError:
                    pass
            revnum -= 1

    def follow_branch(self, branch_path, revnum):
        assert branch_path is not None
        assert isinstance(revnum, int) and revnum >= 0
        if not self.scheme.is_branch(branch_path) and \
           not self.scheme.is_tag(branch_path):
            raise errors.NotSvnBranchPath(branch_path, revnum)
        branch_path = branch_path.strip("/")

        while revnum >= 0:
            paths = self._log.get_revision_paths(revnum, branch_path)
            if paths == {}:
                revnum -= 1
                continue
            yield (branch_path, revnum)
            # FIXME: what if one of the parents of branch_path was moved?
            if (paths.has_key(branch_path) and 
                paths[branch_path][0] in ('R', 'A')):
                if paths[branch_path][1] is None:
                    return
                if not self.scheme.is_branch(paths[branch_path][1]) and \
                   not self.scheme.is_tag(paths[branch_path][1]):
                    # FIXME: if copyfrom_path is not a branch path, 
                    # should simulate a reverse "split" of a branch
                    # for now, just make it look like the branch ended here
                    return
                revnum = paths[branch_path][2]
                branch_path = paths[branch_path][1]
                continue
            revnum -= 1

    def follow_branch_history(self, branch_path, revnum):
        assert branch_path is not None
        if not self.scheme.is_branch(branch_path) and \
           not self.scheme.is_tag(branch_path):
            raise errors.NotSvnBranchPath(branch_path, revnum)

        for (bp, paths, revnum) in self._log.follow_path(branch_path, revnum):
            # FIXME: what if one of the parents of branch_path was moved?
            if (paths.has_key(bp) and 
                paths[bp][1] is not None and 
                not self.scheme.is_branch(paths[bp][1]) and
                not self.scheme.is_tag(paths[bp][1])):
                # FIXME: if copyfrom_path is not a branch path, 
                # should simulate a reverse "split" of a branch
                # for now, just make it look like the branch ended here
                for c in self._log.find_children(paths[bp][1], paths[bp][2]):
                    path = c.replace(paths[bp][1], bp+"/", 1).replace("//", "/")
                    paths[path] = ('A', None, -1)
                paths[bp] = ('A', None, -1)

                yield (bp, paths, revnum)
                return
                     
            yield (bp, paths, revnum)

    def has_signature_for_revision_id(self, revision_id):
        # TODO: Retrieve from SVN_PROP_BZR_SIGNATURE 
        return False # SVN doesn't store GPG signatures. Perhaps 
                     # store in SVN revision property?

    def get_signature_text(self, revision_id):
        # TODO: Retrieve from SVN_PROP_BZR_SIGNATURE 
        # SVN doesn't store GPG signatures
        raise NoSuchRevision(self, revision_id)

    def _full_revision_graph(self):
        graph = {}
        for (branch, revnum) in self.follow_history(self._latest_revnum):
            mutter('%r, %r' % (branch, revnum))
            revid = self.generate_revision_id(revnum, branch)
            graph[revid] = self.revision_parents(revid)
        return graph

    def get_revision_graph(self, revision_id=None):
        if revision_id == NULL_REVISION:
            return {}

        if revision_id is None:
            return self._full_revision_graph()

        (path, revnum) = self.parse_revision_id(revision_id)

        _previous = revision_id
        self._ancestry = {}
        
        if revnum > 0:
            for (branch, rev) in self.follow_branch(path, revnum - 1):
                revid = self.generate_revision_id(rev, branch)
                self._ancestry[_previous] = [revid]
                _previous = revid

        self._ancestry[_previous] = []

        return self._ancestry

    def find_branches(self, revnum=None, pb=None):
        """Find all branches that were changed in the specified revision number.

        :param revnum: Revision to search for branches.
        """
        if revnum is None:
            revnum = self.transport.get_latest_revnum()

        created_branches = {}

        for i in range(revnum+1):
            if pb is not None:
                pb.update("finding branches", i, revnum+1)
            paths = self._log.get_revision_paths(i)
            names = paths.keys()
            names.sort()
            for p in names:
                if self.scheme.is_branch(p) or self.scheme.is_tag(p):
                    if paths[p][0] in ('R', 'D'):
                        del created_branches[p]
                        yield (p, i, False)

                    if paths[p][0] in ('A', 'R'): 
                        created_branches[p] = i
                elif self.scheme.is_branch_parent(p) or self.scheme.is_tag_parent(p):
                    if paths[p][0] in ('R', 'D'):
                        k = created_branches.keys()
                        for c in k:
                            if c.startswith(p+"/"):
                                del created_branches[c] 
                                yield (c, i, False)
                    if paths[p][0] in ('A', 'R'):
                        parents = [p]
                        while parents:
                            p = parents.pop()
                            for c in self.transport.get_dir(p, i)[0].keys():
                                n = p+"/"+c
                                if self.scheme.is_branch(n) or self.scheme.is_tag(n):
                                    created_branches[n] = i
                                elif self.scheme.is_branch_parent(n) or self.scheme.is_tag_parent(n):
                                    parents.append(n)

        for p in created_branches:
            j = self._log.find_latest_change(p, revnum, recurse=True)
            if j is None:
                j = created_branches[p]
            yield (p, j, True)

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return True

    def get_physical_lock_status(self):
        return False

    def get_commit_builder(self, branch, parents, config, timestamp=None, 
                           timezone=None, committer=None, revprops=None, 
                           revision_id=None):
        if timestamp != None:
            raise NotImplementedError(self.get_commit_builder, 
                "timestamp can not be user-specified for Subversion repositories")

        if timezone != None:
            raise NotImplementedError(self.get_commit_builder, 
                "timezone can not be user-specified for Subversion repositories")

        if committer != None:
            raise NotImplementedError(self.get_commit_builder, 
                "committer can not be user-specified for Subversion repositories")

        if revision_id != None:
            raise NotImplementedError(self.get_commit_builder, 
                "revision_id can not be user-specified for Subversion repositories")

        from commit import SvnCommitBuilder
        return SvnCommitBuilder(self, branch, parents, config, revprops)



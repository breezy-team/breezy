# Copyright (C) 2006-2008 Jelmer Vernooij <jelmer@samba.org>

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
"""Subversion repository access."""

import bzrlib
from bzrlib import osutils, ui, urlutils
from bzrlib.branch import Branch, BranchCheckResult
from bzrlib.errors import (InvalidRevisionId, NoSuchRevision, NotBranchError, 
                           UninitializableFormat, UnrelatedBranches)
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.repository import Repository, RepositoryFormat
from bzrlib.revisiontree import RevisionTree
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.transport import Transport, get_transport
from bzrlib.trace import info, mutter

from svn.core import SubversionException, Pool
import svn.core

import os

from branchprops import BranchPropertyList
from cache import create_cache_dir, sqlite3
from config import SvnRepositoryConfig
import errors
import logwalker
from mapping import (SVN_PROP_BZR_REVISION_ID, 
                     SVN_PROP_BZR_BRANCHING_SCHEME, BzrSvnMappingv3FileProps,
                     parse_revision_metadata, parse_revid_property, 
                     parse_merge_property, BzrSvnMapping,
                     get_default_mapping, parse_revision_id)
from revids import RevidMap
from scheme import (BranchingScheme, ListBranchingScheme, 
                    parse_list_scheme_text, guess_scheme_from_history)
from svk import (SVN_PROP_SVK_MERGE, svk_features_merged_since, 
                 parse_svk_feature)
from tree import SvnRevisionTree
import urllib

class lazy_dict:
    def __init__(self, create_fn):
        self.create_fn = create_fn
        self.dict = None

    def _ensure_init(self):
        if self.dict is None:
            self.dict = self.create_fn()

    def __len__(self):
        self._ensure_init()
        return len(self.dict)

    def __getitem__(self, key):
        self._ensure_init()
        return self.dict[key]

    def __setitem__(self, key, value):
        self._ensure_init()
        self.dict[key] = value

    def get(self, key, default=None):
        self._ensure_init()
        return self.dict.get(key, default)

    def has_key(self, key):
        self._ensure_init()
        return self.dict.has_key(key)


def svk_feature_to_revision_id(feature, mapping):
    """Convert a SVK feature to a revision id for this repository.

    :param feature: SVK feature.
    :return: revision id.
    """
    try:
        (uuid, bp, revnum) = parse_svk_feature(feature)
    except errors.InvalidPropertyValue:
        return None
    if not mapping.is_branch(bp) and not mapping.is_tag(bp):
        return None
    return mapping.generate_revision_id(uuid, revnum, bp)


class SvnRepositoryFormat(RepositoryFormat):
    """Repository format for Subversion repositories (accessed using svn_ra).
    """
    rich_root_data = True

    def __get_matchingbzrdir(self):
        from remote import SvnRemoteFormat
        return SvnRemoteFormat()

    _matchingbzrdir = property(__get_matchingbzrdir)

    def __init__(self):
        super(SvnRepositoryFormat, self).__init__()

    def get_format_description(self):
        return "Subversion Repository"

    def initialize(self, url, shared=False, _internal=False):
        """Svn repositories cannot be created (yet)."""
        raise UninitializableFormat(self)

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data

CACHE_DB_VERSION = 3

cachedbs = {}

class SvnRepository(Repository):
    """
    Provides a simplified interface to a Subversion repository 
    by using the RA (remote access) API from subversion
    """
    def __init__(self, bzrdir, transport, branch_path=None):
        from bzrlib.plugins.svn import lazy_register_optimizers
        lazy_register_optimizers()
        from fileids import SimpleFileIdMap
        _revision_store = None

        assert isinstance(transport, Transport)

        control_files = LockableFiles(transport, '', TransportLock)
        Repository.__init__(self, SvnRepositoryFormat(), bzrdir, 
            control_files, None, None, None)

        self.transport = transport
        self.uuid = transport.get_uuid()
        assert self.uuid is not None
        self.base = transport.base
        assert self.base is not None
        self._serializer = None
        self.dir_cache = {}
        self.pool = Pool()
        self.get_config().add_location(self.base)
        cache_dir = self.create_cache_dir()
        cachedir_transport = get_transport(cache_dir)
        cache_file = os.path.join(cache_dir, 'cache-v%d' % CACHE_DB_VERSION)
        if not cachedbs.has_key(cache_file):
            cachedbs[cache_file] = sqlite3.connect(cache_file)
        self.cachedb = cachedbs[cache_file]

        self._log = logwalker.LogWalker(transport=transport, 
                                        cache_db=self.cachedb)

        # TODO: Only use branchprop_list and fileid_map when 
        # fileprops-based mappings are being used
        self.branchprop_list = BranchPropertyList(self._log, self.cachedb)
        self.fileid_map = SimpleFileIdMap(self, cachedir_transport)
        self.revmap = RevidMap(self.cachedb)
        self._scheme = None
        self._hinted_branch_path = branch_path

    def lhs_missing_revisions(self, revhistory, stop_revision):
        missing = []
        slice = revhistory[:revhistory.index(stop_revision)+1]
        for revid in reversed(slice):
            if self.has_revision(revid):
                missing.reverse()
                return missing
            missing.append(revid)
        raise UnrelatedBranches()
    
    def get_transaction(self):
        raise NotImplementedError(self.get_transaction)

    def get_stored_scheme(self):
        """Retrieve the stored branching scheme, either in the repository 
        or in the configuration file.
        """
        scheme = self.get_config().get_branching_scheme()
        if scheme is not None:
            return (scheme, self.get_config().branching_scheme_is_mandatory())

        last_revnum = self.transport.get_latest_revnum()
        scheme = self._get_property_scheme(last_revnum)
        if scheme is not None:
            return (scheme, True)

        return (None, False)

    def get_mapping(self):
        return get_default_mapping()(self.get_scheme())

    def get_scheme(self):
        """Determine the branching scheme to use for this repository.

        :return: Branching scheme.
        """
        # First, try to use the branching scheme we already know
        if self._scheme is not None:
            return self._scheme

        (scheme, mandatory) = self.get_stored_scheme()
        if mandatory:
            self._scheme = scheme
            return scheme

        if scheme is not None:
            if (self._hinted_branch_path is None or 
                scheme.is_branch(self._hinted_branch_path)):
                self._scheme = scheme
                return scheme

        last_revnum = self.transport.get_latest_revnum()
        self.set_branching_scheme(
            self._guess_scheme(last_revnum, self._hinted_branch_path),
            store=(last_revnum > 20),
            mandatory=False)

        return self._scheme

    def _get_property_scheme(self, revnum=None):
        if revnum is None:
            revnum = self.transport.get_latest_revnum()
        text = self.branchprop_list.get_property("", 
            revnum, SVN_PROP_BZR_BRANCHING_SCHEME, None)
        if text is None:
            return None
        return ListBranchingScheme(parse_list_scheme_text(text))

    def set_property_scheme(self, scheme):
        def done(revmetadata, pool):
            pass
        editor = self.transport.get_commit_editor(
                {svn.core.SVN_PROP_REVISION_LOG: "Updating branching scheme for Bazaar."},
                done, None, False)
        root = editor.open_root(-1)
        editor.change_dir_prop(root, SVN_PROP_BZR_BRANCHING_SCHEME, 
                "".join(map(lambda x: x+"\n", scheme.branch_list)).encode("utf-8"))
        editor.close_directory(root)
        editor.close()

    def _guess_scheme(self, last_revnum, branch_path=None):
        scheme = guess_scheme_from_history(
            self._log.follow_path("", last_revnum), last_revnum, 
            branch_path)
        mutter("Guessed branching scheme: %r" % scheme)
        return scheme

    def set_branching_scheme(self, scheme, store=True, mandatory=False):
        self._scheme = scheme
        if store:
            self.get_config().set_branching_scheme(str(scheme), 
                                                   mandatory=mandatory)

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
            info("Initialising Subversion metadata cache in %s" % dir)
            os.mkdir(dir)
        return dir

    def _check(self, revision_ids):
        return BranchCheckResult(self)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def get_fileid_map(self, revnum, path, mapping):
        return self.fileid_map.get_map(self.uuid, revnum, path, 
                                       self.revision_fileid_renames, mapping)

    def transform_fileid_map(self, uuid, revnum, branch, changes, renames, 
                             mapping):
        return self.fileid_map.apply_changes(uuid, revnum, branch, changes, 
                                             renames, mapping)

    def all_revision_ids(self, mapping=None):
        if mapping is None:
            mapping = self.get_mapping()
        for (bp, rev) in self.follow_history(
                self.transport.get_latest_revnum(), mapping):
            yield self.generate_revision_id(rev, bp, mapping)

    def get_inventory_weave(self):
        """See Repository.get_inventory_weave()."""
        raise NotImplementedError(self.get_inventory_weave)

    def set_make_working_trees(self, new_value):
        """See Repository.set_make_working_trees()."""
        pass # FIXME: ignored, nowhere to store it... 

    def make_working_trees(self):
        """See Repository.make_working_trees().

        Always returns False, as working trees are never created inside 
        Subversion repositories.
        """
        return False

    def get_ancestry(self, revision_id, topo_sorted=True):
        """See Repository.get_ancestry().
        
        Note: only the first bit is topologically ordered!
        """
        if revision_id is None: 
            return [None]

        (path, revnum, mapping) = self.lookup_revision_id(revision_id)

        ancestry = [revision_id]

        svn_revprops = lazy_dict(lambda: self.transport.revprop_list(revnum))
        svn_fileprops = lazy_dict(lambda: self.branchprop_list.get_properties(path, revnum))
        ancestry.extend(mapping.get_rhs_ancestors(path, svn_revprops, svn_fileprops))

        if revnum > 0:
            for (branch, rev) in self.follow_branch(path, revnum - 1, mapping):
                ancestry.append(
                    self.generate_revision_id(rev, branch, mapping))

        ancestry.append(None)
        ancestry.reverse()
        return ancestry

    def has_revision(self, revision_id):
        """See Repository.has_revision()."""
        if revision_id is None:
            return True

        try:
            (path, revnum, _) = self.lookup_revision_id(revision_id)
        except NoSuchRevision:
            return False

        try:
            return (svn.core.svn_node_dir == self.transport.check_path(path, revnum))
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                return False
            raise

    def revision_trees(self, revids):
        """See Repository.revision_trees()."""
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        """See Repository.revision_tree()."""
        if revision_id is None:
            revision_id = NULL_REVISION

        if revision_id == NULL_REVISION:
            inventory = Inventory(root_id=None)
            inventory.revision_id = revision_id
            return RevisionTree(self, inventory, revision_id)

        return SvnRevisionTree(self, revision_id)

    def revision_fileid_renames(self, revid):
        """Check which files were renamed in a particular revision.
        
        :param revid: Id of revision to look up.
        :return: dictionary with paths as keys, file ids as values
        """
        (path, revnum, mapping) = self.lookup_revision_id(revid)

        svn_revprops = lazy_dict(lambda: self.transport.revprop_list(revnum))
        svn_fileprops = lazy_dict(lambda: self.branchprop_list.get_changed_properties(path, revnum))

        return mapping.import_fileid_map(svn_revprops, svn_fileprops)

    def _mainline_revision_parent(self, path, revnum, mapping):
        """Find the mainline parent of the specified revision.

        :param path: Path of the revision in Subversion
        :param revnum: Subversion revision number
        :param mapping: Mapping.
        :return: Revision id of the left-hand-side parent or None if 
                  this is the first revision
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int)

        if not mapping.is_branch(path) and \
           not mapping.is_tag(path):
            raise NoSuchRevision(self, 
                    self.generate_revision_id(revnum, path, mapping))

        it = self.follow_branch(path, revnum, mapping)
        # the first tuple returned should match the one specified. 
        # if it's not, then the branch, revnum didn't change in the specified 
        # revision and so it is invalid
        if (path, revnum) != it.next():
            raise NoSuchRevision(self, 
                    self.generate_revision_id(revnum, path, mapping))
        try:
            (branch, rev) = it.next()
            return self.generate_revision_id(rev, branch, mapping)
        except StopIteration:
            # The specified revision was the first one in the branch
            return None

    def get_parents(self, revids):
        parents_list = []
        for revision_id in revids:
            if revision_id == NULL_REVISION:
                parents = []
            else:
                try:
                    parents = self.revision_parents(revision_id)
                except NoSuchRevision:
                    parents = None
                else:
                    if len(parents) == 0:
                        parents = [NULL_REVISION]
            parents_list.append(parents)
        return parents_list

    def _svk_merged_revisions(self, branch, revnum, mapping, 
                              fileprops):
        """Find out what SVK features were merged in a revision.

        """
        current = fileprops.get(SVN_PROP_SVK_MERGE, "")
        if current == "":
            return
        (prev_path, prev_revnum) = self._log.get_previous(branch, revnum)
        if prev_path is None and prev_revnum == -1:
            previous = ""
        else:
            previous = self.branchprop_list.get_property(prev_path.encode("utf-8"), 
                         prev_revnum, SVN_PROP_SVK_MERGE, "")
        for feature in svk_features_merged_since(current, previous):
            revid = svk_feature_to_revision_id(feature, mapping)
            if revid is not None:
                yield revid

    def revision_parents(self, revision_id, svn_fileprops=None):
        """See Repository.revision_parents()."""
        parent_ids = []
        (branch, revnum, mapping) = self.lookup_revision_id(revision_id)
        mainline_parent = self._mainline_revision_parent(branch, revnum, mapping)
        if mainline_parent is not None:
            parent_ids.append(mainline_parent)

        if svn_fileprops is None:
            svn_fileprops = lazy_dict(lambda: self.branchprop_list.get_changed_properties(branch, revnum))

        svn_revprops = lazy_dict(lambda: self.transport.revprop_list(revnum))

        extra_rhs_parents = mapping.get_rhs_parents(branch, svn_revprops, svn_fileprops)
        parent_ids.extend(extra_rhs_parents)

        if extra_rhs_parents == []:
            parent_ids.extend(self._svk_merged_revisions(branch, revnum, mapping, svn_fileprops))

        return parent_ids

    def get_revision(self, revision_id):
        """See Repository.get_revision."""
        if not revision_id or not isinstance(revision_id, str):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)

        (path, revnum, mapping) = self.lookup_revision_id(revision_id)
        
        parent_ids = self.revision_parents(revision_id)

        # Commit SVN revision properties to a Revision object
        class LazySvnRevision(Revision):
            inventory_sha1 = property(lambda rev: self.get_inventory_sha1(rev.revision_id))

        rev = LazySvnRevision(revision_id=revision_id, parent_ids=parent_ids)
        svn_revprops = lazy_dict(lambda: self.transport.revprop_list(revnum))
        svn_fileprops = lazy_dict(lambda: self.branchprop_list.get_changed_properties(path, revnum))

        mapping.import_revision(svn_revprops, svn_fileprops, rev)

        return rev

    def get_revisions(self, revision_ids):
        """See Repository.get_revisions()."""
        # TODO: More efficient implementation?
        return map(self.get_revision, revision_ids)

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError(self.add_revision)

    def generate_revision_id(self, revnum, path, mapping):
        """Generate an unambiguous revision id. 
        
        :param revnum: Subversion revision number.
        :param path: Branch path.
        :param mapping: Mapping to use.

        :return: New revision id.
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int)
        assert isinstance(mapping, BzrSvnMapping)

        # Look in the cache to see if it already has a revision id
        revid = self.revmap.lookup_branch_revnum(revnum, path, str(mapping.scheme))
        if revid is not None:
            return revid

        # See if there is a bzr:revision-id revprop set
        try:
            revprops = lazy_dict(lambda: self._log._get_transport().revprop_list(revnum))
            fileprops = lazy_dict(lambda: self.branchprop_list.get_changed_properties(path, revnum))
            (bzr_revno, revid) = mapping.get_revision_id(path, revprops, 
                                                         fileprops)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(path, revnum)
            raise

        # Or generate it
        if revid is None:
            revid = mapping.generate_revision_id(self.uuid, revnum, path)
        self.revmap.insert_revid(revid, path, revnum, revnum, 
                str(mapping.scheme), bzr_revno)
        return revid

    def lookup_revision_id(self, revid, scheme=None):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :param scheme: Optional branching scheme to use when searching for 
                       revisions
        :raises: NoSuchRevision
        :return: Tuple with branch path, revision number and mapping.
        """
        def get_scheme(name):
            assert isinstance(name, str)
            return BranchingScheme.find_scheme(name)

        # Try a simple parse
        try:
            # FIXME: Also try to parse with the other formats..
            (uuid, branch_path, revnum, mapping) = parse_revision_id(revid)
            assert isinstance(branch_path, str)
            assert isinstance(mapping, BzrSvnMapping)
            if uuid == self.uuid:
                return (branch_path, revnum, mapping)
            # If the UUID doesn't match, this may still be a valid revision
            # id; a revision from another SVN repository may be pushed into 
            # this one.
        except InvalidRevisionId:
            pass

        # Check the record out of the revmap, if it exists
        try:
            (branch_path, min_revnum, max_revnum, \
                    scheme) = self.revmap.lookup_revid(revid)
            assert isinstance(branch_path, str)
            assert isinstance(scheme, str)
            # Entry already complete?
            if min_revnum == max_revnum:
                return (branch_path, min_revnum, BzrSvnMappingv3FileProps(get_scheme(scheme)))
        except NoSuchRevision, e:
            # If there is no entry in the map, walk over all branches:
            if scheme is None:
                scheme = self.get_scheme()
            last_revnum = self.transport.get_latest_revnum()
            if (last_revnum <= self.revmap.last_revnum_checked(str(scheme))):
                # All revision ids in this repository for the current 
                # scheme have already been discovered. No need to 
                # check again.
                raise e
            found = False
            for (branch, revno, _) in self.find_branchpaths(scheme, 
                    self.revmap.last_revnum_checked(str(scheme)),
                    last_revnum):
                assert isinstance(branch, str)
                assert isinstance(revno, int)
                # Look at their bzr:revision-id-vX
                revids = []
                try:
                    for line in self.branchprop_list.get_property(branch, revno, 
                            SVN_PROP_BZR_REVISION_ID+str(scheme), "").splitlines():
                        try:
                            revids.append(parse_revid_property(line))
                        except errors.InvalidPropertyValue, ie:
                            mutter(str(ie))
                except SubversionException, (_, svn.core.SVN_ERR_FS_NOT_DIRECTORY):
                    continue

                # If there are any new entries that are not yet in the cache, 
                # add them
                for (entry_revno, entry_revid) in revids:
                    if entry_revid == revid:
                        found = True
                    self.revmap.insert_revid(entry_revid, branch, 0, revno, 
                            str(scheme), entry_revno)
                
            # We've added all the revision ids for this scheme in the repository,
            # so no need to check again unless new revisions got added
            self.revmap.set_last_revnum_checked(str(scheme), last_revnum)
            if not found:
                raise e
            (branch_path, min_revnum, max_revnum, scheme) = self.revmap.lookup_revid(revid)
            assert isinstance(branch_path, str)

        # Find the branch property between min_revnum and max_revnum that 
        # added revid
        for (bp, rev) in self.follow_branch(branch_path, max_revnum, 
                                            get_scheme(str(scheme))):
            try:
                (entry_revno, entry_revid) = parse_revid_property(
                 self.branchprop_list.get_property_diff(bp, rev, 
                     SVN_PROP_BZR_REVISION_ID+str(scheme)).strip("\n"))
            except errors.InvalidPropertyValue:
                # Don't warn about encountering an invalid property, 
                # that will already have happened earlier
                continue
            if entry_revid == revid:
                self.revmap.insert_revid(revid, bp, rev, rev, scheme, 
                                         entry_revno)
                return (bp, rev, BzrSvnMappingv3FileProps(get_scheme(scheme)))

        raise AssertionError("Revision id %s was added incorrectly" % revid)

    def get_inventory_xml(self, revision_id):
        """See Repository.get_inventory_xml()."""
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(
            self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        """Get the sha1 for the XML representation of an inventory.

        :param revision_id: Revision id of the inventory for which to return 
         the SHA1.
        :return: XML string
        """

        return osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        """Return the XML representation of a revision.

        :param revision_id: Revision for which to return the XML.
        :return: XML string
        """
        return bzrlib.xml5.serializer_v5.write_revision_to_string(
            self.get_revision(revision_id))

    def follow_history(self, revnum, mapping):
        """Yield all the branches found between the start of history 
        and a specified revision number.

        :param revnum: Revision number up to which to search.
        :return: iterator over branches in the range 0..revnum
        """
        assert mapping is not None

        while revnum >= 0:
            yielded_paths = []
            paths = self._log.get_revision_paths(revnum)
            for p in paths:
                try:
                    bp = mapping.scheme.unprefix(p)[0]
                    if not bp in yielded_paths:
                        if not paths.has_key(bp) or paths[bp][0] != 'D':
                            assert revnum > 0 or bp == ""
                            yield (bp, revnum)
                        yielded_paths.append(bp)
                except NotBranchError:
                    pass
            revnum -= 1

    def follow_branch(self, branch_path, revnum, mapping):
        """Follow the history of a branch. Will yield all the 
        left-hand side ancestors of a specified revision.
    
        :param branch_path: Subversion path to search.
        :param revnum: Revision number in Subversion to start.
        :param mapping: Mapping.
        :return: iterator over the ancestors
        """
        assert branch_path is not None
        assert isinstance(branch_path, str)
        assert isinstance(revnum, int) and revnum >= 0
        assert mapping.is_branch(branch_path) or mapping.is_tag(branch_path)
        branch_path = branch_path.strip("/")

        while revnum >= 0:
            assert revnum > 0 or branch_path == ""
            paths = self._log.get_revision_paths(revnum)

            yielded = False
            # If something underneath branch_path changed, there is a 
            # revision there, so yield it.
            for p in paths:
                assert isinstance(p, str)
                if (p == branch_path or 
                    p.startswith(branch_path+"/") or 
                    branch_path == ""):
                    yield (branch_path, revnum)
                    yielded = True
                    break
            
            # If there are no special cases, just go try the 
            # next revnum in history
            revnum -= 1

            # Make sure we get the right location for next time, if 
            # the branch itself was copied
            if (paths.has_key(branch_path) and 
                paths[branch_path][0] in ('R', 'A')):
                if not yielded:
                    yield (branch_path, revnum+1)
                if paths[branch_path][1] is None:
                    return
                if not mapping.is_branch(paths[branch_path][1]) and \
                   not mapping.is_tag(paths[branch_path][1]):
                    # FIXME: if copyfrom_path is not a branch path, 
                    # should simulate a reverse "split" of a branch
                    # for now, just make it look like the branch ended here
                    return
                revnum = paths[branch_path][2]
                branch_path = paths[branch_path][1].encode("utf-8")
                continue
            
            # Make sure we get the right location for the next time if 
            # one of the parents changed

            # Path names need to be sorted so the longer paths 
            # override the shorter ones
            for p in sorted(paths.keys(), reverse=True):
                if paths[p][0] == 'M':
                    continue
                if branch_path.startswith(p+"/"):
                    assert paths[p][0] in ('A', 'R'), "Parent wasn't added"
                    assert paths[p][1] is not None, \
                        "Empty parent added, but child wasn't added !?"

                    revnum = paths[p][2]
                    branch_path = paths[p][1].encode("utf-8") + branch_path[len(p):]
                    break

    def follow_branch_history(self, branch_path, revnum, mapping):
        """Return all the changes that happened in a branch 
        between branch_path and revnum. 

        :return: iterator that returns tuples with branch path, 
            changed paths and revision number.
        """
        assert isinstance(branch_path, str)
        assert mapping.is_branch(branch_path) or mapping.is_tag(branch_path), \
                "Mapping %r doesn't accept %s as branch or tag" % (mapping, branch_path)

        for (bp, paths, revnum) in self._log.follow_path(branch_path, revnum):
            assert revnum > 0 or bp == ""
            assert mapping.is_branch(bp) or mapping.is_tag(bp)
            # Remove non-bp paths from paths
            for p in paths.keys():
                if not p.startswith(bp+"/") and bp != p and bp != "":
                    del paths[p]

            if paths == {}:
                continue

            if (paths.has_key(bp) and paths[bp][1] is not None and 
                not mapping.is_branch(paths[bp][1]) and
                not mapping.is_tag(paths[bp][1])):
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

    def get_config(self):
        return SvnRepositoryConfig(self.uuid)

    def has_signature_for_revision_id(self, revision_id):
        """Check whether a signature exists for a particular revision id.

        :param revision_id: Revision id for which the signatures should be looked up.
        :return: False, as no signatures are stored for revisions in Subversion 
            at the moment.
        """
        # TODO: Retrieve from SVN_PROP_BZR_SIGNATURE 
        return False # SVN doesn't store GPG signatures. Perhaps 
                     # store in SVN revision property?


    def get_signature_text(self, revision_id):
        """Return the signature text for a particular revision.

        :param revision_id: Id of the revision for which to return the 
                            signature.
        :raises NoSuchRevision: Always
        """
        # TODO: Retrieve from SVN_PROP_BZR_SIGNATURE 
        # SVN doesn't store GPG signatures
        raise NoSuchRevision(self, revision_id)

    def _full_revision_graph(self, mapping, _latest_revnum=None):
        if _latest_revnum is None:
            _latest_revnum = self.transport.get_latest_revnum()
        graph = {}
        for (branch, revnum) in self.follow_history(_latest_revnum, 
                                                    mapping):
            mutter('%r, %r' % (branch, revnum))
            revid = self.generate_revision_id(revnum, branch, mapping)
            graph[revid] = self.revision_parents(revid)
        return graph

    def get_revision_graph(self, revision_id=None):
        """See Repository.get_revision_graph()."""
        if revision_id == NULL_REVISION:
            return {}

        if revision_id is None:
            return self._full_revision_graph(self.get_mapping())

        (path, revnum, mapping) = self.lookup_revision_id(revision_id)

        _previous = revision_id
        self._ancestry = {}
        
        if revnum > 0:
            for (branch, rev) in self.follow_branch(path, revnum - 1, mapping):
                revid = self.generate_revision_id(rev, branch, mapping)
                self._ancestry[_previous] = [revid]
                _previous = revid

        self._ancestry[_previous] = []

        return self._ancestry

    def find_branches(self, using=False):
        """Find branches underneath this repository.

        This will include branches inside other branches.

        :param using: If True, list only branches using this repository.
        """
        # All branches use this repository, so the using argument can be 
        # ignored.
        scheme = self.get_scheme()

        existing_branches = [bp for (bp, revnum, _) in 
                filter(lambda (bp, rev, exists): exists,
                       self.find_branchpaths(scheme))]

        branches = []
        for bp in existing_branches:
            try:
                branches.append(Branch.open(urlutils.join(self.base, bp)))
            except NotBranchError: # Skip non-directories
                pass
        return branches

    def find_branchpaths(self, scheme, from_revnum=0, to_revnum=None):
        """Find all branch paths that were changed in the specified revision 
        range.

        :param revnum: Revision to search for branches.
        :return: iterator that returns tuples with (path, revision number, still exists). The revision number is the revision in which the branch last existed.
        """
        assert scheme is not None
        if to_revnum is None:
            to_revnum = self.transport.get_latest_revnum()

        created_branches = {}

        ret = []

        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i in range(from_revnum, to_revnum+1):
                pb.update("finding branches", i, to_revnum+1)
                paths = self._log.get_revision_paths(i)
                for p in sorted(paths.keys()):
                    if scheme.is_branch(p) or scheme.is_tag(p):
                        if paths[p][0] in ('R', 'D') and p in created_branches:
                            del created_branches[p]
                            if paths[p][1]:
                                prev_path = paths[p][1]
                                prev_rev = paths[p][2]
                            else:
                                prev_path = p
                                prev_rev = self._log.find_latest_change(p, 
                                    i-1, include_parents=True, 
                                    include_children=True)
                            assert isinstance(prev_rev, int)
                            ret.append((prev_path, prev_rev, False))

                        if paths[p][0] in ('A', 'R'): 
                            created_branches[p] = i
                    elif scheme.is_branch_parent(p) or \
                            scheme.is_tag_parent(p):
                        if paths[p][0] in ('R', 'D'):
                            k = created_branches.keys()
                            for c in k:
                                if c.startswith(p+"/") and c in created_branches:
                                    del created_branches[c] 
                                    j = self._log.find_latest_change(c, i-1, 
                                            include_parents=True, 
                                            include_children=True)
                                    assert isinstance(j, int)
                                    ret.append((c, j, False))
                        if paths[p][0] in ('A', 'R'):
                            parents = [p]
                            while parents:
                                p = parents.pop()
                                try:
                                    for c in self.transport.get_dir(p, i)[0].keys():
                                        n = p+"/"+c
                                        if scheme.is_branch(n) or scheme.is_tag(n):
                                            created_branches[n] = i
                                        elif (scheme.is_branch_parent(n) or 
                                              scheme.is_tag_parent(n)):
                                            parents.append(n)
                                except SubversionException, (_, svn.core.SVN_ERR_FS_NOT_DIRECTORY):
                                    pass
        finally:
            pb.finished()

        pb = ui.ui_factory.nested_progress_bar()
        i = 0
        for p in created_branches:
            pb.update("determining branch last changes", 
                      i, len(created_branches))
            j = self._log.find_latest_change(p, to_revnum, 
                                             include_parents=True,
                                             include_children=True)
            if j is None:
                j = created_branches[p]
            assert isinstance(j, int)
            ret.append((p, j, True))
            i += 1
        pb.finished()

        return ret

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return True

    def get_physical_lock_status(self):
        return False

    def get_commit_builder(self, branch, parents, config, timestamp=None, 
                           timezone=None, committer=None, revprops=None, 
                           revision_id=None):
        from commit import SvnCommitBuilder
        return SvnCommitBuilder(self, branch, parents, config, timestamp, 
                timezone, committer, revprops, revision_id)




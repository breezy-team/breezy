# Copyright (C) 2006-2008 Jelmer Vernooij <jelmer@samba.org>

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
"""Subversion repository access."""

import bzrlib
from bzrlib import osutils, ui, urlutils, xml7
from bzrlib.branch import Branch, BranchCheckResult
from bzrlib.errors import (InvalidRevisionId, NoSuchRevision, NotBranchError, 
                           UninitializableFormat, UnrelatedBranches)
from bzrlib.graph import CachingParentsProvider
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.repository import Repository, RepositoryFormat, needs_read_lock
from bzrlib.revisiontree import RevisionTree
from bzrlib.revision import Revision, NULL_REVISION, ensure_null
from bzrlib.transport import Transport, get_transport
from bzrlib.trace import info, mutter

import os

from bzrlib.plugins.svn import changes, core, errors, logwalker, properties
from bzrlib.plugins.svn.branchprops import PathPropertyProvider
from bzrlib.plugins.svn.cache import create_cache_dir, sqlite3
from bzrlib.plugins.svn.changes import changes_path, find_prev_location
from bzrlib.plugins.svn.config import SvnRepositoryConfig
from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.mapping import (SVN_PROP_BZR_REVISION_ID, SVN_REVPROP_BZR_SIGNATURE,
                     parse_revision_metadata, parse_revid_property, 
                     parse_merge_property, BzrSvnMapping,
                     get_default_mapping, parse_revision_id, 
                     parse_svn_dateprop)
from bzrlib.plugins.svn.mapping3 import BzrSvnMappingv3FileProps
from bzrlib.plugins.svn.parents import DiskCachingParentsProvider
from bzrlib.plugins.svn.revids import CachingRevidMap, RevidMap
from bzrlib.plugins.svn.svk import (SVN_PROP_SVK_MERGE, svk_features_merged_since, 
                 parse_svk_feature)
from bzrlib.plugins.svn.tree import SvnRevisionTree
from bzrlib.plugins.svn.versionedfiles import (SvnTexts, VirtualRevisionTexts, 
                                               VirtualInventoryTexts, VirtualSignatureTexts)
import urllib

def full_paths(find_children, paths, bp, from_bp, from_rev):
    for c in find_children(from_bp, from_rev):
        path = c.replace(from_bp, bp+"/", 1).replace("//", "/")
        paths[path] = ('A', None, -1)
    return paths


class RevisionMetadata(object):
    def __init__(self, repository, branch_path, paths, revnum, revprops, fileprops):
        self.repository = repository
        self.branch_path = branch_path
        self.paths = paths
        self.revnum = revnum
        self.revprops = revprops
        self.fileprops = fileprops

    def __repr__(self):
        return "<RevisionMetadata for revision %d in repository %s>" % (self.revnum, self.repository.uuid)

    def get_revision_id(self, mapping):
        return self.repository.generate_revision_id(self.revnum, self.branch_path, mapping, self.revprops, self.fileprops)

    def get_lhs_parent(self, mapping):
        return self.repository.lhs_revision_parent(self.branch_path, self.revnum, mapping)

    def get_rhs_parents(self, mapping):
        extra_rhs_parents = mapping.get_rhs_parents(self.branch_path, self.revprops, self.fileprops)

        if extra_rhs_parents != ():
            return extra_rhs_parents

        if mapping.is_bzr_revision(self.revprops, self.fileprops):
            return ()

        (prev_path, prev_revnum) = self.repository._log.get_previous(self.branch_path, 
                                                          self.revnum)
        if prev_path is None and prev_revnum == -1:
            previous = {}
        else:
            previous = logwalker.lazy_dict({}, self.repository.branchprop_list.get_properties, prev_path.encode("utf-8"), prev_revnum)

        return tuple(self.repository._svk_merged_revisions(self.branch_path, self.revnum, mapping, self.fileprops, previous))

    def get_parent_ids(self, mapping):
        lhs_parent = self.get_lhs_parent(mapping)
        if lhs_parent == NULL_REVISION:
            return ()
        return (lhs_parent,) + self.get_rhs_parents(mapping)

    def __hash__(self):
        return hash((self.__class__, self.repository.uuid, self.branch_path, self.revnum))


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
        raise UninitializableFormat(self)

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data


CACHE_DB_VERSION = 4

cachedbs = {}

class SvnRepository(Repository):
    """
    Provides a simplified interface to a Subversion repository 
    by using the RA (remote access) API from subversion
    """
    def __init__(self, bzrdir, transport, branch_path=None):
        from bzrlib.plugins.svn import lazy_register_optimizers
        lazy_register_optimizers()
        from fileids import CachingFileIdMap, simple_apply_changes, FileIdMap
        _revision_store = None

        assert isinstance(transport, Transport)

        control_files = LockableFiles(transport, '', TransportLock)
        Repository.__init__(self, SvnRepositoryFormat(), bzrdir, control_files)

        self.texts = SvnTexts(self)
        self.revisions = VirtualRevisionTexts(self)
        self.inventories = VirtualInventoryTexts(self)
        self.signatures = VirtualSignatureTexts(self)
        self._cached_revnum = None
        self._lock_mode = None
        self._lock_count = 0
        self._layout = None
        self.transport = transport
        self.uuid = transport.get_uuid()
        assert self.uuid is not None
        self.base = transport.base
        assert self.base is not None
        self._serializer = xml7.serializer_v7
        self.get_config().add_location(self.base)
        self._log = logwalker.LogWalker(transport=transport)
        self.fileid_map = FileIdMap(simple_apply_changes, self)
        self.revmap = RevidMap(self)
        self._default_mapping = None
        self._hinted_branch_path = branch_path
        self._real_parents_provider = self

        cache = self.get_config().get_use_cache()

        if cache:
            cache_dir = self.create_cache_dir()
            cache_file = os.path.join(cache_dir, 'cache-v%d' % CACHE_DB_VERSION)
            if not cachedbs.has_key(cache_file):
                cachedbs[cache_file] = sqlite3.connect(cache_file)
            self.cachedb = cachedbs[cache_file]
            self._log = logwalker.CachingLogWalker(self._log, cache_db=self.cachedb)
            cachedir_transport = get_transport(cache_dir)
            self.fileid_map = CachingFileIdMap(cachedir_transport, self.fileid_map)
            self.revmap = CachingRevidMap(self.revmap, self.cachedb)
            self._real_parents_provider = DiskCachingParentsProvider(self._real_parents_provider, cachedir_transport)

        self.branchprop_list = PathPropertyProvider(self._log)

    def get_revmap(self):
        return self.revmap

   
    def get_transaction(self):
        raise NotImplementedError(self.get_transaction)

    def lock_read(self):
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w')
            self._lock_count += 1
        else:
            self._lock_mode = 'r'
            self._lock_count = 1

    def unlock(self):
        """See Branch.unlock()."""
        self._lock_count -= 1
        if self._lock_count == 0:
            self._lock_mode = None
            self._clear_cached_state()

    def _clear_cached_state(self):
        self._cached_revnum = None

    def lock_write(self):
        """See Branch.lock_write()."""
        # TODO: Obtain lock on the remote server?
        if self._lock_mode:
            assert self._lock_mode == 'w'
            self._lock_count += 1
        else:
            self._lock_mode = 'w'
            self._lock_count = 1

    def get_latest_revnum(self):
        if self._lock_mode in ('r','w') and self._cached_revnum:
            return self._cached_revnum
        self._cached_revnum = self.transport.get_latest_revnum()
        return self._cached_revnum

    def item_keys_introduced_by(self, revision_ids, _files_pb=None):
        fileids = {}

        for count, (revid, d) in enumerate(zip(revision_ids, self.get_deltas_for_revisions(self.get_revisions(revision_ids)))):
            if _files_pb is not None:
                _files_pb.update("fetch revisions for texts", count, len(revision_ids))
            for c in d.added + d.modified:
                fileids.setdefault(c[1], set()).add(revid)
            for c in d.renamed:
                fileids.setdefault(c[2], set()).add(revid)

        for fileid, altered_versions in fileids.items():
            yield ("file", fileid, altered_versions)
        
        # We're done with the files_pb.  Note that it finished by the caller,
        # just as it was created by the caller.
        del _files_pb

        yield ("inventory", None, revision_ids)

        # signatures
        revisions_with_signatures = set()
        for rev_id in revision_ids:
            try:
                self.get_signature_text(rev_id)
            except NoSuchRevision:
                # not signed.
                pass
            else:
                revisions_with_signatures.add(rev_id)
        yield ("signatures", None, revisions_with_signatures)

        yield ("revisions", None, revision_ids)

    @needs_read_lock
    def gather_stats(self, revid=None, committers=None):
        result = {}
        def revdate(revnum):
            return parse_svn_dateprop(self._log.revprop_list(revnum)[properties.PROP_REVISION_DATE])
        if committers is not None and revid is not None:
            all_committers = set()
            for rev in self.get_revisions(filter(lambda r: r is not None and r != NULL_REVISION, self.get_ancestry(revid))):
                if rev.committer != '':
                    all_committers.add(rev.committer)
            result['committers'] = len(all_committers)
        result['firstrev'] = revdate(0)
        result['latestrev'] = revdate(self.get_latest_revnum())
        result['uuid'] = self.uuid
        # Approximate number of revisions
        result['revisions'] = self.get_latest_revnum()+1
        return result

    def get_mapping(self):
        if self._default_mapping is None:
            self._default_mapping = get_default_mapping().from_repository(self, self._hinted_branch_path)
        return self._default_mapping

    def _make_parents_provider(self):
        return CachingParentsProvider(self._real_parents_provider)

    def set_layout(self, layout):
        self._layout = layout

    def get_layout(self):
        if self._layout is not None:
            return self._layout
        return self.get_mapping().get_mandated_layout(self)

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

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
        return self.fileid_map.get_map(self.uuid, revnum, path, mapping)

    def transform_fileid_map(self, uuid, revnum, branch, changes, renames, 
                             mapping):
        return self.fileid_map.apply_changes(uuid, revnum, branch, changes, 
                                             renames, mapping)[0]

    def iter_all_changes(self, layout=None, pb=None):
        if layout is None:
            layout = self.get_layout()
    
        latest_revnum = self.get_latest_revnum()

        for (paths, revnum, revprops) in self._log.iter_changes(None, 0, latest_revnum, pb=pb):
            if pb:
                pb.update("discovering revisions", revnum, latest_revnum)
            yielded_paths = set()
            for p in paths:
                try:
                    bp = layout.parse(p)[2]
                except NotBranchError:
                    pass
                else:
                    if not bp in yielded_paths:
                        if not bp in paths or paths[bp][0] != 'D':
                            assert revnum > 0 or bp == "", "%r:%r" % (bp, revnum)
                            yielded_paths.add(bp)
                            if not bp in paths:
                                svn_fileprops = {}
                            else:
                                svn_fileprops = logwalker.lazy_dict({}, self.branchprop_list.get_changed_properties, bp, revnum)
                            yield RevisionMetadata(self, bp, paths, revnum, revprops, svn_fileprops)

    def all_revision_ids(self, layout=None, mapping=None):
        if mapping is None:
            mapping = self.get_mapping()
        if layout is None:
            layout = self.get_layout()
        for revmeta in self.iter_all_changes(layout):
            yield revmeta.get_revision_id(mapping)

    def set_make_working_trees(self, new_value):
        """See Repository.set_make_working_trees()."""
        pass # FIXME: ignored, nowhere to store it... 

    def make_working_trees(self):
        """See Repository.make_working_trees().

        Always returns False, as working trees are never created inside 
        Subversion repositories.
        """
        return False

    def iter_reverse_revision_history(self, revision_id, pb=None, limit=0):
        """Iterate backwards through revision ids in the lefthand history

        :param revision_id: The revision id to start with.  All its lefthand
            ancestors will be traversed.
        """
        if revision_id in (None, NULL_REVISION):
            return
        (branch_path, revnum, mapping) = self.lookup_revision_id(revision_id)
        for revmeta in self.iter_reverse_branch_changes(branch_path, revnum, mapping, pb=pb, 
                                                        limit=limit):
            yield revmeta.get_revision_id(mapping)

    def get_ancestry(self, revision_id, topo_sorted=True):
        """See Repository.get_ancestry().
        """
        ancestry = []
        graph = self.get_graph()
        for rev, parents in graph.iter_ancestry([revision_id]):
            if rev == NULL_REVISION:
                rev = None
            ancestry.append(rev)
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
            return (core.NODE_DIR == self.transport.check_path(path, revnum))
        except SubversionException, (_, num):
            if num == errors.ERR_FS_NO_SUCH_REVISION:
                return False
            raise

    def revision_trees(self, revids):
        """See Repository.revision_trees()."""
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        """See Repository.revision_tree()."""
        revision_id = ensure_null(revision_id)

        if revision_id == NULL_REVISION:
            inventory = Inventory(root_id=None)
            inventory.revision_id = revision_id
            return RevisionTree(self, inventory, revision_id)

        return SvnRevisionTree(self, revision_id)

    def lhs_revision_parent(self, path, revnum, mapping):
        """Find the mainline parent of the specified revision.

        :param path: Path of the revision in Subversion
        :param revnum: Subversion revision number
        :param mapping: Mapping.
        :return: Revision id of the left-hand-side parent or None if 
                  this is the first revision
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int)

        iterator = self.iter_reverse_branch_changes(path, revnum, 
                                                      mapping=mapping, limit=2)
        revmeta = iterator.next()
        assert revmeta.branch_path == path
        assert revmeta.revnum == revnum
        try:
            return iterator.next().get_revision_id(mapping)
        except StopIteration:
            return NULL_REVISION

    def get_parent_map(self, revids):
        parent_map = {}
        for revision_id in revids:
            if revision_id == NULL_REVISION:
                parent_map[revision_id] = ()
                continue

            try:
                (branch, revnum, mapping) = self.lookup_revision_id(ensure_null(revision_id))
            except NoSuchRevision:
                continue

            mainline_parent = self.lhs_revision_parent(branch, revnum, mapping)
            parent_ids = (mainline_parent,)
            
            if mainline_parent != NULL_REVISION:

                svn_fileprops = logwalker.lazy_dict({}, self.branchprop_list.get_changed_properties, branch, revnum)
                svn_revprops = self._log.revprop_list(revnum)
                revmeta = RevisionMetadata(self, branch, None, revnum, svn_revprops, svn_fileprops)

                parent_ids += revmeta.get_rhs_parents(mapping)

            parent_map[revision_id] = parent_ids
        return parent_map

    def _svk_merged_revisions(self, branch, revnum, mapping, 
                              current_fileprops, previous_fileprops):
        """Find out what SVK features were merged in a revision.

        """
        current = current_fileprops.get(SVN_PROP_SVK_MERGE, "")
        if current == "":
            return
        previous = previous_fileprops.get(SVN_PROP_SVK_MERGE, "")
        for feature in svk_features_merged_since(current, previous):
            # We assume svk:merge is only relevant on non-bzr-svn revisions. 
            # If this is a bzr-svn revision, the bzr-svn properties 
            # would be parsed instead.
            #
            # This saves one svn_get_dir() call.
            revid = svk_feature_to_revision_id(feature, mapping)
            if revid is not None:
                yield revid

    def get_revision(self, revision_id):
        """See Repository.get_revision."""
        if not revision_id or not isinstance(revision_id, str):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)

        (path, revnum, mapping) = self.lookup_revision_id(revision_id)
        
        svn_revprops = self._log.revprop_list(revnum)
        svn_fileprops = logwalker.lazy_dict({}, self.branchprop_list.get_changed_properties, path, revnum)

        revmeta = RevisionMetadata(self, path, None, revnum, svn_revprops, svn_fileprops)

        rev = Revision(revision_id=revision_id, 
                       parent_ids=revmeta.get_parent_ids(mapping),
                       inventory_sha1="")

        rev.svn_revision = revnum
        rev.svn_branch = path
        rev.svn_uuid = self.uuid

        mapping.import_revision(svn_revprops, svn_fileprops, self.uuid, path, 
                                revnum, rev)

        return rev

    def get_revisions(self, revision_ids):
        """See Repository.get_revisions()."""
        # TODO: More efficient implementation?
        return map(self.get_revision, revision_ids)

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError(self.add_revision)

    def generate_revision_id(self, revnum, path, mapping, revprops=None, changed_fileprops=None):
        """Generate an unambiguous revision id. 
        
        :param revnum: Subversion revision number.
        :param path: Branch path.
        :param mapping: Mapping to use.

        :return: New revision id.
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int)
        assert isinstance(mapping, BzrSvnMapping)

        if revprops is None:
            revprops = self._log.revprop_list(revnum)

        if changed_fileprops is None:
            changed_fileprops = logwalker.lazy_dict({}, self.branchprop_list.get_changed_properties, path, revnum)

        return self.get_revmap().get_revision_id(revnum, path, mapping, revprops, changed_fileprops)

    def lookup_revision_id(self, revid, layout=None, ancestry=None):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :param layout: Optional repository layout to use when searching for 
                       revisions
        :raises: NoSuchRevision
        :return: Tuple with branch path, revision number and mapping.
        """
        # FIXME: Use ancestry
        # If there is no entry in the map, walk over all branches:
        if layout is None:
            layout = self.get_layout()
        return self.get_revmap().get_branch_revnum(revid, layout)

    def get_inventory_xml(self, revision_id):
        """See Repository.get_inventory_xml()."""
        return self.serialise_inventory(self.get_inventory(revision_id))

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
        return self._serializer.write_revision_to_string(
            self.get_revision(revision_id))

    def iter_changes(self, branch_path, revnum, mapping=None, pb=None, limit=0):
        """Iterate over all revisions backwards.
        
        :return: iterator that returns tuples with branch path, 
            changed paths, revision number, changed file properties and 
        """
        assert isinstance(branch_path, str)
        assert mapping is None or mapping.is_branch(branch_path) or mapping.is_tag(branch_path), \
                "Mapping %r doesn't accept %s as branch or tag" % (mapping, branch_path)

        bp = branch_path
        i = 0

        # Limit can't be passed on directly to LogWalker.iter_changes() 
        # because we're skipping some revs
        # TODO: Rather than fetching everything if limit == 2, maybe just 
        # set specify an extra X revs just to be sure?
        for (paths, revnum, revprops) in self._log.iter_changes([branch_path], revnum, pb=pb):
            assert bp is not None
            next = find_prev_location(paths, bp, revnum)
            assert revnum > 0 or bp == ""
            assert mapping is None or mapping.is_branch(bp) or mapping.is_tag(bp), "%r is not a valid path" % bp

            if (next is not None and 
                not (mapping is None or mapping.is_branch(next[0]) or mapping.is_tag(next[0]))):
                # Make it look like the branch started here if the mapping 
                # doesn't support weird paths as branches
                lazypaths = logwalker.lazy_dict(paths, full_paths, self._log.find_children, paths, bp, next[0], next[1])
                paths[bp] = ('A', None, -1)

                yield (bp, lazypaths, revnum, revprops)
                return
                     
            if changes_path(paths, bp, False):
                yield (bp, paths, revnum, revprops)
                i += 1
                if limit != 0 and limit == i:
                    break

            if next is None:
                bp = None
            else:
                bp = next[0]

    def iter_reverse_branch_changes(self, branch_path, revnum, mapping=None, pb=None, limit=0):
        """Return all the changes that happened in a branch 
        until branch_path,revnum. 

        :return: iterator that returns RevisionMetadata objects.
        """
        history_iter = self.iter_changes(branch_path, revnum, mapping, pb=pb, 
                                         limit=limit)
        for (bp, paths, revnum, revprops) in history_iter:
            if not bp in paths:
                svn_fileprops = {}
            else:
                svn_fileprops = logwalker.lazy_dict({}, self.branchprop_list.get_changed_properties, bp, revnum)

            yield RevisionMetadata(self, bp, paths, revnum, revprops, svn_fileprops)

    def get_config(self):
        return SvnRepositoryConfig(self.uuid)

    def has_signature_for_revision_id(self, revision_id):
        """Check whether a signature exists for a particular revision id.

        :param revision_id: Revision id for which the signatures should be looked up.
        :return: False, as no signatures are stored for revisions in Subversion 
            at the moment.
        """
        try:
            (path, revnum, mapping) = self.lookup_revision_id(revision_id)
        except NoSuchRevision:
            return False
        revprops = self.transport.revprop_list(revnum)
        return revprops.has_key(SVN_REVPROP_BZR_SIGNATURE)

    def get_signature_text(self, revision_id):
        """Return the signature text for a particular revision.

        :param revision_id: Id of the revision for which to return the 
                            signature.
        :raises NoSuchRevision: Always
        """
        (path, revnum, mapping) = self.lookup_revision_id(revision_id)
        revprops = self.transport.revprop_list(revnum)
        try:
            return revprops[SVN_REVPROP_BZR_SIGNATURE]
        except KeyError:
            raise NoSuchRevision(self, revision_id)

    def add_signature_text(self, revision_id, signature):
        (path, revnum, mapping) = self.lookup_revision_id(revision_id)
        self.transport.change_rev_prop(revnum, SVN_REVPROP_BZR_SIGNATURE, signature)

    @needs_read_lock
    def find_branches(self, using=False, layout=None):
        """Find branches underneath this repository.

        This will include branches inside other branches.

        :param using: If True, list only branches using this repository.
        """
        from bzrlib.plugins.svn.branch import SvnBranch # avoid circular imports
        # All branches use this repository, so the using argument can be 
        # ignored.
        if layout is None:
            layout = self.get_layout()

        branches = []
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for project, bp, nick in layout.get_branches(self.get_latest_revnum(), pb=pb):
                try:
                    branches.append(SvnBranch(self, bp))
                except NotBranchError: # Skip non-directories
                    pass
        finally:
            pb.finished()
        return branches

    @needs_read_lock
    def find_tags(self, layout=None, revnum=None, project=None):
        """Find branches underneath this repository.

        """
        if layout is None:
            layout = self.get_layout()

        if revnum is None:
            revnum = self.get_latest_revnum()

        mapping = self.get_mapping()

        tags = {}
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for project, bp, nick in layout.get_tags(revnum, project=project, pb=pb):
                npb = ui.ui_factory.nested_progress_bar()
                try:
                    it = self.iter_changes(bp, revnum, mapping, pb=npb, limit=2)
                    (bp, paths, rev, _) = it.next()
                    if paths.has_key(bp):
                        del paths[bp]
                        if not changes.changes_path(paths, bp, False):
                            try:
                                (bp, _, rev, _) = it.next()
                            except StopIteration:
                                pass
                finally:
                    npb.finished()
                
                tags[nick] = self.generate_revision_id(rev, bp, mapping)
        finally:
            pb.finished()
        return tags

    def find_branchpaths(self, layout, from_revnum=0, to_revnum=None):
        """Find all branch paths that were changed in the specified revision 
        range.

        :param revnum: Revision to search for branches.
        :return: iterator that returns tuples with (path, revision number, still exists). The revision number is the revision in which the branch last existed.
        """
        assert layout is not None
        if to_revnum is None:
            to_revnum = self.get_latest_revnum()

        created_branches = {}

        ret = []

        pb = ui.ui_factory.nested_progress_bar()
        try:
            for (paths, i, revprops) in self._log.iter_changes([""], from_revnum, to_revnum):
                pb.update("finding branches", i, to_revnum)
                for p in sorted(paths.keys()):
                    if layout.is_branch(p) or layout.is_tag(p):
                        if paths[p][0] in ('R', 'D') and p in created_branches:
                            ret.append((p, created_branches[p], False))
                            del created_branches[p]

                        if paths[p][0] in ('A', 'R', 'M'): 
                            created_branches[p] = i
                    elif layout.is_branch_parent(p) or layout.is_tag_parent(p):
                        if paths[p][0] in ('R', 'D'):
                            k = created_branches.keys()
                            for c in k:
                                if c.startswith(p+"/") and c in created_branches:
                                    ret.append((c, created_branches[c], False))
                                    del created_branches[c] 
                        if paths[p][0] in ('A', 'R') and paths[p][1] is not None:
                            parents = [p]
                            while parents:
                                p = parents.pop()
                                try:
                                    for c in self.transport.get_dir(p, i)[0].keys():
                                        n = p+"/"+c
                                        if layout.is_branch(n) or layout.is_tag(n):
                                            created_branches[n] = i
                                        elif (layout.is_branch_parent(n) or 
                                              layout.is_tag_parent(n)):
                                            parents.append(n)
                                except SubversionException, (_, errors.ERR_FS_NOT_DIRECTORY):
                                    pass
        finally:
            pb.finished()

        for p, i in created_branches.items():
            ret.append((p, i, True))

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

    def find_fileprop_branches(self, layout, from_revnum, to_revnum):
        reuse_policy = self.get_config().get_reuse_revisions()
        if reuse_policy == "removed-branches":
            for (branch, revno, _) in self.find_branchpaths(layout, from_revnum, 
                                                            to_revnum):
                yield (branch, revno)
        elif reuse_policy in ("other-branches", "none"):
            revnum = self.get_latest_revnum()
            for (project, branch, nick) in layout.get_branches(revnum):
                yield (branch, revnum)
        else:
            assert False


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
from bzrlib.errors import NoSuchRevision, InvalidRevisionId, BzrError
from bzrlib.graph import Graph
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from bzrlib.lockable_files import LockableFiles, TransportLock
import bzrlib.osutils as osutils
from bzrlib.progress import ProgressBar
from bzrlib.repository import Repository
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.transport import Transport
from bzrlib.trace import mutter

from svn.core import SubversionException, Pool
import svn.core

import os
from cStringIO import StringIO

import branch
import logwalker
from tree import SvnRevisionTree

class SvnInventoryFile(InventoryFile):
    """Inventory entry that can either be a plain file or a 
    symbolic link. Avoids fetching data until necessary. """
    def __init__(self, file_id, name, parent_id, repository, path, revnum, 
                 has_props):
        self.repository = repository
        self.path = path
        self.has_props = has_props
        self.revnum = revnum
        InventoryFile.__init__(self, file_id, name, parent_id)

    def _get_sha1(self):
        text = self.repository._get_file(self.path, self.revnum).read()
        return osutils.sha_string(text)

    def _get_executable(self):
        if not self.has_props:
            return False

        value = self.repository._get_file_prop(self.path, self.revnum, 
                    svn.core.SVN_PROP_EXECUTABLE)
        if value and value == svn.core.SVN_PROP_EXECUTABLE_VALUE:
            return True
        return False 

    def _is_special(self):
        if not self.has_props:
            return False

        value = self.repository._get_file_prop(self.path, self.revnum, 
                    svn.core.SVN_PROP_SPECIAL)
        if value and value == svn.core.SVN_PROP_SPECIAL_VALUE:
            return True
        return False 

    def _get_symlink_target(self):
        if not self._is_special():
            return None
        data = self.repository._get_file(self.path, self.revnum).read()
        if not data.startswith("link "):
            raise BzrError("Improperly formatted symlink file")
        return data[len("link "):]

    def _get_kind(self):
        if self._is_special():
            return 'symlink'
        return 'file'

    # FIXME: we need a set function here because of InventoryEntry.__init__
    def _phony_set(self, data):
        pass
   
    text_sha1 = property(_get_sha1, _phony_set)
    executable = property(_get_executable, _phony_set)
    symlink_target = property(_get_symlink_target, _phony_set)
    kind = property(_get_kind, _phony_set)


class SvnRepository(Repository):
    """
    Provides a simplified interface to a Subversion repository 
    by using the RA (remote access) API from subversion
    """
    def __init__(self, bzrdir, transport):
        _revision_store = None

        assert isinstance(transport, Transport)

        control_files = LockableFiles(transport, '', TransportLock)
        Repository.__init__(self, 'Subversion Smart Server', bzrdir, 
            control_files, None, None, None)

        self.ra = transport.ra

        self.uuid = svn.ra.get_uuid(self.ra)
        self.base = self.url = transport.base
        self.fileid_map = {}
        self.path_map = {}
        self.text_cache = {}
        self.dir_cache = {}
        self.scheme = bzrdir.scheme
        self.pool = Pool()

        assert self.url
        assert self.uuid

        mutter("Connected to repository , UUID %s" % self.uuid)

        self._log = logwalker.LogWalker(self.ra, self.uuid, 
                svn.ra.get_latest_revnum(self.ra))

    def _check(self, revision_ids):
        return BranchCheckResult(self)

    def get_inventory(self, revision_id):
        assert revision_id != None
        (path, revnum) = self.parse_revision_id(revision_id)
        assert path != None
        mutter('getting inventory %r for branch %r' % (revnum, path))

        def read_directory(inv, id, path, revnum):
            (props, dirents) = self._cache_get_dir(path, revnum)

            recurse = {}

            for child_name in dirents:
                dirent = dirents[child_name]

                if path:
                    child_path = "%s/%s" % (path, child_name)
                else:
                    child_path = child_name

                (child_id, revid) = self.path_to_file_id(dirent.created_rev, 
                    child_path)
                if dirent.kind == svn.core.svn_node_dir:
                    inventry = InventoryDirectory(child_id, child_name, id)
                    recurse[child_path] = dirent.created_rev
                elif dirent.kind == svn.core.svn_node_file:
                    inventry = SvnInventoryFile(child_id, child_name, id, self, 
                        child_path, dirent.created_rev, dirent.has_props)

                else:
                    raise BzrError("Unknown entry kind for '%s': %s" % 
                        (child_path, dirent.kind))

                inventry.revision = revid
                inv.add(inventry)

            for child_path in recurse:
                (child_id, _) = self.path_to_file_id(recurse[child_path], 
                    child_path)
                read_directory(inv, child_id, child_path, recurse[child_path])
    
        inv = Inventory(revision_id=revision_id, root_id=ROOT_ID)
        # FIXME: Is this the correct revision_id to set? Probably not...
        inv[ROOT_ID].revision = revision_id

        assert path != None
        read_directory(inv, ROOT_ID, path, revnum)

        return inv

    def path_from_file_id(self, revision_id, file_id):
        """Generate a full Subversion path from a bzr file id.
        
        :param revision_id: 
        :param file_id: 
        :return: Subversion file name relative to the current repository.
        """
        # TODO: Do real parsing here
        return self.fileid_map[revision_id][file_id]

    def path_to_file_id(self, revnum, path):
        """Generate a bzr file id from a Subversion file name. """

        if self.path_map.has_key(revnum) and self.path_map[revnum].has_key(path):
            return self.path_map[revnum][path]

        (path_branch, filename) = self.scheme.unprefix(path)

#        for (paths, rev) in self._log.follow_history(path_branch, revnum):
#            if copied_from:
#                if exists(copied_from, revnum):
#                    break
#                filename = copied_from

        revision_id = self.generate_revision_id(revnum, path_branch)

        if not self.fileid_map.has_key(revision_id):
            self.fileid_map[revision_id] = {}

        if not self.path_map.has_key(revnum):
            self.path_map[revnum] = {}

        file_id = filename.replace("/", "@")
        if file_id == "":
            file_id = ROOT_ID

        self.path_map[revnum][path] = (file_id, revision_id)
        self.fileid_map[revision_id][file_id] = (path, revnum)
        return (file_id, revision_id)

    def all_revision_ids(self):
        raise NotImplementedError(self.all_revision_ids)

    def get_inventory_weave(self):
        raise NotImplementedError(self.get_inventory_weave)

    def set_make_working_trees(self, new_value):
        """See Repository.set_make_working_trees()."""
        pass # FIXME: ignored, nowhere to store it... 

    def make_working_trees(self):
        return False

    def get_ancestry(self, revision_id):
        if revision_id is None: # FIXME: Is this correct?
            return [None]

        #FIXME: Find not just direct predecessors 
        # but also branches from which this branch was copied
        (path, revnum) = self.parse_revision_id(revision_id)

        self._ancestry = [None]

        for (paths, rev, _, _, _) in self._log.get_branch_log(path, 0, revnum - 1, 0, False):
            self._ancestry.append(self.generate_revision_id(rev, path))

        return self._ancestry

    def has_revision(self, revision_id):
        try:
            (path, revnum) = self.parse_revision_id(revision_id)
        except NoSuchRevision:
            return False

        mutter("svn check_path -r%d %s" % (revnum, path))
        try:
            kind = svn.ra.check_path(self.ra, path.encode('utf8'), revnum)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                return False
            raise

        return (kind != svn.core.svn_node_none)

    def revision_tree(self, revision_id):
        if revision_id is None or revision_id == NULL_REVISION:
            return EmptyTree()
        else:
            return SvnRevisionTree(self, revision_id)

    def revision_parents(self, revision_id):
        (path, revnum) = self.parse_revision_id(revision_id)

        # TODO: Use get_file_revs()

        parent_ids = []

        for (paths, rev, a, b, c) in self._log.get_branch_log(path, revnum - 1, 0, 1, False):
            parent_ids.append(self.generate_revision_id(rev, path))
        
        mutter('getting revprop -r %r bzr:parents' % revnum)
        ghosts = svn.ra.rev_prop(self.ra, revnum, "bzr:parents")

        if ghosts is not None:
            parent_ids.extend(ghosts.splitlines())

        return parent_ids

    def get_revision(self, revision_id):
        """See Repository.get_revision."""
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)

        mutter("retrieving %s" % revision_id)
        (path, revnum) = self.parse_revision_id(revision_id)
        
        mutter('svn proplist -r %r' % revnum)
        svn_props = svn.ra.rev_proplist(self.ra, revnum)

        parent_ids = self.revision_parents(revision_id)

        # Commit SVN revision properties to a Revision object
        bzr_props = {}
        rev = Revision(revision_id=revision_id,
                       parent_ids=parent_ids)

        for name in svn_props:
            bzr_props[name] = svn_props[name].decode('utf8')

        rev.timestamp = 1.0 * svn.core.secs_from_timestr(
            bzr_props[svn.core.SVN_PROP_REVISION_DATE], None)
        rev.timezone = None

        rev.committer = bzr_props[svn.core.SVN_PROP_REVISION_AUTHOR]
        rev.message = bzr_props[svn.core.SVN_PROP_REVISION_LOG]

        rev.properties = bzr_props

        rev.inventory_sha1 = self.get_inventory_sha1(revision_id)

        return rev

    def get_revisions(self, revision_ids):
        # TODO: More efficient implementation?
        return map(self.get_revision, revision_ids)

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError()

    def fileid_involved_between_revs(self, from_revid, to_revid):
        # TODO
        raise NotImplementedError()

    def fileid_involved(self, last_revid=None):
        raise NotImplementedError()

    def fileids_altered_by_revision_ids(self, revision_ids):
        # FIXME: Now that the log cache is local, simplify this 
        # function.
        ranges = {}
        interested = {}

        # First, figure out for which revisions to fetch 
        # the logs. Keeps the range as narrow as possible to 
        # save bandwidth (and thus increase speed)
        for revid in revision_ids:
            (path, revnum) = self.parse_revision_id(revid)

            if not ranges.has_key(path):
                ranges[path] = (revnum, revnum)
                interested[path] = [revnum]
            else:
                (min, max) = ranges[path]
                
                if revnum < min: 
                    min = revnum
                if revnum > max:
                    max = revnum
                
                interested[path].append(revnum)

        result = {}

        for path in ranges:
            self._tmp = path
            (min, max) = ranges[path]
            for (paths, revnum, _, _, _) in self._log.get_branch_log(path, min, max, 0, False):
                if not revnum in interested[self._tmp]:
                    return
                for path in paths:
                    (file_id, revid) = self.path_to_file_id(revnum, path)
                    if not result.has_key(file_id):
                        result[file_id] = []
                    result[file_id].append(revid)

        return result

    def fileid_involved_by_set(self, changes):
        ids = []

        for revid in changes:
            pass #FIXME

        return ids

    def generate_revision_id(self, revnum, path):
        """Generate a unambiguous revision id. 
        
        :param revnum: Subversion revision number.
        :param path: Branch path.

        :return: New revision id.
        """
        return "svn:%d@%s-%s" % (revnum, self.uuid, path.strip("/"))

    def parse_revision_id(self, revid):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :raises: NoSuchRevision
        :return: Tuple with branch path and revision number.
        """

        assert revid
        assert isinstance(revid, basestring)

        if not revid.startswith("svn:"):
            raise NoSuchRevision(self, revid)

        revid = revid[len("svn:"):]

        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]

        if uuid != self.uuid:
            raise NoSuchRevision(self, revid)

        branch_path = revid[fash+1:]
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (branch_path, revnum)

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(
            self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        return osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(
            self.get_revision(revision_id))

    def get_revision_sha1(self, revision_id):
        return osutils.sha_string(self.get_revision_xml(revision_id))

    def has_signature_for_revision_id(self, revision_id):
        # TODO: Retrieve from 'bzr:gpg-signature'
        return False # SVN doesn't store GPG signatures. Perhaps 
                     # store in SVN revision property?

    def get_signature_text(self, revision_id):
        # TODO: Retrieve from 'bzr:gpg-signature'
        # SVN doesn't store GPG signatures
        raise NoSuchRevision(self, revision_id)

    def _cache_get_dir(self, path, revnum):
        assert path != None
        path = path.lstrip("/")
        if self.dir_cache.has_key(path) and \
           self.dir_cache[path].has_key(revnum):
            return self.dir_cache[path][revnum]

        mutter("svn ls -r %d '%r'" % (revnum, path))

        try:
            (dirents, _, props) = svn.ra.get_dir2(
                self.ra, path.encode('utf8'), 
                revnum, svn.core.SVN_DIRENT_KIND
                + svn.core.SVN_DIRENT_CREATED_REV
                + svn.core.SVN_DIRENT_HAS_PROPS, self.pool)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(self, revnum)
            raise

        if not self.dir_cache.has_key(path):
            self.dir_cache[path] = {}

        self.dir_cache[path][revnum] = (props, dirents)

        return self.dir_cache[path][revnum]

    def _cache_get_file(self, path, revnum):
        assert path != None
        path = path.lstrip("/")
        if self.text_cache.has_key(path) and \
           self.text_cache[path].has_key(revnum):
               return self.text_cache[path][revnum]

        stream = StringIO()
        mutter('svn getfile -r %r %s' % (revnum, path))
        (realrevnum, props) = svn.ra.get_file(self.ra, path.encode('utf8'), 
            revnum, stream, self.pool)
        if not self.text_cache.has_key(path):
            self.text_cache[path] = {}

        self.text_cache[path][revnum] = (props, stream)
        return self.text_cache[path][revnum]

    def _get_file_prop(self, path, revnum, name):
        (props, _) = self._cache_get_file(path, revnum)
        if props.has_key(name):
            return props[name]
        return None

    def _get_file(self, path, revnum):
        if path == ".bzrignore":
            # TODO: Generate ignore file for specified revision
            return StringIO()

        (_, stream) = self._cache_get_file(path, revnum)
        stream.seek(0)
        return stream

    def get_revision_graph(self, revision_id):
        if revision_id is None:
            raise NotImplementedError()

        (path, revnum) = self.parse_revision_id(revision_id)

        self._previous = revision_id
        self._ancestry = {}
        
        for (_, rev) in self._log.follow_history(path, revnum - 1):
            revid = self.generate_revision_id(rev, path)
            self._ancestry[self._previous] = [revid]
            self._previous = revid

        self._ancestry[self._previous] = []

        return self._ancestry

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

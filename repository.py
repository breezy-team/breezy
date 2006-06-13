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

from bzrlib.branch import BranchCheckResult
from bzrlib.repository import Repository
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.trace import mutter
from bzrlib.revision import Revision
from bzrlib.errors import NoSuchRevision, InvalidRevisionId, BzrError
from bzrlib.progress import ProgressBar
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from libsvn._core import SubversionException
import svn.core
import bzrlib
from fakeweave import FakeFileStore, FakeInventoryWeave
import branch
from bzrlib.weave import Weave
from cStringIO import StringIO
from bzrlib.graph import Graph

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
        return bzrlib.osutils.sha_string(text)

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
    def __init__(self, bzrdir, url):
        _revision_store = None
        control_store = None

        text_store = FakeFileStore(self)
        control_files = LockableFiles(bzrdir.transport, '', TransportLock)
        Repository.__init__(self, 'Subversion Smart Server', bzrdir, 
            control_files, _revision_store, control_store, text_store)

        self.pool = svn.core.svn_pool_create(None)

        self._scheme = bzrdir.transport._scheme
        self.ra = bzrdir.transport.ra

        self.uuid = svn.ra.get_uuid(self.ra)
        self.base = self.url = url
        self.fileid_map = {}
        self.text_cache = {}
        self.dir_cache = {}

        assert self.url
        assert self.uuid

        mutter("Connected to repository at %s, UUID %s" % (
            bzrdir.transport.svn_root_url, self.uuid))


    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

    def _check(self, revision_ids):
        return BranchCheckResult(self)

    def get_inventory(self, revision_id):
        (path, revnum) = self.parse_revision_id(revision_id)
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
    
        inv = Inventory()

        read_directory(inv, ROOT_ID, path, revnum)

        return inv

    def path_from_file_id(self, revision_id, file_id):
        """Generate a Subversion path from a bzr file id."""
        
        return self.fileid_map[revision_id][file_id]

    def path_to_file_id(self, revnum, path):
        """Generate a bzr file id from a Subversion file name. 
        Does not use svn.ra """

        (path_branch, filename) = self._scheme.unprefix(path)

        revision_id = self.generate_revision_id(revnum, path_branch)

        if not self.fileid_map.has_key(revision_id):
            self.fileid_map[revision_id] = {}

        file_id = filename.replace("/", "@")
        if file_id == "":
            file_id = ROOT_ID

        self.fileid_map[revision_id][file_id] = (path, revnum)
        return (file_id, revision_id)

    def all_revision_ids(self):
        raise NotImplementedError(self.all_revision_ids)

    def get_inventory_weave(self):
        return FakeInventoryWeave(self)

    def get_ancestry(self, revision_id):
        if revision_id is None: # FIXME: Is this correct?
            return []
        #FIXME: Find not just direct predecessors 
        # but also branches from which this branch was copied
        (path, revnum) = self.parse_revision_id(revision_id)

        self._ancestry = [None]

        def rcvr(paths, rev, author, date, message, pool):
            revid = self.generate_revision_id(rev, path)
            self._ancestry.append(revid)

        mutter("svn log -r 0:%d %s" % (revnum-1, path))
        try:
            svn.ra.get_log(self.ra, [path.encode('utf8')], 0, \
                revnum - 1, 1, False, False, rcvr)
        except SubversionException, (_, num):
            if num != svn.core.SVN_ERR_FS_NOT_FOUND:
                raise

        return self._ancestry

    def has_revision(self, revision_id):
        (path, revnum) = self.parse_revision_id(revision_id)

        mutter("svn check_path -r%d %s" % (revnum, path))
        kind = svn.ra.check_path(self.ra, path.encode('utf8'), revnum)

        return (kind != svn.core.svn_node_none)

    def revision_parents(self, revision_id):
        (path, revnum) = self.parse_revision_id(revision_id)

        parent_ids = []

        def rcvr(paths, rev, *args):
            revid = self.generate_revision_id(rev, path)
            parent_ids.append(revid)

        mutter("log -r%d:0 %s" % (revnum-1, path))

        try:
            svn.ra.get_log(self.ra, [path.encode('utf8')], revnum - 1, \
                0, 1, False, False, rcvr)
        except SubversionException, (_, num):
            # If this is the first revision, there are no parents
            if num != svn.core.SVN_ERR_FS_NOT_FOUND:
                raise

        return parent_ids

    def get_revision(self, revision_id):
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
            bzr_props[svn.core.SVN_PROP_REVISION_DATE], self.pool)
        rev.timezone = None

        rev.committer = bzr_props[svn.core.SVN_PROP_REVISION_AUTHOR]
        rev.message = bzr_props[svn.core.SVN_PROP_REVISION_LOG]

        rev.properties = bzr_props

        rev.inventory_sha1 = self.get_inventory_sha1(revision_id)

        return rev

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError()

    def fileid_involved_between_revs(self, from_revid, to_revid):
        raise NotImplementedError()

    def fileid_involved(self, last_revid=None):
        raise NotImplementedError()

    def fileids_altered_by_revision_ids(self, revision_ids):
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
                
                interested.append(revnum)

        result = {}

        def rcvr(paths, revnum, *args):
            if not revnum in interested[self._tmp]:
                return
            for path in paths:
                (file_id, revid) = self.path_to_file_id(revnum, path)
                if not result.has_key(file_id):
                    result[file_id] = []
                result[file_id].append(revid)

        for path in ranges:
            self._tmp = path
            (min, max) = ranges[path]
            mutter("svn log -r%d:%d %s" % (min, max, path))
            svn.ra.get_log(self.ra, [path.encode('utf8')], min, \
                max, 0, True, False, rcvr)

        return result

    def fileid_involved_by_set(self, changes):
        ids = []

        for revid in changes:
            pass #FIXME

        return ids

    def generate_revision_id(self, rev, path):
        """ Generate a unambiguous revision id. Does not use svn.ra """
        return "%d@%s-%s" % (rev, self.uuid, path)

    def parse_revision_id(self, revid):
        assert revid
        assert isinstance(revid, basestring)

        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]

        if uuid != self.uuid:
            raise NoSuchRevision()

        return (revid[fash+1:], int(revid[0:at]))

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(
            self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(
            self.get_revision(revision_id))

    def get_revision_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_revision_xml(revision_id))

    def has_signature_for_revision_id(self, revision_id):
        return False # SVN doesn't store GPG signatures. Perhaps 
                     # store in SVN revision property?

    def get_signature_text(self, revision_id):
        # SVN doesn't store GPG signatures
        raise NoSuchRevision(self, revision_id)

    def _cache_get_dir(self, path, revnum):
        if self.dir_cache.has_key(path) and \
           self.dir_cache[path].has_key(revnum):
            return self.dir_cache[path][revnum]

        mutter("svn ls -r %d '%r'" % (revnum, path))

        (dirents, _, props) = svn.ra.get_dir2(
                self.ra, path.encode('utf8'), 
                revnum, svn.core.SVN_DIRENT_KIND
                + svn.core.SVN_DIRENT_CREATED_REV
                + svn.core.SVN_DIRENT_HAS_PROPS, self.pool)

        if not self.dir_cache.has_key(path):
            self.dir_cache[path] = {}

        self.dir_cache[path][revnum] = (props, dirents)

        return self.dir_cache[path][revnum]

    def _cache_get_file(self, path, revnum):
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
        (_, stream) = self._cache_get_file(path, revnum)
        stream.seek(0)
        return stream

    def get_revision_graph(self, revision_id):
        if revision_id is None:
            raise NotImplementedError()

        (path, revnum) = self.parse_revision_id(revision_id)

        self._previous = revision_id
        self._ancestry = {}
        
        def rcvr(paths, rev, author, date, message, pool):
            revid = self.generate_revision_id(rev, path)
            self._ancestry[self._previous] = [revid]
            self._previous = revid

        mutter("svn log -r%d:0 %s" % (revnum-1, path))
        try:
            svn.ra.get_log(self.ra, [path.encode('utf8')], revnum - 1, \
                0, 0, False, False, rcvr)
        except SubversionException, (_, num):
            if num != svn.core.SVN_ERR_FS_NOT_FOUND:
                raise

        self._ancestry[self._previous] = []

        return self._ancestry

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return True

    def get_physical_lock_status(self):
        return False

    def copy_content_into(self, destination, revision_id=None, basis=None):
        pb = ProgressBar()

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call destination.add_revision() 
        # or destination.add_inventory() each time

        if revision_id is None:
            path = ""
            until_revnum = svn.ra.get_latest_revnum(self.ra)
        else:
            (path, until_revnum) = self.parse_revision_id(revision_id)
        
        weave_store = destination.weave_store

        current = {}

        transact = destination.get_transaction()

        changed = []

        mutter("svn log -r0:%d %s" % (until_revnum, path))
        def rcvr(paths, revnum, author, date, message, pool):
            changed.append((paths, revnum))
            pb.update('receiving revision information', revnum, until_revnum)

        svn.ra.get_log(self.ra, [path.encode('utf8')], 0, until_revnum, 0, 
                True, False, rcvr)

        for (paths, revnum) in changed:
            pb.update('copying revision', revnum, until_revnum)
            revid = self.generate_revision_id(revnum, path)
            inv = self.get_inventory(revid)
            rev = self.get_revision(revid)
            destination.add_revision(revid, rev, inv)

            #FIXME: use svn.ra.do_update
            for item in paths:
                (fileid, revid) = self.path_to_file_id(revnum, item)
                branch_path = self.parse_revision_id(revid)[0]
                if branch_path != path:
                    continue

                if paths[item].action == 'A':
                    weave = weave_store.get_weave_or_empty(fileid, transact)
                elif paths[item].action == 'M' or paths[item].action == 'R':
                    weave = weave_store.get_weave(fileid, transact)
                elif paths[item].action == 'D':
                    continue
                else:
                    raise BzrError("Unknown SVN action '%s'" % 
                        paths[item].action)

                parents = []
                if current.has_key(fileid):
                    parents = [current[fileid]]
                
                try:
                    stream = self._get_file(item, revnum)
                except SubversionException, (_, num):
                    if num != svn.core.SVN_ERR_FS_NOT_FILE:
                        raise
                    stream = None

                if stream:
                    stream.seek(0)
                    weave.add_lines(revid, parents, stream.readlines())
        
        pb.clear()

    def fetch(self, source, revision_id=None, pb=None):
        raise NotImplementedError(self.fetch)

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

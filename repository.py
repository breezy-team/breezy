# Foreign branch support for Subversion
# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.repository import Repository
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.trace import mutter
from bzrlib.revision import Revision
from bzrlib.errors import NoSuchRevision, InvalidRevisionId, BzrError
from bzrlib.versionedfile import VersionedFile
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from libsvn._core import SubversionException
import svn.core
import bzrlib
from branch import auth_baton
import branch
from bzrlib.weave import Weave
from cStringIO import StringIO

class SvnFileWeave(VersionedFile):
    def __init__(self,repository,weave_name,access_mode='w'):
        VersionedFile.__init__(self,access_mode)
        self.repository = repository
        self.file_id = weave_name
        assert self.file_id

    def get_lines(self, version_id):
        assert version_id != None

        (path,revnum) = self.repository.filename_from_file_id(version_id, self.file_id)


        stream = StringIO()
        mutter('svn cat -r %r %s' % (revnum, path))
        (revnum,props) = svn.ra.get_file(self.repository.ra, path.encode('utf8'), revnum, stream)
        stream.seek(0)

        return stream.readlines()

class SvnFileStore(object):
    def __init__(self,repository):
        self.repository = repository

    def get_weave(self,file_id,transaction):
        return SvnFileWeave(self.repository,file_id)

class BzrCallbacks(svn.ra.callbacks2_t):
    def __init__(self):
        svn.ra.callbacks2_t.__init__(self)

"""
Provides a simplified interface to a Subversion repository 
by using the RA (remote access) API from subversion
"""
class SvnRepository(Repository):
    branch_paths = [".","branches","tags"]

    def __init__(self, bzrdir, url):
        _revision_store = None
        control_store = None

        text_store = SvnFileStore(self)
        control_files = LockableFiles(bzrdir.transport, '', TransportLock)
        Repository.__init__(self, 'Subversion Smart Server', bzrdir, control_files, _revision_store, control_store, text_store)

        self.pool = svn.core.svn_pool_create(None)

        callbacks = BzrCallbacks()

        self.ra = svn.ra.open2(url.encode('utf8'), callbacks, None, None)

        self.uuid = svn.ra.get_uuid(self.ra)
        self.url = svn.ra.get_repos_root(self.ra)

        svn.ra.reparent(self.ra, self.url)

        self.fileid_map = {}

        assert self.url
        assert self.uuid

        mutter("Connected to repository at %s, UUID %s" % (self.url, self.uuid))


    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

    def get_inventory(self, revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)
        mutter('getting inventory %r for branch %r' % (revnum, path))

        def read_directory(inv,id,path):
            mutter("svn ls -r %d '%r'" % (revnum, path))

            (dirents,last_revnum,props) = svn.ra.get_dir2(self.ra, path.encode('utf8'), revnum, svn.core.SVN_DIRENT_KIND)

            recurse = []

            for child_name in dirents:
                dirent = dirents[child_name]

                if path:
                    child_path = "%s/%s" % (path,child_name)
                else:
                    child_path = child_name

                child_id = self.filename_to_file_id(revision_id, child_path)

                if dirent.kind == svn.core.svn_node_dir:
                    inventry = InventoryDirectory(child_id,child_name,id)
                    recurse.append(child_path)
                elif dirent.kind == svn.core.svn_node_file:
                    inventry = InventoryFile(child_id,child_name,id)
                    inventry.text_sha1 = "FIXME" 
                else:
                    raise BzrError("Unknown entry kind for '%s': %s" % (child_path, dirent.kind))

                # FIXME: shouldn't this be last changed revision?
                inventry.revision = revision_id
                inv.add(inventry)

            for child_path in recurse:
                child_id = self.filename_to_file_id(revision_id, child_path)
                read_directory(inv,child_id,child_path)
    
        inv = Inventory()

        read_directory(inv,ROOT_ID,path)

        return inv

    def filename_from_file_id(self,revision_id,file_id):
        """Generate a Subversion filename from a bzr file id."""
        
        return self.fileid_map[revision_id][file_id]

    def filename_to_file_id(self,revision_id,filename):
        """Generate a bzr file id from a Subversion file name."""
        file_id = filename.replace('/','@')
        if not self.fileid_map.has_key(revision_id):
            self.fileid_map[revision_id] = {}

        (_,revnum) = self.parse_revision_id(revision_id)

        self.fileid_map[revision_id][file_id] = (filename,revnum)
        return file_id

    def all_revision_ids(self):
        raise NotImplementedError()

    def get_inventory_weave(self):
        weave = Weave('inventory','w')
        raise NotImplementedError
        return weave

    def get_ancestry(self, revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)

        self._ancestry = [None]

        def rcvr(paths,rev,author,date,message,pool):
            revid = self.generate_revision_id(rev,path)
            self._ancestry.append(revid)

        mutter("svn log -r 0:%d %s" % (revnum-1,path))
        svn.ra.log(self.ra, [path.encode('utf8')], 0, \
                revnum - 1, 1, False, False, rcvr, 
                self.ra, self.pool)

        return self._ancestry

    def has_revision(self,revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)

        self._found = False

        def rcvr(paths,rev,author,date,message,pool):
            self._found = True

        mutter("svn log -r%d:%d %s" % (revnum,revnum,path))
        svn.ra.log(self.ra, [path.encode('utf8')], revnum, \
                revnum, 1, False, False, rcvr, self.pool)

        return self._found

    def get_revision(self,revision_id):
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id=revision_id,branch=self)

        mutter("retrieving %s" % revision_id)
        (path,revnum) = self.parse_revision_id(revision_id)
        
        mutter('svn proplist -r %r' % revnum)
        svn_props = svn.ra.rev_proplist(self.ra, revnum)

        print svn_props

        parent_ids = []

        def rcvr(paths,rev,*args):
            revid = self.generate_revision_id(rev,path)
            parent_ids.append(revid)

        mutter("log -r%d:0 %s" % (revnum-1,path))
        try:
            svn.ra.get_log(self.ra, [path.encode('utf8')], revnum - 1, \
                0, 1, False, False, rcvr)

        except SubversionException, (_,num):
            if num != 195012:
                raise

        # Commit SVN revision properties to a Revision object
        bzr_props = {}
        rev = Revision(revision_id=revision_id,
                       parent_ids=parent_ids)

        for name in svn_props:
            bzr_props[name] = svn_props[name].decode('utf8')

        rev.timestamp = svn.core.secs_from_timestr(bzr_props[svn.core.SVN_PROP_REVISION_DATE], self.pool) * 1.0
        rev.timezone = None

        rev.committer = bzr_props[svn.core.SVN_PROP_REVISION_AUTHOR]
        rev.message = bzr_props[svn.core.SVN_PROP_REVISION_LOG]

        rev.properties = bzr_props

        rev.inventory_sha1 = "EMPTY"  #FIXME
        
        return rev

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError()

    def fileid_involved_between_revs(self, from_revid, to_revid):
        raise NotImplementedError()

    def fileid_involved(self, last_revid=None):
        raise NotImplementedError()

    def fileid_involved_by_set(self, changes):
        ids = []

        for revid in changes:
            pass #FIXME

        return ids

    def generate_revision_id(self,rev,path):
        return "%d@%s-%s" % (rev,self.uuid,path)

    def parse_revision_id(self,revid):
        assert revid
        assert isinstance(revid, basestring)

        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]

        if uuid != self.uuid:
            raise NoSuchRevision()

        return (revid[fash+1:],int(revid[0:at]))

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(self.get_revision(revision_id))

    def get_revision_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_revision_xml(revision_id))

    def get_revision_graph_with_ghosts(self, revision_id):
        result = Graph()

        #FIXME
        raise NotImplementedError

        return result

    def has_signature_for_revision_id(self, revision_id):
        return False # SVN doesn't store GPG signatures. Perhaps 
                     # store in SVN revision property?

    def get_signature_text(self, revision_id):
        raise NoSuchRevision(self, revision_id) # SVN doesn't store GPG signatures

    def get_revision_graph(self, revision_id):
        if revision_id is None:
            raise NotImplementedError()

        (path,revnum) = self.parse_revision_id(revision_id)

        self._previous = revision_id
        self._ancestry = {}
        
        def rcvr(paths,rev,author,date,message,pool):
            revid = self.generate_revision_id(rev,path)
            self._ancestry[self._previous] = [revid]
            self._previous = revid

        mutter("svn log -r%d:0 %s" % (revnum-1,path))
        svn.ra.get_log(self.ra, [path.encode('utf8')], revnum - 1, \
                0, 0, False, False, rcvr)

        self._ancestry[self._previous] = [None]
        self._ancestry[None] = []

        return self._ancestry

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return True

    def get_physical_lock_status(self):
        return False

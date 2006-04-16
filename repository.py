# Foreign branch support for Subversion
# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.repository import Repository
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.trace import mutter
from bzrlib.revision import Revision
from bzrlib.errors import NoSuchRevision
from bzrlib.versionedfile import VersionedFile
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from libsvn._core import SubversionException
import svn.core
import bzrlib
from branch import auth_baton
from bzrlib.weave import Weave
from cStringIO import StringIO

class SvnFileWeave(VersionedFile):
    def __init__(self,repository,weave_name,access_mode='w'):
        VersionedFile.__init__(self,access_mode)
        self.repository = repository
        self.file = repository.filename_from_file_id(None, weave_name) #FIXME
        assert self.file

    def get_lines(self, version_id):
        assert version_id != None
        
        (path,revnum) = self.repository.parse_revision_id(version_id)

        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_number
        revt.value.number = revnum

        file_url = "%s/%s/%s" % (self.repository.url,path,self.file)

        mutter('svn cat %r' % file_url)

        stream = StringIO()
        svn.client.cat(stream,file_url.encode('utf8'),revt,self.repository.client,self.repository.pool)
        contents = stream.read()
        print contents
        return [contents]

class SvnFileStore(object):
    def __init__(self,repository):
        self.repository = repository

    def get_weave(self,file_id,transaction):
        return SvnFileWeave(self.repository,file_id)

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
        Repository.__init__(self, 'SVN Repository', bzrdir, control_files, _revision_store, control_store, text_store)

        self.pool = svn.core.svn_pool_create(None)

        self.client = svn.client.svn_client_create_context(self.pool)
        self.client.config = svn.core.svn_config_get_config(None)
        self.client.auth_baton = auth_baton

        def rcvr(path,info,pool):
            self.url = info.repos_root_URL
            self.uuid = info.repos_UUID

        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_head

        svn.client.info(url.encode('utf8'), revt, revt, rcvr, False, self.client, self.pool)

        assert self.url
        assert self.uuid

        mutter("Connected to repository at %s, UUID %s" % (self.url, self.uuid))


    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

    def get_inventory(self, revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)
        mutter('getting inventory %r for branch %r' % (revnum, path))

        url = self.url + "/" + path

        mutter("svn ls -r %d '%r'" % (revnum, url))

        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_number
        revt.value.number = revnum

        remote_ls = svn.client.ls(url.encode('utf8'),
                                         revt,
                                         True, # recurse
                                         self.client, 
                                         self.pool)

        # Make sure a directory is always added before its contents
        names = remote_ls.keys()
        names.sort(lambda a,b: len(a) - len(b))

        inv = Inventory()
        for entry in names:
            ri = entry.rfind('/')
            if ri == -1:
                top = entry
                parent = ''
            else:
                top = entry[ri+1:]
                parent = entry[0:ri]

            parent_id = inv.path2id(parent)
            assert not parent_id is None
            
            id = self.filename_to_file_id(revision_id, entry)

            if remote_ls[entry].kind == svn.core.svn_node_dir:
                entry = InventoryDirectory(id,top,parent_id=parent_id)
            elif remote_ls[entry].kind == svn.core.svn_node_file:
                entry = InventoryFile(id,top,parent_id=parent_id)
            else:
                raise BzrError("Unknown entry kind for '%s': %d" % (entry, remote_ls[entry].kind))

            entry.revision = revision_id # FIXME: shouldn't this be last changed revision?
            inv.add(entry)

        return inv

    #FIXME
    def filename_from_file_id(self,revision_id,file_id):
        """Generate a Subversion filename from a bzr file id."""
        return file_id.replace('%','/')

    def filename_to_file_id(self,revision_id,filename):
        """Generate a bzr file id from a Subversion file name."""
        return filename.replace('/','%')

    def all_revision_ids(self):
        raise NotImplementedError()

    def get_inventory_weave(self):
        weave = Weave('inventory','w')
        raise NotImplementedError
        return weave

    def get_ancestry(self, revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)

        url = self.url + "/" + path

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = 0

        revt_peg = svn.core.svn_opt_revision_t()
        revt_peg.kind = svn.core.svn_opt_revision_number
        revt_peg.value.number = revnum

        revt_end = svn.core.svn_opt_revision_t()
        revt_end.kind = svn.core.svn_opt_revision_number
        revt_end.value.number = revnum - 1

        self._ancestry = [None]

        def rcvr(paths,rev,author,date,message,pool):
            revid = "%d@%s-%s" % (rev,self.uuid,path)
            self._ancestry.append(revid)

        mutter("log3 %s" % url)
        svn.client.log3([url.encode('utf8')], revt_peg, revt_begin, \
                revt_end, 1, False, False, rcvr, 
                self.client, self.pool)

        return self._ancestry

    def has_revision(self,revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)

        url = self.url + "/" + path

        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_number
        revt.value.number = revnum

        self._found = False

        def rcvr(paths,rev,author,date,message,pool):
            self._found = True

        mutter("log3 %s" % url)
        svn.client.log3([url.encode('utf8')], revt, revt, \
                revt, 1, False, False, rcvr, 
                self.client, self.pool)

        return self._found

    def get_revision(self,revision_id):
        mutter("retrieving %s" % revision_id)
        (path,revnum) = self.parse_revision_id(revision_id)
        
        url = self.url + "/" + path

        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = revnum
        mutter('svn proplist -r %r %r' % (revnum,url))
        (svn_props, actual_rev) = svn.client.revprop_list(url.encode('utf8'), rev, self.client, self.pool)
        assert actual_rev == revnum

        revt_peg = svn.core.svn_opt_revision_t()
        revt_peg.kind = svn.core.svn_opt_revision_number
        revt_peg.value.number = revnum

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = revnum - 1

        revt_end = svn.core.svn_opt_revision_t()
        revt_end.kind = svn.core.svn_opt_revision_number
        revt_end.value.number = 0

        parent_ids = []

        def rcvr(paths,rev,author,date,message,pool):
            revid = "%d@%s-%s" % (rev,self.uuid,path)
            parent_ids.append(revid)

        mutter("log3 -r%d:0 %s" % (revnum-1,url))
        try:
            svn.client.log3([url.encode('utf8')], revt_peg, revt_begin, \
                revt_end, 1, False, False, rcvr, 
                self.client, self.pool)

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

    def parse_revision_id(self,revid):
        assert isinstance(revid,basestring)
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

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = revnum - 1

        revt_end = svn.core.svn_opt_revision_t()
        revt_end.kind = svn.core.svn_opt_revision_number
        revt_end.value.number = 0

        self._previous = revision_id
        self._ancestry = {}
        
        def rcvr(paths,rev,author,date,message,pool):
            revid = "%d@%s-%s" % (rev,self.uuid,path)
            self._ancestry[self._previous] = [revid]
            self._previous = revid

        url = self.url + "/" + path

        mutter("log3 %s" % (url))
        svn.client.log3([url.encode('utf8')], revt_begin, revt_begin, \
                revt_end, 0, False, False, rcvr, 
                self.client, self.pool)

        self._ancestry[self._previous] = [None]
        self._ancestry[None] = []

        return self._ancestry

# Foreign branch support for Subversion
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

"""Branch support for Subversion repositories

Support for SVN branches has been splitted up into two kinds: 
- RA (remote access) Subversion URLs such as svn+ssh://..., 
    http:// (webdav) or file:/// 
- wc (working copy) local checkouts. These are directories that contain a 
    .svn/ subdirectory)

Subversion always relies on the repository for the history information. Thus,
RA can roughly be mapped to what bzr calls a Branch, and wc to what bzr calls a 
WorkingTree.

Three different identifiers are used in this file to refer to 
revisions:
- revid: bzr revision ids (text data, usually containing email 
    address + sha)
- revno: bzr revision number
- revnum: svn revision number
"""

from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError,NoWorkingTree,NoSuchRevision
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.tree import Tree, EmptyTree
from bzrlib.trace import mutter, note
from bzrlib.workingtree import WorkingTree
import bzrlib

import svn.core, svn.client, svn.wc
import os
from libsvn._core import SubversionException

# Initialize APR (required for all SVN calls)
svn.core.apr_initialize()

global_pool = svn.core.svn_pool_create(None)

def _create_auth_baton(pool):
    # Give the client context baton a suite of authentication
    # providers.
    providers = [
        svn.client.svn_client_get_simple_provider(pool),
        svn.client.svn_client_get_ssl_client_cert_file_provider(pool),
        svn.client.svn_client_get_ssl_client_cert_pw_file_provider(pool),
        svn.client.svn_client_get_ssl_server_trust_file_provider(pool),
        svn.client.svn_client_get_username_provider(pool),
        ]
    return svn.core.svn_auth_open(providers, pool)

auth_baton = _create_auth_baton(global_pool)

class SvnRevisionTree(Tree):
    def __init__(self,branch,revision_id):
        self.branch = branch
        self.revision_id = revision_id
        self.revnum = self.branch.get_revnum(revision_id)
        self._inventory = branch.get_inventory(revision_id)

    def get_file_sha1(self,file_id):
        return bzrlib.osutils.sha_string(self.get_file(file_id))

    def is_executable(self,file_id):
        filename = self.branch.url_from_file_id(self.revision_id,file_id)
        mutter("svn propget %r %r" % (svn.core.SVN_PROP_EXECUTABLE, filename))
        values = svn.client.propget(svn.core.SVN_PROP_EXECUTABLE, filename, self.revnum, False, self.client, self.pool)
        if len(values) == 1 and values.pop() == svn.core.SVN_PROP_EXECUTABLE_VALUE:
            return True
        return False 
    
    def get_file(self,file_id):
        stream = svn.core.svn_stream_empty(self.pool)
        url = self.branch.url_from_file_id(self.revision_id,file_id)
        mutter("svn cat -r %r %r" % (self.revnum.value.number,url))
        svn.client.cat(stream,url.encode('utf8'),self.revnum,self.client,self.pool)
        return Stream(stream).read()

class SvnBranch(Branch):
    @staticmethod
    def open(url):
        # The SVN libraries don't like trailing slashes...
        url = url.rstrip('/')
        if os.path.exists(url):
            url = os.path.abspath(url)
            try:
                return LocalSvnBranch(url)
            except SubversionException, (msg, num):
                if num == svn.core.SVN_ERR_UNVERSIONED_RESOURCE or \
                    num == svn.core.SVN_ERR_WC_NOT_DIRECTORY:
                    raise NotBranchError(path=url)
                raise
        else:
            try:
                return RemoteSvnBranch(url)
            except SubversionException, (msg, num):
                if num == svn.core.SVN_ERR_RA_ILLEGAL_URL or \
                   num == svn.core.SVN_ERR_WC_NOT_DIRECTORY or \
                   num == svn.core.SVN_ERR_RA_NO_REPOS_UUID or \
                   num == svn.core.SVN_ERR_RA_SVN_REPOS_NOT_FOUND or \
                   num == svn.core.SVN_ERR_RA_DAV_REQUEST_FAILED:
                    raise NotBranchError(path=url)
                raise
 
    def __init__(self,base,kind):
        self.pool = svn.core.svn_pool_create(global_pool)
        self.client = svn.client.svn_client_create_context(self.pool)
        self.client.auth_baton = auth_baton
        self.base = base 
        self._get_last_revnum(kind)
        
    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

    #FIXME
    def filename_from_file_id(self,revision_id,file_id):
        """Generate a Subversion filename from a bzr file id."""
        return file_id.replace('_','/')

    def filename_to_file_id(self,revision_id,filename):
        """Generate a bzr file id from a Subversion file name."""
        return filename.replace('/','_')

    def url_from_file_id(self,revision_id,file_id):
        """Generate a full Subversion URL from a bzr file id."""
        return self.base+"/"+self.filename_from_file_id(revision_id,file_id)

    def _get_last_revnum(self,kind):
        # The python bindings for the svn_client_info() function
        # are broken, so this is the only way to (cheaply) find out what the 
        # youngest revision number is
        revt_head = svn.core.svn_opt_revision_t()
        revt_head.kind = kind
        self.last_revnum = None
        def rcvr(paths,rev,author,date,message,pool):
            self.last_revnum = rev
        mutter("svn log -r HEAD %r" % self.base)
        svn.client.log2([self.base.encode('utf8')], revt_head, revt_head, \
                1, 0, 0, rcvr, self.client, self.pool)
        assert self.last_revnum

    def _generate_revnum_map(self):
        #FIXME: Revids should be globally unique, so we should include the 
        # branch path somehow. If we don't do this there might be revisions 
        # that have the same id because they were created in the same commit.
        # This requires finding out the URL of the root of the repository, 
        # but this is not possible at the moment since svn.client.info() does
        # not work.
        self.revid_map = {}
        self.revnum_map = {}
        self._revision_history = []
        for revnum in range(0,self.last_revnum+1):
            revt = svn.core.svn_opt_revision_t()
            revt.kind = svn.core.svn_opt_revision_number
            revt.value.number = revnum
            if revnum == 0:
                revid = None
            else:
                revid = "%d@%s" % (revnum,self.uuid)
                self._revision_history.append(revid)
            self.revid_map[revid] = revt
            self.revnum_map[revnum] = revid

    def get_revnum(self,revid):
        """Map bzr revision id to a SVN revision number."""
        try:
            return self.revid_map[revid]
        except KeyError:
            raise NoSuchRevision(revid,self)

    def set_root_id(self, file_id):
        raise NotImplementedError('set_root_id not supported on Subversion Branches')
            
    @staticmethod
    def open_containing(base):
        # Every directory in a Subversion branch is a directory on itself, 
        # so no need to go down a few levels
        # FIXME: Correction: this is true for directories, not for files...
        return SvnBranch.open(base), ''

    def get_root_id(self):
        inv = self.get_inventory(self.last_revision())
        return inv.root.file_id

    def abspath(self, name):
        return self.base+"/"+name

    def push_stores(self, branch_to):
        raise NotImplementedError('push_stores is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def sign_revision(self, revision_id, gpg_strategy):
        raise NotImplementedError('Subversion revisions can not be signed')

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        raise NotImplementedError('Subversion revisions can not be signed')

    def set_revision_history(self, rev_history):
        raise NotImplementedError('set_revision_history not supported on Subversion branches')

    def set_push_location(self, location):
        raise NotImplementedError('set_push_location not supported on Subversion')

    def get_push_location(self):
        raise NotImplementedError('get_push_location not supported on Subversion')

    def revision_history(self):
        return self._revision_history

    def has_revision(self, revision_id):
        return self.revid_map.has_key(revision_id)

    def print_file(self, file, revno):
        """See Branch.print_file."""
        # For some odd reason this method still takes a revno rather 
        # then a revid
        revnum = self.get_revnum(self.get_rev_id(revno))
        stream = svn.core.svn_stream_empty(self.pool)
        file_url = self.base+"/"+file
        mutter('svn cat -r %r %r' % (revnum.value.number,file_url))
        svn.client.cat(stream,file_url.encode('utf8'),revnum,self.client,self.pool)
        print Stream(stream).read()

    def get_revision(self, revision_id):
        revnum = self.get_revnum(revision_id)
        
        mutter('svn proplist -r %r %r' % (revnum.value.number,self.base))
        (svn_props, actual_rev) = svn.client.revprop_list(self.base.encode('utf8'), revnum, self.client, self.pool)
        assert actual_rev == revnum.value.number

        parent_ids = self.get_parents(revision_id)
    
        # Commit SVN revision properties to a Revision object
        bzr_props = {}
        rev = Revision(revision_id=revision_id,
                       parent_ids=parent_ids)

        for name in svn_props:
            bzr_props[name] = str(svn_props[name])

        rev.timestamp = svn.core.secs_from_timestr(bzr_props[svn.core.SVN_PROP_REVISION_DATE], self.pool) * 1.0
        rev.timezone = None

        rev.committer = bzr_props[svn.core.SVN_PROP_REVISION_AUTHOR]
        rev.message = bzr_props[svn.core.SVN_PROP_REVISION_LOG]

        rev.properties = bzr_props
        rev.inventory_sha1 = self.get_inventory_sha1(revision_id)
        
        return rev

    def get_parents(self, revision_id):
        revnum = self.get_revnum(revision_id)
        parents = []
        if not revision_id is None:
            parent_id = self.revnum_map[revnum.value.number-1]
            if not parent_id is None:
                parents.append(parent_id)
        # FIXME: Figure out if there are any merges here and where they come 
        # from
        return parents

    def get_ancestry(self, revision_id):
        try:
            i = self.revision_history().index(revision_id)
        except ValueError:
            raise NoSuchRevision(revision_id,self)

        # FIXME: Figure out if there are any merges here and where they come 
        # from
        return self.revision_history()[0:i+1]

    def get_inventory(self, revision_id):
        revnum = self.get_revnum(revision_id)
        mutter('getting inventory %r for branch %r' % (revnum.value.number, self.base))

        mutter("svn ls -r %d '%r'" % (revnum.value.number, self.base))
        remote_ls = svn.client.ls(self.base.encode('utf8'),
                                         revnum,
                                         True, # recurse
                                         self.client, self.pool)
        mutter('done')

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
                inv.add(InventoryDirectory(id,top,parent_id=parent_id))
            elif remote_ls[entry].kind == svn.core.svn_node_file:
                inv.add(InventoryFile(id,top,parent_id=parent_id))
            else:
                raise BzrError("Unknown entry kind for '%s': %d" % (entry, remote_ls[entry].kind))

        return inv

    def pull(self, source, overwrite=False):
        print "Pull from %s to %s" % (source,self)
        raise NotImplementedError('pull is abstract') #FIXME

    def update_revisions(self, other, stop_revision=None):
        raise NotImplementedError('update_revisions is abstract') #FIXME

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract') #FIXME
        
    def revision_tree(self, revision_id):
        if revision_id is None or revision_id == NULL_REVISION:
            return EmptyTree()
        
        return SvnRevisionTree(self, revision_id)

    # The remote server handles all this for us
    def lock_write(self):
        pass
        
    def lock_read(self):
        pass

    def unlock(self):
        pass

    def get_parent(self):
        return None

    def set_parent(self, url):
        raise NotImplementedError('can not change parent of SVN branch')

    def get_transaction(self):
        raise NotImplementedError('get_transaction is abstract') #FIXME

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def working_tree(self):
        if self.path is None:
            raise NoWorkingTree(self.base)
        else:
            return SvnWorkingTree(self.path,branch=self)

    # FIXME: perhaps move these four to a 'ForeignBranch' class in 
    # bzr core?
    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(self.get_revision(revision_id))

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(self.get_inventory(revision_id))

    def get_revision_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_revision_xml(revision_id))

    def get_inventory_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_inventory_xml(revision_id))

class RemoteSvnBranch(SvnBranch):
    """Branch representing a remote Subversion repository.  """

    def _get_uid(self):
        mutter("svn uuid '%r'" % self.base)
        uuid = svn.client.uuid_from_url(self.base.encode('utf8'), self.client, self.pool)
        assert uuid
        return uuid
    
    def __init__(self, url):
        SvnBranch.__init__(self,url,svn.core.svn_opt_revision_base)
        self._generate_revnum_map()


class LocalSvnBranch(SvnBranch):
    """Branch representing a local Subversion checkout.  """

    def __init__(self, path):
        SvnBranch.__init__(self,path,svn.core.svn_opt_revision_working)
        self.path = path
        self.base = svn.client.url_from_path(self.path.encode('utf8'),self.pool)
        
        assert self.uuid
        self._generate_revnum_map()

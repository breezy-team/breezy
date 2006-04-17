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
        self._inventory = branch.repository.get_inventory(revision_id)

    def get_file_sha1(self,file_id):
        return bzrlib.osutils.sha_string(self.get_file(file_id))

    def is_executable(self,file_id):
        filename = self.branch.url_from_file_id(self.revision_id,file_id)
        mutter("svn propget %r %r" % (svn.core.SVN_PROP_EXECUTABLE, filename))
        values = svn.client.propget(svn.core.SVN_PROP_EXECUTABLE, filename, self.revnum, False, self.repository.client, self.repository.pool)
        if len(values) == 1 and values.pop() == svn.core.SVN_PROP_EXECUTABLE_VALUE:
            return True
        return False 
    
    def get_file(self,file_id):
        stream = svn.core.svn_stream_empty(self.repository.pool)
        url = self.branch.url_from_file_id(self.revision_id,file_id)
        mutter("svn cat -r %r %r" % (self.revnum.value.number,url))
        svn.repository.client.cat(stream,url.encode('utf8'),self.revnum,self.repository.client,self.repository.pool)
        return Stream(stream).read()

class SvnBranch(Branch):
    def __init__(self,repos,base):
        self.repository = repos

        if not base.startswith(repos.url):
            raise CorruptRepository(repos)

        self.branch_path = base[len(repos.url):].strip("/")
        self.base = base 
        self.base_revt = svn.core.svn_opt_revision_t()
        self.base_revt.kind = svn.core.svn_opt_revision_head
        self.control_files = "FIXME"
        self._generate_revnum_map()
        
    def url_from_file_id(self,revision_id,file_id):
        """Generate a full Subversion URL from a bzr file id."""
        return self.base+"/"+self.filename_from_file_id(revision_id,file_id)

    def _generate_revnum_map(self):
        #FIXME: Revids should be globally unique, so we should include the 
        # branch path somehow. If we don't do this there might be revisions 
        # that have the same id because they were created in the same commit.
        # This requires finding out the URL of the root of the repository, 
        # but this is not possible at the moment since svn.client.info() does
        # not work.
        self._revision_history = []

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = 0

        def rcvr(paths,rev,author,date,message,pool):
            revid = self.repository.generate_revision_id(rev,self.branch_path)
            self._revision_history.append(revid)

        url = "%s/%s" % (self.repository.url, self.branch_path)

        svn.client.log3([url.encode('utf8')], self.base_revt, revt_begin, \
                self.base_revt, 0, False, False, rcvr, 
                self.repository.client, self.repository.pool)
 
    def set_root_id(self, file_id):
        raise NotImplementedError('set_root_id not supported on Subversion Branches')
            
    def get_root_id(self):
        inv = self.repository.get_inventory(self.last_revision())
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
        # get_push_location not supported on Subversion
        return None

    def revision_history(self):
        return self._revision_history

    def has_revision(self, revision_id):
        return self.revision_history().has_key(revision_id)

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

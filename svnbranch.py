# Foreign branch support for Subversion
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL
#
# Support for SVN branches has been splitted up into two kinds: 
# - RA (remote access) Subversion URLs such as svn+ssh://..., http:// (webdav) or file:/// 
# - wc (working copy) local checkouts (directories that contain a .svn/ subdirectory)
# 
# For the latter, a working_tree is available. This WorkingTree will be 
# special (can't use the default bzr one), and is not implemented yet. 
# RA repositories can only be 
# changed by doing a commit and are thus always considered 'remote' in the 
# bzr meaning of the word.

# Three diferrent identifiers are used in this file to refer to 
# revisions:
# - revid: bzr revision ids (text data, usually containing email address + sha)
# - revno: bzr revision number
# - revnum: svn revision number

from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError,NoWorkingTree,NoSuchRevision
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.tree import Tree
from bzrlib.workingtree import WorkingTree

import svn.core, svn.client
import os

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
        self._inventory = branch.get_inventory(revision_id)

    def get_file_sha1(self,file_id):
        return bzrlib.osutils.sha_string(self.get_file_id(file_id))

    def is_executable(self,file_id):
        return False # FIXME: Look up in properties
    
    def get_file(self,file_id):
        return "" # FIXME
        

class SvnBranch(Branch):
    def __init__(self,path_or_url):
        self.pool = svn.core.svn_pool_create(global_pool)
        self.client = svn.client.svn_client_create_context(self.pool)
        self.client.auth_baton = auth_baton
        self.path_or_url = path_or_url

    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

    #FIXME
    def filename_from_file_id(self,revision_id,file_id):
        return file_id.replace('_','/')

    def filename_to_file_id(self,revision_id,filename):
        return filename.replace('/','_')

    def _generate_revnum_map(self):
        #FIXME: Revids should be globally unique, perhaps include hash 
        # of branch path? If we don't do this there might be revisions that 
        # have the same id because they were created in the same commit.
        self.revnum_map = {None: 0}
        for revnum in range(1,self.last_revnum+1):
            revt = svn.core.svn_opt_revision_t()
            revt.kind = svn.core.svn_opt_revision_number
            revt.value.number = revnum
            self.revnum_map["%d@%s" % (revnum,self.uuid)] = revt

    def get_revnum(self,revid):
        """Map bzr revision id to a SVN revision number."""
        try:
            return self.revnum_map[revid]
        except KeyError:
            raise NoSuchRevision(revid,self)
            
    @staticmethod
    def open_containing(base):
        # Every directory in a Subversion branch is a directory on itself, 
        # so no need to go down a few levels
        # FIXME: Correction: this is true for directories, not for files...
        return SvnBranch.open(base), ''

    def abspath(self, name):
        return self.path_or_url+self.sep+self.sep.join("/".split(name))

    def push_stores(self, branch_to):
        raise NotImplementedError('push_stores is abstract') #FIXME

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
        return self.revnum_map.keys()

    def has_revision(self, revision_id):
        return self.revnum_map.has_key(revision_id)

    def print_file(self, file, revno):
        """See Branch.print_file."""
        # For some odd reason this method still takes a revno rather 
        # then a revid
        revnum = self.get_revnum(self.get_rev_id(revno))
        stream = svn.core.svn_stream_for_stdout(self.pool)
        file_url = self.path_or_url+self.sep+file
        svn.client.cat(stream,file_url.encode('utf8'),revnum,self.client,self.pool)

    def get_revision(self, revision_id):
        revnum = self.get_revnum(revision_id)
        
        (svn_props, actual_rev) = svn.client.revprop_list(self.path_or_url.encode('utf8'), revnum, self.client, self.pool)
        assert actual_rev == revnum.value.number
    
        # Commit SVN revision properties to a Revision object
        bzr_props = {}
        rev = Revision(revision_id)
        for name in svn_props:
            val = svn_props[name]
            if name == "svn:date":
                rev.timestamp = svn.core.secs_from_timestr(str(val), self.pool) * 1.0
                rev.timezone = None
            elif name == "svn:author":
                rev.committer = str(val)
            elif name == "svn:log":
                rev.message = str(val)
            else:
                bzr_props[name] = str(val)

        rev.properties = bzr_props
        
        #FIXME: anything else to set?

        return rev

    def get_ancestry(self, revision_id):
        revnum = self.get_revnum(revision_id)
        # FIXME: Figure out if there are any merges here and where they come 
        # from
        return []

    def get_inventory(self, revision_id):
        inv = Inventory()
        revnum = self.get_revnum(revision_id)

        remote_ls = svn.client.svn_client_ls(self.path_or_url.encode('utf8'),
                                         revnum,
                                         1, # recurse
                                         self.client, self.pool)

        # Make sure a directory is always added before its contents
        names = remote_ls.keys()
        names.sort(lambda a,b: len(a) - len(b))
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

    def revision_tree(self, revision_id):
        if revision_id is None or revision_id == NULL_REVISION:
            return EmptyTree()
        
        return SvnRevisionTree(self, revision_id)

    def rename_one(self, from_rel, to_rel):
        # There is no difference between rename and move in SVN
        self.move([from_rel], to_rel)

    # FIXME: perhaps move these two to a 'ForeignBranch' class in 
    # bzr core?
    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(revision_id)

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(revision_id)

    def get_revision_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_revision_xml())

    def get_inventory_sha1(self, revision_id):
        return bzrlib.osutils.sha_string(self.get_inventory_xml())

class RemoteSvnBranch(SvnBranch):
    """Branch representing a remote Subversion repository.

    """
    @staticmethod
    def is_ra(url):
        # FIXME: This needs a more accurate check, and should consider 
        # the methods actually supported by the current SVN library
        url_prefixes = ["svn://","svn+ssh://","http://", "file://"]
        for f in url_prefixes:
            if url.startswith(f):
                return True
        return False
    
    @staticmethod
    def open(url):
        if RemoteSvnBranch.is_ra(url):
            return RemoteSvnBranch(url)

        raise NotBranchError(path=url)

    sep = "/"
    
    def __init__(self, url):
        SvnBranch.__init__(self,url)
        self.url = url
        self.last_revnum = 1000 #FIXME
        # FIXME: Filter out revnums that don't touch this branch?
        self.uuid = svn.client.uuid_from_url(self.url.encode('utf8'), self.client, self.pool)
        assert self.uuid
        self._generate_revnum_map()

    def lock_write(self):
        raise NoWorkingTree(self.url)
        
    def lock_read(self):
        pass

    def unlock(self):
        pass

    def add(self, files, ids=None):
        raise NoWorkingTree(self.url)

    def unknowns(self):
        raise NoWorkingTree(self.url)

    def controlfilename(self, file_or_path):
        raise NoWorkingTree(self.url)

    def controlfile(self, file_or_path, mode='r'):
        raise NoWorkingTree(self.url)

    def put_controlfile(self, path, f, encode=True):
        raise NoWorkingTree(self.url)

    def put_controlfiles(self, files, encode=True):
        raise NoWorkingTree(self.url)

    def move(self, from_paths, to_name):
        raise NoWorkingTree(self.url)

    def get_parent(self):
        return self.url

    def working_tree(self):
        raise NoWorkingTree(self.url)

    def set_parent(self, url):
        raise NoWorkingTree(self.url)

    def get_transaction(self):
        raise NotImplementedError('get_transaction is abstract') #FIXME

    def get_root_id(self):
        raise NotImplementedError('get_root_id is abstract') #FIXME

    def set_root_id(self, file_id):
        raise NotImplementedError('set_root_id is abstract') #FIXME

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def update_revisions(self, other, stop_revision=None):
        raise NotImplementedError('update_revisions is abstract') #FIXME

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract') #FIXME
        
    def pull(self, source, overwrite=False):
        raise NotImplementedError('pull is abstract') #FIXME

class SvnWorkingTree(WorkingTree):
    def __init__(self,path,branch):
        WorkingTree.__init__(self,path,branch)
        self.path = path

    def revert(self,filenames,old_tree=None,backups=True):
        # FIXME: Respect old_tree and backups
        svn.client.revert(filenames,True,self.client,self.pool)

class LocalSvnBranch(SvnBranch):
    """Branch representing a local Subversion checkout.
    
    Most of the methods in here will move to SvnWorkingTree later on, 
    as more of Roberts work on refactoring Branch and WorkingTree enters
    bzr.dev.
    """
    sep = os.path.sep
    
    @staticmethod
    def is_wc(path):
        return os.path.isdir(os.path.join(path, '.svn'))

    @staticmethod
    def open(url):
        if LocalSvnBranch.is_wc(url):
            return LocalSvnBranch(url)

        raise NotBranchError(path=url)
    
    def get_parent(self):
        return self.path

    def working_tree(self):
        return SvnWorkingTree(self.path,branch=self)

    def __init__(self, path):
        SvnBranch.__init__(self,path)
        self.path = path
        self.url = svn.client.url_from_path(self.path.encode('utf8'),self.pool)
        self.uuid = svn.client.uuid_from_path(self.path.encode('utf8'), None, self.client, self.pool)
        assert self.uuid
        self.last_revnum = 1000 #FIXME
        self._generate_revnum_map()

    def unknowns(self):
        return self.working_tree().unknowns()

    def get_transaction(self):
        raise NotImplementedError('get_transaction is abstract') #FIXME

    def lock_write(self):
        raise NotImplementedError('lock_write is abstract') #FIXME
        
    def lock_read(self):
        raise NotImplementedError('lock_read is abstract') #FIXME

    def unlock(self):
        raise NotImplementedError('unlock is abstract') #FIXME

    def controlfilename(self, file_or_path):
        raise NotImplementedError('controlfilename is abstract') #FIXME

    def controlfile(self, file_or_path, mode='r'):
        raise NotImplementedError('controlfile is abstract') #FIXME

    def put_controlfile(self, path, f, encode=True):
        raise NotImplementedError('put_controlfile is abstract') #FIXME

    def put_controlfiles(self, files, encode=True):
        raise NotImplementedError('put_controlfiles is abstract') #FIXME

    def get_root_id(self):
        raise NotImplementedError('get_root_id is abstract') #FIXME

    def set_root_id(self, file_id):
        raise NotImplementedError('set_root_id is abstract') #FIXME

    def add(self, files, ids=None):
        for f in files:
            svn.client.add(f, False, self.client, self.pool)
            if ids:
                id = ids.pop()
                if id:
                    svn.client.propset('bzr:id', id, f, False, self.pool)

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def update_revisions(self, other, stop_revision=None):
        raise NotImplementedError('update_revisions is abstract') #FIXME

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract') #FIXME
        
    def pull(self, source, overwrite=False):
        raise NotImplementedError('pull is abstract') #FIXME

    def move(self, from_paths, to_name):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        for entry in from_paths:
            svn.client.move(entry, revt, to_name, False, self.client, self.pool)

    def set_parent(self, url):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_head
        self.last_revnum = svn.client.switch(self.path, url, revt, True, self.client, self.pool)
        self.url = url
        self._generate_revnum_map()

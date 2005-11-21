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
from bzrlib.errors import (NotBranchError,NoWorkingTree,NoSuchRevision)
from bzrlib.inventory import Inventory
from bzrlib.revision import Revision

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

class SvnBranch(Branch):
    def __init__(self,path_or_url):
        self.pool = svn.core.svn_pool_create(global_pool)
        self.client = svn.client.svn_client_create_context(self.pool)
        self.client.auth_baton = auth_baton
        self.path_or_url = path_or_url

    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

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

    def push_stores(self, branch_to):
        raise NotImplementedError('push_stores is abstract') #FIXME

    def sign_revision(self, revision_id, gpg_strategy):
        raise NotImplementedError('Subversion revisions can not be signed')

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        raise NotImplementedError('Subversion revisions can not be signed')

    def set_revision_history(self, rev_history):
        raise NotImplementedError('set_revision_history not supported on Subversion branches')

    def revision_history(self):
        return self.revnum_map.keys()

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

    # FIXME: perhaps move these two to a 'ForeignBranch' class in 
    # bzr core?
    def get_revision_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_revision_to_string(revision_id)

    def get_inventory_xml(self, revision_id):
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(revision_id)

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
        raise NoWorkingTree(self.base)
        
    def lock_read(self):
        pass

    def unlock(self):
        pass

    def add(self, files, ids=None):
        raise NoWorkingTree(self.base)

    def unknowns(self):
        raise NoWorkingTree(self.base)

    def controlfilename(self, file_or_path):
        raise NoWorkingTree(self.base)

    def controlfile(self, file_or_path, mode='r'):
        raise NoWorkingTree(self.base)

    def put_controlfile(self, path, f, encode=True):
        raise NoWorkingTree(self.base)

    def put_controlfiles(self, files, encode=True):
        raise NoWorkingTree(self.base)

    def rename_one(self, from_rel, to_rel):
        raise NoWorkingTree(self.base)

    def move(self, from_paths, to_name):
        raise NoWorkingTree(self.base)

    def get_parent(self):
        return self.base

    def working_tree(self):
        raise NoWorkingTree(self.base)

    def set_push_location(self, location):
        raise NoWorkingTree(self.base)

    def set_parent(self, url):
        raise NoWorkingTree(self.base)

    def get_push_location(self):
        raise NotImplementedError('get_push_location not supported on remote Subversion branches')

    def get_transaction(self):
        raise NotImplementedError('get_transaction is abstract') #FIXME

    def abspath(self, name):
        raise NotImplementedError('abspath is abstract') #FIXME

    def get_root_id(self):
        raise NotImplementedError('get_root_id is abstract') #FIXME

    def set_root_id(self, file_id):
        raise NotImplementedError('set_root_id is abstract') #FIXME

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def has_revision(self, revision_id):
        raise NotImplementedError('has_revision is abstract') #FIXME

    def get_revision_sha1(self, revision_id):
        raise NotImplementedError('get_revision_sha1 is abstract') #FIXME

    def get_ancestry(self, revision_id):
        revnum = self.get_revnum(revision_id)
        # FIXME: Figure out if there are any merges here and where they come 
        # from
        return []

    def get_inventory(self, revision_id):
        inv = Inventory()
        revnum = self.get_revnum(revision_id)

        remote_ls = svn.client.svn_client_ls(self.url,
                                         revnum,
                                         1, # recurse
                                         self.client, self.pool)

        print remote_ls

        print "get_inventory(%d)" % revnum.value.number
        raise NotImplementedError('get_inventory is abstract') #FIXME

    def get_inventory_sha1(self, revision_id):
        raise NotImplementedError('get_inventory_sha1 is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def update_revisions(self, other, stop_revision=None):
        raise NotImplementedError('update_revisions is abstract') #FIXME

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract') #FIXME
        
    def revision_tree(self, revision_id):
        raise NotImplementedError('revision_tree is abstract') #FIXME

    def pull(self, source, overwrite=False):
        raise NotImplementedError('pull is abstract') #FIXME


class LocalSvnBranch(SvnBranch):
    """Branch representing a local Subversion checkout.

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
        return self.base

    def working_tree(self):
        return WorkingTree(self.base,branch=self)

    def __init__(self, path):
        SvnBranch.__init__(self,path)
        self.path = path
        self.url = svn.client.url_from_path(self.path.encode('utf8'),self.pool)
        self.uuid = svn.client.uuid_from_path(self.path.encode('utf8'), None, self.client, self.pool)
        assert self.uuid
        self.last_revnum = 1000 #FIXME
        self._generate_revnum_map()

    def get_transaction(self):
        raise NotImplementedError('get_transaction is abstract') #FIXME

    def lock_write(self):
        raise NotImplementedError('lock_write is abstract') #FIXME
        
    def lock_read(self):
        raise NotImplementedError('lock_read is abstract') #FIXME

    def unlock(self):
        raise NotImplementedError('unlock is abstract') #FIXME

    def abspath(self, name):
        raise NotImplementedError('abspath is abstract') #FIXME

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
        raise NotImplementedError('add is abstract') #FIXME

    def unknowns(self):
        raise NotImplementedError('add is abstract') #FIXME

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def has_revision(self, revision_id):
        raise NotImplementedError('has_revision is abstract') #FIXME

    def get_revision_xml_file(self, revision_id):
        raise NotImplementedError('get_revision_xml_file is abstract') #FIXME

    def get_revision(self, revision_id):
        raise NotImplementedError('get_revision is abstract') #FIXME

    def get_revision_sha1(self, revision_id):
        raise NotImplementedError('get_revision_sha1 is abstract') #FIXME

    def get_ancestry(self, revision_id):
        raise NotImplementedError('get_ancestry is abstract') #FIXME

    def get_inventory(self, revision_id):
        raise NotImplementedError('get_inventory is abstract') #FIXME

    def get_inventory_sha1(self, revision_id):
        raise NotImplementedError('get_inventory_sha1 is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def update_revisions(self, other, stop_revision=None):
        raise NotImplementedError('update_revisions is abstract') #FIXME

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract') #FIXME
        
    def revision_tree(self, revision_id):
        raise NotImplementedError('revision_tree is abstract') #FIXME

    def pull(self, source, overwrite=False):
        raise NotImplementedError('pull is abstract') #FIXME

    def rename_one(self, from_rel, to_rel):
        raise NotImplementedError('rename_one is abstract') #FIXME

    def move(self, from_paths, to_name):
        raise NotImplementedError('move is abstract') #FIXME

    def get_push_location(self):
        raise NotImplementedError('get_push_location is abstract') #FIXME

    def set_push_location(self, location):
        raise NotImplementedError('set_push_location is abstract') #FIXME

    def set_parent(self, url):
        # svn switch --relocate
        raise NotImplementedError('set_parent is abstract') #FIXME

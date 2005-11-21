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

from bzrlib.branch import Branch
from bzrlib.errors import (NotBranchError,NoWorkingTree)

import svn.core, svn.client

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
    def __init__(self):
        self.pool = svn.core.svn_pool_create(global_pool)
        self.client_ctx = svn.client.svn_client_create_context(self.pool)
        self.client_ctx.auth_baton = auth_baton

    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)
    
    @staticmethod
    def open_containing(base):
        # Every directory in a Subversion branch is a directory on itself, 
        # so no need to go down a few levels
        return SvnBranch.open(base), '.'
        
    @staticmethod
    def is_url(url):
        url_prefixes = ["svn://","svn+ssh://","http://"]
        for f in url_prefixes:
            if url.startswith(f):
                return True
        return False
    
    @staticmethod
    def open(url):
        if SvnBranch.is_url(url):
            return RemoteSvnBranch(url)
        raise NotBranchError(path=url)

    def push_stores(self, branch_to):
        raise NotImplementedError('push_stores is abstract') #FIXME

    def sign_revision(self, revision_id, gpg_strategy):
        raise NotImplementedError('Subversion revisions can not be signed')

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        raise NotImplementedError('Subversion revisions can not be signed')

    def set_revision_history(self, rev_history):
        raise NotImplementedError('set_revision_history not supported on Subversion branches')

class RemoteSvnBranch(SvnBranch):
    """Branch representing a remote Subversion repository.

    """
    def __init__(self, url):
        SvnBranch.__init__(self)
        self.url = url
        self.uuid = svn.client.uuid_from_url(self.url.encode('utf8'), self.client_ctx, self.pool)
        assert self.uuid

    def lock_write(self):
        raise NoWorkingTree(self.base)
        
    def lock_read(self):
        raise NoWorkingTree(self.base)

    def unlock(self):
        raise NoWorkingTree(self.base)

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

    def print_file(self, file, revno):
        # svn cat ...
        raise NotImplementedError('print_file is abstract') #FIXME

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def has_revision(self, revision_id):
        raise NotImplementedError('has_revision is abstract') #FIXME

    def get_revision_xml_file(self, revision_id):
        raise NotImplementedError('get_revision_xml_file is abstract') #FIXME

    def get_revision_xml(self, revision_id):
        raise NotImplementedError('get_revision_xml is abstract') #FIXME

    def get_revision(self, revision_id):
        raise NotImplementedError('get_revision is abstract') #FIXME

    def get_revision_sha1(self, revision_id):
        raise NotImplementedError('get_revision_sha1 is abstract') #FIXME

    def get_ancestry(self, revision_id):
        raise NotImplementedError('get_ancestry is abstract') #FIXME

    def get_inventory(self, revision_id):
        raise NotImplementedError('get_inventory is abstract') #FIXME

    def get_inventory_xml(self, revision_id):
        raise NotImplementedError('get_inventory_xml is abstract') #FIXME

    def get_inventory_sha1(self, revision_id):
        raise NotImplementedError('get_inventory_sha1 is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def revision_history(self):
        raise NotImplementedError('revision_history is abstract') #FIXME

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
    def get_parent(self):
        return self.base

    def working_tree(self):
        return WorkingTree(self.base,branch=self)

    def __init__(self):
        pass

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

    def print_file(self, file, revno):
        # svn cat ...
        raise NotImplementedError('print_file is abstract') #FIXME

    def unknowns(self):
        raise self.working_tree().unknowns()

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract') #FIXME

    def has_revision(self, revision_id):
        raise NotImplementedError('has_revision is abstract') #FIXME

    def get_revision_xml_file(self, revision_id):
        raise NotImplementedError('get_revision_xml_file is abstract') #FIXME

    def get_revision_xml(self, revision_id):
        raise NotImplementedError('get_revision_xml is abstract') #FIXME

    def get_revision(self, revision_id):
        raise NotImplementedError('get_revision is abstract') #FIXME

    def get_revision_sha1(self, revision_id):
        raise NotImplementedError('get_revision_sha1 is abstract') #FIXME

    def get_ancestry(self, revision_id):
        raise NotImplementedError('get_ancestry is abstract') #FIXME

    def get_inventory(self, revision_id):
        raise NotImplementedError('get_inventory is abstract') #FIXME

    def get_inventory_xml(self, revision_id):
        raise NotImplementedError('get_inventory_xml is abstract') #FIXME

    def get_inventory_sha1(self, revision_id):
        raise NotImplementedError('get_inventory_sha1 is abstract') #FIXME

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError('get_revision_inventory is abstract') #FIXME

    def revision_history(self):
        raise NotImplementedError('revision_history is abstract') #FIXME

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


#!/usr/bin/env python2.4

import svn.core, svn.client

def my_svn(pool):

    print svn.client.svn_client_version().minor

    url = 'http://ctrlproxy.vernstok.nl/svn'

    revision = svn.core.svn_opt_revision_t()
    revision.kind = svn.core.svn_opt_revision_head

    remote_ls = svn.client.svn_client_ls(url,
                                         revision,
                                         0,
                                         client_ctx, pool)

    print remote_ls

    print svn.client.uuid_from_url(url, client_ctx, pool)
    #svn.client.checkout('http://ctrlproxy.vernstok.nl/svn/', 'bloe', None, 1, ctx, pool)

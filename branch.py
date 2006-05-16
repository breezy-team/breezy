# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.branch import Branch, BranchFormat
from bzrlib.errors import NotBranchError,NoWorkingTree,NoSuchRevision
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.tree import Tree, EmptyTree
from bzrlib.trace import mutter, note
from bzrlib.workingtree import WorkingTree
from bzrlib.delta import compare_trees
import bzrlib

import svn.core, svn.wc, svn.ra
import os
from libsvn._core import SubversionException

svn.ra.initialize()

_global_pool = svn.core.svn_pool_create(None)

def _create_auth_baton(pool):
    import svn.client
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

auth_baton = _create_auth_baton(_global_pool)

class SvnRevisionTree(Tree):
    def __init__(self,branch,revision_id):
        self.branch = branch
        self.revision_id = revision_id
        self.revnum = self.branch.get_revnum(revision_id)
        self._inventory = branch.repository.get_inventory(revision_id)

    def get_file_sha1(self,file_id):
        return bzrlib.osutils.sha_string(self.get_file(file_id))

    def is_executable(self,file_id):
        filename = self.branch.path_from_file_id(self.revision_id,file_id)
        mutter("svn propget %r %r" % (svn.core.SVN_PROP_EXECUTABLE, filename))
        values = svn.ra.propget(svn.core.SVN_PROP_EXECUTABLE, filename, self.revnum, False, self.repository.ra)
        if len(values) == 1 and values.pop() == svn.core.SVN_PROP_EXECUTABLE_VALUE:
            return True
        return False 
    
    def get_symlink_target(self,file_id):
        data = self.get_file(file_id)
        if not data.startswith("link "):
            raise BzrError("Improperly formatted symlink file")
        return data[len("link "):]
   
    def get_file(self,file_id):
        stream = svn.core.svn_stream_empty(self.repository.pool)
        path = self.branch.path_from_file_id(self.revision_id,file_id)
        mutter("svn cat -r %r %r" % (self.revnum.value.number,path))
        svn.repository.ra.get_file(stream,path.encode('utf8'),self.revnum,self.repository.ra,self.repository.pool)
        return Stream(stream).read()

class SvnBranch(Branch):
    def __init__(self,repos,branch_path):
        self.repository = repos
        self.branch_path = branch_path
        self.base_revnum = svn.ra.get_latest_revnum(self.repository.ra)
        self.control_files = "FIXME"
        self._generate_revnum_map()
        self.base = "%s/%s" % (repos.url, branch_path)
        self._format = SvnBranchFormat()
        mutter("Connected to branch at %s" % branch_path)
        
    def path_from_file_id(self,revision_id,file_id):
        """Generate a full Subversion path from a bzr file id."""
        return self.base+"/"+self.filename_from_file_id(revision_id,file_id)

    def _generate_revnum_map(self):
        #FIXME: Revids should be globally unique, so we should include the 
        # branch path somehow. If we don't do this there might be revisions 
        # that have the same id because they were created in the same commit.
        self._revision_history = []

        def rcvr(paths,rev,author,date,message,pool):
            revid = self.repository.generate_revision_id(rev,self.branch_path)
            self._revision_history.append(revid)

        svn.ra.get_log(self.repository.ra, [self.branch_path.encode('utf8')], 0, \
                self.base_revnum, \
                0, False, False, rcvr, 
                self.repository.pool)

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

    def get_physical_lock_status(self):
        return False

    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """

        assert isinstance(revno, int)
        rh = self.revision_history()
        if not (1 <= revno <= len(rh)):
            raise InvalidRevisionNumber(revno)

        # revno is 1-based; list is 0-based

        new_tree = self.repository.revision_tree(rh[revno-1])
        if revno == 1:
            old_tree = EmptyTree()
        else:
            old_tree = self.repository.revision_tree(rh[revno-2])
        return compare_trees(old_tree, new_tree)

    def sprout(self, to_bzrdir, revision_id=None):
        result = BranchFormat.get_default_format().initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        result.set_parent(self.bzrdir.root_transport.base)
        return result

    def copy_content_into(self, destination, revision_id=None):
        new_history = self.revision_history()
        if revision_id is not None:
            try:
                new_history = new_history[:new_history.index(revision_id) + 1]
            except ValueError:
                rev = self.repository.get_revision(revision_id)
                new_history = rev.get_history(self.repository)[1:]
        destination.set_revision_history(new_history)
        parent = self.get_parent()
        if parent:
            destination.set_parent(parent)

class SvnBranchFormat(BranchFormat):
    def __init__(self):
        BranchFormat.__init__(self)

    def get_format_description(self):
        return 'Subversion Smart Server'

    def initialize(self,to_bzrdir):
        raise NotImplementedError(self.initialize)


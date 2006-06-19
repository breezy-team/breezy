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

from bzrlib.branch import Branch, BranchFormat, BranchCheckResult, BzrBranch
from bzrlib.errors import NotBranchError, NoWorkingTree, NoSuchRevision, \
        NoSuchFile
from bzrlib.inventory import Inventory, InventoryFile, InventoryDirectory, \
            ROOT_ID
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.tree import Tree, EmptyTree
from bzrlib.trace import mutter, note
from bzrlib.workingtree import WorkingTree
from bzrlib.delta import compare_trees
import bzrlib

import svn.core, svn.ra
import os
from libsvn.core import SubversionException


svn.ra.initialize()

_global_pool = svn.core.svn_pool_create(None)

class FakeControlFiles(object):
    def get_utf8(self, name):
        raise NoSuchFile(name)


class SvnBranch(Branch):
    """Maps to a Branch in a Subversion repository """
    def __init__(self, repos, branch_path):
        self.repository = repos
        self.branch_path = branch_path
        self.base_revnum = svn.ra.get_latest_revnum(self.repository.ra)
        self.control_files = FakeControlFiles()
        self._generate_revnum_map()
        self.base = "%s/%s" % (repos.url, branch_path)
        self._format = SvnBranchFormat()
        mutter("Connected to branch at %s" % branch_path)

    def check(self):
        return BranchCheckResult(self)
        
    def path_from_file_id(self, revision_id, file_id):
        """Generate a full Subversion path from a bzr file id.
        
        :param revision_id: 
        :param file_id: 
        :return: Subversion 
        """
        return self.base+"/"+self.filename_from_file_id(revision_id, file_id)

    def _generate_revnum_map(self):
        self._revision_history = []

        def rcvr(paths, rev, author, date, message, pool):
            revid = self.repository.generate_revision_id(rev, self.branch_path)
            self._revision_history.append(revid)

        self.repository._get_log([self.branch_path.encode('utf8')], 
                       0, self.base_revnum, 0, False, False, rcvr)

    def set_root_id(self, file_id):
        raise NotImplementedError(self.set_root_id)
            
    def get_root_id(self):
        inv = self.repository.get_inventory(self.last_revision())
        return inv.root.file_id

    def _get_nick(self):
        return self.branch_path

    nick = property(_get_nick)

    def abspath(self, name):
        return self.base+"/"+name

    def push_stores(self, branch_to):
        raise NotImplementedError(self.push_stores)

    def get_revision_inventory(self, revision_id):
        raise NotImplementedError(self.get_revision_inventory)

    def sign_revision(self, revision_id, gpg_strategy):
        raise NotImplementedError(self.sign_revision)

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        raise NotImplementedError(self.store_revision_signature)

    def set_revision_history(self, rev_history):
        raise NotImplementedError(self.set_revision_history)

    def set_push_location(self, location):
        raise NotImplementedError(self.set_push_location)

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
            raise NoSuchRevision(revision_id, self)

        # FIXME: Figure out if there are any merges here and where they come 
        # from
        return self.revision_history()[0:i+1]

    def pull(self, source, overwrite=False):
        raise NotImplementedError(self.pull)

    def update_revisions(self, other, stop_revision=None):
        raise NotImplementedError(self.update_revisions)

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError(self.pullable_revisions)
        
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
        raise NotImplementedError(self.set_parent, 
                                  'can not change parent of SVN branch')

    def get_transaction(self):
        raise NotImplementedError(self.get_transaction)

    def append_revision(self, *revision_ids):
        # FIXME: raise NotImplementedError(self.append_revision)
        pass

    def get_physical_lock_status(self):
        return False

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

    def submit(self, from_branch, stop_revision):
        if stop_revision is None:
            stop_revision = from_branch.last_revision()

        revisions = self.missing_revisions(from_branch, \
                from_branch.revision_id_to_revno(stop_revision))

        for revid in revisions:
            rev = from_branch.repository.get_revision(revid)
            self.commit(rev.message)

        print revisions


class SvnBranchFormat(BranchFormat):
    """ Branch format for Subversion Branches."""
    def __init__(self):
        BranchFormat.__init__(self)

    def get_format_description(self):
        """See Branch.get_format_description."""
        return 'Subversion Smart Server'

    def get_format_string(self):
        return 'Subversion Smart Server'

    def initialize(self, to_bzrdir):
        raise NotImplementedError(self.initialize)


# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.branch import Branch, BranchFormat, BranchCheckResult, PullResult
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoSuchFile, DivergedBranches
from bzrlib.inventory import (Inventory)
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

import svn.client, svn.core

from commit import push_as_merged
from repository import SvnRepository
from transport import bzr_to_svn_url, svn_config


class FakeControlFiles(object):
    """Dummy implementation of ControlFiles.
    
    This is required as some code relies on controlfiles being 
    available."""
    def get_utf8(self, name):
        raise NoSuchFile(name)

    def get(self, name):
        raise NoSuchFile(name)

    def break_lock(self):
        pass


class SvnBranch(Branch):
    """Maps to a Branch in a Subversion repository """
    def __init__(self, base, repository, branch_path):
        """Instantiate a new SvnBranch.

        :param repos: SvnRepository this branch is part of.
        :param branch_path: Relative path inside the repository this
            branch is located at.
        """
        super(SvnBranch, self).__init__()
        self.repository = repository
        assert isinstance(self.repository, SvnRepository)
        self.branch_path = branch_path
        self.control_files = FakeControlFiles()
        self.base = base.rstrip("/")
        self._format = SvnBranchFormat()
        self._revision_history = None

    def check(self):
        """See Branch.Check.

        Doesn't do anything for Subversion repositories at the moment (yet).
        """
        return BranchCheckResult(self)

    def _create_heavyweight_checkout(self, to_location, revision_id=None):
        checkout_branch = BzrDir.create_branch_convenience(
            to_location, force_new_tree=False)
        checkout = checkout_branch.bzrdir
        checkout_branch.bind(self)
        # pull up to the specified revision_id to set the initial 
        # branch tip correctly, and seed it with history.
        checkout_branch.pull(self, stop_revision=revision_id)
        return checkout.create_workingtree(revision_id)

    def _create_lightweight_checkout(self, to_location, revision_id=None):
        peg_rev = svn.core.svn_opt_revision_t()
        peg_rev.kind = svn.core.svn_opt_revision_head

        rev = svn.core.svn_opt_revision_t()
        if revision_id is None:
            rev.kind = svn.core.svn_opt_revision_head
        else:
            assert revision_id in self.revision_history()
            (_, revnum) = self.repository.parse_revision_id(revision_id)
            rev.kind = svn.core.svn_opt_revision_number
            rev.value.number = revnum
            mutter('hist: %r' % self.revision_history())

        client_ctx = svn.client.create_context()
        client_ctx.config = svn_config
        svn.client.checkout(bzr_to_svn_url(self.base), to_location, rev, 
                            True, client_ctx)

        return WorkingTree.open(to_location)

    def create_checkout(self, to_location, revision_id=None, lightweight=False):
        if lightweight:
            return self._create_lightweight_checkout(to_location, revision_id)
        else:
            return self._create_heavyweight_checkout(to_location, revision_id)

    def generate_revision_id(self, revnum):
        return self.repository.generate_revision_id(revnum, self.branch_path)
       
    def _generate_revision_history(self, last_revnum):
        self._revision_history = []
        for (branch, rev) in self.repository.follow_branch(
                self.branch_path, last_revnum):
            self._revision_history.append(
                    self.repository.generate_revision_id(rev, branch))
        self._revision_history.reverse()

    def get_root_id(self):
        if self.last_revision() is None:
            inv = Inventory()
        else:
            inv = self.repository.get_inventory(self.last_revision())
        return inv.root.file_id

    def _get_nick(self):
        bp = self.branch_path.strip("/")
        if self.branch_path == "":
            return None
        return bp

    nick = property(_get_nick)

    def set_revision_history(self, rev_history):
        raise NotImplementedError(self.set_revision_history)

    def set_last_revision_info(self, revno, revid):
        pass

    def set_push_location(self, location):
        raise NotImplementedError(self.set_push_location)

    def get_push_location(self):
        # get_push_location not supported on Subversion
        return None

    def revision_history(self):
        if self._revision_history is None:
            self._generate_revision_history(self.repository._latest_revnum)
        return self._revision_history

    def last_revision(self):
        # Shortcut for finding the tip. This avoids expensive generation time
        # on large branches.
        if self._revision_history is None:
            for (branch, rev) in self.repository.follow_branch(
                self.branch_path, self.repository._latest_revnum):
                return self.repository.generate_revision_id(rev, branch)
            return None

        ph = self.revision_history()
        if ph:
            return ph[-1]
        else:
            return None

    def pull(self, source, overwrite=False, stop_revision=None):
        result = PullResult()
        result.source_branch = source
        result.master_branch = None
        result.target_branch = self
        source.lock_read()
        try:
            (result.old_revno, result.old_revid) = self.last_revision_info()
            try:
                self.update_revisions(source, stop_revision)
            except DivergedBranches:
                if overwrite:
                    raise NotImplementedError('overwrite not supported for '
                                              'Subversion branches')
                raise
            (result.new_revno, result.new_revid) = self.last_revision_info()
            return result
        finally:
            source.unlock()

    def generate_revision_history(self, revision_id, last_rev=None, 
        other_branch=None):
        """Create a new revision history that will finish with revision_id.
        
        :param revision_id: the new tip to use.
        :param last_rev: The previous last_revision. If not None, then this
            must be a ancestory of revision_id, or DivergedBranches is raised.
        :param other_branch: The other branch that DivergedBranches should
            raise with respect to.
        """
        # stop_revision must be a descendant of last_revision
        # make a new revision history from the graph

    def update_revisions(self, other, stop_revision=None):
        if isinstance(other, SvnBranch):
            if (self.last_revision() == stop_revision or
                self.last_revision() == other.last_revision()):
                return
            # Import from another Subversion branch
            assert other.repository.uuid == self.repository.uuid, \
                    "can only import from elsewhere in the same repository."

            # FIXME: Make sure branches haven't diverged
            # FIXME: svn.ra.del_dir(self.base_path)
            # FIXME: svn.ra.copy_dir(other.base_path, self.base_path)
            raise NotImplementedError(self.pull)
        else:
            for rev_id in self.missing_revisions(other, stop_revision):
                mutter('pushing %r to Svn branch' % rev_id)
                push_as_merged(self, other, rev_id)

    # The remote server handles all this for us
    def lock_write(self):
        pass
        
    def lock_read(self):
        pass

    def unlock(self):
        pass

    def get_parent(self):
        return self.base

    def set_parent(self, url):
        pass # FIXME: Use svn.client.switch()

    def append_revision(self, *revision_ids):
        #raise NotImplementedError(self.append_revision)
        pass

    def get_physical_lock_status(self):
        return False

    def sprout(self, to_bzrdir, revision_id=None):
        result = BranchFormat.get_default_format().initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
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

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

    __repr__ = __str__



class SvnBranchFormat(BranchFormat):
    """Branch format for Subversion Branches."""
    def __init__(self):
        BranchFormat.__init__(self)

    def get_format_description(self):
        """See Branch.get_format_description."""
        return 'Subversion Smart Server'

    def get_format_string(self):
        return 'Subversion Smart Server'

    def initialize(self, to_bzrdir):
        raise NotImplementedError(self.initialize)


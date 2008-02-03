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
"""Handles branch-specific operations."""

from bzrlib import ui
from bzrlib.branch import Branch, BranchFormat, BranchCheckResult, PullResult
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import (NoSuchFile, DivergedBranches, NoSuchRevision, 
                           NotBranchError)
from bzrlib.inventory import (Inventory)
from bzrlib.revision import ensure_null
from bzrlib.workingtree import WorkingTree

import svn.client, svn.core
from svn.core import SubversionException, Pool

from commit import push
from errors import NotSvnBranchPath
from format import get_rich_root_format
from repository import SvnRepository
from transport import bzr_to_svn_url, create_svn_client


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
        :param revnum: Subversion revision number of the branch to 
            look at; none for latest.
        """
        super(SvnBranch, self).__init__()
        self.repository = repository
        assert isinstance(self.repository, SvnRepository)
        self.control_files = FakeControlFiles()
        self.base = base.rstrip("/")
        self._format = SvnBranchFormat()
        self._lock_mode = None
        self._lock_count = 0
        self._cached_revnum = None
        self._revision_history = None
        self._revision_history_revnum = None
        self.mapping = self.repository.get_mapping()
        self._branch_path = branch_path.strip("/")
        try:
            if self.repository.transport.check_path(branch_path.strip("/"), 
                self.get_revnum()) != svn.core.svn_node_dir:
                raise NotBranchError(self.base)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NotBranchError(self.base)
            raise
        if not self.mapping.is_branch(branch_path):
            raise NotSvnBranchPath(branch_path, scheme=self.mapping.scheme)

    def set_branch_path(self, branch_path):
        """Change the branch path for this branch.

        :param branch_path: New branch path.
        """
        self._branch_path = branch_path.strip("/")

    def unprefix(self, relpath):
        """Remove the branch path from a relpath.

        :param relpath: path from the repository root.
        """
        assert relpath.startswith(self.get_branch_path())
        return relpath[len(self.get_branch_path()):].strip("/")

    def get_branch_path(self, revnum=None):
        """Find the branch path of this branch in the specified revnum.

        :param revnum: Revnum to look for.
        """
        if revnum is None:
            return self._branch_path

        # TODO: Use revnum - this branch may have been moved in the past 
        return self._branch_path

    def get_revnum(self):
        """Obtain the Subversion revision number this branch was 
        last changed in.

        :return: Revision number
        """
        if self._lock_mode == 'r' and self._cached_revnum:
            return self._cached_revnum
        self._cached_revnum = self.repository.transport.get_latest_revnum()
        return self._cached_revnum

    def check(self):
        """See Branch.Check.

        Doesn't do anything for Subversion repositories at the moment (yet).
        """
        return BranchCheckResult(self)

    def _create_heavyweight_checkout(self, to_location, revision_id=None):
        """Create a new heavyweight checkout of this branch.

        :param to_location: URL of location to create the new checkout in.
        :param revision_id: Revision that should be the tip of the checkout.
        :return: WorkingTree object of checkout.
        """
        checkout_branch = BzrDir.create_branch_convenience(
            to_location, force_new_tree=False, format=get_rich_root_format())
        checkout = checkout_branch.bzrdir
        checkout_branch.bind(self)
        # pull up to the specified revision_id to set the initial 
        # branch tip correctly, and seed it with history.
        checkout_branch.pull(self, stop_revision=revision_id)
        return checkout.create_workingtree(revision_id)

    def lookup_revision_id(self, revid):
        """Look up the matching Subversion revision number on the mainline of 
        the branch.

        :param revid: Revision id to look up.
        :return: Revision number on the branch. 
        :raises NoSuchRevision: If the revision id was not found.
        """
        (bp, revnum, mapping) = self.repository.lookup_revision_id(revid, 
                                                             scheme=self.mapping.scheme)
        assert bp.strip("/") == self.get_branch_path(revnum).strip("/"), \
                "Got %r, expected %r" % (bp, self.get_branch_path(revnum))
        return revnum

    def _create_lightweight_checkout(self, to_location, revision_id=None):
        """Create a new lightweight checkout of this branch.

        :param to_location: URL of location to create the checkout in.
        :param revision_id: Tip of the checkout.
        :return: WorkingTree object of the checkout.
        """
        peg_rev = svn.core.svn_opt_revision_t()
        peg_rev.kind = svn.core.svn_opt_revision_head

        rev = svn.core.svn_opt_revision_t()
        if revision_id is None:
            rev.kind = svn.core.svn_opt_revision_head
        else:
            revnum = self.lookup_revision_id(revision_id)
            rev.kind = svn.core.svn_opt_revision_number
            rev.value.number = revnum

        client_ctx = create_svn_client(Pool())
        svn.client.checkout(bzr_to_svn_url(self.base), to_location, rev, 
                            True, client_ctx)

        return WorkingTree.open(to_location)

    def create_checkout(self, to_location, revision_id=None, lightweight=False,
                        accelerator_tree=None):
        """See Branch.create_checkout()."""
        if lightweight:
            return self._create_lightweight_checkout(to_location, revision_id)
        else:
            return self._create_heavyweight_checkout(to_location, revision_id)

    def generate_revision_id(self, revnum):
        """Generate a new revision id for a revision on this branch."""
        assert isinstance(revnum, int)
        return self.repository.generate_revision_id(
                revnum, self.get_branch_path(revnum), self.mapping)
       
    def _generate_revision_history(self, last_revnum):
        """Generate the revision history up until a specified revision."""
        revhistory = []
        for (branch, rev) in self.repository.follow_branch(
                self.get_branch_path(last_revnum), last_revnum, self.mapping):
            revhistory.append(
                self.repository.generate_revision_id(rev, branch, 
                    self.mapping))
        revhistory.reverse()
        return revhistory

    def _get_nick(self):
        """Find the nick name for this branch.

        :return: Branch nick
        """
        bp = self._branch_path.strip("/")
        if self._branch_path == "":
            return None
        return bp

    nick = property(_get_nick)

    def set_revision_history(self, rev_history):
        """See Branch.set_revision_history()."""
        raise NotImplementedError(self.set_revision_history)

    def set_last_revision_info(self, revno, revid):
        """See Branch.set_last_revision_info()."""

    def last_revision_info(self):
        """See Branch.last_revision_info()."""
        last_revid = self.last_revision()
        return self.revision_id_to_revno(last_revid), last_revid

    def revno(self):
        """See Branch.revno()."""
        return self.last_revision_info()[0]

    def revision_id_to_revno(self, revision_id):
        """See Branch.revision_id_to_revno()."""
        if revision_id is None:
            return 0
        revno = self.repository.revmap.lookup_dist_to_origin(revision_id)
        if revno is not None:
            return revno
        history = self.revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError:
            raise NoSuchRevision(self, revision_id)

    def set_push_location(self, location):
        """See Branch.set_push_location()."""
        raise NotImplementedError(self.set_push_location)

    def get_push_location(self):
        """See Branch.get_push_location()."""
        # get_push_location not supported on Subversion
        return None

    def revision_history(self, last_revnum=None):
        """See Branch.revision_history()."""
        if last_revnum is None:
            last_revnum = self.get_revnum()
        if (self._revision_history is None or 
            self._revision_history_revnum != last_revnum):
            self._revision_history = self._generate_revision_history(last_revnum)
            self._revision_history_revnum = last_revnum
            self.repository.revmap.insert_revision_history(self._revision_history)
        return self._revision_history

    def last_revision(self):
        """See Branch.last_revision()."""
        # Shortcut for finding the tip. This avoids expensive generation time
        # on large branches.
        last_revnum = self.get_revnum()
        if (self._revision_history is None or 
            self._revision_history_revnum != last_revnum):
            for (branch, rev) in self.repository.follow_branch(
                self.get_branch_path(), last_revnum, self.mapping):
                return self.repository.generate_revision_id(rev, branch, 
                                                            self.mapping)
            return NULL_REVISION

        ph = self.revision_history(last_revnum)
        if ph:
            return ph[-1]
        else:
            return NULL_REVISION

    def pull(self, source, overwrite=False, stop_revision=None, 
             _hook_master=None, run_hooks=True):
        """See Branch.pull()."""
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

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch6, but works for BzrBranch5, as long as the destination's
        repository contains all the lefthand ancestors of the intended
        last_revision.  If not, set_last_revision_info will fail.

        :param destination: The branch to copy the history into
        :param revision_id: The revision-id to truncate history at.  May
          be None to copy complete history.
        """
        if revision_id is None:
            revno, revision_id = self.last_revision_info()
        else:
            revno = self.revision_id_to_revno(revision_id)
        destination.set_last_revision_info(revno, revision_id)

    def update_revisions(self, other, stop_revision=None):
        """See Branch.update_revisions()."""
        if stop_revision is None:
            stop_revision = ensure_null(other.last_revision())
        if (self.last_revision() == stop_revision or
            self.last_revision() == other.last_revision()):
            return
        if not other.repository.get_graph().is_ancestor(self.last_revision(), 
                                                        stop_revision):
            if self.repository.get_graph().is_ancestor(stop_revision, 
                                                       self.last_revision()):
                return
            raise DivergedBranches(self, other)
        todo = self.repository.lhs_missing_revisions(other.revision_history(), 
                                                     stop_revision)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for revid in todo:
                pb.update("pushing revisions", todo.index(revid), 
                          len(todo))
                push(self, other, revid)
        finally:
            pb.finished()

    def lock_write(self):
        """See Branch.lock_write()."""
        # TODO: Obtain lock on the remote server?
        if self._lock_mode:
            assert self._lock_mode == 'w'
            self._lock_count += 1
        else:
            self._lock_mode = 'w'
            self._lock_count = 1
        
    def lock_read(self):
        """See Branch.lock_read()."""
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w')
            self._lock_count += 1
        else:
            self._lock_mode = 'r'
            self._lock_count = 1

    def unlock(self):
        """See Branch.unlock()."""
        self._lock_count -= 1
        if self._lock_count == 0:
            self._lock_mode = None
            self._cached_revnum = None

    def get_parent(self):
        """See Branch.get_parent()."""
        return self.base

    def set_parent(self, url):
        """See Branch.set_parent()."""

    def append_revision(self, *revision_ids):
        """See Branch.append_revision()."""
        #raise NotImplementedError(self.append_revision)
        #FIXME: Make sure the appended revision is already 
        # part of the revision history

    def get_physical_lock_status(self):
        """See Branch.get_physical_lock_status()."""
        return False

    def sprout(self, to_bzrdir, revision_id=None):
        """See Branch.sprout()."""
        result = to_bzrdir.create_branch()
        self.copy_content_into(result, revision_id=revision_id)
        return result

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

    __repr__ = __str__


class SvnBranchFormat(BranchFormat):
    """Branch format for Subversion Branches."""
    def __init__(self):
        BranchFormat.__init__(self)

    def __get_matchingbzrdir(self):
        """See BranchFormat.__get_matchingbzrdir()."""
        from remote import SvnRemoteFormat
        return SvnRemoteFormat()

    _matchingbzrdir = property(__get_matchingbzrdir)

    def get_format_description(self):
        """See BranchFormat.get_format_description."""
        return 'Subversion Smart Server'

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return 'Subversion Smart Server'

    def initialize(self, to_bzrdir):
        """See BranchFormat.initialize()."""
        raise NotImplementedError(self.initialize)


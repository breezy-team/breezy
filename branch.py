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
from bzrlib.config import TreeConfig
from bzrlib.delta import compare_trees
from bzrlib.errors import (NotBranchError, NoWorkingTree, NoSuchRevision, 
                           NoSuchFile, DivergedBranches)
from bzrlib.inventory import (Inventory, InventoryFile, InventoryDirectory, 
                              ROOT_ID)
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.symbol_versioning import deprecated_function, zero_nine
from bzrlib.tree import Tree, EmptyTree
from bzrlib.trace import mutter, note
from bzrlib.workingtree import WorkingTree

import os

import svn.core, svn.ra
from svn.core import SubversionException

from commit import push_as_merged
from repository import SvnRepository
from tree import SvnRevisionTree


class FakeControlFiles(object):
    def get_utf8(self, name):
        raise NoSuchFile(name)

    def get(self, name):
        raise NoSuchFile(name)


class SvnBranch(Branch):
    """Maps to a Branch in a Subversion repository """
    def __init__(self, base, repository, branch_path):
        """Instantiate a new SvnBranch.

        :param repos: SvnRepository this branch is part of.
        :param branch_path: Relative path inside the repository this
            branch is located at.
        """
        self.repository = repository
        assert isinstance(self.repository, SvnRepository)
        self.branch_path = branch_path
        self.control_files = FakeControlFiles()
        self.base = base.rstrip("/")
        self._format = SvnBranchFormat()
        mutter("Connected to branch at %s" % self.branch_path)
        self._generate_revision_history(self.repository._latest_revnum)

    def check(self):
        """See Branch.Check.

        Doesn't do anything for Subversion repositories at the moment (yet).
        """
        return BranchCheckResult(self)
        
    def _generate_revision_history(self, last_revnum):
        self._revision_history = []
        for (branch, _, rev) in self.repository._log.follow_history(
                self.branch_path, last_revnum):
            self._revision_history.append(
                    self.repository.generate_revision_id(rev, branch))
        self._revision_history.reverse()

    def get_root_id(self):
        inv = self.repository.get_inventory(self.last_revision())
        return inv.root.file_id

    def _get_nick(self):
        try:
            if self.branch_path == "":
                return None
            return self.branch_path
        except ValueError:
            return None

    nick = property(_get_nick)

    def set_revision_history(self, rev_history):
        raise NotImplementedError(self.set_revision_history)

    def set_push_location(self, location):
        raise NotImplementedError(self.set_push_location)

    def get_push_location(self):
        # get_push_location not supported on Subversion
        return None

    def revision_history(self):
        return self._revision_history

    def pull(self, source, overwrite=False, stop_revision=None):
        source.lock_read()
        try:
            old_count = len(self.revision_history())
            try:
                self.update_revisions(source, stop_revision)
            except DivergedBranches:
                if overwrite:
                    raise BzrError('overwrite not supported for Subversion branches')
            new_count = len(self.revision_history())
            return new_count - old_count
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
            # Import from another Subversion branch
            assert other.repository.uuid == self.repository.uuid, \
                    "can only import from elsewhere in the same repository."

            # FIXME: Make sure branches haven't diverged
            # FIXME: svn.ra.del_dir(self.base_path)
            # FIXME: svn.ra.copy_dir(other.base_path, self.base_path)
            raise NotImplementedError(self.pull)
        else:
            if stop_revision is None:
                stop_revision = other.last_revision()
                if stop_revision is None:
                    return

            last_rev = self.last_revision()

            my_ancestry = self.repository.get_ancestry(last_rev)
            if stop_revision in my_ancestry:
                # last_revision is a descendant of stop_revision
                return

            stop_graph = other.repository.get_revision_graph(stop_revision)
            if last_rev is not None and last_rev not in stop_graph:
                raise DivergedBranches(self, other)

            for rev_id in other.revision_history():
                if rev_id not in self.revision_history():
                    mutter('integration %r' % rev_id)
                    push_as_merged(self, other, rev_id)

    # The remote server handles all this for us
    def lock_write(self):
        pass
        
    def lock_read(self):
        pass

    def unlock(self):
        pass

    def get_parent(self):
        return self.bzrdir.root_transport.base

    def set_parent(self, url):
        pass # FIXME: Use svn.client.switch()

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

    @deprecated_function(zero_nine)
    def tree_config(self):
        """DEPRECATED; call get_config instead.  
        TreeConfig has become part of BranchConfig."""
        return TreeConfig(self)


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


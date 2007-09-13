# Copyright (C) 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Reconfigure a bzrdir into a new tree/branch/repository layout"""

from bzrlib import (
    branch,
    errors,
    )

class Reconfigure(object):

    def __init__(self, bzrdir, new_bound_location=None):
        self.bzrdir = bzrdir
        self.new_bound_location = new_bound_location
        try:
            self.repository = self.bzrdir.find_repository()
        except errors.NoRepositoryPresent:
            self.repository = None
        try:
            branch = self.bzrdir.open_branch()
            if branch.bzrdir.root_transport.base == bzrdir.root_transport.base:
                self.local_branch = branch
                self.referenced_branch = None
            else:
                self.local_branch = None
                self.referenced_branch = branch
        except errors.NotBranchError:
            self.local_branch = None
            self.referenced_branch = None
        try:
            self.tree = bzrdir.open_workingtree()
        except errors.NoWorkingTree:
            self.tree = None
        self.unbind = False
        self.bind = False
        self.destroy_reference = False
        self.create_branch = False
        self.destroy_tree = False
        self.create_tree = False
        self.create_repository = False

    @staticmethod
    def to_branch(bzrdir):
        reconfiguration = Reconfigure(bzrdir)
        reconfiguration.select_changes(tree=False, branch=True, bound=False)
        if not reconfiguration.planned_changes():
            raise errors.AlreadyBranch(bzrdir)
        return reconfiguration

    @staticmethod
    def to_tree(bzrdir):
        reconfiguration = Reconfigure(bzrdir)
        reconfiguration.select_changes(tree=True, branch=True, bound=False)
        if not reconfiguration.planned_changes():
            raise errors.AlreadyTree(bzrdir)
        return reconfiguration

    @staticmethod
    def to_checkout(bzrdir, bound_location=None):
        reconfiguration = Reconfigure(bzrdir, bound_location)
        reconfiguration.select_changes(tree=True, branch=True, bound=True)
        if not reconfiguration.planned_changes():
            raise errors.AlreadyCheckout(bzrdir)
        return reconfiguration

    def select_changes(self, tree, branch, bound):
        """Determine which changes are needed to assume the configuration"""
        if self.repository is None:
            self.create_repository = True
        if self.local_branch is None:
            if branch is True:
                if self.referenced_branch is not None:
                    self.destroy_reference = True
                    self.create_branch = True
                    if bound:
                        self.bind = True
                else:
                    raise errors.ReconfigurationNotSupported(self.bzrdir)
        else:
            if bound:
                if self.local_branch.get_bound_location() is None:
                    self.bind = True
            else:
                if self.local_branch.get_bound_location() is not None:
                    self.unbind = True
        if not tree and self.tree is not None:
            self.destroy_tree = True
        if tree and self.tree is None:
            self.create_tree = True

    def planned_changes(self):
        """Return True if changes are planned, False otherwise"""
        return (self.unbind or self.bind or self.destroy_tree
                or self.create_tree or self.destroy_reference
                or self.create_branch or self.create_repository)

    def _check(self):
        """Raise if reconfiguration would destroy local changes"""
        if self.destroy_tree:
            changes = self.tree.changes_from(self.tree.basis_tree())
            if changes.has_changed():
                raise errors.UncommittedChanges(self.tree)

    def _select_bind_location(self):
        """Select a location to bind to.

        Preference is:
        1. user specified location
        2. branch reference location (it's a kind of bind location)
        3. previous bind location (it was a good choice once)
        4. push location (it's writeable, so committable)
        5. parent location (it's pullable, so update-from-able)
        """
        if self.new_bound_location is not None:
            return self.new_bound_location
        if self.local_branch is not None:
            old_bound = self.local_branch.get_old_bound_location()
            if old_bound is not None:
                return old_bound
            push_location = self.local_branch.get_push_location()
            if push_location is not None:
                return push_location
            parent = self.local_branch.get_parent()
            if parent is not None:
                return parent
        elif self.referenced_branch is not None:
            return self.referenced_branch.base
        raise errors.NoBindLocation(self.bzrdir)

    def apply(self, force=False):
        if not force:
            self._check()
        if self.create_repository:
            repo = self.bzrdir.create_repository()
        else:
            repo = self.repository
        if self.create_branch:
            repo.fetch(self.referenced_branch.repository,
                       self.referenced_branch.last_revision())
        if self.destroy_reference:
            reference_info = self.referenced_branch.last_revision_info()
            self.bzrdir.destroy_branch()
        if self.create_branch:
            local_branch = self.bzrdir.create_branch()
            local_branch.set_last_revision_info(*reference_info)
        else:
            local_branch = self.local_branch
        if self.destroy_tree:
            self.bzrdir.destroy_workingtree()
        if self.create_tree:
            self.bzrdir.create_workingtree()
        if self.unbind:
            self.local_branch.unbind()
        if self.bind:
            bind_location = self._select_bind_location()
            local_branch.bind(branch.Branch.open(bind_location))

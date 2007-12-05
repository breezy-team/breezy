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
        self._unbind = False
        self._bind = False
        self._destroy_reference = False
        self._create_reference = False
        self._destroy_branch = False
        self._create_branch = False
        self._destroy_tree = False
        self._create_tree = False
        self._create_repository = False
        self._destroy_repository = False

    @staticmethod
    def to_branch(bzrdir):
        """Return a Reconfiguration to convert this bzrdir into a branch

        :param bzrdir: The bzrdir to reconfigure
        :raise errors.AlreadyBranch: if bzrdir is already a branch
        :raise errors.ReconfigurationNotSupported: if bzrdir does not contain
            a branch or branch reference
        """
        reconfiguration = Reconfigure(bzrdir)
        reconfiguration._plan_changes(want_tree=False, want_branch=True,
                                      want_bound=False, want_reference=False)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyBranch(bzrdir)
        return reconfiguration

    @staticmethod
    def to_tree(bzrdir):
        """Return a Reconfiguration to convert this bzrdir into a tree

        :param bzrdir: The bzrdir to reconfigure
        :raise errors.AlreadyTree: if bzrdir is already a tree
        :raise errors.ReconfigurationNotSupported: if bzrdir does not contain
            a branch or branch reference
        """
        reconfiguration = Reconfigure(bzrdir)
        reconfiguration._plan_changes(want_tree=True, want_branch=True,
                                      want_bound=False, want_reference=False)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyTree(bzrdir)
        return reconfiguration

    @staticmethod
    def to_checkout(bzrdir, bound_location=None):
        """Return a Reconfiguration to convert this bzrdir into a checkout

        :param bzrdir: The bzrdir to reconfigure
        :param bound_location: The location the checkout should be bound to.
        :raise errors.AlreadyCheckout: if bzrdir is already a checkout
        :raise errors.ReconfigurationNotSupported: if bzrdir does not contain
            a branch or branch reference
        """
        reconfiguration = Reconfigure(bzrdir, bound_location)
        reconfiguration._plan_changes(want_tree=True, want_branch=True,
                                      want_bound=True, want_reference=False)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyCheckout(bzrdir)
        return reconfiguration

    @classmethod
    def to_lightweight_checkout(klass, bzrdir, reference_location=None):
        """Make a Reconfiguration to convert bzrdir into a lightweight checkout

        :param bzrdir: The bzrdir to reconfigure
        :param bound_location: The location the checkout should be bound to.
        :raise errors.AlreadyLightweightCheckout: if bzrdir is already a
            lightweight checkout
        :raise errors.ReconfigurationNotSupported: if bzrdir does not contain
            a branch or branch reference
        """
        reconfiguration = klass(bzrdir, reference_location)
        reconfiguration._plan_changes(want_tree=True, want_branch=False,
                                      want_bound=False, want_reference=True)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyLightweightCheckout(bzrdir)
        return reconfiguration

    def _plan_changes(self, want_tree, want_branch, want_bound,
                      want_reference):
        """Determine which changes are needed to assume the configuration"""
        if not want_branch and not want_reference:
            raise errors.ReconfigurationNotSupported(self.bzrdir)
        if want_branch and want_reference:
            raise errors.ReconfigurationNotSupported(self.bzrdir)
        if (want_branch or want_reference) and (self.local_branch is None and
                                                self.referenced_branch
                                                is None):
            raise errors.ReconfigurationNotSupported(self.bzrdir)
        if self.repository is None:
            if not want_reference:
                self._create_repository = True
        else:
            if want_reference and (self.repository.bzrdir.root_transport.base
                                   == self.bzrdir.root_transport.base):
                self._destroy_repository = True
        if self.referenced_branch is None:
            if want_reference:
                self._create_reference = True
        else:
            if not want_reference:
                self._destroy_reference = True
        if self.local_branch is None:
            if want_branch is True:
                self._create_branch = True
                if want_bound:
                    self._bind = True
        else:
            if want_bound:
                if self.local_branch.get_bound_location() is None:
                    self._bind = True
            else:
                if self.local_branch.get_bound_location() is not None:
                    self._unbind = True
        if not want_tree and self.tree is not None:
            self._destroy_tree = True
        if want_tree and self.tree is None:
            self._create_tree = True

    def changes_planned(self):
        """Return True if changes are planned, False otherwise"""
        return (self._unbind or self._bind or self._destroy_tree
                or self._create_tree or self._destroy_reference
                or self._create_branch or self._create_repository)

    def _check(self):
        """Raise if reconfiguration would destroy local changes"""
        if self._destroy_tree:
            changes = self.tree.changes_from(self.tree.basis_tree())
            if changes.has_changed():
                raise errors.UncommittedChanges(self.tree)

    def _select_bind_location(self):
        """Select a location to bind or create a reference to.

        Preference is:
        1. user specified location
        2. branch reference location (it's a kind of bind location)
        3. current bind location
        4. previous bind location (it was a good choice once)
        5. push location (it's writeable, so committable)
        6. parent location (it's pullable, so update-from-able)
        """
        if self.new_bound_location is not None:
            return self.new_bound_location
        if self.local_branch is not None:
            bound = self.local_branch.get_bound_location()
            if bound is not None:
                return bound
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
        """Apply the reconfiguration

        :param force: If true, the reconfiguration is applied even if it will
            destroy local changes.
        :raise errors.UncommittedChanges: if the local tree is to be destroyed
            but contains uncommitted changes.
        :raise errors.NoBindLocation: if no bind location was specified and
            none could be autodetected.
        """
        if not force:
            self._check()
        if self._create_repository:
            repo = self.bzrdir.create_repository()
        else:
            repo = self.repository
        if self._create_branch:
            repo.fetch(self.referenced_branch.repository,
                       self.referenced_branch.last_revision())
        if self._destroy_reference:
            reference_info = self.referenced_branch.last_revision_info()
            self.bzrdir.destroy_branch()
        if self._destroy_branch:
            reference_info = self.local_branch.last_revision_info()
            self.bzrdir.destroy_branch()
        if self._create_branch:
            local_branch = self.bzrdir.create_branch()
            local_branch.set_last_revision_info(*reference_info)
        else:
            local_branch = self.local_branch
        if self._create_reference:
            reference_branch = branch.Branch.open(self._select_bind_location())
            format = branch.BranchReferenceFormat().initialize(self.bzrdir,
                reference_branch)
        if self._destroy_tree:
            self.bzrdir.destroy_workingtree()
        if self._create_tree:
            self.bzrdir.create_workingtree()
        if self._unbind:
            self.local_branch.unbind()
        if self._bind:
            bind_location = self._select_bind_location()
            local_branch.bind(branch.Branch.open(bind_location))
        if self._destroy_repository:
            if self._create_reference:
                reference_branch.repository.fetch(self.repository)
            self.bzrdir.destroy_repository()

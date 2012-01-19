# Copyright (C) 2007-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Reconfigure a controldir into a new tree/branch/repository layout.

Various types of reconfiguration operation are available either by
constructing a class or using a factory method on Reconfigure.
"""

from __future__ import absolute_import


from bzrlib import (
    branch,
    controldir,
    errors,
    trace,
    ui,
    urlutils,
    )
from bzrlib.i18n import gettext

# TODO: common base class for all reconfigure operations, making no
# assumptions about what kind of change will be done.


class ReconfigureStackedOn(object):
    """Reconfigures a branch to be stacked on another branch."""

    def apply(self, bzrdir, stacked_on_url):
        branch = bzrdir.open_branch()
        # it may be a path relative to the cwd or a url; the branch wants
        # a path relative to itself...
        on_url = urlutils.relative_url(branch.base,
            urlutils.normalize_url(stacked_on_url))
        branch.lock_write()
        try:
            branch.set_stacked_on_url(on_url)
            if not trace.is_quiet():
                ui.ui_factory.note(gettext(
                    "{0} is now stacked on {1}\n").format(
                      branch.base, branch.get_stacked_on_url()))
        finally:
            branch.unlock()


class ReconfigureUnstacked(object):

    def apply(self, bzrdir):
        branch = bzrdir.open_branch()
        branch.lock_write()
        try:
            branch.set_stacked_on_url(None)
            if not trace.is_quiet():
                ui.ui_factory.note(gettext(
                    "%s is now not stacked\n")
                    % (branch.base,))
        finally:
            branch.unlock()


class Reconfigure(object):

    def __init__(self, bzrdir, new_bound_location=None):
        self.bzrdir = bzrdir
        self.new_bound_location = new_bound_location
        self.local_repository = None
        try:
            self.repository = self.bzrdir.find_repository()
        except errors.NoRepositoryPresent:
            self.repository = None
            self.local_repository = None
        else:
            if (self.repository.user_url == self.bzrdir.user_url):
                self.local_repository = self.repository
            else:
                self.local_repository = None
        try:
            branch = self.bzrdir.open_branch()
            if branch.user_url == bzrdir.user_url:
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
        self._repository_trees = None

    @staticmethod
    def to_branch(bzrdir):
        """Return a Reconfiguration to convert this bzrdir into a branch

        :param bzrdir: The bzrdir to reconfigure
        :raise errors.AlreadyBranch: if bzrdir is already a branch
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
        """
        reconfiguration = klass(bzrdir, reference_location)
        reconfiguration._plan_changes(want_tree=True, want_branch=False,
                                      want_bound=False, want_reference=True)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyLightweightCheckout(bzrdir)
        return reconfiguration

    @classmethod
    def to_use_shared(klass, bzrdir):
        """Convert a standalone branch into a repository branch"""
        reconfiguration = klass(bzrdir)
        reconfiguration._set_use_shared(use_shared=True)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyUsingShared(bzrdir)
        return reconfiguration

    @classmethod
    def to_standalone(klass, bzrdir):
        """Convert a repository branch into a standalone branch"""
        reconfiguration = klass(bzrdir)
        reconfiguration._set_use_shared(use_shared=False)
        if not reconfiguration.changes_planned():
            raise errors.AlreadyStandalone(bzrdir)
        return reconfiguration

    @classmethod
    def set_repository_trees(klass, bzrdir, with_trees):
        """Adjust a repository's working tree presence default"""
        reconfiguration = klass(bzrdir)
        if not reconfiguration.repository.is_shared():
            raise errors.ReconfigurationNotSupported(reconfiguration.bzrdir)
        if with_trees and reconfiguration.repository.make_working_trees():
            raise errors.AlreadyWithTrees(bzrdir)
        elif (not with_trees
              and not reconfiguration.repository.make_working_trees()):
            raise errors.AlreadyWithNoTrees(bzrdir)
        else:
            reconfiguration._repository_trees = with_trees
        return reconfiguration

    def _plan_changes(self, want_tree, want_branch, want_bound,
                      want_reference):
        """Determine which changes are needed to assume the configuration"""
        if not want_branch and not want_reference:
            raise errors.ReconfigurationNotSupported(self.bzrdir)
        if want_branch and want_reference:
            raise errors.ReconfigurationNotSupported(self.bzrdir)
        if self.repository is None:
            if not want_reference:
                self._create_repository = True
        else:
            if want_reference and (
                self.repository.user_url == self.bzrdir.user_url):
                if not self.repository.is_shared():
                    self._destroy_repository = True
        if self.referenced_branch is None:
            if want_reference:
                self._create_reference = True
                if self.local_branch is not None:
                    self._destroy_branch = True
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

    def _set_use_shared(self, use_shared=None):
        if use_shared is None:
            return
        if use_shared:
            if self.local_repository is not None:
                self._destroy_repository = True
        else:
            if self.local_repository is None:
                self._create_repository = True

    def changes_planned(self):
        """Return True if changes are planned, False otherwise"""
        return (self._unbind or self._bind or self._destroy_tree
                or self._create_tree or self._destroy_reference
                or self._create_branch or self._create_repository
                or self._create_reference or self._destroy_repository)

    def _check(self):
        """Raise if reconfiguration would destroy local changes"""
        if self._destroy_tree and self.tree.has_changes():
                raise errors.UncommittedChanges(self.tree)
        if self._create_reference and self.local_branch is not None:
            reference_branch = branch.Branch.open(self._select_bind_location())
            if (reference_branch.last_revision() !=
                self.local_branch.last_revision()):
                raise errors.UnsyncedBranches(self.bzrdir, reference_branch)

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
            if self.local_branch and not self._destroy_branch:
                old_repo = self.local_branch.repository
            elif self._create_branch and self.referenced_branch is not None:
                old_repo = self.referenced_branch.repository
            else:
                old_repo = None
            if old_repo is not None:
                repository_format = old_repo._format
            else:
                repository_format = None
            if repository_format is not None:
                repo = repository_format.initialize(self.bzrdir)
            else:
                repo = self.bzrdir.create_repository()
            if self.local_branch and not self._destroy_branch:
                repo.fetch(self.local_branch.repository,
                           self.local_branch.last_revision())
        else:
            repo = self.repository
        if self._create_branch and self.referenced_branch is not None:
            repo.fetch(self.referenced_branch.repository,
                       self.referenced_branch.last_revision())
        if self._create_reference:
            reference_branch = branch.Branch.open(self._select_bind_location())
        if self._destroy_repository:
            if self._create_reference:
                reference_branch.repository.fetch(self.repository)
            elif self.local_branch is not None and not self._destroy_branch:
                up = self.local_branch.user_transport.clone('..')
                up_bzrdir = controldir.ControlDir.open_containing_from_transport(
                    up)[0]
                new_repo = up_bzrdir.find_repository()
                new_repo.fetch(self.repository)
        last_revision_info = None
        if self._destroy_reference:
            last_revision_info = self.referenced_branch.last_revision_info()
            self.bzrdir.destroy_branch()
        if self._destroy_branch:
            last_revision_info = self.local_branch.last_revision_info()
            if self._create_reference:
                self.local_branch.tags.merge_to(reference_branch.tags)
            self.bzrdir.destroy_branch()
        if self._create_branch:
            local_branch = self.bzrdir.create_branch()
            if last_revision_info is not None:
                local_branch.set_last_revision_info(*last_revision_info)
            if self._destroy_reference:
                self.referenced_branch.tags.merge_to(local_branch.tags)
                self.referenced_branch.update_references(local_branch)
        else:
            local_branch = self.local_branch
        if self._create_reference:
            self.bzrdir.set_branch_reference(reference_branch)
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
            self.bzrdir.destroy_repository()
        if self._repository_trees is not None:
            repo.set_make_working_trees(self._repository_trees)

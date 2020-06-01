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


from . import (
    branch,
    controldir,
    errors,
    trace,
    ui,
    urlutils,
    )
from .i18n import gettext

# TODO: common base class for all reconfigure operations, making no
# assumptions about what kind of change will be done.


class BzrDirError(errors.BzrError):

    def __init__(self, controldir):
        display_url = urlutils.unescape_for_display(controldir.user_url,
                                                    'ascii')
        errors.BzrError.__init__(self, controldir=controldir,
                                 display_url=display_url)


class NoBindLocation(BzrDirError):

    _fmt = "No location could be found to bind to at %(display_url)s."


class UnsyncedBranches(BzrDirError):

    _fmt = ("'%(display_url)s' is not in sync with %(target_url)s.  See"
            " brz help sync-for-reconfigure.")

    def __init__(self, controldir, target_branch):
        errors.BzrError.__init__(self, controldir)
        from . import urlutils
        self.target_url = urlutils.unescape_for_display(target_branch.base,
                                                        'ascii')


class AlreadyBranch(BzrDirError):

    _fmt = "'%(display_url)s' is already a branch."


class AlreadyTree(BzrDirError):

    _fmt = "'%(display_url)s' is already a tree."


class AlreadyCheckout(BzrDirError):

    _fmt = "'%(display_url)s' is already a checkout."


class AlreadyLightweightCheckout(BzrDirError):

    _fmt = "'%(display_url)s' is already a lightweight checkout."


class AlreadyUsingShared(BzrDirError):

    _fmt = "'%(display_url)s' is already using a shared repository."


class AlreadyStandalone(BzrDirError):

    _fmt = "'%(display_url)s' is already standalone."


class AlreadyWithTrees(BzrDirError):

    _fmt = ("Shared repository '%(display_url)s' already creates "
            "working trees.")


class AlreadyWithNoTrees(BzrDirError):

    _fmt = ("Shared repository '%(display_url)s' already doesn't create "
            "working trees.")


class ReconfigurationNotSupported(BzrDirError):

    _fmt = "Requested reconfiguration of '%(display_url)s' is not supported."


class ReconfigureStackedOn(object):
    """Reconfigures a branch to be stacked on another branch."""

    def apply(self, controldir, stacked_on_url):
        branch = controldir.open_branch()
        # it may be a path relative to the cwd or a url; the branch wants
        # a path relative to itself...
        on_url = urlutils.relative_url(branch.base,
                                       urlutils.normalize_url(stacked_on_url))
        with branch.lock_write():
            branch.set_stacked_on_url(on_url)
            if not trace.is_quiet():
                ui.ui_factory.note(gettext(
                    "{0} is now stacked on {1}\n").format(
                    branch.base, branch.get_stacked_on_url()))


class ReconfigureUnstacked(object):

    def apply(self, controldir):
        branch = controldir.open_branch()
        with branch.lock_write():
            branch.set_stacked_on_url(None)
            if not trace.is_quiet():
                ui.ui_factory.note(gettext(
                    "%s is now not stacked\n")
                    % (branch.base,))


class Reconfigure(object):

    def __init__(self, controldir, new_bound_location=None):
        self.controldir = controldir
        self.new_bound_location = new_bound_location
        self.local_repository = None
        try:
            self.repository = self.controldir.find_repository()
        except errors.NoRepositoryPresent:
            self.repository = None
            self.local_repository = None
        else:
            if (self.repository.user_url == self.controldir.user_url):
                self.local_repository = self.repository
            else:
                self.local_repository = None
        try:
            branch = self.controldir.open_branch()
            if branch.user_url == controldir.user_url:
                self.local_branch = branch
                self.referenced_branch = None
            else:
                self.local_branch = None
                self.referenced_branch = branch
        except errors.NotBranchError:
            self.local_branch = None
            self.referenced_branch = None
        try:
            self.tree = controldir.open_workingtree()
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
    def to_branch(controldir):
        """Return a Reconfiguration to convert this controldir into a branch

        :param controldir: The controldir to reconfigure
        :raise AlreadyBranch: if controldir is already a branch
        """
        reconfiguration = Reconfigure(controldir)
        reconfiguration._plan_changes(want_tree=False, want_branch=True,
                                      want_bound=False, want_reference=False)
        if not reconfiguration.changes_planned():
            raise AlreadyBranch(controldir)
        return reconfiguration

    @staticmethod
    def to_tree(controldir):
        """Return a Reconfiguration to convert this controldir into a tree

        :param controldir: The controldir to reconfigure
        :raise AlreadyTree: if controldir is already a tree
        """
        reconfiguration = Reconfigure(controldir)
        reconfiguration._plan_changes(want_tree=True, want_branch=True,
                                      want_bound=False, want_reference=False)
        if not reconfiguration.changes_planned():
            raise AlreadyTree(controldir)
        return reconfiguration

    @staticmethod
    def to_checkout(controldir, bound_location=None):
        """Return a Reconfiguration to convert this controldir into a checkout

        :param controldir: The controldir to reconfigure
        :param bound_location: The location the checkout should be bound to.
        :raise AlreadyCheckout: if controldir is already a checkout
        """
        reconfiguration = Reconfigure(controldir, bound_location)
        reconfiguration._plan_changes(want_tree=True, want_branch=True,
                                      want_bound=True, want_reference=False)
        if not reconfiguration.changes_planned():
            raise AlreadyCheckout(controldir)
        return reconfiguration

    @classmethod
    def to_lightweight_checkout(klass, controldir, reference_location=None):
        """Make a Reconfiguration to convert controldir into a lightweight checkout

        :param controldir: The controldir to reconfigure
        :param bound_location: The location the checkout should be bound to.
        :raise AlreadyLightweightCheckout: if controldir is already a
            lightweight checkout
        """
        reconfiguration = klass(controldir, reference_location)
        reconfiguration._plan_changes(want_tree=True, want_branch=False,
                                      want_bound=False, want_reference=True)
        if not reconfiguration.changes_planned():
            raise AlreadyLightweightCheckout(controldir)
        return reconfiguration

    @classmethod
    def to_use_shared(klass, controldir):
        """Convert a standalone branch into a repository branch"""
        reconfiguration = klass(controldir)
        reconfiguration._set_use_shared(use_shared=True)
        if not reconfiguration.changes_planned():
            raise AlreadyUsingShared(controldir)
        return reconfiguration

    @classmethod
    def to_standalone(klass, controldir):
        """Convert a repository branch into a standalone branch"""
        reconfiguration = klass(controldir)
        reconfiguration._set_use_shared(use_shared=False)
        if not reconfiguration.changes_planned():
            raise AlreadyStandalone(controldir)
        return reconfiguration

    @classmethod
    def set_repository_trees(klass, controldir, with_trees):
        """Adjust a repository's working tree presence default"""
        reconfiguration = klass(controldir)
        if not reconfiguration.repository.is_shared():
            raise ReconfigurationNotSupported(reconfiguration.controldir)
        if with_trees and reconfiguration.repository.make_working_trees():
            raise AlreadyWithTrees(controldir)
        elif (not with_trees and
              not reconfiguration.repository.make_working_trees()):
            raise AlreadyWithNoTrees(controldir)
        else:
            reconfiguration._repository_trees = with_trees
        return reconfiguration

    def _plan_changes(self, want_tree, want_branch, want_bound,
                      want_reference):
        """Determine which changes are needed to assume the configuration"""
        if not want_branch and not want_reference:
            raise ReconfigurationNotSupported(self.controldir)
        if want_branch and want_reference:
            raise ReconfigurationNotSupported(self.controldir)
        if self.repository is None:
            if not want_reference:
                self._create_repository = True
        else:
            if want_reference and (
                    self.repository.user_url == self.controldir.user_url):
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
        return (self._unbind or self._bind or self._destroy_tree or
                self._create_tree or self._destroy_reference or
                self._create_branch or self._create_repository or
                self._create_reference or self._destroy_repository)

    def _check(self):
        """Raise if reconfiguration would destroy local changes"""
        if self._destroy_tree and self.tree.has_changes():
            raise errors.UncommittedChanges(self.tree)
        if self._create_reference and self.local_branch is not None:
            reference_branch = branch.Branch.open(self._select_bind_location())
            if (reference_branch.last_revision()
                    != self.local_branch.last_revision()):
                raise UnsyncedBranches(self.controldir, reference_branch)

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
        raise NoBindLocation(self.controldir)

    def apply(self, force=False):
        """Apply the reconfiguration

        :param force: If true, the reconfiguration is applied even if it will
            destroy local changes.
        :raise errors.UncommittedChanges: if the local tree is to be destroyed
            but contains uncommitted changes.
        :raise NoBindLocation: if no bind location was specified and
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
                repo = repository_format.initialize(self.controldir)
            else:
                repo = self.controldir.create_repository()
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
                up_controldir = controldir.ControlDir.open_containing_from_transport(
                    up)[0]
                new_repo = up_controldir.find_repository()
                new_repo.fetch(self.repository)
        last_revision_info = None
        if self._destroy_reference:
            last_revision_info = self.referenced_branch.last_revision_info()
            self.controldir.destroy_branch()
        if self._destroy_branch:
            last_revision_info = self.local_branch.last_revision_info()
            if self._create_reference:
                self.local_branch.tags.merge_to(reference_branch.tags)
            self.controldir.destroy_branch()
        if self._create_branch:
            local_branch = self.controldir.create_branch()
            if last_revision_info is not None:
                local_branch.set_last_revision_info(*last_revision_info)
            if self._destroy_reference:
                self.referenced_branch.tags.merge_to(local_branch.tags)
                self.referenced_branch.update_references(local_branch)
        else:
            local_branch = self.local_branch
        if self._create_reference:
            self.controldir.set_branch_reference(reference_branch)
        if self._destroy_tree:
            self.controldir.destroy_workingtree()
        if self._create_tree:
            self.controldir.create_workingtree()
        if self._unbind:
            self.local_branch.unbind()
        if self._bind:
            bind_location = self._select_bind_location()
            local_branch.bind(branch.Branch.open(bind_location))
        if self._destroy_repository:
            self.controldir.destroy_repository()
        if self._repository_trees is not None:
            repo.set_make_working_trees(self._repository_trees)

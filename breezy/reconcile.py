# Copyright (C) 2006-2010 Canonical Ltd
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

"""Reconcilers are able to fix some potential data errors in a branch."""

__all__ = [
    "Reconciler",
    "reconcile",
]


from . import errors, ui
from .i18n import gettext


def reconcile(dir, canonicalize_chks=False):
    """Reconcile the data in dir.

    Currently this is limited to a inventory 'reweave'.

    This is a convenience method, for using a Reconciler object.

    Directly using Reconciler is recommended for library users that
    desire fine grained control or analysis of the found issues.

    :param canonicalize_chks: Make sure CHKs are in canonical form.
    """
    reconciler = Reconciler(dir, canonicalize_chks=canonicalize_chks)
    return reconciler.reconcile()


class ReconcileResult:
    """Class describing the result of a reconcile operation."""


class Reconciler:
    """Reconcilers are used to reconcile existing data."""

    def __init__(self, dir, other=None, canonicalize_chks=False):
        """Create a Reconciler."""
        self.controldir = dir
        self.canonicalize_chks = canonicalize_chks

    def reconcile(self):
        """Perform reconciliation."""
        with ui.ui_factory.nested_progress_bar() as self.pb:
            result = ReconcileResult()
            branch_result = self._reconcile_branch()
            repo_result = self._reconcile_repository()
            # TODO(jelmer): Don't hardcode supported attributes here
            result.inconsistent_parents = getattr(
                repo_result, "inconsistent_parents", None
            )
            result.aborted = getattr(repo_result, "aborted", None)
            result.garbage_inventories = getattr(
                repo_result, "garbage_inventories", None
            )
            result.fixed_branch_history = getattr(branch_result, "fixed_history", None)
            return result

    def _reconcile_branch(self):
        try:
            self.branch = self.controldir.open_branch()
        except errors.NotBranchError:
            # Nothing to check here
            return
        ui.ui_factory.note(gettext("Reconciling branch %s") % self.branch.base)
        return self.branch.reconcile(thorough=True)

    def _reconcile_repository(self):
        self.repo = self.controldir.find_repository()
        ui.ui_factory.note(gettext("Reconciling repository %s") % self.repo.user_url)
        self.pb.update(gettext("Reconciling repository"), 0, 1)
        if self.canonicalize_chks:
            try:
                self.repo.reconcile_canonicalize_chks
            except AttributeError:
                raise errors.BzrError(
                    gettext("%s cannot canonicalize CHKs.") % (self.repo,)
                )
            reconcile_result = self.repo.reconcile_canonicalize_chks()
        else:
            reconcile_result = self.repo.reconcile(thorough=True)
        if reconcile_result.aborted:
            ui.ui_factory.note(
                gettext("Reconcile aborted: revision index has inconsistent parents.")
            )
            ui.ui_factory.note(gettext('Run "brz check" for more details.'))
        else:
            ui.ui_factory.note(gettext("Reconciliation complete."))
        return reconcile_result

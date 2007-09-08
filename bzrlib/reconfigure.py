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
    errors,
    )

class Reconfigure(object):

    def __init__(self, bzrdir, tree, branch, unbind):
        self.bzrdir = bzrdir
        self.tree = tree
        self.branch = branch
        self.unbind = unbind

    @staticmethod
    def to_branch(bzrdir):
        try:
            branch = bzrdir.open_branch()
        except errors.NotBranchError:
            raise errors.ReconfigurationNotSupported(bzrdir)
        unbind = (branch.get_bound_location() is not None)
        try:
            tree = bzrdir.open_workingtree()
        except errors.NoWorkingTree:
            raise errors.AlreadyBranch(bzrdir)
        return Reconfigure(bzrdir, tree, branch, unbind)

    def _check(self):
        changes = self.tree.changes_from(self.tree.basis_tree())
        if changes.has_changed():
            raise errors.UncommittedChanges(self.tree)

    def apply(self, force=False):
        if not force:
            self._check()
        self.bzrdir.destroy_workingtree()
        if self.unbind:
            self.branch.unbind()

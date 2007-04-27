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

"""Utility for create branches with particular contents."""

from bzrlib import bzrdir, errors, memorytree


class BranchBuilder(object):
    """A BranchBuilder aids creating Branches with particular shapes."""

    def __init__(self, transport):
        """Construct a BranchBuilder on transport.
        
        :param transport: The transport the branch should be created on.
            If the path of the transport does not exist but its parent does
            it will be created.
        """
        if not transport.has('.'):
            transport.mkdir('.')
        self._branch = bzrdir.BzrDir.create_branch_convenience(transport.base,
            format=bzrdir.format_registry.make_bzrdir('default'))

    def build_commit(self):
        """Build a commit on the branch."""
        tree = memorytree.MemoryTree.create_on_branch(self._branch)
        tree.lock_write()
        tree.add('')
        tree.commit('commit %d' % (self._branch.revno() + 1))
        tree.unlock()

    def get_branch(self):
        """Return the branch created by the builder."""
        return self._branch

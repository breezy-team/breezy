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

from bzrlib import bzrdir, errors


class BranchBuilder(object):
    """A BranchBuilder aids creating Branches with particular shapes."""

    def __init__(self, transport):
        """Construct a BranchBuilder on transport."""
        if not transport.has('.'):
            transport.mkdir('.')
        self._branch = bzrdir.BzrDir.create_branch_convenience(transport.base,
            format=bzrdir.format_registry.make_bzrdir('default'))

    def get_branch(self):
        """Return the branch created by the builder."""
        return self._branch

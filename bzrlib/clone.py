# Copyright (C) 2004, 2005 by Canonical Ltd

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

# TODO: This could be done *much* more efficiently by just copying
# all the whole weaves and revisions, rather than getting one
# revision at a time.

# TODO: Do we really need to invoke merge() to build the working directory?
# That seems a bit of an abstraction inversion.

import sys
import os

from bzrlib.merge import merge
from bzrlib.branch import Branch
from bzrlib.trace import mutter


def copy_branch(branch_from, to_location, revision=None, basis_branch=None):
    """Copy branch_from into the existing directory to_location.

    revision
        If not None, only revisions up to this point will be copied.
        The head of the new branch will be that revision.  Must be a
        revid or None.

    to_location
        The name of a local directory that exists but is empty.

    revno
        The revision to copy up to

    basis_branch
        A local branch to copy revisions from, related to branch_from
    """
    assert isinstance(branch_from, Branch)
    assert isinstance(to_location, basestring)
    
    br_to = Branch.initialize(to_location)
    mutter("copy branch from %s to %s", branch_from, br_to)
    if basis_branch is not None:
        basis_branch.push_stores(br_to)
    br_to.set_root_id(branch_from.get_root_id())
    if revision is None:
        revision = branch_from.last_revision()
    br_to.update_revisions(branch_from, stop_revision=revision)
    merge((to_location, -1), (to_location, 0), this_dir=to_location,
          check_clean=False, ignore_zero=True)
    br_to.set_parent(branch_from.base)
    mutter("copied")
    return br_to

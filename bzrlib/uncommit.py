# Copyright (C) 2006 Canonical Ltd
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

"""Remove the last revision from the history of the current branch.
"""

import os

from bzrlib.errors import BoundBranchOutOfDate


def uncommit(branch, dry_run=False, verbose=False, revno=None, tree=None):
    """Remove the last revision from the supplied branch.

    :param dry_run: Don't actually change anything
    :param verbose: Print each step as you do it
    :param revno: Remove back to this revision
    """
    unlockable = []
    try:
        if tree is not None:
            tree.lock_write()
            unlockable.append(tree)
        
        branch.lock_write()
        unlockable.append(branch)

        pending_merges = []
        if tree is not None:
            pending_merges = tree.pending_merges()

        master = branch.get_master_branch()
        if master is not None:
            master.lock_write()
            unlockable.append(master)
        rh = branch.revision_history()
        if master is not None and rh[-1] != master.last_revision():
            raise BoundBranchOutOfDate(branch, master)
        if revno is None:
            revno = len(rh)

        files_to_remove = []
        for r in range(revno-1, len(rh)):
            rev_id = rh.pop()
            rev = branch.repository.get_revision(rev_id)
            # When we finish popping off the pending merges, we want
            # them to stay in the order that they used to be.
            # but we pop from the end, so reverse the order, and
            # then get the order right at the end
            pending_merges.extend(reversed(rev.parent_ids[1:]))
            if verbose:
                print 'Removing revno %d: %s' % (len(rh)+1, rev_id)

        # Committing before we start removing files, because
        # once we have removed at least one, all the rest are invalid.
        if not dry_run:
            if master is not None:
                master.set_revision_history(rh)
            branch.set_revision_history(rh)
            if tree is not None:
                branch_tip = branch.last_revision()
                if branch_tip is not None:
                    parents = [branch.last_revision()]
                else:
                    parents = []
                parents.extend(reversed(pending_merges))
                tree.set_parent_ids(parents)
    finally:
        for item in reversed(unlockable):
            item.unlock()

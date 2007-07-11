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

"""Remove the last revision from the history of the current branch."""

# TODO: make the guts of this methods on tree, branch.

import os

from bzrlib import revision as _mod_revision
from bzrlib.branch import Branch
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
            pending_merges = tree.get_parent_ids()[1:]

        master = branch.get_master_branch()
        if master is not None:
            master.lock_write()
            unlockable.append(master)
        rh = branch.revision_history()
        if master is not None and rh[-1] != master.last_revision():
            raise BoundBranchOutOfDate(branch, master)
        if revno is None:
            revno = len(rh)
        old_revno, old_tip = branch.last_revision_info()
        new_revno = revno -1

        files_to_remove = []
        for r in range(revno-1, len(rh)):
            rev_id = rh.pop()
            # NB: performance would be better using the revision graph rather
            # than the whole revision.
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
            new_tip = branch.last_revision()
            if master is None:
                hook_local = None
                hook_master = branch
            else:
                hook_local = branch
                hook_master = master
            for hook in Branch.hooks['post_uncommit']:
                hook_new_tip = new_tip
                if hook_new_tip == _mod_revision.NULL_REVISION:
                    hook_new_tip = None
                hook(hook_local, hook_master, old_revno, old_tip, new_revno,
                     hook_new_tip)
            if tree is not None:
                if not _mod_revision.is_null(new_tip):
                    parents = [new_tip]
                else:
                    parents = []
                parents.extend(reversed(pending_merges))
                tree.set_parent_ids(parents)
    finally:
        for item in reversed(unlockable):
            item.unlock()

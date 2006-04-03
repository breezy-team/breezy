#!/usr/bin/env python
"""\
Remove the last revision from the history of the current branch.
"""

import os
import bzrlib
from bzrlib.errors import BoundBranchOutOfDate

def test_remove(filename):
    if os.path.exists(filename):
        os.remove(filename)
    else:
        print '* file does not exist: %r' % filename


def uncommit(branch, dry_run=False, verbose=False, revno=None, tree=None):
    """Remove the last revision from the supplied branch.

    :param dry_run: Don't actually change anything
    :param verbose: Print each step as you do it
    :param revno: Remove back to this revision
    """
    from bzrlib.atomicfile import AtomicFile
    unlockable = []
    try:
        if tree is not None:
            tree.lock_write()
            unlockable.append(tree)
        
        branch.lock_write()
        unlockable.append(branch)

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
            if verbose:
                print 'Removing revno %d: %s' % (len(rh)+1, rev_id)


        # Committing before we start removing files, because
        # once we have removed at least one, all the rest are invalid.
        if not dry_run:
            if master is not None:
                master.set_revision_history(rh)
            branch.set_revision_history(rh)
            if tree is not None:
                tree.set_last_revision(branch.last_revision())
    finally:
        for item in reversed(unlockable):
            item.unlock()

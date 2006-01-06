#!/usr/bin/env python
"""\
Remove the last revision from the history of the current branch.
"""

import os
import bzrlib

def test_remove(filename):
    if os.path.exists(filename):
        os.remove(filename)
    else:
        print '* file does not exist: %r' % filename


def uncommit(branch, dry_run=False, verbose=False, revno=None):
    """Remove the last revision from the supplied branch.

    :param dry_run: Don't actually change anything
    :param verbose: Print each step as you do it
    :param revno: Remove back to this revision
    """
    from bzrlib.atomicfile import AtomicFile
    rh = branch.revision_history()
    if revno is None:
        revno = len(rh)

    files_to_remove = []
    new_rev_history = AtomicFile(branch.controlfilename('revision-history'))
    for r in range(revno-1, len(rh)):
        rev_id = rh.pop()
        if verbose:
            print 'Removing revno %d: %s' % (len(rh)+1, rev_id)
        rev = branch.get_revision(rev_id)
        inv = branch.get_revision_inventory(rev_id)
        inv_prev = []
        for p in rev.parent_ids:
            inv_prev.append(branch.get_revision_inventory(p))

    new_rev_history.write('\n'.join(rh))

    # Committing before we start removing files, because
    # once we have removed at least one, all the rest are invalid.
    if not dry_run:
        new_rev_history.commit()
    else:
        new_rev_history.abort()



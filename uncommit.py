#!/usr/bin/env python
"""\
Remove the last revision from the history of the current branch.
"""

import os
import bzrlib

try:
    set
except NameError:
    from sets import Set as set

def test_remove(filename):
    if os.path.exists(filename):
        os.remove(filename)
    else:
        print '* file does not exist: %r' % filename


def uncommit(branch, remove_files=False,
        dry_run=False, verbose=False):
    """Remove the last revision from the supplied branch.

    :param remove_files: If True, remove files from the stores
        as well.
    """
    from bzrlib.atomicfile import AtomicFile
    rh = branch.revision_history()
    rev_id = rh.pop()
    rev = branch.get_revision(rev_id)
    inv = branch.get_inventory(rev.inventory_id)
    inv_prev = []
    for p in rev.parents:
        inv_prev.append(branch.get_revision_inventory(p.revision_id))

    new_rev_history = AtomicFile(branch.controlfilename('revision-history'))
    new_rev_history.write('\n'.join(rh))
    # Committing now, because even if we fail to remove all files
    # once we have removed at least one, all the rest are invalid.
    if not dry_run:
        new_rev_history.commit()
    else:
        new_rev_history.abort()

    if remove_files:
        # Figure out what text-store entries are new
        files_to_remove = []
        for file_id in inv:
            ie = inv[file_id]
            if not hasattr(ie, 'text_id'):
                continue
            for other_inv in inv_prev:
                if file_id in other_inv:
                    other_ie = other_inv[file_id]
                    if other_ie.text_id == ie.text_id:
                        break
            else:
                # None of the previous ancestors used
                # the same inventory
                files_to_remove.append(branch.controlfilename(['text-store',
                    ie.text_id + '.gz']))
        rev_file = branch.controlfilename(['revision-store',
                rev_id + '.gz'])
        files_to_remove.append(rev_file)
        inv_file = branch.controlfilename(['inventory-store',
                rev.inventory_id + '.gz'])
        files_to_remove.append(inv_file)

        if verbose:
            print 'Removing files:'
            for f in files_to_remove:
                print '\t%s' % branch.relpath(f)

        if not dry_run:
            # Actually start removing files
            for f in files_to_remove:
                test_remove(f)


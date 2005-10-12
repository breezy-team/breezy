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
        dry_run=False, verbose=False, revno=None):
    """Remove the last revision from the supplied branch.

    :param remove_files: If True, remove files from the stores
        as well.
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

        if remove_files:
            # Figure out what text-store entries are new

            # In the future, when we have text_version instead of
            # text_id, we can just check to see if the text_version
            # equals the current revision id.
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

    if verbose and files_to_remove:
        print 'Removing files:'
        for f in files_to_remove:
            print '\t%s' % branch.relpath(f)

    new_rev_history.write('\n'.join(rh))

    # Committing before we start removing files, because
    # once we have removed at least one, all the rest are invalid.
    if not dry_run:
        new_rev_history.commit()
        if remove_files:
            # Actually start removing files
            for f in files_to_remove:
                test_remove(f)

    else:
        new_rev_history.abort()



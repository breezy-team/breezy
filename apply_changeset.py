#!/usr/bin/env python
"""\
This contains the apply changset function for bzr
"""

import bzrlib

def apply_changeset(branch, from_file, reverse=False, auto_commit=False):
    from bzrlib.changeset import apply_changeset
    from bzrlib.merge import regen_inventory
    import sys, read_changeset


    cset_info = read_changeset.read_changeset(from_file)
    cset = cset_info.get_changeset()
    inv = {}
    for file_id in branch.inventory:
        inv[file_id] = branch.inventory.id2path(file_id)
    changes = apply_changeset(cset, inv, branch.base,
            reverse=reverse)

    adjust_ids = []
    for id, path in changes.iteritems():
        if path is not None:
            if path == '.':
                path = ''
        adjust_ids.append((path, id))

    branch.set_inventory(regen_inventory(branch, branch.base, adjust_ids))

    if auto_commit:
        from bzrlib.commit import commit
        if branch.last_patch() == cset_info.precursor:
            # This patch can be applied directly
            commit(branch, message = cset_info.message,
                    timestamp=float(cset_info.timestamp),
                    timezone=float(cset_info.timezone),
                    committer=cset_info.committer,
                    rev_id=cset_info.revision)



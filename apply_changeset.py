#!/usr/bin/env python
"""\
This contains the apply changset function for bzr
"""

import bzrlib

def apply_changeset(branch, from_file, auto_commit=False):
    from bzrlib.merge import merge_inner
    import sys, read_changeset


    cset_info, cset_tree, cset_inv = read_changeset.read_changeset(from_file)

    if auto_commit:
        from bzrlib.commit import commit
        if branch.last_patch() == cset_info.precursor:
            # This patch can be applied directly
            commit(branch, message = cset_info.message,
                    timestamp=float(cset_info.timestamp),
                    timezone=float(cset_info.timezone),
                    committer=cset_info.committer,
                    rev_id=cset_info.revision)



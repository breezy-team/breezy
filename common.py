#!/usr/bin/env python
"""\
Common entries, like strings, etc, for the changeset reading + writing code.
"""

header_str = 'Bazaar-NG (bzr) changeset v'
version = (0, 0, 5)

def get_header():
    return [
        header_str + '.'.join([str(v) for v in version]),
        'This changeset can be applied with bzr apply-changeset',
        ''
    ]

def canonicalize_revision(branch, revnos):
    """Turn some sort of revision information into a single
    set of from-to revision ids.

    A revision id can be None if there is no associated revison.

    :param revnos:  A list of revisions to lookup, should be at most 2 long
    :return: (old, new)
    """
    # If only 1 entry is given, then we assume we want just the
    # changeset between that entry and it's base (we assume parents[0])
    if len(revnos) == 0:
        revnos = [None, None]
    elif len(revnos) == 1:
        revnos = [None, revnos[0]]

    if revnos[1] is None:
        new = branch.last_patch()
    else:
        new = branch.lookup_revision(revnos[1])
    if revnos[0] is None:
        old = branch.get_revision(new).parents[0].revision_id
    else:
        old = branch.lookup_revision(revnos[0])

    return old, new


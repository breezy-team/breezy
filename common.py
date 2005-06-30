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

class ChangesetTree(object):
    """This class is designed to take a base tree, and re-create
    a final tree based on the information contained within a
    changeset.
    """

    def __init__(self, branch, changeset_info):
        """Initialize this ChangesetTree.

        :param branch:  This is where information will be acquired
                        and updated.
        :param changeset_info:  Information about a given changeset,
                                so that we can identify the base,
                                and other information.
        """
        self.branch = branch
        self.changeset_info = changeset_info

        self._build_tree()

    def _build_tree(self):
        """Build the final description of the tree, based on
        the changeset_info object.
        """
        
def format_highres_date(t, offset=0):
    """Format a date, such that it includes higher precision in the
    seconds field.

    :param t:   UTC time in fractional seconds
    :type t: float
    :param offset:  The timezone offset in integer seconds
    :type offset: int

    >>> from bzrlib.osutils import format_date
    >>> format_date(1120153132.350850105, 0)
    'Thu 2005-06-30 17:38:52 +0000'
    >>> format_highres_date(1120153132.350850105, 0)
    'Thu 2005-06-30 17:38:52.350850105 +0000'
    >>> format_date(1120153132.350850105, -5*3600)
    'Thu 2005-06-30 12:38:52 -0500'
    >>> format_highres_date(1120153132.350850105, -5*3600)
    'Thu 2005-06-30 12:38:52.350850105 -0500'
    """
    from bzrlib.errors import BzrError
    import time
    assert isinstance(t, float)
    
    # This has to be formatted for "original" date, so that the
    # revision XML entry will be reproduced faithfully.
    if offset == None:
        offset = 0
    tt = time.gmtime(t + offset)

    return (time.strftime("%a %Y-%m-%d %H:%M:%S", tt)
            + ('%.9f' % (t - int(t)))[1:] # Get the high-res seconds, but ignore the 0
            + ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))

def unpack_highres_date(date):
    """This takes the high-resolution date stamp, and
    converts it back into the tuple (timestamp, timezone)
    Where timestamp is in real seconds, and timezone is an integer
    number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string

    """

if __name__ == '__main__':
    import doctest
    doctest.testmod()

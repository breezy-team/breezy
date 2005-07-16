#!/usr/bin/env python
"""\
Common entries, like strings, etc, for the changeset reading + writing code.
"""

import bzrlib

header_str = 'Bazaar-NG changeset v'
version = (0, 0, 5)

def get_header():
    return [
        header_str + '.'.join([str(v) for v in version]),
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
        if new is None:
            old = None
        else:
            oldrev = branch.get_revision(new)
            if len(oldrev.parents) == 0:
                old = None
            else:
                old = oldrev.parents[0].revision_id
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
        self.base_tree = self.branch.revision_tree(self.changeset_info.base)
        
def guess_text_id(tree, file_id, rev_id, kind, modified=True):
    """This returns the estimated text_id for a given file.
    The idea is that in general the text_id should be the id last
    revision which modified the file.

    :param tree: This should be the base tree for a changeset, since that
                 is all the target has for guessing.
    :param file_id: The file id to guess the text_id for.
    :param rev_id: The target revision id
    :param modified: Was the file modified between base and target?
    """
    from bzrlib.errors import BzrError
    if kind == 'directory':
        return None
    if modified:
        # If the file was modified in an intermediate stage
        # (not in the final target), this won't be correct
        # but it is our best guess.
        # TODO: In the current code, text-ids are randomly generated
        # using the filename as the base. In the future they will
        # probably follow this format.
        return file_id + '-' + rev_id
    # The file was not actually modified in this changeset
    # so the text_id should be equal to it's previous value
    if not file_id in tree.inventory:
        raise BzrError('Unable to generate text_id for file_id {%s}'
            ', file does not exist in tree.' % file_id)
    # This is the last known text_id for this file
    # so assume that it is being used.
    return tree.inventory[file_id].text_id

def encode(s):
    """Take a unicode string, and make sure to escape it for
    use in a changeset.

    Note: It can be either a normal, or a unicode string

    >>> encode(u'abcdefg')
    'abcdefg'
    >>> encode(u'a b\\tc\\nd\\\\e')
    'a b\\tc\\nd\\\\e'
    >>> encode('a b\\tc\\nd\\e')
    'a b\\tc\\nd\\\\e'
    >>> encode(u'\\u1234\\u0020')
    '\\xe1\\x88\\xb4 '
    >>> encode('abcdefg')
    'abcdefg'
    >>> encode(u'')
    ''
    >>> encode('')
    ''
    """
    return s.encode('utf-8')

def decode(s):
    """Undo the encode operation, returning a unicode string.

    >>> decode('abcdefg')
    u'abcdefg'
    >>> decode('a b\\tc\\nd\\\\e')
    u'a b\\tc\\nd\\\\e'
    >>> decode('\\xe1\\x88\\xb4 ')
    u'\\u1234 '
    >>> for s in ('test', 'strings'):
    ...   if decode(encode(s)) != s:
    ...     print 'Failed: %r' % s # There should be no failures

    """
    return s.decode('utf-8')

def format_highres_date(t, offset=0):
    """Format a date, such that it includes higher precision in the
    seconds field.

    :param t:   The local time in fractional seconds since the epoch
    :type t: float
    :param offset:  The timezone offset in integer seconds
    :type offset: int

    Example: format_highres_date(time.time(), -time.timezone)
    this will return a date stamp for right now,
    formatted for the local timezone.

    >>> from bzrlib.osutils import format_date
    >>> format_date(1120153132.350850105, 0)
    'Thu 2005-06-30 17:38:52 +0000'
    >>> format_highres_date(1120153132.350850105, 0)
    'Thu 2005-06-30 17:38:52.350850105 +0000'
    >>> format_date(1120153132.350850105, -5*3600)
    'Thu 2005-06-30 12:38:52 -0500'
    >>> format_highres_date(1120153132.350850105, -5*3600)
    'Thu 2005-06-30 12:38:52.350850105 -0500'
    >>> format_highres_date(1120153132.350850105, 7200)
    'Thu 2005-06-30 19:38:52.350850105 +0200'
    """
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
    Where timestamp is in real UTC since epoch seconds, and timezone is an integer
    number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string

    >>> import time, random
    >>> unpack_highres_date('Thu 2005-06-30 12:38:52.350850105 -0500')
    (1120153132.3508501, -18000)
    >>> unpack_highres_date('Thu 2005-06-30 17:38:52.350850105 +0000')
    (1120153132.3508501, 0)
    >>> unpack_highres_date('Thu 2005-06-30 19:38:52.350850105 +0200')
    (1120153132.3508501, 7200)
    >>> from bzrlib.osutils import local_time_offset
    >>> t = time.time()
    >>> o = local_time_offset()
    >>> t2, o2 = unpack_highres_date(format_highres_date(t, o))
    >>> t == t2
    True
    >>> o == o2
    True
    >>> for count in xrange(500):
    ...   t += random.random()*24*3600*365*2 - 24*3600*364 # Random time within +/- 1 year
    ...   o = random.randint(-12,12)*3600 # Random timezone
    ...   date = format_highres_date(t, o)
    ...   t2, o2 = unpack_highres_date(date)
    ...   if t != t2 or o != o2:
    ...      print 'Failed on date %r, %s,%s diff:%s' % (date, t, o, t2-t)
    ...      break

    """
    import time, calendar
    # Up until the first period is a datestamp that is generated
    # as normal from time.strftime, so use time.strptime to
    # parse it
    dot_loc = date.find('.')
    if dot_loc == -1:
        raise ValueError('Date string does not contain high-precision seconds: %r' % date)
    base_time = time.strptime(date[:dot_loc], "%a %Y-%m-%d %H:%M:%S")
    fract_seconds, offset = date[dot_loc:].split()
    fract_seconds = float(fract_seconds)
    offset = int(offset)
    offset = int(offset / 100) * 3600 + offset % 100
    
    # time.mktime returns localtime, but calendar.timegm returns UTC time
    timestamp = calendar.timegm(base_time)
    timestamp -= offset
    # Add back in the fractional seconds
    timestamp += fract_seconds
    return (timestamp, offset)

if __name__ == '__main__':
    import doctest
    doctest.testmod()


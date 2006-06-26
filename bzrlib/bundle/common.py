#!/usr/bin/env python
"""\
Common entries, like strings, etc, for the bundle reading + writing code.
"""

import bzrlib

header_str = 'Bazaar revision bundle v'
version = (0, 8)


def get_header():
    return [
        header_str + '.'.join([str(v) for v in version]),
        ''
    ]

      
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
            + ('%.9f' % (t - int(t)))[1:] # Get the high-res seconds, but
                                          # ignore the 0
            + ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))


def unpack_highres_date(date):
    """This takes the high-resolution date stamp, and
    converts it back into the tuple (timestamp, timezone)
    Where timestamp is in real UTC since epoch seconds, and timezone is an
    integer number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string

    >>> import time
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
    """
    import time, calendar
    # Up until the first period is a datestamp that is generated
    # as normal from time.strftime, so use time.strptime to
    # parse it
    dot_loc = date.find('.')
    if dot_loc == -1:
        raise ValueError('Date string does not contain high-precision seconds:'
                         ' %r' % date)
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

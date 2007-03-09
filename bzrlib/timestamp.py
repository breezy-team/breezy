# Copyright (C) 2005, 2006, 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import calendar
import time


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
    >>> format_highres_date(1152428738.867522, 19800)
    'Sun 2006-07-09 12:35:38.867522001 +0530'
    """
    assert isinstance(t, float)

    # This has to be formatted for "original" date, so that the
    # revision XML entry will be reproduced faithfully.
    if offset is None:
        offset = 0
    tt = time.gmtime(t + offset)

    return (time.strftime("%a %Y-%m-%d %H:%M:%S", tt)
            # Get the high-res seconds, but ignore the 0
            + ('%.9f' % (t - int(t)))[1:]
            + ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))


def unpack_highres_date(date):
    """This takes the high-resolution date stamp, and
    converts it back into the tuple (timestamp, timezone)
    Where timestamp is in real UTC since epoch seconds, and timezone is an
    integer number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string

    >>> import time, random
    >>> unpack_highres_date('Thu 2005-06-30 12:38:52.350850105 -0500')
    (1120153132.3508501, -18000)
    >>> unpack_highres_date('Thu 2005-06-30 17:38:52.350850105 +0000')
    (1120153132.3508501, 0)
    >>> unpack_highres_date('Thu 2005-06-30 19:38:52.350850105 +0200')
    (1120153132.3508501, 7200)
    >>> unpack_highres_date('Sun 2006-07-09 12:35:38.867522001 +0530')
    (1152428738.867522, 19800)
    >>> from bzrlib.osutils import local_time_offset
    >>> t = time.time()
    >>> o = local_time_offset()
    >>> t2, o2 = unpack_highres_date(format_highres_date(t, o))
    >>> t == t2
    True
    >>> o == o2
    True
    >>> t -= 24*3600*365*2 # Start 2 years ago
    >>> o = -12*3600
    >>> for count in xrange(500):
    ...   t += random.random()*24*3600*30
    ...   o = ((o/3600 + 13) % 25 - 12)*3600 # Add 1 wrap around from [-12, 12]
    ...   date = format_highres_date(t, o)
    ...   t2, o2 = unpack_highres_date(date)
    ...   if t != t2 or o != o2:
    ...      print 'Failed on date %r, %s,%s diff:%s' % (date, t, o, t2-t)
    ...      break

    """
    # Up until the first period is a datestamp that is generated
    # as normal from time.strftime, so use time.strptime to
    # parse it
    dot_loc = date.find('.')
    if dot_loc == -1:
        raise ValueError(
            'Date string does not contain high-precision seconds: %r' % date)
    base_time = time.strptime(date[:dot_loc], "%a %Y-%m-%d %H:%M:%S")
    fract_seconds, offset = date[dot_loc:].split()
    fract_seconds = float(fract_seconds)

    offset = int(offset)

    hours = int(offset / 100)
    minutes = (offset % 100)
    seconds_offset = (hours * 3600) + (minutes * 60)

    # time.mktime returns localtime, but calendar.timegm returns UTC time
    timestamp = calendar.timegm(base_time)
    timestamp -= seconds_offset
    # Add back in the fractional seconds
    timestamp += fract_seconds
    return (timestamp, seconds_offset)


def format_patch_date(secs, offset=0):
    """Format a POSIX timestamp and optional offset as a patch-style date.

    Inverse of parse_patch_date.
    """
    assert offset % 36 == 0
    tm = time.gmtime(secs+offset)
    time_str = time.strftime('%Y-%m-%d %H:%M:%S', tm)
    return '%s %+05d' % (time_str, abs(offset/36))


def parse_patch_date(date_str):
    """Parse a patch-style date into a POSIX timestamp and offset.

    Inverse of format_patch_date.
    """
    secs_str = date_str[:-6]
    offset_str = date_str[-6:]
    offset = int(offset_str) * 36
    tm_time = time.strptime(secs_str, '%Y-%m-%d %H:%M:%S')
    # adjust seconds according to offset before converting to POSIX
    # timestamp, to avoid edge problems
    tm_time = tm_time[:5] + (tm_time[5] - offset,) + tm_time[6:]
    secs = calendar.timegm(tm_time)
    return secs, offset

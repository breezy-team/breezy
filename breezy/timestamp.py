# Copyright (C) 2007, 2008, 2009, 2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import calendar
import time
import re

from . import osutils


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

    >>> from breezy.osutils import format_date
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
    if not isinstance(t, float):
        raise ValueError(t)

    # This has to be formatted for "original" date, so that the
    # revision XML entry will be reproduced faithfully.
    if offset is None:
        offset = 0
    tt = time.gmtime(t + offset)

    return (osutils.weekdays[tt[6]] + time.strftime(" %Y-%m-%d %H:%M:%S", tt) +
            # Get the high-res seconds, but ignore the 0
            ('%.9f' % (t - int(t)))[1:] +
            ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))


def unpack_highres_date(date):
    """This takes the high-resolution date stamp, and
    converts it back into the tuple (timestamp, timezone)
    Where timestamp is in real UTC since epoch seconds, and timezone is an
    integer number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string

    """
    # Weekday parsing is locale sensitive, so drop the weekday
    space_loc = date.find(' ')
    if space_loc == -1 or date[:space_loc] not in osutils.weekdays:
        raise ValueError(
            'Date string does not contain a day of week: %r' % date)
    # Up until the first period is a datestamp that is generated
    # as normal from time.strftime, so use time.strptime to
    # parse it
    dot_loc = date.find('.')
    if dot_loc == -1:
        raise ValueError(
            'Date string does not contain high-precision seconds: %r' % date)
    base_time = time.strptime(date[space_loc:dot_loc], " %Y-%m-%d %H:%M:%S")
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
    if offset % 60 != 0:
        raise ValueError(
            "can't represent timezone %s offset by fractional minutes" % offset)
    # so that we don't need to do calculations on pre-epoch times,
    # which doesn't work with win32 python gmtime, we always
    # give the epoch in utc
    if secs == 0:
        offset = 0
    if secs + offset < 0:
        from warnings import warn
        warn("gmtime of negative time (%s, %s) may not work on Windows" %
             (secs, offset))
    return osutils.format_date(secs, offset=offset,
                               date_fmt='%Y-%m-%d %H:%M:%S')


# Format for patch dates: %Y-%m-%d %H:%M:%S [+-]%H%M
# Groups: 1 = %Y-%m-%d %H:%M:%S; 2 = [+-]%H; 3 = %M
RE_PATCHDATE = re.compile(
    "(\\d+-\\d+-\\d+\\s+\\d+:\\d+:\\d+)\\s*([+-]\\d\\d)(\\d\\d)$")
RE_PATCHDATE_NOOFFSET = re.compile("\\d+-\\d+-\\d+\\s+\\d+:\\d+:\\d+$")


def parse_patch_date(date_str):
    """Parse a patch-style date into a POSIX timestamp and offset.

    Inverse of format_patch_date.
    """
    match = RE_PATCHDATE.match(date_str)
    if match is None:
        if RE_PATCHDATE_NOOFFSET.match(date_str) is not None:
            raise ValueError("time data %r is missing a timezone offset"
                             % date_str)
        else:
            raise ValueError("time data %r does not match format " % date_str +
                             "'%Y-%m-%d %H:%M:%S %z'")
    secs_str = match.group(1)
    offset_hours, offset_mins = int(match.group(2)), int(match.group(3))
    if abs(offset_hours) >= 24 or offset_mins >= 60:
        raise ValueError("invalid timezone %r" %
                         (match.group(2) + match.group(3)))
    offset = offset_hours * 3600 + offset_mins * 60
    tm_time = time.strptime(secs_str, '%Y-%m-%d %H:%M:%S')
    # adjust seconds according to offset before converting to POSIX
    # timestamp, to avoid edge problems
    tm_time = tm_time[:5] + (tm_time[5] - offset,) + tm_time[6:]
    secs = calendar.timegm(tm_time)
    return secs, offset

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
import re
import time

from . import osutils
from ._osutils_rs import format_highres_date, unpack_highres_date


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

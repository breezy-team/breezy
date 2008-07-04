# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bisect
from bzrlib import urlutils
from bzrlib.errors import BzrError


class InvalidExternalsDescription(BzrError):
    _fmt = """Unable to parse externals description."""


def is_valid_property_name(prop):
    if not prop[0].isalnum() and not prop[0] in ":_":
        return False
    for c in prop[1:]:
        if not c.isalnum() and not c in "-:._":
            return False
    return True

def time_to_cstring(timestamp):
    import time
    tm_usec = timestamp % 1000000
    (tm_year, tm_mon, tm_mday, tm_hour, tm_min, 
            tm_sec, tm_wday, tm_yday, tm_isdst) = time.gmtime(timestamp / 1000000)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%06dZ" % (tm_year, tm_mon, tm_mday, tm_hour, tm_min, tm_sec, tm_usec)

def time_from_cstring(text):
    import time
    (basestr, usecstr) = text.split(".", 1)
    assert usecstr[-1] == "Z"
    tm_usec = int(usecstr[:-1])
    tm = time.strptime(basestr, "%Y-%m-%dT%H:%M:%S")
    return (long(time.mktime((tm[0], tm[1], tm[2], tm[3], tm[4], tm[5], tm[6], tm[7], -1)) - time.timezone) * 1000000 + tm_usec)


def parse_externals_description(base_url, val):
    """Parse an svn:externals property value.

    :param base_url: URL on which the property is set. Used for 
        relative externals.

    :returns: dictionary with local names as keys, (revnum, url)
              as value. revnum is the revision number and is 
              set to None if not applicable.
    """
    ret = {}
    for l in val.splitlines():
        if l == "" or l[0] == "#":
            continue
        pts = l.rsplit(None, 2) 
        if len(pts) == 3:
            if not pts[1].startswith("-r"):
                raise InvalidExternalsDescription()
            ret[pts[0]] = (int(pts[1][2:]), urlutils.join(base_url, pts[2]))
        elif len(pts) == 2:
            if pts[1].startswith("//"):
                raise NotImplementedError("Relative to the scheme externals not yet supported")
            if pts[1].startswith("^/"):
                raise NotImplementedError("Relative to the repository root externals not yet supported")
            ret[pts[0]] = (None, urlutils.join(base_url, pts[1]))
        else:
            raise InvalidExternalsDescription()
    return ret


def parse_mergeinfo_property(text):
    ret = {}
    for l in text.splitlines():
        (path, ranges) = l.rsplit(":",1)
        assert path.startswith("/")
        ret[path] = []
        for range in ranges.split(","):
            if range[-1] == "*":
                inheritable = False
                range = range[:-1]
            else:
                inheritable = True
            try:
                (start, end) = range.split("-", 1)
                ret[path].append((int(start), int(end), inheritable))
            except ValueError:
                ret[path].append((int(range), int(range), inheritable))

    return ret


def generate_mergeinfo_property(merges):
    def formatrange((start, end, inheritable)):
        suffix = ""
        if not inheritable:
            suffix = "*"
        if start == end:
            return "%d%s" % (start, suffix)
        else:
            return "%d-%d%s" % (start, end, suffix)
    text = ""
    for (path, ranges) in merges.items():
        assert path.startswith("/")
        text += "%s:%s\n" % (path, ",".join(map(formatrange, ranges)))
    return text


def range_includes_revnum(ranges, revnum):
    i = bisect.bisect(ranges, (revnum, revnum, True))
    if i == 0:
        return False
    (start, end, inheritable) = ranges[i-1]
    return (start <= revnum <= end)


def range_add_revnum(ranges, revnum, inheritable=True):
    # TODO: Deal with inheritable
    item = (revnum, revnum, inheritable)
    if len(ranges) == 0:
        ranges.append(item)
        return ranges
    i = bisect.bisect(ranges, item)
    if i > 0:
        (start, end, inh) = ranges[i-1]
        if (start <= revnum <= end):
            # already there
            return ranges
        if end == revnum-1:
            # Extend previous range
            ranges[i-1] = (start, end+1, inh)
            return ranges
    if i < len(ranges):
        (start, end, inh) = ranges[i]
        if start-1 == revnum:
            # Extend next range
            ranges[i] = (start-1, end, inh)
            return ranges
    ranges.insert(i, item)
    return ranges


def mergeinfo_includes_revision(merges, path, revnum):
    assert path.startswith("/")
    try:
        ranges = merges[path]
    except KeyError:
        return False

    return range_includes_revnum(ranges, revnum)


def mergeinfo_add_revision(mergeinfo, path, revnum):
    assert path.startswith("/")
    mergeinfo[path] = range_add_revnum(mergeinfo.get(path, []), revnum)
    return mergeinfo


PROP_EXECUTABLE = 'svn:executable'
PROP_EXECUTABLE_VALUE = '*'
PROP_EXTERNALS = 'svn:externals'
PROP_IGNORE = 'svn:ignore'
PROP_KEYWORDS = 'svn:keywords'
PROP_MIME_TYPE = 'svn:mime-type'
PROP_MERGEINFO = 'svn:mergeinfo'
PROP_NEEDS_LOCK = 'svn:needs-lock'
PROP_NEEDS_LOCK_VALUE = '*'
PROP_PREFIX = 'svn:'
PROP_SPECIAL = 'svn:special'
PROP_SPECIAL_VALUE = '*'
PROP_WC_PREFIX = 'svn:wc:'
PROP_ENTRY_COMMITTED_DATE = 'svn:entry:committed-date'
PROP_ENTRY_COMMITTED_REV = 'svn:entry:committed-rev'
PROP_ENTRY_LAST_AUTHOR = 'svn:entry:last-author'
PROP_ENTRY_LOCK_TOKEN = 'svn:entry:lock-token'
PROP_ENTRY_UUID = 'svn:entry:uuid'

PROP_REVISION_LOG = "svn:log"
PROP_REVISION_AUTHOR = "svn:author"
PROP_REVISION_DATE = "svn:date"

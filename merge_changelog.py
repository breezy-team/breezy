#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright ? 2008 Canonical Ltd.
# Author: Scott James Remnant <scott@ubuntu.com>.
# Hacked up by: Bryce Harrington <bryce@ubuntu.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re

from bzrlib import (
    merge,
    )

class ChangeLogFileMerge(merge.ConfigurableFileMerger):

    name_prefix = 'deb_changelog'
    default_files = ['debian/changelog']

    def merge_text(self, params):
        return 'success', merge_changelog(params.this_lines, params.other_lines)


########################################################################
# Changelog Management
########################################################################

# Regular expression for top of debian/changelog
CL_RE = re.compile(r'^(\w[-+0-9a-z.]*) \(([^\(\) \t]+)\)((\s+[-0-9a-z]+)+)\;',
                   re.IGNORECASE)

def merge_changelog(left_changelog_lines, right_changelog_lines):
    """Merge a changelog file."""

    left_cl = read_changelog(left_changelog_lines)
    right_cl = read_changelog(right_changelog_lines)

    content = []
    # TODO: This is not a 3-way merge, but a 2-way merge
    #       The resolution is currently 'if left and right have texts that have
    #       the same "version" string, use left', aka "prefer-mine".
    #       We could introduce BASE, and cause conflicts, or appropriately
    #       resolve, etc.
    #       Note also that this code is only invoked when there is a
    #       left-and-right change, so merging a pure-right change will take all
    #       changes.
    for right_ver, right_text in right_cl:
        while len(left_cl) and left_cl[0][0] > right_ver:
            (left_ver, left_text) = left_cl.pop(0)
            content.append(left_text)
            content.append('\n')

        while len(left_cl) and left_cl[0][0] == right_ver:
            (left_ver, left_text) = left_cl.pop(0)

        content.append(right_text)
        content.append('\n')

    for left_ver, left_text in left_cl:
        content.append(left_text)
        content.append('\n')
	    
    return content


def read_changelog(lines):
    """Return a parsed changelog file."""
    entries = []

    (ver, text) = (None, "")
    for line in lines:
        match = CL_RE.search(line)
        if match:
            try:
                ver = Version(match.group(2))
            except ValueError:
                ver = None

            text += line
        elif line.startswith(" -- "):
            if ver is None:
                ver = Version("0")

            text += line
            entries.append((ver, text))
            (ver, text) = (None, "")
        elif len(line.strip()) or ver is not None:
            text += line

    if len(text):
        entries.append((ver, text))

    return entries

########################################################################
# Version parsing code
########################################################################
# Regular expressions make validating things easy
valid_epoch = re.compile(r'^[0-9]+$')
valid_upstream = re.compile(r'^[A-Za-z0-9+:.~-]*$')
valid_revision = re.compile(r'^[A-Za-z0-9+.~]+$')

# Character comparison table for upstream and revision components
cmp_table = "~ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+-.:"


class Version(object):
    """Debian version number.

    This class is designed to be reasonably transparent and allow you
    to write code like:

    |   s.version >= '1.100-1'

    The comparison will be done according to Debian rules, so '1.2' will
    compare lower.

    Properties:
      epoch       Epoch
      upstream    Upstream version
      revision    Debian/local revision
    """

    def __init__(self, ver):
        """Parse a string or number into the three components."""
        self.epoch = 0
        self.upstream = None
        self.revision = None

        ver = str(ver)
        if not len(ver):
            raise ValueError

        # Epoch is component before first colon
        idx = ver.find(":")
        if idx != -1:
            self.epoch = ver[:idx]
            if not len(self.epoch):
                raise ValueError
            if not valid_epoch.search(self.epoch):
                raise ValueError
            ver = ver[idx+1:]

        # Revision is component after last hyphen
        idx = ver.rfind("-")
        if idx != -1:
            self.revision = ver[idx+1:]
            if not len(self.revision):
                raise ValueError
            if not valid_revision.search(self.revision):
                raise ValueError
            ver = ver[:idx]

        # Remaining component is upstream
        self.upstream = ver
        if not len(self.upstream):
            raise ValueError
        if not valid_upstream.search(self.upstream):
            raise ValueError

        self.epoch = int(self.epoch)

    def getWithoutEpoch(self):
        """Return the version without the epoch."""
        str = self.upstream
        if self.revision is not None:
            str += "-%s" % (self.revision,)
        return str

    without_epoch = property(getWithoutEpoch)

    def __str__(self):
        """Return the class as a string for printing."""
        str = ""
        if self.epoch > 0:
            str += "%d:" % (self.epoch,)
        str += self.upstream
        if self.revision is not None:
            str += "-%s" % (self.revision,)
        return str

    def __repr__(self):
        """Return a debugging representation of the object."""
        return "<%s epoch: %d, upstream: %r, revision: %r>" \
               % (self.__class__.__name__, self.epoch,
                  self.upstream, self.revision)

    def __cmp__(self, other):
        """Compare two Version classes."""
        other = Version(other)

        result = cmp(self.epoch, other.epoch)
        if result != 0: return result

        result = deb_cmp(self.upstream, other.upstream)
        if result != 0: return result

        result = deb_cmp(self.revision or "", other.revision or "")
        if result != 0: return result

        return 0


def strcut(str, idx, accept):
    """Cut characters from str that are entirely in accept."""
    ret = ""
    while idx < len(str) and str[idx] in accept:
        ret += str[idx]
        idx += 1

    return (ret, idx)

def deb_order(str, idx):
    """Return the comparison order of two characters."""
    if idx >= len(str):
        return 0
    elif str[idx] == "~":
        return -1
    else:
        return cmp_table.index(str[idx])

def deb_cmp_str(x, y):
    """Compare two strings in a deb version."""
    idx = 0
    while (idx < len(x)) or (idx < len(y)):
        result = deb_order(x, idx) - deb_order(y, idx)
        if result < 0:
            return -1
        elif result > 0:
            return 1

        idx += 1

    return 0

def deb_cmp(x, y):
    """Implement the string comparison outlined by Debian policy."""
    x_idx = y_idx = 0
    while x_idx < len(x) or y_idx < len(y):
        # Compare strings
        (x_str, x_idx) = strcut(x, x_idx, cmp_table)
        (y_str, y_idx) = strcut(y, y_idx, cmp_table)
        result = deb_cmp_str(x_str, y_str)
        if result != 0: return result

        # Compare numbers
        (x_str, x_idx) = strcut(x, x_idx, "0123456789")
        (y_str, y_idx) = strcut(y, y_idx, "0123456789")
        result = cmp(int(x_str or "0"), int(y_str or "0"))
        if result != 0: return result

    return 0

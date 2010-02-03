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

from debian_bundle import changelog

class ChangeLogFileMerge(merge.ConfigurableFileMerger):

    name_prefix = 'deb_changelog'
    default_files = ['debian/changelog']

    def merge_text(self, params):
        return 'success', merge_changelog(params.this_lines, params.other_lines)


# Regular expression for top of debian/changelog
CL_RE = re.compile(r'^(\w[-+0-9a-z.]*) \(([^\(\) \t]+)\)((\s+[-0-9a-z]+)+)\;',
                   re.IGNORECASE)

def merge_changelog(this_lines, other_lines, base_lines=[]):
    """Merge a changelog file."""

    left_cl = read_changelog(this_lines)
    right_cl = read_changelog(other_lines)
    base_cl = read_changelog(base_lines)

    content = []
    def step(iterator):
        try:
            return iterator.next()
        except StopIteration:
            return None
    left_blocks = sorted(left_cl._blocks, key=lambda x:x.version, reverse=True)
    left_blocks = iter(left_blocks)
    right_blocks = sorted(right_cl._blocks, key=lambda x:x.version, reverse=True)
    right_blocks = iter(right_blocks)
    base_blocks = dict((b.version, b) for b in base_cl._blocks)
    left_block = step(left_blocks)
    right_block = step(right_blocks)

    # TODO: This is not a 3-way merge, but a 2-way merge
    #       The resolution is currently 'if left and right have texts that have
    #       the same "version" string, use left', aka "prefer-mine".
    #       We could introduce BASE, and cause conflicts, or appropriately
    #       resolve, etc.
    #       Note also that this code is only invoked when there is a
    #       left-and-right change, so merging a pure-right change will take all
    #       changes.
    while not (left_block is None and right_block is None):
        if left_block is None:
            next_block = right_block
            right_block = step(right_blocks)
        elif right_block is None:
            next_block = left_block
            left_block = step(left_blocks)
        elif left_block.version == right_block.version:
            # Same version, step both
            # TODO: Conflict if left != right
            next_block = left_block
            left_block = step(left_blocks)
            right_block = step(right_blocks)
        elif left_block.version > right_block.version:
            # left comes first
            next_block = left_block
            left_block = step(left_blocks)
        else:
            # right block must come first
            assert right_block.version > left_block.version
            next_block = right_block
            right_block = step(right_blocks)
        content.append(str(next_block))

    return content


def read_changelog(lines):
    """Return a parsed changelog file."""
    # Note: There appears to be a bug in Changelog if you pass it an iterable
    #       of lines (like a file obj, or a list of lines). Specifically, it
    #       does not strip trailing newlines, and it adds ones back in, so you
    #       get doubled blank lines... :(
    #       So we just ''.join() the lines and don't worry about it
    content = ''.join(lines)
    if not content:
        # We get a warning if we try to parse an empty changelog file
        return changelog.Changelog()
    # TODO: import_dsc uses strict=False, it would be nice to try strict=True
    #       as the default
    return changelog.Changelog(content, strict=False)

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
    merge3,
    )

from debian_bundle import changelog

class ChangeLogFileMerge(merge.ConfigurableFileMerger):

    name_prefix = 'deb_changelog'
    default_files = ['debian/changelog']

    def merge_text(self, params):
        return merge_changelog(params.this_lines, params.other_lines,
                               params.base_lines)


# Regular expression for top of debian/changelog
CL_RE = re.compile(r'^(\w[-+0-9a-z.]*) \(([^\(\) \t]+)\)((\s+[-0-9a-z]+)+)\;',
                   re.IGNORECASE)

def merge_changelog(this_lines, other_lines, base_lines=[]):
    """Merge a changelog file."""

    try:
        left_cl = read_changelog(this_lines)
        right_cl = read_changelog(other_lines)
        base_cl = read_changelog(base_lines)
    except changelog.ChangelogParseError:
        return ('not_applicable', None)

    content = []
    def step(iterator):
        try:
            return iterator.next()
        except StopIteration:
            return None
    left_blocks = dict((b.version, b) for b in left_cl._blocks)
    right_blocks = dict((b.version, b) for b in right_cl._blocks)
    # Unfortunately, while version objects implement __eq__ they *don't*
    # implement __hash__, which means we can't do dict lookups properly, so
    # instead, we fall back on the version string instead of the object.
    # Make sure never to try to use right_version in left_blocks because of
    # this.
    base_blocks = dict((b.version.full_version, b) for b in base_cl._blocks)
    left_order = iter(sorted(left_blocks.keys(), reverse=True))
    right_order = iter(sorted(right_blocks.keys(), reverse=True))
    left_version = step(left_order)
    right_version = step(right_order)

    # TODO: Do we want to support the ability to delete a section? We could do
    #       a first-pass algorithm that checks the versions in base versus the
    #       versions in this and other, to determine what versions should be in
    #       the output. For now, we just assume that if a version is present in
    #       any of this or other, then we want it in the output.
    conflict_status = 'success'

    while left_version is not None or right_version is not None:
        if (left_version is None or
            (right_version is not None and right_version > left_version)):
            next_content = str(right_blocks[right_version])
            right_version = step(right_order)
        elif (right_version is None or
            (left_version is not None and left_version > right_version)):
            next_content = str(left_blocks[left_version])
            left_version = step(left_order)
        else:
            assert left_version == right_version
            # Same version, step both
            # TODO: Conflict if left_version != right
            # Note: See above comment why we can't use
            #       right_blocks[left_version] even though they *should* be
            #       equivalent
            left_content = str(left_blocks[left_version])
            right_content = str(right_blocks[right_version])
            if left_content == right_content:
                # Identical content
                next_content = left_content
            else:
                # Sides disagree, compare with base
                if left_version.full_version in base_blocks:
                    base_content = str(base_blocks[left_version.full_version])
                else:
                    base_content = ''
                if left_content == base_content:
                    next_content = right_content
                elif right_content == base_content:
                    next_content = left_content
                else:
                    # TODO: We could use merge3.Merge3 to try a line-based
                    #       textual merge on the content. However, for now I'm
                    #       just going to conflict on the whole region
                    # Conflict names taken from merge.py
                    next_content = ('<<<<<<< TREE\n'
                                    + left_content
                                    + '=======\n'
                                    + right_content
                                    + '>>>>>>> MERGE-SOURCE\n'
                                   )
                    conflict_status = 'conflicted'
            next_block = left_blocks[left_version]
            left_version = step(left_order)
            right_version = step(right_order)
        content.append(next_content)

    return conflict_status, content


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
    return changelog.Changelog(content, strict=True)

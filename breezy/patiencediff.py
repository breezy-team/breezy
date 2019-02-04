#!/usr/bin/env python
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from __future__ import absolute_import

from .lazy_import import lazy_import
lazy_import(globals(), """
import os
import sys
import time
import difflib
""")


__all__ = ['PatienceSequenceMatcher', 'unified_diff', 'unified_diff_bytes',
           'unified_diff_files']


# This is a version of unified_diff which only adds a factory parameter
# so that you can override the default SequenceMatcher
# this has been submitted as a patch to python
def unified_diff(a, b, fromfile='', tofile='', fromfiledate='',
                 tofiledate='', n=3, lineterm='\n',
                 sequencematcher=None):
    r"""
    Compare two sequences of lines; generate the delta as a unified diff.

    Unified diffs are a compact way of showing line changes and a few
    lines of context.  The number of context lines is set by 'n' which
    defaults to three.

    By default, the diff control lines (those with ---, +++, or @@) are
    created with a trailing newline.  This is helpful so that inputs
    created from file.readlines() result in diffs that are suitable for
    file.writelines() since both the inputs and outputs have trailing
    newlines.

    For inputs that do not have trailing newlines, set the lineterm
    argument to "" so that the output will be uniformly newline free.

    The unidiff format normally has a header for filenames and modification
    times.  Any or all of these may be specified using strings for
    'fromfile', 'tofile', 'fromfiledate', and 'tofiledate'.  The modification
    times are normally expressed in the format returned by time.ctime().

    Example:

    >>> for line in unified_diff('one two three four'.split(),
    ...             'zero one tree four'.split(), 'Original', 'Current',
    ...             'Sat Jan 26 23:30:50 1991', 'Fri Jun 06 10:20:52 2003',
    ...             lineterm=''):
    ...     print line
    --- Original Sat Jan 26 23:30:50 1991
    +++ Current Fri Jun 06 10:20:52 2003
    @@ -1,4 +1,4 @@
    +zero
     one
    -two
    -three
    +tree
     four
    """
    if sequencematcher is None:
        sequencematcher = difflib.SequenceMatcher

    if fromfiledate:
        fromfiledate = '\t' + str(fromfiledate)
    if tofiledate:
        tofiledate = '\t' + str(tofiledate)

    started = False
    for group in sequencematcher(None, a, b).get_grouped_opcodes(n):
        if not started:
            yield '--- %s%s%s' % (fromfile, fromfiledate, lineterm)
            yield '+++ %s%s%s' % (tofile, tofiledate, lineterm)
            started = True
        i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
        yield "@@ -%d,%d +%d,%d @@%s" % (i1 + 1, i2 - i1, j1 + 1, j2 - j1, lineterm)
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                for line in a[i1:i2]:
                    yield ' ' + line
                continue
            if tag == 'replace' or tag == 'delete':
                for line in a[i1:i2]:
                    yield '-' + line
            if tag == 'replace' or tag == 'insert':
                for line in b[j1:j2]:
                    yield '+' + line


def unified_diff_bytes(a, b, fromfile=b'', tofile=b'', fromfiledate=b'',
                       tofiledate=b'', n=3, lineterm=b'\n', sequencematcher=None):
    r"""
    Compare two sequences of lines; generate the delta as a unified diff.

    Unified diffs are a compact way of showing line changes and a few
    lines of context.  The number of context lines is set by 'n' which
    defaults to three.

    By default, the diff control lines (those with ---, +++, or @@) are
    created with a trailing newline.  This is helpful so that inputs
    created from file.readlines() result in diffs that are suitable for
    file.writelines() since both the inputs and outputs have trailing
    newlines.

    For inputs that do not have trailing newlines, set the lineterm
    argument to "" so that the output will be uniformly newline free.

    The unidiff format normally has a header for filenames and modification
    times.  Any or all of these may be specified using strings for
    'fromfile', 'tofile', 'fromfiledate', and 'tofiledate'.  The modification
    times are normally expressed in the format returned by time.ctime().

    Example:

    >>> for line in bytes_unified_diff(b'one two three four'.split(),
    ...             b'zero one tree four'.split(), b'Original', b'Current',
    ...             b'Sat Jan 26 23:30:50 1991', b'Fri Jun 06 10:20:52 2003',
    ...             lineterm=b''):
    ...     print line
    --- Original Sat Jan 26 23:30:50 1991
    +++ Current Fri Jun 06 10:20:52 2003
    @@ -1,4 +1,4 @@
    +zero
     one
    -two
    -three
    +tree
     four
    """
    if sequencematcher is None:
        sequencematcher = difflib.SequenceMatcher

    if fromfiledate:
        fromfiledate = b'\t' + bytes(fromfiledate)
    if tofiledate:
        tofiledate = b'\t' + bytes(tofiledate)

    started = False
    for group in sequencematcher(None, a, b).get_grouped_opcodes(n):
        if not started:
            yield b'--- %s%s%s' % (fromfile, fromfiledate, lineterm)
            yield b'+++ %s%s%s' % (tofile, tofiledate, lineterm)
            started = True
        i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
        yield b"@@ -%d,%d +%d,%d @@%s" % (i1 + 1, i2 - i1, j1 + 1, j2 - j1, lineterm)
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                for line in a[i1:i2]:
                    yield b' ' + line
                continue
            if tag == 'replace' or tag == 'delete':
                for line in a[i1:i2]:
                    yield b'-' + line
            if tag == 'replace' or tag == 'insert':
                for line in b[j1:j2]:
                    yield b'+' + line


def unified_diff_files(a, b, sequencematcher=None):
    """Generate the diff for two files.
    """
    # Should this actually be an error?
    if a == b:
        return []
    if a == '-':
        file_a = sys.stdin
        time_a = time.time()
    else:
        file_a = open(a, 'rb')
        time_a = os.stat(a).st_mtime

    if b == '-':
        file_b = sys.stdin
        time_b = time.time()
    else:
        file_b = open(b, 'rb')
        time_b = os.stat(b).st_mtime

    # TODO: Include fromfiledate and tofiledate
    return unified_diff_bytes(file_a.readlines(), file_b.readlines(),
                              fromfile=a, tofile=b,
                              sequencematcher=sequencematcher)


try:
    from ._patiencediff_c import (
        unique_lcs_c as unique_lcs,
        recurse_matches_c as recurse_matches,
        PatienceSequenceMatcher_c as PatienceSequenceMatcher
        )
except ImportError:
    from ._patiencediff_py import (
        unique_lcs_py as unique_lcs,
        recurse_matches_py as recurse_matches,
        PatienceSequenceMatcher_py as PatienceSequenceMatcher
        )  # noqa: F401


def main(args):
    import optparse
    p = optparse.OptionParser(usage='%prog [options] file_a file_b'
                                    '\nFiles can be "-" to read from stdin')
    p.add_option('--patience', dest='matcher', action='store_const', const='patience',
                 default='patience', help='Use the patience difference algorithm')
    p.add_option('--difflib', dest='matcher', action='store_const', const='difflib',
                 default='patience', help='Use python\'s difflib algorithm')

    algorithms = {'patience': PatienceSequenceMatcher,
                  'difflib': difflib.SequenceMatcher}

    (opts, args) = p.parse_args(args)
    matcher = algorithms[opts.matcher]

    if len(args) != 2:
        print('You must supply 2 filenames to diff')
        return -1

    for line in unified_diff_files(args[0], args[1], sequencematcher=matcher):
        sys.stdout.write(line)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

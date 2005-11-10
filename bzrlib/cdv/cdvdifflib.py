# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from nofrillsprecisemerge import recurse_matches
from bzrlib.errors import BzrError
import difflib

__all__ = ['SequenceMatcher', 'unified_diff']

class SequenceMatcher(difflib.SequenceMatcher):
    """Compare a pair of sequences using longest common subset."""

    def __init__(self, isjunk=None, a='', b=''):
        if isjunk is not None:
            raise NotImplementedError('Currently we do not support'
                                      ' isjunk for sequence matching')
        difflib.SequenceMatcher.__init__(self, isjunk, a, b)

    def _check_with_diff(self, alo, ahi, blo, bhi, answer):
        """Use the original diff algorithm on an unmatched section.

        This will check to make sure the range is worth checking,
        before doing any work.

        :param alo: The last line that actually matched
        :param ahi: The next line that actually matches
        :param blo: Same as alo, only for the 'b' set
        :param bhi: Same as ahi
        :param answer: An array which will have the new ranges appended to it
        :return: None
        """
        # WORKAROUND
        # recurse_matches has an implementation design
        # which does not match non-unique lines in the
        # if they do not touch matching unique lines
        # so we rerun the regular diff algorithm
        # if find a large enough chunk.

        # recurse_matches already looked at the direct
        # neighbors, so we only need to run if there is
        # enough space to do so
        if ahi - alo > 2 and bhi - blo > 2:
            a = self.a[alo+1:bhi-1]
            b = self.b[blo+1:bhi-1]
            m = difflib.SequenceMatcher(None, a, b)
            new_blocks = m.get_matching_blocks()
            # difflib always adds a final match
            new_blocks.pop()
            for blk in new_blocks:
                answer.append((blk[0]+alo+1,
                               blk[1]+blo+1,
                               blk[2]))

    def __helper(self, alo, ahi, blo, bhi, answer):
        matches = []
        a = self.a[alo:ahi]
        b = self.b[blo:bhi]
        recurse_matches(a, b, len(a), len(b), matches, 10)
        # Matches now has individual line pairs of
        # line A matches line B, at the given offsets

        start_a = start_b = None
        length = 0
        for i_a, i_b in matches:
            if (start_a is not None
                and (i_a == start_a + length) 
                and (i_b == start_b + length)):
                length += 1
            else:
                # New block
                if start_a is None:
                    # We need to check from 0,0 until the current match
                    self._check_with_diff(alo-1, i_a+alo, blo-1, i_b+blo, answer)
                else:
                    answer.append((start_a+alo, start_b+blo, length))
                    self._check_with_diff(start_a+alo+length, i_a+alo,
                                          start_b+blo+length, i_b+blo,
                                          answer)

                start_a = i_a
                start_b = i_b
                length = 1

        if length != 0:
            answer.append((start_a+alo, start_b+blo, length))
            self._check_with_diff(start_a+alo+length, ahi+1,
                                  start_b+blo+length, bhi+1,
                                  answer)
        if not matches:
            # Nothing matched, so we need to send the complete text
            self._check_with_diff(alo-1, ahi+1, blo-1, bhi+1, answer)

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

    started = False
    for group in sequencematcher(None,a,b).get_grouped_opcodes(n):
        if not started:
            yield '--- %s %s%s' % (fromfile, fromfiledate, lineterm)
            yield '+++ %s %s%s' % (tofile, tofiledate, lineterm)
            started = True
        i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
        yield "@@ -%d,%d +%d,%d @@%s" % (i1+1, i2-i1, j1+1, j2-j1, lineterm)
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


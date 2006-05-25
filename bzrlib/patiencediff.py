#!/usr/bin/env python
# Copyright (C) 2005 Bram Cohen, Copyright (C) 2005, 2006 Canonical Ltd
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


from bisect import bisect
from copy import copy
import difflib
import os
import sys
import time


__all__ = ['SequenceMatcher', 'unified_diff', 'unified_diff_files']


def unique_lcs(a, b):
    """Find the longest common subset for unique lines.

    :param a: An indexable object (such as string or list of strings)
    :param b: Another indexable object (such as string or list of strings)
    :return: A list of tuples, one for each line which is matched.
            [(line_in_a, line_in_b), ...]

    This only matches lines which are unique on both sides.
    This helps prevent common lines from over influencing match
    results.
    The longest common subset uses the Patience Sorting algorithm:
    http://en.wikipedia.org/wiki/Patience_sorting
    """
    # set index[line in a] = position of line in a unless
    # unless a is a duplicate, in which case it's set to None
    index = {}
    for i in xrange(len(a)):
        line = a[i]
        if line in index:
            index[line] = None
        else:
            index[line]= i
    # make btoa[i] = position of line i in a, unless
    # that line doesn't occur exactly once in both, 
    # in which case it's set to None
    btoa = [None] * len(b)
    index2 = {}
    for pos, line in enumerate(b):
        next = index.get(line)
        if next is not None:
            if line in index2:
                # unset the previous mapping, which we now know to
                # be invalid because the line isn't unique
                btoa[index2[line]] = None
                del index[line]
            else:
                index2[line] = pos
                btoa[pos] = next
    # this is the Patience sorting algorithm
    # see http://en.wikipedia.org/wiki/Patience_sorting
    backpointers = [None] * len(b)
    stacks = []
    lasts = []
    k = 0
    for bpos, apos in enumerate(btoa):
        if apos is None:
            continue
        # as an optimization, check if the next line comes at the end,
        # because it usually does
        if stacks and stacks[-1] < apos:
            k = len(stacks)
        # as an optimization, check if the next line comes right after
        # the previous line, because usually it does
        elif stacks and stacks[k] < apos and (k == len(stacks) - 1 or 
                                              stacks[k+1] > apos):
            k += 1
        else:
            k = bisect(stacks, apos)
        if k > 0:
            backpointers[bpos] = lasts[k-1]
        if k < len(stacks):
            stacks[k] = apos
            lasts[k] = bpos
        else:
            stacks.append(apos)
            lasts.append(bpos)
    if len(lasts) == 0:
        return []
    result = []
    k = lasts[-1]
    while k is not None:
        result.append((btoa[k], k))
        k = backpointers[k]
    result.reverse()
    return result


def recurse_matches(a, b, ahi, bhi, answer, maxrecursion):
    """Find all of the matching text in the lines of a and b.

    :param a: A sequence
    :param b: Another sequence
    :param ahi: The maximum length of a to check, typically len(a)
    :param bhi: The maximum length of b to check, typically len(b)
    :param answer: The return array. Will be filled with tuples
                   indicating [(line_in_a), (line_in_b)]
    :param maxrecursion: The maximum depth to recurse.
                         Must be a positive integer.
    :return: None, the return value is in the parameter answer, which
             should be a list

    """
    oldlen = len(answer)
    if maxrecursion < 0:
        # this will never happen normally, this check is to prevent DOS attacks
        return
    oldlength = len(answer)
    if len(answer) == 0:
        alo, blo = 0, 0
    else:
        alo, blo = answer[-1]
        alo += 1
        blo += 1
    if alo == ahi or blo == bhi:
        return
    for apos, bpos in unique_lcs(a[alo:ahi], b[blo:bhi]):
        # recurse between lines which are unique in each file and match
        apos += alo
        bpos += blo
        recurse_matches(a, b, apos, bpos, answer, maxrecursion - 1)
        answer.append((apos, bpos))
    if len(answer) > oldlength:
        # find matches between the last match and the end
        recurse_matches(a, b, ahi, bhi, answer, maxrecursion - 1)
    elif a[alo] == b[blo]:
        # find matching lines at the very beginning
        while alo < ahi and blo < bhi and a[alo] == b[blo]:
            answer.append((alo, blo))
            alo += 1
            blo += 1
        recurse_matches(a, b, ahi, bhi, answer, maxrecursion - 1)
    elif a[ahi - 1] == b[bhi - 1]:
        # find matching lines at the very end
        nahi = ahi - 1
        nbhi = bhi - 1
        while nahi > alo and nbhi > blo and a[nahi - 1] == b[nbhi - 1]:
            nahi -= 1
            nbhi -= 1
        recurse_matches(a, b, nahi, nbhi, answer, maxrecursion - 1)
        for i in xrange(ahi - nahi):
            answer.append((nahi + i, nbhi + i))


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
            a = self.a[alo+1:ahi-1]
            b = self.b[blo+1:bhi-1]
            m = difflib.SequenceMatcher(None, a, b)
            new_blocks = m.get_matching_blocks()
            # difflib always adds a final match
            new_blocks.pop()
            for blk in new_blocks:
                answer.append((blk[0]+alo+1,
                               blk[1]+blo+1,
                               blk[2]))

    def get_matching_blocks(self):
        """Return list of triples describing matching subsequences.

        Each triple is of the form (i, j, n), and means that
        a[i:i+n] == b[j:j+n].  The triples are monotonically increasing in
        i and in j.

        The last triple is a dummy, (len(a), len(b), 0), and is the only
        triple with n==0.

        >>> s = SequenceMatcher(None, "abxcd", "abcd")
        >>> s.get_matching_blocks()
        [(0, 0, 2), (3, 2, 2), (5, 4, 0)]
        """
        # jam 20060525 This is the python 2.4.1 difflib get_matching_blocks 
        # implementation which uses __helper. 2.4.3 got rid of helper for
        # doing it inline with a queue.
        # We should consider doing the same for recurse_matches

        if self.matching_blocks is not None:
            return self.matching_blocks
        self.matching_blocks = []
        la, lb = len(self.a), len(self.b)
        self.__helper(0, la, 0, lb, self.matching_blocks)
        self.matching_blocks.append( (la, lb, 0) )
        return self.matching_blocks

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
                    self._check_with_diff(alo-1, i_a+alo, blo-1, i_b+blo, 
                                          answer)
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

        # For consistency sake, make sure all matches are only increasing
        if __debug__:
            next_a = -1
            next_b = -1
            for a,b,match_len in answer:
                assert a >= next_a, 'Non increasing matches for a'
                assert b >= next_b, 'Not increasing matches for b'
                next_a = a + match_len
                next_b = b + match_len


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
    return unified_diff(file_a.readlines(), file_b.readlines(),
                        fromfile=a, tofile=b,
                        sequencematcher=sequencematcher)


def main(args):
    import optparse
    p = optparse.OptionParser(usage='%prog [options] file_a file_b'
                                    '\nFiles can be "-" to read from stdin')
    p.add_option('--patience', dest='matcher', action='store_const', const='patience',
                 default='patience', help='Use the patience difference algorithm')
    p.add_option('--difflib', dest='matcher', action='store_const', const='difflib',
                 default='patience', help='Use python\'s difflib algorithm')

    algorithms = {'patience':SequenceMatcher, 'difflib':difflib.SequenceMatcher}

    (opts, args) = p.parse_args(args)
    matcher = algorithms[opts.matcher]

    if len(args) != 2:
        print 'You must supply 2 filenames to diff'
        return -1

    for line in unified_diff_files(args[0], args[1], sequencematcher=matcher):
        sys.stdout.write(line)
    
if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

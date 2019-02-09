# Copyright (C) 2005-2010 Canonical Ltd
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

# mbp: "you know that thing where cvs gives you conflict markers?"
# s: "i hate that."

from . import (
    errors,
    patiencediff,
    textfile,
    )


class CantReprocessAndShowBase(errors.BzrError):

    _fmt = ("Can't reprocess and show base, because reprocessing obscures "
            "the relationship of conflicting lines to the base")


def intersect(ra, rb):
    """Given two ranges return the range where they intersect or None.

    >>> intersect((0, 10), (0, 6))
    (0, 6)
    >>> intersect((0, 10), (5, 15))
    (5, 10)
    >>> intersect((0, 10), (10, 15))
    >>> intersect((0, 9), (10, 15))
    >>> intersect((0, 9), (7, 15))
    (7, 9)
    """
    # preconditions: (ra[0] <= ra[1]) and (rb[0] <= rb[1])

    sa = max(ra[0], rb[0])
    sb = min(ra[1], rb[1])
    if sa < sb:
        return sa, sb
    else:
        return None


def compare_range(a, astart, aend, b, bstart, bend):
    """Compare a[astart:aend] == b[bstart:bend], without slicing.
    """
    if (aend - astart) != (bend - bstart):
        return False
    for ia, ib in zip(range(astart, aend), range(bstart, bend)):
        if a[ia] != b[ib]:
            return False
    else:
        return True


class Merge3(object):
    """3-way merge of texts.

    Given BASE, OTHER, THIS, tries to produce a combined text
    incorporating the changes from both BASE->OTHER and BASE->THIS.
    All three will typically be sequences of lines."""

    def __init__(self, base, a, b, is_cherrypick=False, allow_objects=False):
        """Constructor.

        :param base: lines in BASE
        :param a: lines in A
        :param b: lines in B
        :param is_cherrypick: flag indicating if this merge is a cherrypick.
            When cherrypicking b => a, matches with b and base do not conflict.
        :param allow_objects: if True, do not require that base, a and b are
            plain Python strs.  Also prevents BinaryFile from being raised.
            Lines can be any sequence of comparable and hashable Python
            objects.
        """
        if not allow_objects:
            textfile.check_text_lines(base)
            textfile.check_text_lines(a)
            textfile.check_text_lines(b)
        self.base = base
        self.a = a
        self.b = b
        self.is_cherrypick = is_cherrypick

    def merge_lines(self,
                    name_a=None,
                    name_b=None,
                    name_base=None,
                    start_marker=b'<<<<<<<',
                    mid_marker=b'=======',
                    end_marker=b'>>>>>>>',
                    base_marker=None,
                    reprocess=False):
        """Return merge in cvs-like form.
        """
        newline = b'\n'
        if len(self.a) > 0:
            if self.a[0].endswith(b'\r\n'):
                newline = b'\r\n'
            elif self.a[0].endswith(b'\r'):
                newline = b'\r'
        if base_marker and reprocess:
            raise CantReprocessAndShowBase()
        if name_a:
            start_marker = start_marker + b' ' + name_a
        if name_b:
            end_marker = end_marker + b' ' + name_b
        if name_base and base_marker:
            base_marker = base_marker + b' ' + name_base
        merge_regions = self.merge_regions()
        if reprocess is True:
            merge_regions = self.reprocess_merge_regions(merge_regions)
        for t in merge_regions:
            what = t[0]
            if what == 'unchanged':
                for i in range(t[1], t[2]):
                    yield self.base[i]
            elif what == 'a' or what == 'same':
                for i in range(t[1], t[2]):
                    yield self.a[i]
            elif what == 'b':
                for i in range(t[1], t[2]):
                    yield self.b[i]
            elif what == 'conflict':
                yield start_marker + newline
                for i in range(t[3], t[4]):
                    yield self.a[i]
                if base_marker is not None:
                    yield base_marker + newline
                    for i in range(t[1], t[2]):
                        yield self.base[i]
                yield mid_marker + newline
                for i in range(t[5], t[6]):
                    yield self.b[i]
                yield end_marker + newline
            else:
                raise ValueError(what)

    def merge_annotated(self):
        """Return merge with conflicts, showing origin of lines.

        Most useful for debugging merge.
        """
        for t in self.merge_regions():
            what = t[0]
            if what == 'unchanged':
                for i in range(t[1], t[2]):
                    yield 'u | ' + self.base[i]
            elif what == 'a' or what == 'same':
                for i in range(t[1], t[2]):
                    yield what[0] + ' | ' + self.a[i]
            elif what == 'b':
                for i in range(t[1], t[2]):
                    yield 'b | ' + self.b[i]
            elif what == 'conflict':
                yield '<<<<\n'
                for i in range(t[3], t[4]):
                    yield 'A | ' + self.a[i]
                yield '----\n'
                for i in range(t[5], t[6]):
                    yield 'B | ' + self.b[i]
                yield '>>>>\n'
            else:
                raise ValueError(what)

    def merge_groups(self):
        """Yield sequence of line groups.  Each one is a tuple:

        'unchanged', lines
             Lines unchanged from base

        'a', lines
             Lines taken from a

        'same', lines
             Lines taken from a (and equal to b)

        'b', lines
             Lines taken from b

        'conflict', base_lines, a_lines, b_lines
             Lines from base were changed to either a or b and conflict.
        """
        for t in self.merge_regions():
            what = t[0]
            if what == 'unchanged':
                yield what, self.base[t[1]:t[2]]
            elif what == 'a' or what == 'same':
                yield what, self.a[t[1]:t[2]]
            elif what == 'b':
                yield what, self.b[t[1]:t[2]]
            elif what == 'conflict':
                yield (what,
                       self.base[t[1]:t[2]],
                       self.a[t[3]:t[4]],
                       self.b[t[5]:t[6]])
            else:
                raise ValueError(what)

    def merge_regions(self):
        """Return sequences of matching and conflicting regions.

        This returns tuples, where the first value says what kind we
        have:

        'unchanged', start, end
             Take a region of base[start:end]

        'same', astart, aend
             b and a are different from base but give the same result

        'a', start, end
             Non-clashing insertion from a[start:end]

        Method is as follows:

        The two sequences align only on regions which match the base
        and both descendents.  These are found by doing a two-way diff
        of each one against the base, and then finding the
        intersections between those regions.  These "sync regions"
        are by definition unchanged in both and easily dealt with.

        The regions in between can be in any of three cases:
        conflicted, or changed on only one side.
        """

        # section a[0:ia] has been disposed of, etc
        iz = ia = ib = 0

        for zmatch, zend, amatch, aend, bmatch, bend in self.find_sync_regions():
            matchlen = zend - zmatch
            # invariants:
            #   matchlen >= 0
            #   matchlen == (aend - amatch)
            #   matchlen == (bend - bmatch)
            len_a = amatch - ia
            len_b = bmatch - ib
            # invariants:
            # assert len_a >= 0
            # assert len_b >= 0

            # print 'unmatched a=%d, b=%d' % (len_a, len_b)

            if len_a or len_b:
                # try to avoid actually slicing the lists
                same = compare_range(self.a, ia, amatch,
                                     self.b, ib, bmatch)

                if same:
                    yield 'same', ia, amatch
                else:
                    equal_a = compare_range(self.a, ia, amatch,
                                            self.base, iz, zmatch)
                    equal_b = compare_range(self.b, ib, bmatch,
                                            self.base, iz, zmatch)
                    if equal_a and not equal_b:
                        yield 'b', ib, bmatch
                    elif equal_b and not equal_a:
                        yield 'a', ia, amatch
                    elif not equal_a and not equal_b:
                        if self.is_cherrypick:
                            for node in self._refine_cherrypick_conflict(
                                    iz, zmatch, ia, amatch,
                                    ib, bmatch):
                                yield node
                        else:
                            yield ('conflict', iz, zmatch, ia, amatch, ib,
                                   bmatch)
                    else:
                        raise AssertionError(
                            "can't handle a=b=base but unmatched")

                ia = amatch
                ib = bmatch
            iz = zmatch

            # if the same part of the base was deleted on both sides
            # that's OK, we can just skip it.

            if matchlen > 0:
                # invariants:
                # assert ia == amatch
                # assert ib == bmatch
                # assert iz == zmatch

                yield 'unchanged', zmatch, zend
                iz = zend
                ia = aend
                ib = bend

    def _refine_cherrypick_conflict(self, zstart, zend, astart, aend, bstart,
                                    bend):
        """When cherrypicking b => a, ignore matches with b and base."""
        # Do not emit regions which match, only regions which do not match
        matches = patiencediff.PatienceSequenceMatcher(
            None, self.base[zstart:zend], self.b[bstart:bend]
            ).get_matching_blocks()
        last_base_idx = 0
        last_b_idx = 0
        last_b_idx = 0
        yielded_a = False
        for base_idx, b_idx, match_len in matches:
            conflict_b_len = b_idx - last_b_idx
            if conflict_b_len == 0:
                # There are no lines in b which conflict, so skip it
                pass
            else:
                if yielded_a:
                    yield ('conflict',
                           zstart + last_base_idx, zstart + base_idx,
                           aend, aend, bstart + last_b_idx, bstart + b_idx)
                else:
                    # The first conflict gets the a-range
                    yielded_a = True
                    yield ('conflict', zstart + last_base_idx, zstart +
                           base_idx,
                           astart, aend, bstart + last_b_idx, bstart + b_idx)
            last_base_idx = base_idx + match_len
            last_b_idx = b_idx + match_len
        if last_base_idx != zend - zstart or last_b_idx != bend - bstart:
            if yielded_a:
                yield ('conflict', zstart + last_base_idx, zstart + base_idx,
                       aend, aend, bstart + last_b_idx, bstart + b_idx)
            else:
                # The first conflict gets the a-range
                yielded_a = True
                yield ('conflict', zstart + last_base_idx, zstart + base_idx,
                       astart, aend, bstart + last_b_idx, bstart + b_idx)
        if not yielded_a:
            yield ('conflict', zstart, zend, astart, aend, bstart, bend)

    def reprocess_merge_regions(self, merge_regions):
        """Where there are conflict regions, remove the agreed lines.

        Lines where both A and B have made the same changes are
        eliminated.
        """
        for region in merge_regions:
            if region[0] != "conflict":
                yield region
                continue
            type, iz, zmatch, ia, amatch, ib, bmatch = region
            a_region = self.a[ia:amatch]
            b_region = self.b[ib:bmatch]
            matches = patiencediff.PatienceSequenceMatcher(
                None, a_region, b_region).get_matching_blocks()
            next_a = ia
            next_b = ib
            for region_ia, region_ib, region_len in matches[:-1]:
                region_ia += ia
                region_ib += ib
                reg = self.mismatch_region(next_a, region_ia, next_b,
                                           region_ib)
                if reg is not None:
                    yield reg
                yield 'same', region_ia, region_len + region_ia
                next_a = region_ia + region_len
                next_b = region_ib + region_len
            reg = self.mismatch_region(next_a, amatch, next_b, bmatch)
            if reg is not None:
                yield reg

    @staticmethod
    def mismatch_region(next_a, region_ia, next_b, region_ib):
        if next_a < region_ia or next_b < region_ib:
            return 'conflict', None, None, next_a, region_ia, next_b, region_ib

    def find_sync_regions(self):
        """Return a list of sync regions, where both descendents match the base.

        Generates a list of (base1, base2, a1, a2, b1, b2).  There is
        always a zero-length sync region at the end of all the files.
        """

        ia = ib = 0
        amatches = patiencediff.PatienceSequenceMatcher(
            None, self.base, self.a).get_matching_blocks()
        bmatches = patiencediff.PatienceSequenceMatcher(
            None, self.base, self.b).get_matching_blocks()
        len_a = len(amatches)
        len_b = len(bmatches)

        sl = []

        while ia < len_a and ib < len_b:
            abase, amatch, alen = amatches[ia]
            bbase, bmatch, blen = bmatches[ib]

            # there is an unconflicted block at i; how long does it
            # extend?  until whichever one ends earlier.
            i = intersect((abase, abase + alen), (bbase, bbase + blen))
            if i:
                intbase = i[0]
                intend = i[1]
                intlen = intend - intbase

                # found a match of base[i[0], i[1]]; this may be less than
                # the region that matches in either one
                # assert intlen <= alen
                # assert intlen <= blen
                # assert abase <= intbase
                # assert bbase <= intbase

                asub = amatch + (intbase - abase)
                bsub = bmatch + (intbase - bbase)
                aend = asub + intlen
                bend = bsub + intlen

                # assert self.base[intbase:intend] == self.a[asub:aend], \
                #       (self.base[intbase:intend], self.a[asub:aend])
                # assert self.base[intbase:intend] == self.b[bsub:bend]

                sl.append((intbase, intend,
                           asub, aend,
                           bsub, bend))
            # advance whichever one ends first in the base text
            if (abase + alen) < (bbase + blen):
                ia += 1
            else:
                ib += 1

        intbase = len(self.base)
        abase = len(self.a)
        bbase = len(self.b)
        sl.append((intbase, intbase, abase, abase, bbase, bbase))

        return sl

    def find_unconflicted(self):
        """Return a list of ranges in base that are not conflicted."""
        am = patiencediff.PatienceSequenceMatcher(
            None, self.base, self.a).get_matching_blocks()
        bm = patiencediff.PatienceSequenceMatcher(
            None, self.base, self.b).get_matching_blocks()

        unc = []

        while am and bm:
            # there is an unconflicted block at i; how long does it
            # extend?  until whichever one ends earlier.
            a1 = am[0][0]
            a2 = a1 + am[0][2]
            b1 = bm[0][0]
            b2 = b1 + bm[0][2]
            i = intersect((a1, a2), (b1, b2))
            if i:
                unc.append(i)

            if a2 < b2:
                del am[0]
            else:
                del bm[0]

        return unc


def main(argv):
    # as for diff3 and meld the syntax is "MINE BASE OTHER"
    with open(argv[1], 'rt') as f:
        a = f.readlines()
    with open(argv[2], 'rt') as f:
        base = f.readlines()
    with open(argv[3], 'rt') as f:
        b = f.readlines()

    m3 = Merge3(base, a, b)

    # for sr in m3.find_sync_regions():
    #    print sr

    # sys.stdout.writelines(m3.merge_lines(name_a=argv[1], name_b=argv[3]))
    sys.stdout.writelines(m3.merge_annotated())


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))

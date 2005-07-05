# Copyright (C) 2004, 2005 by Canonical Ltd

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
    assert ra[0] <= ra[1]
    assert rb[0] <= rb[1]
    
    sa = max(ra[0], rb[0])
    sb = min(ra[1], rb[1])
    if sa < sb:
        return sa, sb
    else:
        return None


def threeway(baseline, aline, bline):
    if baseline == aline:
        return bline
    elif baseline == bline:
        return aline
    else:
        return [aline, bline]



class Merge3(object):
    """3-way merge of texts.

    Given BASE, OTHER, THIS, tries to produce a combined text
    incorporating the changes from both BASE->OTHER and BASE->THIS.
    All three will typically be sequences of lines."""
    def __init__(self, base, a, b):
        self.base = base
        self.a = a
        self.b = b
        from difflib import SequenceMatcher
        self.a_ops = SequenceMatcher(None, base, a).get_opcodes()
        self.b_ops = SequenceMatcher(None, base, b).get_opcodes()


    def merge(self):
        """Return sequences of matching and conflicting regions.

        Method is as follows:

        The two sequences align only on regions which match the base
        and both descendents.  These are found by doing a two-way diff
        of each one against the base, and then finding the
        intersections between those regions.  These "sync regions"
        are by definition unchanged in both and easily dealt with.

        The regions in between can be in any of three cases:
        conflicted, or changed on only one side.
        """

        
    def find_sync_regions(self):
        """Return a list of sync regions, where both descendents match the base.

        Generates a list of ((base1, base2), (a1, a2), (b1, b2)). 
        """
        from difflib import SequenceMatcher
        aiter = iter(SequenceMatcher(None, self.base, self.a).get_matching_blocks())
        biter = iter(SequenceMatcher(None, self.base, self.b).get_matching_blocks())

        abase, amatch, alen = aiter.next()
        bbase, bmatch, blen = biter.next()

        while aiter and biter:
            # there is an unconflicted block at i; how long does it
            # extend?  until whichever one ends earlier.
            i = intersect((abase, abase+alen), (bbase, bbase+blen))
            if i:
                intbase = i[0]
                intend = i[1]
                intlen = intend - intbase

                # found a match of base[i[0], i[1]]; this may be less than
                # the region that matches in either one
                assert intlen <= alen
                assert intlen <= blen
                assert abase <= intbase
                assert bbase <= intbase

                asub = amatch + (intbase - abase)
                bsub = bmatch + (intbase - bbase)
                aend = asub + intlen
                bend = bsub + intlen

                assert self.base[intbase:intend] == self.a[asub:aend], \
                       (self.base[intbase:intend], self.a[asub:aend])
                
                assert self.base[intbase:intend] == self.b[bsub:bend]

                yield ((intbase, intend),
                       (asub, aend),
                       (bsub, bend))

            # advance whichever one ends first in the base text
            if (abase + alen) < (bbase + blen):
                abase, amatch, alen = aiter.next()
            else:
                bbase, bmatch, blen = biter.next()



    def find_unconflicted(self):
        """Return a list of ranges in base that are not conflicted."""
        from difflib import SequenceMatcher
        am = SequenceMatcher(None, self.base, self.a).get_matching_blocks()
        bm = SequenceMatcher(None, self.base, self.b).get_matching_blocks()

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

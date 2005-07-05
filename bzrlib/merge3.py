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


# mbp: "you know that thing where cvs gives you conflict markers?"
# s: "i hate that."



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



    def merge_lines(self,
                    start_marker='<<<<<<<<\n',
                    mid_marker='========\n',
                    end_marker='>>>>>>>>\n'):
        """Return merge in cvs-like form.
        """
        for t in self.merge_regions():
            what = t[0]
            if what == 'unchanged':
                for i in range(t[1], t[2]):
                    yield self.base[i]
            elif what == 'a':
                for i in range(t[1], t[2]):
                    yield self.a[i]
            elif what == 'b':
                for i in range(t[1], t[2]):
                    yield self.b[i]
            elif what == 'conflict':
                yield start_marker
                for i in range(t[3], t[4]):
                    yield self.a[i]
                yield mid_marker
                for i in range(t[5], t[6]):
                    yield self.b[i]
                yield end_marker
            else:
                raise ValueError(what)
        
        



    def merge_groups(self):
        """Yield sequence of line groups.  Each one is a tuple:

        'unchanged', lines
             Lines unchanged from base

        'a', lines
             Lines taken from a

        'b', lines
             Lines taken from b

        'conflict', base_lines, a_lines, b_lines
             Lines from base were changed to either a or b and conflict.
        """
        for t in self.merge_regions():
            what = t[0]
            if what == 'unchanged':
                yield what, self.base[t[1]:t[2]]
            elif what == 'a':
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
            assert matchlen >= 0
            assert matchlen == (aend - amatch)
            assert matchlen == (bend - bmatch)
            
            len_a = amatch - ia
            len_b = bmatch - ib
            len_base = zmatch - iz
            assert len_a >= 0
            assert len_b >= 0
            assert len_base >= 0

            if len_a or len_b:
                lines_base = self.base[iz:zmatch]
                lines_a = self.a[ia:amatch]
                lines_b = self.b[ib:bmatch]

                # TODO: check the len just as a shortcut
                equal_a = (lines_a == lines_base)
                equal_b = (lines_b == lines_base)

                if equal_a and not equal_b:
                    yield 'b', ib, bmatch
                elif equal_b and not equal_a:
                    yield 'a', ia, amatch
                elif not equal_a and not equal_b:
                    yield 'conflict', iz, zmatch, ia, amatch, ib, bmatch
                else:
                    assert 0

                ia = amatch
                ib = bmatch
            iz = zmatch

            # if the same part of the base was deleted on both sides
            # that's OK, we can just skip it.

                
            if matchlen > 0:
                assert ia == amatch
                assert ib == bmatch
                assert iz == zmatch
                
                yield 'unchanged', zmatch, zend
                iz = zend
                ia = aend
                ib = bend
        

        
    def find_sync_regions(self):
        """Return a list of sync regions, where both descendents match the base.

        Generates a list of (base1, base2, a1, a2, b1, b2).  There is
        always a zero-length sync region at the end of all the files.
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

                yield (intbase, intend,
                       asub, aend,
                       bsub, bend)

            # advance whichever one ends first in the base text
            if (abase + alen) < (bbase + blen):
                abase, amatch, alen = aiter.next()
            else:
                bbase, bmatch, blen = biter.next()

        intbase = len(self.base)
        abase = len(self.a)
        bbase = len(self.b)
        yield (intbase, intbase, abase, abase, bbase, bbase)



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

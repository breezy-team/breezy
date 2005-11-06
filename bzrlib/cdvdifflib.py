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

# Author: Martin Pool <mbp@canonical.com>


from nofrillsprecisemerge import recurse_matches
from bzrlib.errors import BzrError
import difflib

class SequenceMatcher(difflib.SequenceMatcher):
    """Compare a pair of sequences using longest common subset."""

    def __init__(self, isjunk=None, a='', b=''):
        if isjunk is not None:
            raise NotImplementedError('Currently we do not support'
                                      ' isjunk for sequence matching')
        difflib.SequenceMatcher.__init__(self, isjunk, a, b)

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
                if start_a is not None:
                    answer.append((start_a+alo, start_b+blo, length))
                start_a = i_a
                start_b = i_b
                length = 1

        if length != 0:
            answer.append((start_a+blo, start_b+blo, length))


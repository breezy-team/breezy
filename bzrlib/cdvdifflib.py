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
    """This is a class which attempts to look something like difflib's SequenceMatcher"""

    def find_longest_match(self, alo, ahi, blo, bhi):
        raise NotImplementedError

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

        matches = []
        a, b = self.a, self.b
        recurse_matches(a, b, len(a), len(b), matches, 10)
        # Matches now has individual line pairs of
        # line A matches line B, at the given offsets

        match_blocks = []
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
                    match_blocks.append((start_a, start_b, length))
                start_a = i_a
                start_b = i_b
                length = 1

        if length != 0:
            match_blocks.append((start_a, start_b, length))

        match_blocks.append((len(a), len(b), 0))
        return match_blocks


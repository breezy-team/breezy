# Copyright (C) 2005 by Canonical Ltd

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
import bzrlib.errors
from bzrlib.selftest.testrevision import make_branches
from bzrlib.trace import mutter
from bzrlib.branch import Branch, find_branch
import sys
import os

from bzrlib.selftest.HTTPTestUtil import TestCaseWithWebserver
        

class TestFetch(TestCaseWithWebserver):
    def test_fetch(self):
        from bzrlib.fetch import greedy_fetch, has_revision

        def new_branch(name):
            os.mkdir(name)
            return Branch.initialize(name)
            
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches()
        br_rem = Branch.open(self.get_remote_url(br_a.base))
        assert not has_revision(br_b, br_rem.revision_history()[3])
        assert has_revision(br_b, br_rem.revision_history()[2])
        assert len(br_b.revision_history()) == 7
        assert greedy_fetch(br_b, br_rem, br_rem.revision_history()[2])[0] == 0

        # greedy_fetch is not supposed to alter the revision history
        assert len(br_b.revision_history()) == 7
        assert not has_revision(br_b, br_rem.revision_history()[3])

        assert len(br_b.revision_history()) == 7
        assert greedy_fetch(br_b, br_rem, br_rem.revision_history()[3])[0] == 1
        assert has_revision(br_b, br_a.revision_history()[3])
        assert not has_revision(br_rem, br_b.revision_history()[3])
        assert not has_revision(br_rem, br_b.revision_history()[4])

        # When a non-branch ancestor is missing, it should be a failure, not
        # exception
        br_a4 = new_branch('br_a4')
        count, failures = greedy_fetch(br_a4, br_rem)
        assert count == 6
        assert failures == set((br_b.revision_history()[4],
                                br_b.revision_history()[5])) 

        assert greedy_fetch(br_a, br_b)[0] == 4
        assert has_revision(br_a, br_b.revision_history()[3])
        assert has_revision(br_a, br_b.revision_history()[4])

        br_b2 = new_branch('br_b2')
        assert greedy_fetch(br_b2, br_b)[0] == 7
        assert has_revision(br_b2, br_b.revision_history()[4])
        assert has_revision(br_b2, br_a.revision_history()[2])
        assert not has_revision(br_b2, br_a.revision_history()[3])

        br_a2 = new_branch('br_a2')
        assert greedy_fetch(br_a2, br_rem)[0] == 9
        assert has_revision(br_a2, br_b.revision_history()[4])
        assert has_revision(br_a2, br_a.revision_history()[3])


if __name__ == '__main__':
    import unittest
    sys.exit(unittest.run_suite(unittest.makeSuite()))

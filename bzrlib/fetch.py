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
from bzrlib.branch import Branch
from bzrlib.progress import ProgressBar
import sys
import os

def greedy_fetch(to_branch, from_branch, last_revision=None):
    """Copy a revision and all available ancestors from one branch to another
    If no revision is specified, uses the last revision in the source branch's
    revision history.
    """
    from_history = from_branch.revision_history()
    if last_revision is not None:
        try:
            rev_index = from_history.index(last_revision)
        except ValueError:
            rev_index = None
        if rev_index is not None:
            from_history = from_history[:rev_index + 1]
        else:
            from_history = [last_revision]
    to_history = to_branch.revision_history()
    missing = []
    for rev_id in from_history:
        if not has_revision(to_branch, rev_id):
            missing.append(rev_id)
    
    count = 0
    while len(missing) > 0:
        count += to_branch.install_revisions(from_branch, revision_ids=missing)
        new_missing = []
        for rev_id in missing:
            try:
                revision = from_branch.get_revision(rev_id)
            except bzrlib.errors.NoSuchRevision:
                if revision in from_history:
                    raise
                else:
                    continue
            for parent in [p.revision_id for p in revision.parents]:
                print >> sys.stderr, "adding %s" % parent
                if not has_revision(to_branch, parent):
                    new_missing.append(parent)
        missing = new_missing
    return count


from testsweet import InTempDir
def has_revision(branch, revision_id):
    try:
        branch.get_revision_xml(revision_id)
        return True
    except bzrlib.errors.NoSuchRevision:
        return False

class TestFetch(InTempDir):
    def runTest(self):
        def new_branch(name):
            os.mkdir(name)
            return Branch(name, init=True)
            
        #highest indices a: 3, b: 4
        br_a, br_b = make_branches()
        assert not has_revision(br_b, br_a.revision_history()[3])
        assert has_revision(br_b, br_a.revision_history()[2])
        assert len(br_b.revision_history()) == 5
        assert greedy_fetch(br_b, br_a, br_a.revision_history()[2]) == 0

        # greedy_fetch is not supposed to alter the revision history
        assert len(br_b.revision_history()) == 5
        assert not has_revision(br_b, br_a.revision_history()[3])

        assert len(br_b.revision_history()) == 5
        assert greedy_fetch(br_b, br_a, br_a.revision_history()[3]) == 1
        assert has_revision(br_b, br_a.revision_history()[3])
        assert not has_revision(br_a, br_b.revision_history()[3])
        assert not has_revision(br_a, br_b.revision_history()[4])
        assert greedy_fetch(br_a, br_b) == 2
        assert has_revision(br_a, br_b.revision_history()[3])
        assert has_revision(br_a, br_b.revision_history()[4])

        br_b2 = new_branch('br_b2')
        assert greedy_fetch(br_b2, br_b) == 5
        assert has_revision(br_b2, br_b.revision_history()[4])
        assert has_revision(br_b2, br_a.revision_history()[2])
        assert not has_revision(br_b2, br_a.revision_history()[3])

        br_a2 = new_branch('br_a2')
        assert greedy_fetch(br_a2, br_a) == 6
        assert has_revision(br_a2, br_b.revision_history()[4])
        assert has_revision(br_a2, br_a.revision_history()[3])

        br_a3 = new_branch('br_a3')
        assert greedy_fetch(br_a3, br_a2) == 0
        for revno in range(4):
            assert not has_revision(br_a3, br_a.revision_history()[revno])
        assert greedy_fetch(br_a3, br_a2, br_a.revision_history()[2]) == 3
        fetched = greedy_fetch(br_a3, br_a2, br_a.revision_history()[3])
        assert fetched == 3, "fetched %d instead of 3" % fetched



if __name__ == '__main__':
    import sys
    sys.exit(run_suite(unittest.makeSuite()))

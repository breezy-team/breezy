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
import sys
import os

def greedy_fetch(from_branch, to_branch, last_revision=None):
    from_history = from_branch.revision_history()
    if last_revision is not None:
        from_history = from_history[:from_history.index(last_revision)+1]
    to_history = to_branch.revision_history()
    missing = []
    for rev_id in from_history:
        if not has_revision(to_branch, rev_id):
            missing.append(rev_id)

    while len(missing) > 0:
        to_branch.update_revisions(from_branch, revision_ids=missing)
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
                if not has_revision(to_branch, parent):
                    new_missing.append(parent)
        missing = new_missing


from testsweet import InTempDir
def has_revision(branch, revision_id):
    try:
        branch.get_revision_xml(revision_id)
        return True
    except bzrlib.errors.NoSuchRevision:
        return False

class TestFetch(InTempDir):
    def runTest(self):
        br_a, br_b = make_branches()
        assert not has_revision(br_b, br_a.revision_history()[3])
        assert has_revision(br_b, br_a.revision_history()[2])
        greedy_fetch(br_a, br_b, br_a.revision_history()[2])
        assert not has_revision(br_b, br_a.revision_history()[3])
        greedy_fetch(br_a, br_b, br_a.revision_history()[3])
        assert has_revision(br_b, br_a.revision_history()[3])
        assert not has_revision(br_a, br_b.revision_history()[3])
        assert not has_revision(br_a, br_b.revision_history()[4])
        greedy_fetch(br_b, br_a)
        assert has_revision(br_a, br_b.revision_history()[3])
        assert has_revision(br_a, br_b.revision_history()[4])
        os.mkdir('branchc')
        br_c = Branch("branchc", init=True)
        greedy_fetch(br_b, br_c)
        assert has_revision(br_c, br_b.revision_history()[5])
        assert has_revision(br_c, br_a.revision_history()[4])
        os.mkdir('branchd')
        br_d = Branch("branchd", init=True)
        greedy_fetch(br_a, br_d)
        assert has_revision(br_d, br_b.revision_history()[5])
        assert has_revision(br_d, br_a.revision_history()[4])



if __name__ == '__main__':
    import sys
    sys.exit(run_suite(unittest.makeSuite()))

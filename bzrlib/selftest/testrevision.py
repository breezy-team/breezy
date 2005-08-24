# (C) 2005 Canonical Ltd

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

from bzrlib.selftest import InTempDir


def make_branches():
    from bzrlib.branch import Branch
    from bzrlib.commit import commit
    import os
    os.mkdir("branch1")
    br1 = Branch("branch1", init=True)
    commit(br1, "Commit one")
    commit(br1, "Commit two")
    commit(br1, "Commit three")

    os.mkdir("branch2")
    br2 = Branch("branch2", init=True)
    br2.update_revisions(br1)
    commit(br2, "Commit four")
    commit(br2, "Commit five")
    revisions_2 = br2.revision_history()
    br1.add_pending_merge(revisions_2[4])
    commit(br1, "Commit six")
    return br1, br2


class TestIsAncestor(InTempDir):

    def test_is_ancestor(self):
        """Test checking whether a revision is an ancestor of another revision"""
        from bzrlib.revision import is_ancestor, MultipleRevisionSources
        from bzrlib.errors import NoSuchRevision
        br1, br2 = make_branches()
        revisions = br1.revision_history()
        revisions_2 = br2.revision_history()
        sources = MultipleRevisionSources(br1, br2)

        assert is_ancestor(revisions[0], revisions[0], sources)
        assert is_ancestor(revisions[1], revisions[0], sources)
        assert not is_ancestor(revisions[0], revisions[1], sources)
        assert is_ancestor(revisions_2[3], revisions[0], sources)
        self.assertRaises(NoSuchRevision, is_ancestor, revisions_2[3],
                          revisions[0], br1)        
        assert is_ancestor(revisions[3], revisions_2[4], sources)
        assert is_ancestor(revisions[3], revisions_2[4], br1)
        assert is_ancestor(revisions[3], revisions_2[3], sources)
        assert not is_ancestor(revisions[3], revisions_2[3], br1)

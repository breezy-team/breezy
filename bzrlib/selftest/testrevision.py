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
    from bzrlib.revision import validate_revision_id
    import os
    os.mkdir("branch1")
    br1 = Branch("branch1", init=True)
    
    commit(br1, "Commit one", rev_id="a@u-0-0")
    commit(br1, "Commit two", rev_id="a@u-0-1")
    commit(br1, "Commit three", rev_id="a@u-0-2")

    os.mkdir("branch2")
    br2 = Branch("branch2", init=True)
    br2.update_revisions(br1)
    commit(br2, "Commit four", rev_id="b@u-0-3")
    commit(br2, "Commit five", rev_id="b@u-0-4")
    revisions_2 = br2.revision_history()
    br1.add_pending_merge(revisions_2[4])
    commit(br1, "Commit six", rev_id="a@u-0-3")
    commit(br1, "Commit seven", rev_id="a@u-0-4")
    commit(br2, "Commit eight", rev_id="b@u-0-5")
    br1.add_pending_merge(br2.revision_history()[5])
    commit(br1, "Commit nine", rev_id="a@u-0-5")
    br2.add_pending_merge(br1.revision_history()[4])
    commit(br2, "Commit ten", rev_id="b@u-0-6")
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


class TestCommonAncestor(InTempDir):
    """Test checking whether a revision is an ancestor of another revision"""
    def runTest(self):
        from bzrlib.revision import find_present_ancestors, common_ancestor
        from bzrlib.revision import MultipleRevisionSources
        br1, br2 = make_branches()
        revisions = br1.revision_history()
        revisions_2 = br2.revision_history()
        sources = MultipleRevisionSources(br1, br2)

        expected_ancestors_list = {revisions[3]:(0, 0), 
                                   revisions[2]:(1, 1),
                                   revisions_2[4]:(2, 1), 
                                   revisions[1]:(3, 2),
                                   revisions_2[3]:(4, 2),
                                   revisions[0]:(5, 3) }
        ancestors_list = find_present_ancestors(revisions[3], sources)
        assert len(expected_ancestors_list) == len(ancestors_list)
        for key, value in expected_ancestors_list.iteritems():
            self.assertEqual(ancestors_list[key], value, 
                              "key %r, %r != %r" % (key, ancestors_list[key],
                                                    value))

        self.assertEqual(common_ancestor(revisions[0], revisions[0], sources),
                          revisions[0])
        self.assertEqual(common_ancestor(revisions[1], revisions[2], sources),
                          revisions[1])
        self.assertEqual(common_ancestor(revisions[1], revisions[1], sources),
                          revisions[1])
        self.assertEqual(common_ancestor(revisions[2], revisions_2[4], sources),
                          revisions[2])
        self.assertEqual(common_ancestor(revisions[3], revisions_2[4], sources),
                          revisions_2[4])
        self.assertEqual(common_ancestor(revisions[4], revisions_2[5], sources),
                          revisions_2[4])
        self.assertEqual(common_ancestor(revisions[5], revisions_2[6], sources),
                          revisions[4])
        self.assertEqual(common_ancestor(revisions_2[6], revisions[5], sources),
                          revisions_2[5])

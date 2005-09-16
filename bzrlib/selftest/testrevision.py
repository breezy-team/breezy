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


import os

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.commit import commit
from bzrlib.fetch import fetch
from bzrlib.revision import (find_present_ancestors, common_ancestor,
                             is_ancestor)
from bzrlib.trace import mutter
from bzrlib.errors import NoSuchRevision

def make_branches():
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
    
    fetch(from_branch=br2, to_branch=br1)
    br1.add_pending_merge(revisions_2[4])
    assert revisions_2[4] == 'b@u-0-4'
    commit(br1, "Commit six", rev_id="a@u-0-3")
    commit(br1, "Commit seven", rev_id="a@u-0-4")
    commit(br2, "Commit eight", rev_id="b@u-0-5")
    
    fetch(from_branch=br2, to_branch=br1)
    br1.add_pending_merge(br2.revision_history()[5])
    commit(br1, "Commit nine", rev_id="a@u-0-5")

    fetch(from_branch=br1, to_branch=br2)
    br2.add_pending_merge(br1.revision_history()[4])
    commit(br2, "Commit ten", rev_id="b@u-0-6")

    fetch(from_branch=br2, to_branch=br1)
    
    return br1, br2


class TestIsAncestor(TestCaseInTempDir):
    def test_recorded_ancestry(self):
        """Test that commit records all ancestors"""
        br1, br2 = make_branches()
        d = [('a@u-0-0', ['a@u-0-0']),
             ('a@u-0-1', ['a@u-0-0', 'a@u-0-1']),
             ('a@u-0-2', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2']),
             ('b@u-0-3', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3']),
             ('b@u-0-4', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3',
                          'b@u-0-4']),
             ('a@u-0-3', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'a@u-0-3']),
             ('a@u-0-4', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'a@u-0-3', 'a@u-0-4']),
             ('b@u-0-5', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5']),
             ('a@u-0-5', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'a@u-0-3', 'a@u-0-4',
                          'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5', 'a@u-0-5']),
             ('b@u-0-6', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'a@u-0-3', 'a@u-0-4',
                          'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5', 'b@u-0-6']),
             ]
        for branch in br1, br2:
            for rev_id, anc in d:
                mutter('ancestry of {%s}: %r',
                       rev_id, branch.get_ancestry(rev_id))
                self.assertEquals(sorted(branch.get_ancestry(rev_id)),
                                  sorted(anc))
    
    
    def test_is_ancestor(self):
        """Test checking whether a revision is an ancestor of another revision"""
        br1, br2 = make_branches()
        revisions = br1.revision_history()
        revisions_2 = br2.revision_history()
        sources = br1

        assert is_ancestor(revisions[0], revisions[0], br1)
        assert is_ancestor(revisions[1], revisions[0], sources)
        assert not is_ancestor(revisions[0], revisions[1], sources)
        assert is_ancestor(revisions_2[3], revisions[0], sources)
	# disabled mbp 20050914, doesn't seem to happen anymore
        ## self.assertRaises(NoSuchRevision, is_ancestor, revisions_2[3],
        ##                  revisions[0], br1)        
        assert is_ancestor(revisions[3], revisions_2[4], sources)
        assert is_ancestor(revisions[3], revisions_2[4], br1)
        assert is_ancestor(revisions[3], revisions_2[3], sources)
        ## assert not is_ancestor(revisions[3], revisions_2[3], br1)



class TestIntermediateRevisions(TestCaseInTempDir):

    def setUp(self):
        from bzrlib.commit import commit
        TestCaseInTempDir.setUp(self)
        self.br1, self.br2 = make_branches()

        self.br2.commit("Commit eleven", rev_id="b@u-0-7")
        self.br2.commit("Commit twelve", rev_id="b@u-0-8")
        self.br2.commit("Commit thirtteen", rev_id="b@u-0-9")

	fetch(from_branch=self.br2, to_branch=self.br1)
        self.br1.add_pending_merge(self.br2.revision_history()[6])
        self.br1.commit("Commit fourtten", rev_id="a@u-0-6")

	fetch(from_branch=self.br1, to_branch=self.br2)
        self.br2.add_pending_merge(self.br1.revision_history()[6])
        self.br2.commit("Commit fifteen", rev_id="b@u-0-10")

        from bzrlib.revision import MultipleRevisionSources
        self.sources = MultipleRevisionSources(self.br1, self.br2)

    def intervene(self, ancestor, revision, revision_history=None):
        from bzrlib.revision import get_intervening_revisions
        return get_intervening_revisions(ancestor,revision, self.sources, 
                                         revision_history)

    def test_intervene(self):
        """Find intermediate revisions, without requiring history"""
        from bzrlib.errors import NotAncestor, NoSuchRevision
        assert len(self.intervene('a@u-0-0', 'a@u-0-0')) == 0
        self.assertEqual(self.intervene('a@u-0-0', 'a@u-0-1'), ['a@u-0-1'])
        self.assertEqual(self.intervene('a@u-0-0', 'a@u-0-2'), 
                         ['a@u-0-1', 'a@u-0-2'])
        self.assertEqual(self.intervene('a@u-0-0', 'b@u-0-3'), 
                         ['a@u-0-1', 'a@u-0-2', 'b@u-0-3'])
        self.assertEqual(self.intervene('b@u-0-3', 'a@u-0-3'), 
                         ['b@u-0-4', 'a@u-0-3'])
        self.assertEqual(self.intervene('a@u-0-2', 'a@u-0-3', 
                                        self.br1.revision_history()), 
                         ['a@u-0-3'])
        self.assertEqual(self.intervene('a@u-0-0', 'a@u-0-5', 
                                        self.br1.revision_history()), 
                         ['a@u-0-1', 'a@u-0-2', 'a@u-0-3', 'a@u-0-4', 
                          'a@u-0-5'])
        self.assertEqual(self.intervene('a@u-0-0', 'b@u-0-6', 
                         self.br1.revision_history()), 
                         ['a@u-0-1', 'a@u-0-2', 'a@u-0-3', 'a@u-0-4', 
                          'b@u-0-6'])
        self.assertEqual(self.intervene('a@u-0-0', 'b@u-0-5'), 
                         ['a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4', 
                          'b@u-0-5'])
        self.assertEqual(self.intervene('b@u-0-3', 'b@u-0-6', 
                         self.br2.revision_history()), 
                         ['b@u-0-4', 'b@u-0-5', 'b@u-0-6'])
        self.assertEqual(self.intervene('b@u-0-6', 'b@u-0-10'), 
                         ['b@u-0-7', 'b@u-0-8', 'b@u-0-9', 'b@u-0-10'])
        self.assertEqual(self.intervene('b@u-0-6', 'b@u-0-10', 
                                        self.br2.revision_history()), 
                         ['b@u-0-7', 'b@u-0-8', 'b@u-0-9', 'b@u-0-10'])
        self.assertRaises(NotAncestor, self.intervene, 'b@u-0-10', 'b@u-0-6', 
                          self.br2.revision_history())
        self.assertRaises(NoSuchRevision, self.intervene, 'c@u-0-10', 
                          'b@u-0-6', self.br2.revision_history())
        self.assertRaises(NoSuchRevision, self.intervene, 'b@u-0-10', 
                          'c@u-0-6', self.br2.revision_history())


class TestCommonAncestor(TestCaseInTempDir):
    """Test checking whether a revision is an ancestor of another revision"""

    def test_common_ancestor(self):
        br1, br2 = make_branches()
        revisions = br1.revision_history()
        revisions_2 = br2.revision_history()
        sources = br1

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


if __name__ == '__main__':
    import unittest, sys
    unittest.main()
    

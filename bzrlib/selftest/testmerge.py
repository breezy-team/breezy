from bzrlib.branch import Branch
from bzrlib.commit import commit
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.merge import merge
from bzrlib.errors import UnrelatedBranches, NoCommits
import os
class TestMerge(TestCaseInTempDir):
    """Test appending more than one revision"""
    def test_pending(self):
        br = Branch(".", init=True)
        commit(br, "lala!")
        self.assertEquals(len(br.pending_merges()), 0)
        merge(['.', -1], [None, None])
        self.assertEquals(len(br.pending_merges()), 0)

    def test_nocommits(self):
        self.test_pending()
        os.mkdir('branch2')
        br2 = Branch('branch2', init=True)
        self.assertRaises(NoCommits, merge, ['branch2', -1], 
                          [None, None])
        return br2

    def test_unrelated(self):
        br2 = self.test_nocommits()
        commit(br2, "blah")
        self.assertRaises(UnrelatedBranches, merge, ['branch2', -1], 
                          [None, None])
        return br2

    def test_pending_with_null(self):
        """When base is forced to revno 0, pending_merges is set"""
        br2 = self.test_unrelated()
        br1 = Branch('.')
        merge(['branch2', -1], ['branch2', 0])
        self.assertEquals(len(br1.pending_merges()), 1)
        return (br1, br2)

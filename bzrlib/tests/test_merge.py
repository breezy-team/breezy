import os

from bzrlib.branch import Branch
from bzrlib.commit import commit
from bzrlib.tests import TestCaseInTempDir
from bzrlib.merge import merge
from bzrlib.errors import UnrelatedBranches, NoCommits, BzrCommandError
from bzrlib.revision import common_ancestor
from bzrlib.fetch import fetch


class TestMerge(TestCaseInTempDir):
    """Test appending more than one revision"""
    def test_pending(self):
        br = Branch.initialize(".")
        commit(br, "lala!")
        self.assertEquals(len(br.working_tree().pending_merges()), 0)
        merge(['.', -1], [None, None])
        self.assertEquals(len(br.working_tree().pending_merges()), 0)

    def test_nocommits(self):
        self.test_pending()
        os.mkdir('branch2')
        br2 = Branch.initialize('branch2')
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
        br1 = Branch.open('.')
        fetch(from_branch=br2, to_branch=br1)
        # merge all of branch 2 into branch 1 even though they 
        # are not related.
        self.assertRaises(BzrCommandError, merge, ['branch2', -1], 
                          ['branch2', 0], reprocess=True, show_base=True)
        merge(['branch2', -1], ['branch2', 0], reprocess=True)
        self.assertEquals(len(br1.working_tree().pending_merges()), 1)
        return (br1, br2)

    def test_two_roots(self):
        """Merge base is sane when two unrelated branches are merged"""
        br1, br2 = self.test_pending_with_null()
        commit(br1, "blah")
        last = br1.last_revision()
        self.assertEquals(common_ancestor(last, last, br1.storage), last)

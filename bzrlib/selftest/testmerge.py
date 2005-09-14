from bzrlib.branch import Branch
from bzrlib.commit import commit
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.merge import merge
class TestMerge(TestCaseInTempDir):
    """Test appending more than one revision"""
    def test_pending(self):
        br = Branch(".", init=True)
        commit(br, "lala!")
        self.assertEquals(len(br.pending_merges()), 0)
        merge(['.', -1], [None, None])
        self.assertEquals(len(br.pending_merges()), 0)

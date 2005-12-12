from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch

class TestRemove(TestCaseInTempDir):
    def test_remove_verbose(self):
        b = Branch.initialize(u'.')
        self.build_tree(['hello'])
        wt = b.working_tree() 
        wt.add(['hello'])
        wt.commit(message='add hello')
        eq = self.assertEquals
        wt.remove(['hello'], verbose=True)

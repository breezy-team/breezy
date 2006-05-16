from StringIO import StringIO

from bzrlib.bzrdir import BzrDir
from bzrlib.status import show_pending_merges
from bzrlib.tests import TestCaseInTempDir

class TestStatus(TestCaseInTempDir):
    def test_pending_none(self):
        tree = BzrDir.create_standalone_workingtree('a')
        tree.commit('empty commit')
        tree2 = BzrDir.create_standalone_workingtree('b')
        tree2.branch.fetch(tree.branch)
        tree2.set_pending_merges([tree.last_revision()])
        output = StringIO()
        show_pending_merges(tree2, output)
        self.assertContainsRe(output.getvalue(), 'empty commit')

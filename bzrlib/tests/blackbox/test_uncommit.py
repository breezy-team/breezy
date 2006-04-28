"""\
Test the uncommit command.
"""

import os

from bzrlib.bzrdir import BzrDirMetaFormat1
from bzrlib.errors import BzrError, BoundBranchOutOfDate
from bzrlib.uncommit import uncommit
from bzrlib.tests import TestCaseInTempDir

class TestUncommit(TestCaseInTempDir):
    def test_uncommit(self):
        """Test uncommit functionality."""
        bzr = self.capture 
        os.mkdir('branch')
        os.chdir('branch')
        bzr('init')
        self.build_tree(['a', 'b', 'c'])

        bzr('add')
        bzr('commit -m initial')

        self.assertEquals(bzr('revno'), '1\n')

        open('a', 'wb').write('new contents of a\n')
        self.assertEquals(bzr('status'), 'modified:\n  a\n')
        bzr('commit -m second')

        self.assertEquals(bzr('status'), '')
        self.assertEquals(bzr('revno'), '2\n')

        txt = bzr('uncommit --dry-run --force')
        self.failIfEqual(txt.find('Dry-run'), -1)

        self.assertEquals(bzr('status'), '')
        self.assertEquals(bzr('revno'), '2\n')

        txt = bzr('uncommit --force')

        self.assertEquals(bzr('revno'), '1\n')
        self.assertEquals(bzr('status'), 'modified:\n  a\n')
        
        bzr('checkout . ../checkout')
        os.chdir('../checkout')
        self.assertEquals("", bzr('status'))
        self.assertEquals(bzr('revno'), '1\n')

        open('a', 'wb').write('new contents of a\n')
        self.assertEquals(bzr('status'), 'modified:\n  a\n')
        bzr('commit -m second')

        self.assertEquals(bzr('status'), '')
        self.assertEquals(bzr('revno'), '2\n')

        txt = bzr('uncommit --dry-run --force')
        self.failIfEqual(txt.find('Dry-run'), -1)

        self.assertEquals(bzr('status'), '')
        self.assertEquals(bzr('revno'), '2\n')

        txt = bzr('uncommit --force')

        self.assertEquals(bzr('revno'), '1\n')
        self.assertEquals(bzr('status'), 'modified:\n  a\n')

    def test_uncommit_bound(self):
        os.mkdir('a')
        a = BzrDirMetaFormat1().initialize('a')
        a.create_repository()
        a.create_branch()
        t = a.create_workingtree()
        t.commit('commit 1')
        t.commit('commit 2')
        t.commit('commit 3')
        b = t.bzrdir.sprout('b').open_branch()
        b.bind(t.branch)
        uncommit(b)
        t.set_last_revision(t.branch.last_revision())
        self.assertEqual(len(b.revision_history()), 2)
        self.assertEqual(len(t.branch.revision_history()), 2)
        t.commit('commit 3b')
        self.assertRaises(BoundBranchOutOfDate, uncommit, b)
        b.pull(t.branch)
        uncommit(b)


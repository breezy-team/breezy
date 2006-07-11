"""\
Test the uncommit command.
"""

import os

from bzrlib import uncommit, workingtree
from bzrlib.bzrdir import BzrDirMetaFormat1
from bzrlib.errors import BzrError, BoundBranchOutOfDate
from bzrlib.tests import TestCaseWithTransport


class TestUncommit(TestCaseWithTransport):
    def create_simple_tree(self):
        wt = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/c'])
        wt.add(['a', 'b', 'c'])
        wt.commit('initial commit', rev_id='a1')

        open('tree/a', 'wb').write('new contents of a\n')
        wt.commit('second commit', rev_id='a2')

        return wt

    def test_uncommit(self):
        """Test uncommit functionality."""
        wt = self.create_simple_tree()

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '--dry-run', '--force')
        self.assertContainsRe(out, 'Dry-run')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # Nothing has changed
        self.assertEqual('a2', wt.last_revision())

        # Uncommit, don't prompt
        out, err = self.run_bzr('uncommit', '--force')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # This should look like we are back in revno 1
        self.assertEqual('a1', wt.last_revision())
        out, err = self.run_bzr('status')
        self.assertEquals(out, 'modified:\n  a\n')

    def test_uncommit_checkout(self):
        wt = self.create_simple_tree()

        checkout_tree = wt.bzrdir.sprout('checkout').open_workingtree()
        checkout_tree.branch.bind(wt.branch)

        self.assertEqual('a2', checkout_tree.last_revision())

        os.chdir('checkout')
        out, err = self.run_bzr('uncommit', '--dry-run', '--force')
        self.assertContainsRe(out, 'Dry-run')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        self.assertEqual('a2', checkout_tree.last_revision())

        out, err = self.run_bzr('uncommit', '--force')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # uncommit in a checkout should uncommit the parent branch
        # (but doesn't effect the other working tree)
        self.assertEquals('a1', checkout_tree.last_revision())
        self.assertEquals('a1', wt.branch.last_revision())
        self.assertEquals('a2', wt.last_revision())

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
        uncommit.uncommit(b)
        t.set_last_revision(t.branch.last_revision())
        self.assertEqual(len(b.revision_history()), 2)
        self.assertEqual(len(t.branch.revision_history()), 2)
        t.commit('commit 3b')
        self.assertRaises(BoundBranchOutOfDate, uncommit.uncommit, b)
        b.pull(t.branch)
        uncommit.uncommit(b)

    def test_uncommit_revision(self):
        wt = self.create_simple_tree()

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '-r1', '--force')

        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')
        self.assertEqual('a1', wt.last_revision())
        self.assertEqual('a1', wt.branch.last_revision())

    def test_uncommit_neg_1(self):
        wt = self.create_simple_tree()
        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '-r', '-1', retcode=1)
        self.assertEqual('No revisions to uncommit.\n', out)

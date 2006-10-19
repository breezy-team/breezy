# Copyright (C) 2005, 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test the uncommit command."""

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
        self.assertEqual(['a2'], wt.get_parent_ids())

        # Uncommit, don't prompt
        out, err = self.run_bzr('uncommit', '--force')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # This should look like we are back in revno 1
        self.assertEqual(['a1'], wt.get_parent_ids())
        out, err = self.run_bzr('status')
        self.assertEquals(out, 'modified:\n  a\n')

    def test_uncommit_checkout(self):
        wt = self.create_simple_tree()
        checkout_tree = wt.branch.create_checkout('checkout')

        self.assertEqual(['a2'], checkout_tree.get_parent_ids())

        os.chdir('checkout')
        out, err = self.run_bzr('uncommit', '--dry-run', '--force')
        self.assertContainsRe(out, 'Dry-run')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        self.assertEqual(['a2'], checkout_tree.get_parent_ids())

        out, err = self.run_bzr('uncommit', '--force')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # uncommit in a checkout should uncommit the parent branch
        # (but doesn't effect the other working tree)
        self.assertEquals(['a1'], checkout_tree.get_parent_ids())
        self.assertEquals('a1', wt.branch.last_revision())
        self.assertEquals(['a2'], wt.get_parent_ids())

    def test_uncommit_bound(self):
        os.mkdir('a')
        a = BzrDirMetaFormat1().initialize('a')
        a.create_repository()
        a.create_branch()
        t_a = a.create_workingtree()
        t_a.commit('commit 1')
        t_a.commit('commit 2')
        t_a.commit('commit 3')
        b = t_a.branch.create_checkout('b').branch
        uncommit.uncommit(b)
        self.assertEqual(len(b.revision_history()), 2)
        self.assertEqual(len(t_a.branch.revision_history()), 2)
        # update A's tree to not have the uncomitted revision referenced.
        t_a.update()
        t_a.commit('commit 3b')
        self.assertRaises(BoundBranchOutOfDate, uncommit.uncommit, b)
        b.pull(t_a.branch)
        uncommit.uncommit(b)

    def test_uncommit_revision(self):
        wt = self.create_simple_tree()

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '-r1', '--force')

        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')
        self.assertEqual(['a1'], wt.get_parent_ids())
        self.assertEqual('a1', wt.branch.last_revision())

    def test_uncommit_neg_1(self):
        wt = self.create_simple_tree()
        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '-r', '-1', retcode=1)
        self.assertEqual('No revisions to uncommit.\n', out)

    def test_uncommit_merges(self):
        wt = self.create_simple_tree()

        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()

        tree2.commit('unchanged', rev_id='b3')
        tree2.commit('unchanged', rev_id='b4')

        wt.merge_from_branch(tree2.branch)
        wt.commit('merge b4', rev_id='a3')

        self.assertEqual(['a3'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '--force')

        self.assertEqual(['a2', 'b4'], wt.get_parent_ids())

    def test_uncommit_pending_merge(self):
        wt = self.create_simple_tree()
        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('unchanged', rev_id='b3')

        wt.branch.fetch(tree2.branch)
        wt.set_pending_merges(['b3'])

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '--force')
        self.assertEqual(['a1', 'b3'], wt.get_parent_ids())

    def test_uncommit_multiple_merge(self):
        wt = self.create_simple_tree()

        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()

        tree2.commit('unchanged', rev_id='b3')

        wt.merge_from_branch(tree2.branch)
        wt.commit('merge b3', rev_id='a3')

        tree2.commit('unchanged', rev_id='b4')

        wt.merge_from_branch(tree2.branch)
        wt.commit('merge b4', rev_id='a4')

        self.assertEqual(['a4'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '--force', '-r', '2')

        self.assertEqual(['a2', 'b3', 'b4'], wt.get_parent_ids())

    def test_uncommit_merge_plus_pending(self):
        wt = self.create_simple_tree()

        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()

        tree2.commit('unchanged', rev_id='b3')
        wt.branch.fetch(tree2.branch)
        wt.set_pending_merges(['b3'])
        wt.commit('merge b3', rev_id='a3')

        tree2.commit('unchanged', rev_id='b4')
        wt.branch.fetch(tree2.branch)
        wt.set_pending_merges(['b4'])

        self.assertEqual(['a3', 'b4'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '--force', '-r', '2')

        self.assertEqual(['a2', 'b3', 'b4'], wt.get_parent_ids())

    def test_uncommit_octopus_merge(self):
        # Check that uncommit keeps the pending merges in the same order
        wt = self.create_simple_tree()

        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()
        tree3 = wt.bzrdir.sprout('tree3').open_workingtree()

        tree2.commit('unchanged', rev_id='b3')
        tree3.commit('unchanged', rev_id='c3')
        
        wt.merge_from_branch(tree2.branch)
        wt.merge_from_branch(tree3.branch)
        wt.commit('merge b3, c3', rev_id='a3')

        tree2.commit('unchanged', rev_id='b4')
        tree3.commit('unchanged', rev_id='c4')

        wt.merge_from_branch(tree3.branch)
        wt.merge_from_branch(tree2.branch)
        wt.commit('merge b4, c4', rev_id='a4')

        self.assertEqual(['a4'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit', '--force', '-r', '2')

        self.assertEqual(['a2', 'b3', 'c3', 'c4', 'b4'], wt.get_parent_ids())

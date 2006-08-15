# Copyright (C) 2006 by Canonical Ltd
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

"""Test the executable bit under various working tree formats."""

import os

from bzrlib.inventory import InventoryFile
from bzrlib.transform import TreeTransform
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestExecutable(TestCaseWithWorkingTree):

    def setUp(self):
        super(TestExecutable, self).setUp()

        self.a_id = "a-20051208024829-849e76f7968d7a86"
        self.b_id = "b-20051208024829-849e76f7968d7a86"
        wt = self.make_branch_and_tree('b1')
        b = wt.branch
        tt = TreeTransform(wt)
        tt.new_file('a', tt.root, 'a test\n', self.a_id, True)
        tt.new_file('b', tt.root, 'b test\n', self.b_id, False)
        tt.apply()

        self.wt = wt

    def check_exist(self, tree):
        """Just check that both files have the right executable bits set"""
        measured = []
        for cn, ie in tree.inventory.iter_entries():
            if isinstance(ie, InventoryFile):
                measured.append((cn, ie.executable))
        self.assertEqual([('a', True), ('b', False)], measured)
        self.failUnless(tree.is_executable(self.a_id),
                        "'a' lost the execute bit")
        self.failIf(tree.is_executable(self.b_id),
                    "'b' gained an execute bit")

    def check_empty(self, tree, ignore_inv=False):
        """Check that the files are truly missing
        :param ignore_inv: If you just delete files from a working tree
                the inventory still shows them, so don't assert that
                the inventory is empty, just that the tree doesn't have them
        """
        if not ignore_inv:
            self.assertEqual(
                [('', tree.inventory.root)],
                list(tree.inventory.iter_entries()))
        self.failIf(tree.has_id(self.a_id))
        self.failIf(tree.has_filename('a'))
        self.failIf(tree.has_id(self.b_id))
        self.failIf(tree.has_filename('b'))

    def commit_and_branch(self):
        """Commit the current tree, and create a second tree"""
        self.wt.commit('adding a,b', rev_id='r1')

        # Now make sure that 'bzr branch' also preserves the
        # executable bit
        # TODO: Maybe this should be a blackbox test
        dir2 = self.wt.branch.bzrdir.clone('b2', revision_id='r1')
        wt2 = dir2.open_workingtree()
        self.assertEqual('r1', wt2.last_revision())
        self.assertEqual('r1', wt2.branch.last_revision())
        return wt2

    def test_01_is_executable(self):
        """Make sure that the tree was created and has the executable bit set"""
        self.check_exist(self.wt)

    def test_02_stays_executable(self):
        """reopen the tree and ensure it stuck."""
        self.wt = self.wt.bzrdir.open_workingtree()
        self.check_exist(self.wt)

    def test_03_after_commit(self):
        """Commit the change, and check the history"""
        self.wt.commit('adding a,b', rev_id='r1')

        rev_tree = self.wt.branch.repository.revision_tree('r1')
        self.check_exist(rev_tree)

    def test_04_after_removed(self):
        """Make sure reverting removed files brings them back correctly"""
        self.wt.commit('adding a,b', rev_id='r1')

        # Make sure the entries are gone
        os.remove('b1/a')
        os.remove('b1/b')
        self.check_empty(self.wt, ignore_inv=True)

        # Make sure that revert is able to bring them back,
        # and sets 'a' back to being executable

        rev_tree = self.wt.branch.repository.revision_tree('r1')

        self.wt.revert(['a', 'b'], rev_tree, backups=False)
        self.check_exist(self.wt)

    def test_05_removed_and_committed(self):
        """Check that reverting to an earlier commit restores them"""
        self.wt.commit('adding a,b', rev_id='r1')

        # Now remove them again, and make sure that after a
        # commit, they are still marked correctly
        os.remove('b1/a')
        os.remove('b1/b')
        self.wt.commit('removed', rev_id='r2')

        self.check_empty(self.wt)

        rev_tree = self.wt.branch.repository.revision_tree('r1')
        # Now revert back to the previous commit
        self.wt.revert([], rev_tree, backups=False)

        self.check_exist(self.wt)

    def test_06_branch(self):
        """branch b1=>b2 should preserve the executable bits"""
        # TODO: Maybe this should be a blackbox test
        wt2 = self.commit_and_branch()

        self.check_exist(wt2)

    def test_07_pull(self):
        """Test that pull will handle bits correctly"""
        wt2 = self.commit_and_branch()

        os.remove('b1/a')
        os.remove('b1/b')
        self.wt.commit('removed', rev_id='r2')

        # now wt2 can pull and the files should be removed

        # Make sure pull will delete the files
        wt2.pull(self.wt.branch)
        self.assertEquals('r2', wt2.last_revision())
        self.assertEquals('r2', wt2.branch.last_revision())
        self.check_empty(wt2)

        # Now restore the files on the first branch and commit
        # so that the second branch can pull the changes
        # and make sure that the executable bit has been copied
        rev_tree = self.wt.branch.repository.revision_tree('r1')
        self.wt.revert([], rev_tree, backups=False)
        self.wt.commit('resurrected', rev_id='r3')

        self.check_exist(self.wt)

        wt2.pull(self.wt.branch)
        self.assertEquals('r3', wt2.last_revision())
        self.assertEquals('r3', wt2.branch.last_revision())
        self.check_exist(wt2)

    def test_08_no_op_revert(self):
        """Just do a simple revert without anything changed
        
        The bits shouldn't swap.
        """
        self.wt.commit('adding a,b', rev_id='r1')
        rev_tree = self.wt.branch.repository.revision_tree('r1')
        self.wt.revert([], rev_tree, backups=False)
        self.check_exist(self.wt)


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

from bzrlib.transform import TreeTransform
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestExecutable(TestCaseWithWorkingTree):

    def test_stays_executable(self):
        a_id = "a-20051208024829-849e76f7968d7a86"
        b_id = "b-20051208024829-849e76f7968d7a86"
        wt = self.make_branch_and_tree('b1')
        b = wt.branch
        tt = TreeTransform(wt)
        tt.new_file('a', tt.root, 'a test\n', a_id, True)
        tt.new_file('b', tt.root, 'b test\n', b_id, False)
        tt.apply()

        self.failUnless(wt.is_executable(a_id), "'a' lost the execute bit")

        # reopen the tree and ensure it stuck.
        wt = wt.bzrdir.open_workingtree()
        self.assertEqual(['a', 'b'], [cn for cn,ie in wt.inventory.iter_entries()])

        self.failUnless(wt.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(wt.is_executable(b_id), "'b' gained an execute bit")

        wt.commit('adding a,b', rev_id='r1')

        rev_tree = b.repository.revision_tree('r1')
        self.failUnless(rev_tree.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(rev_tree.is_executable(b_id), "'b' gained an execute bit")

        self.failUnless(rev_tree.inventory[a_id].executable)
        self.failIf(rev_tree.inventory[b_id].executable)

        # Make sure the entries are gone
        os.remove('b1/a')
        os.remove('b1/b')
        self.failIf(wt.has_id(a_id))
        self.failIf(wt.has_filename('a'))
        self.failIf(wt.has_id(b_id))
        self.failIf(wt.has_filename('b'))

        # Make sure that revert is able to bring them back,
        # and sets 'a' back to being executable

        wt.revert(['a', 'b'], rev_tree, backups=False)
        self.assertEqual(['a', 'b'], [cn for cn,ie in wt.inventory.iter_entries()])

        self.failUnless(wt.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(wt.is_executable(b_id), "'b' gained an execute bit")

        # Now remove them again, and make sure that after a
        # commit, they are still marked correctly
        os.remove('b1/a')
        os.remove('b1/b')
        wt.commit('removed', rev_id='r2')

        self.assertEqual([], [cn for cn,ie in wt.inventory.iter_entries()])
        self.failIf(wt.has_id(a_id))
        self.failIf(wt.has_filename('a'))
        self.failIf(wt.has_id(b_id))
        self.failIf(wt.has_filename('b'))

        # Now revert back to the previous commit
        wt.revert([], rev_tree, backups=False)
        self.assertEqual(['a', 'b'], [cn for cn,ie in wt.inventory.iter_entries()])

        self.failUnless(wt.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(wt.is_executable(b_id), "'b' gained an execute bit")

        # Now make sure that 'bzr branch' also preserves the
        # executable bit
        # TODO: Maybe this should be a blackbox test
        d2 = b.bzrdir.clone('b2', revision_id='r1')
        t2 = d2.open_workingtree()
        b2 = t2.branch
        self.assertEquals('r1', b2.last_revision())

        self.assertEqual(['a', 'b'], [cn for cn,ie in t2.inventory.iter_entries()])
        self.failUnless(t2.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(t2.is_executable(b_id), "'b' gained an execute bit")

        # Make sure pull will delete the files
        t2.pull(b)
        self.assertEquals('r2', b2.last_revision())
        self.assertEqual([], [cn for cn,ie in t2.inventory.iter_entries()])

        # Now commit the changes on the first branch
        # so that the second branch can pull the changes
        # and make sure that the executable bit has been copied
        wt.commit('resurrected', rev_id='r3')

        t2.pull(b)
        self.assertEquals('r3', b2.last_revision())
        self.assertEqual(['a', 'b'], [cn for cn,ie in t2.inventory.iter_entries()])

        self.failUnless(t2.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(t2.is_executable(b_id), "'b' gained an execute bit")

        # Just do a simple revert without anything changed, and 
        # make sure the bits don't swap.
        t2.revert([], t2.branch.repository.revision_tree('r3'), backups=False)
        self.assertEqual(['a', 'b'], [cn for cn,ie in t2.inventory.iter_entries()])

        self.failUnless(t2.is_executable(a_id), "'a' lost the execute bit")
        self.failIf(t2.is_executable(b_id), "'b' gained an execute bit")

    def test_executable(self):
        """Format 3 trees should keep executable=yes in the working inventory."""
        wt = self.make_branch_and_tree('.')
        tt = TreeTransform(wt)
        tt.new_file('a', tt.root, 'contents of a\n', 'a-xxyy', True)
        tt.new_file('b', tt.root, 'contents of b\n', 'b-xxyy', False)
        tt.apply()

        tree_values = [(cn, ie.executable) 
                       for cn,ie in wt.inventory.iter_entries()]
        self.assertEqual([('a', True), ('b', False)], tree_values)

        # Committing shouldn't remove it
        wt.commit('first rev')
        tree_values = [(cn, ie.executable) 
                       for cn,ie in wt.inventory.iter_entries()]
        self.assertEqual([('a', True), ('b', False)], tree_values)

        # And neither should reverting
        last_tree = wt.branch.repository.revision_tree(wt.last_revision())
        wt.revert([], last_tree, backups=False)
        tree_values = [(cn, ie.executable) 
                       for cn,ie in wt.inventory.iter_entries()]
        self.assertEqual([('a', True), ('b', False)], tree_values)

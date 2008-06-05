# Copyright (C) 2006 Canonical Ltd
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


from bzrlib import (
    errors,
    revision as _mod_revision,
    )
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch


"""Tests for branch.update()"""


class TestUpdate(TestCaseWithBranch):

    def test_update_unbound_works(self):
        b = self.make_branch('.')
        b.update()
        self.assertEqual(_mod_revision.NULL_REVISION,
                         _mod_revision.ensure_null(b.last_revision()))

    def test_update_prefix_returns_none(self):
        # update in a branch when its a prefix of the master should
        # indicate that no local changes were present.
        master_tree = self.make_branch_and_tree('master')
        child_tree = self.make_branch_and_tree('child')
        try:
            child_tree.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # old branch, cant test.
            return
        # commit to the child to make the last rev not-None.
        child_tree.commit('foo', rev_id='foo', allow_pointless=True)
        # update the master so we can commit there.
        master_tree.update()
        # commit to the master making the child tree out of date and a prefix.
        master_tree.commit('bar', rev_id='bar', allow_pointless=True)
        self.assertEqual(None, child_tree.branch.update())

    def test_update_local_commits_returns_old_tip(self):
        # update in a branch when its not a prefix of the master should
        # return the previous tip and reset the revision history.
        master_tree = self.make_branch_and_tree('master')
        child_tree = self.make_branch_and_tree('child')
        try:
            child_tree.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # old branch, cant test.
            return
        # commit to the child to make the last rev not-None and skew it from master.
        child_tree.commit('foo', rev_id='foo', allow_pointless=True, local=True)
        # commit to the master making the child tree out of date and not a prefix.
        master_tree.commit('bar', rev_id='bar', allow_pointless=True)
        self.assertEqual('foo', child_tree.branch.update())
        self.assertEqual(['bar'], child_tree.branch.revision_history())


class TestUpdateRevisions(TestCaseWithBranch):

    def test_accepts_graph(self):
        # An implementation may not use it, but it should allow a 'graph' to be
        # supplied
        tree1 = self.make_branch_and_tree('tree1')
        rev1 = tree1.commit('one')
        tree2 = tree1.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree2.commit('two')

        tree1.lock_write()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        graph = tree2.branch.repository.get_graph(tree1.branch.repository)

        tree1.branch.update_revisions(tree2.branch, graph=graph)
        self.assertEqual((2, rev2), tree1.branch.last_revision_info())

    def test_overwrite_ignores_diverged(self):
        tree1 = self.make_branch_and_tree('tree1')
        rev1 = tree1.commit('one')
        tree2 = tree1.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree1.commit('two')
        rev2b = tree2.commit('alt two')

        self.assertRaises(errors.DivergedBranches,
                          tree1.branch.update_revisions,
                          tree2.branch, overwrite=False)
        # However, the revision should be copied into the repository
        self.assertTrue(tree1.branch.repository.has_revision(rev2b))

        tree1.branch.update_revisions(tree2.branch, overwrite=True)
        self.assertEqual((2, rev2b), tree1.branch.last_revision_info())

    def test_ignores_older_unless_overwrite(self):
        tree1 = self.make_branch_and_tree('tree1')
        rev1 = tree1.commit('one')
        tree2 = tree1.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree1.commit('two')

        tree1.branch.update_revisions(tree2.branch)
        self.assertEqual((2, rev2), tree1.branch.last_revision_info())

        tree1.branch.update_revisions(tree2.branch, overwrite=True)
        self.assertEqual((1, rev1), tree1.branch.last_revision_info())

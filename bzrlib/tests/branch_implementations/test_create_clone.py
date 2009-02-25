# Copyright (C) 2009 Canonical Ltd
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

"""Tests for branch.create_clone behaviour."""

from bzrlib.branch import Branch
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib import remote


class TestCreateClone(TestCaseWithBranch):

    def test_create_clone_on_transport_no_revision_id(self):
        tree = self.make_branch_and_tree('source')
        tree.commit('a commit')
        source = tree.branch
        target_transport = self.get_transport('target')
        result = tree.branch.create_clone_on_transport(target_transport)
        self.assertEqual(source.last_revision(), result.last_revision())

    def test_create_clone_on_transport_revision_id(self):
        tree = self.make_branch_and_tree('source')
        old_revid = tree.commit('a commit')
        source_tip = tree.commit('a second commit')
        source = tree.branch
        target_transport = self.get_transport('target')
        result = tree.branch.create_clone_on_transport(target_transport,
            revision_id=old_revid)
        self.assertEqual(old_revid, result.last_revision())
        result.lock_read()
        self.addCleanup(result.unlock)
        self.assertFalse(result.repository.has_revision(source_tip))

    def test_create_clone_on_transport_stacked(self):
        tree = self.make_branch_and_tree('source')
        tree.commit('a commit')
        trunk = tree.branch.create_clone_on_transport(
            self.get_transport('trunk'))
        revid = tree.commit('a second commit')
        source = tree.branch
        target_transport = self.get_transport('target')
        result = tree.branch.create_clone_on_transport(target_transport,
            stacked_on=trunk.base)
        self.assertEqual(revid, result.last_revision())
        self.assertEqual(trunk.base, result.get_stacked_on_url())

    def assertBranchHookBranchIsStacked(self, pre_change_params):
        # Just calling will either succeed or fail.
        pre_change_params.branch.get_stacked_on_url()
        self.hook_calls.append(pre_change_params)

    def test_create_clone_on_transport_stacked_hooks_get_stacked_branch(self):
        tree = self.make_branch_and_tree('source')
        tree.commit('a commit')
        trunk = tree.branch.create_clone_on_transport(
            self.get_transport('trunk'))
        revid = tree.commit('a second commit')
        source = tree.branch
        target_transport = self.get_transport('target')
        self.hook_calls = []
        Branch.hooks.install_named_hook("pre_change_branch_tip",
            self.assertBranchHookBranchIsStacked, None)
        result = tree.branch.create_clone_on_transport(target_transport,
            stacked_on=trunk.base)
        self.assertEqual(revid, result.last_revision())
        self.assertEqual(trunk.base, result.get_stacked_on_url())
        # Smart servers invoke hooks on both sides
        if isinstance(result, remote.RemoteBranch):
            expected_calls = 2
        else:
            expected_calls = 1
        self.assertEqual(expected_calls, len(self.hook_calls))

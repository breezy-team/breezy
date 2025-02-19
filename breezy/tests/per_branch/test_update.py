# Copyright (C) 2006-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


from breezy import branch, errors, tests
from breezy import revision as _mod_revision
from breezy.tests import per_branch

"""Tests for branch.update()"""


class TestUpdate(per_branch.TestCaseWithBranch):
    def test_update_unbound_works(self):
        b = self.make_branch(".")
        b.update()
        self.assertEqual(_mod_revision.NULL_REVISION, b.last_revision())

    def test_update_prefix_returns_none(self):
        # update in a branch when its a prefix of the master should
        # indicate that no local changes were present.
        master_tree = self.make_branch_and_tree("master")
        child_tree = self.make_branch_and_tree("child")
        try:
            child_tree.branch.bind(master_tree.branch)
        except branch.BindingUnsupported:
            # old branch, cant test.
            return
        # commit to the child to make the last rev not-None.
        child_tree.commit("foo", rev_id=b"foo", allow_pointless=True)
        # update the master so we can commit there.
        master_tree.update()
        # commit to the master making the child tree out of date and a prefix.
        master_tree.commit("bar", rev_id=b"bar", allow_pointless=True)
        self.assertEqual(None, child_tree.branch.update())

    def test_update_local_commits_returns_old_tip(self):
        # update in a branch when its not a prefix of the master should
        # return the previous tip and reset the revision history.
        master_tree = self.make_branch_and_tree("master")
        child_tree = self.make_branch_and_tree("child")
        try:
            child_tree.branch.bind(master_tree.branch)
        except branch.BindingUnsupported:
            # old branch, cant test.
            return
        # commit to the child to make the last rev not-None and skew it from master.
        child_tree.commit("foo", rev_id=b"foo", allow_pointless=True, local=True)
        # commit to the master making the child tree out of date and not a prefix.
        master_tree.commit("bar", rev_id=b"bar", allow_pointless=True)
        self.assertEqual(b"foo", child_tree.branch.update())
        self.assertEqual(b"bar", child_tree.branch.last_revision())

    def test_update_in_checkout_of_readonly(self):
        tree1 = self.make_branch_and_tree("tree1")
        rev1 = tree1.commit("one")
        try:
            tree1.branch.tags.set_tag("test-tag", rev1)
        except errors.TagsNotSupported:
            # Tags not supported
            raise tests.TestNotApplicable("only triggered from branches with tags")
        readonly_branch1 = branch.Branch.open("readonly+" + tree1.branch.base)
        tree2 = tree1.controldir.sprout("tree2").open_workingtree()
        try:
            tree2.branch.bind(readonly_branch1)
        except branch.BindingUnsupported:
            # old branch, cant test.
            raise tests.TestNotApplicable("only triggered in bound branches")
        rev2 = tree1.commit("two")
        tree2.update()
        self.assertEqual(rev2, tree2.branch.last_revision())

# Copyright (C) 2008 Canonical Ltd
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

"""Tests for Branch.get_stacked_on_url and set_stacked_on."""

from bzrlib import (
    bzrdir,
    errors,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestStacking(TestCaseWithBranch):

    def test_get_set_stacked_on(self):
        # branches must either:
        # raise UnstackableBranchFormat or
        # raise UnstackableRepositoryFormat or
        # permit stacking to be done and then return the stacked location.
        branch = self.make_branch('branch')
        target = self.make_branch('target')
        old_format_errors = (
            errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
            )
        try:
            branch.set_stacked_on(target.base)
        except old_format_errors:
            # if the set failed, so must the get
            self.assertRaises(old_format_errors, branch.get_stacked_on_url)
            return
        # now we have a stacked branch:
        self.assertEqual(target.base, branch.get_stacked_on_url())
        branch.set_stacked_on(None)
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)

    def assertRevisionInRepository(self, repo_path, revid):
        """Check that a revision is in a repository, disregarding stacking."""
        repo = bzrdir.BzrDir.open(repo_path).open_repository()
        self.assertTrue(repo.has_revision(revid))

    def assertRevisionNotInRepository(self, repo_path, revid):
        """Check that a revision is not in a repository, disregarding stacking."""
        repo = bzrdir.BzrDir.open(repo_path).open_repository()
        self.assertFalse(repo.has_revision(revid))

    def test_get_graph_stacked(self):
        """A stacked repository shows the graph of its parent."""
        trunk_tree = self.make_branch_and_tree('mainline')
        trunk_revid = trunk_tree.commit('mainline')
        # make a new branch, and stack on the existing one.  we don't use
        # sprout(stacked=True) here because if that is buggy and copies data
        # it would cause a false pass of this test.
        new_branch = self.make_branch('new_branch')
        try:
            new_branch.set_stacked_on(trunk_tree.branch.base)
        except (errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat), e:
            raise TestNotApplicable(e)
        # reading the graph from the stacked branch's repository should see
        # data from the stacked-on branch
        new_repo = new_branch.repository
        new_repo.lock_read()
        try:
            self.assertEqual(new_repo.get_parent_map([trunk_revid]),
                {trunk_revid: (NULL_REVISION, )})
        finally:
            new_repo.unlock()

    def test_sprout_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('mainline')
        trunk_revid = trunk_tree.commit('mainline')
        # and make branch from it which is stacked
        try:
            new_dir = trunk_tree.bzrdir.sprout('newbranch', stacked=True)
        except (errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat), e:
            raise TestNotApplicable(e)
        # stacked repository
        self.assertRevisionNotInRepository('newbranch', trunk_revid)
        new_tree = new_dir.open_workingtree()
        new_tree.commit('something local')

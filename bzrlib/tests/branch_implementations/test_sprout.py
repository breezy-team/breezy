# Copyright (C) 2007 Canonical Ltd
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

"""Tests for Branch.sprout()"""

from bzrlib import (
    remote,
    tests,
    )
from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestSprout(TestCaseWithBranch):

    def test_sprout_branch_nickname(self):
        # test the nick name is reset always
        raise tests.TestSkipped('XXX branch sprouting is not yet tested..')

    def test_sprout_branch_parent(self):
        source = self.make_branch('source')
        target = source.bzrdir.sprout(self.get_url('target')).open_branch()
        self.assertEqual(source.bzrdir.root_transport.base, target.get_parent())

    def test_sprout_preserves_kind(self):
        branch1 = self.make_branch('branch1')
        target_repo = self.make_repository('branch2')
        target_repo.fetch(branch1.repository)
        branch2 = branch1.sprout(target_repo.bzrdir)
        if isinstance(branch1, remote.RemoteBranch):
            branch1._ensure_real()
            target_class = branch1._real_branch.__class__
        else:
            target_class = branch1.__class__
        self.assertIsInstance(branch2, target_class)

    def test_sprout_partial(self):
        # test sprouting with a prefix of the revision-history.
        # also needs not-on-revision-history behaviour defined.
        wt_a = self.make_branch_and_tree('a')
        self.build_tree(['a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')
        self.build_tree(['a/two'])
        wt_a.add(['two'])
        wt_a.commit('commit two', rev_id='2')
        repo_b = self.make_repository('b')
        repo_a = wt_a.branch.repository
        repo_a.copy_content_into(repo_b)
        br_b = wt_a.branch.sprout(repo_b.bzrdir, revision_id='1')
        self.assertEqual('1', br_b.last_revision())

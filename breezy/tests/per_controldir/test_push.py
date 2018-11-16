# Copyright (C) 2009, 2010, 2016 Canonical Ltd
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

"""Tests for bzrdir implementations - push."""

from ...errors import LossyPushToSameVCS

from breezy.tests.per_controldir import (
    TestCaseWithControlDir,
    )


class TestPush(TestCaseWithControlDir):

    def create_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'])
        rev_1 = tree.commit('one')
        return tree, rev_1

    def test_push_new_branch(self):
        tree, rev_1 = self.create_simple_tree()
        dir = self.make_repository('dir').controldir
        result = dir.push_branch(tree.branch)
        self.assertEqual(tree.branch, result.source_branch)
        self.assertEqual(dir.open_branch().base, result.target_branch.base)
        self.assertEqual(dir.open_branch().base,
                         tree.branch.get_push_location())

    def test_push_new_branch_lossy(self):
        tree, rev_1 = self.create_simple_tree()
        dir = self.make_repository('dir').controldir
        self.assertRaises(LossyPushToSameVCS, dir.push_branch,
                          tree.branch, lossy=True)

    def test_push_new_empty(self):
        tree = self.make_branch_and_tree('tree')
        dir = self.make_repository('dir').controldir
        result = dir.push_branch(tree.branch)
        self.assertEqual(tree.branch.base, result.source_branch.base)
        self.assertEqual(dir.open_branch().base,
                         result.target_branch.base)

    def test_push_incremental(self):
        tree, rev1 = self.create_simple_tree()
        dir = self.make_repository('dir').controldir
        dir.push_branch(tree.branch)
        self.build_tree(['tree/b'])
        tree.add(['b'])
        rev_2 = tree.commit('two')
        result = dir.push_branch(tree.branch)
        self.assertEqual(tree.last_revision(),
                         result.branch_push_result.new_revid)
        self.assertEqual(2, result.branch_push_result.new_revno)
        self.assertEqual(tree.branch.base, result.source_branch.base)
        self.assertEqual(dir.open_branch().base, result.target_branch.base)

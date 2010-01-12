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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for bzrdir implementations - push."""

from bzrlib import (
    errors,
    )
from bzrlib.tests.per_bzrdir import (
    TestCaseWithBzrDir,
    )


class TestPush(TestCaseWithBzrDir):

    def create_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a-id'])
        tree.commit('one', rev_id='r1')
        return tree

    def test_push_new_branch(self):
        tree = self.create_simple_tree()
        dir = self.make_repository('dir').bzrdir
        result = dir.push_branch(tree.branch)
        self.assertEquals(tree.branch, result.source_branch)
        self.assertEquals(dir.open_branch().base, result.target_branch.base)
        self.assertEquals(dir.open_branch().base,
            tree.branch.get_push_location())

    def test_push_new_empty(self):
        tree = self.make_branch_and_tree('tree')
        dir = self.make_repository('dir').bzrdir
        result = dir.push_branch(tree.branch)
        self.assertEquals(tree.branch.base, result.source_branch.base)
        self.assertEquals(dir.open_branch().base,
            result.target_branch.base)

    def test_push_incremental(self):
        tree = self.create_simple_tree()
        dir = self.make_repository('dir').bzrdir
        dir.push_branch(tree.branch)
        self.build_tree(['tree/b'])
        tree.add(['b'])
        tree.commit('two', rev_id='r2')
        result = dir.push_branch(tree.branch)
        self.assertEquals(tree.last_revision(),
            result.branch_push_result.new_revid)
        self.assertEquals(2, result.branch_push_result.new_revno)
        self.assertEquals(tree.branch.base, result.source_branch.base)
        self.assertEquals(dir.open_branch().base, result.target_branch.base)

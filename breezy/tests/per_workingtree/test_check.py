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

"""Tests for checking of trees."""

from breezy.tests.per_workingtree import TestCaseWithWorkingTree

from breezy.bzr.workingtree import InventoryWorkingTree
from breezy.tests import TestNotApplicable


class TestCheck(TestCaseWithWorkingTree):

    def test__get_check_refs_new(self):
        tree = self.make_branch_and_tree('tree')
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable(
                "_get_check_refs only relevant for inventory working trees")
        self.assertEqual({('trees', b'null:')},
                         set(tree._get_check_refs()))

    def test__get_check_refs_basis(self):
        # with a basis, all current bzr trees cache it and so need the
        # inventory to cross-check.
        tree = self.make_branch_and_tree('tree')
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable(
                "_get_check_refs only relevant for inventory working trees")
        revid = tree.commit('first post')
        self.assertEqual({('trees', revid)},
                         set(tree._get_check_refs()))

    def test__check_with_refs(self):
        # _check can be called with a dict of the things required.
        tree = self.make_branch_and_tree('tree')
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable(
                "_get_check_refs only relevant for inventory working trees")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        revid = tree.commit('first post')
        needed_refs = tree._get_check_refs()
        repo = tree.branch.repository
        for ref in needed_refs:
            kind, revid = ref
            refs = {}
            if kind == 'trees':
                refs[ref] = repo.revision_tree(revid)
            else:
                self.fail('unknown ref kind')
        tree._check(refs)

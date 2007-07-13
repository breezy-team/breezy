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

"""Tests of the parent related functions of WorkingTrees."""

import os

from bzrlib import (
    errors,
    revision as _mod_revision,
    symbol_versioning,
    uncommit,
    )
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestUncommit(TestCaseWithWorkingTree):

    def test_uncommit_to_null(self):
        tree = self.make_branch_and_tree('branch')
        tree.lock_write()
        revid = tree.commit('a revision')
        tree.unlock()
        uncommit.uncommit(tree.branch, tree=tree)
        self.assertEqual([], tree.get_parent_ids())

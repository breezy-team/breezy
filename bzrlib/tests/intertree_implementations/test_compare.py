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

"""Tests for the InterTree.compare() function."""

from bzrlib import inventory 
from bzrlib.tests.intertree_implementations import TestCaseWithTwoTrees


class TestCompare(TestCaseWithTwoTrees):

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_to_tree_no_parents_no_content(tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.modified)

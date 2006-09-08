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

"""Tests for Tree.revision_tree."""

from bzrlib import errors
from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestRevisionTree(TestCaseWithTree):

    def create_tree_no_parents_no_content(self):
        tree = self.make_branch_and_tree('.')
        return self.get_tree_no_parents_no_content(tree)

    def test_get_random_tree_raises(self):
        test_tree = self.create_tree_no_parents_no_content()
        self.assertRaises(errors.NoSuchRevision, test_tree.revision_tree,
            'this-should-not-exist')

# Copyright (C) 2006 Canonical Ltd
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


"""Tests for comparison functionality"""

from bzrlib.delta import compare_trees
from bzrlib.tests import TestCaseInTempDir
from bzrlib.bzrdir import BzrDir


class TestDelta(TestCaseInTempDir):

    def test_compare_tree_with_root(self):
        wt = BzrDir.create_standalone_workingtree('.')
        delta = compare_trees(wt.basis_tree(), wt)
        self.assertEqual(len(delta.added), 0)
        delta = compare_trees(wt.basis_tree(), wt, include_root=True)
        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0][0], '')

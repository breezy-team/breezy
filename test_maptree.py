# Copyright (C) 2006-2007 by Jelmer Vernooij
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
"""Tests for the maptree code."""

from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.treebuilder import TreeBuilder

from maptree import MapTree


class MapTreeTests(TestCaseWithTransport):
    def setUp(self):
        super(MapTreeTests, self).setUp()

    def test_empty_map(self):
        tree = self.make_branch_and_memory_tree('branch') 
        builder = TreeBuilder()
        builder.start_tree(tree)
        builder.build(['foo'])
        builder.finish_tree()
        m = MapTree(tree, {})

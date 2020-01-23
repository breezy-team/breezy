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

from ....tests import (
    TestCase,
    TestCaseWithTransport,
    )
from ....treebuilder import (
    TreeBuilder,
    )

from ..maptree import (
    MapTree,
    map_file_ids,
    )


class EmptyMapTreeTests(TestCaseWithTransport):

    def setUp(self):
        super(EmptyMapTreeTests, self).setUp()
        tree = self.make_branch_and_tree('branch')
        self.oldtree = tree

    def test_has_filename(self):
        self.oldtree.lock_write()
        builder = TreeBuilder()
        builder.start_tree(self.oldtree)
        builder.build(['foo'])
        builder.finish_tree()
        self.maptree = MapTree(self.oldtree, {})
        self.oldtree.unlock()
        self.assertTrue(self.maptree.has_filename('foo'))
        self.assertTrue(self.oldtree.has_filename('foo'))
        self.assertFalse(self.maptree.has_filename('bar'))

    def test_path2id(self):
        self.oldtree.lock_write()
        self.addCleanup(self.oldtree.unlock)
        builder = TreeBuilder()
        builder.start_tree(self.oldtree)
        builder.build(['foo'])
        builder.build(['bar'])
        builder.build(['bla'])
        builder.finish_tree()
        self.maptree = MapTree(self.oldtree, {})
        self.assertEquals(self.oldtree.path2id("foo"),
                          self.maptree.path2id("foo"))

    def test_id2path(self):
        self.oldtree.lock_write()
        self.addCleanup(self.oldtree.unlock)
        builder = TreeBuilder()
        builder.start_tree(self.oldtree)
        builder.build(['foo'])
        builder.build(['bar'])
        builder.build(['bla'])
        builder.finish_tree()
        self.maptree = MapTree(self.oldtree, {})
        self.assertEquals(
            "foo", self.maptree.id2path(self.maptree.path2id("foo")))


class MapFileIdTests(TestCase):

    def test_empty(self):
        self.assertEquals({}, map_file_ids(None, [], []))

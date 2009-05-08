# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for the TreeBuilder helper class."""

from bzrlib import errors, tests
from bzrlib.memorytree import MemoryTree
from bzrlib.tests import TestCaseWithTransport
from bzrlib.treebuilder import TreeBuilder


class FakeTree(object):
    """A pretend tree to test the calls made by TreeBuilder."""

    def __init__(self):
        self._calls = []

    def lock_tree_write(self):
        self._calls.append("lock_tree_write")

    def unlock(self):
        self._calls.append("unlock")


class TestFakeTree(TestCaseWithTransport):

    def testFakeTree(self):
        """Check that FakeTree works as required for the TreeBuilder tests."""
        tree = FakeTree()
        self.assertEqual([], tree._calls)
        tree.lock_tree_write()
        self.assertEqual(["lock_tree_write"], tree._calls)
        tree.unlock()
        self.assertEqual(["lock_tree_write", "unlock"], tree._calls)


class TestTreeBuilderMemoryTree(tests.TestCaseWithMemoryTransport):

    def test_create(self):
        builder = TreeBuilder()

    def test_start_tree_locks_write(self):
        builder = TreeBuilder()
        tree = FakeTree()
        builder.start_tree(tree)
        self.assertEqual(["lock_tree_write"], tree._calls)

    def test_start_tree_when_started_fails(self):
        builder = TreeBuilder()
        tree = FakeTree()
        builder.start_tree(tree)
        self.assertRaises(errors.AlreadyBuilding, builder.start_tree, tree)

    def test_finish_tree_not_started_errors(self):
        builder = TreeBuilder()
        self.assertRaises(errors.NotBuilding, builder.finish_tree)

    def test_finish_tree_unlocks(self):
        builder = TreeBuilder()
        tree = FakeTree()
        builder.start_tree(tree)
        builder.finish_tree()
        self.assertEqual(["lock_tree_write", "unlock"], tree._calls)

    def test_build_tree_not_started_errors(self):
        builder = TreeBuilder()
        self.assertRaises(errors.NotBuilding, builder.build, "foo")

    def test_build_tree(self):
        """Test building works using a MemoryTree."""
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        builder = TreeBuilder()
        builder.start_tree(tree)
        builder.build(['foo', "bar/", "bar/file"])
        self.assertEqual('contents of foo\n',
            tree.get_file(tree.path2id('foo')).read())
        self.assertEqual('contents of bar/file\n',
            tree.get_file(tree.path2id('bar/file')).read())
        builder.finish_tree()


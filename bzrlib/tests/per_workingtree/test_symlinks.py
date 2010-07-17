# Copyright (C) 2010 Canonical Ltd
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

"""Test symlink support.
"""

import os

from bzrlib import (
    builtins,
    tests,
    workingtree,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestSmartAddTree(TestCaseWithWorkingTree):

    # See eg <https://bugs.launchpad.net/bzr/+bug/192859>

    _test_needs_features = [tests.SymlinkFeature]

    def test_smart_add_symlink(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/link@', 'target'),
            ])
        tree.smart_add(['tree/link'])
        self.assertIsNot(None, tree.path2id('link'))
        self.assertIs(None, tree.path2id('target'))
        self.assertEqual('symlink',
            tree.kind(tree.path2id('link')))

    def test_smart_add_symlink_pointing_outside(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/link@', '../../../../target'),
            ])
        tree.smart_add(['tree/link'])
        self.assertIsNot(None, tree.path2id('link'))
        self.assertIs(None, tree.path2id('target'))
        self.assertEqual('symlink',
            tree.kind(tree.path2id('link')))


class TestKindChanges(TestCaseWithWorkingTree):

    def test_symlink_to_dir(self):
        # <https://bugs.launchpad.net/bzr/+bug/192859>:
        # we had some past problems with the workingtree remembering for too
        # long what kind of object was at a particular name; we really
        # shouldn't do that.  Operating on the dirstate through passing
        # inventory deltas rather than mutating the inventory largely avoids
        # that.
        if self.workingtree_format.upgrade_recommended: 
            # File "bzrlib/workingtree.py", line 2341, in conflicts
            #   for conflicted in self._iter_conflicts():
            # File "bzrlib/workingtree.py", line 1590, in _iter_conflicts
            #   for info in self.list_files():
            # File "bzrlib/workingtree.py", line 1203, in list_files
            #   f_ie = inv.get_child(from_dir_id, f)
            # File "bzrlib/inventory.py", line 1269, in get_child
            #   return self[parent_id].children.get(filename)
            # AttributeError: children
            raise tests.TestSkipped("known broken on pre-dirstate formats; wontfix")
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/a@', 'target')])
        tree.smart_add(['tree/a'])
        tree.commit('add symlink')
        os.unlink('tree/a')
        self.build_tree_contents([
            ('tree/a/',),
            ('tree/a/f', 'content'),
            ])
        tree.smart_add(['tree/a/f'])
        tree.commit('change to dir')


class TestOpenTree(TestCaseWithWorkingTree):

    _test_needs_features = [tests.SymlinkFeature]

    def test_open_containing_through_symlink(self):
        self.make_test_tree()
        self.check_open_containing('link/content', 'tree', 'content')
        self.check_open_containing('link/sublink', 'tree', 'sublink')
        # this next one is a bit debatable, but arguably it's better that
        # open_containing is only concerned with opening the tree 
        # and then you can deal with symlinks along the way if you want
        self.check_open_containing('link/sublink/subcontent', 'tree',
            'sublink/subcontent')

    def check_open_containing(self, to_open, expected_tree_name,
        expected_relpath):
        wt, relpath = workingtree.WorkingTree.open_containing(to_open)
        self.assertEquals(relpath, expected_relpath)
        self.assertEndsWith(wt.basedir, expected_tree_name)

    def test_tree_files(self):
        # not strictly a WorkingTree method, but it should be
        # probably the root cause for
        # <https://bugs.launchpad.net/bzr/+bug/128562>
        self.make_test_tree()
        self.check_tree_files(['tree/outerlink'],
            'tree', ['outerlink'])
        self.check_tree_files(['link/outerlink'],
            'tree', ['outerlink'])
        self.check_tree_files(['link/sublink/subcontent'],
            'tree', ['subdir/subcontent'])

    def check_tree_files(self, to_open, expected_tree, expect_paths):
        tree, relpaths = builtins.tree_files(to_open)
        self.assertEndsWith(tree.basedir, expected_tree)
        self.assertEquals(expect_paths, relpaths)

    def make_test_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('link@', 'tree'),
            ('tree/outerlink@', '/not/there'),
            ('tree/content', 'hello'),
            ('tree/sublink@', 'subdir'),
            ('tree/subdir/',),
            ('tree/subdir/subcontent', 'subcontent stuff')
            ])

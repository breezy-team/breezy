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

See eg <https://bugs.launchpad.net/bzr/+bug/192859>
"""

from bzrlib import (
    tests,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestSmartAddTree(TestCaseWithWorkingTree):

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

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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for Tree.path2id('')"""

from breezy.tests import TestNotApplicable
from breezy.tests.per_tree import TestCaseWithTree

from breezy.workingtree import SettingFileIdUnsupported


class TestGetRootID(TestCaseWithTree):

    def make_tree_with_default_root_id(self):
        tree = self.make_branch_and_tree('tree')
        return self._convert_tree(tree)

    def make_tree_with_fixed_root_id(self):
        tree = self.make_branch_and_tree('tree')
        if not tree.supports_setting_file_ids():
            self.assertRaises(
                SettingFileIdUnsupported, tree.set_root_id,
                b'custom-tree-root-id')
            self.skipTest('tree format does not support setting tree id')
        tree.set_root_id(b'custom-tree-root-id')
        return self._convert_tree(tree)

    def test_get_root_id_default(self):
        tree = self.make_tree_with_default_root_id()
        if not tree.supports_file_ids:
            raise TestNotApplicable('file ids not supported')
        with tree.lock_read():
            self.assertIsNot(None, tree.path2id(''))

    def test_get_root_id_fixed(self):
        try:
            tree = self.make_tree_with_fixed_root_id()
        except SettingFileIdUnsupported:
            raise TestNotApplicable('file ids not supported')
        with tree.lock_read():
            self.assertEqual(b'custom-tree-root-id', tree.path2id(''))

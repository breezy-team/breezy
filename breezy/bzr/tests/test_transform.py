# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

from . import TestCaseWithTransport


class TestInventoryAltered(TestCaseWithTransport):

    def test_inventory_altered_unchanged(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', b'foo-id')
        with tree.preview_transform() as tt:
            self.assertEqual([], tt._inventory_altered())

    def test_inventory_altered_changed_parent_id(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', b'foo-id')
        with tree.preview_transform() as tt:
            tt.unversion_file(tt.root)
            tt.version_file(b'new-id', tt.root)
            foo_trans_id = tt.trans_id_tree_path('foo')
            foo_tuple = ('foo', foo_trans_id)
            root_tuple = ('', tt.root)
            self.assertEqual([root_tuple, foo_tuple], tt._inventory_altered())

    def test_inventory_altered_noop_changed_parent_id(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', b'foo-id')
        with tree.preview_transform() as tt:
            tt.unversion_file(tt.root)
            tt.version_file(tree.path2id(''), tt.root)
            tt.trans_id_tree_path('foo')
            self.assertEqual([], tt._inventory_altered())

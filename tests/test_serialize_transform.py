# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os

from bzrlib import transform
from bzrlib.plugins.shelf2.serialize_transform import (serialize, deserialize)
from bzrlib import tests


class TestSerializeTransform(tests.TestCaseWithTransport):

    def get_two_previews(self, tree):
        tt = transform.TransformPreview(tree)
        self.addCleanup(tt.finalize)
        tt2 = transform.TransformPreview(tree)
        self.addCleanup(tt2.finalize)
        return tt, tt2

    def test_roundtrip_creation(self):
        tree = self.make_branch_and_tree('.')
        tt, tt2 = self.get_two_previews(tree)
        tt.new_file(u'foo\u1234', tt.root, 'bar', 'baz', True)
        tt.new_directory('qux', tt.root, 'quxx')
        deserialize(tt2, serialize(tt))
        self.assertEqual(3, tt2._id_number)
        self.assertEqual({'new-1': u'foo\u1234',
                          'new-2': 'qux'}, tt2._new_name)
        self.assertEqual({'new-1': 'baz', 'new-2': 'quxx'}, tt2._new_id)
        self.assertEqual({'new-1': tt.root, 'new-2': tt.root}, tt2._new_parent)
        self.assertEqual({'baz': 'new-1', 'quxx': 'new-2'}, tt2._r_new_id)
        self.assertEqual({'new-1': True}, tt2._new_executability)
        self.assertEqual({'new-1': 'file',
                          'new-2': 'directory'}, tt2._new_contents)
        foo_limbo = open(tt2._limbo_name('new-1'), 'rb')
        try:
            foo_content = foo_limbo.read()
        finally:
            foo_limbo.close()
        self.assertEqual('bar', foo_content)

    def test_symlink_creation(self):
        self.requireFeature(tests.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        tt, tt2 = self.get_two_previews(tree)
        tt.new_symlink('foo', tt.root, 'bar')
        deserialize(tt2, serialize(tt))
        foo_content = os.readlink(tt2._limbo_name('new-1'))
        self.assertEqual('bar', foo_content)

    def test_roundtrip_destruction(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree([u'foo\u1234', 'bar'])
        tree.add([u'foo\u1234', 'bar'], ['foo-id', 'bar-id'])
        tt, tt2 = self.get_two_previews(tree)
        foo_trans_id = tt.trans_id_tree_file_id('foo-id')
        tt.unversion_file(foo_trans_id)
        bar_trans_id = tt.trans_id_tree_file_id('bar-id')
        tt.delete_contents(bar_trans_id)
        deserialize(tt2, serialize(tt))
        self.assertEqual({u'foo\u1234': foo_trans_id,
                          'bar': bar_trans_id,
                          '': tt.root}, tt2._tree_path_ids)
        self.assertEqual({foo_trans_id: u'foo\u1234',
                          bar_trans_id: 'bar',
                          tt.root: ''}, tt2._tree_id_paths)
        self.assertEqual(set([foo_trans_id]), tt2._removed_id)
        self.assertEqual(set([bar_trans_id]), tt2._removed_contents)

    def test_roundtrip_missing(self):
        tree = self.make_branch_and_tree('.')
        tt, tt2 = self.get_two_previews(tree)
        boo_trans_id = tt.trans_id_file_id('boo')
        deserialize(tt2, serialize(tt))
        self.assertEqual({'boo': boo_trans_id}, tt2._non_present_ids)

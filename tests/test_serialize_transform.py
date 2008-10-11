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

from bzrlib import pack, transform
from bzrlib.plugins.shelf2.serialize_transform import (
    get_parents_lines,
    get_parents_texts,
    deserialize,
    serialize,
)
from bzrlib import tests


class TestSerializeTransform(tests.TestCaseWithTransport):

    def get_two_previews(self, tree):
        tt = transform.TransformPreview(tree)
        self.addCleanup(tt.finalize)
        tt2 = transform.TransformPreview(tree)
        self.addCleanup(tt2.finalize)
        return tt, tt2

    @staticmethod
    def reserialize(tt, tt2):
        serializer = pack.ContainerSerialiser()
        parser = pack.ContainerPushParser()
        parser.accept_bytes(serializer.begin())
        for bytes in serialize(tt, serializer):
            parser.accept_bytes(bytes)
        parser.accept_bytes(serializer.end())
        deserialize(tt2, iter(parser.read_pending_records()))

    def test_roundtrip_creation(self):
        tree = self.make_branch_and_tree('.')
        tt, tt2 = self.get_two_previews(tree)
        tt.new_file(u'foo\u1234', tt.root, 'bar', 'baz', True)
        tt.new_directory('qux', tt.root, 'quxx')
        self.reserialize(tt, tt2)
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
        self.reserialize(tt, tt2)
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
        self.reserialize(tt, tt2)
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
        self.reserialize(tt, tt2)
        self.assertEqual({'boo': boo_trans_id}, tt2._non_present_ids)

    def test_roundtrip_modification(self):
        LINES_ONE = 'aa\nbb\ncc\ndd\n'
        LINES_TWO = 'z\nbb\nx\ndd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', LINES_ONE)])
        tree.add('file', 'file-id')
        tt, tt2 = self.get_two_previews(tree)
        trans_id = tt.trans_id_file_id('file-id')
        tt.delete_contents(trans_id)
        tt.create_file(LINES_TWO, trans_id)
        self.reserialize(tt, tt2)
        self.assertFileEqual(LINES_TWO, tt2._limbo_name(trans_id))

    def test_roundtrip_kind_change(self):
        LINES_ONE = 'a\nb\nc\nd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo/'])
        tree.add('foo', 'foo-id')
        tt, tt2 = self.get_two_previews(tree)
        trans_id = tt.trans_id_file_id('foo-id')
        tt.delete_contents(trans_id)
        tt.create_file(LINES_ONE, trans_id)
        self.reserialize(tt, tt2)
        self.assertFileEqual(LINES_ONE, tt2._limbo_name(trans_id))

    def test_roundtrip_add_contents(self):
        LINES_ONE = 'a\nb\nc\nd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo')
        os.unlink('tree/foo')
        tt, tt2 = self.get_two_previews(tree)
        trans_id = tt.trans_id_tree_path('foo')
        tt.create_file(LINES_ONE, trans_id)
        self.reserialize(tt, tt2)
        self.assertFileEqual(LINES_ONE, tt2._limbo_name(trans_id))

    def test_get_parents_lines(self):
        LINES_ONE = 'aa\nbb\ncc\ndd\n'
        LINES_TWO = 'z\nbb\nx\ndd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', LINES_ONE)])
        tree.add('file', 'file-id')
        tt, tt2 = self.get_two_previews(tree)
        trans_id = tt.trans_id_tree_path('file')
        self.assertEqual((['aa\n', 'bb\n', 'cc\n', 'dd\n'],),
            get_parents_lines(tt, trans_id))

    def test_get_parents_texts(self):
        LINES_ONE = 'aa\nbb\ncc\ndd\n'
        LINES_TWO = 'z\nbb\nx\ndd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', LINES_ONE)])
        tree.add('file', 'file-id')
        tt, tt2 = self.get_two_previews(tree)
        trans_id = tt.trans_id_tree_path('file')
        self.assertEqual((LINES_ONE,),
            get_parents_texts(tt, trans_id))

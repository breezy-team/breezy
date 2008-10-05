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


from bzrlib import transform
from bzrlib.plugins.shelf2.serialize_transform import (serialize, deserialize)
from bzrlib.tests import TestCaseWithTransport


class TestSerializeTransform(TestCaseWithTransport):

    def test_roundtrip(self):
        tree = self.make_branch_and_tree('.')
        tt = transform.TransformPreview(tree)
        self.addCleanup(tt.finalize)
        tt.new_file(u'foo\u1234', tt.root, 'bar', 'baz', True)
        output = serialize(tt)
        tt2 = transform.TransformPreview(tree)
        deserialize(tt2, output)
        self.assertEqual(2, tt2._id_number)
        self.assertEqual({'new-1': u'foo\u1234'}, tt2._new_name)
        self.assertEqual({'new-1': 'baz'}, tt2._new_id)
        self.assertEqual({'baz': 'new-1'}, tt2._r_new_id)

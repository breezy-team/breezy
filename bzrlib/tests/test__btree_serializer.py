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
#

"""Direct tests of the btree serializer extension"""

from bzrlib import tests

from bzrlib.tests.test_btree_index import compiled_btreeparser_feature


class TestGCCKHSHA1LeafNode(tests.TestCase):

    _test_needs_features = [compiled_btreeparser_feature]

    def setUp(self):
        super(TestGCCKHSHA1LeafNode, self).setUp()
        self.module = compiled_btreeparser_feature.module

    def assertInvalid(self, bytes):
        """Ensure that we get a proper error when trying to parse invalid bytes.

        (mostly this is testing that bad input doesn't cause us to segfault)
        """
        self.assertRaises((ValueError, TypeError), 
                          self.module._parse_into_chk, bytes, 1, 0)

    def test_non_str(self):
        self.assertInvalid(u'type=leaf\n')

    def test_not_leaf(self):
        self.assertInvalid('type=internal\n')

    def test_empty_leaf(self):
        leaf = self.module._parse_into_chk('type=leaf\n', 1, 0)
        self.assertEqual(0, len(leaf))
        self.assertEqual([], leaf.all_items())
        self.assertEqual([], leaf.all_keys())

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

import binascii

from bzrlib import tests

from bzrlib.tests.test_btree_index import compiled_btreeparser_feature


class TestBtreeSerializer(tests.TestCase):

    _test_needs_features = [compiled_btreeparser_feature]

    def setUp(self):
        super(TestBtreeSerializer, self).setUp()
        self.module = compiled_btreeparser_feature.module

class TestHexAndUnhex(TestBtreeSerializer):

    def assertHexlify(self, as_binary):
        self.assertEqual(binascii.hexlify(as_binary),
                         self.module._test_hexlify(as_binary))

    def assertUnhexlify(self, as_hex):
        ba_unhex = binascii.unhexlify(as_hex)
        mod_unhex = self.module._test_unhexlify(as_hex)
        if ba_unhex != mod_unhex:
            if mod_unhex is None:
                mod_hex = '<None>'
            else:
                mod_hex = binascii.hexlify(mod_unhex)
            self.fail('_test_unhexlify returned a different answer'
                      ' from binascii:\n    %s\n != %s'
                      % (binascii.hexlify(ba_unhex), mod_hex))

    def assertFailUnhexlify(self, as_hex):
        # Invalid hex content
        self.assertIs(None, self.module._test_unhexlify(as_hex))

    def test_to_hex(self):
        raw_bytes = ''.join(map(chr, range(256)))
        for i in range(0, 240, 20):
            self.assertHexlify(raw_bytes[i:i+20])
        self.assertHexlify(raw_bytes[240:]+raw_bytes[0:4])

    def test_from_hex(self):
        self.assertUnhexlify('0123456789abcdef0123456789abcdef01234567')
        self.assertUnhexlify('123456789abcdef0123456789abcdef012345678')
        self.assertUnhexlify('0123456789ABCDEF0123456789ABCDEF01234567')
        self.assertUnhexlify('123456789ABCDEF0123456789ABCDEF012345678')
        hex_chars = binascii.hexlify(''.join(map(chr, range(256))))
        for i in range(0, 480, 40):
            self.assertUnhexlify(hex_chars[i:i+40])
        self.assertUnhexlify(hex_chars[480:]+hex_chars[0:8])

    def test_from_invalid_hex(self):
        self.assertFailUnhexlify('123456789012345678901234567890123456789X')
        self.assertFailUnhexlify('12345678901234567890123456789012345678X9')


class TestGCCKHSHA1LeafNode(TestBtreeSerializer):


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

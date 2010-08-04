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


_hex_form = '123456789012345678901234567890abcdefabcd'

class Test_KeyToSha1(TestBtreeSerializer):

    def assertKeyToSha1(self, expected, key):
        if expected is None:
            expected_bin = None
        else:
            expected_bin = binascii.unhexlify(expected)
        actual_sha1 = self.module._test_key_to_sha1(key)
        if expected_bin != actual_sha1:
            actual_hex_sha1 = None
            if actual_sha1 is not None:
                actual_hex_sha1 = binascii.hexlify(actual_sha1)
            self.fail('_key_to_sha1 returned:\n    %s\n != %s'
                      % (actual_sha1, expected))

    def test_simple(self):
        self.assertKeyToSha1(_hex_form, ('sha1:' + _hex_form,))

    def test_invalid_not_tuple(self):
        self.assertKeyToSha1(None, _hex_form)
        self.assertKeyToSha1(None, 'sha1:' + _hex_form)

    def test_invalid_empty(self):
        self.assertKeyToSha1(None, ())

    def test_invalid_not_string(self):
        self.assertKeyToSha1(None, (None,))
        self.assertKeyToSha1(None, (list(_hex_form),))

    def test_invalid_not_sha1(self):
        self.assertKeyToSha1(None, (_hex_form,))
        self.assertKeyToSha1(None, ('sha2:' + _hex_form,))

    def test_invalid_not_hex(self):
        self.assertKeyToSha1(None,
            ('sha1:abcdefghijklmnopqrstuvwxyz12345678901234',))


class Test_Sha1ToKey(TestBtreeSerializer):

    def assertSha1ToKey(self, hex_sha1):
        bin_sha1 = binascii.unhexlify(hex_sha1)
        key = self.module._test_sha1_to_key(bin_sha1)
        self.assertEqual(('sha1:' + hex_sha1,), key)

    def test_simple(self):
        self.assertSha1ToKey(_hex_form)


_one_key_content = """type=leaf
sha1:123456789012345678901234567890abcdefabcd\x00\x001 2 3 4
"""

_large_offsets = """type=leaf
sha1:123456789012345678901234567890abcdefabcd\x00\x0012345678901 1234567890 0 1
sha1:abcd123456789012345678901234567890abcdef\x00\x002147483648 2147483647 0 1
sha1:abcdefabcd123456789012345678901234567890\x00\x004294967296 4294967295 4294967294 1
"""

_multi_key_content = """type=leaf
sha1:70c881d4a26984ddce795f6f71817c9cf4480e79\x00\x000 0 0 0
sha1:7e240de74fb1ed08fa08d38063f6a6a91462a815\x00\x001 1 1 1
sha1:86f7e437faa5a7fce15d1ddcb9eaeaea377667b8\x00\x002 2 2 2
sha1:da39a3ee5e6b4b0d3255bfef95601890afd80709\x00\x003 3 3 3
sha1:df51e37c269aa94d38f93e537bf6e2020b21406c\x00\x004 4 4 4
sha1:e0c9035898dd52fc65c41454cec9c4d2611bfb37\x00\x005 5 5 5
sha1:e93b4e3c464ffd51732fbd6ded717e9efda28aad\x00\x006 6 6 6
sha1:f7a9e24777ec23212c54d7a350bc5bea5477fdbb\x00\x007 7 7 7
"""

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
        # It should allow any key to be queried
        self.assertFalse(('key',) in leaf)

    def test_one_key_leaf(self):
        leaf = self.module._parse_into_chk(_one_key_content, 1, 0)
        self.assertEqual(1, len(leaf))
        sha_key = ('sha1:' + _hex_form,)
        self.assertEqual([sha_key], leaf.all_keys())
        self.assertEqual([(sha_key, ('1 2 3 4', ()))], leaf.all_items())
        self.assertTrue(sha_key in leaf)

    def test_large_offsets(self):
        leaf = self.module._parse_into_chk(_large_offsets, 1, 0)
        self.assertEqual(['12345678901 1234567890 0 1',
                          '2147483648 2147483647 0 1',
                          '4294967296 4294967295 4294967294 1',
                         ], [x[1][0] for x in leaf.all_items()])

    def test_many_key_leaf(self):
        leaf = self.module._parse_into_chk(_multi_key_content, 1, 0)
        self.assertEqual(8, len(leaf))
        all_keys = leaf.all_keys()
        self.assertEqual(8, len(leaf.all_keys()))
        for idx, key in enumerate(all_keys):
            self.assertEqual(str(idx), leaf[key][0].split()[0])

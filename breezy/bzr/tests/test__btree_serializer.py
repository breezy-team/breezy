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
import bisect

from ... import tests

from .test_btree_index import compiled_btreeparser_feature


class TestBtreeSerializer(tests.TestCase):

    _test_needs_features = [compiled_btreeparser_feature]

    @property
    def module(self):
        return compiled_btreeparser_feature.module


class TestHexAndUnhex(TestBtreeSerializer):

    def assertHexlify(self, as_binary):
        self.assertEqual(binascii.hexlify(as_binary),
                         self.module._py_hexlify(as_binary))

    def assertUnhexlify(self, as_hex):
        ba_unhex = binascii.unhexlify(as_hex)
        mod_unhex = self.module._py_unhexlify(as_hex)
        if ba_unhex != mod_unhex:
            if mod_unhex is None:
                mod_hex = b'<None>'
            else:
                mod_hex = binascii.hexlify(mod_unhex)
            self.fail('_py_unhexlify returned a different answer'
                      ' from binascii:\n    %r\n != %r'
                      % (binascii.hexlify(ba_unhex), mod_hex))

    def assertFailUnhexlify(self, as_hex):
        # Invalid hex content
        self.assertIs(None, self.module._py_unhexlify(as_hex))

    def test_to_hex(self):
        raw_bytes = bytes(range(256))
        for i in range(0, 240, 20):
            self.assertHexlify(raw_bytes[i:i + 20])
        self.assertHexlify(raw_bytes[240:] + raw_bytes[0:4])

    def test_from_hex(self):
        self.assertUnhexlify(b'0123456789abcdef0123456789abcdef01234567')
        self.assertUnhexlify(b'123456789abcdef0123456789abcdef012345678')
        self.assertUnhexlify(b'0123456789ABCDEF0123456789ABCDEF01234567')
        self.assertUnhexlify(b'123456789ABCDEF0123456789ABCDEF012345678')
        hex_chars = binascii.hexlify(bytes(range(256)))
        for i in range(0, 480, 40):
            self.assertUnhexlify(hex_chars[i:i + 40])
        self.assertUnhexlify(hex_chars[480:] + hex_chars[0:8])

    def test_from_invalid_hex(self):
        self.assertFailUnhexlify(b'123456789012345678901234567890123456789X')
        self.assertFailUnhexlify(b'12345678901234567890123456789012345678X9')

    def test_bad_argument(self):
        self.assertRaises(ValueError, self.module._py_unhexlify, u'1a')
        self.assertRaises(ValueError, self.module._py_unhexlify, b'1b')


_hex_form = b'123456789012345678901234567890abcdefabcd'


class Test_KeyToSha1(TestBtreeSerializer):

    def assertKeyToSha1(self, expected, key):
        if expected is None:
            expected_bin = None
        else:
            expected_bin = binascii.unhexlify(expected)
        actual_sha1 = self.module._py_key_to_sha1(key)
        if expected_bin != actual_sha1:
            actual_hex_sha1 = None
            if actual_sha1 is not None:
                actual_hex_sha1 = binascii.hexlify(actual_sha1)
            self.fail('_key_to_sha1 returned:\n    %s\n != %s'
                      % (actual_sha1, expected))

    def test_simple(self):
        self.assertKeyToSha1(_hex_form, (b'sha1:' + _hex_form,))

    def test_invalid_not_tuple(self):
        self.assertKeyToSha1(None, _hex_form)
        self.assertKeyToSha1(None, b'sha1:' + _hex_form)

    def test_invalid_empty(self):
        self.assertKeyToSha1(None, ())

    def test_invalid_not_string(self):
        self.assertKeyToSha1(None, (None,))
        self.assertKeyToSha1(None, (list(_hex_form),))

    def test_invalid_not_sha1(self):
        self.assertKeyToSha1(None, (_hex_form,))
        self.assertKeyToSha1(None, (b'sha2:' + _hex_form,))

    def test_invalid_not_hex(self):
        self.assertKeyToSha1(None,
                             (b'sha1:abcdefghijklmnopqrstuvwxyz12345678901234',))


class Test_Sha1ToKey(TestBtreeSerializer):

    def assertSha1ToKey(self, hex_sha1):
        bin_sha1 = binascii.unhexlify(hex_sha1)
        key = self.module._py_sha1_to_key(bin_sha1)
        self.assertEqual((b'sha1:' + hex_sha1,), key)

    def test_simple(self):
        self.assertSha1ToKey(_hex_form)


_one_key_content = b"""type=leaf
sha1:123456789012345678901234567890abcdefabcd\x00\x001 2 3 4
"""

_large_offsets = b"""type=leaf
sha1:123456789012345678901234567890abcdefabcd\x00\x0012345678901 1234567890 0 1
sha1:abcd123456789012345678901234567890abcdef\x00\x002147483648 2147483647 0 1
sha1:abcdefabcd123456789012345678901234567890\x00\x004294967296 4294967295 4294967294 1
"""

_multi_key_content = b"""type=leaf
sha1:c80c881d4a26984ddce795f6f71817c9cf4480e7\x00\x000 0 0 0
sha1:c86f7e437faa5a7fce15d1ddcb9eaeaea377667b\x00\x001 1 1 1
sha1:c8e240de74fb1ed08fa08d38063f6a6a91462a81\x00\x002 2 2 2
sha1:cda39a3ee5e6b4b0d3255bfef95601890afd8070\x00\x003 3 3 3
sha1:cdf51e37c269aa94d38f93e537bf6e2020b21406\x00\x004 4 4 4
sha1:ce0c9035898dd52fc65c41454cec9c4d2611bfb3\x00\x005 5 5 5
sha1:ce93b4e3c464ffd51732fbd6ded717e9efda28aa\x00\x006 6 6 6
sha1:cf7a9e24777ec23212c54d7a350bc5bea5477fdb\x00\x007 7 7 7
"""

_multi_key_same_offset = b"""type=leaf
sha1:080c881d4a26984ddce795f6f71817c9cf4480e7\x00\x000 0 0 0
sha1:c86f7e437faa5a7fce15d1ddcb9eaeaea377667b\x00\x001 1 1 1
sha1:cd0c9035898dd52fc65c41454cec9c4d2611bfb3\x00\x002 2 2 2
sha1:cda39a3ee5e6b4b0d3255bfef95601890afd8070\x00\x003 3 3 3
sha1:cde240de74fb1ed08fa08d38063f6a6a91462a81\x00\x004 4 4 4
sha1:cdf51e37c269aa94d38f93e537bf6e2020b21406\x00\x005 5 5 5
sha1:ce7a9e24777ec23212c54d7a350bc5bea5477fdb\x00\x006 6 6 6
sha1:ce93b4e3c464ffd51732fbd6ded717e9efda28aa\x00\x007 7 7 7
"""

_common_32_bits = b"""type=leaf
sha1:123456784a26984ddce795f6f71817c9cf4480e7\x00\x000 0 0 0
sha1:1234567874fb1ed08fa08d38063f6a6a91462a81\x00\x001 1 1 1
sha1:12345678777ec23212c54d7a350bc5bea5477fdb\x00\x002 2 2 2
sha1:123456787faa5a7fce15d1ddcb9eaeaea377667b\x00\x003 3 3 3
sha1:12345678898dd52fc65c41454cec9c4d2611bfb3\x00\x004 4 4 4
sha1:12345678c269aa94d38f93e537bf6e2020b21406\x00\x005 5 5 5
sha1:12345678c464ffd51732fbd6ded717e9efda28aa\x00\x006 6 6 6
sha1:12345678e5e6b4b0d3255bfef95601890afd8070\x00\x007 7 7 7
"""


class TestGCCKHSHA1LeafNode(TestBtreeSerializer):

    def assertInvalid(self, data):
        """Ensure that we get a proper error when trying to parse invalid bytes.

        (mostly this is testing that bad input doesn't cause us to segfault)
        """
        self.assertRaises(
            (ValueError, TypeError), self.module._parse_into_chk, data, 1, 0)

    def test_non_bytes(self):
        self.assertInvalid(u'type=leaf\n')

    def test_not_leaf(self):
        self.assertInvalid(b'type=internal\n')

    def test_empty_leaf(self):
        leaf = self.module._parse_into_chk(b'type=leaf\n', 1, 0)
        self.assertEqual(0, len(leaf))
        self.assertEqual([], leaf.all_items())
        self.assertEqual([], leaf.all_keys())
        # It should allow any key to be queried
        self.assertFalse(('key',) in leaf)

    def test_one_key_leaf(self):
        leaf = self.module._parse_into_chk(_one_key_content, 1, 0)
        self.assertEqual(1, len(leaf))
        sha_key = (b'sha1:' + _hex_form,)
        self.assertEqual([sha_key], leaf.all_keys())
        self.assertEqual([(sha_key, (b'1 2 3 4', ()))], leaf.all_items())
        self.assertTrue(sha_key in leaf)

    def test_large_offsets(self):
        leaf = self.module._parse_into_chk(_large_offsets, 1, 0)
        self.assertEqual([b'12345678901 1234567890 0 1',
                          b'2147483648 2147483647 0 1',
                          b'4294967296 4294967295 4294967294 1',
                          ], [x[1][0] for x in leaf.all_items()])

    def test_many_key_leaf(self):
        leaf = self.module._parse_into_chk(_multi_key_content, 1, 0)
        self.assertEqual(8, len(leaf))
        all_keys = leaf.all_keys()
        self.assertEqual(8, len(leaf.all_keys()))
        for idx, key in enumerate(all_keys):
            self.assertEqual(b'%d' % idx, leaf[key][0].split()[0])

    def test_common_shift(self):
        # The keys were deliberately chosen so that the first 5 bits all
        # overlapped, it also happens that a later bit overlaps
        # Note that by 'overlap' we mean that given bit is either on in all
        # keys, or off in all keys
        leaf = self.module._parse_into_chk(_multi_key_content, 1, 0)
        self.assertEqual(19, leaf.common_shift)
        # The interesting byte for each key is
        # (defined as the 8-bits that come after the common prefix)
        lst = [1, 13, 28, 180, 190, 193, 210, 239]
        offsets = leaf._get_offsets()
        self.assertEqual([bisect.bisect_left(lst, x) for x in range(0, 257)],
                         offsets)
        for idx, val in enumerate(lst):
            self.assertEqual(idx, offsets[val])
        for idx, key in enumerate(leaf.all_keys()):
            self.assertEqual(b'%d' % idx, leaf[key][0].split()[0])

    def test_multi_key_same_offset(self):
        # there is no common prefix, though there are some common bits
        leaf = self.module._parse_into_chk(_multi_key_same_offset, 1, 0)
        self.assertEqual(24, leaf.common_shift)
        offsets = leaf._get_offsets()
        # The interesting byte is just the first 8-bits of the key
        lst = [8, 200, 205, 205, 205, 205, 206, 206]
        self.assertEqual([bisect.bisect_left(lst, x) for x in range(0, 257)],
                         offsets)
        for val in lst:
            self.assertEqual(lst.index(val), offsets[val])
        for idx, key in enumerate(leaf.all_keys()):
            self.assertEqual(b'%d' % idx, leaf[key][0].split()[0])

    def test_all_common_prefix(self):
        # The first 32 bits of all hashes are the same. This is going to be
        # pretty much impossible, but I don't want to fail because of this
        leaf = self.module._parse_into_chk(_common_32_bits, 1, 0)
        self.assertEqual(0, leaf.common_shift)
        lst = [0x78] * 8
        offsets = leaf._get_offsets()
        self.assertEqual([bisect.bisect_left(lst, x) for x in range(0, 257)],
                         offsets)
        for val in lst:
            self.assertEqual(lst.index(val), offsets[val])
        for idx, key in enumerate(leaf.all_keys()):
            self.assertEqual(b'%d' % idx, leaf[key][0].split()[0])

    def test_many_entries(self):
        # Again, this is almost impossible, but we should still work
        # It would be hard to fit more that 120 entries in a 4k page, much less
        # more than 256 of them. but hey, weird stuff happens sometimes
        lines = [b'type=leaf\n']
        for i in range(500):
            key_str = b'sha1:%04x%s' % (i, _hex_form[:36])
            key = (key_str,)
            lines.append(b'%s\0\0%d %d %d %d\n' % (key_str, i, i, i, i))
        data = b''.join(lines)
        leaf = self.module._parse_into_chk(data, 1, 0)
        self.assertEqual(24 - 7, leaf.common_shift)
        offsets = leaf._get_offsets()
        # This is the interesting bits for each entry
        lst = [x // 2 for x in range(500)]
        expected_offsets = [x * 2 for x in range(128)] + [255] * 129
        self.assertEqual(expected_offsets, offsets)
        # We truncate because offsets is an unsigned char. So the bisection
        # will just say 'greater than the last one' for all the rest
        lst = lst[:255]
        self.assertEqual([bisect.bisect_left(lst, x) for x in range(0, 257)],
                         offsets)
        for val in lst:
            self.assertEqual(lst.index(val), offsets[val])
        for idx, key in enumerate(leaf.all_keys()):
            self.assertEqual(b'%d' % idx, leaf[key][0].split()[0])

    def test__sizeof__(self):
        # We can't use the exact numbers because of platform variations, etc.
        # But what we really care about is that it does get bigger with more
        # content.
        leaf0 = self.module._parse_into_chk(b'type=leaf\n', 1, 0)
        leaf1 = self.module._parse_into_chk(_one_key_content, 1, 0)
        leafN = self.module._parse_into_chk(_multi_key_content, 1, 0)
        sizeof_1 = leaf1.__sizeof__() - leaf0.__sizeof__()
        self.assertTrue(sizeof_1 > 0)
        sizeof_N = leafN.__sizeof__() - leaf0.__sizeof__()
        self.assertEqual(sizeof_1 * len(leafN), sizeof_N)

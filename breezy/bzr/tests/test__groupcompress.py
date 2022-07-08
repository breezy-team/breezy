# Copyright (C) 2008-2011 Canonical Ltd
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

"""Tests for the python and pyrex extensions of groupcompress"""

import sys

from ... import (
    tests,
    )
from .. import (
    _groupcompress_py,
    )
from ...tests.scenarios import (
    load_tests_apply_scenarios,
    )
from ...tests import (
    features,
    )


def module_scenarios():
    scenarios = [
        ('python', {'_gc_module': _groupcompress_py}),
        ]
    if compiled_groupcompress_feature.available():
        gc_module = compiled_groupcompress_feature.module
        scenarios.append(('C',
                          {'_gc_module': gc_module}))
    return scenarios


def two_way_scenarios():
    scenarios = [
        ('PP', {'make_delta': _groupcompress_py.make_delta,
                'apply_delta': _groupcompress_py.apply_delta})
        ]
    if compiled_groupcompress_feature.available():
        gc_module = compiled_groupcompress_feature.module
        scenarios.extend([
            ('CC', {'make_delta': gc_module.make_delta,
                    'apply_delta': gc_module.apply_delta}),
            ('PC', {'make_delta': _groupcompress_py.make_delta,
                    'apply_delta': gc_module.apply_delta}),
            ('CP', {'make_delta': gc_module.make_delta,
                    'apply_delta': _groupcompress_py.apply_delta}),
            ])
    return scenarios


load_tests = load_tests_apply_scenarios


compiled_groupcompress_feature = features.ModuleAvailableFeature(
    'breezy.bzr._groupcompress_pyx')

_text1 = b"""\
This is a bit
of source text
which is meant to be matched
against other text
"""

_text2 = b"""\
This is a bit
of source text
which is meant to differ from
against other text
"""

_text3 = b"""\
This is a bit
of source text
which is meant to be matched
against other text
except it also
has a lot more data
at the end of the file
"""

_first_text = b"""\
a bit of text, that
does not have much in
common with the next text
"""

_second_text = b"""\
some more bit of text, that
does not have much in
common with the previous text
and has some extra text
"""


_third_text = b"""\
a bit of text, that
has some in common with the previous text
and has some extra text
and not have much in
common with the next text
"""

_fourth_text = b"""\
123456789012345
same rabin hash
123456789012345
same rabin hash
123456789012345
same rabin hash
123456789012345
same rabin hash
"""


class TestMakeAndApplyDelta(tests.TestCase):

    scenarios = module_scenarios()
    _gc_module = None  # Set by load_tests

    def setUp(self):
        super(TestMakeAndApplyDelta, self).setUp()
        self.make_delta = self._gc_module.make_delta
        self.apply_delta = self._gc_module.apply_delta
        self.apply_delta_to_source = self._gc_module.apply_delta_to_source

    def test_make_delta_is_typesafe(self):
        self.make_delta(b'a string', b'another string')

        def _check_make_delta(string1, string2):
            self.assertRaises(TypeError, self.make_delta, string1, string2)

        _check_make_delta(b'a string', object())
        _check_make_delta(b'a string', u'not a string')
        _check_make_delta(object(), b'a string')
        _check_make_delta(u'not a string', b'a string')

    def test_make_noop_delta(self):
        ident_delta = self.make_delta(_text1, _text1)
        self.assertEqual(b'M\x90M', ident_delta)
        ident_delta = self.make_delta(_text2, _text2)
        self.assertEqual(b'N\x90N', ident_delta)
        ident_delta = self.make_delta(_text3, _text3)
        self.assertEqual(b'\x87\x01\x90\x87', ident_delta)

    def assertDeltaIn(self, delta1, delta2, delta):
        """Make sure that the delta bytes match one of the expectations."""
        # In general, the python delta matcher gives different results than the
        # pyrex delta matcher. Both should be valid deltas, though.
        if delta not in (delta1, delta2):
            self.fail(b"Delta bytes:\n"
                      b"       %r\n"
                      b"not in %r\n"
                      b"    or %r"
                      % (delta, delta1, delta2))

    def test_make_delta(self):
        delta = self.make_delta(_text1, _text2)
        self.assertDeltaIn(
            b'N\x90/\x1fdiffer from\nagainst other text\n',
            b'N\x90\x1d\x1ewhich is meant to differ from\n\x91:\x13',
            delta)
        delta = self.make_delta(_text2, _text1)
        self.assertDeltaIn(
            b'M\x90/\x1ebe matched\nagainst other text\n',
            b'M\x90\x1d\x1dwhich is meant to be matched\n\x91;\x13',
            delta)
        delta = self.make_delta(_text3, _text1)
        self.assertEqual(b'M\x90M', delta)
        delta = self.make_delta(_text3, _text2)
        self.assertDeltaIn(
            b'N\x90/\x1fdiffer from\nagainst other text\n',
            b'N\x90\x1d\x1ewhich is meant to differ from\n\x91:\x13',
            delta)

    def test_make_delta_with_large_copies(self):
        # We want to have a copy that is larger than 64kB, which forces us to
        # issue multiple copy instructions.
        big_text = _text3 * 1220
        delta = self.make_delta(big_text, big_text)
        self.assertDeltaIn(
            b'\xdc\x86\x0a'      # Encoding the length of the uncompressed text
            b'\x80'              # Copy 64kB, starting at byte 0
            b'\x84\x01'          # and another 64kB starting at 64kB
            b'\xb4\x02\x5c\x83',  # And the bit of tail.
            None,   # Both implementations should be identical
            delta)

    def test_apply_delta_is_typesafe(self):
        self.apply_delta(_text1, b'M\x90M')
        self.assertRaises(TypeError, self.apply_delta, object(), b'M\x90M')
        self.assertRaises(TypeError, self.apply_delta,
                          _text1.decode('latin1'), b'M\x90M')
        self.assertRaises(TypeError, self.apply_delta, _text1, u'M\x90M')
        self.assertRaises(TypeError, self.apply_delta, _text1, object())

    def test_apply_delta(self):
        target = self.apply_delta(_text1,
                                  b'N\x90/\x1fdiffer from\nagainst other text\n')
        self.assertEqual(_text2, target)
        target = self.apply_delta(_text2,
                                  b'M\x90/\x1ebe matched\nagainst other text\n')
        self.assertEqual(_text1, target)

    def test_apply_delta_to_source_is_safe(self):
        self.assertRaises(TypeError,
                          self.apply_delta_to_source, object(), 0, 1)
        self.assertRaises(TypeError,
                          self.apply_delta_to_source, u'unicode str', 0, 1)
        # end > length
        self.assertRaises(ValueError,
                          self.apply_delta_to_source, b'foo', 1, 4)
        # start > length
        self.assertRaises(ValueError,
                          self.apply_delta_to_source, b'foo', 5, 3)
        # start > end
        self.assertRaises(ValueError,
                          self.apply_delta_to_source, b'foo', 3, 2)

    def test_apply_delta_to_source(self):
        source_and_delta = (_text1
                            + b'N\x90/\x1fdiffer from\nagainst other text\n')
        self.assertEqual(_text2, self.apply_delta_to_source(source_and_delta,
                                                            len(_text1), len(source_and_delta)))


class TestMakeAndApplyCompatible(tests.TestCase):

    scenarios = two_way_scenarios()

    make_delta = None  # Set by load_tests
    apply_delta = None  # Set by load_tests

    def assertMakeAndApply(self, source, target):
        """Assert that generating a delta and applying gives success."""
        delta = self.make_delta(source, target)
        bytes = self.apply_delta(source, delta)
        self.assertEqualDiff(target, bytes)

    def test_direct(self):
        self.assertMakeAndApply(_text1, _text2)
        self.assertMakeAndApply(_text2, _text1)
        self.assertMakeAndApply(_text1, _text3)
        self.assertMakeAndApply(_text3, _text1)
        self.assertMakeAndApply(_text2, _text3)
        self.assertMakeAndApply(_text3, _text2)


class TestDeltaIndex(tests.TestCase):

    def setUp(self):
        super(TestDeltaIndex, self).setUp()
        # This test isn't multiplied, because we only have DeltaIndex for the
        # compiled form
        # We call this here, because _test_needs_features happens after setUp
        self.requireFeature(compiled_groupcompress_feature)
        self._gc_module = compiled_groupcompress_feature.module

    def test_repr(self):
        di = self._gc_module.DeltaIndex(b'test text\n')
        self.assertEqual('DeltaIndex(1, 10)', repr(di))

    def test_sizeof(self):
        di = self._gc_module.DeltaIndex()
        # Exact value will depend on platform but should include sources
        # source_info is a pointer and two longs so at least 12 bytes
        lower_bound = di._max_num_sources * 12
        self.assertGreater(sys.getsizeof(di), lower_bound)

    def test__dump_no_index(self):
        di = self._gc_module.DeltaIndex()
        self.assertEqual(None, di._dump_index())

    def test__dump_index_simple(self):
        di = self._gc_module.DeltaIndex()
        di.add_source(_text1, 0)
        self.assertFalse(di._has_index())
        self.assertEqual(None, di._dump_index())
        _ = di.make_delta(_text1)
        self.assertTrue(di._has_index())
        hash_list, entry_list = di._dump_index()
        self.assertEqual(16, len(hash_list))
        self.assertEqual(68, len(entry_list))
        just_entries = [(idx, text_offset, hash_val)
                        for idx, (text_offset, hash_val)
                        in enumerate(entry_list)
                        if text_offset != 0 or hash_val != 0]
        rabin_hash = self._gc_module._rabin_hash
        self.assertEqual([(8, 16, rabin_hash(_text1[1:17])),
                          (25, 48, rabin_hash(_text1[33:49])),
                          (34, 32, rabin_hash(_text1[17:33])),
                          (47, 64, rabin_hash(_text1[49:65])),
                          ], just_entries)
        # This ensures that the hash map points to the location we expect it to
        for entry_idx, text_offset, hash_val in just_entries:
            self.assertEqual(entry_idx, hash_list[hash_val & 0xf])

    def test__dump_index_two_sources(self):
        di = self._gc_module.DeltaIndex()
        di.add_source(_text1, 0)
        di.add_source(_text2, 2)
        start2 = len(_text1) + 2
        self.assertTrue(di._has_index())
        hash_list, entry_list = di._dump_index()
        self.assertEqual(16, len(hash_list))
        self.assertEqual(68, len(entry_list))
        just_entries = [(idx, text_offset, hash_val)
                        for idx, (text_offset, hash_val)
                        in enumerate(entry_list)
                        if text_offset != 0 or hash_val != 0]
        rabin_hash = self._gc_module._rabin_hash
        self.assertEqual([(8, 16, rabin_hash(_text1[1:17])),
                          (9, start2 + 16, rabin_hash(_text2[1:17])),
                          (25, 48, rabin_hash(_text1[33:49])),
                          (30, start2 + 64, rabin_hash(_text2[49:65])),
                          (34, 32, rabin_hash(_text1[17:33])),
                          (35, start2 + 32, rabin_hash(_text2[17:33])),
                          (43, start2 + 48, rabin_hash(_text2[33:49])),
                          (47, 64, rabin_hash(_text1[49:65])),
                          ], just_entries)
        # Each entry should be in the appropriate hash bucket.
        for entry_idx, text_offset, hash_val in just_entries:
            hash_idx = hash_val & 0xf
            self.assertTrue(
                hash_list[hash_idx] <= entry_idx < hash_list[hash_idx + 1])

    def test_first_add_source_doesnt_index_until_make_delta(self):
        di = self._gc_module.DeltaIndex()
        self.assertFalse(di._has_index())
        di.add_source(_text1, 0)
        self.assertFalse(di._has_index())
        # However, asking to make a delta will trigger the index to be
        # generated, and will generate a proper delta
        delta = di.make_delta(_text2)
        self.assertTrue(di._has_index())
        self.assertEqual(b'N\x90/\x1fdiffer from\nagainst other text\n', delta)

    def test_add_source_max_bytes_to_index(self):
        di = self._gc_module.DeltaIndex()
        di._max_bytes_to_index = 3 * 16
        di.add_source(_text1, 0)  # (77 bytes -1) // 3 = 25 byte stride
        di.add_source(_text3, 3)  # (135 bytes -1) // 3 = 44 byte stride
        start2 = len(_text1) + 3
        hash_list, entry_list = di._dump_index()
        self.assertEqual(16, len(hash_list))
        self.assertEqual(67, len(entry_list))
        just_entries = sorted([(text_offset, hash_val)
                               for text_offset, hash_val in entry_list
                               if text_offset != 0 or hash_val != 0])
        rabin_hash = self._gc_module._rabin_hash
        self.assertEqual([(25, rabin_hash(_text1[10:26])),
                          (50, rabin_hash(_text1[35:51])),
                          (75, rabin_hash(_text1[60:76])),
                          (start2 + 44, rabin_hash(_text3[29:45])),
                          (start2 + 88, rabin_hash(_text3[73:89])),
                          (start2 + 132, rabin_hash(_text3[117:133])),
                          ], just_entries)

    def test_second_add_source_triggers_make_index(self):
        di = self._gc_module.DeltaIndex()
        self.assertFalse(di._has_index())
        di.add_source(_text1, 0)
        self.assertFalse(di._has_index())
        di.add_source(_text2, 0)
        self.assertTrue(di._has_index())

    def test_make_delta(self):
        di = self._gc_module.DeltaIndex(_text1)
        delta = di.make_delta(_text2)
        self.assertEqual(b'N\x90/\x1fdiffer from\nagainst other text\n', delta)

    def test_delta_against_multiple_sources(self):
        di = self._gc_module.DeltaIndex()
        di.add_source(_first_text, 0)
        self.assertEqual(len(_first_text), di._source_offset)
        di.add_source(_second_text, 0)
        self.assertEqual(len(_first_text) + len(_second_text),
                         di._source_offset)
        delta = di.make_delta(_third_text)
        result = self._gc_module.apply_delta(_first_text + _second_text, delta)
        self.assertEqualDiff(_third_text, result)
        self.assertEqual(b'\x85\x01\x90\x14\x0chas some in '
                         b'\x91v6\x03and\x91d"\x91:\n', delta)

    def test_delta_with_offsets(self):
        di = self._gc_module.DeltaIndex()
        di.add_source(_first_text, 5)
        self.assertEqual(len(_first_text) + 5, di._source_offset)
        di.add_source(_second_text, 10)
        self.assertEqual(len(_first_text) + len(_second_text) + 15,
                         di._source_offset)
        delta = di.make_delta(_third_text)
        self.assertIsNot(None, delta)
        result = self._gc_module.apply_delta(
            b'12345' + _first_text + b'1234567890' + _second_text, delta)
        self.assertIsNot(None, result)
        self.assertEqualDiff(_third_text, result)
        self.assertEqual(b'\x85\x01\x91\x05\x14\x0chas some in '
                         b'\x91\x856\x03and\x91s"\x91?\n', delta)

    def test_delta_with_delta_bytes(self):
        di = self._gc_module.DeltaIndex()
        source = _first_text
        di.add_source(_first_text, 0)
        self.assertEqual(len(_first_text), di._source_offset)
        delta = di.make_delta(_second_text)
        self.assertEqual(b'h\tsome more\x91\x019'
                         b'&previous text\nand has some extra text\n', delta)
        di.add_delta_source(delta, 0)
        source += delta
        self.assertEqual(len(_first_text) + len(delta), di._source_offset)
        second_delta = di.make_delta(_third_text)
        result = self._gc_module.apply_delta(source, second_delta)
        self.assertEqualDiff(_third_text, result)
        # We should be able to match against the
        # 'previous text\nand has some...'  that was part of the delta bytes
        # Note that we don't match the 'common with the', because it isn't long
        # enough to match in the original text, and those bytes are not present
        # in the delta for the second text.
        self.assertEqual(b'\x85\x01\x90\x14\x1chas some in common with the '
                         b'\x91S&\x03and\x91\x18,', second_delta)
        # Add this delta, and create a new delta for the same text. We should
        # find the remaining text, and only insert the short 'and' text.
        di.add_delta_source(second_delta, 0)
        source += second_delta
        third_delta = di.make_delta(_third_text)
        result = self._gc_module.apply_delta(source, third_delta)
        self.assertEqualDiff(_third_text, result)
        self.assertEqual(b'\x85\x01\x90\x14\x91\x7e\x1c'
                         b'\x91S&\x03and\x91\x18,', third_delta)
        # Now create a delta, which we know won't be able to be 'fit' into the
        # existing index
        fourth_delta = di.make_delta(_fourth_text)
        self.assertEqual(_fourth_text,
                         self._gc_module.apply_delta(source, fourth_delta))
        self.assertEqual(b'\x80\x01'
                         b'\x7f123456789012345\nsame rabin hash\n'
                         b'123456789012345\nsame rabin hash\n'
                         b'123456789012345\nsame rabin hash\n'
                         b'123456789012345\nsame rabin hash'
                         b'\x01\n', fourth_delta)
        di.add_delta_source(fourth_delta, 0)
        source += fourth_delta
        # With the next delta, everything should be found
        fifth_delta = di.make_delta(_fourth_text)
        self.assertEqual(_fourth_text,
                         self._gc_module.apply_delta(source, fifth_delta))
        self.assertEqual(b'\x80\x01\x91\xa7\x7f\x01\n', fifth_delta)


class TestCopyInstruction(tests.TestCase):

    def assertEncode(self, expected, offset, length):
        data = _groupcompress_py.encode_copy_instruction(offset, length)
        self.assertEqual(expected, data)

    def assertDecode(self, exp_offset, exp_length, exp_newpos, data, pos):
        cmd = data[pos]
        pos += 1
        out = _groupcompress_py.decode_copy_instruction(data, cmd, pos)
        self.assertEqual((exp_offset, exp_length, exp_newpos), out)

    def test_encode_no_length(self):
        self.assertEncode(b'\x80', 0, 64 * 1024)
        self.assertEncode(b'\x81\x01', 1, 64 * 1024)
        self.assertEncode(b'\x81\x0a', 10, 64 * 1024)
        self.assertEncode(b'\x81\xff', 255, 64 * 1024)
        self.assertEncode(b'\x82\x01', 256, 64 * 1024)
        self.assertEncode(b'\x83\x01\x01', 257, 64 * 1024)
        self.assertEncode(b'\x8F\xff\xff\xff\xff', 0xFFFFFFFF, 64 * 1024)
        self.assertEncode(b'\x8E\xff\xff\xff', 0xFFFFFF00, 64 * 1024)
        self.assertEncode(b'\x8D\xff\xff\xff', 0xFFFF00FF, 64 * 1024)
        self.assertEncode(b'\x8B\xff\xff\xff', 0xFF00FFFF, 64 * 1024)
        self.assertEncode(b'\x87\xff\xff\xff', 0x00FFFFFF, 64 * 1024)
        self.assertEncode(b'\x8F\x04\x03\x02\x01', 0x01020304, 64 * 1024)

    def test_encode_no_offset(self):
        self.assertEncode(b'\x90\x01', 0, 1)
        self.assertEncode(b'\x90\x0a', 0, 10)
        self.assertEncode(b'\x90\xff', 0, 255)
        self.assertEncode(b'\xA0\x01', 0, 256)
        self.assertEncode(b'\xB0\x01\x01', 0, 257)
        self.assertEncode(b'\xB0\xff\xff', 0, 0xFFFF)
        # Special case, if copy == 64KiB, then we store exactly 0
        # Note that this puns with a copy of exactly 0 bytes, but we don't care
        # about that, as we would never actually copy 0 bytes
        self.assertEncode(b'\x80', 0, 64 * 1024)

    def test_encode(self):
        self.assertEncode(b'\x91\x01\x01', 1, 1)
        self.assertEncode(b'\x91\x09\x0a', 9, 10)
        self.assertEncode(b'\x91\xfe\xff', 254, 255)
        self.assertEncode(b'\xA2\x02\x01', 512, 256)
        self.assertEncode(b'\xB3\x02\x01\x01\x01', 258, 257)
        self.assertEncode(b'\xB0\x01\x01', 0, 257)
        # Special case, if copy == 64KiB, then we store exactly 0
        # Note that this puns with a copy of exactly 0 bytes, but we don't care
        # about that, as we would never actually copy 0 bytes
        self.assertEncode(b'\x81\x0a', 10, 64 * 1024)

    def test_decode_no_length(self):
        # If length is 0, it is interpreted as 64KiB
        # The shortest possible instruction is a copy of 64KiB from offset 0
        self.assertDecode(0, 65536, 1, b'\x80', 0)
        self.assertDecode(1, 65536, 2, b'\x81\x01', 0)
        self.assertDecode(10, 65536, 2, b'\x81\x0a', 0)
        self.assertDecode(255, 65536, 2, b'\x81\xff', 0)
        self.assertDecode(256, 65536, 2, b'\x82\x01', 0)
        self.assertDecode(257, 65536, 3, b'\x83\x01\x01', 0)
        self.assertDecode(0xFFFFFFFF, 65536, 5, b'\x8F\xff\xff\xff\xff', 0)
        self.assertDecode(0xFFFFFF00, 65536, 4, b'\x8E\xff\xff\xff', 0)
        self.assertDecode(0xFFFF00FF, 65536, 4, b'\x8D\xff\xff\xff', 0)
        self.assertDecode(0xFF00FFFF, 65536, 4, b'\x8B\xff\xff\xff', 0)
        self.assertDecode(0x00FFFFFF, 65536, 4, b'\x87\xff\xff\xff', 0)
        self.assertDecode(0x01020304, 65536, 5, b'\x8F\x04\x03\x02\x01', 0)

    def test_decode_no_offset(self):
        self.assertDecode(0, 1, 2, b'\x90\x01', 0)
        self.assertDecode(0, 10, 2, b'\x90\x0a', 0)
        self.assertDecode(0, 255, 2, b'\x90\xff', 0)
        self.assertDecode(0, 256, 2, b'\xA0\x01', 0)
        self.assertDecode(0, 257, 3, b'\xB0\x01\x01', 0)
        self.assertDecode(0, 65535, 3, b'\xB0\xff\xff', 0)
        # Special case, if copy == 64KiB, then we store exactly 0
        # Note that this puns with a copy of exactly 0 bytes, but we don't care
        # about that, as we would never actually copy 0 bytes
        self.assertDecode(0, 65536, 1, b'\x80', 0)

    def test_decode(self):
        self.assertDecode(1, 1, 3, b'\x91\x01\x01', 0)
        self.assertDecode(9, 10, 3, b'\x91\x09\x0a', 0)
        self.assertDecode(254, 255, 3, b'\x91\xfe\xff', 0)
        self.assertDecode(512, 256, 3, b'\xA2\x02\x01', 0)
        self.assertDecode(258, 257, 5, b'\xB3\x02\x01\x01\x01', 0)
        self.assertDecode(0, 257, 3, b'\xB0\x01\x01', 0)

    def test_decode_not_start(self):
        self.assertDecode(1, 1, 6, b'abc\x91\x01\x01def', 3)
        self.assertDecode(9, 10, 5, b'ab\x91\x09\x0ade', 2)
        self.assertDecode(254, 255, 6, b'not\x91\xfe\xffcopy', 3)


class TestBase128Int(tests.TestCase):

    scenarios = module_scenarios()

    _gc_module = None  # Set by load_tests

    def assertEqualEncode(self, bytes, val):
        self.assertEqual(bytes, self._gc_module.encode_base128_int(val))

    def assertEqualDecode(self, val, num_decode, bytes):
        self.assertEqual((val, num_decode),
                         self._gc_module.decode_base128_int(bytes))

    def test_encode(self):
        self.assertEqualEncode(b'\x01', 1)
        self.assertEqualEncode(b'\x02', 2)
        self.assertEqualEncode(b'\x7f', 127)
        self.assertEqualEncode(b'\x80\x01', 128)
        self.assertEqualEncode(b'\xff\x01', 255)
        self.assertEqualEncode(b'\x80\x02', 256)
        self.assertEqualEncode(b'\xff\xff\xff\xff\x0f', 0xFFFFFFFF)

    def test_decode(self):
        self.assertEqualDecode(1, 1, b'\x01')
        self.assertEqualDecode(2, 1, b'\x02')
        self.assertEqualDecode(127, 1, b'\x7f')
        self.assertEqualDecode(128, 2, b'\x80\x01')
        self.assertEqualDecode(255, 2, b'\xff\x01')
        self.assertEqualDecode(256, 2, b'\x80\x02')
        self.assertEqualDecode(0xFFFFFFFF, 5, b'\xff\xff\xff\xff\x0f')

    def test_decode_with_trailing_bytes(self):
        self.assertEqualDecode(1, 1, b'\x01abcdef')
        self.assertEqualDecode(127, 1, b'\x7f\x01')
        self.assertEqualDecode(128, 2, b'\x80\x01abcdef')
        self.assertEqualDecode(255, 2, b'\xff\x01\xff')

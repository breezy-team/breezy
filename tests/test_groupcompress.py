# groupcompress, a bzr plugin providing new compression logic.
# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Tests for group compression."""

import zlib

from bzrlib import tests
from bzrlib.osutils import sha_string
from bzrlib.plugins.groupcompress import errors, groupcompress
from bzrlib.tests import (
    TestCaseWithTransport,
    TestScenarioApplier,
    adapt_tests,
    )
from bzrlib.transport import get_transport


def load_tests(standard_tests, module, loader):
    from bzrlib.tests.test_versionedfile import TestVersionedFiles
    vf_interface_tests = loader.loadTestsFromTestCase(TestVersionedFiles)
    cleanup_pack_group = groupcompress.cleanup_pack_group
    make_pack_factory = groupcompress.make_pack_factory
    group_scenario = ('groupcompressrabin-nograph', {
            'cleanup':cleanup_pack_group,
            'factory':make_pack_factory(False, False, 1),
            'graph': False,
            'key_length':1,
            'support_partial_insertion':False,
            }
        )
    applier = TestScenarioApplier()
    applier.scenarios = [group_scenario]
    adapt_tests(vf_interface_tests, applier, standard_tests)
    return standard_tests


class TestGroupCompressor(tests.TestCase):
    """Tests for GroupCompressor"""

    def test_empty_delta(self):
        compressor = groupcompress.GroupCompressor(True)
        self.assertEqual([], compressor.lines)

    def test_one_nosha_delta(self):
        # diff against NUKK
        compressor = groupcompress.GroupCompressor(True)
        sha1, end_point = compressor.compress(('label',),
            'strange\ncommon\n', None)
        self.assertEqual(sha_string('strange\ncommon\n'), sha1)
        expected_lines = [
            'fulltext\n',
            'label:label\nsha1:%s\n' % sha1,
            'len:15\n',
            'strange\ncommon\n',
            ]
        self.assertEqual(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def _chunks_to_repr_lines(self, chunks):
        return '\n'.join(map(repr, ''.join(chunks).split('\n')))

    def assertEqualDiffEncoded(self, expected, actual):
        """Compare the actual content to the expected content.

        :param expected: A group of chunks that we expect to see
        :param actual: The measured 'chunks'

        We will transform the chunks back into lines, and then run 'repr()'
        over them to handle non-ascii characters.
        """
        self.assertEqualDiff(self._chunks_to_repr_lines(expected),
                             self._chunks_to_repr_lines(actual))

    def test_two_nosha_delta(self):
        compressor = groupcompress.GroupCompressor(True)
        sha1_1, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.lines)
        sha1_2, end_point = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        self.assertEqual(sha_string('common long line\n'
                                    'that needs a 16 byte match\n'
                                    'different\n'), sha1_2)
        expected_lines.extend([
            'delta\n'
            'label:newlabel\n',
            'sha1:%s\n' % sha1_2,
            'len:16\n',
            # source and target length
            '\x7e\x36',
            # copy the line common
            '\x91\x52\x2c', #copy, offset 0x52, len 0x2c
            # add the line different, and the trailing newline
            '\x0adifferent\n', # insert 10 bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = groupcompress.GroupCompressor(True)
        sha1_1, end_point = compressor.compress(('label',),
            'strange\ncommon very very long line\nwith some extra text\n', None)
        sha1_2, _ = compressor.compress(('newlabel',),
            'different\nmoredifferent\nand then some more\n', None)
        expected_lines = list(compressor.lines)
        sha1_3, end_point = compressor.compress(('label3',),
            'new\ncommon very very long line\nwith some extra text\n'
            'different\nmoredifferent\nand then some more\n',
            None)
        self.assertEqual(
            sha_string('new\ncommon very very long line\nwith some extra text\n'
                       'different\nmoredifferent\nand then some more\n'),
            sha1_3)
        expected_lines.extend([
            'delta\n',
            'label:label3\n',
            'sha1:%s\n' % sha1_3,
            'len:13\n',
            '\xfa\x01\x5f' # source and target length
            # insert new
            '\x03new',
            # Copy of first parent 'common' range
            '\x91\x51\x31' # copy, offset 0x51, 0x31 bytes
            # Copy of second parent 'different' range
            '\x91\xcf\x2b' # copy, offset 0xcf, 0x2b bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_stats(self):
        compressor = groupcompress.GroupCompressor(True)
        compressor.compress(('label',), 'strange\ncommon\n', None)
        compressor.compress(('newlabel',),
                            'common\ndifferent\nmoredifferent\n', None)
        compressor.compress(('label3',),
                            'new\ncommon\ndifferent\nmoredifferent\n', None)
        self.assertAlmostEqual(0.3, compressor.ratio(), 1)

    def test_extract_from_compressor(self):
        # Knit fetching will try to reconstruct texts locally which results in
        # reading something that is in the compressor stream already.
        compressor = groupcompress.GroupCompressor(True)
        sha_1,  _ = compressor.compress(('label',), 'strange\ncommon\n', None)
        sha_2, _ = compressor.compress(('newlabel',),
            'common\ndifferent\nmoredifferent\n', None)
        # get the first out
        self.assertEqual((['strange\ncommon\n'], sha_1),
            compressor.extract(('label',)))
        # and the second
        self.assertEqual((['common\ndifferent\nmoredifferent\n'],
            sha_2), compressor.extract(('newlabel',)))


class TestBase128Int(tests.TestCase):

    def assertEqualEncode(self, bytes, val):
        self.assertEqual(bytes, groupcompress.encode_base128_int(val))

    def assertEqualDecode(self, val, num_decode, bytes):
        self.assertEqual((val, num_decode),
                         groupcompress.decode_base128_int(bytes))

    def test_encode(self):
        self.assertEqualEncode('\x01', 1)
        self.assertEqualEncode('\x02', 2)
        self.assertEqualEncode('\x7f', 127)
        self.assertEqualEncode('\x80\x01', 128)
        self.assertEqualEncode('\xff\x01', 255)
        self.assertEqualEncode('\x80\x02', 256)
        self.assertEqualEncode('\xff\xff\xff\xff\x0f', 0xFFFFFFFF)

    def test_decode(self):
        self.assertEqualDecode(1, 1, '\x01')
        self.assertEqualDecode(2, 1, '\x02')
        self.assertEqualDecode(127, 1, '\x7f')
        self.assertEqualDecode(128, 2, '\x80\x01')
        self.assertEqualDecode(255, 2, '\xff\x01')
        self.assertEqualDecode(256, 2, '\x80\x02')
        self.assertEqualDecode(0xFFFFFFFF, 5, '\xff\xff\xff\xff\x0f')

    def test_decode_with_trailing_bytes(self):
        self.assertEqualDecode(1, 1, '\x01abcdef')
        self.assertEqualDecode(127, 1, '\x7f\x01')
        self.assertEqualDecode(128, 2, '\x80\x01abcdef')
        self.assertEqualDecode(255, 2, '\xff\x01\xff')


class TestGroupCompressBlock(tests.TestCase):

    def test_from_empty_bytes(self):
        self.assertRaises(errors.InvalidGroupCompressBlock,
                          groupcompress.GroupCompressBlock.from_bytes, '')

    def test_from_bytes(self):
        block = groupcompress.GroupCompressBlock.from_bytes('gcb1p\n')
        self.assertIsInstance(block, groupcompress.GroupCompressBlock)

    def test_add_entry(self):
        gcb = groupcompress.GroupCompressBlock()
        e = gcb.add_entry(('foo', 'bar'), 'fulltext', 'abcd'*10, 0, 100)
        self.assertIsInstance(e, groupcompress.GroupCompressBlockEntry)
        self.assertEqual(('foo', 'bar'), e.key)
        self.assertEqual('fulltext', e.type)
        self.assertEqual('abcd'*10, e.sha1)
        self.assertEqual(0, e.start)
        self.assertEqual(100, e.length)

    def test_to_bytes(self):
        gcb = groupcompress.GroupCompressBlock()
        gcb.add_entry(('foo', 'bar'), 'fulltext', 'abcd'*10, 0, 100)
        gcb.add_entry(('bing',), 'fulltext', 'abcd'*10, 100, 100)
        self.assertEqualDiff('gcb1p\n' # group compress block v1 plain
                             '183\n' # Length of all meta-info
                             'key:bing\n'
                             'type:fulltext\n'
                             'sha1:abcdabcdabcdabcdabcdabcdabcdabcdabcdabcd\n'
                             'start:100\n'
                             'length:100\n'
                             '\n'
                             'key:foo\x00bar\n'
                             'type:fulltext\n'
                             'sha1:abcdabcdabcdabcdabcdabcdabcdabcdabcdabcd\n'
                             'start:0\n'
                             'length:100\n'
                             '\n', gcb.to_bytes())

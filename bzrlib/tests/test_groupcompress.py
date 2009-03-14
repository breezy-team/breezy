# Copyright (C) 2008, 2009 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for group compression."""

import zlib

from bzrlib import (
    groupcompress,
    tests,
    )
from bzrlib.osutils import sha_string
from bzrlib.tests import (
    TestCaseWithTransport,
    multiply_tests,
    )


class TestGroupCompressor(tests.TestCase):
    """Tests for GroupCompressor"""

    def test_empty_delta(self):
        compressor = groupcompress.GroupCompressor(True)
        self.assertEqual([], compressor.lines)

    def test_one_nosha_delta(self):
        # diff against NUKK
        compressor = groupcompress.GroupCompressor(True)
        sha1, end_point, _, _ = compressor.compress(('label',),
            'strange\ncommon\n', None)
        self.assertEqual(sha_string('strange\ncommon\n'), sha1)
        expected_lines = [
            'f', '\x0f', 'strange\ncommon\n',
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
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.lines)
        sha1_2, end_point, _, _ = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        self.assertEqual(sha_string('common long line\n'
                                    'that needs a 16 byte match\n'
                                    'different\n'), sha1_2)
        expected_lines.extend([
            # 'delta', delta length
            'd\x10',
            # source and target length
            '\x36\x36',
            # copy the line common
            '\x91\x0a\x2c', #copy, offset 0x0a, len 0x2c
            # add the line different, and the trailing newline
            '\x0adifferent\n', # insert 10 bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = groupcompress.GroupCompressor(True)
        sha1_1, end_point, _, _ = compressor.compress(('label',),
            'strange\ncommon very very long line\nwith some extra text\n', None)
        sha1_2, _, _, _ = compressor.compress(('newlabel',),
            'different\nmoredifferent\nand then some more\n', None)
        expected_lines = list(compressor.lines)
        sha1_3, end_point, _, _ = compressor.compress(('label3',),
            'new\ncommon very very long line\nwith some extra text\n'
            'different\nmoredifferent\nand then some more\n',
            None)
        self.assertEqual(
            sha_string('new\ncommon very very long line\nwith some extra text\n'
                       'different\nmoredifferent\nand then some more\n'),
            sha1_3)
        expected_lines.extend([
            # 'delta', delta length
            'd\x0c',
            # source and target length
            '\x67\x5f'
            # insert new
            '\x03new',
            # Copy of first parent 'common' range
            '\x91\x09\x31' # copy, offset 0x09, 0x31 bytes
            # Copy of second parent 'different' range
            '\x91\x3c\x2b' # copy, offset 0x3c, 0x2b bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_stats(self):
        compressor = groupcompress.GroupCompressor(True)
        compressor.compress(('label',), 'strange\ncommon long line\n'
                                        'plus more text\n', None)
        compressor.compress(('newlabel',),
                            'common long line\nplus more text\n'
                            'different\nmoredifferent\n', None)
        compressor.compress(('label3',),
                            'new\ncommon long line\nplus more text\n'
                            '\ndifferent\nmoredifferent\n', None)
        self.assertAlmostEqual(1.4, compressor.ratio(), 1)

    def test_extract_from_compressor(self):
        # Knit fetching will try to reconstruct texts locally which results in
        # reading something that is in the compressor stream already.
        compressor = groupcompress.GroupCompressor(True)
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.lines)
        sha1_2, end_point, _, _ = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        # get the first out
        self.assertEqual(('strange\ncommon long line\n'
                          'that needs a 16 byte match\n', sha1_1),
            compressor.extract(('label',)))
        # and the second
        self.assertEqual(('common long line\nthat needs a 16 byte match\n'
                          'different\n', sha1_2),
                         compressor.extract(('newlabel',)))


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
        self.assertRaises(ValueError,
                          groupcompress.GroupCompressBlock.from_bytes, '')

    def test_from_minimal_bytes(self):
        block = groupcompress.GroupCompressBlock.from_bytes(
            'gcb1z\n0\n0\n0\n0\n')
        self.assertIsInstance(block, groupcompress.GroupCompressBlock)
        self.assertEqual({}, block._entries)
        self.assertEqual('', block._content)

    def test_from_bytes(self):
        header = ('key:bing\n'
            'sha1:abcdabcdabcdabcdabcdabcdabcdabcdabcdabcd\n'
            'type:fulltext\n'
            'start:100\n'
            'length:100\n'
            '\n'
            'key:foo\x00bar\n'
            'sha1:abcdabcdabcdabcdabcdabcdabcdabcdabcdabcd\n'
            'type:fulltext\n'
            'start:0\n'
            'length:100\n'
            '\n')
        z_header = zlib.compress(header)
        content = ('a tiny bit of content\n')
        z_content = zlib.compress(content)
        z_bytes = (
            'gcb1z\n' # group compress block v1 plain
            '%d\n' # Length of zlib bytes
            '%d\n' # Length of all meta-info
            '%d\n' # Length of compressed content
            '%d\n' # Length of uncompressed content
            '%s'   # Compressed header
            '%s'   # Compressed content
            ) % (len(z_header), len(header),
                 len(z_content), len(content),
                 z_header, z_content)
        block = groupcompress.GroupCompressBlock.from_bytes(
            z_bytes)
        self.assertIsInstance(block, groupcompress.GroupCompressBlock)
        self.assertEqual([('bing',), ('foo', 'bar')], sorted(block._entries))
        bing = block._entries[('bing',)]
        self.assertEqual(('bing',), bing.key)
        self.assertEqual('fulltext', bing.type)
        self.assertEqual('abcd'*10, bing.sha1)
        self.assertEqual(100, bing.start)
        self.assertEqual(100, bing.length)
        foobar = block._entries[('foo', 'bar')]
        self.assertEqual(('foo', 'bar'), foobar.key)
        self.assertEqual('fulltext', foobar.type)
        self.assertEqual('abcd'*10, foobar.sha1)
        self.assertEqual(0, foobar.start)
        self.assertEqual(100, foobar.length)
        self.assertEqual(content, block._content)

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
        bytes = gcb.to_bytes('this is some content\n'
                             'this content will be compressed\n')
        expected_header =('gcb1z\n' # group compress block v1 zlib
                          '76\n' # Length of compressed bytes
                          '183\n' # Length of uncompressed meta-info
                          '50\n' # Length of compressed content
                          '53\n' # Length of uncompressed content
                         )
        self.assertStartsWith(bytes, expected_header)
        remaining_bytes = bytes[len(expected_header):]
        raw_bytes = zlib.decompress(remaining_bytes)
        self.assertEqualDiff('key:bing\n'
                             'sha1:abcdabcdabcdabcdabcdabcdabcdabcdabcdabcd\n'
                             'type:fulltext\n'
                             'start:100\n'
                             'length:100\n'
                             '\n'
                             'key:foo\x00bar\n'
                             'sha1:abcdabcdabcdabcdabcdabcdabcdabcdabcdabcd\n'
                             'type:fulltext\n'
                             'start:0\n'
                             'length:100\n'
                             '\n', raw_bytes)


class TestCaseWithGroupCompressVersionedFiles(tests.TestCaseWithTransport):

    def make_test_vf(self, create_graph, keylength=1, do_cleanup=True):
        t = self.get_transport()
        vf = groupcompress.make_pack_factory(graph=create_graph,
            delta=False, keylength=keylength)(t)
        if do_cleanup:
            self.addCleanup(groupcompress.cleanup_pack_group, vf)
        return vf

    def test_get_record_stream_as_requested(self):
        # Consider promoting 'as-requested' to general availability, and
        # make this a VF interface test
        vf = self.make_test_vf(False, do_cleanup=False)
        vf.add_lines(('a',), (), ['lines\n'])
        vf.add_lines(('b',), (), ['lines\n'])
        vf.add_lines(('c',), (), ['lines\n'])
        vf.add_lines(('d',), (), ['lines\n'])
        vf.writer.end()
        keys = [record.key for record in vf.get_record_stream(
                    [('a',), ('b',), ('c',), ('d',)],
                    'as-requested', False)]
        self.assertEqual([('a',), ('b',), ('c',), ('d',)], keys)
        keys = [record.key for record in vf.get_record_stream(
                    [('b',), ('a',), ('d',), ('c',)],
                    'as-requested', False)]
        self.assertEqual([('b',), ('a',), ('d',), ('c',)], keys)
        # We have to cleanup manually, because we create a second VF
        groupcompress.cleanup_pack_group(vf)

        # It should work even after being repacked into another VF
        vf2 = self.make_test_vf(False)
        vf2.insert_record_stream(vf.get_record_stream(
                    [('b',), ('a',), ('d',), ('c',)], 'as-requested', False))
        vf2.writer.end()

        keys = [record.key for record in vf2.get_record_stream(
                    [('a',), ('b',), ('c',), ('d',)],
                    'as-requested', False)]
        self.assertEqual([('a',), ('b',), ('c',), ('d',)], keys)
        keys = [record.key for record in vf2.get_record_stream(
                    [('b',), ('a',), ('d',), ('c',)],
                    'as-requested', False)]
        self.assertEqual([('b',), ('a',), ('d',), ('c',)], keys)

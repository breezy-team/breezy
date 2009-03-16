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
    errors,
    osutils,
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
        self.assertIs(None, block._content)
        self.assertEqual('', block._z_content)
        block._ensure_content()
        self.assertEqual('', block._content)
        self.assertIs(None, block._z_content)
        block._ensure_content() # Ensure content is safe to call 2x

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
        self.assertEqual(z_content, block._z_content)
        self.assertIs(None, block._content)
        block._ensure_content()
        self.assertIs(None, block._z_content)
        self.assertEqual(content, block._content)

    def test_from_old_bytes(self):
        # Backwards compatibility, with groups that didn't define content length
        content = ('a tiny bit of content\n')
        z_content = zlib.compress(content)
        z_bytes = (
            'gcb1z\n' # group compress block v1 plain
            '0\n' # Length of zlib bytes
            '0\n' # Length of all meta-info
            ''    # Compressed header
            '%s'   # Compressed content
            ) % (z_content)
        block = groupcompress.GroupCompressBlock.from_bytes(
            z_bytes)
        self.assertIsInstance(block, groupcompress.GroupCompressBlock)
        block._ensure_content()
        self.assertIs(None, block._z_content)
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

    def test_partial_decomp(self):
        content_chunks = []
        # We need a sufficient amount of data so that zlib.decompress has
        # partial decompression to work with. Most auto-generated data
        # compresses a bit too well, we want a combination, so we combine a sha
        # hash with compressible data.
        for i in xrange(2048):
            next_content = '%d\nThis is a bit of duplicate text\n' % (i,)
            content_chunks.append(next_content)
            next_sha1 = osutils.sha_string(next_content)
            content_chunks.append(next_sha1 + '\n')
        content = ''.join(content_chunks)
        self.assertEqual(158634, len(content))
        z_content = zlib.compress(content)
        self.assertEqual(57182, len(z_content))
        block = groupcompress.GroupCompressBlock()
        block._z_content = z_content
        block._z_content_length = len(z_content)
        block._compressor_name = 'zlib'
        block._content_length = 158634
        self.assertIs(None, block._content)
        block._ensure_content(100)
        self.assertIsNot(None, block._content)
        # We have decompressed at least 100 bytes
        self.assertTrue(len(block._content) >= 100)
        # We have not decompressed the whole content
        self.assertTrue(len(block._content) < 158634)
        self.assertEqualDiff(content[:len(block._content)], block._content)
        # ensuring content that we already have shouldn't cause any more data
        # to be extracted
        cur_len = len(block._content)
        block._ensure_content(cur_len - 10)
        self.assertEqual(cur_len, len(block._content))
        # Now we want a bit more content
        cur_len += 10
        block._ensure_content(cur_len)
        self.assertTrue(len(block._content) >= cur_len)
        self.assertTrue(len(block._content) < 158634)
        self.assertEqualDiff(content[:len(block._content)], block._content)
        # And now lets finish
        block._ensure_content(158634)
        self.assertEqualDiff(content, block._content)
        # And the decompressor is finalized
        self.assertIs(None, block._z_content_decompressor)

    def test_partial_decomp_no_known_length(self):
        content_chunks = []
        for i in xrange(2048):
            next_content = '%d\nThis is a bit of duplicate text\n' % (i,)
            content_chunks.append(next_content)
            next_sha1 = osutils.sha_string(next_content)
            content_chunks.append(next_sha1 + '\n')
        content = ''.join(content_chunks)
        self.assertEqual(158634, len(content))
        z_content = zlib.compress(content)
        self.assertEqual(57182, len(z_content))
        block = groupcompress.GroupCompressBlock()
        block._z_content = z_content
        block._z_content_length = len(z_content)
        block._compressor_name = 'zlib'
        block._content_length = None # Don't tell the decompressed length
        self.assertIs(None, block._content)
        block._ensure_content(100)
        self.assertIsNot(None, block._content)
        # We have decompressed at least 100 bytes
        self.assertTrue(len(block._content) >= 100)
        # We have not decompressed the whole content
        self.assertTrue(len(block._content) < 158634)
        self.assertEqualDiff(content[:len(block._content)], block._content)
        # ensuring content that we already have shouldn't cause any more data
        # to be extracted
        cur_len = len(block._content)
        block._ensure_content(cur_len - 10)
        self.assertEqual(cur_len, len(block._content))
        # Now we want a bit more content
        cur_len += 10
        block._ensure_content(cur_len)
        self.assertTrue(len(block._content) >= cur_len)
        self.assertTrue(len(block._content) < 158634)
        self.assertEqualDiff(content[:len(block._content)], block._content)
        # And now lets finish
        block._ensure_content()
        self.assertEqualDiff(content, block._content)
        # And the decompressor is finalized
        self.assertIs(None, block._z_content_decompressor)


class TestCaseWithGroupCompressVersionedFiles(tests.TestCaseWithTransport):

    def make_test_vf(self, create_graph, keylength=1, do_cleanup=True):
        t = self.get_transport()
        vf = groupcompress.make_pack_factory(graph=create_graph,
            delta=False, keylength=keylength)(t)
        if do_cleanup:
            self.addCleanup(groupcompress.cleanup_pack_group, vf)
        return vf


class TestGroupCompressVersionedFiles(TestCaseWithGroupCompressVersionedFiles):

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


class TestLazyGroupCompressFactory(tests.TestCaseWithTransport):

    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        start = 0
        for key in sorted(key_to_text):
            compressor.compress(key, key_to_text[key], None)
        entries = compressor._block._entries
        raw_bytes = compressor.flush()
        return entries, groupcompress.GroupCompressBlock.from_bytes(raw_bytes)

    def entry_and_block_to_factory(self, key, entries, block, first=False):
        entry = entries[key]
        return groupcompress.LazyGroupCompressFactory(key, (), block,
            entry.start, entry.start + entry.length, first)

    def test_get_fulltexts(self):
        key_to_text = {
            ('key1',): "this is a text\n"
                       "with a reasonable amount of compressible bytes\n",
            ('key2',): "another text\n"
                       "with a reasonable amount of compressible bytes\n",
        }
        entries, block = self.make_block(key_to_text)
        for key in key_to_text:
            cf = self.entry_and_block_to_factory(key, entries, block)
            text = key_to_text[key]
            self.assertEqual(text, cf.get_bytes_as('fulltext'))
            self.assertEqual(text, ''.join(cf.get_bytes_as('chunked')))
            self.assertRaises(errors.UnavailableRepresentation,
                cf.get_bytes_as, 'unknown-representation')

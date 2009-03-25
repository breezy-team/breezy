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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for group compression."""

import zlib

from bzrlib import (
    groupcompress,
    errors,
    osutils,
    tests,
    versionedfile,
    )
from bzrlib.osutils import sha_string
from bzrlib.tests import (
    TestCaseWithTransport,
    multiply_tests,
    )


class TestGroupCompressor(tests.TestCase):
    """Tests for GroupCompressor"""

    def test_empty_delta(self):
        compressor = groupcompress.GroupCompressor()
        self.assertEqual([], compressor.lines)

    def test_one_nosha_delta(self):
        # diff against NUKK
        compressor = groupcompress.GroupCompressor()
        sha1, start_point, end_point, _, _ = compressor.compress(('label',),
            'strange\ncommon\n', None)
        self.assertEqual(sha_string('strange\ncommon\n'), sha1)
        expected_lines = [
            'f', '\x0f', 'strange\ncommon\n',
            ]
        self.assertEqual(expected_lines, compressor.lines)
        self.assertEqual(0, start_point)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_empty_content(self):
        compressor = groupcompress.GroupCompressor()
        # Adding empty bytes should return the 'null' record
        sha1, start_point, end_point, kind, _ = compressor.compress(('empty',),
            '', None)
        self.assertEqual(0, start_point)
        self.assertEqual(0, end_point)
        self.assertEqual('fulltext', kind)
        self.assertEqual(groupcompress._null_sha1, sha1)
        self.assertEqual(0, compressor.endpoint)
        self.assertEqual([], compressor.lines)
        # Even after adding some content
        compressor.compress(('content',), 'some\nbytes\n', None)
        self.assertTrue(compressor.endpoint > 0)
        sha1, start_point, end_point, kind, _ = compressor.compress(('empty2',),
            '', None)
        self.assertEqual(0, start_point)
        self.assertEqual(0, end_point)
        self.assertEqual('fulltext', kind)
        self.assertEqual(groupcompress._null_sha1, sha1)

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
        compressor = groupcompress.GroupCompressor()
        sha1_1, _, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.lines)
        sha1_2, start_point, end_point, _, _ = compressor.compress(('newlabel',),
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
        compressor = groupcompress.GroupCompressor()
        sha1_1, _, _, _, _ = compressor.compress(('label',),
            'strange\ncommon very very long line\nwith some extra text\n', None)
        sha1_2, _, _, _, _ = compressor.compress(('newlabel',),
            'different\nmoredifferent\nand then some more\n', None)
        expected_lines = list(compressor.lines)
        sha1_3, start_point, end_point, _, _ = compressor.compress(('label3',),
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
        compressor = groupcompress.GroupCompressor()
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
        compressor = groupcompress.GroupCompressor()
        sha1_1, _, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.lines)
        sha1_2, _, end_point, _, _ = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        # get the first out
        self.assertEqual(('strange\ncommon long line\n'
                          'that needs a 16 byte match\n', sha1_1),
            compressor.extract(('label',)))
        # and the second
        self.assertEqual(('common long line\nthat needs a 16 byte match\n'
                          'different\n', sha1_2),
                         compressor.extract(('newlabel',)))


class TestEncodeCopyInstruction(tests.TestCase):

    def assertCopyInstruction(self, expected, offset, length):
        bytes = groupcompress.encode_copy_instruction(offset, length)
        if expected != bytes:
            self.assertEqual([hex(ord(e)) for e in expected],
                             [hex(ord(b)) for b in bytes])

    def test_encode_no_length(self):
        self.assertCopyInstruction('\x80', 0, None)
        self.assertCopyInstruction('\x81\x01', 1, None)
        self.assertCopyInstruction('\x81\x0a', 10, None)
        self.assertCopyInstruction('\x81\xff', 255, None)
        self.assertCopyInstruction('\x82\x01', 256, None)
        self.assertCopyInstruction('\x83\x01\x01', 257, None)
        self.assertCopyInstruction('\x8F\xff\xff\xff\xff', 0xFFFFFFFF, None)
        self.assertCopyInstruction('\x8E\xff\xff\xff', 0xFFFFFF00, None)
        self.assertCopyInstruction('\x8D\xff\xff\xff', 0xFFFF00FF, None)
        self.assertCopyInstruction('\x8B\xff\xff\xff', 0xFF00FFFF, None)
        self.assertCopyInstruction('\x87\xff\xff\xff', 0x00FFFFFF, None)
        self.assertCopyInstruction('\x8F\x04\x03\x02\x01', 0x01020304, None)

    def test_encode_no_offset(self):
        self.assertCopyInstruction('\x90\x01', 0, 1)
        self.assertCopyInstruction('\x90\x0a', 0, 10)
        self.assertCopyInstruction('\x90\xff', 0, 255)
        self.assertCopyInstruction('\xA0\x01', 0, 256)
        self.assertCopyInstruction('\xB0\x01\x01', 0, 257)
        self.assertCopyInstruction('\xB0\x01\x01', 0, 257)
        self.assertCopyInstruction('\xB0\xff\xff', 0, 0xFFFF)
        # Special case, if copy == 64KiB, then we store exactly 0
        # Note that this puns with a copy of exactly 0 bytes, but we don't care
        # about that, as we would never actually copy 0 bytes
        self.assertCopyInstruction('\x80', 0, 64*1024)

    def test_encode(self):
        self.assertCopyInstruction('\x91\x01\x01', 1, 1)
        self.assertCopyInstruction('\x91\x09\x0a', 9, 10)
        self.assertCopyInstruction('\x91\xfe\xff', 254, 255)
        self.assertCopyInstruction('\xA2\x02\x01', 512, 256)
        self.assertCopyInstruction('\xB3\x02\x01\x01\x01', 258, 257)
        self.assertCopyInstruction('\xB0\x01\x01', 0, 257)
        # Special case, if copy == 64KiB, then we store exactly 0
        # Note that this puns with a copy of exactly 0 bytes, but we don't care
        # about that, as we would never actually copy 0 bytes
        self.assertCopyInstruction('\x81\x0a', 10, 64*1024)


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

    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        start = 0
        for key in sorted(key_to_text):
            compressor.compress(key, key_to_text[key], None)
        block = compressor.flush()
        entries = block._entries
        # Go through from_bytes(to_bytes()) so that we start with a compressed
        # content object
        return entries, groupcompress.GroupCompressBlock.from_bytes(
            block.to_bytes())

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
        self.assertEqual('', block._z_content)
        block._ensure_content() # Ensure content is safe to call 2x

    def test_from_bytes_with_labels(self):
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
        block._parse_header()
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
        self.assertEqual(z_content, block._z_content)
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
        self.assertEqual(z_content, block._z_content)
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
        no_labels = groupcompress._NO_LABELS
        def reset():
            groupcompress._NO_LABELS = no_labels
        self.addCleanup(reset)
        groupcompress._NO_LABELS = False
        gcb = groupcompress.GroupCompressBlock()
        gcb.add_entry(('foo', 'bar'), 'fulltext', 'abcd'*10, 0, 100)
        gcb.add_entry(('bing',), 'fulltext', 'abcd'*10, 100, 100)
        gcb.set_content('this is some content\n'
                        'this content will be compressed\n')
        bytes = gcb.to_bytes()
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

    def make_test_vf(self, create_graph, keylength=1, do_cleanup=True,
                     dir='.'):
        t = self.get_transport(dir)
        t.ensure_base()
        vf = groupcompress.make_pack_factory(graph=create_graph,
            delta=False, keylength=keylength)(t)
        if do_cleanup:
            self.addCleanup(groupcompress.cleanup_pack_group, vf)
        return vf


class TestGroupCompressVersionedFiles(TestCaseWithGroupCompressVersionedFiles):

    def test_get_record_stream_as_requested(self):
        # Consider promoting 'as-requested' to general availability, and
        # make this a VF interface test
        vf = self.make_test_vf(False, dir='source')
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

        # It should work even after being repacked into another VF
        vf2 = self.make_test_vf(False, dir='target')
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

    def test_insert_record_stream_re_uses_blocks(self):
        vf = self.make_test_vf(True, dir='source')
        def grouped_stream(revision_ids, first_parents=()):
            parents = first_parents
            for revision_id in revision_ids:
                key = (revision_id,)
                record = versionedfile.FulltextContentFactory(
                    key, parents, None,
                    'some content that is\n'
                    'identical except for\n'
                    'revision_id:%s\n' % (revision_id,))
                yield record
                parents = (key,)
        # One group, a-d
        vf.insert_record_stream(grouped_stream(['a', 'b', 'c', 'd']))
        # Second group, e-h
        vf.insert_record_stream(grouped_stream(['e', 'f', 'g', 'h'],
                                               first_parents=(('d',),)))
        block_bytes = {}
        stream = vf.get_record_stream([(r,) for r in 'abcdefgh'],
                                      'unordered', False)
        num_records = 0
        for record in stream:
            if record.key in [('a',), ('e',)]:
                self.assertEqual('groupcompress-block', record.storage_kind)
            else:
                self.assertEqual('groupcompress-block-ref',
                                 record.storage_kind)
            block_bytes[record.key] = record._manager._block._z_content
            num_records += 1
        self.assertEqual(8, num_records)
        for r in 'abcd':
            key = (r,)
            self.assertIs(block_bytes[key], block_bytes[('a',)])
            self.assertNotEqual(block_bytes[key], block_bytes[('e',)])
        for r in 'efgh':
            key = (r,)
            self.assertIs(block_bytes[key], block_bytes[('e',)])
            self.assertNotEqual(block_bytes[key], block_bytes[('a',)])
        # Now copy the blocks into another vf, and ensure that the blocks are
        # preserved without creating new entries
        vf2 = self.make_test_vf(True, dir='target')
        # ordering in 'groupcompress' order, should actually swap the groups in
        # the target vf, but the groups themselves should not be disturbed.
        vf2.insert_record_stream(vf.get_record_stream(
            [(r,) for r in 'abcdefgh'], 'groupcompress', False))
        stream = vf2.get_record_stream([(r,) for r in 'abcdefgh'],
                                       'groupcompress', False)
        vf2.writer.end()
        num_records = 0
        for record in stream:
            num_records += 1
            self.assertEqual(block_bytes[record.key],
                             record._manager._block._z_content)
        self.assertEqual(8, num_records)

    def test__insert_record_stream_no_reuse_block(self):
        vf = self.make_test_vf(True, dir='source')
        def grouped_stream(revision_ids, first_parents=()):
            parents = first_parents
            for revision_id in revision_ids:
                key = (revision_id,)
                record = versionedfile.FulltextContentFactory(
                    key, parents, None,
                    'some content that is\n'
                    'identical except for\n'
                    'revision_id:%s\n' % (revision_id,))
                yield record
                parents = (key,)
        # One group, a-d
        vf.insert_record_stream(grouped_stream(['a', 'b', 'c', 'd']))
        # Second group, e-h
        vf.insert_record_stream(grouped_stream(['e', 'f', 'g', 'h'],
                                               first_parents=(('d',),)))
        vf.writer.end()
        self.assertEqual(8, len(list(vf.get_record_stream(
                                        [(r,) for r in 'abcdefgh'],
                                        'unordered', False))))
        # Now copy the blocks into another vf, and ensure that the blocks are
        # preserved without creating new entries
        vf2 = self.make_test_vf(True, dir='target')
        # ordering in 'groupcompress' order, should actually swap the groups in
        # the target vf, but the groups themselves should not be disturbed.
        list(vf2._insert_record_stream(vf.get_record_stream(
            [(r,) for r in 'abcdefgh'], 'groupcompress', False),
            reuse_blocks=False))
        vf2.writer.end()
        # After inserting with reuse_blocks=False, we should have everything in
        # a single new block.
        stream = vf2.get_record_stream([(r,) for r in 'abcdefgh'],
                                       'groupcompress', False)
        block = None
        for record in stream:
            if block is None:
                block = record._manager._block
            else:
                self.assertIs(block, record._manager._block)


class TestLazyGroupCompress(tests.TestCaseWithTransport):

    _texts = {
        ('key1',): "this is a text\n"
                   "with a reasonable amount of compressible bytes\n",
        ('key2',): "another text\n"
                   "with a reasonable amount of compressible bytes\n",
        ('key3',): "yet another text which won't be extracted\n"
                   "with a reasonable amount of compressible bytes\n",
        ('key4',): "this will be extracted\n"
                   "but references bytes from\n"
                   "yet another text which won't be extracted\n"
                   "with a reasonable amount of compressible bytes\n",
    }
    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        start = 0
        for key in sorted(key_to_text):
            compressor.compress(key, key_to_text[key], None)
        block = compressor.flush()
        entries = block._entries
        raw_bytes = block.to_bytes()
        return entries, groupcompress.GroupCompressBlock.from_bytes(raw_bytes)

    def add_key_to_manager(self, key, entries, block, manager):
        entry = entries[key]
        manager.add_factory(entry.key, (), entry.start, entry.end)

    def test_get_fulltexts(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key1',), entries, block, manager)
        self.add_key_to_manager(('key2',), entries, block, manager)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as('fulltext'))
        self.assertEqual([('key1',), ('key2',)], result_order)

        # If we build the manager in the opposite order, we should get them
        # back in the opposite order
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key2',), entries, block, manager)
        self.add_key_to_manager(('key1',), entries, block, manager)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as('fulltext'))
        self.assertEqual([('key2',), ('key1',)], result_order)

    def test__wire_bytes_no_keys(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        wire_bytes = manager._wire_bytes()
        block_length = len(block.to_bytes())
        # We should have triggered a strip, since we aren't using any content
        stripped_block = manager._block.to_bytes()
        self.assertTrue(block_length > len(stripped_block))
        empty_z_header = zlib.compress('')
        self.assertEqual('groupcompress-block\n'
                         '8\n' # len(compress(''))
                         '0\n' # len('')
                         '%d\n'# compressed block len
                         '%s'  # zheader
                         '%s'  # block
                         % (len(stripped_block), empty_z_header,
                            stripped_block),
                         wire_bytes)

    def test__wire_bytes(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key1',), entries, block, manager)
        self.add_key_to_manager(('key4',), entries, block, manager)
        block_bytes = block.to_bytes()
        wire_bytes = manager._wire_bytes()
        (storage_kind, z_header_len, header_len,
         block_len, rest) = wire_bytes.split('\n', 4)
        z_header_len = int(z_header_len)
        header_len = int(header_len)
        block_len = int(block_len)
        self.assertEqual('groupcompress-block', storage_kind)
        self.assertEqual(33, z_header_len)
        self.assertEqual(25, header_len)
        self.assertEqual(len(block_bytes), block_len)
        z_header = rest[:z_header_len]
        header = zlib.decompress(z_header)
        self.assertEqual(header_len, len(header))
        entry1 = entries[('key1',)]
        entry4 = entries[('key4',)]
        self.assertEqualDiff('key1\n'
                             '\n'  # no parents
                             '%d\n' # start offset
                             '%d\n' # end byte
                             'key4\n'
                             '\n'
                             '%d\n'
                             '%d\n'
                             % (entry1.start, entry1.end,
                                entry4.start, entry4.end),
                            header)
        z_block = rest[z_header_len:]
        self.assertEqual(block_bytes, z_block)

    def test_from_bytes(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key1',), entries, block, manager)
        self.add_key_to_manager(('key4',), entries, block, manager)
        wire_bytes = manager._wire_bytes()
        self.assertStartsWith(wire_bytes, 'groupcompress-block\n')
        manager = groupcompress._LazyGroupContentManager.from_bytes(wire_bytes)
        self.assertIsInstance(manager, groupcompress._LazyGroupContentManager)
        self.assertEqual(2, len(manager._factories))
        self.assertEqual(block._z_content, manager._block._z_content)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as('fulltext'))
        self.assertEqual([('key1',), ('key4',)], result_order)

    def test__check_rebuild_no_changes(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request all the keys, which ensures that we won't rebuild
        self.add_key_to_manager(('key1',), entries, block, manager)
        self.add_key_to_manager(('key2',), entries, block, manager)
        self.add_key_to_manager(('key3',), entries, block, manager)
        self.add_key_to_manager(('key4',), entries, block, manager)
        manager._check_rebuild_block()
        self.assertIs(block, manager._block)

    def test__check_rebuild_only_one(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request just the first key, which should trigger a 'strip' action
        self.add_key_to_manager(('key1',), entries, block, manager)
        manager._check_rebuild_block()
        self.assertIsNot(block, manager._block)
        self.assertTrue(block._content_length > manager._block._content_length)
        # We should be able to still get the content out of this block, though
        # it should only have 1 entry
        for record in manager.get_record_stream():
            self.assertEqual(('key1',), record.key)
            self.assertEqual(self._texts[record.key],
                             record.get_bytes_as('fulltext'))

    def test__check_rebuild_middle(self):
        entries, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request a small key in the middle should trigger a 'rebuild'
        self.add_key_to_manager(('key4',), entries, block, manager)
        manager._check_rebuild_block()
        self.assertIsNot(block, manager._block)
        self.assertTrue(block._content_length > manager._block._content_length)
        for record in manager.get_record_stream():
            self.assertEqual(('key4',), record.key)
            self.assertEqual(self._texts[record.key],
                             record.get_bytes_as('fulltext'))

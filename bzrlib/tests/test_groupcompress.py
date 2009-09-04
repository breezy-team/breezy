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
    btree_index,
    groupcompress,
    errors,
    index as _mod_index,
    osutils,
    tests,
    trace,
    versionedfile,
    )
from bzrlib.osutils import sha_string
from bzrlib.tests.test__groupcompress import CompiledGroupCompressFeature


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    to_adapt, result = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance(TestAllGroupCompressors))
    scenarios = [
        ('python', {'compressor': groupcompress.PythonGroupCompressor}),
        ]
    if CompiledGroupCompressFeature.available():
        scenarios.append(('C',
            {'compressor': groupcompress.PyrexGroupCompressor}))
    return tests.multiply_tests(to_adapt, scenarios, result)


class TestGroupCompressor(tests.TestCase):

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


class TestAllGroupCompressors(TestGroupCompressor):
    """Tests for GroupCompressor"""

    compressor = None # Set by multiply_tests

    def test_empty_delta(self):
        compressor = self.compressor()
        self.assertEqual([], compressor.chunks)

    def test_one_nosha_delta(self):
        # diff against NUKK
        compressor = self.compressor()
        sha1, start_point, end_point, _ = compressor.compress(('label',),
            'strange\ncommon\n', None)
        self.assertEqual(sha_string('strange\ncommon\n'), sha1)
        expected_lines = 'f' '\x0f' 'strange\ncommon\n'
        self.assertEqual(expected_lines, ''.join(compressor.chunks))
        self.assertEqual(0, start_point)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_empty_content(self):
        compressor = self.compressor()
        # Adding empty bytes should return the 'null' record
        sha1, start_point, end_point, kind = compressor.compress(('empty',),
                                                                 '', None)
        self.assertEqual(0, start_point)
        self.assertEqual(0, end_point)
        self.assertEqual('fulltext', kind)
        self.assertEqual(groupcompress._null_sha1, sha1)
        self.assertEqual(0, compressor.endpoint)
        self.assertEqual([], compressor.chunks)
        # Even after adding some content
        compressor.compress(('content',), 'some\nbytes\n', None)
        self.assertTrue(compressor.endpoint > 0)
        sha1, start_point, end_point, kind = compressor.compress(('empty2',),
                                                                 '', None)
        self.assertEqual(0, start_point)
        self.assertEqual(0, end_point)
        self.assertEqual('fulltext', kind)
        self.assertEqual(groupcompress._null_sha1, sha1)

    def test_extract_from_compressor(self):
        # Knit fetching will try to reconstruct texts locally which results in
        # reading something that is in the compressor stream already.
        compressor = self.compressor()
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.chunks)
        sha1_2, _, end_point, _ = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        # get the first out
        self.assertEqual(('strange\ncommon long line\n'
                          'that needs a 16 byte match\n', sha1_1),
                         compressor.extract(('label',)))
        # and the second
        self.assertEqual(('common long line\nthat needs a 16 byte match\n'
                          'different\n', sha1_2),
                         compressor.extract(('newlabel',)))

    def test_pop_last(self):
        compressor = self.compressor()
        _, _, _, _ = compressor.compress(('key1',),
            'some text\nfor the first entry\n', None)
        expected_lines = list(compressor.chunks)
        _, _, _, _ = compressor.compress(('key2',),
            'some text\nfor the second entry\n', None)
        compressor.pop_last()
        self.assertEqual(expected_lines, compressor.chunks)


class TestPyrexGroupCompressor(TestGroupCompressor):

    _test_needs_features = [CompiledGroupCompressFeature]
    compressor = groupcompress.PyrexGroupCompressor

    def test_stats(self):
        compressor = self.compressor()
        compressor.compress(('label',),
                            'strange\n'
                            'common very very long line\n'
                            'plus more text\n', None)
        compressor.compress(('newlabel',),
                            'common very very long line\n'
                            'plus more text\n'
                            'different\n'
                            'moredifferent\n', None)
        compressor.compress(('label3',),
                            'new\n'
                            'common very very long line\n'
                            'plus more text\n'
                            'different\n'
                            'moredifferent\n', None)
        self.assertAlmostEqual(1.9, compressor.ratio(), 1)

    def test_two_nosha_delta(self):
        compressor = self.compressor()
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.chunks)
        sha1_2, start_point, end_point, _ = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        self.assertEqual(sha_string('common long line\n'
                                    'that needs a 16 byte match\n'
                                    'different\n'), sha1_2)
        expected_lines.extend([
            # 'delta', delta length
            'd\x0f',
            # source and target length
            '\x36',
            # copy the line common
            '\x91\x0a\x2c', #copy, offset 0x0a, len 0x2c
            # add the line different, and the trailing newline
            '\x0adifferent\n', # insert 10 bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = self.compressor()
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon very very long line\nwith some extra text\n', None)
        sha1_2, _, _, _ = compressor.compress(('newlabel',),
            'different\nmoredifferent\nand then some more\n', None)
        expected_lines = list(compressor.chunks)
        sha1_3, start_point, end_point, _ = compressor.compress(('label3',),
            'new\ncommon very very long line\nwith some extra text\n'
            'different\nmoredifferent\nand then some more\n',
            None)
        self.assertEqual(
            sha_string('new\ncommon very very long line\nwith some extra text\n'
                       'different\nmoredifferent\nand then some more\n'),
            sha1_3)
        expected_lines.extend([
            # 'delta', delta length
            'd\x0b',
            # source and target length
            '\x5f'
            # insert new
            '\x03new',
            # Copy of first parent 'common' range
            '\x91\x09\x31' # copy, offset 0x09, 0x31 bytes
            # Copy of second parent 'different' range
            '\x91\x3c\x2b' # copy, offset 0x3c, 0x2b bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)


class TestPythonGroupCompressor(TestGroupCompressor):

    compressor = groupcompress.PythonGroupCompressor

    def test_stats(self):
        compressor = self.compressor()
        compressor.compress(('label',),
                            'strange\n'
                            'common very very long line\n'
                            'plus more text\n', None)
        compressor.compress(('newlabel',),
                            'common very very long line\n'
                            'plus more text\n'
                            'different\n'
                            'moredifferent\n', None)
        compressor.compress(('label3',),
                            'new\n'
                            'common very very long line\n'
                            'plus more text\n'
                            'different\n'
                            'moredifferent\n', None)
        self.assertAlmostEqual(1.9, compressor.ratio(), 1)

    def test_two_nosha_delta(self):
        compressor = self.compressor()
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon long line\nthat needs a 16 byte match\n', None)
        expected_lines = list(compressor.chunks)
        sha1_2, start_point, end_point, _ = compressor.compress(('newlabel',),
            'common long line\nthat needs a 16 byte match\ndifferent\n', None)
        self.assertEqual(sha_string('common long line\n'
                                    'that needs a 16 byte match\n'
                                    'different\n'), sha1_2)
        expected_lines.extend([
            # 'delta', delta length
            'd\x0f',
            # target length
            '\x36',
            # copy the line common
            '\x91\x0a\x2c', #copy, offset 0x0a, len 0x2c
            # add the line different, and the trailing newline
            '\x0adifferent\n', # insert 10 bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = self.compressor()
        sha1_1, _, _, _ = compressor.compress(('label',),
            'strange\ncommon very very long line\nwith some extra text\n', None)
        sha1_2, _, _, _ = compressor.compress(('newlabel',),
            'different\nmoredifferent\nand then some more\n', None)
        expected_lines = list(compressor.chunks)
        sha1_3, start_point, end_point, _ = compressor.compress(('label3',),
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
            # target length
            '\x5f'
            # insert new
            '\x04new\n',
            # Copy of first parent 'common' range
            '\x91\x0a\x30' # copy, offset 0x0a, 0x30 bytes
            # Copy of second parent 'different' range
            '\x91\x3c\x2b' # copy, offset 0x3c, 0x2b bytes
            ])
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)


class TestGroupCompressBlock(tests.TestCase):

    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        start = 0
        for key in sorted(key_to_text):
            compressor.compress(key, key_to_text[key], None)
        locs = dict((key, (start, end)) for key, (start, _, end, _)
                    in compressor.labels_deltas.iteritems())
        block = compressor.flush()
        raw_bytes = block.to_bytes()
        # Go through from_bytes(to_bytes()) so that we start with a compressed
        # content object
        return locs, groupcompress.GroupCompressBlock.from_bytes(raw_bytes)

    def test_from_empty_bytes(self):
        self.assertRaises(ValueError,
                          groupcompress.GroupCompressBlock.from_bytes, '')

    def test_from_minimal_bytes(self):
        block = groupcompress.GroupCompressBlock.from_bytes(
            'gcb1z\n0\n0\n')
        self.assertIsInstance(block, groupcompress.GroupCompressBlock)
        self.assertIs(None, block._content)
        self.assertEqual('', block._z_content)
        block._ensure_content()
        self.assertEqual('', block._content)
        self.assertEqual('', block._z_content)
        block._ensure_content() # Ensure content is safe to call 2x

    def test_from_invalid(self):
        self.assertRaises(ValueError,
                          groupcompress.GroupCompressBlock.from_bytes,
                          'this is not a valid header')

    def test_from_bytes(self):
        content = ('a tiny bit of content\n')
        z_content = zlib.compress(content)
        z_bytes = (
            'gcb1z\n' # group compress block v1 plain
            '%d\n' # Length of compressed content
            '%d\n' # Length of uncompressed content
            '%s'   # Compressed content
            ) % (len(z_content), len(content), z_content)
        block = groupcompress.GroupCompressBlock.from_bytes(
            z_bytes)
        self.assertEqual(z_content, block._z_content)
        self.assertIs(None, block._content)
        self.assertEqual(len(z_content), block._z_content_length)
        self.assertEqual(len(content), block._content_length)
        block._ensure_content()
        self.assertEqual(z_content, block._z_content)
        self.assertEqual(content, block._content)

    def test_to_bytes(self):
        content = ('this is some content\n'
                   'this content will be compressed\n')
        gcb = groupcompress.GroupCompressBlock()
        gcb.set_content(content)
        bytes = gcb.to_bytes()
        self.assertEqual(gcb._z_content_length, len(gcb._z_content))
        self.assertEqual(gcb._content_length, len(content))
        expected_header =('gcb1z\n' # group compress block v1 zlib
                          '%d\n' # Length of compressed content
                          '%d\n' # Length of uncompressed content
                         ) % (gcb._z_content_length, gcb._content_length)
        self.assertStartsWith(bytes, expected_header)
        remaining_bytes = bytes[len(expected_header):]
        raw_bytes = zlib.decompress(remaining_bytes)
        self.assertEqual(content, raw_bytes)

        # we should get the same results if using the chunked version
        gcb = groupcompress.GroupCompressBlock()
        gcb.set_chunked_content(['this is some content\n'
                                 'this content will be compressed\n'],
                                 len(content))
        old_bytes = bytes
        bytes = gcb.to_bytes()
        self.assertEqual(old_bytes, bytes)

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

    def test__dump(self):
        dup_content = 'some duplicate content\nwhich is sufficiently long\n'
        key_to_text = {('1',): dup_content + '1 unique\n',
                       ('2',): dup_content + '2 extra special\n'}
        locs, block = self.make_block(key_to_text)
        self.assertEqual([('f', len(key_to_text[('1',)])),
                          ('d', 21, len(key_to_text[('2',)]),
                           [('c', 2, len(dup_content)),
                            ('i', len('2 extra special\n'), '')
                           ]),
                         ], block._dump())


class TestCaseWithGroupCompressVersionedFiles(tests.TestCaseWithTransport):

    def make_test_vf(self, create_graph, keylength=1, do_cleanup=True,
                     dir='.', inconsistency_fatal=True):
        t = self.get_transport(dir)
        t.ensure_base()
        vf = groupcompress.make_pack_factory(graph=create_graph,
            delta=False, keylength=keylength,
            inconsistency_fatal=inconsistency_fatal)(t)
        if do_cleanup:
            self.addCleanup(groupcompress.cleanup_pack_group, vf)
        return vf


class TestGroupCompressVersionedFiles(TestCaseWithGroupCompressVersionedFiles):

    def make_g_index(self, name, ref_lists=0, nodes=[]):
        builder = btree_index.BTreeBuilder(ref_lists)
        for node, references, value in nodes:
            builder.add_node(node, references, value)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return btree_index.BTreeGraphIndex(trans, name, size)

    def make_g_index_missing_parent(self):
        graph_index = self.make_g_index('missing_parent', 1,
            [(('parent', ), '2 78 2 10', ([],)),
             (('tip', ), '2 78 2 10',
              ([('parent', ), ('missing-parent', )],)),
              ])
        return graph_index

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

    def test_insert_record_stream_reuses_blocks(self):
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
        def small_size_stream():
            for record in vf.get_record_stream([(r,) for r in 'abcdefgh'],
                                               'groupcompress', False):
                record._manager._full_enough_block_size = \
                    record._manager._block._content_length
                yield record
                        
        vf2.insert_record_stream(small_size_stream())
        stream = vf2.get_record_stream([(r,) for r in 'abcdefgh'],
                                       'groupcompress', False)
        vf2.writer.end()
        num_records = 0
        for record in stream:
            num_records += 1
            self.assertEqual(block_bytes[record.key],
                             record._manager._block._z_content)
        self.assertEqual(8, num_records)

    def test_insert_record_stream_packs_on_the_fly(self):
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
        # Now copy the blocks into another vf, and see that the
        # insert_record_stream rebuilt a new block on-the-fly because of
        # under-utilization
        vf2 = self.make_test_vf(True, dir='target')
        vf2.insert_record_stream(vf.get_record_stream(
            [(r,) for r in 'abcdefgh'], 'groupcompress', False))
        stream = vf2.get_record_stream([(r,) for r in 'abcdefgh'],
                                       'groupcompress', False)
        vf2.writer.end()
        num_records = 0
        # All of the records should be recombined into a single block
        block = None
        for record in stream:
            num_records += 1
            if block is None:
                block = record._manager._block
            else:
                self.assertIs(block, record._manager._block)
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

    def test_add_missing_noncompression_parent_unvalidated_index(self):
        unvalidated = self.make_g_index_missing_parent()
        combined = _mod_index.CombinedGraphIndex([unvalidated])
        index = groupcompress._GCGraphIndex(combined,
            is_locked=lambda: True, parents=True,
            track_external_parent_refs=True)
        index.scan_unvalidated_index(unvalidated)
        self.assertEqual(
            frozenset([('missing-parent',)]), index.get_missing_parents())

    def test_track_external_parent_refs(self):
        g_index = self.make_g_index('empty', 1, [])
        mod_index = btree_index.BTreeBuilder(1, 1)
        combined = _mod_index.CombinedGraphIndex([g_index, mod_index])
        index = groupcompress._GCGraphIndex(combined,
            is_locked=lambda: True, parents=True,
            add_callback=mod_index.add_nodes,
            track_external_parent_refs=True)
        index.add_records([
            (('new-key',), '2 10 2 10', [(('parent-1',), ('parent-2',))])])
        self.assertEqual(
            frozenset([('parent-1',), ('parent-2',)]),
            index.get_missing_parents())

    def make_source_with_b(self, a_parent, path):
        source = self.make_test_vf(True, dir=path)
        source.add_lines(('a',), (), ['lines\n'])
        if a_parent:
            b_parents = (('a',),)
        else:
            b_parents = ()
        source.add_lines(('b',), b_parents, ['lines\n'])
        return source

    def do_inconsistent_inserts(self, inconsistency_fatal):
        target = self.make_test_vf(True, dir='target',
                                   inconsistency_fatal=inconsistency_fatal)
        for x in range(2):
            source = self.make_source_with_b(x==1, 'source%s' % x)
            target.insert_record_stream(source.get_record_stream(
                [('b',)], 'unordered', False))

    def test_inconsistent_redundant_inserts_warn(self):
        """Should not insert a record that is already present."""
        warnings = []
        def warning(template, args):
            warnings.append(template % args)
        _trace_warning = trace.warning
        trace.warning = warning
        try:
            self.do_inconsistent_inserts(inconsistency_fatal=False)
        finally:
            trace.warning = _trace_warning
        self.assertEqual(["inconsistent details in skipped record: ('b',)"
                          " ('42 32 0 8', ((),)) ('74 32 0 8', ((('a',),),))"],
                         warnings)

    def test_inconsistent_redundant_inserts_raises(self):
        e = self.assertRaises(errors.KnitCorrupt, self.do_inconsistent_inserts,
                              inconsistency_fatal=True)
        self.assertContainsRe(str(e), "Knit.* corrupt: inconsistent details"
                              " in add_records:"
                              " \('b',\) \('42 32 0 8', \(\(\),\)\) \('74 32"
                              " 0 8', \(\(\('a',\),\),\)\)")


class TestLazyGroupCompress(tests.TestCaseWithTransport):

    _texts = {
        ('key1',): "this is a text\n"
                   "with a reasonable amount of compressible bytes\n"
                   "which can be shared between various other texts\n",
        ('key2',): "another text\n"
                   "with a reasonable amount of compressible bytes\n"
                   "which can be shared between various other texts\n",
        ('key3',): "yet another text which won't be extracted\n"
                   "with a reasonable amount of compressible bytes\n"
                   "which can be shared between various other texts\n",
        ('key4',): "this will be extracted\n"
                   "but references most of its bytes from\n"
                   "yet another text which won't be extracted\n"
                   "with a reasonable amount of compressible bytes\n"
                   "which can be shared between various other texts\n",
    }
    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        start = 0
        for key in sorted(key_to_text):
            compressor.compress(key, key_to_text[key], None)
        locs = dict((key, (start, end)) for key, (start, _, end, _)
                    in compressor.labels_deltas.iteritems())
        block = compressor.flush()
        raw_bytes = block.to_bytes()
        return locs, groupcompress.GroupCompressBlock.from_bytes(raw_bytes)

    def add_key_to_manager(self, key, locations, block, manager):
        start, end = locations[key]
        manager.add_factory(key, (), start, end)

    def make_block_and_full_manager(self, texts):
        locations, block = self.make_block(texts)
        manager = groupcompress._LazyGroupContentManager(block)
        for key in sorted(texts):
            self.add_key_to_manager(key, locations, block, manager)
        return block, manager

    def test_get_fulltexts(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key1',), locations, block, manager)
        self.add_key_to_manager(('key2',), locations, block, manager)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as('fulltext'))
        self.assertEqual([('key1',), ('key2',)], result_order)

        # If we build the manager in the opposite order, we should get them
        # back in the opposite order
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key2',), locations, block, manager)
        self.add_key_to_manager(('key1',), locations, block, manager)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as('fulltext'))
        self.assertEqual([('key2',), ('key1',)], result_order)

    def test__wire_bytes_no_keys(self):
        locations, block = self.make_block(self._texts)
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
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key1',), locations, block, manager)
        self.add_key_to_manager(('key4',), locations, block, manager)
        block_bytes = block.to_bytes()
        wire_bytes = manager._wire_bytes()
        (storage_kind, z_header_len, header_len,
         block_len, rest) = wire_bytes.split('\n', 4)
        z_header_len = int(z_header_len)
        header_len = int(header_len)
        block_len = int(block_len)
        self.assertEqual('groupcompress-block', storage_kind)
        self.assertEqual(34, z_header_len)
        self.assertEqual(26, header_len)
        self.assertEqual(len(block_bytes), block_len)
        z_header = rest[:z_header_len]
        header = zlib.decompress(z_header)
        self.assertEqual(header_len, len(header))
        entry1 = locations[('key1',)]
        entry4 = locations[('key4',)]
        self.assertEqualDiff('key1\n'
                             '\n'  # no parents
                             '%d\n' # start offset
                             '%d\n' # end offset
                             'key4\n'
                             '\n'
                             '%d\n'
                             '%d\n'
                             % (entry1[0], entry1[1],
                                entry4[0], entry4[1]),
                            header)
        z_block = rest[z_header_len:]
        self.assertEqual(block_bytes, z_block)

    def test_from_bytes(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager(('key1',), locations, block, manager)
        self.add_key_to_manager(('key4',), locations, block, manager)
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
        block, manager = self.make_block_and_full_manager(self._texts)
        manager._check_rebuild_block()
        self.assertIs(block, manager._block)

    def test__check_rebuild_only_one(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request just the first key, which should trigger a 'strip' action
        self.add_key_to_manager(('key1',), locations, block, manager)
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
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request a small key in the middle should trigger a 'rebuild'
        self.add_key_to_manager(('key4',), locations, block, manager)
        manager._check_rebuild_block()
        self.assertIsNot(block, manager._block)
        self.assertTrue(block._content_length > manager._block._content_length)
        for record in manager.get_record_stream():
            self.assertEqual(('key4',), record.key)
            self.assertEqual(self._texts[record.key],
                             record.get_bytes_as('fulltext'))

    def test_check_is_well_utilized_all_keys(self):
        block, manager = self.make_block_and_full_manager(self._texts)
        self.assertFalse(manager.check_is_well_utilized())
        # Though we can fake it by changing the recommended minimum size
        manager._full_enough_block_size = block._content_length
        self.assertTrue(manager.check_is_well_utilized())
        # Setting it just above causes it to fail
        manager._full_enough_block_size = block._content_length + 1
        self.assertFalse(manager.check_is_well_utilized())
        # Setting the mixed-block size doesn't do anything, because the content
        # is considered to not be 'mixed'
        manager._full_enough_mixed_block_size = block._content_length
        self.assertFalse(manager.check_is_well_utilized())

    def test_check_is_well_utilized_mixed_keys(self):
        texts = {}
        f1k1 = ('f1', 'k1')
        f1k2 = ('f1', 'k2')
        f2k1 = ('f2', 'k1')
        f2k2 = ('f2', 'k2')
        texts[f1k1] = self._texts[('key1',)]
        texts[f1k2] = self._texts[('key2',)]
        texts[f2k1] = self._texts[('key3',)]
        texts[f2k2] = self._texts[('key4',)]
        block, manager = self.make_block_and_full_manager(texts)
        self.assertFalse(manager.check_is_well_utilized())
        manager._full_enough_block_size = block._content_length
        self.assertTrue(manager.check_is_well_utilized())
        manager._full_enough_block_size = block._content_length + 1
        self.assertFalse(manager.check_is_well_utilized())
        manager._full_enough_mixed_block_size = block._content_length
        self.assertTrue(manager.check_is_well_utilized())

    def test_check_is_well_utilized_partial_use(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        manager._full_enough_block_size = block._content_length
        self.add_key_to_manager(('key1',), locations, block, manager)
        self.add_key_to_manager(('key2',), locations, block, manager)
        # Just using the content from key1 and 2 is not enough to be considered
        # 'complete'
        self.assertFalse(manager.check_is_well_utilized())
        # However if we add key3, then we have enough, as we only require 75%
        # consumption
        self.add_key_to_manager(('key4',), locations, block, manager)
        self.assertTrue(manager.check_is_well_utilized())

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

"""Tests for group compression."""

import zlib

from breezy import config, osutils, tests, trace
from breezy.osutils import sha_string
from breezy.tests.scenarios import load_tests_apply_scenarios

from .. import btree_index, groupcompress, knit, versionedfile
from .. import index as _mod_index
from .test__groupcompress import compiled_groupcompress_feature


def group_compress_implementation_scenarios():
    scenarios = [
        ("python", {"compressor": groupcompress.PythonGroupCompressor}),
    ]
    if compiled_groupcompress_feature.available():
        scenarios.append(("C", {"compressor": groupcompress.PyrexGroupCompressor}))
    return scenarios


load_tests = load_tests_apply_scenarios


class TestGroupCompressor(tests.TestCase):
    def _chunks_to_repr_lines(self, chunks):
        return "\n".join(map(repr, b"".join(chunks).split(b"\n")))

    def assertEqualDiffEncoded(self, expected, actual):
        """Compare the actual content to the expected content.

        :param expected: A group of chunks that we expect to see
        :param actual: The measured 'chunks'

        We will transform the chunks back into lines, and then run 'repr()'
        over them to handle non-ascii characters.
        """
        self.assertEqualDiff(
            self._chunks_to_repr_lines(expected), self._chunks_to_repr_lines(actual)
        )


class TestAllGroupCompressors(TestGroupCompressor):
    """Tests for GroupCompressor."""

    scenarios = group_compress_implementation_scenarios()
    compressor = None  # Set by scenario

    def test_empty_delta(self):
        compressor = self.compressor()
        self.assertEqual([], compressor.chunks)

    def test_one_nosha_delta(self):
        # diff against NUKK
        compressor = self.compressor()
        text = b"strange\ncommon\n"
        sha1, start_point, end_point, _ = compressor.compress(
            (b"label",), [text], len(text), None
        )
        self.assertEqual(sha_string(b"strange\ncommon\n"), sha1)
        expected_lines = b"f\x0fstrange\ncommon\n"
        self.assertEqual(expected_lines, b"".join(compressor.chunks))
        self.assertEqual(0, start_point)
        self.assertEqual(len(expected_lines), end_point)

    def test_empty_content(self):
        compressor = self.compressor()
        # Adding empty bytes should return the 'null' record
        sha1, start_point, end_point, kind = compressor.compress(
            (b"empty",), [], 0, None
        )
        self.assertEqual(0, start_point)
        self.assertEqual(0, end_point)
        self.assertEqual("fulltext", kind)
        self.assertEqual(groupcompress._null_sha1, sha1)
        self.assertEqual(0, compressor.endpoint)
        self.assertEqual([], compressor.chunks)
        # Even after adding some content
        text = b"some\nbytes\n"
        compressor.compress((b"content",), [text], len(text), None)
        self.assertGreater(compressor.endpoint, 0)
        sha1, start_point, end_point, kind = compressor.compress(
            (b"empty2",), [], 0, None
        )
        self.assertEqual(0, start_point)
        self.assertEqual(0, end_point)
        self.assertEqual("fulltext", kind)
        self.assertEqual(groupcompress._null_sha1, sha1)

    def test_extract_from_compressor(self):
        # Knit fetching will try to reconstruct texts locally which results in
        # reading something that is in the compressor stream already.
        compressor = self.compressor()
        text = b"strange\ncommon long line\nthat needs a 16 byte match\n"
        sha1_1, _, _, _ = compressor.compress((b"label",), [text], len(text), None)
        list(compressor.chunks)
        text = b"common long line\nthat needs a 16 byte match\ndifferent\n"
        sha1_2, _, end_point, _ = compressor.compress(
            (b"newlabel",), [text], len(text), None
        )
        # get the first out
        self.assertEqual(
            ([b"strange\ncommon long line\nthat needs a 16 byte match\n"], sha1_1),
            compressor.extract((b"label",)),
        )
        # and the second
        self.assertEqual(
            (
                [b"common long line\nthat needs a 16 byte match\ndifferent\n"],
                sha1_2,
            ),
            compressor.extract((b"newlabel",)),
        )


class TestPyrexGroupCompressor(TestGroupCompressor):
    _test_needs_features = [compiled_groupcompress_feature]
    compressor = groupcompress.PyrexGroupCompressor

    def test_stats(self):
        compressor = self.compressor()
        chunks = [b"strange\n", b"common very very long line\n", b"plus more text\n"]
        compressor.compress((b"label",), chunks, sum(map(len, chunks)), None)
        chunks = [
            b"common very very long line\n",
            b"plus more text\n",
            b"different\n",
            b"moredifferent\n",
        ]
        compressor.compress((b"newlabel",), chunks, sum(map(len, chunks)), None)
        chunks = [
            b"new\n",
            b"common very very long line\n",
            b"plus more text\n",
            b"different\n",
            b"moredifferent\n",
        ]
        compressor.compress((b"label3",), chunks, sum(map(len, chunks)), None)
        self.assertAlmostEqual(1.9, compressor.ratio(), 1)

    def test_two_nosha_delta(self):
        compressor = self.compressor()
        text = b"strange\ncommon long line\nthat needs a 16 byte match\n"
        sha1_1, _, _, _ = compressor.compress((b"label",), [text], len(text), None)
        expected_lines = list(compressor.chunks)
        text = b"common long line\nthat needs a 16 byte match\ndifferent\n"
        sha1_2, start_point, end_point, _ = compressor.compress(
            (b"newlabel",), [text], len(text), None
        )
        self.assertEqual(sha_string(text), sha1_2)
        expected_lines.extend(
            [
                # 'delta', delta length
                b"d\x0f",
                # source and target length
                b"\x36",
                # copy the line common
                b"\x91\x0a\x2c",  # copy, offset 0x0a, len 0x2c
                # add the line different, and the trailing newline
                b"\x0adifferent\n",  # insert 10 bytes
            ]
        )
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = self.compressor()
        text = b"strange\ncommon very very long line\nwith some extra text\n"
        sha1_1, _, _, _ = compressor.compress((b"label",), [text], len(text), None)
        text = b"different\nmoredifferent\nand then some more\n"
        sha1_2, _, _, _ = compressor.compress((b"newlabel",), [text], len(text), None)
        expected_lines = list(compressor.chunks)
        text = (
            b"new\ncommon very very long line\nwith some extra text\n"
            b"different\nmoredifferent\nand then some more\n"
        )
        sha1_3, start_point, end_point, _ = compressor.compress(
            (b"label3",), [text], len(text), None
        )
        self.assertEqual(sha_string(text), sha1_3)
        expected_lines.extend(
            [
                # 'delta', delta length
                b"d\x0b",
                # source and target length
                b"\x5f"
                # insert new
                b"\x03new",
                # Copy of first parent 'common' range
                b"\x91\x09\x31"  # copy, offset 0x09, 0x31 bytes
                # Copy of second parent 'different' range
                b"\x91\x3c\x2b",  # copy, offset 0x3c, 0x2b bytes
            ]
        )
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)


class TestPythonGroupCompressor(TestGroupCompressor):
    compressor = groupcompress.PythonGroupCompressor

    def test_stats(self):
        compressor = self.compressor()
        chunks = [b"strange\n", b"common very very long line\n", b"plus more text\n"]
        compressor.compress((b"label",), chunks, sum(map(len, chunks)), None)
        chunks = [
            b"common very very long line\n",
            b"plus more text\n",
            b"different\n",
            b"moredifferent\n",
        ]
        compressor.compress((b"newlabel",), chunks, sum(map(len, chunks)), None)
        chunks = [
            b"new\n",
            b"common very very long line\n",
            b"plus more text\n",
            b"different\n",
            b"moredifferent\n",
        ]
        compressor.compress((b"label3",), chunks, sum(map(len, chunks)), None)
        self.assertAlmostEqual(1.9, compressor.ratio(), 1)

    def test_two_nosha_delta(self):
        compressor = self.compressor()
        text = b"strange\ncommon long line\nthat needs a 16 byte match\n"
        sha1_1, _, _, _ = compressor.compress((b"label",), [text], len(text), None)
        expected_lines = list(compressor.chunks)
        text = b"common long line\nthat needs a 16 byte match\ndifferent\n"
        sha1_2, start_point, end_point, _ = compressor.compress(
            (b"newlabel",), [text], len(text), None
        )
        self.assertEqual(sha_string(text), sha1_2)
        expected_lines.extend(
            [
                # 'delta', delta length
                b"d\x0f",
                # target length
                b"\x36",
                # copy the line common
                b"\x91\x0a\x2c",  # copy, offset 0x0a, len 0x2c
                # add the line different, and the trailing newline
                b"\x0adifferent\n",  # insert 10 bytes
            ]
        )
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = self.compressor()
        text = b"strange\ncommon very very long line\nwith some extra text\n"
        sha1_1, _, _, _ = compressor.compress((b"label",), [text], len(text), None)
        text = b"different\nmoredifferent\nand then some more\n"
        sha1_2, _, _, _ = compressor.compress((b"newlabel",), [text], len(text), None)
        expected_lines = list(compressor.chunks)
        text = (
            b"new\ncommon very very long line\nwith some extra text\n"
            b"different\nmoredifferent\nand then some more\n"
        )
        sha1_3, start_point, end_point, _ = compressor.compress(
            (b"label3",), [text], len(text), None
        )
        self.assertEqual(sha_string(text), sha1_3)
        expected_lines.extend(
            [
                # 'delta', delta length
                b"d\x0c",
                # target length
                b"\x5f"
                # insert new
                b"\x04new\n",
                # Copy of first parent 'common' range
                b"\x91\x0a\x30"  # copy, offset 0x0a, 0x30 bytes
                # Copy of second parent 'different' range
                b"\x91\x3c\x2b",  # copy, offset 0x3c, 0x2b bytes
            ]
        )
        self.assertEqualDiffEncoded(expected_lines, compressor.chunks)
        self.assertEqual(sum(map(len, expected_lines)), end_point)


class TestGroupCompressBlock(tests.TestCase):
    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        for key in sorted(key_to_text):
            compressor.compress(key, [key_to_text[key]], len(key_to_text[key]), None)
        locs = {
            key: (start, end)
            for key, (start, _, end, _) in compressor.labels_deltas.items()
        }
        block = compressor.flush()
        raw_bytes = block.to_bytes()
        # Go through from_bytes(to_bytes()) so that we start with a compressed
        # content object
        return locs, groupcompress.GroupCompressBlock.from_bytes(raw_bytes)

    def test_from_empty_bytes(self):
        self.assertRaises(ValueError, groupcompress.GroupCompressBlock.from_bytes, b"")

    def test_from_minimal_bytes(self):
        block = groupcompress.GroupCompressBlock.from_bytes(b"gcb1z\n0\n0\n")
        self.assertIsInstance(block, groupcompress.GroupCompressBlock)
        self.assertIs(None, block._content)
        self.assertEqual(b"", block._z_content)
        block._ensure_content()
        self.assertEqual(b"", block._content)
        self.assertEqual(b"", block._z_content)
        block._ensure_content()  # Ensure content is safe to call 2x

    def test_from_invalid(self):
        self.assertRaises(
            ValueError,
            groupcompress.GroupCompressBlock.from_bytes,
            b"this is not a valid header",
        )

    def test_from_bytes(self):
        content = b"a tiny bit of content\n"
        z_content = zlib.compress(content)
        z_bytes = (
            b"gcb1z\n"  # group compress block v1 plain
            b"%d\n"  # Length of compressed content
            b"%d\n"  # Length of uncompressed content
            b"%s"  # Compressed content
        ) % (len(z_content), len(content), z_content)
        block = groupcompress.GroupCompressBlock.from_bytes(z_bytes)
        self.assertEqual(z_content, block._z_content)
        self.assertIs(None, block._content)
        self.assertEqual(len(z_content), block._z_content_length)
        self.assertEqual(len(content), block._content_length)
        block._ensure_content()
        self.assertEqual(z_content, block._z_content)
        self.assertEqual(content, block._content)

    def test_to_chunks(self):
        content_chunks = [
            b"this is some content\n",
            b"this content will be compressed\n",
        ]
        content_len = sum(map(len, content_chunks))
        content = b"".join(content_chunks)
        gcb = groupcompress.GroupCompressBlock()
        gcb.set_chunked_content(content_chunks, content_len)
        total_len, block_chunks = gcb.to_chunks()
        block_bytes = b"".join(block_chunks)
        self.assertEqual(gcb._z_content_length, len(gcb._z_content))
        self.assertEqual(total_len, len(block_bytes))
        self.assertEqual(gcb._content_length, content_len)
        expected_header = (
            b"gcb1z\n"  # group compress block v1 zlib
            b"%d\n"  # Length of compressed content
            b"%d\n"  # Length of uncompressed content
        ) % (gcb._z_content_length, gcb._content_length)
        # The first chunk should be the header chunk. It is small, fixed size,
        # and there is no compelling reason to split it up
        self.assertEqual(expected_header, block_chunks[0])
        self.assertStartsWith(block_bytes, expected_header)
        remaining_bytes = block_bytes[len(expected_header) :]
        raw_bytes = zlib.decompress(remaining_bytes)
        self.assertEqual(content, raw_bytes)

    def test_to_bytes(self):
        content = b"this is some content\nthis content will be compressed\n"
        gcb = groupcompress.GroupCompressBlock()
        gcb.set_content(content)
        data = gcb.to_bytes()
        self.assertEqual(gcb._z_content_length, len(gcb._z_content))
        self.assertEqual(gcb._content_length, len(content))
        expected_header = (
            b"gcb1z\n"  # group compress block v1 zlib
            b"%d\n"  # Length of compressed content
            b"%d\n"  # Length of uncompressed content
        ) % (gcb._z_content_length, gcb._content_length)
        self.assertStartsWith(data, expected_header)
        remaining_bytes = data[len(expected_header) :]
        raw_bytes = zlib.decompress(remaining_bytes)
        self.assertEqual(content, raw_bytes)

        # we should get the same results if using the chunked version
        gcb = groupcompress.GroupCompressBlock()
        gcb.set_chunked_content(
            [b"this is some content\nthis content will be compressed\n"],
            len(content),
        )
        old_data = data
        data = gcb.to_bytes()
        self.assertEqual(old_data, data)

    def test_partial_decomp(self):
        content_chunks = []
        # We need a sufficient amount of data so that zlib.decompress has
        # partial decompression to work with. Most auto-generated data
        # compresses a bit too well, we want a combination, so we combine a sha
        # hash with compressible data.
        for i in range(2048):
            next_content = b"%d\nThis is a bit of duplicate text\n" % (i,)
            content_chunks.append(next_content)
            next_sha1 = osutils.sha_string(next_content)
            content_chunks.append(next_sha1 + b"\n")
        content = b"".join(content_chunks)
        self.assertEqual(158634, len(content))
        z_content = zlib.compress(content)
        self.assertEqual(57182, len(z_content))
        block = groupcompress.GroupCompressBlock()
        block._z_content_chunks = (z_content,)
        block._z_content_length = len(z_content)
        block._compressor_name = "zlib"
        block._content_length = 158634
        self.assertIs(None, block._content)
        block._ensure_content(100)
        self.assertIsNot(None, block._content)
        # We have decompressed at least 100 bytes
        self.assertGreaterEqual(len(block._content), 100)
        # We have not decompressed the whole content
        self.assertLess(len(block._content), 158634)
        self.assertEqualDiff(content[: len(block._content)], block._content)
        # ensuring content that we already have shouldn't cause any more data
        # to be extracted
        cur_len = len(block._content)
        block._ensure_content(cur_len - 10)
        self.assertEqual(cur_len, len(block._content))
        # Now we want a bit more content
        cur_len += 10
        block._ensure_content(cur_len)
        self.assertGreaterEqual(len(block._content), cur_len)
        self.assertLess(len(block._content), 158634)
        self.assertEqualDiff(content[: len(block._content)], block._content)
        # And now lets finish
        block._ensure_content(158634)
        self.assertEqualDiff(content, block._content)
        # And the decompressor is finalized
        self.assertIs(None, block._z_content_decompressor)

    def test__ensure_all_content(self):
        content_chunks = []
        # We need a sufficient amount of data so that zlib.decompress has
        # partial decompression to work with. Most auto-generated data
        # compresses a bit too well, we want a combination, so we combine a sha
        # hash with compressible data.
        for i in range(2048):
            next_content = b"%d\nThis is a bit of duplicate text\n" % (i,)
            content_chunks.append(next_content)
            next_sha1 = osutils.sha_string(next_content)
            content_chunks.append(next_sha1 + b"\n")
        content = b"".join(content_chunks)
        self.assertEqual(158634, len(content))
        z_content = zlib.compress(content)
        self.assertEqual(57182, len(z_content))
        block = groupcompress.GroupCompressBlock()
        block._z_content_chunks = (z_content,)
        block._z_content_length = len(z_content)
        block._compressor_name = "zlib"
        block._content_length = 158634
        self.assertIs(None, block._content)
        # The first _ensure_content got all of the required data
        block._ensure_content(158634)
        self.assertEqualDiff(content, block._content)
        # And we should have released the _z_content_decompressor since it was
        # fully consumed
        self.assertIs(None, block._z_content_decompressor)

    def test__dump(self):
        dup_content = b"some duplicate content\nwhich is sufficiently long\n"
        key_to_text = {
            (b"1",): dup_content + b"1 unique\n",
            (b"2",): dup_content + b"2 extra special\n",
        }
        locs, block = self.make_block(key_to_text)
        self.assertEqual(
            [
                (b"f", len(key_to_text[(b"1",)])),
                (
                    b"d",
                    21,
                    len(key_to_text[(b"2",)]),
                    [
                        (b"c", 2, len(dup_content)),
                        (b"i", len(b"2 extra special\n"), b""),
                    ],
                ),
            ],
            block._dump(),
        )


class TestCaseWithGroupCompressVersionedFiles(tests.TestCaseWithMemoryTransport):
    def make_test_vf(
        self,
        create_graph,
        keylength=1,
        do_cleanup=True,
        dir=".",
        inconsistency_fatal=True,
    ):
        t = self.get_transport(dir)
        t.ensure_base()
        vf = groupcompress.make_pack_factory(
            graph=create_graph,
            delta=False,
            keylength=keylength,
            inconsistency_fatal=inconsistency_fatal,
        )(t)
        if do_cleanup:
            self.addCleanup(groupcompress.cleanup_pack_group, vf)
        return vf


class TestGroupCompressVersionedFiles(TestCaseWithGroupCompressVersionedFiles):
    def make_g_index(self, name, ref_lists=0, nodes=None):
        if nodes is None:
            nodes = []
        builder = btree_index.BTreeBuilder(ref_lists)
        for node, references, value in nodes:
            builder.add_node(node, references, value)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return btree_index.BTreeGraphIndex(trans, name, size)

    def make_g_index_missing_parent(self):
        graph_index = self.make_g_index(
            "missing_parent",
            1,
            [
                ((b"parent",), b"2 78 2 10", ([],)),
                ((b"tip",), b"2 78 2 10", ([(b"parent",), (b"missing-parent",)],)),
            ],
        )
        return graph_index

    def test_get_record_stream_as_requested(self):
        # Consider promoting 'as-requested' to general availability, and
        # make this a VF interface test
        vf = self.make_test_vf(False, dir="source")
        vf.add_lines((b"a",), (), [b"lines\n"])
        vf.add_lines((b"b",), (), [b"lines\n"])
        vf.add_lines((b"c",), (), [b"lines\n"])
        vf.add_lines((b"d",), (), [b"lines\n"])
        vf.writer.end()
        keys = [
            record.key
            for record in vf.get_record_stream(
                [(b"a",), (b"b",), (b"c",), (b"d",)], "as-requested", False
            )
        ]
        self.assertEqual([(b"a",), (b"b",), (b"c",), (b"d",)], keys)
        keys = [
            record.key
            for record in vf.get_record_stream(
                [(b"b",), (b"a",), (b"d",), (b"c",)], "as-requested", False
            )
        ]
        self.assertEqual([(b"b",), (b"a",), (b"d",), (b"c",)], keys)

        # It should work even after being repacked into another VF
        vf2 = self.make_test_vf(False, dir="target")
        vf2.insert_record_stream(
            vf.get_record_stream(
                [(b"b",), (b"a",), (b"d",), (b"c",)], "as-requested", False
            )
        )
        vf2.writer.end()

        keys = [
            record.key
            for record in vf2.get_record_stream(
                [(b"a",), (b"b",), (b"c",), (b"d",)], "as-requested", False
            )
        ]
        self.assertEqual([(b"a",), (b"b",), (b"c",), (b"d",)], keys)
        keys = [
            record.key
            for record in vf2.get_record_stream(
                [(b"b",), (b"a",), (b"d",), (b"c",)], "as-requested", False
            )
        ]
        self.assertEqual([(b"b",), (b"a",), (b"d",), (b"c",)], keys)

    def test_get_record_stream_max_bytes_to_index_default(self):
        vf = self.make_test_vf(True, dir="source")
        vf.add_lines((b"a",), (), [b"lines\n"])
        vf.writer.end()
        record = next(vf.get_record_stream([(b"a",)], "unordered", True))
        self.assertEqual(
            vf._DEFAULT_COMPRESSOR_SETTINGS, record._manager._get_compressor_settings()
        )

    def test_get_record_stream_accesses_compressor_settings(self):
        vf = self.make_test_vf(True, dir="source")
        vf.add_lines((b"a",), (), [b"lines\n"])
        vf.writer.end()
        vf._max_bytes_to_index = 1234
        record = next(vf.get_record_stream([(b"a",)], "unordered", True))
        self.assertEqual(
            {"max_bytes_to_index": 1234}, record._manager._get_compressor_settings()
        )

    @staticmethod
    def grouped_stream(revision_ids, first_parents=()):
        parents = first_parents
        for revision_id in revision_ids:
            key = (revision_id,)
            record = versionedfile.FulltextContentFactory(
                key,
                parents,
                None,
                b"some content that is\n"
                b"identical except for\n"
                b"revision_id:%s\n" % (revision_id,),
            )
            yield record
            parents = (key,)

    def test_insert_record_stream_reuses_blocks(self):
        vf = self.make_test_vf(True, dir="source")
        # One group, a-d
        vf.insert_record_stream(self.grouped_stream([b"a", b"b", b"c", b"d"]))
        # Second group, e-h
        vf.insert_record_stream(
            self.grouped_stream([b"e", b"f", b"g", b"h"], first_parents=((b"d",),))
        )
        block_bytes = {}
        stream = vf.get_record_stream(
            [(r.encode(),) for r in "abcdefgh"], "unordered", False
        )
        num_records = 0
        for record in stream:
            if record.key in [(b"a",), (b"e",)]:
                self.assertEqual("groupcompress-block", record.storage_kind)
            else:
                self.assertEqual("groupcompress-block-ref", record.storage_kind)
            block_bytes[record.key] = record._manager._block._z_content
            num_records += 1
        self.assertEqual(8, num_records)
        for r in "abcd":
            key = (r.encode(),)
            self.assertIs(block_bytes[key], block_bytes[(b"a",)])
            self.assertNotEqual(block_bytes[key], block_bytes[(b"e",)])
        for r in "efgh":
            key = (r.encode(),)
            self.assertIs(block_bytes[key], block_bytes[(b"e",)])
            self.assertNotEqual(block_bytes[key], block_bytes[(b"a",)])
        # Now copy the blocks into another vf, and ensure that the blocks are
        # preserved without creating new entries
        vf2 = self.make_test_vf(True, dir="target")
        keys = [(r.encode(),) for r in "abcdefgh"]
        # ordering in 'groupcompress' order, should actually swap the groups in
        # the target vf, but the groups themselves should not be disturbed.

        def small_size_stream():
            for record in vf.get_record_stream(keys, "groupcompress", False):
                record._manager._full_enough_block_size = (
                    record._manager._block._content_length
                )
                yield record

        vf2.insert_record_stream(small_size_stream())
        stream = vf2.get_record_stream(keys, "groupcompress", False)
        vf2.writer.end()
        num_records = 0
        for record in stream:
            num_records += 1
            self.assertEqual(block_bytes[record.key], record._manager._block._z_content)
        self.assertEqual(8, num_records)

    def test_insert_record_stream_packs_on_the_fly(self):
        vf = self.make_test_vf(True, dir="source")
        # One group, a-d
        vf.insert_record_stream(self.grouped_stream([b"a", b"b", b"c", b"d"]))
        # Second group, e-h
        vf.insert_record_stream(
            self.grouped_stream([b"e", b"f", b"g", b"h"], first_parents=((b"d",),))
        )
        # Now copy the blocks into another vf, and see that the
        # insert_record_stream rebuilt a new block on-the-fly because of
        # under-utilization
        vf2 = self.make_test_vf(True, dir="target")
        keys = [(r.encode(),) for r in "abcdefgh"]
        vf2.insert_record_stream(vf.get_record_stream(keys, "groupcompress", False))
        stream = vf2.get_record_stream(keys, "groupcompress", False)
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
        vf = self.make_test_vf(True, dir="source")
        # One group, a-d
        vf.insert_record_stream(self.grouped_stream([b"a", b"b", b"c", b"d"]))
        # Second group, e-h
        vf.insert_record_stream(
            self.grouped_stream([b"e", b"f", b"g", b"h"], first_parents=((b"d",),))
        )
        vf.writer.end()
        keys = [(r.encode(),) for r in "abcdefgh"]
        self.assertEqual(8, len(list(vf.get_record_stream(keys, "unordered", False))))
        # Now copy the blocks into another vf, and ensure that the blocks are
        # preserved without creating new entries
        vf2 = self.make_test_vf(True, dir="target")
        # ordering in 'groupcompress' order, should actually swap the groups in
        # the target vf, but the groups themselves should not be disturbed.
        list(
            vf2._insert_record_stream(
                vf.get_record_stream(keys, "groupcompress", False), reuse_blocks=False
            )
        )
        vf2.writer.end()
        # After inserting with reuse_blocks=False, we should have everything in
        # a single new block.
        stream = vf2.get_record_stream(keys, "groupcompress", False)
        block = None
        for record in stream:
            if block is None:
                block = record._manager._block
            else:
                self.assertIs(block, record._manager._block)

    def test_add_missing_noncompression_parent_unvalidated_index(self):
        unvalidated = self.make_g_index_missing_parent()
        combined = _mod_index.CombinedGraphIndex([unvalidated])
        index = groupcompress._GCGraphIndex(
            combined,
            is_locked=lambda: True,
            parents=True,
            track_external_parent_refs=True,
        )
        index.scan_unvalidated_index(unvalidated)
        self.assertEqual(frozenset([(b"missing-parent",)]), index.get_missing_parents())

    def test_track_external_parent_refs(self):
        g_index = self.make_g_index("empty", 1, [])
        mod_index = btree_index.BTreeBuilder(1, 1)
        combined = _mod_index.CombinedGraphIndex([g_index, mod_index])
        index = groupcompress._GCGraphIndex(
            combined,
            is_locked=lambda: True,
            parents=True,
            add_callback=mod_index.add_nodes,
            track_external_parent_refs=True,
        )
        index.add_records(
            [((b"new-key",), b"2 10 2 10", [((b"parent-1",), (b"parent-2",))])]
        )
        self.assertEqual(
            frozenset([(b"parent-1",), (b"parent-2",)]), index.get_missing_parents()
        )

    def make_source_with_b(self, a_parent, path):
        source = self.make_test_vf(True, dir=path)
        source.add_lines((b"a",), (), [b"lines\n"])
        b_parents = ((b"a",),) if a_parent else ()
        source.add_lines((b"b",), b_parents, [b"lines\n"])
        return source

    def do_inconsistent_inserts(self, inconsistency_fatal):
        target = self.make_test_vf(
            True, dir="target", inconsistency_fatal=inconsistency_fatal
        )
        for x in range(2):
            source = self.make_source_with_b(x == 1, f"source{x}")
            target.insert_record_stream(
                source.get_record_stream([(b"b",)], "unordered", False)
            )

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
        self.assertContainsRe(
            "\n".join(warnings),
            r"^inconsistent details in skipped record: \(b?'b',\)"
            r" \(b?'42 32 0 8', \(\(\),\)\)"
            r" \(b?'74 32 0 8', \(\(\(b?'a',\),\),\)\)$",
        )

    def test_inconsistent_redundant_inserts_raises(self):
        e = self.assertRaises(
            knit.KnitCorrupt, self.do_inconsistent_inserts, inconsistency_fatal=True
        )
        self.assertContainsRe(
            str(e),
            r"Knit.* corrupt: inconsistent details"
            r" in add_records:"
            r" \(b?'b',\) \(b?'42 32 0 8', \(\(\),\)\)"
            r" \(b?'74 32 0 8', \(\(\(b?'a',\),\),\)\)",
        )

    def test_clear_cache(self):
        vf = self.make_source_with_b(True, "source")
        vf.writer.end()
        for _record in vf.get_record_stream([(b"a",), (b"b",)], "unordered", True):
            pass
        self.assertGreater(len(vf._group_cache), 0)
        vf.clear_cache()
        self.assertEqual(0, len(vf._group_cache))


class TestGroupCompressConfig(tests.TestCaseWithTransport):
    def make_test_vf(self):
        t = self.get_transport(".")
        t.ensure_base()
        factory = groupcompress.make_pack_factory(
            graph=True, delta=False, keylength=1, inconsistency_fatal=True
        )
        vf = factory(t)
        self.addCleanup(groupcompress.cleanup_pack_group, vf)
        return vf

    def test_max_bytes_to_index_default(self):
        vf = self.make_test_vf()
        gc = vf._make_group_compressor()
        self.assertEqual(vf._DEFAULT_MAX_BYTES_TO_INDEX, vf._max_bytes_to_index)
        if isinstance(gc, groupcompress.PyrexGroupCompressor):
            self.assertEqual(
                vf._DEFAULT_MAX_BYTES_TO_INDEX, gc._delta_index._max_bytes_to_index
            )

    def test_max_bytes_to_index_in_config(self):
        c = config.GlobalConfig()
        c.set_user_option("bzr.groupcompress.max_bytes_to_index", "10000")
        vf = self.make_test_vf()
        gc = vf._make_group_compressor()
        self.assertEqual(10000, vf._max_bytes_to_index)
        if isinstance(gc, groupcompress.PyrexGroupCompressor):
            self.assertEqual(10000, gc._delta_index._max_bytes_to_index)

    def test_max_bytes_to_index_bad_config(self):
        c = config.GlobalConfig()
        c.set_user_option("bzr.groupcompress.max_bytes_to_index", "boogah")
        vf = self.make_test_vf()
        # TODO: This is triggering a warning, we might want to trap and make
        #       sure it is readable.
        gc = vf._make_group_compressor()
        self.assertEqual(vf._DEFAULT_MAX_BYTES_TO_INDEX, vf._max_bytes_to_index)
        if isinstance(gc, groupcompress.PyrexGroupCompressor):
            self.assertEqual(
                vf._DEFAULT_MAX_BYTES_TO_INDEX, gc._delta_index._max_bytes_to_index
            )


class StubGCVF:
    def __init__(self, canned_get_blocks=None):
        self._group_cache = {}
        self._canned_get_blocks = canned_get_blocks or []

    def _get_blocks(self, read_memos):
        return iter(self._canned_get_blocks)


class Test_BatchingBlockFetcher(TestCaseWithGroupCompressVersionedFiles):
    """Simple whitebox unit tests for _BatchingBlockFetcher."""

    def test_add_key_new_read_memo(self):
        """Adding a key with an uncached read_memo new to this batch adds that
        read_memo to the list of memos to fetch.
        """
        # locations are: index_memo, ignored, parents, ignored
        # where index_memo is: (idx, offset, len, factory_start, factory_end)
        # and (idx, offset, size) is known as the 'read_memo', identifying the
        # raw bytes needed.
        read_memo = ("fake index", 100, 50)
        locations = {("key",): (read_memo + (None, None), None, None, None)}
        batcher = groupcompress._BatchingBlockFetcher(StubGCVF(), locations)
        total_size = batcher.add_key(("key",))
        self.assertEqual(50, total_size)
        self.assertEqual([("key",)], batcher.keys)
        self.assertEqual([read_memo], batcher.memos_to_get)

    def test_add_key_duplicate_read_memo(self):
        """read_memos that occur multiple times in a batch will only be fetched
        once.
        """
        read_memo = ("fake index", 100, 50)
        # Two keys, both sharing the same read memo (but different overall
        # index_memos).
        locations = {
            ("key1",): (read_memo + (0, 1), None, None, None),
            ("key2",): (read_memo + (1, 2), None, None, None),
        }
        batcher = groupcompress._BatchingBlockFetcher(StubGCVF(), locations)
        total_size = batcher.add_key(("key1",))
        total_size = batcher.add_key(("key2",))
        self.assertEqual(50, total_size)
        self.assertEqual([("key1",), ("key2",)], batcher.keys)
        self.assertEqual([read_memo], batcher.memos_to_get)

    def test_add_key_cached_read_memo(self):
        """Adding a key with a cached read_memo will not cause that read_memo
        to be added to the list to fetch.
        """
        read_memo = ("fake index", 100, 50)
        gcvf = StubGCVF()
        gcvf._group_cache[read_memo] = "fake block"
        locations = {("key",): (read_memo + (None, None), None, None, None)}
        batcher = groupcompress._BatchingBlockFetcher(gcvf, locations)
        total_size = batcher.add_key(("key",))
        self.assertEqual(0, total_size)
        self.assertEqual([("key",)], batcher.keys)
        self.assertEqual([], batcher.memos_to_get)

    def test_yield_factories_empty(self):
        """An empty batch yields no factories."""
        batcher = groupcompress._BatchingBlockFetcher(StubGCVF(), {})
        self.assertEqual([], list(batcher.yield_factories()))

    def test_yield_factories_calls_get_blocks(self):
        """Uncached memos are retrieved via get_blocks."""
        read_memo1 = ("fake index", 100, 50)
        read_memo2 = ("fake index", 150, 40)
        gcvf = StubGCVF(
            canned_get_blocks=[
                (read_memo1, groupcompress.GroupCompressBlock()),
                (read_memo2, groupcompress.GroupCompressBlock()),
            ]
        )
        locations = {
            ("key1",): (read_memo1 + (0, 0), None, None, None),
            ("key2",): (read_memo2 + (0, 0), None, None, None),
        }
        batcher = groupcompress._BatchingBlockFetcher(gcvf, locations)
        batcher.add_key(("key1",))
        batcher.add_key(("key2",))
        factories = list(batcher.yield_factories(full_flush=True))
        self.assertLength(2, factories)
        keys = [f.key for f in factories]
        kinds = [f.storage_kind for f in factories]
        self.assertEqual([("key1",), ("key2",)], keys)
        self.assertEqual(["groupcompress-block", "groupcompress-block"], kinds)

    def test_yield_factories_flushing(self):
        """yield_factories holds back on yielding results from the final block
        unless passed full_flush=True.
        """
        fake_block = groupcompress.GroupCompressBlock()
        read_memo = ("fake index", 100, 50)
        gcvf = StubGCVF()
        gcvf._group_cache[read_memo] = fake_block
        locations = {("key",): (read_memo + (0, 0), None, None, None)}
        batcher = groupcompress._BatchingBlockFetcher(gcvf, locations)
        batcher.add_key(("key",))
        self.assertEqual([], list(batcher.yield_factories()))
        factories = list(batcher.yield_factories(full_flush=True))
        self.assertLength(1, factories)
        self.assertEqual(("key",), factories[0].key)
        self.assertEqual("groupcompress-block", factories[0].storage_kind)


class TestLazyGroupCompress(tests.TestCaseWithTransport):
    _texts = {
        (b"key1",): b"this is a text\n"
        b"with a reasonable amount of compressible bytes\n"
        b"which can be shared between various other texts\n",
        (b"key2",): b"another text\n"
        b"with a reasonable amount of compressible bytes\n"
        b"which can be shared between various other texts\n",
        (b"key3",): b"yet another text which won't be extracted\n"
        b"with a reasonable amount of compressible bytes\n"
        b"which can be shared between various other texts\n",
        (b"key4",): b"this will be extracted\n"
        b"but references most of its bytes from\n"
        b"yet another text which won't be extracted\n"
        b"with a reasonable amount of compressible bytes\n"
        b"which can be shared between various other texts\n",
    }

    def make_block(self, key_to_text):
        """Create a GroupCompressBlock, filling it with the given texts."""
        compressor = groupcompress.GroupCompressor()
        for key in sorted(key_to_text):
            compressor.compress(key, [key_to_text[key]], len(key_to_text[key]), None)
        locs = {
            key: (start, end)
            for key, (start, _, end, _) in compressor.labels_deltas.items()
        }
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
        self.add_key_to_manager((b"key1",), locations, block, manager)
        self.add_key_to_manager((b"key2",), locations, block, manager)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as("fulltext"))
        self.assertEqual([(b"key1",), (b"key2",)], result_order)

        # If we build the manager in the opposite order, we should get them
        # back in the opposite order
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager((b"key2",), locations, block, manager)
        self.add_key_to_manager((b"key1",), locations, block, manager)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as("fulltext"))
        self.assertEqual([(b"key2",), (b"key1",)], result_order)

    def test__wire_bytes_no_keys(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        wire_bytes = manager._wire_bytes()
        block_length = len(block.to_bytes())
        # We should have triggered a strip, since we aren't using any content
        stripped_block = manager._block.to_bytes()
        self.assertGreater(block_length, len(stripped_block))
        empty_z_header = zlib.compress(b"")
        self.assertEqual(
            b"groupcompress-block\n"
            b"8\n"  # len(compress(''))
            b"0\n"  # len('')
            b"%d\n"  # compressed block len
            b"%s"  # zheader
            b"%s" % (len(stripped_block), empty_z_header, stripped_block),  # block
            wire_bytes,
        )

    def test__wire_bytes(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager((b"key1",), locations, block, manager)
        self.add_key_to_manager((b"key4",), locations, block, manager)
        block_bytes = block.to_bytes()
        wire_bytes = manager._wire_bytes()
        (storage_kind, z_header_len, header_len, block_len, rest) = wire_bytes.split(
            b"\n", 4
        )
        z_header_len = int(z_header_len)
        header_len = int(header_len)
        block_len = int(block_len)
        self.assertEqual(b"groupcompress-block", storage_kind)
        self.assertEqual(34, z_header_len)
        self.assertEqual(26, header_len)
        self.assertEqual(len(block_bytes), block_len)
        z_header = rest[:z_header_len]
        header = zlib.decompress(z_header)
        self.assertEqual(header_len, len(header))
        entry1 = locations[(b"key1",)]
        entry4 = locations[(b"key4",)]
        self.assertEqualDiff(
            b"key1\n"
            b"\n"  # no parents
            b"%d\n"  # start offset
            b"%d\n"  # end offset
            b"key4\n"
            b"\n"
            b"%d\n"
            b"%d\n" % (entry1[0], entry1[1], entry4[0], entry4[1]),
            header,
        )
        z_block = rest[z_header_len:]
        self.assertEqual(block_bytes, z_block)

    def test_from_bytes(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        self.add_key_to_manager((b"key1",), locations, block, manager)
        self.add_key_to_manager((b"key4",), locations, block, manager)
        wire_bytes = manager._wire_bytes()
        self.assertStartsWith(wire_bytes, b"groupcompress-block\n")
        manager = groupcompress._LazyGroupContentManager.from_bytes(wire_bytes)
        self.assertIsInstance(manager, groupcompress._LazyGroupContentManager)
        self.assertEqual(2, len(manager._factories))
        self.assertEqual(block._z_content, manager._block._z_content)
        result_order = []
        for record in manager.get_record_stream():
            result_order.append(record.key)
            text = self._texts[record.key]
            self.assertEqual(text, record.get_bytes_as("fulltext"))
        self.assertEqual([(b"key1",), (b"key4",)], result_order)

    def test__check_rebuild_no_changes(self):
        block, manager = self.make_block_and_full_manager(self._texts)
        manager._check_rebuild_block()
        self.assertIs(block, manager._block)

    def test__check_rebuild_only_one(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request just the first key, which should trigger a 'strip' action
        self.add_key_to_manager((b"key1",), locations, block, manager)
        manager._check_rebuild_block()
        self.assertIsNot(block, manager._block)
        self.assertGreater(block._content_length, manager._block._content_length)
        # We should be able to still get the content out of this block, though
        # it should only have 1 entry
        for record in manager.get_record_stream():
            self.assertEqual((b"key1",), record.key)
            self.assertEqual(self._texts[record.key], record.get_bytes_as("fulltext"))

    def test__check_rebuild_middle(self):
        locations, block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(block)
        # Request a small key in the middle should trigger a 'rebuild'
        self.add_key_to_manager((b"key4",), locations, block, manager)
        manager._check_rebuild_block()
        self.assertIsNot(block, manager._block)
        self.assertGreater(block._content_length, manager._block._content_length)
        for record in manager.get_record_stream():
            self.assertEqual((b"key4",), record.key)
            self.assertEqual(self._texts[record.key], record.get_bytes_as("fulltext"))

    def test_manager_default_compressor_settings(self):
        locations, old_block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(old_block)
        gcvf = groupcompress.GroupCompressVersionedFiles
        # It doesn't greedily evaluate _max_bytes_to_index
        self.assertIs(None, manager._compressor_settings)
        self.assertEqual(
            gcvf._DEFAULT_COMPRESSOR_SETTINGS, manager._get_compressor_settings()
        )

    def test_manager_custom_compressor_settings(self):
        locations, old_block = self.make_block(self._texts)
        called = []

        def compressor_settings():
            called.append("called")
            return (10,)

        manager = groupcompress._LazyGroupContentManager(
            old_block, get_compressor_settings=compressor_settings
        )
        # It doesn't greedily evaluate compressor_settings
        self.assertIs(None, manager._compressor_settings)
        self.assertEqual((10,), manager._get_compressor_settings())
        self.assertEqual((10,), manager._get_compressor_settings())
        self.assertEqual((10,), manager._compressor_settings)
        # Only called 1 time
        self.assertEqual(["called"], called)

    def test__rebuild_handles_compressor_settings(self):
        if not isinstance(
            groupcompress.GroupCompressor, groupcompress.PyrexGroupCompressor
        ):
            raise tests.TestNotApplicable(
                "pure-python compressor does not handle compressor_settings"
            )
        locations, old_block = self.make_block(self._texts)
        manager = groupcompress._LazyGroupContentManager(
            old_block, get_compressor_settings=lambda: {"max_bytes_to_index": 32}
        )
        gc = manager._make_group_compressor()
        self.assertEqual(32, gc._delta_index._max_bytes_to_index)
        self.add_key_to_manager((b"key3",), locations, old_block, manager)
        self.add_key_to_manager((b"key4",), locations, old_block, manager)
        action, last_byte, total_bytes = manager._check_rebuild_action()
        self.assertEqual("rebuild", action)
        manager._rebuild_block()
        new_block = manager._block
        self.assertIsNot(old_block, new_block)
        # Because of the new max_bytes_to_index, we do a poor job of
        # rebuilding. This is a side-effect of the change, but at least it does
        # show the setting had an effect.
        self.assertLess(old_block._content_length, new_block._content_length)

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
        f1k1 = (b"f1", b"k1")
        f1k2 = (b"f1", b"k2")
        f2k1 = (b"f2", b"k1")
        f2k2 = (b"f2", b"k2")
        texts[f1k1] = self._texts[(b"key1",)]
        texts[f1k2] = self._texts[(b"key2",)]
        texts[f2k1] = self._texts[(b"key3",)]
        texts[f2k2] = self._texts[(b"key4",)]
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
        self.add_key_to_manager((b"key1",), locations, block, manager)
        self.add_key_to_manager((b"key2",), locations, block, manager)
        # Just using the content from key1 and 2 is not enough to be considered
        # 'complete'
        self.assertFalse(manager.check_is_well_utilized())
        # However if we add key3, then we have enough, as we only require 75%
        # consumption
        self.add_key_to_manager((b"key4",), locations, block, manager)
        self.assertTrue(manager.check_is_well_utilized())


class Test_GCBuildDetails(tests.TestCase):
    def test_acts_like_tuple(self):
        # _GCBuildDetails inlines some of the data that used to be spread out
        # across a bunch of tuples
        bd = groupcompress._GCBuildDetails(
            (("parent1",), ("parent2",)), ("INDEX", 10, 20, 0, 5)
        )
        self.assertEqual(4, len(bd))
        self.assertEqual(("INDEX", 10, 20, 0, 5), bd[0])
        self.assertEqual(None, bd[1])  # Compression Parent is always None
        self.assertEqual((("parent1",), ("parent2",)), bd[2])
        self.assertEqual(("group", None), bd[3])  # Record details

    def test__repr__(self):
        bd = groupcompress._GCBuildDetails(
            (("parent1",), ("parent2",)), ("INDEX", 10, 20, 0, 5)
        )
        self.assertEqual(
            "_GCBuildDetails(('INDEX', 10, 20, 0, 5), (('parent1',), ('parent2',)))",
            repr(bd),
        )


class TestBase128Int(tests.TestCase):
    def assertEqualEncode(self, bytes, val):
        self.assertEqual(bytes, groupcompress.encode_base128_int(val))

    def assertEqualDecode(self, val, num_decode, bytes):
        self.assertEqual((val, num_decode), groupcompress.decode_base128_int(bytes))

    def test_encode(self):
        self.assertEqualEncode(b"\x01", 1)
        self.assertEqualEncode(b"\x02", 2)
        self.assertEqualEncode(b"\x7f", 127)
        self.assertEqualEncode(b"\x80\x01", 128)
        self.assertEqualEncode(b"\xff\x01", 255)
        self.assertEqualEncode(b"\x80\x02", 256)
        self.assertEqualEncode(b"\xff\xff\xff\xff\x0f", 0xFFFFFFFF)

    def test_decode(self):
        self.assertEqualDecode(1, 1, b"\x01")
        self.assertEqualDecode(2, 1, b"\x02")
        self.assertEqualDecode(127, 1, b"\x7f")
        self.assertEqualDecode(128, 2, b"\x80\x01")
        self.assertEqualDecode(255, 2, b"\xff\x01")
        self.assertEqualDecode(256, 2, b"\x80\x02")
        self.assertEqualDecode(0xFFFFFFFF, 5, b"\xff\xff\xff\xff\x0f")

    def test_decode_with_trailing_bytes(self):
        self.assertEqualDecode(1, 1, b"\x01abcdef")
        self.assertEqualDecode(127, 1, b"\x7f\x01")
        self.assertEqualDecode(128, 2, b"\x80\x01abcdef")
        self.assertEqualDecode(255, 2, b"\xff\x01\xff")

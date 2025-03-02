# Copyright (C) 2008-2012, 2016 Canonical Ltd
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

"""Tests for btree indices."""

import pprint
import zlib

from ... import fifo_cache, lru_cache, osutils, tests, transport
from ...tests import TestCaseWithTransport, features, scenarios
from .. import btree_index
from .. import index as _mod_index

load_tests = scenarios.load_tests_apply_scenarios


def btreeparser_scenarios():
    import breezy.bzr._btree_serializer_py as py_module

    scenarios = [("python", {"parse_btree": py_module})]
    if compiled_btreeparser_feature.available():
        scenarios.append(("C", {"parse_btree": compiled_btreeparser_feature.module}))
    return scenarios


compiled_btreeparser_feature = features.ModuleAvailableFeature(
    "breezy.bzr._btree_serializer_pyx"
)


class BTreeTestCase(TestCaseWithTransport):
    # test names here are suffixed by the key length and reference list count
    # that they test.

    def setUp(self):
        super().setUp()
        self.overrideAttr(btree_index, "_RESERVED_HEADER_BYTES", 100)

    def make_nodes(self, count, key_elements, reference_lists):
        """Generate count*key_elements sample nodes."""

        def _pos_to_key(pos, lead=b""):
            return (lead + (b"%d" % pos) * 40,)

        keys = []
        for prefix_pos in range(key_elements):
            if key_elements - 1:
                prefix = _pos_to_key(prefix_pos)
            else:
                prefix = ()
            for pos in range(count):
                # TODO: This creates odd keys. When count == 100,000, it
                #       creates a 240 byte key
                key = prefix + _pos_to_key(pos)
                value = b"value:%d" % pos
                if reference_lists:
                    # generate some references
                    refs = []
                    for list_pos in range(reference_lists):
                        # as many keys in each list as its index + the key depth
                        # mod 2 - this generates both 0 length lists and
                        # ones slightly longer than the number of lists.
                        # It also ensures we have non homogeneous lists.
                        refs.append([])
                        for ref_pos in range(list_pos + pos % 2):
                            if pos % 2:
                                # refer to a nearby key
                                refs[-1].append(prefix + _pos_to_key(pos - 1, b"ref"))
                            else:
                                # serial of this ref in the ref list
                                refs[-1].append(prefix + _pos_to_key(ref_pos, b"ref"))
                        refs[-1] = tuple(refs[-1])
                    refs = tuple(refs)
                else:
                    refs = ()
                keys.append((key, value, refs))
        return keys

    def shrink_page_size(self):
        """Shrink the default page size so that less fits in a page."""
        self.overrideAttr(btree_index, "_PAGE_SIZE")
        btree_index._PAGE_SIZE = 2048

    def assertEqualApproxCompressed(self, expected, actual, slop=6):
        """Check a count of compressed bytes is approximately as expected.

        Relying on compressed length being stable even with fixed inputs is
        slightly bogus, but zlib is stable enough that this mostly works.
        """
        if not expected - slop < actual < expected + slop:
            self.fail(
                f"Expected around {expected} bytes compressed but got {actual} bytes."
            )


class TestBTreeBuilder(BTreeTestCase):
    def test_clear_cache(self):
        builder = btree_index.BTreeBuilder(reference_lists=0, key_elements=1)
        # This is a no-op, but we need the api to be consistent with other
        # BTreeGraphIndex apis.
        builder.clear_cache()

    def test_empty_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=0\n"
            b"row_lengths=\n",
            content,
        )

    def test_empty_2_1(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=1)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=1\nkey_elements=2\nlen=0\n"
            b"row_lengths=\n",
            content,
        )

    def test_root_leaf_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(5, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(131, len(content))
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=5\n"
            b"row_lengths=1\n",
            content[:73],
        )
        node_content = content[73:]
        node_bytes = zlib.decompress(node_content)
        expected_node = (
            b"type=leaf\n"
            b"0000000000000000000000000000000000000000\x00\x00value:0\n"
            b"1111111111111111111111111111111111111111\x00\x00value:1\n"
            b"2222222222222222222222222222222222222222\x00\x00value:2\n"
            b"3333333333333333333333333333333333333333\x00\x00value:3\n"
            b"4444444444444444444444444444444444444444\x00\x00value:4\n"
        )
        self.assertEqual(expected_node, node_bytes)

    def test_root_leaf_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(5, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(238, len(content))
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=2\nkey_elements=2\nlen=10\n"
            b"row_lengths=1\n",
            content[:74],
        )
        node_content = content[74:]
        node_bytes = zlib.decompress(node_content)
        expected_node = (
            b"type=leaf\n"
            b"0000000000000000000000000000000000000000\x000000000000000000000000000000000000000000\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:0\n"
            b"0000000000000000000000000000000000000000\x001111111111111111111111111111111111111111\x000000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\r0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:1\n"
            b"0000000000000000000000000000000000000000\x002222222222222222222222222222222222222222\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:2\n"
            b"0000000000000000000000000000000000000000\x003333333333333333333333333333333333333333\x000000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\t0000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\r0000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\x00value:3\n"
            b"0000000000000000000000000000000000000000\x004444444444444444444444444444444444444444\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:4\n"
            b"1111111111111111111111111111111111111111\x000000000000000000000000000000000000000000\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:0\n"
            b"1111111111111111111111111111111111111111\x001111111111111111111111111111111111111111\x001111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\r1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:1\n"
            b"1111111111111111111111111111111111111111\x002222222222222222222222222222222222222222\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:2\n"
            b"1111111111111111111111111111111111111111\x003333333333333333333333333333333333333333\x001111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\t1111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\r1111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\x00value:3\n"
            b"1111111111111111111111111111111111111111\x004444444444444444444444444444444444444444\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:4\n"
            b""
        )
        self.assertEqual(expected_node, node_bytes)

    def test_2_leaves_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(400, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqualApproxCompressed(9283, len(content))
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=400\n"
            b"row_lengths=1,2\n",
            content[:77],
        )
        root = content[77:4096]
        leaf1 = content[4096:8192]
        leaf2 = content[8192:]
        root_bytes = zlib.decompress(root)
        expected_root = (b"type=internal\noffset=0\n") + (b"307" * 40) + b"\n"
        self.assertEqual(expected_root, root_bytes)
        # We already know serialisation works for leaves, check key selection:
        leaf1_bytes = zlib.decompress(leaf1)
        sorted_node_keys = sorted(node[0] for node in nodes)
        node = btree_index._LeafNode(leaf1_bytes, 1, 0)
        self.assertEqual(231, len(node))
        self.assertEqual(sorted_node_keys[:231], node.all_keys())
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(400 - 231, len(node))
        self.assertEqual(sorted_node_keys[231:], node.all_keys())

    def test_last_page_rounded_1_layer(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(10, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqualApproxCompressed(155, len(content))
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=10\n"
            b"row_lengths=1\n",
            content[:74],
        )
        # Check thelast page is well formed
        leaf2 = content[74:]
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(10, len(node))
        sorted_node_keys = sorted(node[0] for node in nodes)
        self.assertEqual(sorted_node_keys, node.all_keys())

    def test_last_page_not_rounded_2_layer(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(400, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqualApproxCompressed(9283, len(content))
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=400\n"
            b"row_lengths=1,2\n",
            content[:77],
        )
        # Check the last page is well formed
        leaf2 = content[8192:]
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(400 - 231, len(node))
        sorted_node_keys = sorted(node[0] for node in nodes)
        self.assertEqual(sorted_node_keys[231:], node.all_keys())

    def test_three_level_tree_details(self):
        # The left most pointer in the second internal node in a row should
        # pointer to the second node that the internal node is for, _not_
        # the first, otherwise the first node overlaps with the last node of
        # the prior internal node on that row.
        self.shrink_page_size()
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 40K nodes is enough to create a two internal nodes on the second
        # level, with a 2K page size
        nodes = self.make_nodes(20000, 2, 2)

        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", self.time(builder.finish))
        del builder
        index = btree_index.BTreeGraphIndex(t, "index", size)
        # Seed the metadata, we're using internal calls now.
        index.key_count()
        self.assertEqual(
            3, len(index._row_lengths), "Not enough rows: {!r}".format(index._row_lengths)
        )
        self.assertEqual(4, len(index._row_offsets))
        self.assertEqual(sum(index._row_lengths), index._row_offsets[-1])
        internal_nodes = index._get_internal_nodes([0, 1, 2])
        internal_nodes[0]
        internal_node1 = internal_nodes[1]
        internal_node2 = internal_nodes[2]
        # The left most node node2 points at should be one after the right most
        # node pointed at by node1.
        self.assertEqual(internal_node2.offset, 1 + len(internal_node1.keys))
        # The left most key of the second node pointed at by internal_node2
        # should be its first key. We can check this by looking for its first key
        # in the second node it points at
        pos = index._row_offsets[2] + internal_node2.offset + 1
        leaf = index._get_leaf_nodes([pos])[pos]
        self.assertTrue(internal_node2.keys[0] in leaf)

    def test_2_leaves_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(100, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqualApproxCompressed(12643, len(content))
        self.assertEqual(
            b"B+Tree Graph Index 2\nnode_ref_lists=2\nkey_elements=2\nlen=200\n"
            b"row_lengths=1,3\n",
            content[:77],
        )
        root = content[77:4096]
        content[4096:8192]
        content[8192:12288]
        content[12288:]
        root_bytes = zlib.decompress(root)
        expected_root = (
            b"type=internal\n"
            b"offset=0\n"
            + (b"0" * 40)
            + b"\x00"
            + (b"91" * 40)
            + b"\n"
            + (b"1" * 40)
            + b"\x00"
            + (b"81" * 40)
            + b"\n"
        )
        self.assertEqual(expected_root, root_bytes)
        # We assume the other leaf nodes have been written correctly - layering
        # FTW.

    def test_spill_index_stress_1_1(self):
        builder = btree_index.BTreeBuilder(key_elements=1, spill_at=2)
        nodes = [node[0:2] for node in self.make_nodes(16, 1, 0)]
        builder.add_node(*nodes[0])
        # Test the parts of the index that take up memory are doing so
        # predictably.
        self.assertEqual(1, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        builder.add_node(*nodes[2])
        self.assertEqual(1, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        # And spills to a second backing index combing all
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # The next spills to the 2-len slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # Next spill combines
        builder.add_node(*nodes[6])
        builder.add_node(*nodes[7])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        # And so forth - counting up in binary.
        builder.add_node(*nodes[8])
        builder.add_node(*nodes[9])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[10])
        builder.add_node(*nodes[11])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[12])
        # Test that memory and disk are both used for query methods; and that
        # None is skipped over happily.
        self.assertEqual(
            [(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()),
        )
        # Two nodes - one memory one disk
        self.assertEqual(
            {(builder,) + node for node in nodes[11:13]},
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])),
        )
        self.assertEqual(13, builder.key_count())
        self.assertEqual(
            {(builder,) + node for node in nodes[11:13]},
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])),
        )
        builder.add_node(*nodes[13])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[14])
        builder.add_node(*nodes[15])
        self.assertEqual(4, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(None, builder._backing_indices[2])
        self.assertEqual(16, builder._backing_indices[3].key_count())
        # Now finish, and check we got a correctly ordered tree
        t = self.get_transport("")
        size = t.put_file("index", builder.finish())
        index = btree_index.BTreeGraphIndex(t, "index", size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_spill_index_stress_1_1_no_combine(self):
        builder = btree_index.BTreeBuilder(key_elements=1, spill_at=2)
        builder.set_optimize(for_size=False, combine_backing_indices=False)
        nodes = [node[0:2] for node in self.make_nodes(16, 1, 0)]
        builder.add_node(*nodes[0])
        # Test the parts of the index that take up memory are doing so
        # predictably.
        self.assertEqual(1, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        builder.add_node(*nodes[2])
        self.assertEqual(1, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        # And spills to a second backing index but doesn't combine
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        for backing_index in builder._backing_indices:
            self.assertEqual(2, backing_index.key_count())
        # The next spills to the 3rd slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(3, len(builder._backing_indices))
        for backing_index in builder._backing_indices:
            self.assertEqual(2, backing_index.key_count())
        # Now spill a few more, and check that we don't combine
        builder.add_node(*nodes[6])
        builder.add_node(*nodes[7])
        builder.add_node(*nodes[8])
        builder.add_node(*nodes[9])
        builder.add_node(*nodes[10])
        builder.add_node(*nodes[11])
        builder.add_node(*nodes[12])
        self.assertEqual(6, len(builder._backing_indices))
        for backing_index in builder._backing_indices:
            self.assertEqual(2, backing_index.key_count())
        # Test that memory and disk are both used for query methods; and that
        # None is skipped over happily.
        self.assertEqual(
            [(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()),
        )
        # Two nodes - one memory one disk
        self.assertEqual(
            {(builder,) + node for node in nodes[11:13]},
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])),
        )
        self.assertEqual(13, builder.key_count())
        self.assertEqual(
            {(builder,) + node for node in nodes[11:13]},
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])),
        )
        builder.add_node(*nodes[13])
        builder.add_node(*nodes[14])
        builder.add_node(*nodes[15])
        self.assertEqual(8, len(builder._backing_indices))
        for backing_index in builder._backing_indices:
            self.assertEqual(2, backing_index.key_count())
        # Now finish, and check we got a correctly ordered tree
        transport = self.get_transport("")
        size = transport.put_file("index", builder.finish())
        index = btree_index.BTreeGraphIndex(transport, "index", size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_set_optimize(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        builder.set_optimize(for_size=True)
        self.assertTrue(builder._optimize_for_size)
        builder.set_optimize(for_size=False)
        self.assertFalse(builder._optimize_for_size)
        # test that we can set combine_backing_indices without effecting
        # _optimize_for_size
        obj = object()
        builder._optimize_for_size = obj
        builder.set_optimize(combine_backing_indices=False)
        self.assertFalse(builder._combine_backing_indices)
        self.assertIs(obj, builder._optimize_for_size)
        builder.set_optimize(combine_backing_indices=True)
        self.assertTrue(builder._combine_backing_indices)
        self.assertIs(obj, builder._optimize_for_size)

    def test_spill_index_stress_2_2(self):
        # test that references and longer keys don't confuse things.
        builder = btree_index.BTreeBuilder(
            key_elements=2, reference_lists=2, spill_at=2
        )
        nodes = self.make_nodes(16, 2, 2)
        builder.add_node(*nodes[0])
        # Test the parts of the index that take up memory are doing so
        # predictably.
        self.assertEqual(1, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        # Build up the nodes by key dict
        old = dict(builder._get_nodes_by_key())
        builder.add_node(*nodes[2])
        self.assertEqual(1, len(builder._nodes))
        self.assertIsNot(None, builder._nodes_by_key)
        self.assertNotEqual({}, builder._nodes_by_key)
        # We should have a new entry
        self.assertNotEqual(old, builder._nodes_by_key)
        # And spills to a second backing index combing all
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # The next spills to the 2-len slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # Next spill combines
        builder.add_node(*nodes[6])
        builder.add_node(*nodes[7])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        # And so forth - counting up in binary.
        builder.add_node(*nodes[8])
        builder.add_node(*nodes[9])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[10])
        builder.add_node(*nodes[11])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[12])
        # Test that memory and disk are both used for query methods; and that
        # None is skipped over happily.
        self.assertEqual(
            [(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()),
        )
        # Two nodes - one memory one disk
        self.assertEqual(
            {(builder,) + node for node in nodes[11:13]},
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])),
        )
        self.assertEqual(13, builder.key_count())
        self.assertEqual(
            {(builder,) + node for node in nodes[11:13]},
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])),
        )
        builder.add_node(*nodes[13])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[14])
        builder.add_node(*nodes[15])
        self.assertEqual(4, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(None, builder._backing_indices[2])
        self.assertEqual(16, builder._backing_indices[3].key_count())
        # Now finish, and check we got a correctly ordered tree
        transport = self.get_transport("")
        size = transport.put_file("index", builder.finish())
        index = btree_index.BTreeGraphIndex(transport, "index", size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_spill_index_duplicate_key_caught_on_finish(self):
        builder = btree_index.BTreeBuilder(key_elements=1, spill_at=2)
        nodes = [node[0:2] for node in self.make_nodes(16, 1, 0)]
        builder.add_node(*nodes[0])
        builder.add_node(*nodes[1])
        builder.add_node(*nodes[0])
        self.assertRaises(_mod_index.BadIndexDuplicateKey, builder.finish)


class TestBTreeIndex(BTreeTestCase):
    def make_index(self, ref_lists=0, key_elements=1, nodes=None):
        if nodes is None:
            nodes = []
        builder = btree_index.BTreeBuilder(
            reference_lists=ref_lists, key_elements=key_elements
        )
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = transport.get_transport_from_url("trace+" + self.get_url())
        size = trans.put_file("index", stream)
        return btree_index.BTreeGraphIndex(trans, "index", size)

    def make_index_with_offset(self, ref_lists=1, key_elements=1, nodes=None, offset=0):
        if nodes is None:
            nodes = []
        builder = btree_index.BTreeBuilder(
            key_elements=key_elements, reference_lists=ref_lists
        )
        builder.add_nodes(nodes)
        transport = self.get_transport("")
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        size = len(content)
        transport.put_bytes("index", (b" " * offset) + content)
        return btree_index.BTreeGraphIndex(transport, "index", size=size, offset=offset)

    def test_clear_cache(self):
        nodes = self.make_nodes(160, 2, 2)
        index = self.make_index(ref_lists=2, key_elements=2, nodes=nodes)
        self.assertEqual(1, len(list(index.iter_entries([nodes[30][0]]))))
        self.assertEqual([1, 4], index._row_lengths)
        self.assertIsNot(None, index._root_node)
        internal_node_pre_clear = set(index._internal_node_cache)
        self.assertTrue(len(index._leaf_node_cache) > 0)
        index.clear_cache()
        # We don't touch _root_node or _internal_node_cache, both should be
        # small, and can save a round trip or two
        self.assertIsNot(None, index._root_node)
        # NOTE: We don't want to affect the _internal_node_cache, as we expect
        #       it will be small, and if we ever do touch this index again, it
        #       will save round-trips.  This assertion isn't very strong,
        #       becuase without a 3-level index, we don't have any internal
        #       nodes cached.
        self.assertEqual(internal_node_pre_clear, set(index._internal_node_cache))
        self.assertEqual(0, len(index._leaf_node_cache))

    def test_trivial_constructor(self):
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        btree_index.BTreeGraphIndex(t, "index", None)
        # Checks the page size at load, but that isn't logged yet.
        self.assertEqual([], t._activity)

    def test_with_size_constructor(self):
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        btree_index.BTreeGraphIndex(t, "index", 1)
        # Checks the page size at load, but that isn't logged yet.
        self.assertEqual([], t._activity)

    def test_empty_key_count_no_size(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        t.put_file("index", builder.finish())
        index = btree_index.BTreeGraphIndex(t, "index", None)
        del t._activity[:]
        self.assertEqual([], t._activity)
        self.assertEqual(0, index.key_count())
        # The entire index should have been requested (as we generally have the
        # size available, and doing many small readvs is inappropriate).
        # We can't tell how much was actually read here, but - check the code.
        self.assertEqual([("get", "index")], t._activity)

    def test_empty_key_count(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        self.assertEqual(72, size)
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        self.assertEqual(0, index.key_count())
        # The entire index should have been read, as 4K > size
        self.assertEqual([("readv", "index", [(0, 72)], False, None)], t._activity)

    def test_non_empty_key_count_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(35, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        self.assertEqual(70, index.key_count())
        # The entire index should have been read, as it is one page long.
        self.assertEqual([("readv", "index", [(0, size)], False, None)], t._activity)
        self.assertEqualApproxCompressed(1173, size)

    def test_with_offset_no_size(self):
        index = self.make_index_with_offset(
            key_elements=1, ref_lists=1, offset=1234, nodes=self.make_nodes(200, 1, 1)
        )
        index._size = None  # throw away the size info
        self.assertEqual(200, index.key_count())

    def test_with_small_offset(self):
        index = self.make_index_with_offset(
            key_elements=1, ref_lists=1, offset=1234, nodes=self.make_nodes(200, 1, 1)
        )
        self.assertEqual(200, index.key_count())

    def test_with_large_offset(self):
        index = self.make_index_with_offset(
            key_elements=1, ref_lists=1, offset=123456, nodes=self.make_nodes(200, 1, 1)
        )
        self.assertEqual(200, index.key_count())

    def test__read_nodes_no_size_one_page_reads_once(self):
        self.make_index(nodes=[((b"key",), b"value", ())])
        trans = transport.get_transport_from_url("trace+" + self.get_url())
        index = btree_index.BTreeGraphIndex(trans, "index", None)
        del trans._activity[:]
        nodes = dict(index._read_nodes([0]))
        self.assertEqual({0}, set(nodes))
        node = nodes[0]
        self.assertEqual([(b"key",)], node.all_keys())
        self.assertEqual([("get", "index")], trans._activity)

    def test__read_nodes_no_size_multiple_pages(self):
        index = self.make_index(2, 2, nodes=self.make_nodes(160, 2, 2))
        index.key_count()
        num_pages = index._row_offsets[-1]
        # Reopen with a traced transport and no size
        trans = transport.get_transport_from_url("trace+" + self.get_url())
        index = btree_index.BTreeGraphIndex(trans, "index", None)
        del trans._activity[:]
        nodes = dict(index._read_nodes([0]))
        self.assertEqual(list(range(num_pages)), sorted(nodes))

    def test_2_levels_key_count_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        self.assertEqualApproxCompressed(17692, size)
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        self.assertEqual(320, index.key_count())
        # The entire index should not have been read.
        self.assertEqual([("readv", "index", [(0, 4096)], False, None)], t._activity)

    def test_validate_one_page(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(45, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        index.validate()
        # The entire index should have been read linearly.
        self.assertEqual([("readv", "index", [(0, size)], False, None)], t._activity)
        self.assertEqualApproxCompressed(1488, size)

    def test_validate_two_pages(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(80, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        # Root page, 2 leaf pages
        self.assertEqualApproxCompressed(9339, size)
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        index.validate()
        rem = size - 8192  # Number of remaining bytes after second block
        # The entire index should have been read linearly.
        self.assertEqual(
            [
                ("readv", "index", [(0, 4096)], False, None),
                ("readv", "index", [(4096, 4096), (8192, rem)], False, None),
            ],
            t._activity,
        )
        # XXX: TODO: write some badly-ordered nodes, and some pointers-to-wrong
        # node and make validate find them.

    def test_eq_ne(self):
        # two indices are equal when constructed with the same parameters:
        t1 = transport.get_transport_from_url("trace+" + self.get_url(""))
        t2 = self.get_transport()
        self.assertTrue(
            btree_index.BTreeGraphIndex(t1, "index", None)
            == btree_index.BTreeGraphIndex(t1, "index", None)
        )
        self.assertTrue(
            btree_index.BTreeGraphIndex(t1, "index", 20)
            == btree_index.BTreeGraphIndex(t1, "index", 20)
        )
        self.assertFalse(
            btree_index.BTreeGraphIndex(t1, "index", 20)
            == btree_index.BTreeGraphIndex(t2, "index", 20)
        )
        self.assertFalse(
            btree_index.BTreeGraphIndex(t1, "inde1", 20)
            == btree_index.BTreeGraphIndex(t1, "inde2", 20)
        )
        self.assertFalse(
            btree_index.BTreeGraphIndex(t1, "index", 10)
            == btree_index.BTreeGraphIndex(t1, "index", 20)
        )
        self.assertFalse(
            btree_index.BTreeGraphIndex(t1, "index", None)
            != btree_index.BTreeGraphIndex(t1, "index", None)
        )
        self.assertFalse(
            btree_index.BTreeGraphIndex(t1, "index", 20)
            != btree_index.BTreeGraphIndex(t1, "index", 20)
        )
        self.assertTrue(
            btree_index.BTreeGraphIndex(t1, "index", 20)
            != btree_index.BTreeGraphIndex(t2, "index", 20)
        )
        self.assertTrue(
            btree_index.BTreeGraphIndex(t1, "inde1", 20)
            != btree_index.BTreeGraphIndex(t1, "inde2", 20)
        )
        self.assertTrue(
            btree_index.BTreeGraphIndex(t1, "index", 10)
            != btree_index.BTreeGraphIndex(t1, "index", 20)
        )

    def test_key_too_big(self):
        # the size that matters here is the _compressed_ size of the key, so we can't
        # do a simple character repeat.
        bigKey = b"".join(b"%d" % n for n in range(btree_index._PAGE_SIZE))
        self.assertRaises(
            _mod_index.BadIndexKey, self.make_index, nodes=[((bigKey,), b"value", ())]
        )

    def test_iter_all_only_root_no_size(self):
        self.make_index(nodes=[((b"key",), b"value", ())])
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        index = btree_index.BTreeGraphIndex(t, "index", None)
        del t._activity[:]
        self.assertEqual(
            [((b"key",), b"value")], [x[1:] for x in index.iter_all_entries()]
        )
        self.assertEqual([("get", "index")], t._activity)

    def test_iter_all_entries_reads(self):
        # iterating all entries reads the header, then does a linear
        # read.
        self.shrink_page_size()
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 20k nodes is enough to create a two internal nodes on the second
        # level, with a 2K page size
        nodes = self.make_nodes(10000, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        page_size = btree_index._PAGE_SIZE
        del builder
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        found_nodes = self.time(list, index.iter_all_entries())
        bare_nodes = []
        for node in found_nodes:
            self.assertTrue(node[0] is index)
            bare_nodes.append(node[1:])
        self.assertEqual(
            3, len(index._row_lengths), "Not enough rows: {!r}".format(index._row_lengths)
        )
        # Should be as long as the nodes we supplied
        self.assertEqual(20000, len(found_nodes))
        # Should have the same content
        self.assertEqual(set(nodes), set(bare_nodes))
        # Should have done linear scan IO up the index, ignoring
        # the internal nodes:
        # The entire index should have been read
        total_pages = sum(index._row_lengths)
        self.assertEqual(total_pages, index._row_offsets[-1])
        self.assertEqualApproxCompressed(1303220, size)
        # The start of the leaves
        first_byte = index._row_offsets[-2] * page_size
        readv_request = []
        for offset in range(first_byte, size, page_size):
            readv_request.append((offset, page_size))
        # The last page is truncated
        readv_request[-1] = (readv_request[-1][0], size % page_size)
        expected = [
            ("readv", "index", [(0, page_size)], False, None),
            ("readv", "index", readv_request, False, None),
        ]
        if expected != t._activity:
            self.assertEqualDiff(pprint.pformat(expected), pprint.pformat(t._activity))

    def test_iter_entries_references_2_refs_resolved(self):
        # iterating some entries reads just the pages needed. For now, to
        # get it working and start measuring, only 4K pages are read.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 80 nodes is enough to create a two-level index.
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        t = transport.get_transport_from_url("trace+" + self.get_url(""))
        size = t.put_file("index", builder.finish())
        del builder
        index = btree_index.BTreeGraphIndex(t, "index", size)
        del t._activity[:]
        self.assertEqual([], t._activity)
        # search for one key
        found_nodes = list(index.iter_entries([nodes[30][0]]))
        bare_nodes = []
        for node in found_nodes:
            self.assertTrue(node[0] is index)
            bare_nodes.append(node[1:])
        # Should be as long as the nodes we supplied
        self.assertEqual(1, len(found_nodes))
        # Should have the same content
        self.assertEqual(nodes[30], bare_nodes[0])
        # Should have read the root node, then one leaf page:
        self.assertEqual(
            [
                ("readv", "index", [(0, 4096)], False, None),
                (
                    "readv",
                    "index",
                    [
                        (8192, 4096),
                    ],
                    False,
                    None,
                ),
            ],
            t._activity,
        )

    def test_iter_key_prefix_1_element_key_None(self):
        index = self.make_index()
        self.assertRaises(
            _mod_index.BadIndexKey, list, index.iter_entries_prefix([(None,)])
        )

    def test_iter_key_prefix_wrong_length(self):
        index = self.make_index()
        self.assertRaises(
            _mod_index.BadIndexKey, list, index.iter_entries_prefix([(b"foo", None)])
        )
        index = self.make_index(key_elements=2)
        self.assertRaises(
            _mod_index.BadIndexKey, list, index.iter_entries_prefix([(b"foo",)])
        )
        self.assertRaises(
            _mod_index.BadIndexKey,
            list,
            index.iter_entries_prefix([(b"foo", None, None)]),
        )

    def test_iter_key_prefix_1_key_element_no_refs(self):
        index = self.make_index(
            nodes=[((b"name",), b"data", ()), ((b"ref",), b"refdata", ())]
        )
        self.assertEqual(
            {(index, (b"name",), b"data"), (index, (b"ref",), b"refdata")},
            set(index.iter_entries_prefix([(b"name",), (b"ref",)])),
        )

    def test_iter_key_prefix_1_key_element_refs(self):
        index = self.make_index(
            1,
            nodes=[
                ((b"name",), b"data", ([(b"ref",)],)),
                ((b"ref",), b"refdata", ([],)),
            ],
        )
        self.assertEqual(
            {
                (index, (b"name",), b"data", (((b"ref",),),)),
                (index, (b"ref",), b"refdata", ((),)),
            },
            set(index.iter_entries_prefix([(b"name",), (b"ref",)])),
        )

    def test_iter_key_prefix_2_key_element_no_refs(self):
        index = self.make_index(
            key_elements=2,
            nodes=[
                ((b"name", b"fin1"), b"data", ()),
                ((b"name", b"fin2"), b"beta", ()),
                ((b"ref", b"erence"), b"refdata", ()),
            ],
        )
        self.assertEqual(
            {
                (index, (b"name", b"fin1"), b"data"),
                (index, (b"ref", b"erence"), b"refdata"),
            },
            set(index.iter_entries_prefix([(b"name", b"fin1"), (b"ref", b"erence")])),
        )
        self.assertEqual(
            {
                (index, (b"name", b"fin1"), b"data"),
                (index, (b"name", b"fin2"), b"beta"),
            },
            set(index.iter_entries_prefix([(b"name", None)])),
        )

    def test_iter_key_prefix_2_key_element_refs(self):
        index = self.make_index(
            1,
            key_elements=2,
            nodes=[
                ((b"name", b"fin1"), b"data", ([(b"ref", b"erence")],)),
                ((b"name", b"fin2"), b"beta", ([],)),
                ((b"ref", b"erence"), b"refdata", ([],)),
            ],
        )
        self.assertEqual(
            {
                (index, (b"name", b"fin1"), b"data", (((b"ref", b"erence"),),)),
                (index, (b"ref", b"erence"), b"refdata", ((),)),
            },
            set(index.iter_entries_prefix([(b"name", b"fin1"), (b"ref", b"erence")])),
        )
        self.assertEqual(
            {
                (index, (b"name", b"fin1"), b"data", (((b"ref", b"erence"),),)),
                (index, (b"name", b"fin2"), b"beta", ((),)),
            },
            set(index.iter_entries_prefix([(b"name", None)])),
        )

    # XXX: external_references tests are duplicated in test_index.  We
    # probably should have per_graph_index tests...
    def test_external_references_no_refs(self):
        index = self.make_index(ref_lists=0, nodes=[])
        self.assertRaises(ValueError, index.external_references, 0)

    def test_external_references_no_results(self):
        index = self.make_index(ref_lists=1, nodes=[((b"key",), b"value", ([],))])
        self.assertEqual(set(), index.external_references(0))

    def test_external_references_missing_ref(self):
        missing_key = (b"missing",)
        index = self.make_index(
            ref_lists=1, nodes=[((b"key",), b"value", ([missing_key],))]
        )
        self.assertEqual({missing_key}, index.external_references(0))

    def test_external_references_multiple_ref_lists(self):
        missing_key = (b"missing",)
        index = self.make_index(
            ref_lists=2, nodes=[((b"key",), b"value", ([], [missing_key]))]
        )
        self.assertEqual(set(), index.external_references(0))
        self.assertEqual({missing_key}, index.external_references(1))

    def test_external_references_two_records(self):
        index = self.make_index(
            ref_lists=1,
            nodes=[
                ((b"key-1",), b"value", ([(b"key-2",)],)),
                ((b"key-2",), b"value", ([],)),
            ],
        )
        self.assertEqual(set(), index.external_references(0))

    def test__find_ancestors_one_page(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        index = self.make_index(
            ref_lists=1,
            key_elements=1,
            nodes=[
                (key1, b"value", ([key2],)),
                (key2, b"value", ([],)),
            ],
        )
        parent_map = {}
        missing_keys = set()
        search_keys = index._find_ancestors([key1], 0, parent_map, missing_keys)
        self.assertEqual({key1: (key2,), key2: ()}, parent_map)
        self.assertEqual(set(), missing_keys)
        self.assertEqual(set(), search_keys)

    def test__find_ancestors_one_page_w_missing(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        key3 = (b"key-3",)
        index = self.make_index(
            ref_lists=1,
            key_elements=1,
            nodes=[
                (key1, b"value", ([key2],)),
                (key2, b"value", ([],)),
            ],
        )
        parent_map = {}
        missing_keys = set()
        search_keys = index._find_ancestors([key2, key3], 0, parent_map, missing_keys)
        self.assertEqual({key2: ()}, parent_map)
        # we know that key3 is missing because we read the page that it would
        # otherwise be on
        self.assertEqual({key3}, missing_keys)
        self.assertEqual(set(), search_keys)

    def test__find_ancestors_one_parent_missing(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        key3 = (b"key-3",)
        index = self.make_index(
            ref_lists=1,
            key_elements=1,
            nodes=[
                (key1, b"value", ([key2],)),
                (key2, b"value", ([key3],)),
            ],
        )
        parent_map = {}
        missing_keys = set()
        search_keys = index._find_ancestors([key1], 0, parent_map, missing_keys)
        self.assertEqual({key1: (key2,), key2: (key3,)}, parent_map)
        self.assertEqual(set(), missing_keys)
        # all we know is that key3 wasn't present on the page we were reading
        # but if you look, the last key is key2 which comes before key3, so we
        # don't know whether key3 would land on this page or not.
        self.assertEqual({key3}, search_keys)
        search_keys = index._find_ancestors(search_keys, 0, parent_map, missing_keys)
        # passing it back in, we are sure it is 'missing'
        self.assertEqual({key1: (key2,), key2: (key3,)}, parent_map)
        self.assertEqual({key3}, missing_keys)
        self.assertEqual(set(), search_keys)

    def test__find_ancestors_dont_search_known(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        key3 = (b"key-3",)
        index = self.make_index(
            ref_lists=1,
            key_elements=1,
            nodes=[
                (key1, b"value", ([key2],)),
                (key2, b"value", ([key3],)),
                (key3, b"value", ([],)),
            ],
        )
        # We already know about key2, so we won't try to search for key3
        parent_map = {key2: (key3,)}
        missing_keys = set()
        search_keys = index._find_ancestors([key1], 0, parent_map, missing_keys)
        self.assertEqual({key1: (key2,), key2: (key3,)}, parent_map)
        self.assertEqual(set(), missing_keys)
        self.assertEqual(set(), search_keys)

    def test__find_ancestors_multiple_pages(self):
        # We need to use enough keys that we actually cause a split
        start_time = 1249671539
        email = "joebob@example.com"
        nodes = []
        ref_lists = ((),)
        rev_keys = []
        for i in range(400):
            rev_id = (
                "{}-{}-{}".format(
                    email, osutils.compact_date(start_time + i), osutils.rand_chars(16)
                )
            ).encode("ascii")
            rev_key = (rev_id,)
            nodes.append((rev_key, b"value", ref_lists))
            # We have a ref 'list' of length 1, with a list of parents, with 1
            # parent which is a key
            ref_lists = ((rev_key,),)
            rev_keys.append(rev_key)
        index = self.make_index(ref_lists=1, key_elements=1, nodes=nodes)
        self.assertEqual(400, index.key_count())
        self.assertEqual(3, len(index._row_offsets))
        nodes = dict(index._read_nodes([1, 2]))
        l1 = nodes[1]
        l2 = nodes[2]
        min_l2_key = l2.min_key
        max_l1_key = l1.max_key
        self.assertTrue(max_l1_key < min_l2_key)
        parents_min_l2_key = l2[min_l2_key][1][0]
        self.assertEqual((l1.max_key,), parents_min_l2_key)
        # Now, whatever key we select that would fall on the second page,
        # should give us all the parents until the page break
        key_idx = rev_keys.index(min_l2_key)
        next_key = rev_keys[key_idx + 1]
        # So now when we get the parent map, we should get the key we are
        # looking for, min_l2_key, and then a reference to go look for the
        # parent of that key
        parent_map = {}
        missing_keys = set()
        search_keys = index._find_ancestors([next_key], 0, parent_map, missing_keys)
        self.assertEqual([min_l2_key, next_key], sorted(parent_map))
        self.assertEqual(set(), missing_keys)
        self.assertEqual({max_l1_key}, search_keys)
        parent_map = {}
        search_keys = index._find_ancestors([max_l1_key], 0, parent_map, missing_keys)
        self.assertEqual(l1.all_keys(), sorted(parent_map))
        self.assertEqual(set(), missing_keys)
        self.assertEqual(set(), search_keys)

    def test__find_ancestors_empty_index(self):
        index = self.make_index(ref_lists=1, key_elements=1, nodes=[])
        parent_map = {}
        missing_keys = set()
        search_keys = index._find_ancestors(
            [("one",), ("two",)], 0, parent_map, missing_keys
        )
        self.assertEqual(set(), search_keys)
        self.assertEqual({}, parent_map)
        self.assertEqual({("one",), ("two",)}, missing_keys)

    def test_supports_unlimited_cache(self):
        builder = btree_index.BTreeBuilder(reference_lists=0, key_elements=1)
        # We need enough nodes to cause a page split (so we have both an
        # internal node and a couple leaf nodes. 500 seems to be enough.)
        nodes = self.make_nodes(500, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file("index", stream)
        index = btree_index.BTreeGraphIndex(trans, "index", size)
        self.assertEqual(500, index.key_count())
        # We have an internal node
        self.assertEqual(2, len(index._row_lengths))
        # We have at least 2 leaf nodes
        self.assertTrue(index._row_lengths[-1] >= 2)
        self.assertIsInstance(index._leaf_node_cache, lru_cache.LRUCache)
        self.assertEqual(
            btree_index._NODE_CACHE_SIZE, index._leaf_node_cache._max_cache
        )
        self.assertIsInstance(index._internal_node_cache, fifo_cache.FIFOCache)
        self.assertEqual(100, index._internal_node_cache._max_cache)
        # No change if unlimited_cache=False is passed
        index = btree_index.BTreeGraphIndex(trans, "index", size, unlimited_cache=False)
        self.assertIsInstance(index._leaf_node_cache, lru_cache.LRUCache)
        self.assertEqual(
            btree_index._NODE_CACHE_SIZE, index._leaf_node_cache._max_cache
        )
        self.assertIsInstance(index._internal_node_cache, fifo_cache.FIFOCache)
        self.assertEqual(100, index._internal_node_cache._max_cache)
        index = btree_index.BTreeGraphIndex(trans, "index", size, unlimited_cache=True)
        self.assertIsInstance(index._leaf_node_cache, dict)
        self.assertIs(type(index._internal_node_cache), dict)
        # Exercise the lookup code
        entries = set(index.iter_entries([n[0] for n in nodes]))
        self.assertEqual(500, len(entries))


class TestBTreeNodes(BTreeTestCase):
    scenarios = btreeparser_scenarios()

    def setUp(self):
        super().setUp()
        self.overrideAttr(btree_index, "_btree_serializer", self.parse_btree)

    def test_LeafNode_1_0(self):
        node_bytes = (
            b"type=leaf\n"
            b"0000000000000000000000000000000000000000\x00\x00value:0\n"
            b"1111111111111111111111111111111111111111\x00\x00value:1\n"
            b"2222222222222222222222222222222222222222\x00\x00value:2\n"
            b"3333333333333333333333333333333333333333\x00\x00value:3\n"
            b"4444444444444444444444444444444444444444\x00\x00value:4\n"
        )
        node = btree_index._LeafNode(node_bytes, 1, 0)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual(
            {
                (b"0000000000000000000000000000000000000000",): (b"value:0", ()),
                (b"1111111111111111111111111111111111111111",): (b"value:1", ()),
                (b"2222222222222222222222222222222222222222",): (b"value:2", ()),
                (b"3333333333333333333333333333333333333333",): (b"value:3", ()),
                (b"4444444444444444444444444444444444444444",): (b"value:4", ()),
            },
            dict(node.all_items()),
        )

    def test_LeafNode_2_2(self):
        node_bytes = (
            b"type=leaf\n"
            b"00\x0000\x00\t00\x00ref00\x00value:0\n"
            b"00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n"
            b"11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n"
            b"11\x0044\x00\t11\x00ref00\x00value:4\n"
            b""
        )
        node = btree_index._LeafNode(node_bytes, 2, 2)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual(
            {
                (b"00", b"00"): (b"value:0", ((), ((b"00", b"ref00"),))),
                (b"00", b"11"): (
                    b"value:1",
                    (((b"00", b"ref00"),), ((b"00", b"ref00"), (b"01", b"ref01"))),
                ),
                (b"11", b"33"): (
                    b"value:3",
                    (((b"11", b"ref22"),), ((b"11", b"ref22"), (b"11", b"ref22"))),
                ),
                (b"11", b"44"): (b"value:4", ((), ((b"11", b"ref00"),))),
            },
            dict(node.all_items()),
        )

    def test_InternalNode_1(self):
        node_bytes = (
            b"type=internal\n"
            b"offset=1\n"
            b"0000000000000000000000000000000000000000\n"
            b"1111111111111111111111111111111111111111\n"
            b"2222222222222222222222222222222222222222\n"
            b"3333333333333333333333333333333333333333\n"
            b"4444444444444444444444444444444444444444\n"
        )
        node = btree_index._InternalNode(node_bytes)
        # We want to bisect to find the right children from this node, so a
        # vector is most useful.
        self.assertEqual(
            [
                (b"0000000000000000000000000000000000000000",),
                (b"1111111111111111111111111111111111111111",),
                (b"2222222222222222222222222222222222222222",),
                (b"3333333333333333333333333333333333333333",),
                (b"4444444444444444444444444444444444444444",),
            ],
            node.keys,
        )
        self.assertEqual(1, node.offset)

    def assertFlattened(self, expected, key, value, refs):
        flat_key, flat_line = self.parse_btree._flatten_node(
            (None, key, value, refs), bool(refs)
        )
        self.assertEqual(b"\x00".join(key), flat_key)
        self.assertEqual(expected, flat_line)

    def test__flatten_node(self):
        self.assertFlattened(b"key\0\0value\n", (b"key",), b"value", [])
        self.assertFlattened(
            b"key\0tuple\0\0value str\n", (b"key", b"tuple"), b"value str", []
        )
        self.assertFlattened(
            b"key\0tuple\0triple\0\0value str\n",
            (b"key", b"tuple", b"triple"),
            b"value str",
            [],
        )
        self.assertFlattened(
            b"k\0t\0s\0ref\0value str\n",
            (b"k", b"t", b"s"),
            b"value str",
            [[(b"ref",)]],
        )
        self.assertFlattened(
            b"key\0tuple\0ref\0key\0value str\n",
            (b"key", b"tuple"),
            b"value str",
            [[(b"ref", b"key")]],
        )
        self.assertFlattened(
            b"00\x0000\x00\t00\x00ref00\x00value:0\n",
            (b"00", b"00"),
            b"value:0",
            ((), ((b"00", b"ref00"),)),
        )
        self.assertFlattened(
            b"00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n",
            (b"00", b"11"),
            b"value:1",
            (((b"00", b"ref00"),), ((b"00", b"ref00"), (b"01", b"ref01"))),
        )
        self.assertFlattened(
            b"11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n",
            (b"11", b"33"),
            b"value:3",
            (((b"11", b"ref22"),), ((b"11", b"ref22"), (b"11", b"ref22"))),
        )
        self.assertFlattened(
            b"11\x0044\x00\t11\x00ref00\x00value:4\n",
            (b"11", b"44"),
            b"value:4",
            ((), ((b"11", b"ref00"),)),
        )


class TestCompiledBtree(tests.TestCase):
    def test_exists(self):
        # This is just to let the user know if they don't have the feature
        # available
        self.requireFeature(compiled_btreeparser_feature)


class TestMultiBisectRight(tests.TestCase):
    def assertMultiBisectRight(self, offsets, search_keys, fixed_keys):
        self.assertEqual(
            offsets,
            btree_index.BTreeGraphIndex._multi_bisect_right(search_keys, fixed_keys),
        )

    def test_after(self):
        self.assertMultiBisectRight([(1, ["b"])], ["b"], ["a"])
        self.assertMultiBisectRight(
            [(3, ["e", "f", "g"])], ["e", "f", "g"], ["a", "b", "c"]
        )

    def test_before(self):
        self.assertMultiBisectRight([(0, ["a"])], ["a"], ["b"])
        self.assertMultiBisectRight(
            [(0, ["a", "b", "c", "d"])], ["a", "b", "c", "d"], ["e", "f", "g"]
        )

    def test_exact(self):
        self.assertMultiBisectRight([(1, ["a"])], ["a"], ["a"])
        self.assertMultiBisectRight([(1, ["a"]), (2, ["b"])], ["a", "b"], ["a", "b"])
        self.assertMultiBisectRight(
            [(1, ["a"]), (3, ["c"])], ["a", "c"], ["a", "b", "c"]
        )

    def test_inbetween(self):
        self.assertMultiBisectRight([(1, ["b"])], ["b"], ["a", "c"])
        self.assertMultiBisectRight(
            [(1, ["b", "c", "d"]), (2, ["f", "g"])],
            ["b", "c", "d", "f", "g"],
            ["a", "e", "h"],
        )

    def test_mixed(self):
        self.assertMultiBisectRight(
            [(0, ["a", "b"]), (2, ["d", "e"]), (4, ["g", "h"])],
            ["a", "b", "d", "e", "g", "h"],
            ["c", "d", "f", "g"],
        )


class TestExpandOffsets(tests.TestCase):
    def make_index(self, size, recommended_pages=None):
        """Make an index with a generic size.

        This doesn't actually create anything on disk, it just primes a
        BTreeGraphIndex with the recommended information.
        """
        index = btree_index.BTreeGraphIndex(
            transport.get_transport_from_url("memory:///"), "test-index", size=size
        )
        if recommended_pages is not None:
            index._recommended_pages = recommended_pages
        return index

    def set_cached_offsets(self, index, cached_offsets):
        """Monkeypatch to give a canned answer for _get_offsets_for...()."""

        def _get_offsets_to_cached_pages():
            cached = set(cached_offsets)
            return cached

        index._get_offsets_to_cached_pages = _get_offsets_to_cached_pages

    def prepare_index(
        self, index, node_ref_lists, key_length, key_count, row_lengths, cached_offsets
    ):
        """Setup the BTreeGraphIndex with some pre-canned information."""
        index.node_ref_lists = node_ref_lists
        index._key_length = key_length
        index._key_count = key_count
        index._row_lengths = row_lengths
        index._compute_row_offsets()
        index._root_node = btree_index._InternalNode(b"internal\noffset=0\n")
        self.set_cached_offsets(index, cached_offsets)

    def make_100_node_index(self):
        index = self.make_index(4096 * 100, 6)
        # Consider we've already made a single request at the middle
        self.prepare_index(
            index,
            node_ref_lists=0,
            key_length=1,
            key_count=1000,
            row_lengths=[1, 99],
            cached_offsets=[0, 50],
        )
        return index

    def make_1000_node_index(self):
        index = self.make_index(4096 * 1000, 6)
        # Pretend we've already made a single request in the middle
        self.prepare_index(
            index,
            node_ref_lists=0,
            key_length=1,
            key_count=90000,
            row_lengths=[1, 9, 990],
            cached_offsets=[0, 5, 500],
        )
        return index

    def assertNumPages(self, expected_pages, index, size):
        index._size = size
        self.assertEqual(expected_pages, index._compute_total_pages_in_index())

    def assertExpandOffsets(self, expected, index, offsets):
        self.assertEqual(
            expected,
            index._expand_offsets(offsets),
            "We did not get the expected value after expanding {}".format(offsets),
        )

    def test_default_recommended_pages(self):
        index = self.make_index(None)
        # local transport recommends 4096 byte reads, which is 1 page
        self.assertEqual(1, index._recommended_pages)

    def test__compute_total_pages_in_index(self):
        index = self.make_index(None)
        self.assertNumPages(1, index, 1024)
        self.assertNumPages(1, index, 4095)
        self.assertNumPages(1, index, 4096)
        self.assertNumPages(2, index, 4097)
        self.assertNumPages(2, index, 8192)
        self.assertNumPages(76, index, 4096 * 75 + 10)

    def test__find_layer_start_and_stop(self):
        index = self.make_1000_node_index()
        self.assertEqual((0, 1), index._find_layer_first_and_end(0))
        self.assertEqual((1, 10), index._find_layer_first_and_end(1))
        self.assertEqual((1, 10), index._find_layer_first_and_end(9))
        self.assertEqual((10, 1000), index._find_layer_first_and_end(10))
        self.assertEqual((10, 1000), index._find_layer_first_and_end(99))
        self.assertEqual((10, 1000), index._find_layer_first_and_end(999))

    def test_unknown_size(self):
        # We should not expand if we don't know the file size
        index = self.make_index(None, 10)
        self.assertExpandOffsets([0], index, [0])
        self.assertExpandOffsets([1, 4, 9], index, [1, 4, 9])

    def test_more_than_recommended(self):
        index = self.make_index(4096 * 100, 2)
        self.assertExpandOffsets([1, 10], index, [1, 10])
        self.assertExpandOffsets([1, 10, 20], index, [1, 10, 20])

    def test_read_all_from_root(self):
        index = self.make_index(4096 * 10, 20)
        self.assertExpandOffsets(list(range(10)), index, [0])

    def test_read_all_when_cached(self):
        # We've read enough that we can grab all the rest in a single request
        index = self.make_index(4096 * 10, 5)
        self.prepare_index(
            index,
            node_ref_lists=0,
            key_length=1,
            key_count=1000,
            row_lengths=[1, 9],
            cached_offsets=[0, 1, 2, 5, 6],
        )
        # It should fill the remaining nodes, regardless of the one requested
        self.assertExpandOffsets([3, 4, 7, 8, 9], index, [3])
        self.assertExpandOffsets([3, 4, 7, 8, 9], index, [8])
        self.assertExpandOffsets([3, 4, 7, 8, 9], index, [9])

    def test_no_root_node(self):
        index = self.make_index(4096 * 10, 5)
        self.assertExpandOffsets([0], index, [0])

    def test_include_neighbors(self):
        index = self.make_100_node_index()
        # We expand in both directions, until we have at least 'recommended'
        # pages
        self.assertExpandOffsets([9, 10, 11, 12, 13, 14, 15], index, [12])
        self.assertExpandOffsets([88, 89, 90, 91, 92, 93, 94], index, [91])
        # If we hit an 'edge' we continue in the other direction
        self.assertExpandOffsets([1, 2, 3, 4, 5, 6], index, [2])
        self.assertExpandOffsets([94, 95, 96, 97, 98, 99], index, [98])

        # Requesting many nodes will expand all locations equally
        self.assertExpandOffsets([1, 2, 3, 80, 81, 82], index, [2, 81])
        self.assertExpandOffsets([1, 2, 3, 9, 10, 11, 80, 81, 82], index, [2, 10, 81])

    def test_stop_at_cached(self):
        index = self.make_100_node_index()
        self.set_cached_offsets(index, [0, 10, 19])
        self.assertExpandOffsets([11, 12, 13, 14, 15, 16], index, [11])
        self.assertExpandOffsets([11, 12, 13, 14, 15, 16], index, [12])
        self.assertExpandOffsets([12, 13, 14, 15, 16, 17, 18], index, [15])
        self.assertExpandOffsets([13, 14, 15, 16, 17, 18], index, [16])
        self.assertExpandOffsets([13, 14, 15, 16, 17, 18], index, [17])
        self.assertExpandOffsets([13, 14, 15, 16, 17, 18], index, [18])

    def test_cannot_fully_expand(self):
        index = self.make_100_node_index()
        self.set_cached_offsets(index, [0, 10, 12])
        # We don't go into an endless loop if we are bound by cached nodes
        self.assertExpandOffsets([11], index, [11])

    def test_overlap(self):
        index = self.make_100_node_index()
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15], index, [12, 13])
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15], index, [11, 14])

    def test_stay_within_layer(self):
        index = self.make_1000_node_index()
        # When expanding a request, we won't read nodes from the next layer
        self.assertExpandOffsets([1, 2, 3, 4], index, [2])
        self.assertExpandOffsets([6, 7, 8, 9], index, [6])
        self.assertExpandOffsets([6, 7, 8, 9], index, [9])
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15], index, [10])
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15, 16], index, [13])

        self.set_cached_offsets(index, [0, 4, 12])
        self.assertExpandOffsets([5, 6, 7, 8, 9], index, [7])
        self.assertExpandOffsets([10, 11], index, [11])

    def test_small_requests_unexpanded(self):
        index = self.make_100_node_index()
        self.set_cached_offsets(index, [0])
        self.assertExpandOffsets([1], index, [1])
        self.assertExpandOffsets([50], index, [50])
        # If we request more than one node, then we'll expand
        self.assertExpandOffsets([49, 50, 51, 59, 60, 61], index, [50, 60])

        # The first pass does not expand
        index = self.make_1000_node_index()
        self.set_cached_offsets(index, [0])
        self.assertExpandOffsets([1], index, [1])
        self.set_cached_offsets(index, [0, 1])
        self.assertExpandOffsets([100], index, [100])
        self.set_cached_offsets(index, [0, 1, 100])
        # But after the first depth, we will expand
        self.assertExpandOffsets([2, 3, 4, 5, 6, 7], index, [2])
        self.assertExpandOffsets([2, 3, 4, 5, 6, 7], index, [4])
        self.set_cached_offsets(index, [0, 1, 2, 3, 4, 5, 6, 7, 100])
        self.assertExpandOffsets([102, 103, 104, 105, 106, 107, 108], index, [105])

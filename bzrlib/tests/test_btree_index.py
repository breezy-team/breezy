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

"""Tests for btree indices."""

import time
import pprint
import zlib

from bzrlib import (
    btree_index,
    errors,
    tests,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    TestScenarioApplier,
    adapt_tests,
    condition_isinstance,
    split_suite_by_condition,
    )
from bzrlib.transport import get_transport


def load_tests(standard_tests, module, loader):
    # parameterise the TestBTreeNodes tests
    node_tests, others = split_suite_by_condition(standard_tests,
        condition_isinstance(TestBTreeNodes))
    applier = TestScenarioApplier()
    import bzrlib._parse_btree_py as py_module
    applier.scenarios = [('python', {'parse_btree': py_module})]
    if CompiledBtreeParserFeature.available():
        # Is there a way to do this that gets missing feature failures rather
        # than no indication to the user?
        import bzrlib._parse_btree_c as c_module
        applier.scenarios.append(('C', {'parse_btree': c_module}))
    adapt_tests(node_tests, applier, others)
    return others


class _CompiledBtreeParserFeature(tests.Feature):
    def _probe(self):
        try:
            import bzrlib._parse_btree_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._parse_btree_c'

CompiledBtreeParserFeature = _CompiledBtreeParserFeature()


class BTreeTestCase(TestCaseWithTransport):
    # test names here are suffixed by the key length and reference list count
    # that they test.

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self._original_header = btree_index._RESERVED_HEADER_BYTES
        def restore():
            btree_index._RESERVED_HEADER_BYTES = self._original_header
        self.addCleanup(restore)
        btree_index._RESERVED_HEADER_BYTES = 100

    def make_nodes(self, count, key_elements, reference_lists):
        """Generate count*key_elements sample nodes."""
        keys = []
        for prefix_pos in range(key_elements):
            if key_elements - 1:
                prefix = (str(prefix_pos) * 40,)
            else:
                prefix = ()
            for pos in range(count):
                key = prefix + (str(pos) * 40,)
                value = "value:%s" % pos
                if reference_lists:
                    # generate some references
                    refs = []
                    for list_pos in range(reference_lists):
                        # as many keys in each list as its index + the key depth
                        # mod 2 - this generates both 0 length lists and
                        # ones slightly longer than the number of lists.
                        # It alsu ensures we have non homogeneous lists.
                        refs.append([])
                        for ref_pos in range(list_pos + pos % 2):
                            if pos % 2:
                                # refer to a nearby key
                                refs[-1].append(prefix + ("ref" + str(pos - 1) * 40,))
                            else:
                                # serial of this ref in the ref list
                                refs[-1].append(prefix + ("ref" + str(ref_pos) * 40,))
                        refs[-1] = tuple(refs[-1])
                    refs = tuple(refs)
                else:
                    refs = ()
                keys.append((key, value, refs))
        return keys


class TestBTreeBuilder(BTreeTestCase):

    def test_empty_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=0\n"
            "row_lengths=\n",
            content)

    def test_empty_2_1(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=1)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=1\nkey_elements=2\nlen=0\n"
            "row_lengths=\n",
            content)

    def test_root_leaf_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(5, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(158, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=5\n"
            "row_lengths=1\n",
            content[:73])
        node_content = content[73:]
        node_bytes = zlib.decompress(node_content)
        expected_node = ("type=leaf\n"
            "0000000000000000000000000000000000000000\x00\x00value:0\n"
            "1111111111111111111111111111111111111111\x00\x00value:1\n"
            "2222222222222222222222222222222222222222\x00\x00value:2\n"
            "3333333333333333333333333333333333333333\x00\x00value:3\n"
            "4444444444444444444444444444444444444444\x00\x00value:4\n")
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
        self.assertEqual(264, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=2\nkey_elements=2\nlen=10\n"
            "row_lengths=1\n",
            content[:74])
        node_content = content[74:]
        node_bytes = zlib.decompress(node_content)
        expected_node = (
            "type=leaf\n"
            "0000000000000000000000000000000000000000\x000000000000000000000000000000000000000000\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:0\n"
            "0000000000000000000000000000000000000000\x001111111111111111111111111111111111111111\x000000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\r0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:1\n"
            "0000000000000000000000000000000000000000\x002222222222222222222222222222222222222222\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:2\n"
            "0000000000000000000000000000000000000000\x003333333333333333333333333333333333333333\x000000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\t0000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\r0000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\x00value:3\n"
            "0000000000000000000000000000000000000000\x004444444444444444444444444444444444444444\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:4\n"
            "1111111111111111111111111111111111111111\x000000000000000000000000000000000000000000\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:0\n"
            "1111111111111111111111111111111111111111\x001111111111111111111111111111111111111111\x001111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\r1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:1\n"
            "1111111111111111111111111111111111111111\x002222222222222222222222222222222222222222\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:2\n"
            "1111111111111111111111111111111111111111\x003333333333333333333333333333333333333333\x001111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\t1111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\r1111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\x00value:3\n"
            "1111111111111111111111111111111111111111\x004444444444444444444444444444444444444444\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:4\n"
            ""
            )
        self.assertEqual(expected_node, node_bytes)

    def test_2_leaves_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(800, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(10646, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=800\n"
            "row_lengths=1,2\n",
            content[:77])
        root = content[77:4096]
        leaf1 = content[4096:8192]
        leaf2 = content[8192:]
        root_bytes = zlib.decompress(root)
        expected_root = (
            "type=internal\n"
            "offset=0\n"
            "503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503503\n"
            )
        self.assertEqual(expected_root, root_bytes)
        # We already know serialisation works for leaves, check key selection:
        leaf1_bytes = zlib.decompress(leaf1)
        sorted_node_keys = sorted(node[0] for node in nodes)
        node = btree_index._LeafNode(leaf1_bytes, 1, 0)
        self.assertEqual(448, len(node.keys))
        self.assertEqual(sorted_node_keys[:448], sorted(node.keys))
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(800 - 448, len(node.keys))
        self.assertEqual(sorted_node_keys[448:], sorted(node.keys))

    def test_last_page_rounded_1_layer(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(10, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(181, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=10\n"
            "row_lengths=1\n",
            content[:74])
        # Check thelast page is well formed
        leaf2 = content[74:]
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(10, len(node.keys))
        sorted_node_keys = sorted(node[0] for node in nodes)
        self.assertEqual(sorted_node_keys, sorted(node.keys))

    def test_last_page_not_rounded_2_layer(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(800, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(10646, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=800\n"
            "row_lengths=1,2\n",
            content[:77])
        # Check thelast page is well formed
        leaf2 = content[8192:]
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(800 - 448, len(node.keys))
        sorted_node_keys = sorted(node[0] for node in nodes)
        self.assertEqual(sorted_node_keys[448:], sorted(node.keys))

    def test_three_level_tree_details(self):
        # The left most pointer in the second internal node in a row should
        # pointer to the second node that the internal node is for, _not_
        # the first, otherwise the first node overlaps with the last node of
        # the prior internal node on that row.
        # We will be adding 200,000 nodes, so spill at 200,001 to prevent
        # having to flush anything out to disk.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2,
            spill_at=200001)
        # 200K nodes is enough to create a two internal nodes on the second level
        tstart = time.time()
        nodes = self.make_nodes(100000, 2, 2)
        delta_make = time.time() - tstart

        tstart = time.time()
        for node in nodes:
            builder.add_node(*node)
        delta = time.time() - tstart
        transport = get_transport('trace+' + self.get_url(''))
        tstart = time.time()
        size = transport.put_file('index', builder.finish())
        delta_flush = time.time() - tstart
        del builder
        # print "\n  Spent %.3fs creating and %.3fs adding nodes and %.3fs flushing" % (delta_make, delta, delta_flush)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        # Seed the metadata, we're using internal calls now.
        index.key_count()
        self.assertEqual(3, len(index._row_lengths),
            "Not enough rows: %r" % index._row_lengths)
        self.assertEqual(4, len(index._row_offsets))
        self.assertEqual(sum(index._row_lengths), index._row_offsets[-1])
        internal_nodes = index._get_internal_nodes([0, 1, 2])
        root_node = internal_nodes[0]
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
        self.assertTrue(internal_node2.keys[0] in leaf.keys)

    def test_2_leaves_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(200, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(10574, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=2\nkey_elements=2\nlen=400\n"
            "row_lengths=1,2\n",
            content[:77])
        root = content[77:4096]
        leaf1 = content[4096:8192]
        leaf2 = content[8192:]
        root_bytes = zlib.decompress(root)
        expected_root = (
            "type=internal\n"
            "offset=0\n"
            "1111111111111111111111111111111111111111\x00"
            "126126126126126126126126126126126126126126126126126126126"
            "126126126126126126126126126126126126126126126126126126126126126\n"
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
        self.assertEqual(1, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        builder.add_node(*nodes[2])
        self.assertEqual(1, len(builder._nodes))
        self.assertEqual(1, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
        # And spills to a second backing index combing all
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # The next spills to the 2-len slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
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
        self.assertEqual([(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()))
        # Two nodes - one memory one disk
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])))
        self.assertEqual(13, builder.key_count())
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])))
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
        transport = self.get_transport('')
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_spill_index_stress_2_2(self):
        # test that references and longer keys don't confuse things.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2,
            spill_at=2)
        nodes = self.make_nodes(16, 2, 2)
        builder.add_node(*nodes[0])
        # Test the parts of the index that take up memory are doing so
        # predictably.
        self.assertEqual(1, len(builder._keys))
        self.assertEqual(2, len(builder._nodes))
        self.assertNotEqual({}, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._keys))
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual({}, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        builder.add_node(*nodes[2])
        self.assertEqual(2, len(builder._nodes))
        self.assertEqual(1, len(builder._keys))
        self.assertNotEqual({}, builder._nodes_by_key)
        # And spills to a second backing index combing all
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # The next spills to the 2-len slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertEqual({}, builder._nodes_by_key)
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
        self.assertEqual([(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()))
        # Two nodes - one memory one disk
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])))
        self.assertEqual(13, builder.key_count())
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])))
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
        transport = self.get_transport('')
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_spill_index_duplicate_key_caught_on_finish(self):
        builder = btree_index.BTreeBuilder(key_elements=1, spill_at=2)
        nodes = [node[0:2] for node in self.make_nodes(16, 1, 0)]
        builder.add_node(*nodes[0])
        builder.add_node(*nodes[1])
        builder.add_node(*nodes[0])
        self.assertRaises(errors.BadIndexDuplicateKey, builder.finish)


class TestBTreeIndex(BTreeTestCase):

    def make_index(self, ref_lists=0, key_elements=1, nodes=[]):
        builder = btree_index.BTreeBuilder(reference_lists=ref_lists,
            key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = get_transport('trace+' + self.get_url())
        size = trans.put_file('index', stream)
        return btree_index.BTreeGraphIndex(trans, 'index', size)

    def test_trivial_constructor(self):
        transport = get_transport('trace+' + self.get_url(''))
        index = btree_index.BTreeGraphIndex(transport, 'index', None)
        # Checks the page size at load, but that isn't logged yet.
        self.assertEqual([], transport._activity)

    def test_with_size_constructor(self):
        transport = get_transport('trace+' + self.get_url(''))
        index = btree_index.BTreeGraphIndex(transport, 'index', 1)
        # Checks the page size at load, but that isn't logged yet.
        self.assertEqual([], transport._activity)

    def test_empty_key_count_no_size(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        transport = get_transport('trace+' + self.get_url(''))
        transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', None)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(0, index.key_count())
        # The entire index should have been requested (as we generally have the
        # size available, and doing many small readvs is inappropriate).
        # We can't tell how much was actually read here, but - check the code.
        self.assertEqual([('get', 'index'),
            ('readv', 'index', [(0, 72)], False, None)],
            transport._activity)

    def test_empty_key_count(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        self.assertEqual(72, size)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(0, index.key_count())
        # The entire index should have been read, as 4K > size
        self.assertEqual([('readv', 'index', [(0, 72)], False, None)],
            transport._activity)

    def test_non_empty_key_count_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(35, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(70, index.key_count())
        # The entire index should have been read, as it is one page long.
        self.assertEqual([('readv', 'index', [(0, size)], False, None)],
            transport._activity)
        self.assertEqual(1593, size)

    def test_2_levels_key_count_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        self.assertEqual(10242, size)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(320, index.key_count())
        # The entire index should not have been read.
        self.assertEqual([('readv', 'index', [(0, 4096)], False, None)],
            transport._activity)

    def test_validate_one_page(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(80, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        index.validate()
        # The entire index should have been read linearly.
        self.assertEqual([('readv', 'index', [(0, size)], False, None)],
            transport._activity)
        self.assertEqual(3846, size)

    def test_validate_two_pages(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        # Root page, 2 leaf pages
        self.assertEqual(10242, size)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        index.validate()
        # The entire index should have been read linearly.
        self.assertEqual([('readv', 'index', [(0, 4096)], False, None),
            ('readv', 'index', [(4096, 4096), (8192, 2050)], False, None)],
            transport._activity)
        # XXX: TODO: write some badly-ordered nodes, and some pointers-to-wrong
        # node and make validate find them.

    def test_eq_ne(self):
        # two indices are equal when constructed with the same parameters:
        transport1 = get_transport('trace+' + self.get_url(''))
        transport2 = get_transport(self.get_url(''))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', None) ==
            btree_index.BTreeGraphIndex(transport1, 'index', None))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) ==
            btree_index.BTreeGraphIndex(transport1, 'index', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) ==
            btree_index.BTreeGraphIndex(transport2, 'index', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'inde1', 20) ==
            btree_index.BTreeGraphIndex(transport1, 'inde2', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', 10) ==
            btree_index.BTreeGraphIndex(transport1, 'index', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', None) !=
            btree_index.BTreeGraphIndex(transport1, 'index', None))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) !=
            btree_index.BTreeGraphIndex(transport1, 'index', 20))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) !=
            btree_index.BTreeGraphIndex(transport2, 'index', 20))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'inde1', 20) !=
            btree_index.BTreeGraphIndex(transport1, 'inde2', 20))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', 10) !=
            btree_index.BTreeGraphIndex(transport1, 'index', 20))

    def test_iter_all_entries_reads(self):
        # iterating all entries reads the header, then does a linear
        # read.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2,
                                           spill_at=200001)
        # 200k nodes is enough to create a three-level index.
        nodes = self.make_nodes(100000, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        self.assertEqual(4058469, size, 'number of expected bytes in the'
                                        ' output changed')
        del builder
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        found_nodes = list(index.iter_all_entries())
        bare_nodes = []
        for node in found_nodes:
            self.assertTrue(node[0] is index)
            bare_nodes.append(node[1:])
        self.assertEqual(3, len(index._row_lengths),
            "Not enough rows: %r" % index._row_lengths)
        # Should be as long as the nodes we supplied
        self.assertEqual(200000, len(found_nodes))
        # Should have the same content
        self.assertEqual(set(nodes), set(bare_nodes))
        # Should have done linear scan IO up the index, ignoring
        # the internal nodes:
        # The entire index should have been read
        total_pages = sum(index._row_lengths)
        self.assertEqual(total_pages, index._row_offsets[-1])
        self.assertEqual(4058469, size)
        # The start of the leaves
        first_byte = index._row_offsets[-2] * btree_index._PAGE_SIZE
        readv_request = []
        for offset in range(first_byte, size, 4096):
            readv_request.append((offset, 4096))
        readv_request[-1] = (readv_request[-1][0], 3429)
        expected = [('readv', 'index', [(0, 4096)], False, None),
             ('readv',  'index', readv_request, False, None)]
        if expected != transport._activity:
            self.assertEqualDiff(pprint.pformat(expected),
                                 pprint.pformat(transport._activity))

    def _test_iter_entries_references_resolved(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', ), ('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),('ref',)),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name',), ('ref',)])))

    def test_iter_entries_references_2_refs_resolved(self):
        # iterating some entries reads just the pages needed. For now, to
        # get it working and start measuring, only 4K pages are read.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 80 nodes is enough to create a two-level index.
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        del builder
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
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
        self.assertEqual([('readv', 'index', [(0, 4096)], False, None),
             ('readv',  'index', [(4096, 4096), ], False, None)],
            transport._activity)

    def test_iter_key_prefix_1_element_key_None(self):
        index = self.make_index()
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([(None, )]))

    def test_iter_key_prefix_wrong_length(self):
        index = self.make_index()
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([('foo', None)]))
        index = self.make_index(key_elements=2)
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([('foo', )]))
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([('foo', None, None)]))

    def test_iter_key_prefix_1_key_element_no_refs(self):
        index = self.make_index( nodes=[
            (('name', ), 'data', ()),
            (('ref', ), 'refdata', ())])
        self.assertEqual(set([(index, ('name', ), 'data'),
            (index, ('ref', ), 'refdata')]),
            set(index.iter_entries_prefix([('name', ), ('ref', )])))

    def test_iter_key_prefix_1_key_element_refs(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', ), ('ref', )])))

    def test_iter_key_prefix_2_key_element_no_refs(self):
        index = self.make_index(key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ()),
            (('name', 'fin2'), 'beta', ()),
            (('ref', 'erence'), 'refdata', ())])
        self.assertEqual(set([(index, ('name', 'fin1'), 'data'),
            (index, ('ref', 'erence'), 'refdata')]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index, ('name', 'fin1'), 'data'),
            (index, ('name', 'fin2'), 'beta')]),
            set(index.iter_entries_prefix([('name', None)])))

    def test_iter_key_prefix_2_key_element_refs(self):
        index = self.make_index(1, key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ([('ref', 'erence')], )),
            (('name', 'fin2'), 'beta', ([], )),
            (('ref', 'erence'), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index, ('ref', 'erence'), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index, ('name', 'fin2'), 'beta', ((), ))]),
            set(index.iter_entries_prefix([('name', None)])))


class TestBTreeNodes(BTreeTestCase):

    def restore_parser(self):
        btree_index._parse_btree = self.saved_parser

    def setUp(self):
        BTreeTestCase.setUp(self)
        self.saved_parser = btree_index._parse_btree
        self.addCleanup(self.restore_parser)
        btree_index._parse_btree = self.parse_btree

    def test_LeafNode_1_0(self):
        node_bytes = ("type=leaf\n"
            "0000000000000000000000000000000000000000\x00\x00value:0\n"
            "1111111111111111111111111111111111111111\x00\x00value:1\n"
            "2222222222222222222222222222222222222222\x00\x00value:2\n"
            "3333333333333333333333333333333333333333\x00\x00value:3\n"
            "4444444444444444444444444444444444444444\x00\x00value:4\n")
        node = btree_index._LeafNode(node_bytes, 1, 0)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual({
            ("0000000000000000000000000000000000000000",): ("value:0", ()),
            ("1111111111111111111111111111111111111111",): ("value:1", ()),
            ("2222222222222222222222222222222222222222",): ("value:2", ()),
            ("3333333333333333333333333333333333333333",): ("value:3", ()),
            ("4444444444444444444444444444444444444444",): ("value:4", ()),
            }, node.keys)

    def test_LeafNode_2_2(self):
        node_bytes = ("type=leaf\n"
            "00\x0000\x00\t00\x00ref00\x00value:0\n"
            "00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n"
            "11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n"
            "11\x0044\x00\t11\x00ref00\x00value:4\n"
            ""
            )
        node = btree_index._LeafNode(node_bytes, 2, 2)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual({
            ('00', '00'): ('value:0', ((), (('00', 'ref00'),))),
            ('00', '11'): ('value:1',
                ((('00', 'ref00'),), (('00', 'ref00'), ('01', 'ref01')))),
            ('11', '33'): ('value:3',
                ((('11', 'ref22'),), (('11', 'ref22'), ('11', 'ref22')))),
            ('11', '44'): ('value:4', ((), (('11', 'ref00'),)))
            }, node.keys)

    def test_InternalNode_1(self):
        node_bytes = ("type=internal\n"
            "offset=1\n"
            "0000000000000000000000000000000000000000\n"
            "1111111111111111111111111111111111111111\n"
            "2222222222222222222222222222222222222222\n"
            "3333333333333333333333333333333333333333\n"
            "4444444444444444444444444444444444444444\n"
            )
        node = btree_index._InternalNode(node_bytes)
        # We want to bisect to find the right children from this node, so a
        # vector is most useful.
        self.assertEqual([
            ("0000000000000000000000000000000000000000",),
            ("1111111111111111111111111111111111111111",),
            ("2222222222222222222222222222222222222222",),
            ("3333333333333333333333333333333333333333",),
            ("4444444444444444444444444444444444444444",),
            ], node.keys)
        self.assertEqual(1, node.offset)

    def test_LeafNode_2_2(self):
        node_bytes = ("type=leaf\n"
            "00\x0000\x00\t00\x00ref00\x00value:0\n"
            "00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n"
            "11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n"
            "11\x0044\x00\t11\x00ref00\x00value:4\n"
            ""
            )
        node = btree_index._LeafNode(node_bytes, 2, 2)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual({
            ('00', '00'): ('value:0', ((), (('00', 'ref00'),))),
            ('00', '11'): ('value:1',
                ((('00', 'ref00'),), (('00', 'ref00'), ('01', 'ref01')))),
            ('11', '33'): ('value:3',
                ((('11', 'ref22'),), (('11', 'ref22'), ('11', 'ref22')))),
            ('11', '44'): ('value:4', ((), (('11', 'ref00'),)))
            }, node.keys)


class TestCompiledBtree(tests.TestCase):

    def test_exists(self):
        # This is just to let the user know if they don't have the feature
        # available
        self.requireFeature(CompiledBtreeParserFeature)


class TestMultiBisectRight(tests.TestCase):

    def assertMultiBisectRight(self, offsets, search_keys, fixed_keys):
        self.assertEqual(offsets,
                         btree_index.BTreeGraphIndex._multi_bisect_right(
                            search_keys, fixed_keys))

    def test_after(self):
        self.assertMultiBisectRight([(1, ['b'])], ['b'], ['a'])
        self.assertMultiBisectRight([(3, ['e', 'f', 'g'])],
                                    ['e', 'f', 'g'], ['a', 'b', 'c'])

    def test_before(self):
        self.assertMultiBisectRight([(0, ['a'])], ['a'], ['b'])
        self.assertMultiBisectRight([(0, ['a', 'b', 'c', 'd'])],
                                    ['a', 'b', 'c', 'd'], ['e', 'f', 'g'])

    def test_exact(self):
        self.assertMultiBisectRight([(1, ['a'])], ['a'], ['a'])
        self.assertMultiBisectRight([(1, ['a']), (2, ['b'])], ['a', 'b'], ['a', 'b'])
        self.assertMultiBisectRight([(1, ['a']), (3, ['c'])],
                                    ['a', 'c'], ['a', 'b', 'c'])

    def test_inbetween(self):
        self.assertMultiBisectRight([(1, ['b'])], ['b'], ['a', 'c'])
        self.assertMultiBisectRight([(1, ['b', 'c', 'd']), (2, ['f', 'g'])],
                                    ['b', 'c', 'd', 'f', 'g'], ['a', 'e', 'h'])

    def test_mixed(self):
        self.assertMultiBisectRight([(0, ['a', 'b']), (2, ['d', 'e']),
                                     (4, ['g', 'h'])],
                                    ['a', 'b', 'd', 'e', 'g', 'h'],
                                    ['c', 'd', 'f', 'g'])

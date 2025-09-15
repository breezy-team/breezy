# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for indices."""

from ... import tests, transport
from .. import index as _mod_index


class ErrorTests(tests.TestCase):
    def test_bad_index_format_signature(self):
        error = _mod_index.BadIndexFormatSignature("foo", "bar")
        self.assertEqual("foo is not an index of type bar.", str(error))

    def test_bad_index_data(self):
        error = _mod_index.BadIndexData("foo")
        self.assertEqual("Error in data for index foo.", str(error))

    def test_bad_index_duplicate_key(self):
        error = _mod_index.BadIndexDuplicateKey("foo", "bar")
        self.assertEqual("The key 'foo' is already in index 'bar'.", str(error))

    def test_bad_index_key(self):
        error = _mod_index.BadIndexKey("foo")
        self.assertEqual("The key 'foo' is not a valid key.", str(error))

    def test_bad_index_options(self):
        error = _mod_index.BadIndexOptions("foo")
        self.assertEqual("Could not parse options for index foo.", str(error))

    def test_bad_index_value(self):
        error = _mod_index.BadIndexValue("foo")
        self.assertEqual("The value 'foo' is not a valid value.", str(error))


class TestGraphIndexBuilder(tests.TestCaseWithMemoryTransport):
    def test_build_index_empty(self):
        builder = _mod_index.GraphIndexBuilder()
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=0\n\n",
            contents,
        )

    def test_build_index_empty_two_element_keys(self):
        builder = _mod_index.GraphIndexBuilder(key_elements=2)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=2\nlen=0\n\n",
            contents,
        )

    def test_build_index_one_reference_list_empty(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=0\n\n",
            contents,
        )

    def test_build_index_two_reference_list_empty(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=0\n\n",
            contents,
        )

    def test_build_index_one_node_no_refs(self):
        builder = _mod_index.GraphIndexBuilder()
        builder.add_node((b"akey",), b"data")
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=1\n"
            b"akey\x00\x00\x00data\n\n",
            contents,
        )

    def test_build_index_one_node_no_refs_accepts_empty_reflist(self):
        builder = _mod_index.GraphIndexBuilder()
        builder.add_node((b"akey",), b"data", ())
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=1\n"
            b"akey\x00\x00\x00data\n\n",
            contents,
        )

    def test_build_index_one_node_2_element_keys(self):
        # multipart keys are separated by \x00 - because they are fixed length,
        # not variable this does not cause any issues, and seems clearer to the
        # author.
        builder = _mod_index.GraphIndexBuilder(key_elements=2)
        builder.add_node((b"akey", b"secondpart"), b"data")
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=2\nlen=1\n"
            b"akey\x00secondpart\x00\x00\x00data\n\n",
            contents,
        )

    def test_add_node_empty_value(self):
        builder = _mod_index.GraphIndexBuilder()
        builder.add_node((b"akey",), b"")
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=1\n"
            b"akey\x00\x00\x00\n\n",
            contents,
        )

    def test_build_index_nodes_sorted(self):
        # the highest sorted node comes first.
        builder = _mod_index.GraphIndexBuilder()
        # use three to have a good chance of glitching dictionary hash
        # lookups etc. Insert in randomish order that is not correct
        # and not the reverse of the correct order.
        builder.add_node((b"2002",), b"data")
        builder.add_node((b"2000",), b"data")
        builder.add_node((b"2001",), b"data")
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=3\n"
            b"2000\x00\x00\x00data\n"
            b"2001\x00\x00\x00data\n"
            b"2002\x00\x00\x00data\n"
            b"\n",
            contents,
        )

    def test_build_index_2_element_key_nodes_sorted(self):
        # multiple element keys are sorted first-key, second-key.
        builder = _mod_index.GraphIndexBuilder(key_elements=2)
        # use three values of each key element, to have a good chance of
        # glitching dictionary hash lookups etc. Insert in randomish order that
        # is not correct and not the reverse of the correct order.
        builder.add_node((b"2002", b"2002"), b"data")
        builder.add_node((b"2002", b"2000"), b"data")
        builder.add_node((b"2002", b"2001"), b"data")
        builder.add_node((b"2000", b"2002"), b"data")
        builder.add_node((b"2000", b"2000"), b"data")
        builder.add_node((b"2000", b"2001"), b"data")
        builder.add_node((b"2001", b"2002"), b"data")
        builder.add_node((b"2001", b"2000"), b"data")
        builder.add_node((b"2001", b"2001"), b"data")
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=2\nlen=9\n"
            b"2000\x002000\x00\x00\x00data\n"
            b"2000\x002001\x00\x00\x00data\n"
            b"2000\x002002\x00\x00\x00data\n"
            b"2001\x002000\x00\x00\x00data\n"
            b"2001\x002001\x00\x00\x00data\n"
            b"2001\x002002\x00\x00\x00data\n"
            b"2002\x002000\x00\x00\x00data\n"
            b"2002\x002001\x00\x00\x00data\n"
            b"2002\x002002\x00\x00\x00data\n"
            b"\n",
            contents,
        )

    def test_build_index_reference_lists_are_included_one(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        builder.add_node((b"key",), b"data", ([],))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=1\n"
            b"key\x00\x00\x00data\n"
            b"\n",
            contents,
        )

    def test_build_index_reference_lists_with_2_element_keys(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1, key_elements=2)
        builder.add_node((b"key", b"key2"), b"data", ([],))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=2\nlen=1\n"
            b"key\x00key2\x00\x00\x00data\n"
            b"\n",
            contents,
        )

    def test_build_index_reference_lists_are_included_two(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        builder.add_node((b"key",), b"data", ([], []))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=1\n"
            b"key\x00\x00\t\x00data\n"
            b"\n",
            contents,
        )

    def test_clear_cache(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        # This is a no-op, but the api should exist
        builder.clear_cache()

    def test_node_references_are_byte_offsets(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        builder.add_node((b"reference",), b"data", ([],))
        builder.add_node((b"key",), b"data", ([(b"reference",)],))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=2\n"
            b"key\x00\x0072\x00data\n"
            b"reference\x00\x00\x00data\n"
            b"\n",
            contents,
        )

    def test_node_references_are_cr_delimited(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        builder.add_node((b"reference",), b"data", ([],))
        builder.add_node((b"reference2",), b"data", ([],))
        builder.add_node((b"key",), b"data", ([(b"reference",), (b"reference2",)],))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=3\n"
            b"key\x00\x00077\r094\x00data\n"
            b"reference\x00\x00\x00data\n"
            b"reference2\x00\x00\x00data\n"
            b"\n",
            contents,
        )

    def test_multiple_reference_lists_are_tab_delimited(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        builder.add_node((b"keference",), b"data", ([], []))
        builder.add_node((b"rey",), b"data", ([(b"keference",)], [(b"keference",)]))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=2\n"
            b"keference\x00\x00\t\x00data\n"
            b"rey\x00\x0059\t59\x00data\n"
            b"\n",
            contents,
        )

    def test_add_node_referencing_missing_key_makes_absent(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        builder.add_node((b"rey",), b"data", ([(b"beference",), (b"aeference2",)],))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=1\n"
            b"aeference2\x00a\x00\x00\n"
            b"beference\x00a\x00\x00\n"
            b"rey\x00\x00074\r059\x00data\n"
            b"\n",
            contents,
        )

    def test_node_references_three_digits(self):
        # test the node digit expands as needed.
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        references = [((b"%d" % val),) for val in range(8, -1, -1)]
        builder.add_node((b"2-key",), b"", (references,))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqualDiff(
            b"Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=1\n"
            b"0\x00a\x00\x00\n"
            b"1\x00a\x00\x00\n"
            b"2\x00a\x00\x00\n"
            b"2-key\x00\x00151\r145\r139\r133\r127\r121\r071\r065\r059\x00\n"
            b"3\x00a\x00\x00\n"
            b"4\x00a\x00\x00\n"
            b"5\x00a\x00\x00\n"
            b"6\x00a\x00\x00\n"
            b"7\x00a\x00\x00\n"
            b"8\x00a\x00\x00\n"
            b"\n",
            contents,
        )

    def test_absent_has_no_reference_overhead(self):
        # the offsets after an absent record should be correct when there are
        # >1 reference lists.
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        builder.add_node((b"parent",), b"", ([(b"aail",), (b"zther",)], []))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            b"Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=1\n"
            b"aail\x00a\x00\x00\n"
            b"parent\x00\x0059\r84\t\x00\n"
            b"zther\x00a\x00\x00\n"
            b"\n",
            contents,
        )

    def test_add_node_bad_key(self):
        builder = _mod_index.GraphIndexBuilder()
        for bad_char in bytearray(b"\t\n\x0b\x0c\r\x00 "):
            self.assertRaises(
                _mod_index.BadIndexKey,
                builder.add_node,
                (b"a%skey" % bytes([bad_char]),),
                b"data",
            )
        self.assertRaises(_mod_index.BadIndexKey, builder.add_node, (), b"data")
        self.assertRaises(
            _mod_index.BadIndexKey, builder.add_node, b"not-a-tuple", b"data"
        )
        # not enough length
        self.assertRaises(_mod_index.BadIndexKey, builder.add_node, (), b"data")
        # too long
        self.assertRaises(
            _mod_index.BadIndexKey,
            builder.add_node,
            (b"primary", b"secondary"),
            b"data",
        )
        # secondary key elements get checked too:
        builder = _mod_index.GraphIndexBuilder(key_elements=2)
        for bad_char in bytearray(b"\t\n\x0b\x0c\r\x00 "):
            self.assertRaises(
                _mod_index.BadIndexKey,
                builder.add_node,
                (b"prefix", b"a%skey" % bytes([bad_char])),
                b"data",
            )

    def test_add_node_bad_data(self):
        builder = _mod_index.GraphIndexBuilder()
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data\naa"
        )
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data\x00aa"
        )

    def test_add_node_bad_mismatched_ref_lists_length(self):
        builder = _mod_index.GraphIndexBuilder()
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data aa", ([],)
        )
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data aa"
        )
        self.assertRaises(
            _mod_index.BadIndexValue,
            builder.add_node,
            (b"akey",),
            b"data aa",
            (),
        )
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data aa", ([], [])
        )
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data aa"
        )
        self.assertRaises(
            _mod_index.BadIndexValue, builder.add_node, (b"akey",), b"data aa", ([],)
        )
        self.assertRaises(
            _mod_index.BadIndexValue,
            builder.add_node,
            (b"akey",),
            b"data aa",
            ([], [], []),
        )

    def test_add_node_bad_key_in_reference_lists(self):
        # first list, first key - trivial
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        self.assertRaises(
            _mod_index.BadIndexKey,
            builder.add_node,
            (b"akey",),
            b"data aa",
            ([(b"a key",)],),
        )
        # references keys must be tuples too
        self.assertRaises(
            _mod_index.BadIndexKey,
            builder.add_node,
            (b"akey",),
            b"data aa",
            (["not-a-tuple"],),
        )
        # not enough length
        self.assertRaises(
            _mod_index.BadIndexKey, builder.add_node, (b"akey",), b"data aa", ([()],)
        )
        # too long
        self.assertRaises(
            _mod_index.BadIndexKey,
            builder.add_node,
            (b"akey",),
            b"data aa",
            ([(b"primary", b"secondary")],),
        )
        # need to check more than the first key in the list
        self.assertRaises(
            _mod_index.BadIndexKey,
            builder.add_node,
            (b"akey",),
            b"data aa",
            ([(b"agoodkey",), (b"that is a bad key",)],),
        )
        # and if there is more than one list it should be getting checked
        # too
        builder = _mod_index.GraphIndexBuilder(reference_lists=2)
        self.assertRaises(
            _mod_index.BadIndexKey,
            builder.add_node,
            (b"akey",),
            b"data aa",
            ([], ["a bad key"]),
        )

    def test_add_duplicate_key(self):
        builder = _mod_index.GraphIndexBuilder()
        builder.add_node((b"key",), b"data")
        self.assertRaises(
            _mod_index.BadIndexDuplicateKey, builder.add_node, (b"key",), b"data"
        )

    def test_add_duplicate_key_2_elements(self):
        builder = _mod_index.GraphIndexBuilder(key_elements=2)
        builder.add_node((b"key", b"key"), b"data")
        self.assertRaises(
            _mod_index.BadIndexDuplicateKey, builder.add_node, (b"key", b"key"), b"data"
        )

    def test_add_key_after_referencing_key(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1)
        builder.add_node((b"key",), b"data", ([(b"reference",)],))
        builder.add_node((b"reference",), b"data", ([],))

    def test_add_key_after_referencing_key_2_elements(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1, key_elements=2)
        builder.add_node((b"k", b"ey"), b"data", ([(b"reference", b"tokey")],))
        builder.add_node((b"reference", b"tokey"), b"data", ([],))

    def test_set_optimize(self):
        builder = _mod_index.GraphIndexBuilder(reference_lists=1, key_elements=2)
        builder.set_optimize(for_size=True)
        self.assertTrue(builder._optimize_for_size)
        builder.set_optimize(for_size=False)
        self.assertFalse(builder._optimize_for_size)


class TestGraphIndex(tests.TestCaseWithMemoryTransport):
    def make_key(self, number):
        return ((b"%d" % number) + b"X" * 100,)

    def make_value(self, number):
        return (b"%d" % number) + b"Y" * 100

    def make_nodes(self, count=64):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        nodes = []
        for counter in range(count):
            nodes.append((self.make_key(counter), self.make_value(counter), ()))
        return nodes

    def make_index(self, ref_lists=0, key_elements=1, nodes=None):
        if nodes is None:
            nodes = []
        builder = _mod_index.GraphIndexBuilder(ref_lists, key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = transport.get_transport_from_url("trace+" + self.get_url())
        size = trans.put_file("index", stream)
        return _mod_index.GraphIndex(trans, "index", size)

    def make_index_with_offset(self, ref_lists=0, key_elements=1, nodes=None, offset=0):
        if nodes is None:
            nodes = []
        builder = _mod_index.GraphIndexBuilder(ref_lists, key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        content = builder.finish().read()
        size = len(content)
        trans = self.get_transport()
        trans.put_bytes("index", (b" " * offset) + content)
        return _mod_index.GraphIndex(trans, "index", size, offset=offset)

    def test_clear_cache(self):
        index = self.make_index()
        # For now, we just want to make sure the api is available. As this is
        # old code, we don't really worry if it *does* anything.
        index.clear_cache()

    def test_open_bad_index_no_error(self):
        trans = self.get_transport()
        trans.put_bytes("name", b"not an index\n")
        _mod_index.GraphIndex(trans, "name", 13)

    def test_with_offset(self):
        nodes = self.make_nodes(200)
        idx = self.make_index_with_offset(offset=1234567, nodes=nodes)
        self.assertEqual(200, idx.key_count())

    def test_buffer_all_with_offset(self):
        nodes = self.make_nodes(200)
        idx = self.make_index_with_offset(offset=1234567, nodes=nodes)
        idx._buffer_all()
        self.assertEqual(200, idx.key_count())

    def test_side_effect_buffering_with_offset(self):
        nodes = self.make_nodes(20)
        index = self.make_index_with_offset(offset=1234567, nodes=nodes)
        index._transport.recommended_page_size = lambda: 64 * 1024
        subset_nodes = [nodes[0][0], nodes[10][0], nodes[19][0]]
        entries = [n[1] for n in index.iter_entries(subset_nodes)]
        self.assertEqual(sorted(subset_nodes), sorted(entries))
        self.assertEqual(20, index.key_count())

    def test_open_sets_parsed_map_empty(self):
        index = self.make_index()
        self.assertEqual([], index._parsed_byte_map)
        self.assertEqual([], index._parsed_key_map)

    def test_key_count_buffers(self):
        index = self.make_index(nodes=self.make_nodes(2))
        # reset the transport log
        del index._transport._activity[:]
        self.assertEqual(2, index.key_count())
        # We should have requested reading the header bytes
        self.assertEqual(
            [
                ("readv", "index", [(0, 200)], True, index._size),
            ],
            index._transport._activity,
        )
        # And that should have been enough to trigger reading the whole index
        # with buffering
        self.assertIsNot(None, index._nodes)

    def test_lookup_key_via_location_buffers(self):
        index = self.make_index()
        # reset the transport log
        del index._transport._activity[:]
        # do a _lookup_keys_via_location call for the middle of the file, which
        # is what bisection uses.
        result = index._lookup_keys_via_location([(index._size // 2, (b"missing",))])
        # this should have asked for a readv request, with adjust_for_latency,
        # and two regions: the header, and half-way into the file.
        self.assertEqual(
            [
                ("readv", "index", [(30, 30), (0, 200)], True, 60),
            ],
            index._transport._activity,
        )
        # and the result should be that the key cannot be present, because this
        # is a trivial index.
        self.assertEqual([((index._size // 2, (b"missing",)), False)], result)
        # And this should have caused the file to be fully buffered
        self.assertIsNot(None, index._nodes)
        self.assertEqual([], index._parsed_byte_map)

    def test_first_lookup_key_via_location(self):
        # We need enough data so that the _HEADER_READV doesn't consume the
        # whole file. We always read 800 bytes for every key, and the local
        # transport natural expansion is 4096 bytes. So we have to have >8192
        # bytes or we will trigger "buffer_all".
        # We also want the 'missing' key to fall within the range that *did*
        # read
        index = self.make_index(nodes=self.make_nodes(64))
        # reset the transport log
        del index._transport._activity[:]
        # do a _lookup_keys_via_location call for the middle of the file, which
        # is what bisection uses.
        start_lookup = index._size // 2
        result = index._lookup_keys_via_location([(start_lookup, (b"40missing",))])
        # this should have asked for a readv request, with adjust_for_latency,
        # and two regions: the header, and half-way into the file.
        self.assertEqual(
            [
                ("readv", "index", [(start_lookup, 800), (0, 200)], True, index._size),
            ],
            index._transport._activity,
        )
        # and the result should be that the key cannot be present, because this
        # is a trivial index.
        self.assertEqual([((start_lookup, (b"40missing",)), False)], result)
        # And this should not have caused the file to be fully buffered
        self.assertIs(None, index._nodes)
        # And the regions of the file that have been parsed should be in the
        # parsed_byte_map and the parsed_key_map
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(26)), (self.make_key(31), self.make_key(48))],
            index._parsed_key_map,
        )

    def test_parsing_non_adjacent_data_trims(self):
        index = self.make_index(nodes=self.make_nodes(64))
        result = index._lookup_keys_via_location([(index._size // 2, (b"40",))])
        # and the result should be that the key cannot be present, because key is
        # in the middle of the observed data from a 4K read - the smallest transport
        # will do today with this api.
        self.assertEqual([((index._size // 2, (b"40",)), False)], result)
        # and we should have a parse map that includes the header and the
        # region that was parsed after trimming.
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(26)), (self.make_key(31), self.make_key(48))],
            index._parsed_key_map,
        )

    def test_parsing_data_handles_parsed_contained_regions(self):
        # the following patten creates a parsed region that is wholly within a
        # single result from the readv layer:
        # .... single-read (readv-minimum-size) ...
        # which then trims the start and end so the parsed size is < readv
        # miniumum.
        # then a dual lookup (or a reference lookup for that matter) which
        # abuts or overlaps the parsed region on both sides will need to
        # discard the data in the middle, but parse the end as well.
        #
        # we test this by doing a single lookup to seed the data, then
        # a lookup for two keys that are present, and adjacent -
        # we except both to be found, and the parsed byte map to include the
        # locations of both keys.
        index = self.make_index(nodes=self.make_nodes(128))
        result = index._lookup_keys_via_location([(index._size // 2, (b"40",))])
        # and we should have a parse map that includes the header and the
        # region that was parsed after trimming.
        self.assertEqual([(0, 4045), (11759, 15707)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(116)), (self.make_key(35), self.make_key(51))],
            index._parsed_key_map,
        )
        # now ask for two keys, right before and after the parsed region
        result = index._lookup_keys_via_location(
            [(11450, self.make_key(34)), (15707, self.make_key(52))]
        )
        self.assertEqual(
            [
                (
                    (11450, self.make_key(34)),
                    (index, self.make_key(34), self.make_value(34)),
                ),
                (
                    (15707, self.make_key(52)),
                    (index, self.make_key(52), self.make_value(52)),
                ),
            ],
            result,
        )
        self.assertEqual([(0, 4045), (9889, 17993)], index._parsed_byte_map)

    def test_lookup_missing_key_answers_without_io_when_map_permits(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # lookup the keys in the middle of the file
        result = index._lookup_keys_via_location([(index._size // 2, (b"40",))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(26)), (self.make_key(31), self.make_key(48))],
            index._parsed_key_map,
        )
        # reset the transport log
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # not create a new transport request, and should return False (cannot
        # be in the index) - even when the byte location we ask for is outside
        # the parsed region
        result = index._lookup_keys_via_location([(4000, (b"40",))])
        self.assertEqual([((4000, (b"40",)), False)], result)
        self.assertEqual([], index._transport._activity)

    def test_lookup_present_key_answers_without_io_when_map_permits(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # lookup the keys in the middle of the file
        result = index._lookup_keys_via_location([(index._size // 2, (b"40",))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(26)), (self.make_key(31), self.make_key(48))],
            index._parsed_key_map,
        )
        # reset the transport log
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # not create a new transport request, and should return False (cannot
        # be in the index) - even when the byte location we ask for is outside
        # the parsed region
        #
        result = index._lookup_keys_via_location([(4000, self.make_key(40))])
        self.assertEqual(
            [
                (
                    (4000, self.make_key(40)),
                    (index, self.make_key(40), self.make_value(40)),
                )
            ],
            result,
        )
        self.assertEqual([], index._transport._activity)

    def test_lookup_key_below_probed_area(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # ask for the key in the middle, but a key that is located in the
        # unparsed region before the middle.
        result = index._lookup_keys_via_location([(index._size // 2, (b"30",))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(26)), (self.make_key(31), self.make_key(48))],
            index._parsed_key_map,
        )
        self.assertEqual([((index._size // 2, (b"30",)), -1)], result)

    def test_lookup_key_above_probed_area(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # ask for the key in the middle, but a key that is located in the
        # unparsed region after the middle.
        result = index._lookup_keys_via_location([(index._size // 2, (b"50",))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(26)), (self.make_key(31), self.make_key(48))],
            index._parsed_key_map,
        )
        self.assertEqual([((index._size // 2, (b"50",)), +1)], result)

    def test_lookup_key_resolves_references(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        nodes = []
        for counter in range(99):
            nodes.append(
                (
                    self.make_key(counter),
                    self.make_value(counter),
                    ((self.make_key(counter + 20),),),
                )
            )
        index = self.make_index(ref_lists=1, nodes=nodes)
        # lookup a key in the middle that does not exist, so that when we can
        # check that the referred-to-keys are not accessed automatically.
        index_size = index._size
        index_center = index_size // 2
        result = index._lookup_keys_via_location([(index_center, (b"40",))])
        # check the parse map - only the start and middle should have been
        # parsed.
        self.assertEqual([(0, 4027), (10198, 14028)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(17)), (self.make_key(44), self.make_key(5))],
            index._parsed_key_map,
        )
        # and check the transport activity likewise.
        self.assertEqual(
            [("readv", "index", [(index_center, 800), (0, 200)], True, index_size)],
            index._transport._activity,
        )
        # reset the transport log for testing the reference lookup
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # only perform IO to resolve its key references.
        result = index._lookup_keys_via_location([(11000, self.make_key(45))])
        self.assertEqual(
            [
                (
                    (11000, self.make_key(45)),
                    (
                        index,
                        self.make_key(45),
                        self.make_value(45),
                        ((self.make_key(65),),),
                    ),
                )
            ],
            result,
        )
        self.assertEqual(
            [("readv", "index", [(15093, 800)], True, index_size)],
            index._transport._activity,
        )

    def test_lookup_key_can_buffer_all(self):
        nodes = []
        for counter in range(64):
            nodes.append(
                (
                    self.make_key(counter),
                    self.make_value(counter),
                    ((self.make_key(counter + 20),),),
                )
            )
        index = self.make_index(ref_lists=1, nodes=nodes)
        # lookup a key in the middle that does not exist, so that when we can
        # check that the referred-to-keys are not accessed automatically.
        index_size = index._size
        index_center = index_size // 2
        result = index._lookup_keys_via_location([(index_center, (b"40",))])
        # check the parse map - only the start and middle should have been
        # parsed.
        self.assertEqual([(0, 3890), (6444, 10274)], index._parsed_byte_map)
        self.assertEqual(
            [((), self.make_key(25)), (self.make_key(37), self.make_key(52))],
            index._parsed_key_map,
        )
        # and check the transport activity likewise.
        self.assertEqual(
            [("readv", "index", [(index_center, 800), (0, 200)], True, index_size)],
            index._transport._activity,
        )
        # reset the transport log for testing the reference lookup
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # only perform IO to resolve its key references.
        result = index._lookup_keys_via_location([(7000, self.make_key(40))])
        self.assertEqual(
            [
                (
                    (7000, self.make_key(40)),
                    (
                        index,
                        self.make_key(40),
                        self.make_value(40),
                        ((self.make_key(60),),),
                    ),
                )
            ],
            result,
        )
        # Resolving the references would have required more data read, and we
        # are already above the 50% threshold, so it triggered a _buffer_all
        self.assertEqual([("get", "index")], index._transport._activity)

    def test_iter_all_entries_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index = self.make_index(nodes=[((b"name",), b"data", ())])
        self.assertEqual([(index, (b"name",), b"data")], list(index.iter_all_entries()))

    def test_iter_all_entries_simple_2_elements(self):
        index = self.make_index(
            key_elements=2, nodes=[((b"name", b"surname"), b"data", ())]
        )
        self.assertEqual(
            [(index, (b"name", b"surname"), b"data")], list(index.iter_all_entries())
        )

    def test_iter_all_entries_references_resolved(self):
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
            set(index.iter_all_entries()),
        )

    def test_iter_entries_buffers_once(self):
        index = self.make_index(nodes=self.make_nodes(2))
        # reset the transport log
        del index._transport._activity[:]
        self.assertEqual(
            {(index, self.make_key(1), self.make_value(1))},
            set(index.iter_entries([self.make_key(1)])),
        )
        # We should have requested reading the header bytes
        # But not needed any more than that because it would have triggered a
        # buffer all
        self.assertEqual(
            [
                ("readv", "index", [(0, 200)], True, index._size),
            ],
            index._transport._activity,
        )
        # And that should have been enough to trigger reading the whole index
        # with buffering
        self.assertIsNot(None, index._nodes)

    def test_iter_entries_buffers_by_bytes_read(self):
        index = self.make_index(nodes=self.make_nodes(64))
        list(index.iter_entries([self.make_key(10)]))
        # The first time through isn't enough to trigger a buffer all
        self.assertIs(None, index._nodes)
        self.assertEqual(4096, index._bytes_read)
        # Grabbing a key in that same page won't trigger a buffer all, as we
        # still haven't read 50% of the file
        list(index.iter_entries([self.make_key(11)]))
        self.assertIs(None, index._nodes)
        self.assertEqual(4096, index._bytes_read)
        # We haven't read more data, so reading outside the range won't trigger
        # a buffer all right away
        list(index.iter_entries([self.make_key(40)]))
        self.assertIs(None, index._nodes)
        self.assertEqual(8192, index._bytes_read)
        # On the next pass, we will not trigger buffer all if the key is
        # available without reading more
        list(index.iter_entries([self.make_key(32)]))
        self.assertIs(None, index._nodes)
        # But if we *would* need to read more to resolve it, then we will
        # buffer all.
        list(index.iter_entries([self.make_key(60)]))
        self.assertIsNot(None, index._nodes)

    def test_iter_entries_references_resolved(self):
        index = self.make_index(
            1,
            nodes=[
                ((b"name",), b"data", ([(b"ref",), (b"ref",)],)),
                ((b"ref",), b"refdata", ([],)),
            ],
        )
        self.assertEqual(
            {
                (index, (b"name",), b"data", (((b"ref",), (b"ref",)),)),
                (index, (b"ref",), b"refdata", ((),)),
            },
            set(index.iter_entries([(b"name",), (b"ref",)])),
        )

    def test_iter_entries_references_2_refs_resolved(self):
        index = self.make_index(
            2,
            nodes=[
                ((b"name",), b"data", ([(b"ref",)], [(b"ref",)])),
                ((b"ref",), b"refdata", ([], [])),
            ],
        )
        self.assertEqual(
            {
                (index, (b"name",), b"data", (((b"ref",),), ((b"ref",),))),
                (index, (b"ref",), b"refdata", ((), ())),
            },
            set(index.iter_entries([(b"name",), (b"ref",)])),
        )

    def test_iteration_absent_skipped(self):
        index = self.make_index(1, nodes=[((b"name",), b"data", ([(b"ref",)],))])
        self.assertEqual(
            {(index, (b"name",), b"data", (((b"ref",),),))},
            set(index.iter_all_entries()),
        )
        self.assertEqual(
            {(index, (b"name",), b"data", (((b"ref",),),))},
            set(index.iter_entries([(b"name",)])),
        )
        self.assertEqual([], list(index.iter_entries([(b"ref",)])))

    def test_iteration_absent_skipped_2_element_keys(self):
        index = self.make_index(
            1,
            key_elements=2,
            nodes=[((b"name", b"fin"), b"data", ([(b"ref", b"erence")],))],
        )
        self.assertEqual(
            [(index, (b"name", b"fin"), b"data", (((b"ref", b"erence"),),))],
            list(index.iter_all_entries()),
        )
        self.assertEqual(
            [(index, (b"name", b"fin"), b"data", (((b"ref", b"erence"),),))],
            list(index.iter_entries([(b"name", b"fin")])),
        )
        self.assertEqual([], list(index.iter_entries([(b"ref", b"erence")])))

    def test_iter_all_keys(self):
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
            set(index.iter_entries([(b"name",), (b"ref",)])),
        )

    def test_iter_nothing_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_missing_entry_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([(b"a",)])))

    def test_iter_missing_entry_empty_no_size(self):
        idx = self.make_index()
        idx = _mod_index.GraphIndex(idx._transport, "index", None)
        self.assertEqual([], list(idx.iter_entries([(b"a",)])))

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

    def test_key_count_empty(self):
        index = self.make_index()
        self.assertEqual(0, index.key_count())

    def test_key_count_one(self):
        index = self.make_index(nodes=[((b"name",), b"", ())])
        self.assertEqual(1, index.key_count())

    def test_key_count_two(self):
        index = self.make_index(nodes=[((b"name",), b"", ()), ((b"foo",), b"", ())])
        self.assertEqual(2, index.key_count())

    def test_read_and_parse_tracks_real_read_value(self):
        index = self.make_index(nodes=self.make_nodes(10))
        del index._transport._activity[:]
        index._read_and_parse([(0, 200)])
        self.assertEqual(
            [
                ("readv", "index", [(0, 200)], True, index._size),
            ],
            index._transport._activity,
        )
        # The readv expansion code will expand the initial request to 4096
        # bytes, which is more than enough to read the entire index, and we
        # will track the fact that we read that many bytes.
        self.assertEqual(index._size, index._bytes_read)

    def test_read_and_parse_triggers_buffer_all(self):
        index = self.make_index(
            key_elements=2,
            nodes=[
                ((b"name", b"fin1"), b"data", ()),
                ((b"name", b"fin2"), b"beta", ()),
                ((b"ref", b"erence"), b"refdata", ()),
            ],
        )
        self.assertGreater(index._size, 0)
        self.assertIs(None, index._nodes)
        index._read_and_parse([(0, index._size)])
        self.assertIsNot(None, index._nodes)

    def test_validate_bad_index_errors(self):
        trans = self.get_transport()
        trans.put_bytes("name", b"not an index\n")
        idx = _mod_index.GraphIndex(trans, "name", 13)
        self.assertRaises(_mod_index.BadIndexFormatSignature, idx.validate)

    def test_validate_bad_node_refs(self):
        idx = self.make_index(2)
        trans = self.get_transport()
        content = trans.get_bytes("index")
        # change the options line to end with a rather than a parseable number
        new_content = content[:-2] + b"a\n\n"
        trans.put_bytes("index", new_content)
        self.assertRaises(_mod_index.BadIndexOptions, idx.validate)

    def test_validate_missing_end_line_empty(self):
        index = self.make_index(2)
        trans = self.get_transport()
        content = trans.get_bytes("index")
        # truncate the last byte
        trans.put_bytes("index", content[:-1])
        self.assertRaises(_mod_index.BadIndexData, index.validate)

    def test_validate_missing_end_line_nonempty(self):
        index = self.make_index(2, nodes=[((b"key",), b"", ([], []))])
        trans = self.get_transport()
        content = trans.get_bytes("index")
        # truncate the last byte
        trans.put_bytes("index", content[:-1])
        self.assertRaises(_mod_index.BadIndexData, index.validate)

    def test_validate_empty(self):
        index = self.make_index()
        index.validate()

    def test_validate_no_refs_content(self):
        index = self.make_index(nodes=[((b"key",), b"value", ())])
        index.validate()

    # XXX: external_references tests are duplicated in test_btree_index.  We
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

    def test__find_ancestors(self):
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
        self.assertEqual({key1: (key2,)}, parent_map)
        self.assertEqual(set(), missing_keys)
        self.assertEqual({key2}, search_keys)
        search_keys = index._find_ancestors(search_keys, 0, parent_map, missing_keys)
        self.assertEqual({key1: (key2,), key2: ()}, parent_map)
        self.assertEqual(set(), missing_keys)
        self.assertEqual(set(), search_keys)

    def test__find_ancestors_w_missing(self):
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

    def test_supports_unlimited_cache(self):
        builder = _mod_index.GraphIndexBuilder(0, key_elements=1)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file("index", stream)
        # It doesn't matter what unlimited_cache does here, just that it can be
        # passed
        _mod_index.GraphIndex(trans, "index", size, unlimited_cache=True)


class TestCombinedGraphIndex(tests.TestCaseWithMemoryTransport):
    def make_index(self, name, ref_lists=0, key_elements=1, nodes=None):
        if nodes is None:
            nodes = []
        builder = _mod_index.GraphIndexBuilder(ref_lists, key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return _mod_index.GraphIndex(trans, name, size)

    def make_combined_index_with_missing(self, missing=None):
        """Create a CombinedGraphIndex which will have missing indexes.

        This creates a CGI which thinks it has 2 indexes, however they have
        been deleted. If CGI._reload_func() is called, then it will repopulate
        with a new index.

        :param missing: The underlying indexes to delete
        :return: (CombinedGraphIndex, reload_counter)
        """
        if missing is None:
            missing = ["1", "2"]
        idx1 = self.make_index("1", nodes=[((b"1",), b"", ())])
        idx2 = self.make_index("2", nodes=[((b"2",), b"", ())])
        idx3 = self.make_index("3", nodes=[((b"1",), b"", ()), ((b"2",), b"", ())])

        # total_reloads, num_changed, num_unchanged
        reload_counter = [0, 0, 0]

        def reload():
            reload_counter[0] += 1
            new_indices = [idx3]
            if idx._indices == new_indices:
                reload_counter[2] += 1
                return False
            reload_counter[1] += 1
            idx._indices[:] = new_indices
            return True

        idx = _mod_index.CombinedGraphIndex([idx1, idx2], reload_func=reload)
        trans = self.get_transport()
        for fname in missing:
            trans.delete(fname)
        return idx, reload_counter

    def test_open_missing_index_no_error(self):
        trans = self.get_transport()
        idx1 = _mod_index.GraphIndex(trans, "missing", 100)
        _mod_index.CombinedGraphIndex([idx1])

    def test_add_index(self):
        idx = _mod_index.CombinedGraphIndex([])
        idx1 = self.make_index("name", 0, nodes=[((b"key",), b"", ())])
        idx.insert_index(0, idx1)
        self.assertEqual([(idx1, (b"key",), b"")], list(idx.iter_all_entries()))

    def test_clear_cache(self):
        log = []

        class ClearCacheProxy:
            def __init__(self, index):
                self._index = index

            def __getattr__(self, name):
                return getattr(self._index)

            def clear_cache(self):
                log.append(self._index)
                return self._index.clear_cache()

        idx = _mod_index.CombinedGraphIndex([])
        idx1 = self.make_index("name", 0, nodes=[((b"key",), b"", ())])
        idx.insert_index(0, ClearCacheProxy(idx1))
        idx2 = self.make_index("name", 0, nodes=[((b"key",), b"", ())])
        idx.insert_index(1, ClearCacheProxy(idx2))
        # CombinedGraphIndex should call 'clear_cache()' on all children
        idx.clear_cache()
        self.assertEqual(sorted([idx1, idx2]), sorted(log))

    def test_iter_all_entries_empty(self):
        idx = _mod_index.CombinedGraphIndex([])
        self.assertEqual([], list(idx.iter_all_entries()))

    def test_iter_all_entries_children_empty(self):
        idx1 = self.make_index("name")
        idx = _mod_index.CombinedGraphIndex([idx1])
        self.assertEqual([], list(idx.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        idx1 = self.make_index("name", nodes=[((b"name",), b"data", ())])
        idx = _mod_index.CombinedGraphIndex([idx1])
        self.assertEqual([(idx1, (b"name",), b"data")], list(idx.iter_all_entries()))

    def test_iter_all_entries_two_indices(self):
        idx1 = self.make_index("name1", nodes=[((b"name",), b"data", ())])
        idx2 = self.make_index("name2", nodes=[((b"2",), b"", ())])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(
            [(idx1, (b"name",), b"data"), (idx2, (b"2",), b"")],
            list(idx.iter_all_entries()),
        )

    def test_iter_entries_two_indices_dup_key(self):
        idx1 = self.make_index("name1", nodes=[((b"name",), b"data", ())])
        idx2 = self.make_index("name2", nodes=[((b"name",), b"data", ())])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(
            [(idx1, (b"name",), b"data")], list(idx.iter_entries([(b"name",)]))
        )

    def test_iter_all_entries_two_indices_dup_key(self):
        idx1 = self.make_index("name1", nodes=[((b"name",), b"data", ())])
        idx2 = self.make_index("name2", nodes=[((b"name",), b"data", ())])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual([(idx1, (b"name",), b"data")], list(idx.iter_all_entries()))

    def test_iter_key_prefix_2_key_element_refs(self):
        idx1 = self.make_index(
            "1",
            1,
            key_elements=2,
            nodes=[((b"name", b"fin1"), b"data", ([(b"ref", b"erence")],))],
        )
        idx2 = self.make_index(
            "2",
            1,
            key_elements=2,
            nodes=[
                ((b"name", b"fin2"), b"beta", ([],)),
                ((b"ref", b"erence"), b"refdata", ([],)),
            ],
        )
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(
            {
                (idx1, (b"name", b"fin1"), b"data", (((b"ref", b"erence"),),)),
                (idx2, (b"ref", b"erence"), b"refdata", ((),)),
            },
            set(idx.iter_entries_prefix([(b"name", b"fin1"), (b"ref", b"erence")])),
        )
        self.assertEqual(
            {
                (idx1, (b"name", b"fin1"), b"data", (((b"ref", b"erence"),),)),
                (idx2, (b"name", b"fin2"), b"beta", ((),)),
            },
            set(idx.iter_entries_prefix([(b"name", None)])),
        )

    def test_iter_nothing_empty(self):
        idx = _mod_index.CombinedGraphIndex([])
        self.assertEqual([], list(idx.iter_entries([])))

    def test_iter_nothing_children_empty(self):
        idx1 = self.make_index("name")
        idx = _mod_index.CombinedGraphIndex([idx1])
        self.assertEqual([], list(idx.iter_entries([])))

    def test_iter_all_keys(self):
        idx1 = self.make_index("1", 1, nodes=[((b"name",), b"data", ([(b"ref",)],))])
        idx2 = self.make_index("2", 1, nodes=[((b"ref",), b"refdata", ((),))])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(
            {
                (idx1, (b"name",), b"data", (((b"ref",),),)),
                (idx2, (b"ref",), b"refdata", ((),)),
            },
            set(idx.iter_entries([(b"name",), (b"ref",)])),
        )

    def test_iter_all_keys_dup_entry(self):
        idx1 = self.make_index(
            "1",
            1,
            nodes=[
                ((b"name",), b"data", ([(b"ref",)],)),
                ((b"ref",), b"refdata", ([],)),
            ],
        )
        idx2 = self.make_index("2", 1, nodes=[((b"ref",), b"refdata", ([],))])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(
            {
                (idx1, (b"name",), b"data", (((b"ref",),),)),
                (idx1, (b"ref",), b"refdata", ((),)),
            },
            set(idx.iter_entries([(b"name",), (b"ref",)])),
        )

    def test_iter_missing_entry_empty(self):
        idx = _mod_index.CombinedGraphIndex([])
        self.assertEqual([], list(idx.iter_entries([("a",)])))

    def test_iter_missing_entry_one_index(self):
        idx1 = self.make_index("1")
        idx = _mod_index.CombinedGraphIndex([idx1])
        self.assertEqual([], list(idx.iter_entries([(b"a",)])))

    def test_iter_missing_entry_two_index(self):
        idx1 = self.make_index("1")
        idx2 = self.make_index("2")
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual([], list(idx.iter_entries([("a",)])))

    def test_iter_entry_present_one_index_only(self):
        idx1 = self.make_index("1", nodes=[((b"key",), b"", ())])
        idx2 = self.make_index("2", nodes=[])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual([(idx1, (b"key",), b"")], list(idx.iter_entries([(b"key",)])))
        # and in the other direction
        idx = _mod_index.CombinedGraphIndex([idx2, idx1])
        self.assertEqual([(idx1, (b"key",), b"")], list(idx.iter_entries([(b"key",)])))

    def test_key_count_empty(self):
        idx1 = self.make_index("1", nodes=[])
        idx2 = self.make_index("2", nodes=[])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(0, idx.key_count())

    def test_key_count_sums_index_keys(self):
        idx1 = self.make_index("1", nodes=[((b"1",), b"", ()), ((b"2",), b"", ())])
        idx2 = self.make_index("2", nodes=[((b"1",), b"", ())])
        idx = _mod_index.CombinedGraphIndex([idx1, idx2])
        self.assertEqual(3, idx.key_count())

    def test_validate_bad_child_index_errors(self):
        trans = self.get_transport()
        trans.put_bytes("name", b"not an index\n")
        idx1 = _mod_index.GraphIndex(trans, "name", 13)
        idx = _mod_index.CombinedGraphIndex([idx1])
        self.assertRaises(_mod_index.BadIndexFormatSignature, idx.validate)

    def test_validate_empty(self):
        idx = _mod_index.CombinedGraphIndex([])
        idx.validate()

    def test_key_count_reloads(self):
        idx, reload_counter = self.make_combined_index_with_missing()
        self.assertEqual(2, idx.key_count())
        self.assertEqual([1, 1, 0], reload_counter)

    def test_key_count_no_reload(self):
        idx, _reload_counter = self.make_combined_index_with_missing()
        idx._reload_func = None
        # Without a _reload_func we just raise the exception
        self.assertRaises(transport.NoSuchFile, idx.key_count)

    def test_key_count_reloads_and_fails(self):
        # We have deleted all underlying indexes, so we will try to reload, but
        # still fail. This is mostly to test we don't get stuck in an infinite
        # loop trying to reload
        idx, reload_counter = self.make_combined_index_with_missing(["1", "2", "3"])
        self.assertRaises(transport.NoSuchFile, idx.key_count)
        self.assertEqual([2, 1, 1], reload_counter)

    def test_iter_entries_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        result = list(index.iter_entries([(b"1",), (b"2",), (b"3",)]))
        index3 = index._indices[0]
        self.assertEqual({(index3, (b"1",), b""), (index3, (b"2",), b"")}, set(result))
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_reloads_midway(self):
        # The first index still looks present, so we get interrupted mid-way
        # through
        index, reload_counter = self.make_combined_index_with_missing(["2"])
        index1, _index2 = index._indices
        result = list(index.iter_entries([(b"1",), (b"2",), (b"3",)]))
        index3 = index._indices[0]
        # We had already yielded b'1', so we just go on to the next, we should
        # not yield b'1' twice.
        self.assertEqual([(index1, (b"1",), b""), (index3, (b"2",), b"")], result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_no_reload(self):
        index, _reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        # Without a _reload_func we just raise the exception
        self.assertListRaises(transport.NoSuchFile, index.iter_entries, [("3",)])

    def test_iter_entries_reloads_and_fails(self):
        index, reload_counter = self.make_combined_index_with_missing(["1", "2", "3"])
        self.assertListRaises(transport.NoSuchFile, index.iter_entries, [("3",)])
        self.assertEqual([2, 1, 1], reload_counter)

    def test_iter_all_entries_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        result = list(index.iter_all_entries())
        index3 = index._indices[0]
        self.assertEqual({(index3, (b"1",), b""), (index3, (b"2",), b"")}, set(result))
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_all_entries_reloads_midway(self):
        index, reload_counter = self.make_combined_index_with_missing(["2"])
        index1, _index2 = index._indices
        result = list(index.iter_all_entries())
        index3 = index._indices[0]
        # We had already yielded '1', so we just go on to the next, we should
        # not yield '1' twice.
        self.assertEqual([(index1, (b"1",), b""), (index3, (b"2",), b"")], result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_all_entries_no_reload(self):
        index, _reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        self.assertListRaises(transport.NoSuchFile, index.iter_all_entries)

    def test_iter_all_entries_reloads_and_fails(self):
        index, _reload_counter = self.make_combined_index_with_missing(["1", "2", "3"])
        self.assertListRaises(transport.NoSuchFile, index.iter_all_entries)

    def test_iter_entries_prefix_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        result = list(index.iter_entries_prefix([(b"1",)]))
        index3 = index._indices[0]
        self.assertEqual([(index3, (b"1",), b"")], result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_prefix_reloads_midway(self):
        index, reload_counter = self.make_combined_index_with_missing(["2"])
        index1, _index2 = index._indices
        result = list(index.iter_entries_prefix([(b"1",)]))
        index._indices[0]
        # We had already yielded b'1', so we just go on to the next, we should
        # not yield b'1' twice.
        self.assertEqual([(index1, (b"1",), b"")], result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_prefix_no_reload(self):
        index, _reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        self.assertListRaises(
            transport.NoSuchFile, index.iter_entries_prefix, [(b"1",)]
        )

    def test_iter_entries_prefix_reloads_and_fails(self):
        index, _reload_counter = self.make_combined_index_with_missing(["1", "2", "3"])
        self.assertListRaises(
            transport.NoSuchFile, index.iter_entries_prefix, [(b"1",)]
        )

    def make_index_with_simple_nodes(self, name, num_nodes=1):
        """Make an index named after 'name', with keys named after 'name' too.

        Nodes will have a value of '' and no references.
        """
        nodes = [
            ((f"index-{name}-key-{n}".encode("ascii"),), b"", ())
            for n in range(1, num_nodes + 1)
        ]
        return self.make_index(f"index-{name}", 0, nodes=nodes)

    def test_reorder_after_iter_entries(self):
        # Four indices: [key1] in idx1, [key2,key3] in idx2, [] in idx3,
        # [key4] in idx4.
        idx = _mod_index.CombinedGraphIndex([])
        idx.insert_index(0, self.make_index_with_simple_nodes("1"), b"1")
        idx.insert_index(1, self.make_index_with_simple_nodes("2"), b"2")
        idx.insert_index(2, self.make_index_with_simple_nodes("3"), b"3")
        idx.insert_index(3, self.make_index_with_simple_nodes("4"), b"4")
        idx1, idx2, idx3, idx4 = idx._indices
        # Query a key from idx4 and idx2.
        self.assertLength(
            2, list(idx.iter_entries([(b"index-4-key-1",), (b"index-2-key-1",)]))
        )
        # Now idx2 and idx4 should be moved to the front (and idx1 should
        # still be before idx3).
        self.assertEqual([idx2, idx4, idx1, idx3], idx._indices)
        self.assertEqual([b"2", b"4", b"1", b"3"], idx._index_names)

    def test_reorder_propagates_to_siblings(self):
        # Two CombinedGraphIndex objects, with the same number of indicies with
        # matching names.
        cgi1 = _mod_index.CombinedGraphIndex([])
        cgi2 = _mod_index.CombinedGraphIndex([])
        cgi1.insert_index(0, self.make_index_with_simple_nodes("1-1"), "one")
        cgi1.insert_index(1, self.make_index_with_simple_nodes("1-2"), "two")
        cgi2.insert_index(0, self.make_index_with_simple_nodes("2-1"), "one")
        cgi2.insert_index(1, self.make_index_with_simple_nodes("2-2"), "two")
        index2_1, index2_2 = cgi2._indices
        cgi1.set_sibling_indices([cgi2])
        # Trigger a reordering in cgi1.  cgi2 will be reordered as well.
        list(cgi1.iter_entries([(b"index-1-2-key-1",)]))
        self.assertEqual([index2_2, index2_1], cgi2._indices)
        self.assertEqual(["two", "one"], cgi2._index_names)

    def test_validate_reloads(self):
        idx, reload_counter = self.make_combined_index_with_missing()
        idx.validate()
        self.assertEqual([1, 1, 0], reload_counter)

    def test_validate_reloads_midway(self):
        idx, _reload_counter = self.make_combined_index_with_missing(["2"])
        idx.validate()

    def test_validate_no_reload(self):
        idx, _reload_counter = self.make_combined_index_with_missing()
        idx._reload_func = None
        self.assertRaises(transport.NoSuchFile, idx.validate)

    def test_validate_reloads_and_fails(self):
        idx, _reload_counter = self.make_combined_index_with_missing(["1", "2", "3"])
        self.assertRaises(transport.NoSuchFile, idx.validate)

    def test_find_ancestors_across_indexes(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        key3 = (b"key-3",)
        key4 = (b"key-4",)
        index1 = self.make_index(
            "12",
            ref_lists=1,
            nodes=[
                (key1, b"value", ([],)),
                (key2, b"value", ([key1],)),
            ],
        )
        index2 = self.make_index(
            "34",
            ref_lists=1,
            nodes=[
                (key3, b"value", ([key2],)),
                (key4, b"value", ([key3],)),
            ],
        )
        c_index = _mod_index.CombinedGraphIndex([index1, index2])
        parent_map, missing_keys = c_index.find_ancestry([key1], 0)
        self.assertEqual({key1: ()}, parent_map)
        self.assertEqual(set(), missing_keys)
        # Now look for a key from index2 which requires us to find the key in
        # the second index, and then continue searching for parents in the
        # first index
        parent_map, missing_keys = c_index.find_ancestry([key3], 0)
        self.assertEqual({key1: (), key2: (key1,), key3: (key2,)}, parent_map)
        self.assertEqual(set(), missing_keys)

    def test_find_ancestors_missing_keys(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        key3 = (b"key-3",)
        key4 = (b"key-4",)
        index1 = self.make_index(
            "12",
            ref_lists=1,
            nodes=[
                (key1, b"value", ([],)),
                (key2, b"value", ([key1],)),
            ],
        )
        index2 = self.make_index(
            "34",
            ref_lists=1,
            nodes=[
                (key3, b"value", ([key2],)),
            ],
        )
        c_index = _mod_index.CombinedGraphIndex([index1, index2])
        # Searching for a key which is actually not present at all should
        # eventually converge
        parent_map, missing_keys = c_index.find_ancestry([key4], 0)
        self.assertEqual({}, parent_map)
        self.assertEqual({key4}, missing_keys)

    def test_find_ancestors_no_indexes(self):
        c_index = _mod_index.CombinedGraphIndex([])
        key1 = (b"key-1",)
        parent_map, missing_keys = c_index.find_ancestry([key1], 0)
        self.assertEqual({}, parent_map)
        self.assertEqual({key1}, missing_keys)

    def test_find_ancestors_ghost_parent(self):
        key1 = (b"key-1",)
        key2 = (b"key-2",)
        key3 = (b"key-3",)
        key4 = (b"key-4",)
        index1 = self.make_index(
            "12",
            ref_lists=1,
            nodes=[
                (key1, b"value", ([],)),
                (key2, b"value", ([key1],)),
            ],
        )
        index2 = self.make_index(
            "34",
            ref_lists=1,
            nodes=[
                (key4, b"value", ([key2, key3],)),
            ],
        )
        c_index = _mod_index.CombinedGraphIndex([index1, index2])
        # Searching for a key which is actually not present at all should
        # eventually converge
        parent_map, missing_keys = c_index.find_ancestry([key4], 0)
        self.assertEqual({key4: (key2, key3), key2: (key1,), key1: ()}, parent_map)
        self.assertEqual({key3}, missing_keys)

    def test__find_ancestors_empty_index(self):
        idx = self.make_index("test", ref_lists=1, key_elements=1, nodes=[])
        parent_map = {}
        missing_keys = set()
        search_keys = idx._find_ancestors(
            [(b"one",), (b"two",)], 0, parent_map, missing_keys
        )
        self.assertEqual(set(), search_keys)
        self.assertEqual({}, parent_map)
        self.assertEqual({(b"one",), (b"two",)}, missing_keys)


class TestInMemoryGraphIndex(tests.TestCaseWithMemoryTransport):
    def make_index(self, ref_lists=0, key_elements=1, nodes=None):
        if nodes is None:
            nodes = []
        result = _mod_index.InMemoryGraphIndex(ref_lists, key_elements=key_elements)
        result.add_nodes(nodes)
        return result

    def test_add_nodes_no_refs(self):
        index = self.make_index(0)
        index.add_nodes([((b"name",), b"data")])
        index.add_nodes([((b"name2",), b""), ((b"name3",), b"")])
        self.assertEqual(
            {
                (index, (b"name",), b"data"),
                (index, (b"name2",), b""),
                (index, (b"name3",), b""),
            },
            set(index.iter_all_entries()),
        )

    def test_add_nodes(self):
        index = self.make_index(1)
        index.add_nodes([((b"name",), b"data", ([],))])
        index.add_nodes([((b"name2",), b"", ([],)), ((b"name3",), b"", ([(b"r",)],))])
        self.assertEqual(
            {
                (index, (b"name",), b"data", ((),)),
                (index, (b"name2",), b"", ((),)),
                (index, (b"name3",), b"", (((b"r",),),)),
            },
            set(index.iter_all_entries()),
        )

    def test_iter_all_entries_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index = self.make_index(nodes=[((b"name",), b"data")])
        self.assertEqual([(index, (b"name",), b"data")], list(index.iter_all_entries()))

    def test_iter_all_entries_references(self):
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
            set(index.iter_all_entries()),
        )

    def test_iteration_absent_skipped(self):
        index = self.make_index(1, nodes=[((b"name",), b"data", ([(b"ref",)],))])
        self.assertEqual(
            {(index, (b"name",), b"data", (((b"ref",),),))},
            set(index.iter_all_entries()),
        )
        self.assertEqual(
            {(index, (b"name",), b"data", (((b"ref",),),))},
            set(index.iter_entries([(b"name",)])),
        )
        self.assertEqual([], list(index.iter_entries([(b"ref",)])))

    def test_iter_all_keys(self):
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
            set(index.iter_entries([(b"name",), (b"ref",)])),
        )

    def test_iter_key_prefix_1_key_element_no_refs(self):
        index = self.make_index(nodes=[((b"name",), b"data"), ((b"ref",), b"refdata")])
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
                ((b"name", b"fin1"), b"data"),
                ((b"name", b"fin2"), b"beta"),
                ((b"ref", b"erence"), b"refdata"),
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

    def test_iter_nothing_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_missing_entry_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([b"a"])))

    def test_key_count_empty(self):
        index = self.make_index()
        self.assertEqual(0, index.key_count())

    def test_key_count_one(self):
        index = self.make_index(nodes=[((b"name",), b"")])
        self.assertEqual(1, index.key_count())

    def test_key_count_two(self):
        index = self.make_index(nodes=[((b"name",), b""), ((b"foo",), b"")])
        self.assertEqual(2, index.key_count())

    def test_validate_empty(self):
        index = self.make_index()
        index.validate()

    def test_validate_no_refs_content(self):
        index = self.make_index(nodes=[((b"key",), b"value")])
        index.validate()


class TestGraphIndexPrefixAdapter(tests.TestCaseWithMemoryTransport):
    def make_index(self, ref_lists=1, key_elements=2, nodes=None, add_callback=False):
        if nodes is None:
            nodes = []
        result = _mod_index.InMemoryGraphIndex(ref_lists, key_elements=key_elements)
        result.add_nodes(nodes)
        add_nodes_callback = result.add_nodes if add_callback else None
        adapter = _mod_index.GraphIndexPrefixAdapter(
            result,
            (b"prefix",),
            key_elements - 1,
            add_nodes_callback=add_nodes_callback,
        )
        return result, adapter

    def test_add_node(self):
        index, adapter = self.make_index(add_callback=True)
        adapter.add_node((b"key",), b"value", (((b"ref",),),))
        self.assertEqual(
            {(index, (b"prefix", b"key"), b"value", (((b"prefix", b"ref"),),))},
            set(index.iter_all_entries()),
        )

    def test_add_nodes(self):
        index, adapter = self.make_index(add_callback=True)
        adapter.add_nodes(
            (
                ((b"key",), b"value", (((b"ref",),),)),
                ((b"key2",), b"value2", ((),)),
            )
        )
        self.assertEqual(
            {
                (index, (b"prefix", b"key2"), b"value2", ((),)),
                (index, (b"prefix", b"key"), b"value", (((b"prefix", b"ref"),),)),
            },
            set(index.iter_all_entries()),
        )

    def test_construct(self):
        idx = _mod_index.InMemoryGraphIndex()
        _mod_index.GraphIndexPrefixAdapter(idx, (b"prefix",), 1)

    def test_construct_with_callback(self):
        idx = _mod_index.InMemoryGraphIndex()
        _mod_index.GraphIndexPrefixAdapter(idx, (b"prefix",), 1, idx.add_nodes)

    def test_iter_all_entries_cross_prefix_map_errors(self):
        _index, adapter = self.make_index(
            nodes=[((b"prefix", b"key1"), b"data1", (((b"prefixaltered", b"key2"),),))]
        )
        self.assertRaises(_mod_index.BadIndexData, list, adapter.iter_all_entries())

    def test_iter_all_entries(self):
        index, adapter = self.make_index(
            nodes=[
                ((b"notprefix", b"key1"), b"data", ((),)),
                ((b"prefix", b"key1"), b"data1", ((),)),
                ((b"prefix", b"key2"), b"data2", (((b"prefix", b"key1"),),)),
            ]
        )
        self.assertEqual(
            {
                (index, (b"key1",), b"data1", ((),)),
                (index, (b"key2",), b"data2", (((b"key1",),),)),
            },
            set(adapter.iter_all_entries()),
        )

    def test_iter_entries(self):
        index, adapter = self.make_index(
            nodes=[
                ((b"notprefix", b"key1"), b"data", ((),)),
                ((b"prefix", b"key1"), b"data1", ((),)),
                ((b"prefix", b"key2"), b"data2", (((b"prefix", b"key1"),),)),
            ]
        )
        # ask for many - get all
        self.assertEqual(
            {
                (index, (b"key1",), b"data1", ((),)),
                (index, (b"key2",), b"data2", (((b"key1",),),)),
            },
            set(adapter.iter_entries([(b"key1",), (b"key2",)])),
        )
        # ask for one, get one
        self.assertEqual(
            {(index, (b"key1",), b"data1", ((),))},
            set(adapter.iter_entries([(b"key1",)])),
        )
        # ask for missing, get none
        self.assertEqual(set(), set(adapter.iter_entries([(b"key3",)])))

    def test_iter_entries_prefix(self):
        index, adapter = self.make_index(
            key_elements=3,
            nodes=[
                ((b"notprefix", b"foo", b"key1"), b"data", ((),)),
                ((b"prefix", b"prefix2", b"key1"), b"data1", ((),)),
                (
                    (b"prefix", b"prefix2", b"key2"),
                    b"data2",
                    (((b"prefix", b"prefix2", b"key1"),),),
                ),
            ],
        )
        # ask for a prefix, get the results for just that prefix, adjusted.
        self.assertEqual(
            {
                (
                    index,
                    (
                        b"prefix2",
                        b"key1",
                    ),
                    b"data1",
                    ((),),
                ),
                (
                    index,
                    (
                        b"prefix2",
                        b"key2",
                    ),
                    b"data2",
                    (
                        (
                            (
                                b"prefix2",
                                b"key1",
                            ),
                        ),
                    ),
                ),
            },
            set(adapter.iter_entries_prefix([(b"prefix2", None)])),
        )

    def test_key_count_no_matching_keys(self):
        _index, adapter = self.make_index(
            nodes=[((b"notprefix", b"key1"), b"data", ((),))]
        )
        self.assertEqual(0, adapter.key_count())

    def test_key_count_some_keys(self):
        _index, adapter = self.make_index(
            nodes=[
                ((b"notprefix", b"key1"), b"data", ((),)),
                ((b"prefix", b"key1"), b"data1", ((),)),
                ((b"prefix", b"key2"), b"data2", (((b"prefix", b"key1"),),)),
            ]
        )
        self.assertEqual(2, adapter.key_count())

    def test_validate(self):
        index, adapter = self.make_index()
        calls = []

        def validate():
            calls.append("called")

        index.validate = validate
        adapter.validate()
        self.assertEqual(["called"], calls)

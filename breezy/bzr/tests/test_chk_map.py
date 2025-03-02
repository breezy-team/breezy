# Copyright (C) 2008-2011, 2016 Canonical Ltd
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

"""Tests for maps built on a CHK versionedfiles facility."""

from ... import errors, osutils, tests
from .. import chk_map, groupcompress
from ..chk_map import CHKMap, InternalNode, LeafNode, Node
from ..static_tuple import StaticTuple


class TestNode(tests.TestCase):
    def assertCommonPrefix(self, expected_common, prefix, key):
        common = Node.common_prefix(prefix, key)
        self.assertTrue(len(common) <= len(prefix))
        self.assertTrue(len(common) <= len(key))
        self.assertStartsWith(prefix, common)
        self.assertStartsWith(key, common)
        self.assertEqual(expected_common, common)

    def test_common_prefix(self):
        self.assertCommonPrefix(b"beg", b"beg", b"begin")

    def test_no_common_prefix(self):
        self.assertCommonPrefix(b"", b"begin", b"end")

    def test_equal(self):
        self.assertCommonPrefix(b"begin", b"begin", b"begin")

    def test_not_a_prefix(self):
        self.assertCommonPrefix(b"b", b"begin", b"b")

    def test_empty(self):
        self.assertCommonPrefix(b"", b"", b"end")
        self.assertCommonPrefix(b"", b"begin", b"")
        self.assertCommonPrefix(b"", b"", b"")


class TestCaseWithStore(tests.TestCaseWithMemoryTransport):
    def get_chk_bytes(self):
        # This creates a standalone CHK store.
        factory = groupcompress.make_pack_factory(False, False, 1)
        self.chk_bytes = factory(self.get_transport())
        return self.chk_bytes

    def _get_map(
        self, a_dict, maximum_size=0, chk_bytes=None, key_width=1, search_key_func=None
    ):
        if chk_bytes is None:
            chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(
            chk_bytes,
            a_dict,
            maximum_size=maximum_size,
            key_width=key_width,
            search_key_func=search_key_func,
        )
        root_key2 = CHKMap._create_via_map(
            chk_bytes,
            a_dict,
            maximum_size=maximum_size,
            key_width=key_width,
            search_key_func=search_key_func,
        )
        self.assertEqual(
            root_key,
            root_key2,
            "CHKMap.from_dict() did not match CHKMap._create_via_map",
        )
        chkmap = CHKMap(chk_bytes, root_key, search_key_func=search_key_func)
        return chkmap

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], "unordered", True)
        record = next(stream)
        if record.storage_kind == "absent":
            self.fail("Store does not contain the key {}".format(key))
        return record.get_bytes_as("fulltext")

    def to_dict(self, node, *args):
        return dict(node.iteritems(*args))


class TestCaseWithExampleMaps(TestCaseWithStore):
    def get_chk_bytes(self):
        if getattr(self, "_chk_bytes", None) is None:
            self._chk_bytes = super().get_chk_bytes()
        return self._chk_bytes

    def get_map(self, a_dict, maximum_size=100, search_key_func=None):
        c_map = self._get_map(
            a_dict,
            maximum_size=maximum_size,
            chk_bytes=self.get_chk_bytes(),
            search_key_func=search_key_func,
        )
        return c_map

    def make_root_only_map(self, search_key_func=None):
        return self.get_map(
            {
                (b"aaa",): b"initial aaa content",
                (b"abb",): b"initial abb content",
            },
            search_key_func=search_key_func,
        )

    def make_root_only_aaa_ddd_map(self, search_key_func=None):
        return self.get_map(
            {
                (b"aaa",): b"initial aaa content",
                (b"ddd",): b"initial ddd content",
            },
            search_key_func=search_key_func,
        )

    def make_one_deep_map(self, search_key_func=None):
        # Same as root_only_map, except it forces an InternalNode at the root
        return self.get_map(
            {
                (b"aaa",): b"initial aaa content",
                (b"abb",): b"initial abb content",
                (b"ccc",): b"initial ccc content",
                (b"ddd",): b"initial ddd content",
            },
            search_key_func=search_key_func,
        )

    def make_two_deep_map(self, search_key_func=None):
        # Carefully chosen so that it creates a 2-deep map for both
        # _search_key_plain and for _search_key_16
        # Also so that things line up with make_one_deep_two_prefix_map
        return self.get_map(
            {
                (b"aaa",): b"initial aaa content",
                (b"abb",): b"initial abb content",
                (b"acc",): b"initial acc content",
                (b"ace",): b"initial ace content",
                (b"add",): b"initial add content",
                (b"adh",): b"initial adh content",
                (b"adl",): b"initial adl content",
                (b"ccc",): b"initial ccc content",
                (b"ddd",): b"initial ddd content",
            },
            search_key_func=search_key_func,
        )

    def make_one_deep_two_prefix_map(self, search_key_func=None):
        """Create a map with one internal node, but references are extra long.

        Otherwise has similar content to make_two_deep_map.
        """
        return self.get_map(
            {
                (b"aaa",): b"initial aaa content",
                (b"add",): b"initial add content",
                (b"adh",): b"initial adh content",
                (b"adl",): b"initial adl content",
            },
            search_key_func=search_key_func,
        )

    def make_one_deep_one_prefix_map(self, search_key_func=None):
        """Create a map with one internal node, but references are extra long.

        Similar to make_one_deep_two_prefix_map, except the split is at the
        first char, rather than the second.
        """
        return self.get_map(
            {
                (b"add",): b"initial add content",
                (b"adh",): b"initial adh content",
                (b"adl",): b"initial adl content",
                (b"bbb",): b"initial bbb content",
            },
            search_key_func=search_key_func,
        )


class TestTestCaseWithExampleMaps(TestCaseWithExampleMaps):
    """Actual tests for the provided examples."""

    def test_root_only_map_plain(self):
        c_map = self.make_root_only_map()
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "      ('abb',) 'initial abb content'\n",
            c_map._dump_tree(),
        )

    def test_root_only_map_16(self):
        c_map = self.make_root_only_map(search_key_func=chk_map._search_key_16)
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "      ('abb',) 'initial abb content'\n",
            c_map._dump_tree(),
        )

    def test_one_deep_map_plain(self):
        c_map = self.make_one_deep_map()
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "      ('abb',) 'initial abb content'\n"
            "  'c' LeafNode\n"
            "      ('ccc',) 'initial ccc content'\n"
            "  'd' LeafNode\n"
            "      ('ddd',) 'initial ddd content'\n",
            c_map._dump_tree(),
        )

    def test_one_deep_map_16(self):
        c_map = self.make_one_deep_map(search_key_func=chk_map._search_key_16)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '2' LeafNode\n"
            "      ('ccc',) 'initial ccc content'\n"
            "  '4' LeafNode\n"
            "      ('abb',) 'initial abb content'\n"
            "  'F' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "      ('ddd',) 'initial ddd content'\n",
            c_map._dump_tree(),
        )

    def test_root_only_aaa_ddd_plain(self):
        c_map = self.make_root_only_aaa_ddd_map()
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "      ('ddd',) 'initial ddd content'\n",
            c_map._dump_tree(),
        )

    def test_root_only_aaa_ddd_16(self):
        c_map = self.make_root_only_aaa_ddd_map(search_key_func=chk_map._search_key_16)
        # We use 'aaa' and 'ddd' because they happen to map to 'F' when using
        # _search_key_16
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "      ('ddd',) 'initial ddd content'\n",
            c_map._dump_tree(),
        )

    def test_two_deep_map_plain(self):
        c_map = self.make_two_deep_map()
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aa' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "    'ab' LeafNode\n"
            "      ('abb',) 'initial abb content'\n"
            "    'ac' LeafNode\n"
            "      ('acc',) 'initial acc content'\n"
            "      ('ace',) 'initial ace content'\n"
            "    'ad' LeafNode\n"
            "      ('add',) 'initial add content'\n"
            "      ('adh',) 'initial adh content'\n"
            "      ('adl',) 'initial adl content'\n"
            "  'c' LeafNode\n"
            "      ('ccc',) 'initial ccc content'\n"
            "  'd' LeafNode\n"
            "      ('ddd',) 'initial ddd content'\n",
            c_map._dump_tree(),
        )

    def test_two_deep_map_16(self):
        c_map = self.make_two_deep_map(search_key_func=chk_map._search_key_16)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '2' LeafNode\n"
            "      ('acc',) 'initial acc content'\n"
            "      ('ccc',) 'initial ccc content'\n"
            "  '4' LeafNode\n"
            "      ('abb',) 'initial abb content'\n"
            "  'C' LeafNode\n"
            "      ('ace',) 'initial ace content'\n"
            "  'F' InternalNode\n"
            "    'F0' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "    'F3' LeafNode\n"
            "      ('adl',) 'initial adl content'\n"
            "    'F4' LeafNode\n"
            "      ('adh',) 'initial adh content'\n"
            "    'FB' LeafNode\n"
            "      ('ddd',) 'initial ddd content'\n"
            "    'FD' LeafNode\n"
            "      ('add',) 'initial add content'\n",
            c_map._dump_tree(),
        )

    def test_one_deep_two_prefix_map_plain(self):
        c_map = self.make_one_deep_two_prefix_map()
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aa' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "  'ad' LeafNode\n"
            "      ('add',) 'initial add content'\n"
            "      ('adh',) 'initial adh content'\n"
            "      ('adl',) 'initial adl content'\n",
            c_map._dump_tree(),
        )

    def test_one_deep_two_prefix_map_16(self):
        c_map = self.make_one_deep_two_prefix_map(
            search_key_func=chk_map._search_key_16
        )
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'F0' LeafNode\n"
            "      ('aaa',) 'initial aaa content'\n"
            "  'F3' LeafNode\n"
            "      ('adl',) 'initial adl content'\n"
            "  'F4' LeafNode\n"
            "      ('adh',) 'initial adh content'\n"
            "  'FD' LeafNode\n"
            "      ('add',) 'initial add content'\n",
            c_map._dump_tree(),
        )

    def test_one_deep_one_prefix_map_plain(self):
        c_map = self.make_one_deep_one_prefix_map()
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('add',) 'initial add content'\n"
            "      ('adh',) 'initial adh content'\n"
            "      ('adl',) 'initial adl content'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'initial bbb content'\n",
            c_map._dump_tree(),
        )

    def test_one_deep_one_prefix_map_16(self):
        c_map = self.make_one_deep_one_prefix_map(
            search_key_func=chk_map._search_key_16
        )
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '4' LeafNode\n"
            "      ('bbb',) 'initial bbb content'\n"
            "  'F' LeafNode\n"
            "      ('add',) 'initial add content'\n"
            "      ('adh',) 'initial adh content'\n"
            "      ('adl',) 'initial adl content'\n",
            c_map._dump_tree(),
        )


class TestMap(TestCaseWithStore):
    def assertHasABMap(self, chk_bytes):
        ab_leaf_bytes = b"chkleaf:\n0\n1\n1\na\n\x001\nb\n"
        ab_sha1 = osutils.sha_string(ab_leaf_bytes)
        self.assertEqual(b"90986195696b177c8895d48fdb4b7f2366f798a0", ab_sha1)
        root_key = (b"sha1:" + ab_sha1,)
        self.assertEqual(ab_leaf_bytes, self.read_bytes(chk_bytes, root_key))
        return root_key

    def assertHasEmptyMap(self, chk_bytes):
        empty_leaf_bytes = b"chkleaf:\n0\n1\n0\n\n"
        empty_sha1 = osutils.sha_string(empty_leaf_bytes)
        self.assertEqual(b"8571e09bf1bcc5b9621ce31b3d4c93d6e9a1ed26", empty_sha1)
        root_key = (b"sha1:" + empty_sha1,)
        self.assertEqual(empty_leaf_bytes, self.read_bytes(chk_bytes, root_key))
        return root_key

    def assertMapLayoutEqual(self, map_one, map_two):
        """Assert that the internal structure is identical between the maps."""
        map_one._ensure_root()
        node_one_stack = [map_one._root_node]
        map_two._ensure_root()
        node_two_stack = [map_two._root_node]
        while node_one_stack:
            node_one = node_one_stack.pop()
            node_two = node_two_stack.pop()
            if node_one.__class__ != node_two.__class__:
                self.assertEqualDiff(
                    map_one._dump_tree(include_keys=True),
                    map_two._dump_tree(include_keys=True),
                )
            self.assertEqual(node_one._search_prefix, node_two._search_prefix)
            if isinstance(node_one, InternalNode):
                # Internal nodes must have identical references
                self.assertEqual(
                    sorted(node_one._items.keys()), sorted(node_two._items.keys())
                )
                node_one_stack.extend(
                    sorted(
                        [n for n, _ in node_one._iter_nodes(map_one._store)],
                        key=lambda a: a._search_prefix,
                    )
                )
                node_two_stack.extend(
                    sorted(
                        [n for n, _ in node_two._iter_nodes(map_two._store)],
                        key=lambda a: a._search_prefix,
                    )
                )
            else:
                # Leaf nodes must have identical contents
                self.assertEqual(node_one._items, node_two._items)
        self.assertEqual([], node_two_stack)

    def assertCanonicalForm(self, chkmap):
        """Assert that the chkmap is in 'canonical' form.

        We do this by adding all of the key value pairs from scratch, both in
        forward order and reverse order, and assert that the final tree layout
        is identical.
        """
        items = list(chkmap.iteritems())
        map_forward = chk_map.CHKMap(None, None)
        map_forward._root_node.set_maximum_size(chkmap._root_node.maximum_size)
        for key, value in items:
            map_forward.map(key, value)
        self.assertMapLayoutEqual(map_forward, chkmap)
        map_reverse = chk_map.CHKMap(None, None)
        map_reverse._root_node.set_maximum_size(chkmap._root_node.maximum_size)
        for key, value in reversed(items):
            map_reverse.map(key, value)
        self.assertMapLayoutEqual(map_reverse, chkmap)

    def test_assert_map_layout_equal(self):
        store = self.get_chk_bytes()
        map_one = CHKMap(store, None)
        map_one._root_node.set_maximum_size(20)
        map_two = CHKMap(store, None)
        map_two._root_node.set_maximum_size(20)
        self.assertMapLayoutEqual(map_one, map_two)
        map_one.map((b"aaa",), b"value")
        self.assertRaises(AssertionError, self.assertMapLayoutEqual, map_one, map_two)
        map_two.map((b"aaa",), b"value")
        self.assertMapLayoutEqual(map_one, map_two)
        # Split the tree, so we ensure that internal nodes and leaf nodes are
        # properly checked
        map_one.map((b"aab",), b"value")
        self.assertIsInstance(map_one._root_node, InternalNode)
        self.assertRaises(AssertionError, self.assertMapLayoutEqual, map_one, map_two)
        map_two.map((b"aab",), b"value")
        self.assertMapLayoutEqual(map_one, map_two)
        map_one.map((b"aac",), b"value")
        self.assertRaises(AssertionError, self.assertMapLayoutEqual, map_one, map_two)
        self.assertCanonicalForm(map_one)

    def test_from_dict_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasEmptyMap(chk_bytes)
        self.assertEqual(expected_root_key, root_key)

    def test_from_dict_ab(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {(b"a",): b"b"})
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasABMap(chk_bytes)
        self.assertEqual(expected_root_key, root_key)

    def test_apply_empty_ab(self):
        # applying a delta (None, "a", "b") to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([(None, (b"a",), b"b")])
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasABMap(chk_bytes)
        self.assertEqual(expected_root_key, new_root)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_apply_ab_empty(self):
        # applying a delta ("a", None, None) to a map with 'a' in it generates
        # an empty map.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {(b"a",): b"b"})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([((b"a",), None, None)])
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasEmptyMap(chk_bytes)
        self.assertEqual(expected_root_key, new_root)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_apply_delete_to_internal_node(self):
        # applying a delta should be convert an internal root node to a leaf
        # node if the delta shrinks the map enough.
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Add three items: 2 small enough to fit in one node, and one huge to
        # force multiple nodes.
        chkmap._root_node.set_maximum_size(100)
        chkmap.map((b"small",), b"value")
        chkmap.map((b"little",), b"value")
        chkmap.map((b"very-big",), b"x" * 100)
        # (Check that we have constructed the scenario we want to test)
        self.assertIsInstance(chkmap._root_node, InternalNode)
        # Delete the huge item so that the map fits in one node again.
        delta = [((b"very-big",), None, None)]
        chkmap.apply_delta(delta)
        self.assertCanonicalForm(chkmap)
        self.assertIsInstance(chkmap._root_node, LeafNode)

    def test_apply_new_keys_must_be_new(self):
        # applying a delta (None, "a", "b") to a map with 'a' in it generates
        # an error.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {(b"a",): b"b"})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertRaises(
            errors.InconsistentDelta, chkmap.apply_delta, [(None, (b"a",), b"b")]
        )
        # As an error occured, the update should have left us without changing
        # anything (the root should be unchanged).
        self.assertEqual(root_key, chkmap._root_node._key)

    def test_apply_delta_is_deterministic(self):
        chk_bytes = self.get_chk_bytes()
        chkmap1 = CHKMap(chk_bytes, None)
        chkmap1._root_node.set_maximum_size(10)
        chkmap1.apply_delta(
            [
                (None, (b"aaa",), b"common"),
                (None, (b"bba",), b"target2"),
                (None, (b"bbb",), b"common"),
            ]
        )
        root_key1 = chkmap1._save()
        self.assertCanonicalForm(chkmap1)

        chkmap2 = CHKMap(chk_bytes, None)
        chkmap2._root_node.set_maximum_size(10)
        chkmap2.apply_delta(
            [
                (None, (b"bbb",), b"common"),
                (None, (b"bba",), b"target2"),
                (None, (b"aaa",), b"common"),
            ]
        )
        root_key2 = chkmap2._save()
        self.assertEqualDiff(
            chkmap1._dump_tree(include_keys=True), chkmap2._dump_tree(include_keys=True)
        )
        self.assertEqual(root_key1, root_key2)
        self.assertCanonicalForm(chkmap2)

    def test_stable_splitting(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(35)
        chkmap.map((b"aaa",), b"v")
        self.assertEqualDiff("'' LeafNode\n      ('aaa',) 'v'\n", chkmap._dump_tree())
        chkmap.map((b"aab",), b"v")
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaa',) 'v'\n      ('aab',) 'v'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)

        # Creates a new internal node, and splits the others into leaves
        chkmap.map((b"aac",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "  'aab' LeafNode\n"
            "      ('aab',) 'v'\n"
            "  'aac' LeafNode\n"
            "      ('aac',) 'v'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)

        # Splits again, because it can't fit in the current structure
        chkmap.map((b"bbb",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'v'\n"
            "    'aac' LeafNode\n"
            "      ('aac',) 'v'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'v'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)

    def test_map_splits_with_longer_key(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 1 key per LeafNode
        chkmap._root_node.set_maximum_size(10)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aaaa",), b"v")
        self.assertCanonicalForm(chkmap)
        self.assertIsInstance(chkmap._root_node, InternalNode)

    def test_with_linefeed_in_key(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 1 key per LeafNode
        chkmap._root_node.set_maximum_size(10)
        chkmap.map((b"a\ra",), b"val1")
        chkmap.map((b"a\rb",), b"val2")
        chkmap.map((b"ac",), b"val3")
        self.assertCanonicalForm(chkmap)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a\\r' InternalNode\n"
            "    'a\\ra' LeafNode\n"
            "      ('a\\ra',) 'val1'\n"
            "    'a\\rb' LeafNode\n"
            "      ('a\\rb',) 'val2'\n"
            "  'ac' LeafNode\n"
            "      ('ac',) 'val3'\n",
            chkmap._dump_tree(),
        )
        # We should also successfully serialise and deserialise these items
        root_key = chkmap._save()
        chkmap = CHKMap(store, root_key)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a\\r' InternalNode\n"
            "    'a\\ra' LeafNode\n"
            "      ('a\\ra',) 'val1'\n"
            "    'a\\rb' LeafNode\n"
            "      ('a\\rb',) 'val2'\n"
            "  'ac' LeafNode\n"
            "      ('ac',) 'val3'\n",
            chkmap._dump_tree(),
        )

    def test_deep_splitting(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map((b"aaaaaaaa",), b"v")
        chkmap.map((b"aaaaabaa",), b"v")
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaaaaaaa',) 'v'\n      ('aaaaabaa',) 'v'\n",
            chkmap._dump_tree(),
        )
        chkmap.map((b"aaabaaaa",), b"v")
        chkmap.map((b"aaababaa",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaaa' LeafNode\n"
            "      ('aaaaaaaa',) 'v'\n"
            "      ('aaaaabaa',) 'v'\n"
            "  'aaab' LeafNode\n"
            "      ('aaabaaaa',) 'v'\n"
            "      ('aaababaa',) 'v'\n",
            chkmap._dump_tree(),
        )
        chkmap.map((b"aaabacaa",), b"v")
        chkmap.map((b"aaabadaa",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaaa' LeafNode\n"
            "      ('aaaaaaaa',) 'v'\n"
            "      ('aaaaabaa',) 'v'\n"
            "  'aaab' InternalNode\n"
            "    'aaabaa' LeafNode\n"
            "      ('aaabaaaa',) 'v'\n"
            "    'aaabab' LeafNode\n"
            "      ('aaababaa',) 'v'\n"
            "    'aaabac' LeafNode\n"
            "      ('aaabacaa',) 'v'\n"
            "    'aaabad' LeafNode\n"
            "      ('aaabadaa',) 'v'\n",
            chkmap._dump_tree(),
        )
        chkmap.map((b"aaababba",), b"val")
        chkmap.map((b"aaababca",), b"val")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaaa' LeafNode\n"
            "      ('aaaaaaaa',) 'v'\n"
            "      ('aaaaabaa',) 'v'\n"
            "  'aaab' InternalNode\n"
            "    'aaabaa' LeafNode\n"
            "      ('aaabaaaa',) 'v'\n"
            "    'aaabab' InternalNode\n"
            "      'aaababa' LeafNode\n"
            "      ('aaababaa',) 'v'\n"
            "      'aaababb' LeafNode\n"
            "      ('aaababba',) 'val'\n"
            "      'aaababc' LeafNode\n"
            "      ('aaababca',) 'val'\n"
            "    'aaabac' LeafNode\n"
            "      ('aaabacaa',) 'v'\n"
            "    'aaabad' LeafNode\n"
            "      ('aaabadaa',) 'v'\n",
            chkmap._dump_tree(),
        )
        # Now we add a node that should fit around an existing InternalNode,
        # but has a slightly different key prefix, which causes a new
        # InternalNode split
        chkmap.map((b"aaabDaaa",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaaa' LeafNode\n"
            "      ('aaaaaaaa',) 'v'\n"
            "      ('aaaaabaa',) 'v'\n"
            "  'aaab' InternalNode\n"
            "    'aaabD' LeafNode\n"
            "      ('aaabDaaa',) 'v'\n"
            "    'aaaba' InternalNode\n"
            "      'aaabaa' LeafNode\n"
            "      ('aaabaaaa',) 'v'\n"
            "      'aaabab' InternalNode\n"
            "        'aaababa' LeafNode\n"
            "      ('aaababaa',) 'v'\n"
            "        'aaababb' LeafNode\n"
            "      ('aaababba',) 'val'\n"
            "        'aaababc' LeafNode\n"
            "      ('aaababca',) 'val'\n"
            "      'aaabac' LeafNode\n"
            "      ('aaabacaa',) 'v'\n"
            "      'aaabad' LeafNode\n"
            "      ('aaabadaa',) 'v'\n",
            chkmap._dump_tree(),
        )

    def test_map_collapses_if_size_changes(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(35)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aab",), b"very long value that splits")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "  'aab' LeafNode\n"
            "      ('aab',) 'very long value that splits'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)
        # Now changing the value to something small should cause a rebuild
        chkmap.map((b"aab",), b"v")
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaa',) 'v'\n      ('aab',) 'v'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)

    def test_map_double_deep_collapses(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 small keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aab",), b"very long value that splits")
        chkmap.map((b"abc",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aa' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'very long value that splits'\n"
            "  'ab' LeafNode\n"
            "      ('abc',) 'v'\n",
            chkmap._dump_tree(),
        )
        chkmap.map((b"aab",), b"v")
        self.assertCanonicalForm(chkmap)
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaa',) 'v'\n      ('aab',) 'v'\n      ('abc',) 'v'\n",
            chkmap._dump_tree(),
        )

    def test_stable_unmap(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(35)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aab",), b"v")
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaa',) 'v'\n      ('aab',) 'v'\n",
            chkmap._dump_tree(),
        )
        # Creates a new internal node, and splits the others into leaves
        chkmap.map((b"aac",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "  'aab' LeafNode\n"
            "      ('aab',) 'v'\n"
            "  'aac' LeafNode\n"
            "      ('aac',) 'v'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)
        # Now lets unmap one of the keys, and assert that we collapse the
        # structures.
        chkmap.unmap((b"aac",))
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaa',) 'v'\n      ('aab',) 'v'\n",
            chkmap._dump_tree(),
        )
        self.assertCanonicalForm(chkmap)

    def test_unmap_double_deep(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aaab",), b"v")
        chkmap.map((b"aab",), b"very long value")
        chkmap.map((b"abc",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aa' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "      ('aaab',) 'v'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'very long value'\n"
            "  'ab' LeafNode\n"
            "      ('abc',) 'v'\n",
            chkmap._dump_tree(),
        )
        # Removing the 'aab' key should cause everything to collapse back to a
        # single node
        chkmap.unmap((b"aab",))
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "      ('aaab',) 'v'\n"
            "      ('abc',) 'v'\n",
            chkmap._dump_tree(),
        )

    def test_unmap_double_deep_non_empty_leaf(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aab",), b"long value")
        chkmap.map((b"aabb",), b"v")
        chkmap.map((b"abc",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aa' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'long value'\n"
            "      ('aabb',) 'v'\n"
            "  'ab' LeafNode\n"
            "      ('abc',) 'v'\n",
            chkmap._dump_tree(),
        )
        # Removing the 'aab' key should cause everything to collapse back to a
        # single node
        chkmap.unmap((b"aab",))
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "      ('aabb',) 'v'\n"
            "      ('abc',) 'v'\n",
            chkmap._dump_tree(),
        )

    def test_unmap_with_known_internal_node_doesnt_page(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aab",), b"v")
        chkmap.map((b"aac",), b"v")
        chkmap.map((b"abc",), b"v")
        chkmap.map((b"acd",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aa' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'v'\n"
            "    'aac' LeafNode\n"
            "      ('aac',) 'v'\n"
            "  'ab' LeafNode\n"
            "      ('abc',) 'v'\n"
            "  'ac' LeafNode\n"
            "      ('acd',) 'v'\n",
            chkmap._dump_tree(),
        )
        # Save everything to the map, and start over
        chkmap = CHKMap(store, chkmap._save())
        # Mapping an 'aa' key loads the internal node, but should not map the
        # 'ab' and 'ac' nodes
        chkmap.map((b"aad",), b"v")
        self.assertIsInstance(chkmap._root_node._items[b"aa"], InternalNode)
        self.assertIsInstance(chkmap._root_node._items[b"ab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"ac"], StaticTuple)
        # Unmapping 'acd' can notice that 'aa' is an InternalNode and not have
        # to map in 'ab'
        chkmap.unmap((b"acd",))
        self.assertIsInstance(chkmap._root_node._items[b"aa"], InternalNode)
        self.assertIsInstance(chkmap._root_node._items[b"ab"], StaticTuple)

    def test_unmap_without_fitting_doesnt_page_in(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(20)
        chkmap.map((b"aaa",), b"v")
        chkmap.map((b"aab",), b"v")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaa' LeafNode\n"
            "      ('aaa',) 'v'\n"
            "  'aab' LeafNode\n"
            "      ('aab',) 'v'\n",
            chkmap._dump_tree(),
        )
        # Save everything to the map, and start over
        chkmap = CHKMap(store, chkmap._save())
        chkmap.map((b"aac",), b"v")
        chkmap.map((b"aad",), b"v")
        chkmap.map((b"aae",), b"v")
        chkmap.map((b"aaf",), b"v")
        # At this point, the previous nodes should not be paged in, but the
        # newly added nodes would be
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aad"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aae"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aaf"], LeafNode)
        # Now unmapping one of the new nodes will use only the already-paged-in
        # nodes to determine that we don't need to do more.
        chkmap.unmap((b"aaf",))
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aad"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aae"], LeafNode)

    def test_unmap_pages_in_if_necessary(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map((b"aaa",), b"val")
        chkmap.map((b"aab",), b"val")
        chkmap.map((b"aac",), b"val")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaa' LeafNode\n"
            "      ('aaa',) 'val'\n"
            "  'aab' LeafNode\n"
            "      ('aab',) 'val'\n"
            "  'aac' LeafNode\n"
            "      ('aac',) 'val'\n",
            chkmap._dump_tree(),
        )
        root_key = chkmap._save()
        # Save everything to the map, and start over
        chkmap = CHKMap(store, root_key)
        chkmap.map((b"aad",), b"v")
        # At this point, the previous nodes should not be paged in, but the
        # newly added node would be
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aad"], LeafNode)
        # Unmapping the new node will check the existing nodes to see if they
        # would fit.
        # Clear the page cache so we ensure we have to read all the children
        chk_map.clear_cache()
        chkmap.unmap((b"aad",))
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], LeafNode)

    def test_unmap_pages_in_from_page_cache(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map((b"aaa",), b"val")
        chkmap.map((b"aab",), b"val")
        chkmap.map((b"aac",), b"val")
        root_key = chkmap._save()
        # Save everything to the map, and start over
        chkmap = CHKMap(store, root_key)
        chkmap.map((b"aad",), b"val")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'aaa' LeafNode\n"
            "      ('aaa',) 'val'\n"
            "  'aab' LeafNode\n"
            "      ('aab',) 'val'\n"
            "  'aac' LeafNode\n"
            "      ('aac',) 'val'\n"
            "  'aad' LeafNode\n"
            "      ('aad',) 'val'\n",
            chkmap._dump_tree(),
        )
        # Save everything to the map, start over after _dump_tree
        chkmap = CHKMap(store, root_key)
        chkmap.map((b"aad",), b"v")
        # At this point, the previous nodes should not be paged in, but the
        # newly added node would be
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aad"], LeafNode)
        # Now clear the page cache, and only include 2 of the children in the
        # cache
        aab_key = chkmap._root_node._items[b"aab"]
        aab_bytes = chk_map._get_cache()[aab_key]
        aac_key = chkmap._root_node._items[b"aac"]
        aac_bytes = chk_map._get_cache()[aac_key]
        chk_map.clear_cache()
        chk_map._get_cache()[aab_key] = aab_bytes
        chk_map._get_cache()[aac_key] = aac_bytes

        # Unmapping the new node will check the nodes from the page cache
        # first, and not have to read in 'aaa'
        chkmap.unmap((b"aad",))
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], LeafNode)

    def test_unmap_uses_existing_items(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map((b"aaa",), b"val")
        chkmap.map((b"aab",), b"val")
        chkmap.map((b"aac",), b"val")
        root_key = chkmap._save()
        # Save everything to the map, and start over
        chkmap = CHKMap(store, root_key)
        chkmap.map((b"aad",), b"val")
        chkmap.map((b"aae",), b"val")
        chkmap.map((b"aaf",), b"val")
        # At this point, the previous nodes should not be paged in, but the
        # newly added node would be
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aad"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aae"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aaf"], LeafNode)

        # Unmapping a new node will see the other nodes that are already in
        # memory, and not need to page in anything else
        chkmap.unmap((b"aad",))
        self.assertIsInstance(chkmap._root_node._items[b"aaa"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aab"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aac"], StaticTuple)
        self.assertIsInstance(chkmap._root_node._items[b"aae"], LeafNode)
        self.assertIsInstance(chkmap._root_node._items[b"aaf"], LeafNode)

    def test_iter_changes_empty_ab(self):
        # Asking for changes between an empty dict to a dict with keys returns
        # all the keys.
        basis = self._get_map({}, maximum_size=10)
        target = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"},
            chk_bytes=basis._store,
            maximum_size=10,
        )
        self.assertEqual(
            [((b"a",), None, b"content here"), ((b"b",), None, b"more content")],
            sorted(target.iter_changes(basis)),
        )

    def test_iter_changes_ab_empty(self):
        # Asking for changes between a dict with keys to an empty dict returns
        # all the keys.
        basis = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"}, maximum_size=10
        )
        target = self._get_map({}, chk_bytes=basis._store, maximum_size=10)
        self.assertEqual(
            [((b"a",), b"content here", None), ((b"b",), b"more content", None)],
            sorted(target.iter_changes(basis)),
        )

    def test_iter_changes_empty_empty_is_empty(self):
        basis = self._get_map({}, maximum_size=10)
        target = self._get_map({}, chk_bytes=basis._store, maximum_size=10)
        self.assertEqual([], sorted(target.iter_changes(basis)))

    def test_iter_changes_ab_ab_is_empty(self):
        basis = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"}, maximum_size=10
        )
        target = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"},
            chk_bytes=basis._store,
            maximum_size=10,
        )
        self.assertEqual([], sorted(target.iter_changes(basis)))

    def test_iter_changes_ab_ab_nodes_not_loaded(self):
        basis = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"}, maximum_size=10
        )
        target = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"},
            chk_bytes=basis._store,
            maximum_size=10,
        )
        list(target.iter_changes(basis))
        self.assertIsInstance(target._root_node, StaticTuple)
        self.assertIsInstance(basis._root_node, StaticTuple)

    def test_iter_changes_ab_ab_changed_values_shown(self):
        basis = self._get_map(
            {(b"a",): b"content here", (b"b",): b"more content"}, maximum_size=10
        )
        target = self._get_map(
            {(b"a",): b"content here", (b"b",): b"different content"},
            chk_bytes=basis._store,
            maximum_size=10,
        )
        result = sorted(target.iter_changes(basis))
        self.assertEqual([((b"b",), b"more content", b"different content")], result)

    def test_iter_changes_mixed_node_length(self):
        # When one side has different node lengths than the other, common
        # but different keys still need to be show, and new-and-old included
        # appropriately.
        # aaa - common unaltered
        # aab - common altered
        # b - basis only
        # at - target only
        # we expect:
        # aaa to be not loaded (later test)
        # aab, b, at to be returned.
        # basis splits at byte 0,1,2, aaa is commonb is basis only
        basis_dict = {
            (b"aaa",): b"foo bar",
            (b"aab",): b"common altered a",
            (b"b",): b"foo bar b",
        }
        # target splits at byte 1,2, at is target only
        target_dict = {
            (b"aaa",): b"foo bar",
            (b"aab",): b"common altered b",
            (b"at",): b"foo bar t",
        }
        changes = [
            ((b"aab",), b"common altered a", b"common altered b"),
            ((b"at",), None, b"foo bar t"),
            ((b"b",), b"foo bar b", None),
        ]
        basis = self._get_map(basis_dict, maximum_size=10)
        target = self._get_map(target_dict, maximum_size=10, chk_bytes=basis._store)
        self.assertEqual(changes, sorted(target.iter_changes(basis)))

    def test_iter_changes_common_pages_not_loaded(self):
        # aaa - common unaltered
        # aab - common altered
        # b - basis only
        # at - target only
        # we expect:
        # aaa to be not loaded
        # aaa not to be in result.
        basis_dict = {
            (b"aaa",): b"foo bar",
            (b"aab",): b"common altered a",
            (b"b",): b"foo bar b",
        }
        # target splits at byte 1, at is target only
        target_dict = {
            (b"aaa",): b"foo bar",
            (b"aab",): b"common altered b",
            (b"at",): b"foo bar t",
        }
        basis = self._get_map(basis_dict, maximum_size=10)
        target = self._get_map(target_dict, maximum_size=10, chk_bytes=basis._store)
        basis_get = basis._store.get_record_stream

        def get_record_stream(keys, order, fulltext):
            if (b"sha1:1adf7c0d1b9140ab5f33bb64c6275fa78b1580b7",) in keys:
                raise AssertionError("'aaa' pointer was followed {!r}".format(keys))
            return basis_get(keys, order, fulltext)

        basis._store.get_record_stream = get_record_stream
        result = sorted(target.iter_changes(basis))
        for change in result:
            if change[0] == (b"aaa",):
                self.fail("Found unexpected change: {}".format(change))

    def test_iter_changes_unchanged_keys_in_multi_key_leafs_ignored(self):
        # Within a leaf there are no hash's to exclude keys, make sure multi
        # value leaf nodes are handled well.
        basis_dict = {
            (b"aaa",): b"foo bar",
            (b"aab",): b"common altered a",
            (b"b",): b"foo bar b",
        }
        target_dict = {
            (b"aaa",): b"foo bar",
            (b"aab",): b"common altered b",
            (b"at",): b"foo bar t",
        }
        changes = [
            ((b"aab",), b"common altered a", b"common altered b"),
            ((b"at",), None, b"foo bar t"),
            ((b"b",), b"foo bar b", None),
        ]
        basis = self._get_map(basis_dict)
        target = self._get_map(target_dict, chk_bytes=basis._store)
        self.assertEqual(changes, sorted(target.iter_changes(basis)))

    def test_iteritems_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual([], list(chkmap.iteritems()))

    def test_iteritems_two_items(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(
            chk_bytes, {(b"a",): b"content here", (b"b",): b"more content"}
        )
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual(
            [((b"a",), b"content here"), ((b"b",), b"more content")],
            sorted(chkmap.iteritems()),
        )

    def test_iteritems_selected_one_of_two_items(self):
        chkmap = self._get_map({(b"a",): b"content here", (b"b",): b"more content"})
        self.assertEqual({(b"a",): b"content here"}, self.to_dict(chkmap, [(b"a",)]))

    def test_iteritems_keys_prefixed_by_2_width_nodes(self):
        chkmap = self._get_map(
            {
                (b"a", b"a"): b"content here",
                (
                    b"a",
                    b"b",
                ): b"more content",
                (b"b", b""): b"boring content",
            },
            maximum_size=10,
            key_width=2,
        )
        self.assertEqual(
            {(b"a", b"a"): b"content here", (b"a", b"b"): b"more content"},
            self.to_dict(chkmap, [(b"a",)]),
        )

    def test_iteritems_keys_prefixed_by_2_width_nodes_hashed(self):
        search_key_func = chk_map.search_key_registry.get(b"hash-16-way")
        self.assertEqual(
            b"E8B7BE43\x00E8B7BE43", search_key_func(StaticTuple(b"a", b"a"))
        )
        self.assertEqual(
            b"E8B7BE43\x0071BEEFF9", search_key_func(StaticTuple(b"a", b"b"))
        )
        self.assertEqual(
            b"71BEEFF9\x0000000000", search_key_func(StaticTuple(b"b", b""))
        )
        chkmap = self._get_map(
            {
                (b"a", b"a"): b"content here",
                (
                    b"a",
                    b"b",
                ): b"more content",
                (b"b", b""): b"boring content",
            },
            maximum_size=10,
            key_width=2,
            search_key_func=search_key_func,
        )
        self.assertEqual(
            {(b"a", b"a"): b"content here", (b"a", b"b"): b"more content"},
            self.to_dict(chkmap, [(b"a",)]),
        )

    def test_iteritems_keys_prefixed_by_2_width_one_leaf(self):
        chkmap = self._get_map(
            {
                (b"a", b"a"): b"content here",
                (
                    b"a",
                    b"b",
                ): b"more content",
                (b"b", b""): b"boring content",
            },
            key_width=2,
        )
        self.assertEqual(
            {(b"a", b"a"): b"content here", (b"a", b"b"): b"more content"},
            self.to_dict(chkmap, [(b"a",)]),
        )

    def test___len__empty(self):
        chkmap = self._get_map({})
        self.assertEqual(0, len(chkmap))

    def test___len__2(self):
        chkmap = self._get_map({(b"foo",): b"bar", (b"gam",): b"quux"})
        self.assertEqual(2, len(chkmap))

    def test_max_size_100_bytes_new(self):
        # When there is a 100 byte upper node limit, a tree is formed.
        chkmap = self._get_map(
            {(b"k1" * 50,): b"v1", (b"k2" * 50,): b"v2"}, maximum_size=100
        )
        # We expect three nodes:
        # A root, with two children, and with two key prefixes - k1 to one, and
        # k2 to the other as our node splitting is only just being developed.
        # The maximum size should be embedded
        chkmap._ensure_root()
        self.assertEqual(100, chkmap._root_node.maximum_size)
        self.assertEqual(1, chkmap._root_node._key_width)
        # There should be two child nodes, and prefix of 2(bytes):
        self.assertEqual(2, len(chkmap._root_node._items))
        self.assertEqual(b"k", chkmap._root_node._compute_search_prefix())
        # The actual nodes pointed at will change as serialisers change; so
        # here we test that the key prefix is correct; then load the nodes and
        # check they have the right pointed at key; whether they have the
        # pointed at value inline or not is also unrelated to this test so we
        # don't check that in detail - rather we just check the aggregate
        # value.
        nodes = sorted(chkmap._root_node._items.items())
        ptr1 = nodes[0]
        ptr2 = nodes[1]
        self.assertEqual(b"k1", ptr1[0])
        self.assertEqual(b"k2", ptr2[0])
        node1 = chk_map._deserialise(chkmap._read_bytes(ptr1[1]), ptr1[1], None)
        self.assertIsInstance(node1, LeafNode)
        self.assertEqual(1, len(node1))
        self.assertEqual({(b"k1" * 50,): b"v1"}, self.to_dict(node1, chkmap._store))
        node2 = chk_map._deserialise(chkmap._read_bytes(ptr2[1]), ptr2[1], None)
        self.assertIsInstance(node2, LeafNode)
        self.assertEqual(1, len(node2))
        self.assertEqual({(b"k2" * 50,): b"v2"}, self.to_dict(node2, chkmap._store))
        # Having checked we have a good structure, check that the content is
        # still accessible.
        self.assertEqual(2, len(chkmap))
        self.assertEqual(
            {(b"k1" * 50,): b"v1", (b"k2" * 50,): b"v2"}, self.to_dict(chkmap)
        )

    def test_init_root_is_LeafNode_new(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = CHKMap(chk_bytes, None)
        self.assertIsInstance(chkmap._root_node, LeafNode)
        self.assertEqual({}, self.to_dict(chkmap))
        self.assertEqual(0, len(chkmap))

    def test_init_and_save_new(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = CHKMap(chk_bytes, None)
        key = chkmap._save()
        leaf_node = LeafNode()
        self.assertEqual([key], leaf_node.serialise(chk_bytes))

    def test_map_first_item_new(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = CHKMap(chk_bytes, None)
        chkmap.map((b"foo,",), b"bar")
        self.assertEqual({(b"foo,",): b"bar"}, self.to_dict(chkmap))
        self.assertEqual(1, len(chkmap))
        key = chkmap._save()
        leaf_node = LeafNode()
        leaf_node.map(chk_bytes, (b"foo,",), b"bar")
        self.assertEqual([key], leaf_node.serialise(chk_bytes))

    def test_unmap_last_item_root_is_leaf_new(self):
        chkmap = self._get_map({(b"k1" * 50,): b"v1", (b"k2" * 50,): b"v2"})
        chkmap.unmap((b"k1" * 50,))
        chkmap.unmap((b"k2" * 50,))
        self.assertEqual(0, len(chkmap))
        self.assertEqual({}, self.to_dict(chkmap))
        key = chkmap._save()
        leaf_node = LeafNode()
        self.assertEqual([key], leaf_node.serialise(chkmap._store))

    def test__dump_tree(self):
        chkmap = self._get_map(
            {
                (b"aaa",): b"value1",
                (b"aab",): b"value2",
                (b"bbb",): b"value3",
            },
            maximum_size=15,
        )
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(),
        )
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(),
        )
        self.assertEqualDiff(
            "'' InternalNode sha1:0690d471eb0a624f359797d0ee4672bd68f4e236\n"
            "  'a' InternalNode sha1:1514c35503da9418d8fd90c1bed553077cb53673\n"
            "    'aaa' LeafNode sha1:4cc5970454d40b4ce297a7f13ddb76f63b88fefb\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode sha1:1d68bc90914ef8a3edbcc8bb28b00cb4fea4b5e2\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode sha1:3686831435b5596515353364eab0399dc45d49e7\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(include_keys=True),
        )

    def test__dump_tree_in_progress(self):
        chkmap = self._get_map(
            {(b"aaa",): b"value1", (b"aab",): b"value2"}, maximum_size=10
        )
        chkmap.map((b"bbb",), b"value3")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(),
        )
        # For things that are updated by adding 'bbb', we don't have a sha key
        # for them yet, so they are listed as None
        self.assertEqualDiff(
            "'' InternalNode None\n"
            "  'a' InternalNode sha1:6b0d881dd739a66f733c178b24da64395edfaafd\n"
            "    'aaa' LeafNode sha1:40b39a08d895babce17b20ae5f62d187eaa4f63a\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode sha1:ad1dc7c4e801302c95bf1ba7b20bc45e548cd51a\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode None\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(include_keys=True),
        )


def _search_key_single(key):
    """A search key function that maps all nodes to the same value."""
    return "value"


def _test_search_key(key):
    return b"test:" + b"\x00".join(key)


class TestMapSearchKeys(TestCaseWithStore):
    def test_default_chk_map_uses_flat_search_key(self):
        chkmap = chk_map.CHKMap(self.get_chk_bytes(), None)
        self.assertEqual(b"1", chkmap._search_key_func((b"1",)))
        self.assertEqual(b"1\x002", chkmap._search_key_func((b"1", b"2")))
        self.assertEqual(b"1\x002\x003", chkmap._search_key_func((b"1", b"2", b"3")))

    def test_search_key_is_passed_to_root_node(self):
        chkmap = chk_map.CHKMap(
            self.get_chk_bytes(), None, search_key_func=_test_search_key
        )
        self.assertIs(_test_search_key, chkmap._search_key_func)
        self.assertEqual(
            b"test:1\x002\x003", chkmap._search_key_func((b"1", b"2", b"3"))
        )
        self.assertEqual(
            b"test:1\x002\x003", chkmap._root_node._search_key((b"1", b"2", b"3"))
        )

    def test_search_key_passed_via__ensure_root(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = chk_map.CHKMap(chk_bytes, None, search_key_func=_test_search_key)
        root_key = chkmap._save()
        chkmap = chk_map.CHKMap(chk_bytes, root_key, search_key_func=_test_search_key)
        chkmap._ensure_root()
        self.assertEqual(
            b"test:1\x002\x003", chkmap._root_node._search_key((b"1", b"2", b"3"))
        )

    def test_search_key_with_internal_node(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = chk_map.CHKMap(chk_bytes, None, search_key_func=_test_search_key)
        chkmap._root_node.set_maximum_size(10)
        chkmap.map((b"1",), b"foo")
        chkmap.map((b"2",), b"bar")
        chkmap.map((b"3",), b"baz")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'test:1' LeafNode\n"
            "      ('1',) 'foo'\n"
            "  'test:2' LeafNode\n"
            "      ('2',) 'bar'\n"
            "  'test:3' LeafNode\n"
            "      ('3',) 'baz'\n",
            chkmap._dump_tree(),
        )
        root_key = chkmap._save()
        chkmap = chk_map.CHKMap(chk_bytes, root_key, search_key_func=_test_search_key)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'test:1' LeafNode\n"
            "      ('1',) 'foo'\n"
            "  'test:2' LeafNode\n"
            "      ('2',) 'bar'\n"
            "  'test:3' LeafNode\n"
            "      ('3',) 'baz'\n",
            chkmap._dump_tree(),
        )

    def test_search_key_16(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = chk_map.CHKMap(chk_bytes, None, search_key_func=chk_map._search_key_16)
        chkmap._root_node.set_maximum_size(10)
        chkmap.map((b"1",), b"foo")
        chkmap.map((b"2",), b"bar")
        chkmap.map((b"3",), b"baz")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '1' LeafNode\n"
            "      ('2',) 'bar'\n"
            "  '6' LeafNode\n"
            "      ('3',) 'baz'\n"
            "  '8' LeafNode\n"
            "      ('1',) 'foo'\n",
            chkmap._dump_tree(),
        )
        root_key = chkmap._save()
        chkmap = chk_map.CHKMap(
            chk_bytes, root_key, search_key_func=chk_map._search_key_16
        )
        # We can get the values back correctly
        self.assertEqual([((b"1",), b"foo")], list(chkmap.iteritems([(b"1",)])))
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '1' LeafNode\n"
            "      ('2',) 'bar'\n"
            "  '6' LeafNode\n"
            "      ('3',) 'baz'\n"
            "  '8' LeafNode\n"
            "      ('1',) 'foo'\n",
            chkmap._dump_tree(),
        )

    def test_search_key_255(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = chk_map.CHKMap(
            chk_bytes, None, search_key_func=chk_map._search_key_255
        )
        chkmap._root_node.set_maximum_size(10)
        chkmap.map((b"1",), b"foo")
        chkmap.map((b"2",), b"bar")
        chkmap.map((b"3",), b"baz")
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '\\x1a' LeafNode\n"
            "      ('2',) 'bar'\n"
            "  'm' LeafNode\n"
            "      ('3',) 'baz'\n"
            "  '\\x83' LeafNode\n"
            "      ('1',) 'foo'\n",
            chkmap._dump_tree(encoding="latin1"),
        )
        root_key = chkmap._save()
        chkmap = chk_map.CHKMap(
            chk_bytes, root_key, search_key_func=chk_map._search_key_255
        )
        # We can get the values back correctly
        self.assertEqual([((b"1",), b"foo")], list(chkmap.iteritems([(b"1",)])))
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  '\\x1a' LeafNode\n"
            "      ('2',) 'bar'\n"
            "  'm' LeafNode\n"
            "      ('3',) 'baz'\n"
            "  '\\x83' LeafNode\n"
            "      ('1',) 'foo'\n",
            chkmap._dump_tree(encoding="latin1"),
        )

    def test_search_key_collisions(self):
        chkmap = chk_map.CHKMap(
            self.get_chk_bytes(), None, search_key_func=_search_key_single
        )
        # The node will want to expand, but it cannot, because it knows that
        # all the keys must map to this node
        chkmap._root_node.set_maximum_size(20)
        chkmap.map((b"1",), b"foo")
        chkmap.map((b"2",), b"bar")
        chkmap.map((b"3",), b"baz")
        self.assertEqualDiff(
            "'' LeafNode\n      ('1',) 'foo'\n      ('2',) 'bar'\n      ('3',) 'baz'\n",
            chkmap._dump_tree(),
        )


class TestLeafNode(TestCaseWithStore):
    def test_current_size_empty(self):
        node = LeafNode()
        self.assertEqual(16, node._current_size())

    def test_current_size_size_changed(self):
        node = LeafNode()
        node.set_maximum_size(10)
        self.assertEqual(17, node._current_size())

    def test_current_size_width_changed(self):
        node = LeafNode()
        node._key_width = 10
        self.assertEqual(17, node._current_size())

    def test_current_size_items(self):
        node = LeafNode()
        base_size = node._current_size()
        node.map(None, (b"foo bar",), b"baz")
        self.assertEqual(base_size + 14, node._current_size())

    def test_deserialise_empty(self):
        node = LeafNode.deserialise(b"chkleaf:\n10\n1\n0\n\n", (b"sha1:1234",))
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertIs(None, node._search_prefix)
        self.assertIs(None, node._common_serialised_prefix)

    def test_deserialise_items(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo bar",), b"baz"), ((b"quux",), b"blarh")],
            sorted(node.iteritems(None)),
        )

    def test_deserialise_item_with_null_width_1(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n1\n2\n\nfoo\x001\nbar\x00baz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo",), b"bar\x00baz"), ((b"quux",), b"blarh")],
            sorted(node.iteritems(None)),
        )

    def test_deserialise_item_with_null_width_2(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n2\n2\n\nfoo\x001\x001\nbar\x00baz\nquux\x00\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo", b"1"), b"bar\x00baz"), ((b"quux", b""), b"blarh")],
            sorted(node.iteritems(None)),
        )

    def test_iteritems_selected_one_of_two_items(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"quux",), b"blarh")],
            sorted(node.iteritems(None, [(b"quux",), (b"qaz",)])),
        )

    def test_deserialise_item_with_common_prefix(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n2\n2\nfoo\x00\n1\x001\nbar\x00baz\n2\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo", b"1"), b"bar\x00baz"), ((b"foo", b"2"), b"blarh")],
            sorted(node.iteritems(None)),
        )
        self.assertIs(chk_map._unknown, node._search_prefix)
        self.assertEqual(b"foo\x00", node._common_serialised_prefix)

    def test_deserialise_multi_line(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n2\n2\nfoo\x00\n1\x002\nbar\nbaz\n2\x002\nblarh\n\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [
                ((b"foo", b"1"), b"bar\nbaz"),
                ((b"foo", b"2"), b"blarh\n"),
            ],
            sorted(node.iteritems(None)),
        )
        self.assertIs(chk_map._unknown, node._search_prefix)
        self.assertEqual(b"foo\x00", node._common_serialised_prefix)

    def test_key_new(self):
        node = LeafNode()
        self.assertEqual(None, node.key())

    def test_key_after_map(self):
        node = LeafNode.deserialise(b"chkleaf:\n10\n1\n0\n\n", (b"sha1:1234",))
        node.map(None, (b"foo bar",), b"baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = LeafNode.deserialise(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        node.unmap(None, (b"foo bar",))
        self.assertEqual(None, node.key())

    def test_map_exceeding_max_size_only_entry_new(self):
        node = LeafNode()
        node.set_maximum_size(10)
        result = node.map(None, (b"foo bar",), b"baz quux")
        self.assertEqual((b"foo bar", [(b"", node)]), result)
        self.assertTrue(node._current_size() > 10)

    def test_map_exceeding_max_size_second_entry_early_difference_new(self):
        node = LeafNode()
        node.set_maximum_size(10)
        node.map(None, (b"foo bar",), b"baz quux")
        prefix, result = list(node.map(None, (b"blue",), b"red"))
        self.assertEqual(b"", prefix)
        self.assertEqual(2, len(result))
        split_chars = {result[0][0], result[1][0]}
        self.assertEqual({b"f", b"b"}, split_chars)
        nodes = dict(result)
        node = nodes[b"f"]
        self.assertEqual({(b"foo bar",): b"baz quux"}, self.to_dict(node, None))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(1, node._key_width)
        node = nodes[b"b"]
        self.assertEqual({(b"blue",): b"red"}, self.to_dict(node, None))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(1, node._key_width)

    def test_map_first(self):
        node = LeafNode()
        result = node.map(None, (b"foo bar",), b"baz quux")
        self.assertEqual((b"foo bar", [(b"", node)]), result)
        self.assertEqual({(b"foo bar",): b"baz quux"}, self.to_dict(node, None))
        self.assertEqual(1, len(node))

    def test_map_second(self):
        node = LeafNode()
        node.map(None, (b"foo bar",), b"baz quux")
        result = node.map(None, (b"bingo",), b"bango")
        self.assertEqual((b"", [(b"", node)]), result)
        self.assertEqual(
            {(b"foo bar",): b"baz quux", (b"bingo",): b"bango"},
            self.to_dict(node, None),
        )
        self.assertEqual(2, len(node))

    def test_map_replacement(self):
        node = LeafNode()
        node.map(None, (b"foo bar",), b"baz quux")
        result = node.map(None, (b"foo bar",), b"bango")
        self.assertEqual((b"foo bar", [(b"", node)]), result)
        self.assertEqual({(b"foo bar",): b"bango"}, self.to_dict(node, None))
        self.assertEqual(1, len(node))

    def test_serialise_empty(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        expected_key = (b"sha1:f34c3f0634ea3f85953dffa887620c0a5b1f4a51",)
        self.assertEqual([expected_key], list(node.serialise(store)))
        self.assertEqual(
            b"chkleaf:\n10\n1\n0\n\n", self.read_bytes(store, expected_key)
        )
        self.assertEqual(expected_key, node.key())

    def test_serialise_items(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        node.map(None, (b"foo bar",), b"baz quux")
        expected_key = (b"sha1:f89fac7edfc6bdb1b1b54a556012ff0c646ef5e0",)
        self.assertEqual(b"foo bar", node._common_serialised_prefix)
        self.assertEqual([expected_key], list(node.serialise(store)))
        self.assertEqual(
            b"chkleaf:\n10\n1\n1\nfoo bar\n\x001\nbaz quux\n",
            self.read_bytes(store, expected_key),
        )
        self.assertEqual(expected_key, node.key())

    def test_unique_serialised_prefix_empty_new(self):
        node = LeafNode()
        self.assertIs(None, node._compute_search_prefix())

    def test_unique_serialised_prefix_one_item_new(self):
        node = LeafNode()
        node.map(None, (b"foo bar", b"baz"), b"baz quux")
        self.assertEqual(b"foo bar\x00baz", node._compute_search_prefix())

    def test_unmap_missing(self):
        node = LeafNode()
        self.assertRaises(KeyError, node.unmap, None, (b"foo bar",))

    def test_unmap_present(self):
        node = LeafNode()
        node.map(None, (b"foo bar",), b"baz quux")
        result = node.unmap(None, (b"foo bar",))
        self.assertEqual(node, result)
        self.assertEqual({}, self.to_dict(node, None))
        self.assertEqual(0, len(node))

    def test_map_maintains_common_prefixes(self):
        node = LeafNode()
        node._key_width = 2
        node.map(None, (b"foo bar", b"baz"), b"baz quux")
        self.assertEqual(b"foo bar\x00baz", node._search_prefix)
        self.assertEqual(b"foo bar\x00baz", node._common_serialised_prefix)
        node.map(None, (b"foo bar", b"bing"), b"baz quux")
        self.assertEqual(b"foo bar\x00b", node._search_prefix)
        self.assertEqual(b"foo bar\x00b", node._common_serialised_prefix)
        node.map(None, (b"fool", b"baby"), b"baz quux")
        self.assertEqual(b"foo", node._search_prefix)
        self.assertEqual(b"foo", node._common_serialised_prefix)
        node.map(None, (b"foo bar", b"baz"), b"replaced")
        self.assertEqual(b"foo", node._search_prefix)
        self.assertEqual(b"foo", node._common_serialised_prefix)
        node.map(None, (b"very", b"different"), b"value")
        self.assertEqual(b"", node._search_prefix)
        self.assertEqual(b"", node._common_serialised_prefix)

    def test_unmap_maintains_common_prefixes(self):
        node = LeafNode()
        node._key_width = 2
        node.map(None, (b"foo bar", b"baz"), b"baz quux")
        node.map(None, (b"foo bar", b"bing"), b"baz quux")
        node.map(None, (b"fool", b"baby"), b"baz quux")
        node.map(None, (b"very", b"different"), b"value")
        self.assertEqual(b"", node._search_prefix)
        self.assertEqual(b"", node._common_serialised_prefix)
        node.unmap(None, (b"very", b"different"))
        self.assertEqual(b"foo", node._search_prefix)
        self.assertEqual(b"foo", node._common_serialised_prefix)
        node.unmap(None, (b"fool", b"baby"))
        self.assertEqual(b"foo bar\x00b", node._search_prefix)
        self.assertEqual(b"foo bar\x00b", node._common_serialised_prefix)
        node.unmap(None, (b"foo bar", b"baz"))
        self.assertEqual(b"foo bar\x00bing", node._search_prefix)
        self.assertEqual(b"foo bar\x00bing", node._common_serialised_prefix)
        node.unmap(None, (b"foo bar", b"bing"))
        self.assertEqual(None, node._search_prefix)
        self.assertEqual(None, node._common_serialised_prefix)


class TestInternalNode(TestCaseWithStore):
    def test_add_node_empty_new(self):
        node = InternalNode(b"fo")
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"foo",), b"bar")
        node.add_node(b"foo", child)
        # Note that node isn't strictly valid now as a tree (only one child),
        # but thats ok for this test.
        # The first child defines the node's width:
        self.assertEqual(3, node._node_width)
        # We should be able to iterate over the contents without doing IO.
        self.assertEqual({(b"foo",): b"bar"}, self.to_dict(node, None))
        # The length should be known:
        self.assertEqual(1, len(node))
        # serialising the node should serialise the child and the node.
        chk_bytes = self.get_chk_bytes()
        keys = list(node.serialise(chk_bytes))
        child_key = child.serialise(chk_bytes)[0]
        self.assertEqual(
            [child_key, (b"sha1:cf67e9997d8228a907c1f5bfb25a8bd9cd916fac",)], keys
        )
        # We should be able to access deserialised content.
        bytes = self.read_bytes(chk_bytes, keys[1])
        node = chk_map._deserialise(bytes, keys[1], None)
        self.assertEqual(1, len(node))
        self.assertEqual({(b"foo",): b"bar"}, self.to_dict(node, chk_bytes))
        self.assertEqual(3, node._node_width)

    def test_add_node_resets_key_new(self):
        node = InternalNode(b"fo")
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"foo",), b"bar")
        node.add_node(b"foo", child)
        chk_bytes = self.get_chk_bytes()
        keys = list(node.serialise(chk_bytes))
        self.assertEqual(keys[1], node._key)
        node.add_node(b"fos", child)
        self.assertEqual(None, node._key)

    #    def test_add_node_empty_oversized_one_ok_new(self):
    #    def test_add_node_one_oversized_second_kept_minimum_fan(self):
    #    def test_add_node_two_oversized_third_kept_minimum_fan(self):
    #    def test_add_node_one_oversized_second_splits_errors(self):

    def test__iter_nodes_no_key_filter(self):
        node = InternalNode(b"")
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"foo",), b"bar")
        node.add_node(b"f", child)
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"bar",), b"baz")
        node.add_node(b"b", child)

        for _child, node_key_filter in node._iter_nodes(None, key_filter=None):
            self.assertEqual(None, node_key_filter)

    def test__iter_nodes_splits_key_filter(self):
        node = InternalNode(b"")
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"foo",), b"bar")
        node.add_node(b"f", child)
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"bar",), b"baz")
        node.add_node(b"b", child)

        # foo and bar both match exactly one leaf node, but 'cat' should not
        # match any, and should not be placed in one.
        key_filter = ((b"foo",), (b"bar",), (b"cat",))
        for _child, node_key_filter in node._iter_nodes(None, key_filter=key_filter):
            # each child could only match one key filter, so make sure it was
            # properly filtered
            self.assertEqual(1, len(node_key_filter))

    def test__iter_nodes_with_multiple_matches(self):
        node = InternalNode(b"")
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"foo",), b"val")
        child.map(None, (b"fob",), b"val")
        node.add_node(b"f", child)
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"bar",), b"val")
        child.map(None, (b"baz",), b"val")
        node.add_node(b"b", child)

        # Note that 'ram' doesn't match anything, so it should be freely
        # ignored
        key_filter = ((b"foo",), (b"fob",), (b"bar",), (b"baz",), (b"ram",))
        for _child, node_key_filter in node._iter_nodes(None, key_filter=key_filter):
            # each child could match two key filters, so make sure they were
            # both included.
            self.assertEqual(2, len(node_key_filter))

    def make_fo_fa_node(self):
        node = InternalNode(b"f")
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"foo",), b"val")
        child.map(None, (b"fob",), b"val")
        node.add_node(b"fo", child)
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, (b"far",), b"val")
        child.map(None, (b"faz",), b"val")
        node.add_node(b"fa", child)
        return node

    def test__iter_nodes_single_entry(self):
        node = self.make_fo_fa_node()
        key_filter = [(b"foo",)]
        nodes = list(node._iter_nodes(None, key_filter=key_filter))
        self.assertEqual(1, len(nodes))
        self.assertEqual(key_filter, nodes[0][1])

    def test__iter_nodes_single_entry_misses(self):
        node = self.make_fo_fa_node()
        key_filter = [(b"bar",)]
        nodes = list(node._iter_nodes(None, key_filter=key_filter))
        self.assertEqual(0, len(nodes))

    def test__iter_nodes_mixed_key_width(self):
        node = self.make_fo_fa_node()
        key_filter = [(b"foo", b"bar"), (b"foo",), (b"fo",), (b"b",)]
        nodes = list(node._iter_nodes(None, key_filter=key_filter))
        self.assertEqual(1, len(nodes))
        matches = key_filter[:]
        matches.remove((b"b",))
        self.assertEqual(sorted(matches), sorted(nodes[0][1]))

    def test__iter_nodes_match_all(self):
        node = self.make_fo_fa_node()
        key_filter = [(b"foo", b"bar"), (b"foo",), (b"fo",), (b"f",)]
        nodes = list(node._iter_nodes(None, key_filter=key_filter))
        self.assertEqual(2, len(nodes))

    def test__iter_nodes_fixed_widths_and_misses(self):
        node = self.make_fo_fa_node()
        # foo and faa should both match one child, baz should miss
        key_filter = [(b"foo",), (b"faa",), (b"baz",)]
        nodes = list(node._iter_nodes(None, key_filter=key_filter))
        self.assertEqual(2, len(nodes))
        for _node, matches in nodes:
            self.assertEqual(1, len(matches))

    def test_iteritems_empty_new(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems(None)))

    def test_iteritems_two_children(self):
        node = InternalNode()
        leaf1 = LeafNode()
        leaf1.map(None, (b"foo bar",), b"quux")
        leaf2 = LeafNode()
        leaf2.map(None, (b"strange",), b"beast")
        node.add_node(b"f", leaf1)
        node.add_node(b"s", leaf2)
        self.assertEqual(
            [((b"foo bar",), b"quux"), ((b"strange",), b"beast")],
            sorted(node.iteritems(None)),
        )

    def test_iteritems_two_children_partial(self):
        node = InternalNode()
        leaf1 = LeafNode()
        leaf1.map(None, (b"foo bar",), b"quux")
        leaf2 = LeafNode()
        leaf2.map(None, (b"strange",), b"beast")
        node.add_node(b"f", leaf1)
        # This sets up a path that should not be followed - it will error if
        # the code tries to.
        node._items[b"f"] = None
        node.add_node(b"s", leaf2)
        self.assertEqual(
            [((b"strange",), b"beast")],
            sorted(node.iteritems(None, [(b"strange",), (b"weird",)])),
        )

    def test_iteritems_two_children_with_hash(self):
        search_key_func = chk_map.search_key_registry.get(b"hash-255-way")
        node = InternalNode(search_key_func=search_key_func)
        leaf1 = LeafNode(search_key_func=search_key_func)
        leaf1.map(
            None,
            StaticTuple(
                b"foo bar",
            ),
            b"quux",
        )
        leaf2 = LeafNode(search_key_func=search_key_func)
        leaf2.map(
            None,
            StaticTuple(
                b"strange",
            ),
            b"beast",
        )
        self.assertEqual(
            b"\xbeF\x014",
            search_key_func(
                StaticTuple(
                    b"foo bar",
                )
            ),
        )
        self.assertEqual(
            b"\x85\xfa\xf7K",
            search_key_func(
                StaticTuple(
                    b"strange",
                )
            ),
        )
        node.add_node(b"\xbe", leaf1)
        # This sets up a path that should not be followed - it will error if
        # the code tries to.
        node._items[b"\xbe"] = None
        node.add_node(b"\x85", leaf2)
        self.assertEqual(
            [((b"strange",), b"beast")],
            sorted(
                node.iteritems(
                    None,
                    [
                        StaticTuple(
                            b"strange",
                        ),
                        StaticTuple(
                            b"weird",
                        ),
                    ],
                )
            ),
        )

    def test_iteritems_partial_empty(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems([(b"missing",)])))

    def test_map_to_new_child_new(self):
        chkmap = self._get_map({(b"k1",): b"foo", (b"k2",): b"bar"}, maximum_size=10)
        chkmap._ensure_root()
        node = chkmap._root_node
        # Ensure test validity: nothing paged in below the root.
        self.assertEqual(
            2,
            len(
                [
                    value
                    for value in node._items.values()
                    if isinstance(value, StaticTuple)
                ]
            ),
        )
        # now, mapping to k3 should add a k3 leaf
        prefix, nodes = node.map(None, (b"k3",), b"quux")
        self.assertEqual(b"k", prefix)
        self.assertEqual([(b"", node)], nodes)
        # check new child details
        child = node._items[b"k3"]
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({(b"k3",): b"quux"}, self.to_dict(child, None))
        self.assertEqual(None, child._key)
        self.assertEqual(10, child.maximum_size)
        self.assertEqual(1, child._key_width)
        # Check overall structure:
        self.assertEqual(3, len(chkmap))
        self.assertEqual(
            {(b"k1",): b"foo", (b"k2",): b"bar", (b"k3",): b"quux"},
            self.to_dict(chkmap),
        )
        # serialising should only serialise the new data - k3 and the internal
        # node.
        keys = list(node.serialise(chkmap._store))
        child_key = child.serialise(chkmap._store)[0]
        self.assertEqual([child_key, keys[1]], keys)

    def test_map_to_child_child_splits_new(self):
        chkmap = self._get_map({(b"k1",): b"foo", (b"k22",): b"bar"}, maximum_size=10)
        # Check for the canonical root value for this tree:
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'k1' LeafNode\n"
            "      ('k1',) 'foo'\n"
            "  'k2' LeafNode\n"
            "      ('k22',) 'bar'\n",
            chkmap._dump_tree(),
        )
        # _dump_tree pages everything in, so reload using just the root
        chkmap = CHKMap(chkmap._store, chkmap._root_node)
        chkmap._ensure_root()
        node = chkmap._root_node
        # Ensure test validity: nothing paged in below the root.
        self.assertEqual(
            2,
            len(
                [
                    value
                    for value in node._items.values()
                    if isinstance(value, StaticTuple)
                ]
            ),
        )
        # now, mapping to k23 causes k22 ('k2' in node) to split into k22 and
        # k23, which for simplicity in the current implementation generates
        # a new internal node between node, and k22/k23.
        prefix, nodes = node.map(chkmap._store, (b"k23",), b"quux")
        self.assertEqual(b"k", prefix)
        self.assertEqual([(b"", node)], nodes)
        # check new child details
        child = node._items[b"k2"]
        self.assertIsInstance(child, InternalNode)
        self.assertEqual(2, len(child))
        self.assertEqual(
            {(b"k22",): b"bar", (b"k23",): b"quux"}, self.to_dict(child, None)
        )
        self.assertEqual(None, child._key)
        self.assertEqual(10, child.maximum_size)
        self.assertEqual(1, child._key_width)
        self.assertEqual(3, child._node_width)
        # Check overall structure:
        self.assertEqual(3, len(chkmap))
        self.assertEqual(
            {(b"k1",): b"foo", (b"k22",): b"bar", (b"k23",): b"quux"},
            self.to_dict(chkmap),
        )
        # serialising should only serialise the new data - although k22 hasn't
        # changed because its a special corner case (splitting on with only one
        # key leaves one node unaltered), in general k22 is serialised, so we
        # expect k22, k23, the new internal node, and node, to be serialised.
        keys = list(node.serialise(chkmap._store))
        child_key = child._key
        k22_key = child._items[b"k22"]._key
        k23_key = child._items[b"k23"]._key
        self.assertEqual({k22_key, k23_key, child_key, node.key()}, set(keys))
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'k1' LeafNode\n"
            "      ('k1',) 'foo'\n"
            "  'k2' InternalNode\n"
            "    'k22' LeafNode\n"
            "      ('k22',) 'bar'\n"
            "    'k23' LeafNode\n"
            "      ('k23',) 'quux'\n",
            chkmap._dump_tree(),
        )

    def test__search_prefix_filter_with_hash(self):
        search_key_func = chk_map.search_key_registry.get(b"hash-16-way")
        node = InternalNode(search_key_func=search_key_func)
        node._key_width = 2
        node._node_width = 4
        self.assertEqual(
            b"E8B7BE43\x0071BEEFF9", search_key_func(StaticTuple(b"a", b"b"))
        )
        self.assertEqual(b"E8B7", node._search_prefix_filter(StaticTuple(b"a", b"b")))
        self.assertEqual(
            b"E8B7",
            node._search_prefix_filter(
                StaticTuple(
                    b"a",
                )
            ),
        )

    def test_unmap_k23_from_k1_k22_k23_gives_k1_k22_tree_new(self):
        chkmap = self._get_map(
            {(b"k1",): b"foo", (b"k22",): b"bar", (b"k23",): b"quux"}, maximum_size=10
        )
        # Check we have the expected tree.
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'k1' LeafNode\n"
            "      ('k1',) 'foo'\n"
            "  'k2' InternalNode\n"
            "    'k22' LeafNode\n"
            "      ('k22',) 'bar'\n"
            "    'k23' LeafNode\n"
            "      ('k23',) 'quux'\n",
            chkmap._dump_tree(),
        )
        chkmap = CHKMap(chkmap._store, chkmap._root_node)
        chkmap._ensure_root()
        node = chkmap._root_node
        # unmapping k23 should give us a root, with k1 and k22 as direct
        # children.
        node.unmap(chkmap._store, (b"k23",))
        # check the pointed-at object within node - k2 should now point at the
        # k22 leaf (which has been paged in to see if we can collapse the tree)
        child = node._items[b"k2"]
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({(b"k22",): b"bar"}, self.to_dict(child, None))
        # Check overall structure is instact:
        self.assertEqual(2, len(chkmap))
        self.assertEqual({(b"k1",): b"foo", (b"k22",): b"bar"}, self.to_dict(chkmap))
        # serialising should only serialise the new data - the root node.
        keys = list(node.serialise(chkmap._store))
        self.assertEqual([keys[-1]], keys)
        chkmap = CHKMap(chkmap._store, keys[-1])
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'k1' LeafNode\n"
            "      ('k1',) 'foo'\n"
            "  'k2' LeafNode\n"
            "      ('k22',) 'bar'\n",
            chkmap._dump_tree(),
        )

    def test_unmap_k1_from_k1_k22_k23_gives_k22_k23_tree_new(self):
        chkmap = self._get_map(
            {(b"k1",): b"foo", (b"k22",): b"bar", (b"k23",): b"quux"}, maximum_size=10
        )
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'k1' LeafNode\n"
            "      ('k1',) 'foo'\n"
            "  'k2' InternalNode\n"
            "    'k22' LeafNode\n"
            "      ('k22',) 'bar'\n"
            "    'k23' LeafNode\n"
            "      ('k23',) 'quux'\n",
            chkmap._dump_tree(),
        )
        orig_root = chkmap._root_node
        chkmap = CHKMap(chkmap._store, orig_root)
        chkmap._ensure_root()
        node = chkmap._root_node
        k2_ptr = node._items[b"k2"]
        # unmapping k1 should give us a root, with k22 and k23 as direct
        # children, and should not have needed to page in the subtree.
        result = node.unmap(chkmap._store, (b"k1",))
        self.assertEqual(k2_ptr, result)
        chkmap = CHKMap(chkmap._store, orig_root)
        # Unmapping at the CHKMap level should switch to the new root
        chkmap.unmap((b"k1",))
        self.assertEqual(k2_ptr, chkmap._root_node)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'k22' LeafNode\n"
            "      ('k22',) 'bar'\n"
            "  'k23' LeafNode\n"
            "      ('k23',) 'quux'\n",
            chkmap._dump_tree(),
        )


# leaf:
# map -> fits - done
# map -> doesn't fit - shrink from left till fits
#        key data to return: the common prefix, new nodes.

# unmap -> how to tell if siblings can be combined.
#          combing leaf nodes means expanding the prefix to the left; so gather the size of
#          all the leaf nodes addressed by expanding the prefix by 1; if any adjacent node
#          is an internal node, we know that that is a dense subtree - can't combine.
#          otherwise as soon as the sum of serialised values exceeds the split threshold
#          we know we can't combine - stop.
# unmap -> key return data - space in node, common prefix length? and key count
# internal:
# variable length prefixes? -> later start with fixed width to get something going
# map -> fits - update pointer to leaf
#        return [prefix and node] - seems sound.
# map -> doesn't fit - find unique prefix and shift right
#        create internal nodes for all the partitions, return list of unique
#        prefixes and nodes.
# map -> new prefix - create a leaf
# unmap -> if child key count 0, remove
# unmap -> return space in node, common prefix length? (why?), key count
# map:
# map, if 1 node returned, use it, otherwise make an internal and populate.
# map - unmap - if empty, use empty leafnode (avoids special cases in driver
# code)
# map inits as empty leafnode.
# tools:
# visualiser


# how to handle:
# AA, AB, AC, AD, BA
# packed internal node - ideal:
# AA, AB, AC, AD, BA
# single byte fanout - A,B,   AA,AB,AC,AD,     BA
# build order's:
# BA
# AB - split, but we want to end up with AB, BA, in one node, with
# 1-4K get0


class TestCHKMapDifference(TestCaseWithExampleMaps):
    def get_difference(self, new_roots, old_roots, search_key_func=None):
        if search_key_func is None:
            search_key_func = chk_map._search_key_plain
        return chk_map.CHKMapDifference(
            self.get_chk_bytes(), new_roots, old_roots, search_key_func
        )

    def test__init__(self):
        c_map = self.make_root_only_map()
        key1 = c_map.key()
        c_map.map((b"aaa",), b"new aaa content")
        key2 = c_map._save()
        diff = self.get_difference([key2], [key1])
        self.assertEqual({key1}, diff._all_old_chks)
        self.assertEqual([], diff._old_queue)
        self.assertEqual([], diff._new_queue)

    def help__read_all_roots(self, search_key_func):
        c_map = self.make_root_only_map(search_key_func=search_key_func)
        key1 = c_map.key()
        c_map.map((b"aaa",), b"new aaa content")
        key2 = c_map._save()
        diff = self.get_difference([key2], [key1], search_key_func)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key2], root_results)
        # We should have queued up only items that aren't in the old
        # set
        self.assertEqual([((b"aaa",), b"new aaa content")], diff._new_item_queue)
        self.assertEqual([], diff._new_queue)
        # And there are no old references, so that queue should be
        # empty
        self.assertEqual([], diff._old_queue)

    def test__read_all_roots_plain(self):
        self.help__read_all_roots(search_key_func=chk_map._search_key_plain)

    def test__read_all_roots_16(self):
        self.help__read_all_roots(search_key_func=chk_map._search_key_16)

    def test__read_all_roots_skips_known_old(self):
        c_map = self.make_one_deep_map(chk_map._search_key_plain)
        key1 = c_map.key()
        c_map2 = self.make_root_only_map(chk_map._search_key_plain)
        key2 = c_map2.key()
        diff = self.get_difference([key2], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        # We should have no results. key2 is completely contained within key1,
        # and we should have seen that in the first pass
        self.assertEqual([], root_results)

    def test__read_all_roots_prepares_queues(self):
        c_map = self.make_one_deep_map(chk_map._search_key_plain)
        key1 = c_map.key()
        c_map._dump_tree()  # load everything
        key1_a = c_map._root_node._items[b"a"].key()
        c_map.map((b"abb",), b"new abb content")
        key2 = c_map._save()
        key2_a = c_map._root_node._items[b"a"].key()
        diff = self.get_difference([key2], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key2], root_results)
        # At this point, we should have queued up only the 'a' Leaf on both
        # sides, both 'c' and 'd' are known to not have changed on both sides
        self.assertEqual([key2_a], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)
        self.assertEqual([key1_a], diff._old_queue)

    def test__read_all_roots_multi_new_prepares_queues(self):
        c_map = self.make_one_deep_map(chk_map._search_key_plain)
        key1 = c_map.key()
        c_map._dump_tree()  # load everything
        key1_a = c_map._root_node._items[b"a"].key()
        key1_c = c_map._root_node._items[b"c"].key()
        c_map.map((b"abb",), b"new abb content")
        key2 = c_map._save()
        key2_a = c_map._root_node._items[b"a"].key()
        c_map._root_node._items[b"c"].key()
        c_map = chk_map.CHKMap(self.get_chk_bytes(), key1, chk_map._search_key_plain)
        c_map.map((b"ccc",), b"new ccc content")
        key3 = c_map._save()
        c_map._root_node._items[b"a"].key()
        key3_c = c_map._root_node._items[b"c"].key()
        diff = self.get_difference([key2, key3], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual(sorted([key2, key3]), sorted(root_results))
        # We should have queued up key2_a, and key3_c, but not key2_c or key3_c
        self.assertEqual({key2_a, key3_c}, set(diff._new_queue))
        self.assertEqual([], diff._new_item_queue)
        # And we should have queued up both a and c for the old set
        self.assertEqual({key1_a, key1_c}, set(diff._old_queue))

    def test__read_all_roots_different_depths(self):
        c_map = self.make_two_deep_map(chk_map._search_key_plain)
        c_map._dump_tree()  # load everything
        key1 = c_map.key()
        key1_a = c_map._root_node._items[b"a"].key()
        key1_c = c_map._root_node._items[b"c"].key()
        key1_d = c_map._root_node._items[b"d"].key()

        c_map2 = self.make_one_deep_two_prefix_map(chk_map._search_key_plain)
        c_map2._dump_tree()
        key2 = c_map2.key()
        key2_aa = c_map2._root_node._items[b"aa"].key()
        key2_ad = c_map2._root_node._items[b"ad"].key()

        diff = self.get_difference([key2], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key2], root_results)
        # Only the 'a' subset should be queued up, since 'c' and 'd' cannot be
        # present
        self.assertEqual([key1_a], diff._old_queue)
        self.assertEqual({key2_aa, key2_ad}, set(diff._new_queue))
        self.assertEqual([], diff._new_item_queue)

        diff = self.get_difference([key1], [key2], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key1], root_results)

        self.assertEqual({key2_aa, key2_ad}, set(diff._old_queue))
        self.assertEqual({key1_a, key1_c, key1_d}, set(diff._new_queue))
        self.assertEqual([], diff._new_item_queue)

    def test__read_all_roots_different_depths_16(self):
        c_map = self.make_two_deep_map(chk_map._search_key_16)
        c_map._dump_tree()  # load everything
        key1 = c_map.key()
        key1_2 = c_map._root_node._items[b"2"].key()
        key1_4 = c_map._root_node._items[b"4"].key()
        key1_C = c_map._root_node._items[b"C"].key()
        key1_F = c_map._root_node._items[b"F"].key()

        c_map2 = self.make_one_deep_two_prefix_map(chk_map._search_key_16)
        c_map2._dump_tree()
        key2 = c_map2.key()
        key2_F0 = c_map2._root_node._items[b"F0"].key()
        key2_F3 = c_map2._root_node._items[b"F3"].key()
        key2_F4 = c_map2._root_node._items[b"F4"].key()
        key2_FD = c_map2._root_node._items[b"FD"].key()

        diff = self.get_difference([key2], [key1], chk_map._search_key_16)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key2], root_results)
        # Only the subset of keys that may be present should be queued up.
        self.assertEqual([key1_F], diff._old_queue)
        self.assertEqual(
            sorted([key2_F0, key2_F3, key2_F4, key2_FD]), sorted(diff._new_queue)
        )
        self.assertEqual([], diff._new_item_queue)

        diff = self.get_difference([key1], [key2], chk_map._search_key_16)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key1], root_results)

        self.assertEqual(
            sorted([key2_F0, key2_F3, key2_F4, key2_FD]), sorted(diff._old_queue)
        )
        self.assertEqual(
            sorted([key1_2, key1_4, key1_C, key1_F]), sorted(diff._new_queue)
        )
        self.assertEqual([], diff._new_item_queue)

    def test__read_all_roots_mixed_depth(self):
        c_map = self.make_one_deep_two_prefix_map(chk_map._search_key_plain)
        c_map._dump_tree()  # load everything
        key1 = c_map.key()
        key1_aa = c_map._root_node._items[b"aa"].key()
        c_map._root_node._items[b"ad"].key()

        c_map2 = self.make_one_deep_one_prefix_map(chk_map._search_key_plain)
        c_map2._dump_tree()
        key2 = c_map2.key()
        key2_a = c_map2._root_node._items[b"a"].key()
        key2_b = c_map2._root_node._items[b"b"].key()

        diff = self.get_difference([key2], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key2], root_results)
        # 'ad' matches exactly 'a' on the other side, so it should be removed,
        # and neither side should have it queued for walking
        self.assertEqual([], diff._old_queue)
        self.assertEqual([key2_b], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)

        diff = self.get_difference([key1], [key2], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key1], root_results)
        # Note: This is technically not the 'true minimal' set that we could
        #       use The reason is that 'a' was matched exactly to 'ad' (by sha
        #       sum).  However, the code gets complicated in the case of more
        #       than one interesting key, so for now, we live with this
        #       Consider revising, though benchmarking showing it to be a
        #       real-world issue should be done
        self.assertEqual([key2_a], diff._old_queue)
        # self.assertEqual([], diff._old_queue)
        self.assertEqual([key1_aa], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)

    def test__read_all_roots_yields_extra_deep_records(self):
        # This is slightly controversial, as we will yield a chk page that we
        # might later on find out could be filtered out. (If a root node is
        # referenced deeper in the old set.)
        # However, even with stacking, we always have all chk pages that we
        # will need. So as long as we filter out the referenced keys, we'll
        # never run into problems.
        # This allows us to yield a root node record immediately, without any
        # buffering.
        c_map = self.make_two_deep_map(chk_map._search_key_plain)
        c_map._dump_tree()  # load all keys
        key1 = c_map.key()
        key1_a = c_map._root_node._items[b"a"].key()
        c_map2 = self.get_map(
            {
                (b"acc",): b"initial acc content",
                (b"ace",): b"initial ace content",
            },
            maximum_size=100,
        )
        self.assertEqualDiff(
            "'' LeafNode\n"
            "      ('acc',) 'initial acc content'\n"
            "      ('ace',) 'initial ace content'\n",
            c_map2._dump_tree(),
        )
        key2 = c_map2.key()
        diff = self.get_difference([key2], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key2], root_results)
        # However, even though we have yielded the root node to be fetched,
        # we should have enqued all of the chk pages to be walked, so that we
        # can find the keys if they are present
        self.assertEqual([key1_a], diff._old_queue)
        self.assertEqual(
            {
                ((b"acc",), b"initial acc content"),
                ((b"ace",), b"initial ace content"),
            },
            set(diff._new_item_queue),
        )

    def test__read_all_roots_multiple_targets(self):
        c_map = self.make_root_only_map()
        key1 = c_map.key()
        c_map = self.make_one_deep_map()
        key2 = c_map.key()
        c_map._dump_tree()
        key2_c = c_map._root_node._items[b"c"].key()
        key2_d = c_map._root_node._items[b"d"].key()
        c_map.map((b"ccc",), b"new ccc value")
        key3 = c_map._save()
        key3_c = c_map._root_node._items[b"c"].key()
        diff = self.get_difference([key2, key3], [key1], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual(sorted([key2, key3]), sorted(root_results))
        self.assertEqual([], diff._old_queue)
        # the key 'd' is interesting from key2 and key3, but should only be
        # entered into the queue 1 time
        self.assertEqual(sorted([key2_c, key3_c, key2_d]), sorted(diff._new_queue))
        self.assertEqual([], diff._new_item_queue)

    def test__read_all_roots_no_old(self):
        # This is the 'initial branch' case. With nothing in the old
        # set, we can just queue up all root nodes into interesting queue, and
        # then have them fast-path flushed via _flush_new_queue
        c_map = self.make_two_deep_map()
        key1 = c_map.key()
        diff = self.get_difference([key1], [], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([], root_results)
        self.assertEqual([], diff._old_queue)
        self.assertEqual([key1], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)

        c_map2 = self.make_one_deep_map()
        key2 = c_map2.key()
        diff = self.get_difference([key1, key2], [], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([], root_results)
        self.assertEqual([], diff._old_queue)
        self.assertEqual(sorted([key1, key2]), sorted(diff._new_queue))
        self.assertEqual([], diff._new_item_queue)

    def test__read_all_roots_no_old_16(self):
        c_map = self.make_two_deep_map(chk_map._search_key_16)
        key1 = c_map.key()
        diff = self.get_difference([key1], [], chk_map._search_key_16)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([], root_results)
        self.assertEqual([], diff._old_queue)
        self.assertEqual([key1], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)

        c_map2 = self.make_one_deep_map(chk_map._search_key_16)
        key2 = c_map2.key()
        diff = self.get_difference([key1, key2], [], chk_map._search_key_16)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([], root_results)
        self.assertEqual([], diff._old_queue)
        self.assertEqual(sorted([key1, key2]), sorted(diff._new_queue))
        self.assertEqual([], diff._new_item_queue)

    def test__read_all_roots_multiple_old(self):
        c_map = self.make_two_deep_map()
        key1 = c_map.key()
        c_map._dump_tree()  # load everything
        key1_a = c_map._root_node._items[b"a"].key()
        c_map.map((b"ccc",), b"new ccc value")
        key2 = c_map._save()
        c_map._root_node._items[b"a"].key()
        c_map.map((b"add",), b"new add value")
        key3 = c_map._save()
        key3_a = c_map._root_node._items[b"a"].key()
        diff = self.get_difference([key3], [key1, key2], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key3], root_results)
        # the 'a' keys should not be queued up 2 times, since they are
        # identical
        self.assertEqual([key1_a], diff._old_queue)
        self.assertEqual([key3_a], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)

    def test__process_next_old_batched_no_dupes(self):
        c_map = self.make_two_deep_map()
        key1 = c_map.key()
        c_map._dump_tree()  # load everything
        key1_a = c_map._root_node._items[b"a"].key()
        key1_aa = c_map._root_node._items[b"a"]._items[b"aa"].key()
        key1_ab = c_map._root_node._items[b"a"]._items[b"ab"].key()
        key1_ac = c_map._root_node._items[b"a"]._items[b"ac"].key()
        key1_ad = c_map._root_node._items[b"a"]._items[b"ad"].key()
        c_map.map((b"aaa",), b"new aaa value")
        key2 = c_map._save()
        key2_a = c_map._root_node._items[b"a"].key()
        key2_aa = c_map._root_node._items[b"a"]._items[b"aa"].key()
        c_map.map((b"acc",), b"new acc content")
        key3 = c_map._save()
        key3_a = c_map._root_node._items[b"a"].key()
        c_map._root_node._items[b"a"]._items[b"ac"].key()
        diff = self.get_difference([key3], [key1, key2], chk_map._search_key_plain)
        root_results = [record.key for record in diff._read_all_roots()]
        self.assertEqual([key3], root_results)
        self.assertEqual(sorted([key1_a, key2_a]), sorted(diff._old_queue))
        self.assertEqual([key3_a], diff._new_queue)
        self.assertEqual([], diff._new_item_queue)
        diff._process_next_old()
        # All of the old records should be brought in and queued up,
        # but we should not have any duplicates
        self.assertEqual(
            sorted([key1_aa, key1_ab, key1_ac, key1_ad, key2_aa]),
            sorted(diff._old_queue),
        )


class TestIterInterestingNodes(TestCaseWithExampleMaps):
    def get_map_key(self, a_dict, maximum_size=10):
        c_map = self.get_map(a_dict, maximum_size=maximum_size)
        return c_map.key()

    def assertIterInteresting(self, records, items, interesting_keys, old_keys):
        """Check the result of iter_interesting_nodes.

        Note that we no longer care how many steps are taken, etc, just that
        the right contents are returned.

        :param records: A list of record keys that should be yielded
        :param items: A list of items (key,value) that should be yielded.
        """
        store = self.get_chk_bytes()
        store._search_key_func = chk_map._search_key_plain
        iter_nodes = chk_map.iter_interesting_nodes(store, interesting_keys, old_keys)
        record_keys = []
        all_items = []
        for record, new_items in iter_nodes:
            if record is not None:
                record_keys.append(record.key)
            if new_items:
                all_items.extend(new_items)
        self.assertEqual(sorted(records), sorted(record_keys))
        self.assertEqual(sorted(items), sorted(all_items))

    def test_empty_to_one_keys(self):
        target = self.get_map_key({(b"a",): b"content"})
        self.assertIterInteresting([target], [((b"a",), b"content")], [target], [])

    def test_none_to_one_key(self):
        basis = self.get_map_key({})
        target = self.get_map_key({(b"a",): b"content"})
        self.assertIterInteresting([target], [((b"a",), b"content")], [target], [basis])

    def test_one_to_none_key(self):
        basis = self.get_map_key({(b"a",): b"content"})
        target = self.get_map_key({})
        self.assertIterInteresting([target], [], [target], [basis])

    def test_common_pages(self):
        basis = self.get_map_key(
            {
                (b"a",): b"content",
                (b"b",): b"content",
                (b"c",): b"content",
            }
        )
        target = self.get_map_key(
            {
                (b"a",): b"content",
                (b"b",): b"other content",
                (b"c",): b"content",
            }
        )
        target_map = CHKMap(self.get_chk_bytes(), target)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('a',) 'content'\n"
            "  'b' LeafNode\n"
            "      ('b',) 'other content'\n"
            "  'c' LeafNode\n"
            "      ('c',) 'content'\n",
            target_map._dump_tree(),
        )
        b_key = target_map._root_node._items[b"b"].key()
        # This should return the root node, and the node for the 'b' key
        self.assertIterInteresting(
            [target, b_key], [((b"b",), b"other content")], [target], [basis]
        )

    def test_common_sub_page(self):
        basis = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"c",): b"common",
            }
        )
        target = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"aab",): b"new",
                (b"c",): b"common",
            }
        )
        target_map = CHKMap(self.get_chk_bytes(), target)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'common'\n"
            "    'aab' LeafNode\n"
            "      ('aab',) 'new'\n"
            "  'c' LeafNode\n"
            "      ('c',) 'common'\n",
            target_map._dump_tree(),
        )
        # The key for the internal aa node
        a_key = target_map._root_node._items[b"a"].key()
        # The key for the leaf aab node
        # aaa_key = target_map._root_node._items['a']._items['aaa'].key()
        aab_key = target_map._root_node._items[b"a"]._items[b"aab"].key()
        self.assertIterInteresting(
            [target, a_key, aab_key], [((b"aab",), b"new")], [target], [basis]
        )

    def test_common_leaf(self):
        basis = self.get_map_key({})
        target1 = self.get_map_key({(b"aaa",): b"common"})
        target2 = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"bbb",): b"new",
            }
        )
        target3 = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"aac",): b"other",
                (b"bbb",): b"new",
            }
        )
        # The LeafNode containing 'aaa': 'common' occurs at 3 different levels.
        # Once as a root node, once as a second layer, and once as a third
        # layer. It should only be returned one time regardless
        target1_map = CHKMap(self.get_chk_bytes(), target1)
        self.assertEqualDiff(
            "'' LeafNode\n      ('aaa',) 'common'\n", target1_map._dump_tree()
        )
        target2_map = CHKMap(self.get_chk_bytes(), target2)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('aaa',) 'common'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'new'\n",
            target2_map._dump_tree(),
        )
        target3_map = CHKMap(self.get_chk_bytes(), target3)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'common'\n"
            "    'aac' LeafNode\n"
            "      ('aac',) 'other'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'new'\n",
            target3_map._dump_tree(),
        )
        target1_map._root_node.key()
        b_key = target2_map._root_node._items[b"b"].key()
        a_key = target3_map._root_node._items[b"a"].key()
        aac_key = target3_map._root_node._items[b"a"]._items[b"aac"].key()
        self.assertIterInteresting(
            [target1, target2, target3, a_key, aac_key, b_key],
            [((b"aaa",), b"common"), ((b"bbb",), b"new"), ((b"aac",), b"other")],
            [target1, target2, target3],
            [basis],
        )

        self.assertIterInteresting(
            [target2, target3, a_key, aac_key, b_key],
            [((b"bbb",), b"new"), ((b"aac",), b"other")],
            [target2, target3],
            [target1],
        )

        # Technically, target1 could be filtered out, but since it is a root
        # node, we yield it immediately, rather than waiting to find out much
        # later on.
        self.assertIterInteresting([target1], [], [target1], [target3])

    def test_multiple_maps(self):
        basis1 = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"aab",): b"basis1",
            }
        )
        basis2 = self.get_map_key(
            {
                (b"bbb",): b"common",
                (b"bbc",): b"basis2",
            }
        )
        target1 = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"aac",): b"target1",
                (b"bbb",): b"common",
            }
        )
        target2 = self.get_map_key(
            {
                (b"aaa",): b"common",
                (b"bba",): b"target2",
                (b"bbb",): b"common",
            }
        )
        target1_map = CHKMap(self.get_chk_bytes(), target1)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aaa' LeafNode\n"
            "      ('aaa',) 'common'\n"
            "    'aac' LeafNode\n"
            "      ('aac',) 'target1'\n"
            "  'b' LeafNode\n"
            "      ('bbb',) 'common'\n",
            target1_map._dump_tree(),
        )
        # The key for the target1 internal a node
        a_key = target1_map._root_node._items[b"a"].key()
        # The key for the leaf aac node
        aac_key = target1_map._root_node._items[b"a"]._items[b"aac"].key()

        target2_map = CHKMap(self.get_chk_bytes(), target2)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('aaa',) 'common'\n"
            "  'b' InternalNode\n"
            "    'bba' LeafNode\n"
            "      ('bba',) 'target2'\n"
            "    'bbb' LeafNode\n"
            "      ('bbb',) 'common'\n",
            target2_map._dump_tree(),
        )
        # The key for the target2 internal bb node
        b_key = target2_map._root_node._items[b"b"].key()
        # The key for the leaf bba node
        bba_key = target2_map._root_node._items[b"b"]._items[b"bba"].key()
        self.assertIterInteresting(
            [target1, target2, a_key, aac_key, b_key, bba_key],
            [((b"aac",), b"target1"), ((b"bba",), b"target2")],
            [target1, target2],
            [basis1, basis2],
        )

    def test_multiple_maps_overlapping_common_new(self):
        # Test that when a node found through the interesting_keys iteration
        # for *some roots* and also via the old keys iteration, that
        # it is still scanned for old refs and items, because its
        # not truely new. This requires 2 levels of InternalNodes to expose,
        # because of the way the bootstrap in _find_children_info works.
        # This suggests that the code is probably amenable to/benefit from
        # consolidation.
        # How does this test work?
        # 1) We need a second level InternalNode present in a basis tree.
        # 2) We need a left side new tree that uses that InternalNode
        # 3) We need a right side new tree that does not use that InternalNode
        #    at all but that has an unchanged *value* that was reachable inside
        #    that InternalNode
        basis = self.get_map_key(
            {
                # InternalNode, unchanged in left:
                (b"aaa",): b"left",
                (b"abb",): b"right",
                # Forces an internalNode at 'a'
                (b"ccc",): b"common",
            }
        )
        left = self.get_map_key(
            {
                # All of basis unchanged
                (b"aaa",): b"left",
                (b"abb",): b"right",
                (b"ccc",): b"common",
                # And a new top level node so the root key is different
                (b"ddd",): b"change",
            }
        )
        right = self.get_map_key(
            {
                # A value that is unchanged from basis and thus should be filtered
                # out.
                (b"abb",): b"right"
            }
        )
        basis_map = CHKMap(self.get_chk_bytes(), basis)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aa' LeafNode\n"
            "      ('aaa',) 'left'\n"
            "    'ab' LeafNode\n"
            "      ('abb',) 'right'\n"
            "  'c' LeafNode\n"
            "      ('ccc',) 'common'\n",
            basis_map._dump_tree(),
        )
        # Get left expected data
        left_map = CHKMap(self.get_chk_bytes(), left)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' InternalNode\n"
            "    'aa' LeafNode\n"
            "      ('aaa',) 'left'\n"
            "    'ab' LeafNode\n"
            "      ('abb',) 'right'\n"
            "  'c' LeafNode\n"
            "      ('ccc',) 'common'\n"
            "  'd' LeafNode\n"
            "      ('ddd',) 'change'\n",
            left_map._dump_tree(),
        )
        # Keys from left side target
        l_d_key = left_map._root_node._items[b"d"].key()
        # Get right expected data
        right_map = CHKMap(self.get_chk_bytes(), right)
        self.assertEqualDiff(
            "'' LeafNode\n      ('abb',) 'right'\n", right_map._dump_tree()
        )
        # Keys from the right side target - none, the root is enough.
        # Test behaviour
        self.assertIterInteresting(
            [right, left, l_d_key], [((b"ddd",), b"change")], [left, right], [basis]
        )

    def test_multiple_maps_similar(self):
        # We want to have a depth=2 tree, with multiple entries in each leaf
        # node
        basis = self.get_map_key(
            {
                (b"aaa",): b"unchanged",
                (b"abb",): b"will change left",
                (b"caa",): b"unchanged",
                (b"cbb",): b"will change right",
            },
            maximum_size=60,
        )
        left = self.get_map_key(
            {
                (b"aaa",): b"unchanged",
                (b"abb",): b"changed left",
                (b"caa",): b"unchanged",
                (b"cbb",): b"will change right",
            },
            maximum_size=60,
        )
        right = self.get_map_key(
            {
                (b"aaa",): b"unchanged",
                (b"abb",): b"will change left",
                (b"caa",): b"unchanged",
                (b"cbb",): b"changed right",
            },
            maximum_size=60,
        )
        basis_map = CHKMap(self.get_chk_bytes(), basis)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('aaa',) 'unchanged'\n"
            "      ('abb',) 'will change left'\n"
            "  'c' LeafNode\n"
            "      ('caa',) 'unchanged'\n"
            "      ('cbb',) 'will change right'\n",
            basis_map._dump_tree(),
        )
        # Get left expected data
        left_map = CHKMap(self.get_chk_bytes(), left)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('aaa',) 'unchanged'\n"
            "      ('abb',) 'changed left'\n"
            "  'c' LeafNode\n"
            "      ('caa',) 'unchanged'\n"
            "      ('cbb',) 'will change right'\n",
            left_map._dump_tree(),
        )
        # Keys from left side target
        l_a_key = left_map._root_node._items[b"a"].key()
        left_map._root_node._items[b"c"].key()
        # Get right expected data
        right_map = CHKMap(self.get_chk_bytes(), right)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('aaa',) 'unchanged'\n"
            "      ('abb',) 'will change left'\n"
            "  'c' LeafNode\n"
            "      ('caa',) 'unchanged'\n"
            "      ('cbb',) 'changed right'\n",
            right_map._dump_tree(),
        )
        right_map._root_node._items[b"a"].key()
        r_c_key = right_map._root_node._items[b"c"].key()
        self.assertIterInteresting(
            [right, left, l_a_key, r_c_key],
            [((b"abb",), b"changed left"), ((b"cbb",), b"changed right")],
            [left, right],
            [basis],
        )

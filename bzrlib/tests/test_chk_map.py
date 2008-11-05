# Copyright (C) 2008 Canonical Ltd
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

"""Tests for maps built on a CHK versionedfiles facility."""

from bzrlib.chk_map import CHKMap, RootNode, InternalNode, LeafNode, ValueNode
from bzrlib.tests import TestCaseWithTransport


class TestCaseWithStore(TestCaseWithTransport):

    def get_chk_bytes(self):
        # The eassiest way to get a CHK store is a development3 repository and
        # then work with the chk_bytes attribute directly.
        repo = self.make_repository(".", format="development3")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        return repo.chk_bytes

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], 'unordered', True)
        return stream.next().get_bytes_as("fulltext")

    def to_dict(self, node):
        return dict(node.iteritems())


class TestMap(TestCaseWithStore):

    def assertHasABMap(self, chk_bytes):
        root_key = ('sha1:29f1da33ce2323d754485fd308abc5ff17f3856e',)
        self.assertEqual(
            "chkroot:\n0\n1\na\x00sha1:cb29f32e561a1b7f862c38ccfd6bc7c7d892f04b\n",
            self.read_bytes(chk_bytes, root_key))
        self.assertEqual(
            "chkvalue:\nb",
            self.read_bytes(chk_bytes,
                ("sha1:cb29f32e561a1b7f862c38ccfd6bc7c7d892f04b",)))

    def assertHasEmptyMap(self, chk_bytes):
        root_key = ('sha1:d0826cf765ff45bd602f602ecb0efbe375ea3b50',)
        self.assertEqual("chkroot:\n0\n0\n", self.read_bytes(chk_bytes, root_key))

    def _get_map(self, a_dict, maximum_size=0):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, a_dict, maximum_size=maximum_size)
        chkmap = CHKMap(chk_bytes, root_key)
        return chkmap

    def test_from_dict_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        self.assertEqual(('sha1:d0826cf765ff45bd602f602ecb0efbe375ea3b50',),
            root_key)
        self.assertHasEmptyMap(chk_bytes)

    def test_from_dict_ab(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {"a":"b"})
        self.assertEqual(('sha1:29f1da33ce2323d754485fd308abc5ff17f3856e',),
            root_key)
        self.assertHasABMap(chk_bytes)

    def test_apply_empty_ab(self):
        # applying a delta (None, "a", "b") to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([(None, "a", "b")])
        self.assertEqual(('sha1:29f1da33ce2323d754485fd308abc5ff17f3856e',),
            new_root)
        self.assertHasABMap(chk_bytes)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_apply_ab_empty(self):
        # applying a delta ("a", None, None) to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {"a":"b"})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([("a", None, None)])
        self.assertEqual(('sha1:d0826cf765ff45bd602f602ecb0efbe375ea3b50',),
            new_root)
        self.assertHasEmptyMap(chk_bytes)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_iteritems_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual([], list(chkmap.iteritems()))

    def test_iteritems_two_items(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes,
            {"a":"content here", "b":"more content"})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual([("a", "content here"), ("b", "more content")],
            sorted(list(chkmap.iteritems())))

    def test_iteritems_selected_one_of_two_items(self):
        chkmap = self._get_map( {"a":"content here", "b":"more content"})
        self.assertEqual([("a", "content here")],
            sorted(list(chkmap.iteritems(["a"]))))

    def test___len__empty(self):
        chkmap = self._get_map({})
        self.assertEqual(0, len(chkmap))

    def test___len__2(self):
        chkmap = self._get_map({"foo":"bar", "gam":"quux"})
        self.assertEqual(2, len(chkmap))

    def test_max_size_100_bytes(self):
        # When there is a 100 byte upper node limit, a tree is formed.
        chkmap = self._get_map({"k1"*50:"v1", "k2"*50:"v2"}, maximum_size=100)
        # We expect three nodes:
        # A root, with two children, and with two key prefixes - k1 to one, and
        # k2 to the other as our node splitting is only just being developed.
        # The maximum size should be embedded
        chkmap._ensure_root()
        self.assertEqual(100, chkmap._root_node.maximum_size)
        # There should be two child nodes, and prefix of 2(bytes):
        self.assertEqual(2, len(chkmap._root_node._nodes))
        self.assertEqual(2, chkmap._root_node.prefix_length)
        # The actual nodes pointed at will change as serialisers change; so
        # here we test that the key prefix is correct; then load the nodes and
        # check they have the right pointed at key; whether they have the
        # pointed at value inline or not is also unrelated to this test so we
        # don't check that.
        nodes = sorted(chkmap._root_node._nodes.items())
        ptr1 = nodes[0]
        ptr2 = nodes[1]
        self.assertEqual('k1', ptr1[0])
        self.assertEqual('k2', ptr2[0])
        node1 = chk_map._deserialise(chkmap._read_bytes(ptr1[1]), ptr1[1])
        self.assertEqual(1, len(node1._nodes))
        self.assertEqual(['k1'*50], node1._nodes.keys())
        node2 = chk_map._deserialise(chkmap._read_bytes(ptr2[1]), ptr2[1])
        self.assertEqual(1, len(node2._nodes))
        self.assertEqual(['k2'*50], node2._nodes.keys())
        # Having checked we have a good structure, check that the content is
        # still accessible.
        self.assertEqual(2, len(chkmap))
        self.assertEqual([("k1"*50, "v1"), ("k2"*50, "v2")],
            sorted(list(chkmap.iteritems())))


class TestRootNode(TestCaseWithTransport):

    def test__current_size(self):
        node = RootNode()
        self.assertEqual(15, node._current_size())
        node.add_child("cd", ("sha1:12345",))
        self.assertEqual(29, node._current_size())
        self.assertEqual(29, len(node.serialise()))
        node.add_child("cd", ("sha1:123456",))
        self.assertEqual(30, node._current_size())
        self.assertEqual(30, len(node.serialise()))
        node.remove_child("cd")
        self.assertEqual(15, node._current_size())
        self.assertEqual(15, len(node.serialise()))
        node.set_maximum_size(100)
        self.assertEqual(17, node._current_size())

    def test_serialise_empty(self):
        node = RootNode()
        bytes = node.serialise()
        self.assertEqual("chkroot:\n0\n0\n0\n", bytes)

    def test_add_child_over_limit(self):
        node = RootNode()
        node.set_maximum_size(20)
        node.add_child("abcdef", ("sha1:12345",))
        size = node._current_size()
        self.assertTrue(20 < size)
        self.assertEqual(False, node.add_child("12345", ("sha1:34",)))
        # Nothing should have changed
        self.assertEqual(size, node._current_size())
        self.assertEqual(1, len(node))

    def test_add_child_resets_key(self):
        node = RootNode()
        node._key = ("something",)
        node.add_child("c", ("sha1:1234",))
        self.assertEqual(None, node._key)

    def test_add_child_returns_True(self):
        node = RootNode()
        node._key = ("something",)
        self.assertEqual(True, node.add_child("c", ("sha1:1234",)))

    def test_add_child_increases_len(self):
        node = RootNode()
        node._key = ("something",)
        node.add_child("c", ("sha1:1234",))
        self.assertEqual(1, len(node))

    def test_remove_child_decreases_len(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        node._key = ("something",)
        node.remove_child("c")
        self.assertEqual(0, len(node))

    def test_remove_child_removes_child(self):
        node = RootNode()
        node.add_child("a", ("sha1:4321",))
        node.add_child("c", ("sha1:1234",))
        node._key = ("something",)
        node.remove_child("a")
        self.assertEqual({"c":("sha1:1234",)}, node._nodes)

    def test_remove_child_resets_key(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        node._key = ("something",)
        node.remove_child("c")
        self.assertEqual(None, node._key)

    def test_deserialise(self):
        # deserialising from a bytestring & key sets the nodes and the known
        # key.
        node = RootNode()
        node.deserialise("chkroot:\n0\n0\n1\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual({"c": ("sha1:1234",)}, node._nodes)
        self.assertEqual(("foo",), node._key)
        self.assertEqual(1, len(node))
        self.assertEqual(0, node.maximum_size)

    def test_serialise_with_child(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        bytes = node.serialise()
        # type 0-max-length 1-value key\x00CHK
        self.assertEqual("chkroot:\n0\n0\n1\nc\x00sha1:1234\n", bytes)

    def test_deserialise_max_size(self):
        node = RootNode()
        node.deserialise("chkroot:\n100\n0\n1\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual(100, node.maximum_size)

    def test_deserialise_key_prefix(self):
        node = RootNode()
        node.deserialise("chkroot:\n100\n10\n1\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual(10, node.prefix_width)


class TestValueNode(TestCaseWithTransport):

    def test_deserialise(self):
        node = ValueNode.deserialise("chkvalue:\nfoo bar baz\n")
        self.assertEqual("foo bar baz\n", node.value)

    def test_serialise(self):
        node = ValueNode("b")
        bytes = node.serialise()
        self.assertEqual("chkvalue:\nb", bytes)


class TestLeafNode(TestCaseWithStore):

    def test_current_size_empty(self):
        node = LeafNode()
        self.assertEqual(15, node._current_size())

    def test_current_size_size_changed(self):
        node = LeafNode()
        node.set_maximum_size(10)
        self.assertEqual(16, node._current_size())

    def test_current_size_width_changed(self):
        node = LeafNode()
        node._key_width = 10
        self.assertEqual(16, node._current_size())

    def test_current_size_items(self):
        node = LeafNode()
        base_size = node._current_size()
        node = node.map(("foo bar",), "baz")
        self.assertEqual(base_size + 12, node._current_size())

    def test_deserialise_empty(self):
        node = LeafNode.deserialise("chkleaf:\n10\n1\n0\n", ("sha1:1234",))
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())

    def test_deserialise_items(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo bar",), "baz"), (("quux",), "blarh")],
            sorted(node.iteritems()))

    def test_iteritems_selected_one_of_two_items(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("quux",), "blarh")],
            sorted(node.iteritems([("quux",), ("qaz",)])))

    def test_key_new(self):
        node = LeafNode()
        self.assertEqual(None, node.key())

    def test_key_after_map(self):
        node = LeafNode.deserialise("chkleaf:\n10\n1\n0\n", ("sha1:1234",))
        node = node.map(("foo bar",), "baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        node = node.unmap(("foo bar",))
        self.assertEqual(None, node.key())

    def test_map_exceeding_max_size_only_entry(self):
        node = LeafNode()
        node.set_maximum_size(10)
        result = node.map(("foo bar",), "baz quux")
        self.assertEqual(result, node)
        self.assertTrue(10 < result._current_size())

    def test_map_exceeding_max_size_second_entry_early_difference(self):
        node = LeafNode()
        node.set_maximum_size(10)
        node = node.map(("foo bar",), "baz quux")
        result = node.map(("blue",), "red")
        self.assertIsInstance(result, InternalNode)
        # should have copied the data in:
        self.assertEqual(2, len(result))
        self.assertEqual({('blue',): 'red', ('foo bar',): 'baz quux'},
            self.to_dict(result))
        self.assertEqual(10, result.maximum_size)
        self.assertEqual(1, result._key_width)

    def test_map_exceeding_max_size_second_entry_last_octect_changed(self):
        node = LeafNode()
        node.set_maximum_size(10)
        node = node.map(("foo bar",), "baz quux")
        result = node.map(("foo baz",), "red")
        self.assertIsInstance(result, InternalNode)
        # should have copied the data in:
        self.assertEqual(2, len(result))
        self.assertEqual({('foo baz',): 'red', ('foo bar',): 'baz quux'},
            self.to_dict(result))
        self.assertEqual(10, result.maximum_size)
        self.assertEqual(1, result._key_width)

    def test_map_first(self):
        node = LeafNode()
        result = node.map(("foo bar",), "baz quux")
        self.assertEqual(result, node)
        self.assertEqual({("foo bar",):"baz quux"}, self.to_dict(node))
        self.assertEqual(1, len(node))

    def test_map_second(self):
        node = LeafNode()
        node = node.map(("foo bar",), "baz quux")
        result = node.map(("bingo",), "bango")
        self.assertEqual(result, node)
        self.assertEqual({("foo bar",):"baz quux", ("bingo",):"bango"},
            self.to_dict(node))
        self.assertEqual(2, len(node))

    def test_map_replacement(self):
        node = LeafNode()
        node = node.map(("foo bar",), "baz quux")
        result = node.map(("foo bar",), "bango")
        self.assertEqual(result, node)
        self.assertEqual({("foo bar",): "bango"},
            self.to_dict(node))
        self.assertEqual(1, len(node))

    def test_serialise_empty(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        expected_key = ("sha1:62cc3565b48b0e830216e652cf99c6bd6b05b4b9",)
        self.assertEqual([expected_key],
            list(node.serialise(store)))
        self.assertEqual("chkleaf:\n10\n1\n0\n", self.read_bytes(store, expected_key))
        self.assertEqual(expected_key, node.key())

    def test_serialise_items(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        node = node.map(("foo bar",), "baz quux")
        expected_key = ("sha1:d44cb6f0299b7e047da7f9e98f810e98f1dce1a7",)
        self.assertEqual([expected_key],
            list(node.serialise(store)))
        self.assertEqual("chkleaf:\n10\n1\n1\nfoo bar\x00baz quux\n",
            self.read_bytes(store, expected_key))
        self.assertEqual(expected_key, node.key())

    def test_unmap_missing(self):
        node = LeafNode()
        self.assertRaises(KeyError, node.unmap, ("foo bar",))

    def test_unmap_present(self):
        node = LeafNode()
        node = node.map(("foo bar",), "baz quux")
        result = node.unmap(("foo bar",))
        self.assertEqual(result, node)
        self.assertEqual({}, self.to_dict(node))
        self.assertEqual(0, len(node))


class TestInternalNode(TestCaseWithStore):

    def test_add_node_empty_oversized_no_common_sets_prefix(self):
        # adding a node with two children that is oversized will generate two
        # new leaf nodes, and a prefix width that cuts one byte off the longest
        # key (because that is sufficient to guarantee a split
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(("foo bar",), "baz")
        overpacked.map(("strange thing",), "it is")
        # at this point, map returned a new internal node that is already
        # packed, but that should have preserved the old node due to the 
        # functional idioms.. check to be sure:
        self.assertTrue(overpacked.maximum_size < overpacked._current_size())
        node = InternalNode()
        # We're not testing that the internal node rebalances yet
        node.set_maximum_size(0)
        node._add_node(overpacked)
        # 13 is the length of strange_thing serialised; as there is no node size
        # set, we pack the internal node as densely as possible.
        self.assertEqual(13, node._node_width)
        self.assertEqual(set(["strange thing", "foo bar\x00\x00\x00\x00\x00\x00"]),
            set(node._items.keys()))
        self.assertEqual(2, len(node))
        self.assertEqual({('strange thing',): 'it is'},
            self.to_dict(node._items["strange thing"]))
        self.assertEqual({('foo bar',): 'baz'},
            self.to_dict(node._items["foo bar\x00\x00\x00\x00\x00\x00"]))

    def test_iteritems_empty(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems()))

    def test_iteritems_two_children(self):
        node = InternalNode()
        leaf1 = LeafNode()
        leaf1.map(('foo bar',), 'quux')
        leaf2 = LeafNode()
        leaf2 = LeafNode()
        leaf2.map(('strange',), 'beast')
        node._items['foo ba'] = leaf1
        node._items['strang'] = leaf2
        self.assertEqual([(('foo bar',), 'quux'), (('strange',), 'beast')],
            sorted(node.iteritems()))

    def test_iteritems_two_children_partial(self):
        node = InternalNode()
        leaf2 = LeafNode()
        leaf2 = LeafNode()
        leaf2.map(('strange',), 'beast')
        # This sets up a path that should not be followed - it will error if
        # the code tries to.
        node._items['foo ba'] = None
        node._items['strang'] = leaf2
        node._node_width = 6
        self.assertEqual([(('strange',), 'beast')],
            sorted(node.iteritems([('strange',), ('weird',)])))

    def test_iteritems_partial_empty(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems([('missing',)])))

    def test_map_to_existing_child(self):
        # mapping a new key which is in a child of an internal node maps
        # recursively.
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(("foo bar",), "baz")
        node = overpacked.map(("foo baz",), "it is")
        self.assertIsInstance(node, InternalNode)
        # Now, increase the maximum size limit on the subnode for foo bar
        child = node._items[node._serialised_key(("foo bar",))]
        child.set_maximum_size(200)
        # And map a new key into node, which will land in the same child node
        result = node.map(("foo bar baz",), "new value")
        self.assertTrue(result is node)
        self.assertEqual(3, len(result))
        self.assertEqual(2, len(child))
        self.assertEqual({('foo bar',): 'baz',
            ('foo bar baz',): 'new value', ('foo baz',): 'it is'},
            self.to_dict(node))

    def test_map_to_existing_child_exceed_child_size_not_internal_size(self):
        # mapping a new key which is in a child of an internal node maps
        # recursively, and when the child splits that is accomodated within the
        # internal node if there is room for another child pointer.
        overpacked = LeafNode()
        overpacked.set_maximum_size(40)
        overpacked.map(("foo bar",), "baz baz baz baz baz baz baz")
        node = overpacked.map(("foo baz",), "it is it is it is it is it is")
        self.assertIsInstance(node, InternalNode)
        # And map a new key into node, which will land in the same child path
        # within node, but trigger a spill event on the child, and should end
        # up with 3 pointers in node (as the pointers can fit in the node
        # space.
        result = node.map(("foo bar baz",),
            "new value new value new value new value new value")
        self.assertTrue(result is node)
        self.assertEqual(3, len(result))
        # We should have one child for foo bar
        child = node._items[node._serialised_key(("foo bar\x00",))]
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        # And one for 'foo bar '
        child = node._items[node._serialised_key(("foo bar ",))]
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({('foo bar',): 'baz baz baz baz baz baz baz',
            ('foo bar baz',): 'new value new value new value',
            ('foo baz',): 'it is it is it is it is it is'},
            self.to_dict(node))

    def test_map_to_new_child(self):
        # mapping a new key which is in a child of an internal node maps
        # recursively.
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(("foo bar",), "baz")
        node = overpacked.map(("foo baz",), "it is")
        self.assertIsInstance(node, InternalNode)
        # Map a new key into node, which will land in a new child node
        result = node.map(("quux",), "new value")
        # Now, increase the maximum size limit on the subnode for foo bar
        child = node._items[node._serialised_key(("quux",))]
        self.assertTrue(result is node)
        self.assertEqual(3, len(result))
        self.assertEqual(1, len(child))
        self.assertEqual({('foo bar',): 'baz',
            ('quux',): 'new value', ('foo baz',): 'it is'},
            self.to_dict(node))

    def test_unmap_second_last_shrinks_to_other_branch(self):
        # unmapping the second last child of an internal node downgrades it to
        # a leaf node.
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(("foo bar",), "baz")
        node = overpacked.map(("strange thing",), "it is")
        self.assertIsInstance(node, InternalNode)
        result = node.unmap(("foo bar",))
        self.assertIsInstance(result, LeafNode)
        self.assertEqual({("strange thing",): "it is"}, self.to_dict(result))

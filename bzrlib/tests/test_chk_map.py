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

from itertools import izip

from bzrlib import chk_map, osutils
from bzrlib.chk_map import (
    CHKMap,
    InternalNode,
    LeafNode,
    _deserialise,
    )
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

    def _get_map(self, a_dict, maximum_size=0, chk_bytes=None, key_width=1):
        if chk_bytes is None:
            chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, a_dict,
            maximum_size=maximum_size, key_width=key_width)
        chkmap = CHKMap(chk_bytes, root_key)
        return chkmap

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], 'unordered', True)
        record = stream.next()
        if record.storage_kind == 'absent':
            self.fail('Store does not contain the key %s' % (key,))
        return record.get_bytes_as("fulltext")

    def to_dict(self, node, *args):
        return dict(node.iteritems(*args))


class TestMap(TestCaseWithStore):

    def assertHasABMap(self, chk_bytes):
        ab_leaf_bytes = 'chkleaf:\n0\n1\n1\na\n\x00b\n'
        ab_sha1 = osutils.sha_string(ab_leaf_bytes)
        self.assertEqual('ffb046e740d93f2108f1c54ae52035578c99fa45', ab_sha1)
        root_key = ('sha1:' + ab_sha1,)
        self.assertEqual(ab_leaf_bytes, self.read_bytes(chk_bytes, root_key))
        return root_key

    def assertHasEmptyMap(self, chk_bytes):
        empty_leaf_bytes = 'chkleaf:\n0\n1\n0\n\n'
        empty_sha1 = osutils.sha_string(empty_leaf_bytes)
        self.assertEqual('8571e09bf1bcc5b9621ce31b3d4c93d6e9a1ed26', empty_sha1)
        root_key = ('sha1:' + empty_sha1,)
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
                self.assertEqualDiff(map_one._dump_tree(include_keys=True),
                                     map_two._dump_tree(include_keys=True))
            self.assertEqual(node_one._search_prefix,
                             node_two._search_prefix)
            if isinstance(node_one, InternalNode):
                # Internal nodes must have identical references
                self.assertEqual(sorted(node_one._items.keys()),
                                 sorted(node_two._items.keys()))
                node_one_stack.extend(node_one._iter_nodes(map_one._store))
                node_two_stack.extend(node_two._iter_nodes(map_two._store))
            else:
                # Leaf nodes must have identical contents
                self.assertEqual(node_one._items, node_two._items)

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
        map_one.map('aaa', 'value')
        self.assertRaises(AssertionError,
            self.assertMapLayoutEqual, map_one, map_two)
        map_two.map('aaa', 'value')
        self.assertMapLayoutEqual(map_one, map_two)
        # Split the tree, so we ensure that internal nodes and leaf nodes are
        # properly checked
        map_one.map('aab', 'value')
        self.assertIsInstance(map_one._root_node, InternalNode)
        self.assertRaises(AssertionError,
            self.assertMapLayoutEqual, map_one, map_two)
        map_two.map('aab', 'value')
        self.assertMapLayoutEqual(map_one, map_two)
        map_one.map('aac', 'value')
        self.assertRaises(AssertionError,
            self.assertMapLayoutEqual, map_one, map_two)
        self.assertCanonicalForm(map_one)

    def test_from_dict_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasEmptyMap(chk_bytes)
        self.assertEqual(expected_root_key, root_key)

    def test_from_dict_ab(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {"a": "b"})
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasABMap(chk_bytes)
        self.assertEqual(expected_root_key, root_key)

    def test_apply_empty_ab(self):
        # applying a delta (None, "a", "b") to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([(None, "a", "b")])
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
        root_key = CHKMap.from_dict(chk_bytes, {("a",):"b"})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([(("a",), None, None)])
        # Check the data was saved and inserted correctly.
        expected_root_key = self.assertHasEmptyMap(chk_bytes)
        self.assertEqual(expected_root_key, new_root)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_apply_delta_is_deterministic(self):
        chk_bytes = self.get_chk_bytes()
        chkmap1 = CHKMap(chk_bytes, None)
        chkmap1._root_node.set_maximum_size(10)
        chkmap1.apply_delta([(None, ('aaa',), 'common'),
                             (None, ('bba',), 'target2'),
                             (None, ('bbb',), 'common')])
        root_key1 = chkmap1._save()
        self.assertCanonicalForm(chkmap1)

        chkmap2 = CHKMap(chk_bytes, None)
        chkmap2._root_node.set_maximum_size(10)
        chkmap2.apply_delta([(None, ('bbb',), 'common'),
                             (None, ('bba',), 'target2'),
                             (None, ('aaa',), 'common')])
        root_key2 = chkmap2._save()
        self.assertEqualDiff(chkmap1._dump_tree(include_keys=True),
                             chkmap2._dump_tree(include_keys=True))
        self.assertEqual(root_key1, root_key2)
        self.assertCanonicalForm(chkmap2)

    def test_stable_splitting(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'v')
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n",
                             chkmap._dump_tree())
        chkmap.map(('aab',), 'v')
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aab',) 'v'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)

        # Creates a new internal node, and splits the others into leaves
        chkmap.map(('aac',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "  'aab' LeafNode\n"
                             "      ('aab',) 'v'\n"
                             "  'aac' LeafNode\n"
                             "      ('aac',) 'v'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)

        # Splits again, because it can't fit in the current structure
        chkmap.map(('bbb',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'a' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'v'\n"
                             "    'aac' LeafNode\n"
                             "      ('aac',) 'v'\n"
                             "  'b' LeafNode\n"
                             "      ('bbb',) 'v'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)

    def test_map_splits_with_longer_key(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 1 key per LeafNode
        chkmap._root_node.set_maximum_size(10)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aaaa',), 'v')
        self.assertCanonicalForm(chkmap)
        self.assertIsInstance(chkmap._root_node, InternalNode)

    def test_with_linefeed_in_key(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 1 key per LeafNode
        chkmap._root_node.set_maximum_size(10)
        chkmap.map(('a\ra',), 'val1')
        chkmap.map(('a\rb',), 'val2')
        chkmap.map(('ac',), 'val3')
        self.assertCanonicalForm(chkmap)
        self.assertEqualDiff("'' InternalNode\n"
                             "  'a\\r' InternalNode\n"
                             "    'a\\ra' LeafNode\n"
                             "      ('a\\ra',) 'val1'\n"
                             "    'a\\rb' LeafNode\n"
                             "      ('a\\rb',) 'val2'\n"
                             "  'ac' LeafNode\n"
                             "      ('ac',) 'val3'\n",
                             chkmap._dump_tree())
        # We should also successfully serialise and deserialise these items
        root_key = chkmap._save()
        chkmap = CHKMap(store, root_key)
        self.assertEqualDiff("'' InternalNode\n"
                             "  'a\\r' InternalNode\n"
                             "    'a\\ra' LeafNode\n"
                             "      ('a\\ra',) 'val1'\n"
                             "    'a\\rb' LeafNode\n"
                             "      ('a\\rb',) 'val2'\n"
                             "  'ac' LeafNode\n"
                             "      ('ac',) 'val3'\n",
                             chkmap._dump_tree())

    def test_deep_splitting(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map(('aaaaaaaa',), 'v')
        chkmap.map(('aaaaabaa',), 'v')
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaaaaaaa',) 'v'\n"
                             "      ('aaaaabaa',) 'v'\n",
                             chkmap._dump_tree())
        chkmap.map(('aaabaaaa',), 'v')
        chkmap.map(('aaababaa',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaaa' LeafNode\n"
                             "      ('aaaaaaaa',) 'v'\n"
                             "      ('aaaaabaa',) 'v'\n"
                             "  'aaab' LeafNode\n"
                             "      ('aaabaaaa',) 'v'\n"
                             "      ('aaababaa',) 'v'\n",
                             chkmap._dump_tree())
        chkmap.map(('aaabacaa',), 'v')
        chkmap.map(('aaabadaa',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
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
                             chkmap._dump_tree())
        chkmap.map(('aaababba',), 'val')
        chkmap.map(('aaababca',), 'val')
        self.assertEqualDiff("'' InternalNode\n"
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
                             chkmap._dump_tree())
        # Now we add a node that should fit around an existing InternalNode,
        # but has a slightly different key prefix, which causes a new
        # InternalNode split
        chkmap.map(('aaabDaaa',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
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
                             chkmap._dump_tree())

    def test_map_collapses_if_size_changes(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aab',), 'very long value that splits')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "  'aab' LeafNode\n"
                             "      ('aab',) 'very long value that splits'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)
        # Now changing the value to something small should cause a rebuild
        chkmap.map(('aab',), 'v')
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aab',) 'v'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)

    def test_map_double_deep_collapses(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 small keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aab',), 'very long value that splits')
        chkmap.map(('abc',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aa' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'very long value that splits'\n"
                             "  'ab' LeafNode\n"
                             "      ('abc',) 'v'\n",
                             chkmap._dump_tree())
        chkmap.map(('aab',), 'v')
        self.assertCanonicalForm(chkmap)
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aab',) 'v'\n"
                             "      ('abc',) 'v'\n",
                             chkmap._dump_tree())

    def test_stable_unmap(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aab',), 'v')
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aab',) 'v'\n",
                             chkmap._dump_tree())
        # Creates a new internal node, and splits the others into leaves
        chkmap.map(('aac',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "  'aab' LeafNode\n"
                             "      ('aab',) 'v'\n"
                             "  'aac' LeafNode\n"
                             "      ('aac',) 'v'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)
        # Now lets unmap one of the keys, and assert that we collapse the
        # structures.
        chkmap.unmap(('aac',))
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aab',) 'v'\n",
                             chkmap._dump_tree())
        self.assertCanonicalForm(chkmap)

    def test_unmap_double_deep(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aaab',), 'v')
        chkmap.map(('aab',), 'very long value')
        chkmap.map(('abc',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aa' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aaab',) 'v'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'very long value'\n"
                             "  'ab' LeafNode\n"
                             "      ('abc',) 'v'\n",
                             chkmap._dump_tree())
        # Removing the 'aab' key should cause everything to collapse back to a
        # single node
        chkmap.unmap(('aab',))
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aaab',) 'v'\n"
                             "      ('abc',) 'v'\n",
                             chkmap._dump_tree())

    def test_unmap_double_deep_non_empty_leaf(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 keys per LeafNode
        chkmap._root_node.set_maximum_size(40)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aab',), 'long value')
        chkmap.map(('aabb',), 'v')
        chkmap.map(('abc',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aa' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'long value'\n"
                             "      ('aabb',) 'v'\n"
                             "  'ab' LeafNode\n"
                             "      ('abc',) 'v'\n",
                             chkmap._dump_tree())
        # Removing the 'aab' key should cause everything to collapse back to a
        # single node
        chkmap.unmap(('aab',))
        self.assertEqualDiff("'' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "      ('aabb',) 'v'\n"
                             "      ('abc',) 'v'\n",
                             chkmap._dump_tree())

    def test_unmap_with_known_internal_node_doesnt_page(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 3 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aab',), 'v')
        chkmap.map(('aac',), 'v')
        chkmap.map(('abc',), 'v')
        chkmap.map(('acd',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
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
                             chkmap._dump_tree())
        # Save everything to the map, and start over
        chkmap = CHKMap(store, chkmap._save())
        # Mapping an 'aa' key loads the internal node, but should not map the
        # 'ab' and 'ac' nodes
        chkmap.map(('aad',), 'v')
        self.assertIsInstance(chkmap._root_node._items['aa'], InternalNode)
        self.assertIsInstance(chkmap._root_node._items['ab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['ac'], tuple)
        # Unmapping 'acd' can notice that 'aa' is an InternalNode and not have
        # to map in 'ab'
        chkmap.unmap(('acd',))
        self.assertIsInstance(chkmap._root_node._items['aa'], InternalNode)
        self.assertIsInstance(chkmap._root_node._items['ab'], tuple)

    def test_unmap_without_fitting_doesnt_page_in(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(20)
        chkmap.map(('aaa',), 'v')
        chkmap.map(('aab',), 'v')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaa' LeafNode\n"
                             "      ('aaa',) 'v'\n"
                             "  'aab' LeafNode\n"
                             "      ('aab',) 'v'\n",
                             chkmap._dump_tree())
        # Save everything to the map, and start over
        chkmap = CHKMap(store, chkmap._save())
        chkmap.map(('aac',), 'v')
        chkmap.map(('aad',), 'v')
        chkmap.map(('aae',), 'v')
        chkmap.map(('aaf',), 'v')
        # At this point, the previous nodes should not be paged in, but the
        # newly added nodes would be
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aac'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aad'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aae'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aaf'], LeafNode)
        # Now unmapping one of the new nodes will use only the already-paged-in
        # nodes to determine that we don't need to do more.
        chkmap.unmap(('aaf',))
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aac'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aad'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aae'], LeafNode)

    def test_unmap_pages_in_if_necessary(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'val')
        chkmap.map(('aab',), 'val')
        chkmap.map(('aac',), 'val')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaa' LeafNode\n"
                             "      ('aaa',) 'val'\n"
                             "  'aab' LeafNode\n"
                             "      ('aab',) 'val'\n"
                             "  'aac' LeafNode\n"
                             "      ('aac',) 'val'\n",
                             chkmap._dump_tree())
        root_key = chkmap._save()
        # Save everything to the map, and start over
        chkmap = CHKMap(store, root_key)
        chkmap.map(('aad',), 'v')
        # At this point, the previous nodes should not be paged in, but the
        # newly added node would be
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aac'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aad'], LeafNode)
        # Unmapping the new node will check the existing nodes to see if they
        # would fit.
        # Clear the page cache so we ensure we have to read all the children
        chk_map._page_cache.clear()
        chkmap.unmap(('aad',))
        self.assertIsInstance(chkmap._root_node._items['aaa'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aab'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aac'], LeafNode)

    def test_unmap_pages_in_from_page_cache(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'val')
        chkmap.map(('aab',), 'val')
        chkmap.map(('aac',), 'val')
        root_key = chkmap._save()
        # Save everything to the map, and start over
        chkmap = CHKMap(store, root_key)
        chkmap.map(('aad',), 'val')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'aaa' LeafNode\n"
                             "      ('aaa',) 'val'\n"
                             "  'aab' LeafNode\n"
                             "      ('aab',) 'val'\n"
                             "  'aac' LeafNode\n"
                             "      ('aac',) 'val'\n"
                             "  'aad' LeafNode\n"
                             "      ('aad',) 'val'\n",
                             chkmap._dump_tree())
        # Save everything to the map, start over after _dump_tree
        chkmap = CHKMap(store, root_key)
        chkmap.map(('aad',), 'v')
        # At this point, the previous nodes should not be paged in, but the
        # newly added node would be
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aac'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aad'], LeafNode)
        # Now clear the page cache, and only include 2 of the children in the
        # cache
        aab_key = chkmap._root_node._items['aab']
        aab_bytes = chk_map._page_cache[aab_key]
        aac_key = chkmap._root_node._items['aac']
        aac_bytes = chk_map._page_cache[aac_key]
        chk_map._page_cache.clear()
        chk_map._page_cache[aab_key] = aab_bytes
        chk_map._page_cache[aac_key] = aac_bytes

        # Unmapping the new node will check the nodes from the page cache
        # first, and not have to read in 'aaa'
        chkmap.unmap(('aad',))
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aac'], LeafNode)

    def test_unmap_uses_existing_items(self):
        store = self.get_chk_bytes()
        chkmap = CHKMap(store, None)
        # Should fit 2 keys per LeafNode
        chkmap._root_node.set_maximum_size(30)
        chkmap.map(('aaa',), 'val')
        chkmap.map(('aab',), 'val')
        chkmap.map(('aac',), 'val')
        root_key = chkmap._save()
        # Save everything to the map, and start over
        chkmap = CHKMap(store, root_key)
        chkmap.map(('aad',), 'val')
        chkmap.map(('aae',), 'val')
        chkmap.map(('aaf',), 'val')
        # At this point, the previous nodes should not be paged in, but the
        # newly added node would be
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aac'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aad'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aae'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aaf'], LeafNode)

        # Unmapping a new node will see the other nodes that are already in
        # memory, and not need to page in anything else
        chkmap.unmap(('aad',))
        self.assertIsInstance(chkmap._root_node._items['aaa'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aab'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aac'], tuple)
        self.assertIsInstance(chkmap._root_node._items['aae'], LeafNode)
        self.assertIsInstance(chkmap._root_node._items['aaf'], LeafNode)

    def test_iter_changes_empty_ab(self):
        # Asking for changes between an empty dict to a dict with keys returns
        # all the keys.
        basis = self._get_map({}, maximum_size=10)
        target = self._get_map(
            {('a',): 'content here', ('b',): 'more content'},
            chk_bytes=basis._store, maximum_size=10)
        self.assertEqual([(('a',), None, 'content here'),
            (('b',), None, 'more content')],
            sorted(list(target.iter_changes(basis))))

    def test_iter_changes_ab_empty(self):
        # Asking for changes between a dict with keys to an empty dict returns
        # all the keys.
        basis = self._get_map({('a',): 'content here', ('b',): 'more content'},
            maximum_size=10)
        target = self._get_map({}, chk_bytes=basis._store, maximum_size=10)
        self.assertEqual([(('a',), 'content here', None),
            (('b',), 'more content', None)],
            sorted(list(target.iter_changes(basis))))

    def test_iter_changes_empty_empty_is_empty(self):
        basis = self._get_map({}, maximum_size=10)
        target = self._get_map({}, chk_bytes=basis._store, maximum_size=10)
        self.assertEqual([], sorted(list(target.iter_changes(basis))))

    def test_iter_changes_ab_ab_is_empty(self):
        basis = self._get_map({('a',): 'content here', ('b',): 'more content'},
            maximum_size=10)
        target = self._get_map(
            {('a',): 'content here', ('b',): 'more content'},
            chk_bytes=basis._store, maximum_size=10)
        self.assertEqual([], sorted(list(target.iter_changes(basis))))

    def test_iter_changes_ab_ab_nodes_not_loaded(self):
        basis = self._get_map({('a',): 'content here', ('b',): 'more content'},
            maximum_size=10)
        target = self._get_map(
            {('a',): 'content here', ('b',): 'more content'},
            chk_bytes=basis._store, maximum_size=10)
        list(target.iter_changes(basis))
        self.assertIsInstance(target._root_node, tuple)
        self.assertIsInstance(basis._root_node, tuple)

    def test_iter_changes_ab_ab_changed_values_shown(self):
        basis = self._get_map({('a',): 'content here', ('b',): 'more content'},
            maximum_size=10)
        target = self._get_map(
            {('a',): 'content here', ('b',): 'different content'},
            chk_bytes=basis._store, maximum_size=10)
        result = sorted(list(target.iter_changes(basis)))
        self.assertEqual([(('b',), 'more content', 'different content')],
            result)

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
        basis_dict = {('aaa',): 'foo bar',
            ('aab',): 'common altered a', ('b',): 'foo bar b'}
        # target splits at byte 1,2, at is target only
        target_dict = {('aaa',): 'foo bar',
            ('aab',): 'common altered b', ('at',): 'foo bar t'}
        changes = [
            (('aab',), 'common altered a', 'common altered b'),
            (('at',), None, 'foo bar t'),
            (('b',), 'foo bar b', None),
            ]
        basis = self._get_map(basis_dict, maximum_size=10)
        target = self._get_map(target_dict, maximum_size=10,
            chk_bytes=basis._store)
        self.assertEqual(changes, sorted(list(target.iter_changes(basis))))

    def test_iter_changes_common_pages_not_loaded(self):
        # aaa - common unaltered
        # aab - common altered
        # b - basis only
        # at - target only
        # we expect:
        # aaa to be not loaded
        # aaa not to be in result.
        basis_dict = {('aaa',): 'foo bar',
            ('aab',): 'common altered a', ('b',): 'foo bar b'}
        # target splits at byte 1, at is target only
        target_dict = {('aaa',): 'foo bar',
            ('aab',): 'common altered b', ('at',): 'foo bar t'}
        basis = self._get_map(basis_dict, maximum_size=10)
        target = self._get_map(target_dict, maximum_size=10,
            chk_bytes=basis._store)
        basis_get = basis._store.get_record_stream
        def get_record_stream(keys, order, fulltext):
            if ('sha1:1adf7c0d1b9140ab5f33bb64c6275fa78b1580b7',) in keys:
                self.fail("'aaa' pointer was followed %r" % keys)
            return basis_get(keys, order, fulltext)
        basis._store.get_record_stream = get_record_stream
        result = sorted(list(target.iter_changes(basis)))
        for change in result:
            if change[0] == ('aaa',):
                self.fail("Found unexpected change: %s" % change)

    def test_iter_changes_unchanged_keys_in_multi_key_leafs_ignored(self):
        # Within a leaf there are no hash's to exclude keys, make sure multi
        # value leaf nodes are handled well.
        basis_dict = {('aaa',): 'foo bar',
            ('aab',): 'common altered a', ('b',): 'foo bar b'}
        target_dict = {('aaa',): 'foo bar',
            ('aab',): 'common altered b', ('at',): 'foo bar t'}
        changes = [
            (('aab',), 'common altered a', 'common altered b'),
            (('at',), None, 'foo bar t'),
            (('b',), 'foo bar b', None),
            ]
        basis = self._get_map(basis_dict)
        target = self._get_map(target_dict, chk_bytes=basis._store)
        self.assertEqual(changes, sorted(list(target.iter_changes(basis))))

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
        self.assertEqual([(("a",), "content here"), (("b",), "more content")],
            sorted(list(chkmap.iteritems())))

    def test_iteritems_selected_one_of_two_items(self):
        chkmap = self._get_map( {("a",):"content here", ("b",):"more content"})
        self.assertEqual({("a",): "content here"},
            self.to_dict(chkmap, [("a",)]))

    def test_iteritems_keys_prefixed_by_2_width_nodes(self):
        chkmap = self._get_map(
            {("a","a"):"content here", ("a", "b",):"more content",
             ("b", ""): 'boring content'},
            maximum_size=10, key_width=2)
        self.assertEqual(
            {("a", "a"): "content here", ("a", "b"): 'more content'},
            self.to_dict(chkmap, [("a",)]))

    def test_iteritems_keys_prefixed_by_2_width_one_leaf(self):
        chkmap = self._get_map(
            {("a","a"):"content here", ("a", "b",):"more content",
             ("b", ""): 'boring content'}, key_width=2)
        self.assertEqual(
            {("a", "a"): "content here", ("a", "b"): 'more content'},
            self.to_dict(chkmap, [("a",)]))

    def test___len__empty(self):
        chkmap = self._get_map({})
        self.assertEqual(0, len(chkmap))

    def test___len__2(self):
        chkmap = self._get_map({"foo":"bar", "gam":"quux"})
        self.assertEqual(2, len(chkmap))

    def test_max_size_100_bytes_new(self):
        # When there is a 100 byte upper node limit, a tree is formed.
        chkmap = self._get_map({("k1"*50,):"v1", ("k2"*50,):"v2"}, maximum_size=100)
        # We expect three nodes:
        # A root, with two children, and with two key prefixes - k1 to one, and
        # k2 to the other as our node splitting is only just being developed.
        # The maximum size should be embedded
        chkmap._ensure_root()
        self.assertEqual(100, chkmap._root_node.maximum_size)
        self.assertEqual(1, chkmap._root_node._key_width)
        # There should be two child nodes, and prefix of 2(bytes):
        self.assertEqual(2, len(chkmap._root_node._items))
        self.assertEqual("k", chkmap._root_node._compute_search_prefix())
        # The actual nodes pointed at will change as serialisers change; so
        # here we test that the key prefix is correct; then load the nodes and
        # check they have the right pointed at key; whether they have the
        # pointed at value inline or not is also unrelated to this test so we
        # don't check that in detail - rather we just check the aggregate
        # value.
        nodes = sorted(chkmap._root_node._items.items())
        ptr1 = nodes[0]
        ptr2 = nodes[1]
        self.assertEqual('k1', ptr1[0])
        self.assertEqual('k2', ptr2[0])
        node1 = _deserialise(chkmap._read_bytes(ptr1[1]), ptr1[1])
        self.assertIsInstance(node1, LeafNode)
        self.assertEqual(1, len(node1))
        self.assertEqual({('k1'*50,): 'v1'}, self.to_dict(node1, chkmap._store))
        node2 = _deserialise(chkmap._read_bytes(ptr2[1]), ptr2[1])
        self.assertIsInstance(node2, LeafNode)
        self.assertEqual(1, len(node2))
        self.assertEqual({('k2'*50,): 'v2'}, self.to_dict(node2, chkmap._store))
        # Having checked we have a good structure, check that the content is
        # still accessible.
        self.assertEqual(2, len(chkmap))
        self.assertEqual({("k1"*50,): "v1", ("k2"*50,): "v2"},
            self.to_dict(chkmap))

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
        chkmap.map(("foo,",), "bar")
        self.assertEqual({('foo,',): 'bar'}, self.to_dict(chkmap))
        self.assertEqual(1, len(chkmap))
        key = chkmap._save()
        leaf_node = LeafNode()
        leaf_node.map(chk_bytes, ("foo,",), "bar")
        self.assertEqual([key], leaf_node.serialise(chk_bytes))

    def test_unmap_last_item_root_is_leaf_new(self):
        chkmap = self._get_map({("k1"*50,): "v1", ("k2"*50,): "v2"})
        chkmap.unmap(("k1"*50,))
        chkmap.unmap(("k2"*50,))
        self.assertEqual(0, len(chkmap))
        self.assertEqual({}, self.to_dict(chkmap))
        key = chkmap._save()
        leaf_node = LeafNode()
        self.assertEqual([key], leaf_node.serialise(chkmap._store))

    def test__dump_tree(self):
        chkmap = self._get_map({("aaa",): "value1", ("aab",): "value2",
                                ("bbb",): "value3",},
                               maximum_size=10)
        self.assertEqualDiff("'' InternalNode\n"
                             "  'a' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'value1'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'value2'\n"
                             "  'b' LeafNode\n"
                             "      ('bbb',) 'value3'\n",
                             chkmap._dump_tree())
        self.assertEqualDiff("'' InternalNode\n"
                             "  'a' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'value1'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'value2'\n"
                             "  'b' LeafNode\n"
                             "      ('bbb',) 'value3'\n",
                             chkmap._dump_tree())
        self.assertEqualDiff(
            "'' InternalNode sha1:9c0e7f6cca48983d33e03897b847710c27fd78ad\n"
            "  'a' InternalNode sha1:771cd596632557845720770a0e4829d8065d53da\n"
            "    'aaa' LeafNode sha1:6cabbca9713908aff819d79b3688e181c6eab8b2\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode sha1:c11b2aa06649e62846acbdff810fca5718c23ba6\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode sha1:5036c643a1c6491ae76d6bb0fd927f3a40d63ee8\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(include_keys=True))

    def test__dump_tree_in_progress(self):
        chkmap = self._get_map({("aaa",): "value1", ("aab",): "value2"},
                               maximum_size=10)
        chkmap.map(('bbb',), 'value3')
        self.assertEqualDiff("'' InternalNode\n"
                             "  'a' InternalNode\n"
                             "    'aaa' LeafNode\n"
                             "      ('aaa',) 'value1'\n"
                             "    'aab' LeafNode\n"
                             "      ('aab',) 'value2'\n"
                             "  'b' LeafNode\n"
                             "      ('bbb',) 'value3'\n",
                             chkmap._dump_tree())
        # For things that are updated by adding 'bbb', we don't have a sha key
        # for them yet, so they are listed as None
        self.assertEqualDiff(
            "'' InternalNode None\n"
            "  'a' InternalNode sha1:771cd596632557845720770a0e4829d8065d53da\n"
            "    'aaa' LeafNode sha1:6cabbca9713908aff819d79b3688e181c6eab8b2\n"
            "      ('aaa',) 'value1'\n"
            "    'aab' LeafNode sha1:c11b2aa06649e62846acbdff810fca5718c23ba6\n"
            "      ('aab',) 'value2'\n"
            "  'b' LeafNode None\n"
            "      ('bbb',) 'value3'\n",
            chkmap._dump_tree(include_keys=True))


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
        node.map(None, ("foo bar",), "baz")
        self.assertEqual(base_size + 12, node._current_size())

    def test_deserialise_empty(self):
        node = LeafNode.deserialise("chkleaf:\n10\n1\n0\n\n", ("sha1:1234",))
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertIs(None, node._search_prefix)
        self.assertIs(None, node._common_serialised_prefix)

    def test_deserialise_items(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\n\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo bar",), "baz"), (("quux",), "blarh")],
            sorted(node.iteritems(None)))

    def test_deserialise_item_with_null_width_1(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\n\nfoo\x00bar\x00baz\nquux\x00blarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo",), "bar\x00baz"), (("quux",), "blarh")],
            sorted(node.iteritems(None)))

    def test_deserialise_item_with_null_width_2(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n2\n2\n\nfoo\x001\x00bar\x00baz\nquux\x00\x00blarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo", "1"), "bar\x00baz"), (("quux", ""), "blarh")],
            sorted(node.iteritems(None)))

    def test_iteritems_selected_one_of_two_items(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\n\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("quux",), "blarh")],
            sorted(node.iteritems(None, [("quux",), ("qaz",)])))

    def test_deserialise_item_with_common_prefix(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n2\n2\nfoo\x00\n1\x00bar\x00baz\n2\x00blarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo", "1"), "bar\x00baz"), (("foo", "2"), "blarh")],
            sorted(node.iteritems(None)))
        self.assertEqual('foo\x00', node._search_prefix)
        self.assertEqual('foo\x00', node._common_serialised_prefix)

    def test_key_new(self):
        node = LeafNode()
        self.assertEqual(None, node.key())

    def test_key_after_map(self):
        node = LeafNode.deserialise("chkleaf:\n10\n1\n0\n\n", ("sha1:1234",))
        node.map(None, ("foo bar",), "baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\n\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        node.unmap(None, ("foo bar",))
        self.assertEqual(None, node.key())

    def test_map_exceeding_max_size_only_entry_new(self):
        node = LeafNode()
        node.set_maximum_size(10)
        result = node.map(None, ("foo bar",), "baz quux")
        self.assertEqual(("foo bar", [("", node)]), result)
        self.assertTrue(10 < node._current_size())

    def test_map_exceeding_max_size_second_entry_early_difference_new(self):
        node = LeafNode()
        node.set_maximum_size(10)
        node.map(None, ("foo bar",), "baz quux")
        prefix, result = list(node.map(None, ("blue",), "red"))
        self.assertEqual("", prefix)
        self.assertEqual(2, len(result))
        split_chars = set([result[0][0], result[1][0]])
        self.assertEqual(set(["f", "b"]), split_chars)
        nodes = dict(result)
        node = nodes["f"]
        self.assertEqual({("foo bar",): "baz quux"}, self.to_dict(node, None))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(1, node._key_width)
        node = nodes["b"]
        self.assertEqual({("blue",): "red"}, self.to_dict(node, None))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(1, node._key_width)

    def test_map_first(self):
        node = LeafNode()
        result = node.map(None, ("foo bar",), "baz quux")
        self.assertEqual(("foo bar", [("", node)]), result)
        self.assertEqual({("foo bar",):"baz quux"}, self.to_dict(node, None))
        self.assertEqual(1, len(node))

    def test_map_second(self):
        node = LeafNode()
        node.map(None, ("foo bar",), "baz quux")
        result = node.map(None, ("bingo",), "bango")
        self.assertEqual(("", [("", node)]), result)
        self.assertEqual({("foo bar",):"baz quux", ("bingo",):"bango"},
            self.to_dict(node, None))
        self.assertEqual(2, len(node))

    def test_map_replacement(self):
        node = LeafNode()
        node.map(None, ("foo bar",), "baz quux")
        result = node.map(None, ("foo bar",), "bango")
        self.assertEqual(("foo bar", [("", node)]), result)
        self.assertEqual({("foo bar",): "bango"},
            self.to_dict(node, None))
        self.assertEqual(1, len(node))

    def test_serialise_empty(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        expected_key = ("sha1:f34c3f0634ea3f85953dffa887620c0a5b1f4a51",)
        self.assertEqual([expected_key],
            list(node.serialise(store)))
        self.assertEqual("chkleaf:\n10\n1\n0\n\n", self.read_bytes(store, expected_key))
        self.assertEqual(expected_key, node.key())

    def test_serialise_items(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        node.map(None, ("foo bar",), "baz quux")
        expected_key = ("sha1:f98fcfe7d3fc59c29134a5d5438c896e57cefe6d",)
        self.assertEqual('foo bar', node._common_serialised_prefix)
        self.assertEqual([expected_key],
            list(node.serialise(store)))
        self.assertEqual("chkleaf:\n10\n1\n1\nfoo bar\n\x00baz quux\n",
            self.read_bytes(store, expected_key))
        self.assertEqual(expected_key, node.key())

    def test_unique_serialised_prefix_empty_new(self):
        node = LeafNode()
        self.assertIs(None, node._compute_search_prefix())

    def test_unique_serialised_prefix_one_item_new(self):
        node = LeafNode()
        node.map(None, ("foo bar", "baz"), "baz quux")
        self.assertEqual("foo bar\x00baz", node._compute_search_prefix())

    def test_unmap_missing(self):
        node = LeafNode()
        self.assertRaises(KeyError, node.unmap, None, ("foo bar",))

    def test_unmap_present(self):
        node = LeafNode()
        node.map(None, ("foo bar",), "baz quux")
        result = node.unmap(None, ("foo bar",))
        self.assertEqual(node, result)
        self.assertEqual({}, self.to_dict(node, None))
        self.assertEqual(0, len(node))

    def test_map_maintains_common_prefixes(self):
        node = LeafNode()
        node._key_width = 2
        node.map(None, ("foo bar", "baz"), "baz quux")
        self.assertEqual('foo bar\x00baz', node._search_prefix)
        self.assertEqual('foo bar\x00baz', node._common_serialised_prefix)
        node.map(None, ("foo bar", "bing"), "baz quux")
        self.assertEqual('foo bar\x00b', node._search_prefix)
        self.assertEqual('foo bar\x00b', node._common_serialised_prefix)
        node.map(None, ("fool", "baby"), "baz quux")
        self.assertEqual('foo', node._search_prefix)
        self.assertEqual('foo', node._common_serialised_prefix)
        node.map(None, ("foo bar", "baz"), "replaced")
        self.assertEqual('foo', node._search_prefix)
        self.assertEqual('foo', node._common_serialised_prefix)
        node.map(None, ("very", "different"), "value")
        self.assertEqual('', node._search_prefix)
        self.assertEqual('', node._common_serialised_prefix)

    def test_unmap_maintains_common_prefixes(self):
        node = LeafNode()
        node._key_width = 2
        node.map(None, ("foo bar", "baz"), "baz quux")
        node.map(None, ("foo bar", "bing"), "baz quux")
        node.map(None, ("fool", "baby"), "baz quux")
        node.map(None, ("very", "different"), "value")
        self.assertEqual('', node._search_prefix)
        self.assertEqual('', node._common_serialised_prefix)
        node.unmap(None, ("very", "different"))
        self.assertEqual("foo", node._search_prefix)
        self.assertEqual("foo", node._common_serialised_prefix)
        node.unmap(None, ("fool", "baby"))
        self.assertEqual('foo bar\x00b', node._search_prefix)
        self.assertEqual('foo bar\x00b', node._common_serialised_prefix)
        node.unmap(None, ("foo bar", "baz"))
        self.assertEqual('foo bar\x00bing', node._search_prefix)
        self.assertEqual('foo bar\x00bing', node._common_serialised_prefix)
        node.unmap(None, ("foo bar", "bing"))
        self.assertEqual(None, node._search_prefix)
        self.assertEqual(None, node._common_serialised_prefix)


class TestInternalNode(TestCaseWithStore):

    def test_add_node_empty_new(self):
        node = InternalNode('fo')
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, ("foo",), "bar")
        node.add_node("foo", child)
        # Note that node isn't strictly valid now as a tree (only one child),
        # but thats ok for this test.
        # The first child defines the node's width:
        self.assertEqual(3, node._node_width)
        # We should be able to iterate over the contents without doing IO.
        self.assertEqual({('foo',): 'bar'}, self.to_dict(node, None))
        # The length should be known:
        self.assertEqual(1, len(node))
        # serialising the node should serialise the child and the node.
        chk_bytes = self.get_chk_bytes()
        keys = list(node.serialise(chk_bytes))
        child_key = child.serialise(chk_bytes)[0]
        self.assertEqual(
            [child_key, ('sha1:72dda40e7c70d00cde178f6f79560d36f3264ba5',)],
            keys)
        # We should be able to access deserialised content.
        bytes = self.read_bytes(chk_bytes, keys[1])
        node = _deserialise(bytes, keys[1])
        self.assertEqual(1, len(node))
        self.assertEqual({('foo',): 'bar'}, self.to_dict(node, chk_bytes))
        self.assertEqual(3, node._node_width)

    def test_add_node_resets_key_new(self):
        node = InternalNode('fo')
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, ("foo",), "bar")
        node.add_node("foo", child)
        chk_bytes = self.get_chk_bytes()
        keys = list(node.serialise(chk_bytes))
        self.assertEqual(keys[1], node._key)
        node.add_node("fos", child)
        self.assertEqual(None, node._key)

#    def test_add_node_empty_oversized_one_ok_new(self):
#    def test_add_node_one_oversized_second_kept_minimum_fan(self):
#    def test_add_node_two_oversized_third_kept_minimum_fan(self):
#    def test_add_node_one_oversized_second_splits_errors(self):

    def test_iteritems_empty_new(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems(None)))

    def test_iteritems_two_children(self):
        node = InternalNode()
        leaf1 = LeafNode()
        leaf1.map(None, ('foo bar',), 'quux')
        leaf2 = LeafNode()
        leaf2.map(None, ('strange',), 'beast')
        node.add_node("f", leaf1)
        node.add_node("s", leaf2)
        self.assertEqual([(('foo bar',), 'quux'), (('strange',), 'beast')],
            sorted(node.iteritems(None)))

    def test_iteritems_two_children_partial(self):
        node = InternalNode()
        leaf1 = LeafNode()
        leaf1.map(None, ('foo bar',), 'quux')
        leaf2 = LeafNode()
        leaf2.map(None, ('strange',), 'beast')
        node.add_node("f", leaf1)
        # This sets up a path that should not be followed - it will error if
        # the code tries to.
        node._items['f'] = None
        node.add_node("s", leaf2)
        self.assertEqual([(('strange',), 'beast')],
            sorted(node.iteritems(None, [('strange',), ('weird',)])))

    def test_iteritems_partial_empty(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems([('missing',)])))

    def test_map_to_new_child_new(self):
        chkmap = self._get_map({('k1',):'foo', ('k2',):'bar'}, maximum_size=10)
        chkmap._ensure_root()
        node = chkmap._root_node
        # Ensure test validity: nothing paged in below the root.
        self.assertEqual(2,
            len([value for value in node._items.values()
                if type(value) == tuple]))
        # now, mapping to k3 should add a k3 leaf
        prefix, nodes = node.map(None, ('k3',), 'quux')
        self.assertEqual("k", prefix)
        self.assertEqual([("", node)], nodes)
        # check new child details
        child = node._items['k3']
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({('k3',): 'quux'}, self.to_dict(child, None))
        self.assertEqual(None, child._key)
        self.assertEqual(10, child.maximum_size)
        self.assertEqual(1, child._key_width)
        # Check overall structure:
        self.assertEqual(3, len(chkmap))
        self.assertEqual({('k1',): 'foo', ('k2',): 'bar', ('k3',): 'quux'},
            self.to_dict(chkmap))
        # serialising should only serialise the new data - k3 and the internal
        # node.
        keys = list(node.serialise(chkmap._store))
        child_key = child.serialise(chkmap._store)[0]
        self.assertEqual([child_key, keys[1]], keys)

    def test_map_to_child_child_splits_new(self):
        chkmap = self._get_map({('k1',):'foo', ('k22',):'bar'}, maximum_size=10)
        # Check for the canonical root value for this tree:
        self.assertEqualDiff("'' InternalNode\n"
                             "  'k1' LeafNode\n"
                             "      ('k1',) 'foo'\n"
                             "  'k2' LeafNode\n"
                             "      ('k22',) 'bar'\n"
                             , chkmap._dump_tree())
        # _dump_tree pages everything in, so reload using just the root
        chkmap = CHKMap(chkmap._store, chkmap._root_node)
        chkmap._ensure_root()
        node = chkmap._root_node
        # Ensure test validity: nothing paged in below the root.
        self.assertEqual(2,
            len([value for value in node._items.values()
                if type(value) == tuple]))
        # now, mapping to k23 causes k22 ('k2' in node) to split into k22 and
        # k23, which for simplicity in the current implementation generates
        # a new internal node between node, and k22/k23.
        prefix, nodes = node.map(chkmap._store, ('k23',), 'quux')
        self.assertEqual("k", prefix)
        self.assertEqual([("", node)], nodes)
        # check new child details
        child = node._items['k2']
        self.assertIsInstance(child, InternalNode)
        self.assertEqual(2, len(child))
        self.assertEqual({('k22',): 'bar', ('k23',): 'quux'},
            self.to_dict(child, None))
        self.assertEqual(None, child._key)
        self.assertEqual(10, child.maximum_size)
        self.assertEqual(1, child._key_width)
        self.assertEqual(3, child._node_width)
        # Check overall structure:
        self.assertEqual(3, len(chkmap))
        self.assertEqual({('k1',): 'foo', ('k22',): 'bar', ('k23',): 'quux'},
            self.to_dict(chkmap))
        # serialising should only serialise the new data - although k22 hasn't
        # changed because its a special corner case (splitting on with only one
        # key leaves one node unaltered), in general k22 is serialised, so we
        # expect k22, k23, the new internal node, and node, to be serialised.
        keys = list(node.serialise(chkmap._store))
        child_key = child._key
        k22_key = child._items['k22']._key
        k23_key = child._items['k23']._key
        self.assertEqual([k22_key, k23_key, child_key, node.key()], keys)
        self.assertEqualDiff("'' InternalNode\n"
                             "  'k1' LeafNode\n"
                             "      ('k1',) 'foo'\n"
                             "  'k2' InternalNode\n"
                             "    'k22' LeafNode\n"
                             "      ('k22',) 'bar'\n"
                             "    'k23' LeafNode\n"
                             "      ('k23',) 'quux'\n"
                             , chkmap._dump_tree())

    def test_unmap_k23_from_k1_k22_k23_gives_k1_k22_tree_new(self):
        chkmap = self._get_map(
            {('k1',):'foo', ('k22',):'bar', ('k23',): 'quux'}, maximum_size=10)
        # Check we have the expected tree.
        self.assertEqualDiff("'' InternalNode\n"
                             "  'k1' LeafNode\n"
                             "      ('k1',) 'foo'\n"
                             "  'k2' InternalNode\n"
                             "    'k22' LeafNode\n"
                             "      ('k22',) 'bar'\n"
                             "    'k23' LeafNode\n"
                             "      ('k23',) 'quux'\n"
                             , chkmap._dump_tree())
        chkmap = CHKMap(chkmap._store, chkmap._root_node)
        chkmap._ensure_root()
        node = chkmap._root_node
        # unmapping k23 should give us a root, with k1 and k22 as direct
        # children.
        result = node.unmap(chkmap._store, ('k23',))
        # check the pointed-at object within node - k2 should now point at the
        # k22 leaf (which has been paged in to see if we can collapse the tree)
        child = node._items['k2']
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({('k22',): 'bar'},
            self.to_dict(child, None))
        # Check overall structure is instact:
        self.assertEqual(2, len(chkmap))
        self.assertEqual({('k1',): 'foo', ('k22',): 'bar'},
            self.to_dict(chkmap))
        # serialising should only serialise the new data - the root node.
        keys = list(node.serialise(chkmap._store))
        self.assertEqual([keys[-1]], keys)
        chkmap = CHKMap(chkmap._store, keys[-1])
        self.assertEqualDiff("'' InternalNode\n"
                             "  'k1' LeafNode\n"
                             "      ('k1',) 'foo'\n"
                             "  'k2' LeafNode\n"
                             "      ('k22',) 'bar'\n"
                             , chkmap._dump_tree())

    def test_unmap_k1_from_k1_k22_k23_gives_k22_k23_tree_new(self):
        chkmap = self._get_map(
            {('k1',):'foo', ('k22',):'bar', ('k23',): 'quux'}, maximum_size=10)
        self.assertEqualDiff("'' InternalNode\n"
                             "  'k1' LeafNode\n"
                             "      ('k1',) 'foo'\n"
                             "  'k2' InternalNode\n"
                             "    'k22' LeafNode\n"
                             "      ('k22',) 'bar'\n"
                             "    'k23' LeafNode\n"
                             "      ('k23',) 'quux'\n"
                             , chkmap._dump_tree())
        orig_root = chkmap._root_node
        chkmap = CHKMap(chkmap._store, orig_root)
        chkmap._ensure_root()
        node = chkmap._root_node
        k2_ptr = node._items['k2']
        # unmapping k1 should give us a root, with k22 and k23 as direct
        # children, and should not have needed to page in the subtree.
        result = node.unmap(chkmap._store, ('k1',))
        self.assertEqual(k2_ptr, result)
        chkmap = CHKMap(chkmap._store, orig_root)
        # Unmapping at the CHKMap level should switch to the new root
        chkmap.unmap(('k1',))
        self.assertEqual(k2_ptr, chkmap._root_node)
        self.assertEqualDiff("'' InternalNode\n"
                             "  'k22' LeafNode\n"
                             "      ('k22',) 'bar'\n"
                             "  'k23' LeafNode\n"
                             "      ('k23',) 'quux'\n"
                             , chkmap._dump_tree())


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


class TestIterInterestingNodes(TestCaseWithStore):

    def get_chk_bytes(self):
        if getattr(self, '_chk_bytes', None) is None:
            self._chk_bytes = super(TestIterInterestingNodes,
                                    self).get_chk_bytes()
        return self._chk_bytes

    def get_map_key(self, a_dict):
        c_map = self._get_map(a_dict, maximum_size=10,
                              chk_bytes=self.get_chk_bytes())
        return c_map.key()

    def assertIterInteresting(self, expected, interesting_keys,
                              uninteresting_keys):
        """Check the result of iter_interesting_nodes.

        :param expected: A list of (record_keys, interesting_chk_pages,
                                    interesting key value pairs)
        """
        store = self.get_chk_bytes()
        iter_nodes = chk_map.iter_interesting_nodes(store, interesting_keys,
                                                    uninteresting_keys)
        for count, (exp, act) in enumerate(izip(expected, iter_nodes)):
            exp_record_keys, exp_items = exp
            records, items = act
            exp_tuple = (sorted(exp_record_keys), sorted(exp_items))
            act_tuple = (sorted(records.keys()), sorted(items))
            self.assertEqual(exp_tuple, act_tuple)
        self.assertEqual(len(expected), count + 1)

    def test_empty_to_one_keys(self):
        target = self.get_map_key({('a',): 'content'})
        self.assertIterInteresting(
            [([target], [(('a',), 'content')])],
            [target], [])

    def test_none_to_one_key(self):
        basis = self.get_map_key({})
        target = self.get_map_key({('a',): 'content'})
        self.assertIterInteresting(
            [([target], [(('a',), 'content')])],
            [target], [basis])

    def test_one_to_none_key(self):
        basis = self.get_map_key({('a',): 'content'})
        target = self.get_map_key({})
        self.assertIterInteresting(
            [([target], [])],
            [target], [basis])

    def test_common_pages(self):
        basis = self.get_map_key({('a',): 'content',
                                  ('b',): 'content',
                                  ('c',): 'content',
                                 })
        target = self.get_map_key({('a',): 'content',
                                   ('b',): 'other content',
                                   ('c',): 'content',
                                  })
        target_map = CHKMap(self.get_chk_bytes(), target)
        self.assertEqualDiff(
            "'' InternalNode\n"
            "  'a' LeafNode\n"
            "      ('a',) 'content'\n"
            "  'b' LeafNode\n"
            "      ('b',) 'other content'\n"
            "  'c' LeafNode\n"
            "      ('c',) 'content'\n",
            target_map._dump_tree())
        b_key = target_map._root_node._items['b'].key()
        # This should return the root node, and the node for the 'b' key
        self.assertIterInteresting(
            [([target], []),
             ([b_key], [(('b',), 'other content')])],
            [target], [basis])

    def test_common_sub_page(self):
        basis = self.get_map_key({('aaa',): 'common',
                                  ('c',): 'common',
                                 })
        target = self.get_map_key({('aaa',): 'common',
                                   ('aab',): 'new',
                                   ('c',): 'common',
                                  })
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
            target_map._dump_tree())
        # The key for the internal aa node
        a_key = target_map._root_node._items['a'].key()
        # The key for the leaf aab node
        aab_key = target_map._root_node._items['a']._items['aab'].key()
        self.assertIterInteresting(
            [([target], []),
             ([a_key], []),
             ([aab_key], [(('aab',), 'new')])],
            [target], [basis])

    def test_multiple_maps(self):
        basis1 = self.get_map_key({('aaa',): 'common',
                                   ('aab',): 'basis1',
                                  })
        basis2 = self.get_map_key({('bbb',): 'common',
                                   ('bbc',): 'basis2',
                                  })
        target1 = self.get_map_key({('aaa',): 'common',
                                    ('aac',): 'target1',
                                    ('bbb',): 'common',
                                   })
        target2 = self.get_map_key({('aaa',): 'common',
                                    ('bba',): 'target2',
                                    ('bbb',): 'common',
                                   })
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
            target1_map._dump_tree())
        # The key for the target1 internal a node
        a_key = target1_map._root_node._items['a'].key()
        # The key for the leaf aac node
        aac_key = target1_map._root_node._items['a']._items['aac'].key()

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
            target2_map._dump_tree())
        # The key for the target2 internal bb node
        b_key = target2_map._root_node._items['b'].key()
        # The key for the leaf bba node
        bba_key = target2_map._root_node._items['b']._items['bba'].key()
        self.assertIterInteresting(
            [([target1, target2], []),
             ([a_key], []),
             ([b_key], []),
             ([aac_key], [(('aac',), 'target1')]),
             ([bba_key], [(('bba',), 'target2')]),
            ], [target1, target2], [basis1, basis2])

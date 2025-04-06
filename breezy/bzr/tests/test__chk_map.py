# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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

"""Tests for _chk_map_*."""

from ... import tests
from .. import chk_map


def load_tests(loader, standard_tests, pattern):
    suite, _ = tests.permute_tests_for_extension(
        standard_tests, loader, "breezy.bzr._chk_map_py", "breezy.bzr._chk_map_pyx"
    )
    return suite


class TestDeserialiseLeafNode(tests.TestCase):
    module = None

    def assertDeserialiseErrors(self, text):
        self.assertRaises(
            (ValueError, IndexError),
            self.module._deserialise_leaf_node,
            text,
            b"not-a-real-sha",
        )

    def test_raises_on_non_leaf(self):
        self.assertDeserialiseErrors(b"")
        self.assertDeserialiseErrors(b"short\n")
        self.assertDeserialiseErrors(b"chknotleaf:\n")
        self.assertDeserialiseErrors(b"chkleaf:x\n")
        self.assertDeserialiseErrors(b"chkleaf:\n")
        self.assertDeserialiseErrors(b"chkleaf:\nnotint\n")
        self.assertDeserialiseErrors(b"chkleaf:\n10\n")
        self.assertDeserialiseErrors(b"chkleaf:\n10\n256\n")
        self.assertDeserialiseErrors(b"chkleaf:\n10\n256\n10\n")

    def test_deserialise_empty(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n10\n1\n0\n\n",
            (b"sha1:1234",),
        )
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertIsInstance(node.key(), tuple)
        self.assertIs(None, node._search_prefix)
        self.assertIs(None, node._common_serialised_prefix)

    def test_deserialise_items(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo bar",), b"baz"), ((b"quux",), b"blarh")],
            sorted(node.iteritems(None)),
        )

    def test_deserialise_item_with_null_width_1(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo\x001\nbar\x00baz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo",), b"bar\x00baz"), ((b"quux",), b"blarh")],
            sorted(node.iteritems(None)),
        )

    def test_deserialise_item_with_null_width_2(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n2\n2\n\nfoo\x001\x001\nbar\x00baz\nquux\x00\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"foo", b"1"), b"bar\x00baz"), ((b"quux", b""), b"blarh")],
            sorted(node.iteritems(None)),
        )

    def test_iteritems_selected_one_of_two_items(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        self.assertEqual(2, len(node))
        self.assertEqual(
            [((b"quux",), b"blarh")],
            sorted(node.iteritems(None, [(b"quux",), (b"qaz",)])),
        )

    def test_deserialise_item_with_common_prefix(self):
        node = self.module._deserialise_leaf_node(
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
        node = self.module._deserialise_leaf_node(
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

    def test_key_after_map(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n10\n1\n0\n\n", (b"sha1:1234",)
        )
        node.map(None, (b"foo bar",), b"baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",),
        )
        node.unmap(None, (b"foo bar",))
        self.assertEqual(None, node.key())


class TestDeserialiseInternalNode(tests.TestCase):
    module = None

    def assertDeserialiseErrors(self, text):
        self.assertRaises(
            (ValueError, IndexError),
            self.module._deserialise_internal_node,
            text,
            (b"not-a-real-sha",),
        )

    def test_raises_on_non_internal(self):
        self.assertDeserialiseErrors(b"")
        self.assertDeserialiseErrors(b"short\n")
        self.assertDeserialiseErrors(b"chknotnode:\n")
        self.assertDeserialiseErrors(b"chknode:x\n")
        self.assertDeserialiseErrors(b"chknode:\n")
        self.assertDeserialiseErrors(b"chknode:\nnotint\n")
        self.assertDeserialiseErrors(b"chknode:\n10\n")
        self.assertDeserialiseErrors(b"chknode:\n10\n256\n")
        self.assertDeserialiseErrors(b"chknode:\n10\n256\n10\n")
        # no trailing newline
        self.assertDeserialiseErrors(b"chknode:\n10\n256\n0\n1\nfo")

    def test_deserialise_one(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\n\na\x00sha1:abcd\n",
            (b"sha1:1234",),
        )
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b"", node._search_prefix)
        self.assertEqual({b"a": (b"sha1:abcd",)}, node._items)

    def test_deserialise_with_prefix(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\na\x00sha1:abcd\n",
            (b"sha1:1234",),
        )
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b"pref", node._search_prefix)
        self.assertEqual({b"prefa": (b"sha1:abcd",)}, node._items)

        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\n\x00sha1:abcd\n",
            (b"sha1:1234",),
        )
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b"pref", node._search_prefix)
        self.assertEqual({b"pref": (b"sha1:abcd",)}, node._items)

    def test_deserialise_pref_with_null(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\x00fo\n\x00sha1:abcd\n",
            (b"sha1:1234",),
        )
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b"pref\x00fo", node._search_prefix)
        self.assertEqual({b"pref\x00fo": (b"sha1:abcd",)}, node._items)

    def test_deserialise_with_null_pref(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\x00fo\n\x00\x00sha1:abcd\n",
            (b"sha1:1234",),
        )
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b"pref\x00fo", node._search_prefix)
        self.assertEqual({b"pref\x00fo\x00": (b"sha1:abcd",)}, node._items)

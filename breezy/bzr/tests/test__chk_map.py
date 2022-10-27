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

from ... import (
    tests,
    )
from .. import (
    chk_map,
    )
from ..static_tuple import StaticTuple
stuple = StaticTuple


def load_tests(loader, standard_tests, pattern):
    suite, _ = tests.permute_tests_for_extension(standard_tests, loader,
                                                 'breezy.bzr._chk_map_py', 'breezy.bzr._chk_map_pyx')
    return suite


class TestSearchKeys(tests.TestCase):

    module = None  # Filled in by test parameterization

    def assertSearchKey16(self, expected, key):
        self.assertEqual(expected, self.module._search_key_16(key))

    def assertSearchKey255(self, expected, key):
        actual = self.module._search_key_255(key)
        self.assertEqual(expected, actual, 'actual: %r' % (actual,))

    def test_simple_16(self):
        self.assertSearchKey16(b'8C736521', stuple(b'foo',))
        self.assertSearchKey16(b'8C736521\x008C736521', stuple(b'foo', b'foo'))
        self.assertSearchKey16(b'8C736521\x0076FF8CAA', stuple(b'foo', b'bar'))
        self.assertSearchKey16(b'ED82CD11', stuple(b'abcd',))

    def test_simple_255(self):
        self.assertSearchKey255(b'\x8cse!', stuple(b'foo',))
        self.assertSearchKey255(b'\x8cse!\x00\x8cse!', stuple(b'foo', b'foo'))
        self.assertSearchKey255(
            b'\x8cse!\x00v\xff\x8c\xaa', stuple(b'foo', b'bar'))
        # The standard mapping for these would include '\n', so it should be
        # mapped to '_'
        self.assertSearchKey255(b'\xfdm\x93_\x00P_\x1bL', stuple(b'<', b'V'))

    def test_255_does_not_include_newline(self):
        # When mapping via _search_key_255, we should never have the '\n'
        # character, but all other 255 values should be present
        chars_used = set()
        for char_in in range(256):
            search_key = self.module._search_key_255(
                stuple(bytes([char_in]),))
            chars_used.update([bytes([x]) for x in search_key])
        all_chars = {bytes([x]) for x in range(256)}
        unused_chars = all_chars.symmetric_difference(chars_used)
        self.assertEqual({b'\n'}, unused_chars)


class TestDeserialiseLeafNode(tests.TestCase):

    module = None

    def assertDeserialiseErrors(self, text):
        self.assertRaises((ValueError, IndexError),
                          self.module._deserialise_leaf_node, text, b'not-a-real-sha')

    def test_raises_on_non_leaf(self):
        self.assertDeserialiseErrors(b'')
        self.assertDeserialiseErrors(b'short\n')
        self.assertDeserialiseErrors(b'chknotleaf:\n')
        self.assertDeserialiseErrors(b'chkleaf:x\n')
        self.assertDeserialiseErrors(b'chkleaf:\n')
        self.assertDeserialiseErrors(b'chkleaf:\nnotint\n')
        self.assertDeserialiseErrors(b'chkleaf:\n10\n')
        self.assertDeserialiseErrors(b'chkleaf:\n10\n256\n')
        self.assertDeserialiseErrors(b'chkleaf:\n10\n256\n10\n')

    def test_deserialise_empty(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n10\n1\n0\n\n", stuple(b"sha1:1234",))
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertIsInstance(node.key(), StaticTuple)
        self.assertIs(None, node._search_prefix)
        self.assertIs(None, node._common_serialised_prefix)

    def test_deserialise_items(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([((b"foo bar",), b"baz"), ((b"quux",), b"blarh")],
                         sorted(node.iteritems(None)))

    def test_deserialise_item_with_null_width_1(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo\x001\nbar\x00baz\nquux\x001\nblarh\n",
            (b"sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([((b"foo",), b"bar\x00baz"), ((b"quux",), b"blarh")],
                         sorted(node.iteritems(None)))

    def test_deserialise_item_with_null_width_2(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n2\n2\n\nfoo\x001\x001\nbar\x00baz\n"
            b"quux\x00\x001\nblarh\n",
            (b"sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([((b"foo", b"1"), b"bar\x00baz"), ((b"quux", b""), b"blarh")],
                         sorted(node.iteritems(None)))

    def test_iteritems_selected_one_of_two_items(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([((b"quux",), b"blarh")],
                         sorted(node.iteritems(None, [(b"quux",), (b"qaz",)])))

    def test_deserialise_item_with_common_prefix(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n2\n2\nfoo\x00\n1\x001\nbar\x00baz\n2\x001\nblarh\n",
            (b"sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([((b"foo", b"1"), b"bar\x00baz"), ((b"foo", b"2"), b"blarh")],
                         sorted(node.iteritems(None)))
        self.assertIs(chk_map._unknown, node._search_prefix)
        self.assertEqual(b'foo\x00', node._common_serialised_prefix)

    def test_deserialise_multi_line(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n2\n2\nfoo\x00\n1\x002\nbar\nbaz\n2\x002\nblarh\n\n",
            (b"sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([((b"foo", b"1"), b"bar\nbaz"),
                          ((b"foo", b"2"), b"blarh\n"),
                          ], sorted(node.iteritems(None)))
        self.assertIs(chk_map._unknown, node._search_prefix)
        self.assertEqual(b'foo\x00', node._common_serialised_prefix)

    def test_key_after_map(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n10\n1\n0\n\n", (b"sha1:1234",))
        node.map(None, (b"foo bar",), b"baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = self.module._deserialise_leaf_node(
            b"chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            (b"sha1:1234",))
        node.unmap(None, (b"foo bar",))
        self.assertEqual(None, node.key())


class TestDeserialiseInternalNode(tests.TestCase):

    module = None

    def assertDeserialiseErrors(self, text):
        self.assertRaises((ValueError, IndexError),
                          self.module._deserialise_internal_node, text,
                          stuple(b'not-a-real-sha',))

    def test_raises_on_non_internal(self):
        self.assertDeserialiseErrors(b'')
        self.assertDeserialiseErrors(b'short\n')
        self.assertDeserialiseErrors(b'chknotnode:\n')
        self.assertDeserialiseErrors(b'chknode:x\n')
        self.assertDeserialiseErrors(b'chknode:\n')
        self.assertDeserialiseErrors(b'chknode:\nnotint\n')
        self.assertDeserialiseErrors(b'chknode:\n10\n')
        self.assertDeserialiseErrors(b'chknode:\n10\n256\n')
        self.assertDeserialiseErrors(b'chknode:\n10\n256\n10\n')
        # no trailing newline
        self.assertDeserialiseErrors(b'chknode:\n10\n256\n0\n1\nfo')

    def test_deserialise_one(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\n\na\x00sha1:abcd\n", stuple(b'sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b'', node._search_prefix)
        self.assertEqual({b'a': (b'sha1:abcd',)}, node._items)

    def test_deserialise_with_prefix(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\na\x00sha1:abcd\n",
            stuple(b'sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b'pref', node._search_prefix)
        self.assertEqual({b'prefa': (b'sha1:abcd',)}, node._items)

        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\n\x00sha1:abcd\n",
            stuple(b'sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b'pref', node._search_prefix)
        self.assertEqual({b'pref': (b'sha1:abcd',)}, node._items)

    def test_deserialise_pref_with_null(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\x00fo\n\x00sha1:abcd\n",
            stuple(b'sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b'pref\x00fo', node._search_prefix)
        self.assertEqual({b'pref\x00fo': (b'sha1:abcd',)}, node._items)

    def test_deserialise_with_null_pref(self):
        node = self.module._deserialise_internal_node(
            b"chknode:\n10\n1\n1\npref\x00fo\n\x00\x00sha1:abcd\n",
            stuple(b'sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual((b"sha1:1234",), node.key())
        self.assertEqual(b'pref\x00fo', node._search_prefix)
        self.assertEqual({b'pref\x00fo\x00': (b'sha1:abcd',)}, node._items)


class Test_BytesToTextKey(tests.TestCase):

    def assertBytesToTextKey(self, key, bytes):
        self.assertEqual(key,
                         self.module._bytes_to_text_key(bytes))

    def assertBytesToTextKeyRaises(self, bytes):
        # These are invalid bytes, and we want to make sure the code under test
        # raises an exception rather than segfaults, etc. We don't particularly
        # care what exception.
        self.assertRaises(Exception, self.module._bytes_to_text_key, bytes)

    def test_file(self):
        self.assertBytesToTextKey((b'file-id', b'revision-id'),
                                  b'file: file-id\nparent-id\nname\nrevision-id\n'
                                  b'da39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN')

    def test_invalid_no_kind(self):
        self.assertBytesToTextKeyRaises(
            b'file  file-id\nparent-id\nname\nrevision-id\n'
            b'da39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN')

    def test_invalid_no_space(self):
        self.assertBytesToTextKeyRaises(
            b'file:file-id\nparent-id\nname\nrevision-id\n'
            b'da39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN')

    def test_invalid_too_short_file_id(self):
        self.assertBytesToTextKeyRaises(b'file:file-id')

    def test_invalid_too_short_parent_id(self):
        self.assertBytesToTextKeyRaises(b'file:file-id\nparent-id')

    def test_invalid_too_short_name(self):
        self.assertBytesToTextKeyRaises(b'file:file-id\nparent-id\nname')

    def test_dir(self):
        self.assertBytesToTextKey((b'dir-id', b'revision-id'),
                                  b'dir: dir-id\nparent-id\nname\nrevision-id')

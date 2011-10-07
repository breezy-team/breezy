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

from bzrlib import (
    chk_map,
    tests,
    )
from bzrlib.static_tuple import StaticTuple
stuple = StaticTuple


def load_tests(standard_tests, module, loader):
    suite, _ = tests.permute_tests_for_extension(standard_tests, loader,
        'bzrlib._chk_map_py', 'bzrlib._chk_map_pyx')
    return suite


class TestSearchKeys(tests.TestCase):

    module = None # Filled in by test parameterization

    def assertSearchKey16(self, expected, key):
        self.assertEqual(expected, self.module._search_key_16(key))

    def assertSearchKey255(self, expected, key):
        actual = self.module._search_key_255(key)
        self.assertEqual(expected, actual, 'actual: %r' % (actual,))

    def test_simple_16(self):
        self.assertSearchKey16('8C736521', stuple('foo',))
        self.assertSearchKey16('8C736521\x008C736521', stuple('foo', 'foo'))
        self.assertSearchKey16('8C736521\x0076FF8CAA', stuple('foo', 'bar'))
        self.assertSearchKey16('ED82CD11', stuple('abcd',))

    def test_simple_255(self):
        self.assertSearchKey255('\x8cse!', stuple('foo',))
        self.assertSearchKey255('\x8cse!\x00\x8cse!', stuple('foo', 'foo'))
        self.assertSearchKey255('\x8cse!\x00v\xff\x8c\xaa', stuple('foo', 'bar'))
        # The standard mapping for these would include '\n', so it should be
        # mapped to '_'
        self.assertSearchKey255('\xfdm\x93_\x00P_\x1bL', stuple('<', 'V'))

    def test_255_does_not_include_newline(self):
        # When mapping via _search_key_255, we should never have the '\n'
        # character, but all other 255 values should be present
        chars_used = set()
        for char_in in range(256):
            search_key = self.module._search_key_255(stuple(chr(char_in),))
            chars_used.update(search_key)
        all_chars = set([chr(x) for x in range(256)])
        unused_chars = all_chars.symmetric_difference(chars_used)
        self.assertEqual(set('\n'), unused_chars)


class TestDeserialiseLeafNode(tests.TestCase):

    module = None

    def assertDeserialiseErrors(self, text):
        self.assertRaises((ValueError, IndexError),
            self.module._deserialise_leaf_node, text, 'not-a-real-sha')

    def test_raises_on_non_leaf(self):
        self.assertDeserialiseErrors('')
        self.assertDeserialiseErrors('short\n')
        self.assertDeserialiseErrors('chknotleaf:\n')
        self.assertDeserialiseErrors('chkleaf:x\n')
        self.assertDeserialiseErrors('chkleaf:\n')
        self.assertDeserialiseErrors('chkleaf:\nnotint\n')
        self.assertDeserialiseErrors('chkleaf:\n10\n')
        self.assertDeserialiseErrors('chkleaf:\n10\n256\n')
        self.assertDeserialiseErrors('chkleaf:\n10\n256\n10\n')

    def test_deserialise_empty(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n10\n1\n0\n\n", stuple("sha1:1234",))
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertIsInstance(node.key(), StaticTuple)
        self.assertIs(None, node._search_prefix)
        self.assertIs(None, node._common_serialised_prefix)

    def test_deserialise_items(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo bar",), "baz"), (("quux",), "blarh")],
            sorted(node.iteritems(None)))

    def test_deserialise_item_with_null_width_1(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n1\n2\n\nfoo\x001\nbar\x00baz\nquux\x001\nblarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo",), "bar\x00baz"), (("quux",), "blarh")],
            sorted(node.iteritems(None)))

    def test_deserialise_item_with_null_width_2(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n2\n2\n\nfoo\x001\x001\nbar\x00baz\n"
            "quux\x00\x001\nblarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo", "1"), "bar\x00baz"), (("quux", ""), "blarh")],
            sorted(node.iteritems(None)))

    def test_iteritems_selected_one_of_two_items(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("quux",), "blarh")],
            sorted(node.iteritems(None, [("quux",), ("qaz",)])))

    def test_deserialise_item_with_common_prefix(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n2\n2\nfoo\x00\n1\x001\nbar\x00baz\n2\x001\nblarh\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo", "1"), "bar\x00baz"), (("foo", "2"), "blarh")],
            sorted(node.iteritems(None)))
        self.assertIs(chk_map._unknown, node._search_prefix)
        self.assertEqual('foo\x00', node._common_serialised_prefix)

    def test_deserialise_multi_line(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n2\n2\nfoo\x00\n1\x002\nbar\nbaz\n2\x002\nblarh\n\n",
            ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo", "1"), "bar\nbaz"),
                          (("foo", "2"), "blarh\n"),
                         ], sorted(node.iteritems(None)))
        self.assertIs(chk_map._unknown, node._search_prefix)
        self.assertEqual('foo\x00', node._common_serialised_prefix)

    def test_key_after_map(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n10\n1\n0\n\n", ("sha1:1234",))
        node.map(None, ("foo bar",), "baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = self.module._deserialise_leaf_node(
            "chkleaf:\n0\n1\n2\n\nfoo bar\x001\nbaz\nquux\x001\nblarh\n",
            ("sha1:1234",))
        node.unmap(None, ("foo bar",))
        self.assertEqual(None, node.key())


class TestDeserialiseInternalNode(tests.TestCase):

    module = None

    def assertDeserialiseErrors(self, text):
        self.assertRaises((ValueError, IndexError),
            self.module._deserialise_internal_node, text,
                stuple('not-a-real-sha',))

    def test_raises_on_non_internal(self):
        self.assertDeserialiseErrors('')
        self.assertDeserialiseErrors('short\n')
        self.assertDeserialiseErrors('chknotnode:\n')
        self.assertDeserialiseErrors('chknode:x\n')
        self.assertDeserialiseErrors('chknode:\n')
        self.assertDeserialiseErrors('chknode:\nnotint\n')
        self.assertDeserialiseErrors('chknode:\n10\n')
        self.assertDeserialiseErrors('chknode:\n10\n256\n')
        self.assertDeserialiseErrors('chknode:\n10\n256\n10\n')
        # no trailing newline
        self.assertDeserialiseErrors('chknode:\n10\n256\n0\n1\nfo')

    def test_deserialise_one(self):
        node = self.module._deserialise_internal_node(
            "chknode:\n10\n1\n1\n\na\x00sha1:abcd\n", stuple('sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertEqual('', node._search_prefix)
        self.assertEqual({'a': ('sha1:abcd',)}, node._items)

    def test_deserialise_with_prefix(self):
        node = self.module._deserialise_internal_node(
            "chknode:\n10\n1\n1\npref\na\x00sha1:abcd\n", stuple('sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertEqual('pref', node._search_prefix)
        self.assertEqual({'prefa': ('sha1:abcd',)}, node._items)

        node = self.module._deserialise_internal_node(
            "chknode:\n10\n1\n1\npref\n\x00sha1:abcd\n", stuple('sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertEqual('pref', node._search_prefix)
        self.assertEqual({'pref': ('sha1:abcd',)}, node._items)

    def test_deserialise_pref_with_null(self):
        node = self.module._deserialise_internal_node(
            "chknode:\n10\n1\n1\npref\x00fo\n\x00sha1:abcd\n",
            stuple('sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertEqual('pref\x00fo', node._search_prefix)
        self.assertEqual({'pref\x00fo': ('sha1:abcd',)}, node._items)

    def test_deserialise_with_null_pref(self):
        node = self.module._deserialise_internal_node(
            "chknode:\n10\n1\n1\npref\x00fo\n\x00\x00sha1:abcd\n",
            stuple('sha1:1234',))
        self.assertIsInstance(node, chk_map.InternalNode)
        self.assertEqual(1, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())
        self.assertEqual('pref\x00fo', node._search_prefix)
        self.assertEqual({'pref\x00fo\x00': ('sha1:abcd',)}, node._items)


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
        self.assertBytesToTextKey(('file-id', 'revision-id'),
                 'file: file-id\nparent-id\nname\nrevision-id\n'
                 'da39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN')

    def test_invalid_no_kind(self):
        self.assertBytesToTextKeyRaises(
                 'file  file-id\nparent-id\nname\nrevision-id\n'
                 'da39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN')

    def test_invalid_no_space(self):
        self.assertBytesToTextKeyRaises(
                 'file:file-id\nparent-id\nname\nrevision-id\n'
                 'da39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN')

    def test_invalid_too_short_file_id(self):
        self.assertBytesToTextKeyRaises('file:file-id')

    def test_invalid_too_short_parent_id(self):
        self.assertBytesToTextKeyRaises('file:file-id\nparent-id')

    def test_invalid_too_short_name(self):
        self.assertBytesToTextKeyRaises('file:file-id\nparent-id\nname')

    def test_dir(self):
        self.assertBytesToTextKey(('dir-id', 'revision-id'),
                 'dir: dir-id\nparent-id\nname\nrevision-id')

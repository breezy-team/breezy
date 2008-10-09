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

from bzrlib.chk_map import CHKMap, RootNode, ValueNode
from bzrlib.tests import TestCaseWithTransport


class TestDumbMap(TestCaseWithTransport):

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

    def assertHasABMap(self, chk_bytes):
        root_key = ('sha1:5c464bbd8fecba1aa2574c6d2eb26813d622ce17',)
        self.assertEqual(
            "chkroot:\na\x00sha1:cb29f32e561a1b7f862c38ccfd6bc7c7d892f04b\n",
            self.read_bytes(chk_bytes, root_key))
        self.assertEqual(
            "chkvalue:\nb",
            self.read_bytes(chk_bytes,
                ("sha1:cb29f32e561a1b7f862c38ccfd6bc7c7d892f04b",)))

    def assertHasEmptyMap(self, chk_bytes):
        root_key = ('sha1:572d8da882e1ebf0f50f1e2da2d7a9cadadf4db5',)
        self.assertEqual("chkroot:\n", self.read_bytes(chk_bytes, root_key))

    def test_from_dict_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        self.assertEqual(('sha1:572d8da882e1ebf0f50f1e2da2d7a9cadadf4db5',),
            root_key)
        self.assertHasEmptyMap(chk_bytes)

    def test_from_dict_ab(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {"a":"b"})
        self.assertEqual(('sha1:5c464bbd8fecba1aa2574c6d2eb26813d622ce17',),
            root_key)
        self.assertHasABMap(chk_bytes)

    def test_apply_empty_ab(self):
        # applying a delta (None, "a", "b") to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([(None, "a", "b")])
        self.assertEqual(('sha1:5c464bbd8fecba1aa2574c6d2eb26813d622ce17',),
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
        self.assertEqual(('sha1:572d8da882e1ebf0f50f1e2da2d7a9cadadf4db5',),
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
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes,
            {"a":"content here", "b":"more content"})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual([("a", "content here")],
            sorted(list(chkmap.iteritems(["a"]))))


class TestRootNode(TestCaseWithTransport):

    def test_serialise_empty(self):
        node = RootNode()
        bytes = node.serialise()
        self.assertEqual("chkroot:\n", bytes)

    def test_add_child_resets_key(self):
        node = RootNode()
        node._key = ("something",)
        node.add_child("c", ("sha1:1234",))
        self.assertEqual(None, node._key)

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
        node.deserialise("chkroot:\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual({"c": ("sha1:1234",)}, node._nodes)
        self.assertEqual(("foo",), node._key)

    def test_serialise_with_child(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        bytes = node.serialise()
        self.assertEqual("chkroot:\nc\x00sha1:1234\n", bytes)


class TestValueNode(TestCaseWithTransport):

    def test_deserialise(self):
        node = ValueNode.deserialise("chkvalue:\nfoo bar baz\n")
        self.assertEqual("foo bar baz\n", node.value)

    def test_serialise(self):
        node = ValueNode("b")
        bytes = node.serialise()
        self.assertEqual("chkvalue:\nb", bytes)

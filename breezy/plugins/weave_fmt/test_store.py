# Copyright (C) 2005-2011, 2016 Canonical Ltd
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

"""Test Store implementations."""

import gzip
import os
from io import BytesIO

from ... import errors as errors
from ... import transactions, transport
from ...bzr.weave import WeaveFile
from ...errors import BzrError
from ...tests import TestCase, TestCaseInTempDir, TestCaseWithTransport
from ...transport.memory import MemoryTransport
from .store import TransportStore
from .store.text import TextStore
from .store.versioned import VersionedFileStore


class TestStores:
    """Mixin template class that provides some common tests for stores."""

    def check_content(self, store, fileid, value):
        with store.get(fileid) as f:
            self.assertEqual(f.read(), value)

    def fill_store(self, store):
        store.add(BytesIO(b"hello"), b"a")
        store.add(BytesIO(b"other"), b"b")
        store.add(BytesIO(b"something"), b"c")
        store.add(BytesIO(b"goodbye"), b"123123")

    def test_get(self):
        store = self.get_store()
        self.fill_store(store)

        self.check_content(store, b"a", b"hello")
        self.check_content(store, b"b", b"other")
        self.check_content(store, b"c", b"something")

        # Make sure that requesting a non-existing file fails
        self.assertRaises(KeyError, self.check_content, store, b"d", None)

    def test_multiple_add(self):
        """Multiple add with same ID should raise a BzrError."""
        store = self.get_store()
        self.fill_store(store)
        self.assertRaises(BzrError, store.add, BytesIO(b"goodbye"), b"123123")


class TestCompressedTextStore(TestCaseInTempDir, TestStores):
    def get_store(self, path="."):
        t = transport.get_transport_from_path(path)
        return TextStore(t, compressed=True)

    def test_total_size(self):
        store = self.get_store(".")
        store.register_suffix("dsc")
        store.add(BytesIO(b"goodbye"), b"123123")
        store.add(BytesIO(b"goodbye2"), b"123123", "dsc")
        # these get gzipped - content should be stable
        self.assertEqual(store.total_size(), (2, 55))

    def test__relpath_suffixed(self):
        my_store = TextStore(MockTransport(), prefixed=True, compressed=True)
        my_store.register_suffix("dsc")
        self.assertEqual("45/foo.dsc", my_store._relpath(b"foo", ["dsc"]))


class TestMemoryStore(TestCase):
    def get_store(self):
        return TextStore(MemoryTransport())

    def test_add_and_retrieve(self):
        store = self.get_store()
        store.add(BytesIO(b"hello"), b"aa")
        self.assertNotEqual(store.get(b"aa"), None)
        self.assertEqual(store.get(b"aa").read(), b"hello")
        store.add(BytesIO(b"hello world"), b"bb")
        self.assertNotEqual(store.get(b"bb"), None)
        self.assertEqual(store.get(b"bb").read(), b"hello world")

    def test_missing_is_absent(self):
        store = self.get_store()
        self.assertNotIn(b"aa", store)

    def test_adding_fails_when_present(self):
        my_store = self.get_store()
        my_store.add(BytesIO(b"hello"), b"aa")
        self.assertRaises(BzrError, my_store.add, BytesIO(b"hello"), b"aa")

    def test_total_size(self):
        store = self.get_store()
        store.add(BytesIO(b"goodbye"), b"123123")
        store.add(BytesIO(b"goodbye2"), b"123123.dsc")
        self.assertEqual(store.total_size(), (2, 15))
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class TestTextStore(TestCaseInTempDir, TestStores):
    def get_store(self, path="."):
        t = transport.get_transport_from_path(path)
        return TextStore(t, compressed=False)

    def test_total_size(self):
        store = self.get_store()
        store.add(BytesIO(b"goodbye"), b"123123")
        store.add(BytesIO(b"goodbye2"), b"123123.dsc")
        self.assertEqual(store.total_size(), (2, 15))
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class TestMixedTextStore(TestCaseInTempDir, TestStores):
    def get_store(self, path=".", compressed=True):
        t = transport.get_transport_from_path(path)
        return TextStore(t, compressed=compressed)

    def test_get_mixed(self):
        cs = self.get_store(".", compressed=True)
        s = self.get_store(".", compressed=False)
        cs.add(BytesIO(b"hello there"), b"a")

        self.assertPathExists("a.gz")
        self.assertFalse(os.path.lexists("a"))

        with gzip.GzipFile("a.gz") as f:
            self.assertEqual(f.read(), b"hello there")

        self.assertEqual(cs.has_id(b"a"), True)
        self.assertEqual(s.has_id(b"a"), True)
        self.assertEqual(cs.get(b"a").read(), b"hello there")
        self.assertEqual(s.get(b"a").read(), b"hello there")

        self.assertRaises(BzrError, s.add, BytesIO(b"goodbye"), b"a")

        s.add(BytesIO(b"goodbye"), b"b")
        self.assertPathExists("b")
        self.assertFalse(os.path.lexists("b.gz"))
        with open("b", "rb") as f:
            self.assertEqual(f.read(), b"goodbye")

        self.assertEqual(cs.has_id(b"b"), True)
        self.assertEqual(s.has_id(b"b"), True)
        self.assertEqual(cs.get(b"b").read(), b"goodbye")
        self.assertEqual(s.get(b"b").read(), b"goodbye")

        self.assertRaises(BzrError, cs.add, BytesIO(b"again"), b"b")


class MockTransport(transport.Transport):
    """A fake transport for testing with."""

    def has(self, filename):
        return False

    def __init__(self, url=None):
        if url is None:
            url = "http://example.com"
        super().__init__(url)

    def mkdir(self, filename):
        return


class InstrumentedTransportStore(TransportStore):
    """An instrumented TransportStore.

    Here we replace template method worker methods with calls that record the
    expected results.
    """

    def _add(self, filename, file):
        self._calls.append(("_add", filename, file))

    def __init__(self, transport, prefixed=False):
        super().__init__(transport, prefixed)
        self._calls = []


class TestInstrumentedTransportStore(TestCase):
    def test__add_records(self):
        my_store = InstrumentedTransportStore(MockTransport())
        my_store._add("filename", "file")
        self.assertEqual([("_add", "filename", "file")], my_store._calls)


class TestMockTransport(TestCase):
    def test_isinstance(self):
        self.assertIsInstance(MockTransport(), transport.Transport)

    def test_has(self):
        self.assertEqual(False, MockTransport().has("foo"))

    def test_mkdir(self):
        MockTransport().mkdir("45")


class TestTransportStore(TestCase):
    def test__relpath_invalid(self):
        my_store = TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, b"/foo")
        self.assertRaises(ValueError, my_store._relpath, b"foo/")

    def test_register_invalid_suffixes(self):
        my_store = TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store.register_suffix, "/")
        self.assertRaises(ValueError, my_store.register_suffix, ".gz/bar")

    def test__relpath_unregister_suffixes(self):
        my_store = TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, b"foo", [b"gz"])
        self.assertRaises(ValueError, my_store._relpath, b"foo", [b"dsc", b"gz"])

    def test__relpath_simple(self):
        my_store = TransportStore(MockTransport())
        self.assertEqual("foo", my_store._relpath(b"foo"))

    def test__relpath_prefixed(self):
        my_store = TransportStore(MockTransport(), True)
        self.assertEqual("45/foo", my_store._relpath(b"foo"))

    def test__relpath_simple_suffixed(self):
        my_store = TransportStore(MockTransport())
        my_store.register_suffix("bar")
        my_store.register_suffix("baz")
        self.assertEqual("foo.baz", my_store._relpath(b"foo", ["baz"]))
        self.assertEqual("foo.bar.baz", my_store._relpath(b"foo", ["bar", "baz"]))

    def test__relpath_prefixed_suffixed(self):
        my_store = TransportStore(MockTransport(), True)
        my_store.register_suffix("bar")
        my_store.register_suffix("baz")
        self.assertEqual("45/foo.baz", my_store._relpath(b"foo", ["baz"]))
        self.assertEqual("45/foo.bar.baz", my_store._relpath(b"foo", ["bar", "baz"]))

    def test_add_simple(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport())
        my_store.add(stream, b"foo")
        self.assertEqual([("_add", "foo", stream)], my_store._calls)

    def test_add_prefixed(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport(), True)
        my_store.add(stream, b"foo")
        self.assertEqual([("_add", "45/foo", stream)], my_store._calls)

    def test_add_simple_suffixed(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport())
        my_store.register_suffix("dsc")
        my_store.add(stream, b"foo", "dsc")
        self.assertEqual([("_add", "foo.dsc", stream)], my_store._calls)

    def test_add_simple_suffixed_dir(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport(), True)
        my_store.register_suffix("dsc")
        my_store.add(stream, b"foo", "dsc")
        self.assertEqual([("_add", "45/foo.dsc", stream)], my_store._calls)

    def get_populated_store(
        self, prefixed=False, store_class=TextStore, compressed=False
    ):
        my_store = store_class(MemoryTransport(), prefixed, compressed=compressed)
        my_store.register_suffix("sig")
        stream = BytesIO(b"signature")
        my_store.add(stream, b"foo", "sig")
        stream = BytesIO(b"content")
        my_store.add(stream, b"foo")
        stream = BytesIO(b"signature for missing base")
        my_store.add(stream, b"missing", "sig")
        return my_store

    def test_has_simple(self):
        my_store = self.get_populated_store()
        self.assertEqual(True, my_store.has_id(b"foo"))
        my_store = self.get_populated_store(True)
        self.assertEqual(True, my_store.has_id(b"foo"))

    def test_has_suffixed(self):
        my_store = self.get_populated_store()
        self.assertEqual(True, my_store.has_id(b"foo", "sig"))
        my_store = self.get_populated_store(True)
        self.assertEqual(True, my_store.has_id(b"foo", "sig"))

    def test_has_suffixed_no_base(self):
        my_store = self.get_populated_store()
        self.assertEqual(False, my_store.has_id(b"missing"))
        my_store = self.get_populated_store(True)
        self.assertEqual(False, my_store.has_id(b"missing"))

    def test_get_simple(self):
        my_store = self.get_populated_store()
        self.assertEqual(b"content", my_store.get(b"foo").read())
        my_store = self.get_populated_store(True)
        self.assertEqual(b"content", my_store.get(b"foo").read())

    def test_get_suffixed(self):
        my_store = self.get_populated_store()
        self.assertEqual(b"signature", my_store.get(b"foo", "sig").read())
        my_store = self.get_populated_store(True)
        self.assertEqual(b"signature", my_store.get(b"foo", "sig").read())

    def test_get_suffixed_no_base(self):
        my_store = self.get_populated_store()
        self.assertEqual(
            b"signature for missing base", my_store.get(b"missing", "sig").read()
        )
        my_store = self.get_populated_store(True)
        self.assertEqual(
            b"signature for missing base", my_store.get(b"missing", "sig").read()
        )

    def test___iter__no_suffix(self):
        my_store = TextStore(MemoryTransport(), prefixed=False, compressed=False)
        stream = BytesIO(b"content")
        my_store.add(stream, b"foo")
        self.assertEqual({b"foo"}, set(my_store.__iter__()))

    def test___iter__(self):
        self.assertEqual({b"foo"}, set(self.get_populated_store().__iter__()))
        self.assertEqual({b"foo"}, set(self.get_populated_store(True).__iter__()))

    def test___iter__compressed(self):
        self.assertEqual(
            {b"foo"}, set(self.get_populated_store(compressed=True).__iter__())
        )
        self.assertEqual(
            {b"foo"}, set(self.get_populated_store(True, compressed=True).__iter__())
        )

    def test___len__(self):
        self.assertEqual(1, len(self.get_populated_store()))

    def test_relpath_escaped(self):
        my_store = TransportStore(MemoryTransport())
        self.assertEqual("%25", my_store._relpath(b"%"))

    def test_escaped_uppercase(self):
        """Uppercase letters are escaped for safety on Windows."""
        my_store = TransportStore(MemoryTransport(), prefixed=True, escaped=True)
        # a particularly perverse file-id! :-)
        self.assertEqual(my_store._relpath(b"C:<>"), "be/%2543%253a%253c%253e")


class TestVersionFileStore(TestCaseWithTransport):
    def get_scope(self):
        return self._transaction

    def setUp(self):
        super().setUp()
        self.vfstore = VersionedFileStore(
            MemoryTransport(), versionedfile_class=WeaveFile
        )
        self.vfstore.get_scope = self.get_scope
        self._transaction = None

    def test_get_weave_registers_dirty_in_write(self):
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave_or_empty(b"id", self._transaction)
        self._transaction.finish()
        self._transaction = None
        self.assertRaises(errors.OutSideTransaction, vf.add_lines, b"b", [], [])
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave(b"id", self._transaction)
        self._transaction.finish()
        self._transaction = None
        self.assertRaises(errors.OutSideTransaction, vf.add_lines, b"b", [], [])

    def test_get_weave_readonly_cant_write(self):
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave_or_empty(b"id", self._transaction)
        self._transaction.finish()
        self._transaction = transactions.ReadOnlyTransaction()
        vf = self.vfstore.get_weave_or_empty(b"id", self._transaction)
        self.assertRaises(errors.ReadOnlyError, vf.add_lines, b"b", [], [])

    def test___iter__escaped(self):
        self.vfstore = VersionedFileStore(
            MemoryTransport(),
            prefixed=True,
            escaped=True,
            versionedfile_class=WeaveFile,
        )
        self.vfstore.get_scope = self.get_scope
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave_or_empty(b" ", self._transaction)
        vf.add_lines(b"a", [], [])
        del vf
        self._transaction.finish()
        self.assertEqual([b" "], list(self.vfstore))

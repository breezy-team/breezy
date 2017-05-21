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

import os
import gzip

import bzrlib.errors as errors
from bzrlib.errors import BzrError
from bzrlib.sixish import (
    BytesIO,
    )
from bzrlib.store import TransportStore
from bzrlib.store.text import TextStore
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.tests import TestCase, TestCaseInTempDir, TestCaseWithTransport
import bzrlib.transactions as transactions
import bzrlib.transport as transport
from bzrlib.transport.memory import MemoryTransport
from bzrlib.weave import WeaveFile


class TestStores(object):
    """Mixin template class that provides some common tests for stores"""

    def check_content(self, store, fileid, value):
        f = store.get(fileid)
        self.assertEqual(f.read(), value)

    def fill_store(self, store):
        store.add(BytesIO(b'hello'), 'a')
        store.add(BytesIO(b'other'), 'b')
        store.add(BytesIO(b'something'), 'c')
        store.add(BytesIO(b'goodbye'), '123123')

    def test_copy_all(self):
        """Test copying"""
        os.mkdir('a')
        store_a = self.get_store('a')
        store_a.add(BytesIO(b'foo'), '1')
        os.mkdir('b')
        store_b = self.get_store('b')
        store_b.copy_all_ids(store_a)
        self.assertEqual(store_a.get('1').read(), 'foo')
        self.assertEqual(store_b.get('1').read(), 'foo')
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)

    def test_get(self):
        store = self.get_store()
        self.fill_store(store)

        self.check_content(store, 'a', 'hello')
        self.check_content(store, 'b', 'other')
        self.check_content(store, 'c', 'something')

        # Make sure that requesting a non-existing file fails
        self.assertRaises(KeyError, self.check_content, store, 'd', None)

    def test_multiple_add(self):
        """Multiple add with same ID should raise a BzrError"""
        store = self.get_store()
        self.fill_store(store)
        self.assertRaises(BzrError, store.add, BytesIO(b'goodbye'), '123123')


class TestCompressedTextStore(TestCaseInTempDir, TestStores):

    def get_store(self, path=u'.'):
        t = transport.get_transport_from_path(path)
        return TextStore(t, compressed=True)

    def test_total_size(self):
        store = self.get_store(u'.')
        store.register_suffix('dsc')
        store.add(BytesIO(b'goodbye'), '123123')
        store.add(BytesIO(b'goodbye2'), '123123', 'dsc')
        # these get gzipped - content should be stable
        self.assertEqual(store.total_size(), (2, 55))

    def test__relpath_suffixed(self):
        my_store = TextStore(MockTransport(),
                             prefixed=True, compressed=True)
        my_store.register_suffix('dsc')
        self.assertEqual('45/foo.dsc', my_store._relpath('foo', ['dsc']))


class TestMemoryStore(TestCase):

    def get_store(self):
        return TextStore(MemoryTransport())

    def test_add_and_retrieve(self):
        store = self.get_store()
        store.add(BytesIO(b'hello'), 'aa')
        self.assertNotEqual(store.get('aa'), None)
        self.assertEqual(store.get('aa').read(), 'hello')
        store.add(BytesIO(b'hello world'), 'bb')
        self.assertNotEqual(store.get('bb'), None)
        self.assertEqual(store.get('bb').read(), 'hello world')

    def test_missing_is_absent(self):
        store = self.get_store()
        self.assertFalse('aa' in store)

    def test_adding_fails_when_present(self):
        my_store = self.get_store()
        my_store.add(BytesIO(b'hello'), 'aa')
        self.assertRaises(BzrError,
                          my_store.add, BytesIO(b'hello'), 'aa')

    def test_total_size(self):
        store = self.get_store()
        store.add(BytesIO(b'goodbye'), '123123')
        store.add(BytesIO(b'goodbye2'), '123123.dsc')
        self.assertEqual(store.total_size(), (2, 15))
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class TestTextStore(TestCaseInTempDir, TestStores):

    def get_store(self, path=u'.'):
        t = transport.get_transport_from_path(path)
        return TextStore(t, compressed=False)

    def test_total_size(self):
        store = self.get_store()
        store.add(BytesIO(b'goodbye'), '123123')
        store.add(BytesIO(b'goodbye2'), '123123.dsc')
        self.assertEqual(store.total_size(), (2, 15))
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class TestMixedTextStore(TestCaseInTempDir, TestStores):

    def get_store(self, path=u'.', compressed=True):
        t = transport.get_transport_from_path(path)
        return TextStore(t, compressed=compressed)

    def test_get_mixed(self):
        cs = self.get_store(u'.', compressed=True)
        s = self.get_store(u'.', compressed=False)
        cs.add(BytesIO(b'hello there'), 'a')

        self.assertPathExists('a.gz')
        self.assertFalse(os.path.lexists('a'))

        self.assertEqual(gzip.GzipFile('a.gz').read(), 'hello there')

        self.assertEqual(cs.has_id('a'), True)
        self.assertEqual(s.has_id('a'), True)
        self.assertEqual(cs.get('a').read(), 'hello there')
        self.assertEqual(s.get('a').read(), 'hello there')

        self.assertRaises(BzrError, s.add, BytesIO(b'goodbye'), 'a')

        s.add(BytesIO(b'goodbye'), 'b')
        self.assertPathExists('b')
        self.assertFalse(os.path.lexists('b.gz'))
        self.assertEqual(open('b').read(), 'goodbye')

        self.assertEqual(cs.has_id('b'), True)
        self.assertEqual(s.has_id('b'), True)
        self.assertEqual(cs.get('b').read(), 'goodbye')
        self.assertEqual(s.get('b').read(), 'goodbye')

        self.assertRaises(BzrError, cs.add, BytesIO(b'again'), 'b')

class MockTransport(transport.Transport):
    """A fake transport for testing with."""

    def has(self, filename):
        return False

    def __init__(self, url=None):
        if url is None:
            url = "http://example.com"
        super(MockTransport, self).__init__(url)

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
        super(InstrumentedTransportStore, self).__init__(transport, prefixed)
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
        self.assertEqual(False, MockTransport().has('foo'))

    def test_mkdir(self):
        MockTransport().mkdir('45')


class TestTransportStore(TestCase):

    def test__relpath_invalid(self):
        my_store = TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, '/foo')
        self.assertRaises(ValueError, my_store._relpath, 'foo/')

    def test_register_invalid_suffixes(self):
        my_store = TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store.register_suffix, '/')
        self.assertRaises(ValueError, my_store.register_suffix, '.gz/bar')

    def test__relpath_unregister_suffixes(self):
        my_store = TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, 'foo', ['gz'])
        self.assertRaises(ValueError, my_store._relpath, 'foo', ['dsc', 'gz'])

    def test__relpath_simple(self):
        my_store = TransportStore(MockTransport())
        self.assertEqual("foo", my_store._relpath('foo'))

    def test__relpath_prefixed(self):
        my_store = TransportStore(MockTransport(), True)
        self.assertEqual('45/foo', my_store._relpath('foo'))

    def test__relpath_simple_suffixed(self):
        my_store = TransportStore(MockTransport())
        my_store.register_suffix('bar')
        my_store.register_suffix('baz')
        self.assertEqual('foo.baz', my_store._relpath('foo', ['baz']))
        self.assertEqual('foo.bar.baz', my_store._relpath('foo', ['bar', 'baz']))

    def test__relpath_prefixed_suffixed(self):
        my_store = TransportStore(MockTransport(), True)
        my_store.register_suffix('bar')
        my_store.register_suffix('baz')
        self.assertEqual('45/foo.baz', my_store._relpath('foo', ['baz']))
        self.assertEqual('45/foo.bar.baz',
                         my_store._relpath('foo', ['bar', 'baz']))

    def test_add_simple(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport())
        my_store.add(stream, "foo")
        self.assertEqual([("_add", "foo", stream)], my_store._calls)

    def test_add_prefixed(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport(), True)
        my_store.add(stream, "foo")
        self.assertEqual([("_add", "45/foo", stream)], my_store._calls)

    def test_add_simple_suffixed(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport())
        my_store.register_suffix('dsc')
        my_store.add(stream, "foo", 'dsc')
        self.assertEqual([("_add", "foo.dsc", stream)], my_store._calls)

    def test_add_simple_suffixed(self):
        stream = BytesIO(b"content")
        my_store = InstrumentedTransportStore(MockTransport(), True)
        my_store.register_suffix('dsc')
        my_store.add(stream, "foo", 'dsc')
        self.assertEqual([("_add", "45/foo.dsc", stream)], my_store._calls)

    def get_populated_store(self, prefixed=False,
            store_class=TextStore, compressed=False):
        my_store = store_class(MemoryTransport(), prefixed,
                               compressed=compressed)
        my_store.register_suffix('sig')
        stream = BytesIO(b"signature")
        my_store.add(stream, "foo", 'sig')
        stream = BytesIO(b"content")
        my_store.add(stream, "foo")
        stream = BytesIO(b"signature for missing base")
        my_store.add(stream, "missing", 'sig')
        return my_store

    def test_has_simple(self):
        my_store = self.get_populated_store()
        self.assertEqual(True, my_store.has_id('foo'))
        my_store = self.get_populated_store(True)
        self.assertEqual(True, my_store.has_id('foo'))

    def test_has_suffixed(self):
        my_store = self.get_populated_store()
        self.assertEqual(True, my_store.has_id('foo', 'sig'))
        my_store = self.get_populated_store(True)
        self.assertEqual(True, my_store.has_id('foo', 'sig'))

    def test_has_suffixed_no_base(self):
        my_store = self.get_populated_store()
        self.assertEqual(False, my_store.has_id('missing'))
        my_store = self.get_populated_store(True)
        self.assertEqual(False, my_store.has_id('missing'))

    def test_get_simple(self):
        my_store = self.get_populated_store()
        self.assertEqual('content', my_store.get('foo').read())
        my_store = self.get_populated_store(True)
        self.assertEqual('content', my_store.get('foo').read())

    def test_get_suffixed(self):
        my_store = self.get_populated_store()
        self.assertEqual('signature', my_store.get('foo', 'sig').read())
        my_store = self.get_populated_store(True)
        self.assertEqual('signature', my_store.get('foo', 'sig').read())

    def test_get_suffixed_no_base(self):
        my_store = self.get_populated_store()
        self.assertEqual('signature for missing base',
                         my_store.get('missing', 'sig').read())
        my_store = self.get_populated_store(True)
        self.assertEqual('signature for missing base',
                         my_store.get('missing', 'sig').read())

    def test___iter__no_suffix(self):
        my_store = TextStore(MemoryTransport(),
                             prefixed=False, compressed=False)
        stream = BytesIO(b"content")
        my_store.add(stream, "foo")
        self.assertEqual({'foo'},
                         set(my_store.__iter__()))

    def test___iter__(self):
        self.assertEqual({'foo'},
                         set(self.get_populated_store().__iter__()))
        self.assertEqual({'foo'},
                         set(self.get_populated_store(True).__iter__()))

    def test___iter__compressed(self):
        self.assertEqual({'foo'},
                         set(self.get_populated_store(
                             compressed=True).__iter__()))
        self.assertEqual({'foo'},
                         set(self.get_populated_store(
                             True, compressed=True).__iter__()))

    def test___len__(self):
        self.assertEqual(1, len(self.get_populated_store()))

    def test_copy_suffixes(self):
        from_store = self.get_populated_store()
        to_store = TextStore(MemoryTransport(),
                             prefixed=True, compressed=True)
        to_store.register_suffix('sig')
        to_store.copy_all_ids(from_store)
        self.assertEqual(1, len(to_store))
        self.assertEqual({'foo'}, set(to_store.__iter__()))
        self.assertEqual('content', to_store.get('foo').read())
        self.assertEqual('signature', to_store.get('foo', 'sig').read())
        self.assertRaises(KeyError, to_store.get, 'missing', 'sig')

    def test_relpath_escaped(self):
        my_store = TransportStore(MemoryTransport())
        self.assertEqual('%25', my_store._relpath('%'))

    def test_escaped_uppercase(self):
        """Uppercase letters are escaped for safety on Windows"""
        my_store = TransportStore(MemoryTransport(), prefixed=True,
            escaped=True)
        # a particularly perverse file-id! :-)
        self.assertEqual(my_store._relpath('C:<>'), 'be/%2543%253a%253c%253e')


class TestVersionFileStore(TestCaseWithTransport):

    def get_scope(self):
        return self._transaction

    def setUp(self):
        super(TestVersionFileStore, self).setUp()
        self.vfstore = VersionedFileStore(MemoryTransport(),
            versionedfile_class=WeaveFile)
        self.vfstore.get_scope = self.get_scope
        self._transaction = None

    def test_get_weave_registers_dirty_in_write(self):
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave_or_empty('id', self._transaction)
        self._transaction.finish()
        self._transaction = None
        self.assertRaises(errors.OutSideTransaction, vf.add_lines, 'b', [], [])
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave('id', self._transaction)
        self._transaction.finish()
        self._transaction = None
        self.assertRaises(errors.OutSideTransaction, vf.add_lines, 'b', [], [])

    def test_get_weave_readonly_cant_write(self):
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave_or_empty('id', self._transaction)
        self._transaction.finish()
        self._transaction = transactions.ReadOnlyTransaction()
        vf = self.vfstore.get_weave_or_empty('id', self._transaction)
        self.assertRaises(errors.ReadOnlyError, vf.add_lines, 'b', [], [])

    def test___iter__escaped(self):
        self.vfstore = VersionedFileStore(MemoryTransport(),
            prefixed=True, escaped=True, versionedfile_class=WeaveFile)
        self.vfstore.get_scope = self.get_scope
        self._transaction = transactions.WriteTransaction()
        vf = self.vfstore.get_weave_or_empty(' ', self._transaction)
        vf.add_lines('a', [], [])
        del vf
        self._transaction.finish()
        self.assertEqual([' '], list(self.vfstore))

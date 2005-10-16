# Copyright (C) 2005 by Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test Store implementations."""

from cStringIO import StringIO
import os

from bzrlib.errors import BzrError, UnlistableStore
from bzrlib.store import copy_all
from bzrlib.transport.local import LocalTransport
from bzrlib.transport import NoSuchFile
from bzrlib.store.compressed_text import CompressedTextStore
from bzrlib.store.text import TextStore
from bzrlib.selftest import TestCase, TestCaseInTempDir
import bzrlib.store as store
import bzrlib.transport as transport


class TestStores(object):

    def check_content(self, store, fileid, value):
        f = store.get(fileid)
        self.assertEqual(f.read(), value)

    def fill_store(self, store):
        store.add(StringIO('hello'), 'a')
        store.add(StringIO('other'), 'b')
        store.add(StringIO('something'), 'c')
        store.add(StringIO('goodbye'), '123123')

    def test_copy_all(self):
        """Test copying"""
        os.mkdir('a')
        store_a = self.get_store('a')
        store_a.add('foo', '1')
        os.mkdir('b')
        store_b = self.get_store('b')
        copy_all(store_a, store_b)
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
        self.assertRaises(BzrError, store.add, StringIO('goodbye'), '123123')


class TestCompressedTextStore(TestCaseInTempDir, TestStores):

    def get_store(self, path='.'):
        t = LocalTransport(path)
        return CompressedTextStore(t)

    def test_total_size(self):
        store = self.get_store('.')
        store.register_suffix('dsc')
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123', 'dsc')
        # these get gzipped - content should be stable
        self.assertEqual(store.total_size(), (2, 55))
        
    def test__relpath_suffixed(self):
        my_store = CompressedTextStore(MockTransport(), True)
        my_store.register_suffix('dsc')
        self.assertEqual('45/foo.dsc.gz', my_store._relpath('foo', ['dsc']))


class TestMemoryStore(TestCase):
    
    def get_store(self):
        return store.ImmutableMemoryStore()
    
    def test_imports(self):
        from bzrlib.store import ImmutableMemoryStore

    def test_add_and_retrieve(self):
        store = self.get_store()
        store.add(StringIO('hello'), 'aa')
        self.assertNotEqual(store.get('aa'), None)
        self.assertEqual(store.get('aa').read(), 'hello')
        store.add(StringIO('hello world'), 'bb')
        self.assertNotEqual(store.get('bb'), None)
        self.assertEqual(store.get('bb').read(), 'hello world')

    def test_missing_is_absent(self):
        store = self.get_store()
        self.failIf('aa' in store)

    def test_adding_fails_when_present(self):
        my_store = self.get_store()
        my_store.add(StringIO('hello'), 'aa')
        self.assertRaises(BzrError,
                          my_store.add, StringIO('hello'), 'aa')

    def test_total_size(self):
        store = self.get_store()
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123.dsc')
        self.assertEqual(store.total_size(), (2, 15))
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class TestTextStore(TestCaseInTempDir, TestStores):

    def get_store(self, path='.'):
        t = LocalTransport(path)
        return TextStore(t)

    def test_total_size(self):
        store = self.get_store()
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123.dsc')
        self.assertEqual(store.total_size(), (2, 15))
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


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


class InstrumentedTransportStore(store.TransportStore):
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
        self.failUnless(isinstance(MockTransport(), transport.Transport))

    def test_has(self):
        self.assertEqual(False, MockTransport().has('foo'))

    def test_mkdir(self):
        MockTransport().mkdir('45')


class TestTransportStore(TestCase):
    
    def test__relpath_invalid(self):
        my_store = store.TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, '/foo')
        self.assertRaises(ValueError, my_store._relpath, 'foo/')

    def test_register_invalid_suffixes(self):
        my_store = store.TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store.register_suffix, '/')
        self.assertRaises(ValueError, my_store.register_suffix, '.gz/bar')

    def test__relpath_unregister_suffixes(self):
        my_store = store.TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, 'foo', ['gz'])
        self.assertRaises(ValueError, my_store._relpath, 'foo', ['dsc', 'gz'])

    def test__relpath_simple(self):
        my_store = store.TransportStore(MockTransport())
        self.assertEqual("foo", my_store._relpath('foo'))

    def test__relpath_prefixed(self):
        my_store = store.TransportStore(MockTransport(), True)
        self.assertEqual('45/foo', my_store._relpath('foo'))

    def test__relpath_simple_suffixed(self):
        my_store = store.TransportStore(MockTransport())
        my_store.register_suffix('gz')
        my_store.register_suffix('bar')
        self.assertEqual('foo.gz', my_store._relpath('foo', ['gz']))
        self.assertEqual('foo.gz.bar', my_store._relpath('foo', ['gz', 'bar']))

    def test__relpath_prefixed_suffixed(self):
        my_store = store.TransportStore(MockTransport(), True)
        my_store.register_suffix('gz')
        my_store.register_suffix('bar')
        self.assertEqual('45/foo.gz', my_store._relpath('foo', ['gz']))
        self.assertEqual('45/foo.gz.bar',
                         my_store._relpath('foo', ['gz', 'bar']))

    def test_add_simple(self):
        stream = StringIO("content")
        my_store = InstrumentedTransportStore(MockTransport())
        my_store.add(stream, "foo")
        self.assertEqual([("_add", "foo", stream)], my_store._calls)

    def test_add_prefixed(self):
        stream = StringIO("content")
        my_store = InstrumentedTransportStore(MockTransport(), True)
        my_store.add(stream, "foo")
        self.assertEqual([("_add", "45/foo", stream)], my_store._calls)

    def test_add_simple_suffixed(self):
        stream = StringIO("content")
        my_store = InstrumentedTransportStore(MockTransport())
        my_store.register_suffix('dsc')
        my_store.add(stream, "foo", 'dsc')
        self.assertEqual([("_add", "foo.dsc", stream)], my_store._calls)
        
    def test_add_simple_suffixed(self):
        stream = StringIO("content")
        my_store = InstrumentedTransportStore(MockTransport(), True)
        my_store.register_suffix('dsc')
        my_store.add(stream, "foo", 'dsc')
        self.assertEqual([("_add", "45/foo.dsc", stream)], my_store._calls)

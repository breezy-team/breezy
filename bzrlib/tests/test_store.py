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
import gzip

from bzrlib.errors import BzrError, UnlistableStore
from bzrlib.store import copy_all
from bzrlib.transport.local import LocalTransport
from bzrlib.transport import NoSuchFile
from bzrlib.store.text import TextStore
from bzrlib.tests import TestCase, TestCaseInTempDir
import bzrlib.store as store
import bzrlib.transport as transport
from bzrlib.transport.memory import MemoryTransport


class TestStores(object):
    """Mixin template class that provides some common tests for stores"""

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
        return TextStore(t, compressed=True)

    def test_total_size(self):
        store = self.get_store('.')
        store.register_suffix('dsc')
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123', 'dsc')
        # these get gzipped - content should be stable
        self.assertEqual(store.total_size(), (2, 55))
        
    def test__relpath_suffixed(self):
        my_store = TextStore(MockTransport(), True, compressed=True)
        my_store.register_suffix('dsc')
        self.assertEqual('45/foo.dsc', my_store._relpath('foo', ['dsc']))


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
        return TextStore(t, compressed=False)

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


class TestMixedTextStore(TestCaseInTempDir, TestStores):

    def get_store(self, path='.', compressed=True):
        t = LocalTransport(path)
        return TextStore(t, compressed=compressed)

    def test_get_mixed(self):
        cs = self.get_store('.', compressed=True)
        s = self.get_store('.', compressed=False)
        cs.add(StringIO('hello there'), 'a')

        self.failUnlessExists('a.gz')
        self.failIf(os.path.lexists('a'))

        self.assertEquals(gzip.GzipFile('a.gz').read(), 'hello there')

        self.assertEquals(cs.has_id('a'), True)
        self.assertEquals(s.has_id('a'), True)
        self.assertEquals(cs.get('a').read(), 'hello there')
        self.assertEquals(s.get('a').read(), 'hello there')
        
        self.assertRaises(BzrError, s.add, StringIO('goodbye'), 'a')

        s.add(StringIO('goodbye'), 'b')
        self.failUnlessExists('b')
        self.failIf(os.path.lexists('b.gz'))
        self.assertEquals(open('b').read(), 'goodbye')

        self.assertEquals(cs.has_id('b'), True)
        self.assertEquals(s.has_id('b'), True)
        self.assertEquals(cs.get('b').read(), 'goodbye')
        self.assertEquals(s.get('b').read(), 'goodbye')
        
        self.assertRaises(BzrError, cs.add, StringIO('again'), 'b')

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
        my_store.register_suffix('bar')
        my_store.register_suffix('baz')
        self.assertEqual('foo.baz', my_store._relpath('foo', ['baz']))
        self.assertEqual('foo.bar.baz', my_store._relpath('foo', ['bar', 'baz']))

    def test__relpath_prefixed_suffixed(self):
        my_store = store.TransportStore(MockTransport(), True)
        my_store.register_suffix('bar')
        my_store.register_suffix('baz')
        self.assertEqual('45/foo.baz', my_store._relpath('foo', ['baz']))
        self.assertEqual('45/foo.bar.baz',
                         my_store._relpath('foo', ['bar', 'baz']))

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

    def get_populated_store(self, prefixed=False,
            store_class=TextStore, compressed=False):
        my_store = store_class(MemoryTransport(), prefixed,
                               compressed=compressed)
        my_store.register_suffix('sig')
        stream = StringIO("signature")
        my_store.add(stream, "foo", 'sig')
        stream = StringIO("content")
        my_store.add(stream, "foo")
        stream = StringIO("signature for missing base")
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
        my_store = TextStore(MemoryTransport(), False, compressed=False)
        stream = StringIO("content")
        my_store.add(stream, "foo")
        self.assertEqual(set(['foo']),
                         set(my_store.__iter__()))

    def test___iter__(self):
        self.assertEqual(set(['foo']),
                         set(self.get_populated_store().__iter__()))
        self.assertEqual(set(['foo']),
                         set(self.get_populated_store(True).__iter__()))

    def test___iter__compressed(self):
        self.assertEqual(set(['foo']),
                         set(self.get_populated_store(
                             compressed=True).__iter__()))
        self.assertEqual(set(['foo']),
                         set(self.get_populated_store(
                             True, compressed=True).__iter__()))

    def test___len__(self):
        self.assertEqual(1, len(self.get_populated_store()))

    def test_copy_suffixes(self):
        from_store = self.get_populated_store()
        to_store = TextStore(MemoryTransport(), True, compressed=True)
        to_store.register_suffix('sig')
        copy_all(from_store, to_store)
        self.assertEqual(1, len(to_store))
        self.assertEqual(set(['foo']), set(to_store.__iter__()))
        self.assertEqual('content', to_store.get('foo').read())
        self.assertEqual('signature', to_store.get('foo', 'sig').read())
        self.assertRaises(KeyError, to_store.get, 'missing', 'sig')

    def test_relpath_escaped(self):
        my_store = store.TransportStore(MemoryTransport())
        self.assertEqual('%25', my_store._relpath('%'))

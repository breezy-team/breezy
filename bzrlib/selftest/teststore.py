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


def fill_store(store):
    store.add(StringIO('hello'), 'a')
    store.add(StringIO('other'), 'b')
    store.add(StringIO('something'), 'c')
    store.add(StringIO('goodbye'), '123123')


def check_equals(tester, store, files, values, permit_failure=False):
    files = store.get(files, permit_failure=permit_failure)
    count = 0
    for f, v in zip(files, values):
        count += 1
        if v is None:
            tester.assert_(f is None)
        else:
            tester.assertEquals(f.read(), v)
    tester.assertEquals(count, len(values))
    # We need to check to make sure there are no more
    # files to be returned, I'm using a cheezy way
    # Convert to a list, and there shouldn't be any left
    tester.assertEquals(len(list(files)), 0)


def test_multiple_add(tester, store):
    fill_store(store)
    tester.assertRaises(BzrError, store.add, StringIO('goodbye'), '123123')


def test_get(tester, store):
    fill_store(store)

    check_equals(tester, store, ['a'], ['hello'])
    check_equals(tester, store, ['b', 'c'], ['other', 'something'])

    # Make sure that requesting a non-existing file fails
    tester.assertRaises(NoSuchFile, check_equals, tester, store,
            ['d'], [None])
    tester.assertRaises(NoSuchFile, check_equals, tester, store,
            ['a', 'd'], ['hello', None])
    tester.assertRaises(NoSuchFile, check_equals, tester, store,
            ['d', 'a'], [None, 'hello'])
    tester.assertRaises(NoSuchFile, check_equals, tester, store,
            ['d', 'd', 'd'], [None, None, None])
    tester.assertRaises(NoSuchFile, check_equals, tester, store,
            ['a', 'd', 'b'], ['hello', None, 'other'])


def test_ignore_get(tester, store):
    fill_store(store)

    files = store.get(['d'], permit_failure=True)
    files = list(files)
    tester.assertEquals(len(files), 1)
    tester.assert_(files[0] is None)

    check_equals(tester, store, ['a', 'd'], ['hello', None],
            permit_failure=True)
    check_equals(tester, store, ['d', 'a'], [None, 'hello'],
            permit_failure=True)
    check_equals(tester, store, ['d', 'd'], [None, None],
            permit_failure=True)
    check_equals(tester, store, ['a', 'd', 'b'], ['hello', None, 'other'],
            permit_failure=True)
    check_equals(tester, store, ['a', 'd', 'b'], ['hello', None, 'other'],
            permit_failure=True)
    check_equals(tester, store, ['b', 'd', 'c'], ['other', None, 'something'],
            permit_failure=True)


def get_compressed_store(path='.'):
    t = LocalTransport(path)
    return CompressedTextStore(t)


def get_text_store(path='.'):
    t = LocalTransport(path)
    return TextStore(t)


class TestCompressedTextStore(TestCaseInTempDir):

    def test_multiple_add(self):
        """Multiple add with same ID should raise a BzrError"""
        store = get_compressed_store()
        test_multiple_add(self, store)

    def test_get(self):
        store = get_compressed_store()
        test_get(self, store)

    def test_ignore_get(self):
        store = get_compressed_store()
        test_ignore_get(self, store)

    def test_total_size(self):
        store = get_compressed_store('.')
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123.dsc')
        # these get gzipped - content should be stable
        self.assertEqual(store.total_size(), (2, 55))
        
    def test_copy_all(self):
        """Test copying"""
        os.mkdir('a')
        store_a = get_text_store('a')
        store_a.add('foo', '1')
        os.mkdir('b')
        store_b = get_text_store('b')
        copy_all(store_a, store_b)
        self.assertEqual(store_a['1'].read(), 'foo')
        self.assertEqual(store_b['1'].read(), 'foo')


class TestMemoryStore(TestCase):
    
    def get_store(self):
        return store.ImmutableMemoryStore()
    
    def test_imports(self):
        from bzrlib.store import ImmutableMemoryStore

    def test_add_and_retrieve(self):
        store = self.get_store()
        store.add(StringIO('hello'), 'aa')
        self.assertNotEqual(store['aa'], None)
        self.assertEqual(store['aa'].read(), 'hello')
        store.add(StringIO('hello world'), 'bb')
        self.assertNotEqual(store['bb'], None)
        self.assertEqual(store['bb'].read(), 'hello world')

    def test_missing_is_absent(self):
        store = self.get_store()
        self.failIf('aa' in store)

    def test_adding_fails_when_present(self):
        my_store = self.get_store()
        my_store.add(StringIO('hello'), 'aa')
        self.assertRaises(store.StoreError,
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


class TestTextStore(TestCaseInTempDir):
    def test_multiple_add(self):
        """Multiple add with same ID should raise a BzrError"""
        store = get_text_store()
        test_multiple_add(self, store)

    def test_get(self):
        store = get_text_store()
        test_get(self, store)

    def test_ignore_get(self):
        store = get_text_store()
        test_ignore_get(self, store)

    def test_copy_all(self):
        """Test copying"""
        os.mkdir('a')
        store_a = get_text_store('a')
        store_a.add('foo', '1')
        os.mkdir('b')
        store_b = get_text_store('b')
        copy_all(store_a, store_b)
        self.assertEqual(store_a['1'].read(), 'foo')
        self.assertEqual(store_b['1'].read(), 'foo')
        # TODO: Switch the exception form UnlistableStore to
        #       or make Stores throw UnlistableStore if their
        #       Transport doesn't support listing
        # store_c = RemoteStore('http://example.com/')
        # self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class MockTransport(transport.Transport):
    """A fake transport for testing with."""

    def __init__(self, url=None):
        if url is None:
            url = "http://example.com"
        super(MockTransport, self).__init__(url)


class TestMockTransport(TestCase):

    def test_isinstance(self):
        self.failUnless(isinstance(MockTransport(), transport.Transport))


class TestTransportStore(TestCase):
    
    def test__relpath_invalid(self):
        my_store = store.TransportStore(MockTransport())
        self.assertRaises(ValueError, my_store._relpath, '/foo')
        self.assertRaises(ValueError, my_store._relpath, 'foo/')

    def test__relpath_simple(self):
        my_store = store.TransportStore(MockTransport())
        self.assertEqual("foo", my_store._relpath('foo'))

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

"""Test Store implementation
"""
from bzrlib.transport.local import LocalTransport
from bzrlib.transport import NoSuchFile
from bzrlib.store.compressed_text import CompressedTextStore
from bzrlib.selftest import TestCaseInTempDir
from StringIO import StringIO
from bzrlib.errors import BzrError

def fill_store(store):
    store.add(StringIO('hello'), 'a')
    store.add(StringIO('other'), 'b')
    store.add(StringIO('something'), 'c')
    store.add(StringIO('goodbye'), '123123')

def check_equals(tester, store, files, values, ignore_missing=False):
    files = store.get(files, ignore_missing=ignore_missing)
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

    files = store.get(['d'], ignore_missing=True)
    files = list(files)
    tester.assertEquals(len(files), 1)
    tester.assert_(files[0] is None)

    check_equals(tester, store, ['a', 'd'], ['hello', None],
            ignore_missing=True)
    check_equals(tester, store, ['d', 'a'], [None, 'hello'],
            ignore_missing=True)
    check_equals(tester, store, ['d', 'd'], [None, None],
            ignore_missing=True)
    check_equals(tester, store, ['a', 'd', 'b'], ['hello', None, 'other'],
            ignore_missing=True)
    check_equals(tester, store, ['a', 'd', 'b'], ['hello', None, 'other'],
            ignore_missing=True)
    check_equals(tester, store, ['b', 'd', 'c'], ['other', None, 'something'],
            ignore_missing=True)

def get_compressed_store():
    t = LocalTransport('.')
    return CompressedTextStore(t)

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


TEST_CLASSES = [
    TestCompressedTextStore,
    ]
